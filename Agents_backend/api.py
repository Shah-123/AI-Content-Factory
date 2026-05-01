"""
api.py — FastAPI web application for the AI Content Factory.

This replaces the CLI as the primary entry point. The existing
LangGraph pipeline (main.py / build_graph) is invoked via
FastAPI BackgroundTasks so generation runs asynchronously while
the WebSocket endpoint streams live agent events to the browser.

Start with:
    cd Agents_backend
    uvicorn api:app --reload --reload-exclude "data/*" --host 0.0.0.0 --port 8000
"""

import os
import sys
import json
import asyncio
import threading
import logging
from pathlib import Path
from typing import Any

# ── ensure the backend dir is on sys.path ──────────────────────────────────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── FastAPI ─────────────────────────────────────────────────────────────────
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Internal imports ─────────────────────────────────────────────────────────
from db import create_job, get_job, list_jobs, update_job, set_job_running, \
               set_job_awaiting_approval, set_job_completed, set_job_failed
import event_bus as events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

# ── Thread-safe containers for HITL approval signals ──────────────────────
# Maps job_id → asyncio.Event that fires when the user approves the plan
_approval_events: dict[str, asyncio.Event] = {}
# Maps job_id → revised plan dict (or None for approve-as-is)
_plan_revisions: dict[str, Any] = {}
# Maps job_id → threading.Event for the worker thread to await
_worker_approval_events: dict[str, threading.Event] = {}

# ============================================================================
# APP
# ============================================================================

app = FastAPI(title="AI Content Factory API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── serve static frontend ──────────────────────────────────────────────────
_FRONTEND = _HERE.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")
else:
    logger.warning(f"Frontend directory not found at {_FRONTEND}. UI will not be available.")


@app.on_event("startup")
async def startup():
    events.start_cleanup_task()


@app.on_event("shutdown")
async def shutdown():
    events.stop_cleanup_task()


# ============================================================================
# ROOT → index.html
# ============================================================================

@app.get("/")
async def root():
    index = _FRONTEND / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"status": "AI Content Factory API running"})


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class CreateJobRequest(BaseModel):
    topic: str
    tone: str = "professional"
    sections: int = 3
    generate_podcast: bool = False
    generate_video: bool = False
    generate_campaign: bool = False


class RevisePlanRequest(BaseModel):
    feedback: str


# ============================================================================
# BACKGROUND WORKER
# ============================================================================

def _run_pipeline(job_id: str, topic: str, tone: str, sections: int,
                  generate_podcast: bool, generate_video: bool,
                  generate_campaign: bool, worker_event: threading.Event):
    """
    Runs the full LangGraph pipeline in a background thread.
    Emits events to the event_bus so the WebSocket can relay them.
    """
    try:
        # Late import so api.py can load without OPENAI_API_KEY set
        from dotenv import load_dotenv
        load_dotenv(_HERE.parent / ".env")

        import os as _os
        if not _os.getenv("OPENAI_API_KEY"):
            raise EnvironmentError("OPENAI_API_KEY not set in .env")

        # ── Import pipeline pieces ────────────────────────────────────────
        from main import (
            build_graph, create_blog_structure, save_blog_content,
            generate_readme, refine_plan_with_llm
        )
        from datetime import date

        # ── Folder structure ──────────────────────────────────────────────
        folders = create_blog_structure(topic)
        set_job_running(job_id, folders["base"])

        events.emit(job_id, "system", "started",
                    f"Pipeline started for: {topic}", {"blog_folder": folders["base"]})

        # ── Build graph ───────────────────────────────────────────────────
        graph = build_graph()
        import uuid as _uuid
        thread_cfg = {"configurable": {"thread_id": f"job_{_uuid.uuid4().hex[:12]}"}}

        initial_state = {
            "topic":             topic,
            "as_of":             date.today().isoformat(),
            "sections":          [],
            "blog_folder":       folders["base"],
            "target_tone":       tone,
            "target_keywords":   [],
            "target_sections":   sections,
            "generate_images":   False,
            "generate_qa":       False,
            "generate_campaign": generate_campaign,
            "generate_video":    generate_video,
            "generate_podcast":  generate_podcast,
            "export_formats":    ["html"],
            "_job_id":           job_id,
        }

        # ── Phase 1: Research & Planning ──────────────────────────────────
        events.emit(job_id, "router", "working", "Analyzing topic and routing to agents...")
        for _ in graph.stream(initial_state, thread_cfg, stream_mode="values"):
            pass

        # ── HITL: surface the plan to the frontend ────────────────────────
        state = graph.get_state(thread_cfg).values
        plan  = state.get("plan")
        if plan:
            plan_dict = plan.model_dump()
            set_job_awaiting_approval(job_id, json.dumps(plan_dict))
            events.emit(job_id, "orchestrator", "plan_ready",
                        "Blog plan ready for approval.", {"plan": plan_dict})

            # Wait for user approval (up to 20 minutes)
            logger.info(f"⏳ Job {job_id}: Awaiting HITL plan approval...")
            approved = worker_event.wait(timeout=1200)
            if not approved:
                logger.error(f"❌ Job {job_id}: Plan approval timed out after 20 minutes.")
                raise TimeoutError("HITL plan approval timed out")

            # Apply any revision
            revised = _plan_revisions.pop(job_id, None)
            if revised is not None:
                new_plan = refine_plan_with_llm(plan, revised)
                graph.update_state(thread_cfg, {"plan": new_plan})
                events.emit(job_id, "orchestrator", "plan_revised",
                            "Plan updated based on your feedback.")

            events.emit(job_id, "orchestrator", "plan_approved", "Plan approved. Starting writing phase...")

        # ── Phase 2: Write & Produce ──────────────────────────────────────
        events.emit(job_id, "writer", "working", "Writing blog sections...")
        for _ in graph.stream(None, thread_cfg, stream_mode="values", recursion_limit=150):
            pass

        # ── Save outputs ──────────────────────────────────────────────────
        final_state = graph.get_state(thread_cfg).values
        saved       = save_blog_content(folders, final_state)
        generate_readme(folders, saved, final_state)

        # Read the blog content for serving via API
        final_content = final_state.get("final", "")
        
        # We store relative paths in the DB to work with the /api/files endpoint
        blog_relative = os.path.relpath(saved["blog"], folders["base"]) if saved.get("blog") else None
        html_relative = os.path.relpath(saved["blog_html"], folders["base"]) if saved.get("blog_html") else None
        podcast_relative = os.path.relpath(saved["podcast"], folders["base"]) if saved.get("podcast") else None
        video_relative = os.path.relpath(saved["video"], folders["base"]) if saved.get("video") else None

        set_job_completed(
            job_id,
            qa_score             = final_state.get("qa_score"),
            qa_verdict           = final_state.get("qa_verdict"),
            blog_evaluator_score = final_state.get("blog_evaluator_score"),
            blog_file            = blog_relative,
            blog_html_file       = html_relative,
            podcast_file         = podcast_relative,
            video_file           = video_relative,
            word_count           = len(final_content.split()),
            final_content        = final_content,
            social_linkedin      = final_state.get("linkedin_post", ""),
            social_twitter       = final_state.get("twitter_thread", ""),
        )

        events.emit(job_id, "system", "completed",
                    "Blog generation complete!",
                    {
                        "qa_score": final_state.get("qa_score"),
                        "blog_evaluator_score": final_state.get("blog_evaluator_score"),
                        "blog_folder": folders["base"],
                    })

    except Exception as exc:
        logger.exception(f"Pipeline failed for job {job_id}: {exc}")
        set_job_failed(job_id, str(exc))
        events.emit(job_id, "system", "error", f"Generation failed: {exc}")


# ============================================================================
# API ROUTES
# ============================================================================

@app.post("/api/jobs")
async def create_new_job(req: CreateJobRequest, background_tasks: BackgroundTasks):
    """Start a blog generation job."""
    job = create_job(
        topic            = req.topic,
        tone             = req.tone,
        sections         = req.sections,
        generate_podcast = req.generate_podcast,
        generate_video   = req.generate_video,
        generate_campaign= req.generate_campaign,
    )
    job_id = job["id"]

    # Create threading.Event for HITL synchronisation with the worker thread
    worker_event = threading.Event()
    _worker_approval_events[job_id] = worker_event

    background_tasks.add_task(
        _run_pipeline,
        job_id           = job_id,
        topic            = req.topic,
        tone             = req.tone,
        sections         = req.sections,
        generate_podcast = req.generate_podcast,
        generate_video   = req.generate_video,
        generate_campaign= req.generate_campaign,
        worker_event     = worker_event,
    )
    return job


@app.get("/api/jobs")
async def list_all_jobs():
    """Return all jobs, newest-first."""
    return list_jobs()


@app.get("/api/jobs/{job_id}")
async def get_job_details(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}/blog")
async def get_blog_content(job_id: str):
    """Return the raw markdown blog content."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    content = job.get("final_content") or ""
    if not content and job.get("blog_file"):
        try:
            content = Path(job["blog_file"]).read_text(encoding="utf-8")
        except Exception:
            pass
    return {"content": content, "format": "markdown"}


@app.get("/api/jobs/{job_id}/approve-plan")
async def approve_plan(job_id: str):
    """Signal HITL approval — unblocks the worker thread."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    _plan_revisions[job_id] = None  # no revision — straight approve
    worker_event = _worker_approval_events.get(job_id)
    if worker_event:
        worker_event.set()
    update_job(job_id, status="running")
    return {"status": "approved"}


@app.post("/api/jobs/{job_id}/revise-plan")
async def revise_plan(job_id: str, req: RevisePlanRequest):
    """Submit feedback and unblock the worker to apply revision."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    _plan_revisions[job_id] = req.feedback
    worker_event = _worker_approval_events.get(job_id)
    if worker_event:
        worker_event.set()
    update_job(job_id, status="running")
    return {"status": "revision_queued"}


@app.get("/api/jobs/{job_id}/qa-report")
async def get_qa_report(job_id: str):
    """Return the QA report text for a completed job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    report_text = ""
    if job.get("blog_folder"):
        report_path = Path(job["blog_folder"]) / "reports" / "qa_report.txt"
        if report_path.exists():
            report_text = report_path.read_text(encoding="utf-8")
    return {"report": report_text}


@app.get("/api/files/{job_id}/{filepath:path}")
async def serve_file(job_id: str, filepath: str):
    """Serve any file from a job's blog folder."""
    job = get_job(job_id)
    if not job or not job.get("blog_folder"):
        raise HTTPException(404, "Job not found")
    full_path = Path(job["blog_folder"]) / filepath
    if not full_path.exists():
        raise HTTPException(404, f"File not found: {filepath}")
    return FileResponse(str(full_path))


# ============================================================================
# MANUAL TASKS (Decoupled generation)
# ============================================================================

def _run_manual_task(job_id: str, task_name: str):
    """Runs a specific decoupled media or QA task on a completed blog."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_HERE.parent / ".env")
        
        from main import save_blog_content
        from Graph.nodes import (
            decide_images, generate_and_place_images,
            video_generator_node, podcast_node,
            campaign_generator_node, qa_agent_node,
            revision_node
        )

        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        base_path = job["blog_folder"]
        meta_path = Path(base_path) / "metadata" / "metadata.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        blog_path_str = meta.get("file_paths", {}).get("blog")
        if blog_path_str and Path(blog_path_str).exists():
            blog_path = Path(blog_path_str)
        else:
            content_dir = Path(base_path) / "content"
            md_files = list(content_dir.glob("*.md")) if content_dir.exists() else []
            if md_files:
                blog_path = md_files[0]
            else:
                md_files = list(Path(base_path).glob("*.md"))
                if md_files:
                    blog_path = md_files[0]
                else:
                    raise FileNotFoundError(f"Could not locate blog markdown file in {base_path}")

        with open(blog_path, "r", encoding="utf-8") as f:
            final_md = f.read()

        from Graph.state import Plan
        plan_path = Path(base_path) / "metadata" / "plan.json"
        plan_obj = None
        if plan_path.exists():
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
                plan_obj = Plan(**plan_data)

        state = {
            "topic": meta.get("topic", "Unknown"),
            "target_tone": meta.get("target_tone", "professional"),
            "target_keywords": meta.get("target_keywords", []),
            "merged_md": final_md,
            "final": final_md,
            "blog_folder": base_path,
            "_job_id": job_id,
            "qa_verdict": meta.get("qa_verdict", "READY"),
            "qa_score": meta.get("qa_score", 0),
            "qa_issues": [],
            "revision_count": 0,
            "qa_fixed_claims": [],
            "plan": plan_obj
        }

        events.emit(job_id, task_name, "started", f"Starting manual {task_name}...")

        updates = {}
        if task_name == "images":
            state.update(decide_images(state))
            state.update(generate_and_place_images(state))
        elif task_name == "video":
            video_path = Path(base_path) / "video" / "short.mp4"
            if job.get("video_file") or video_path.exists():
                events.emit(job_id, task_name, "completed", "Video already exists. Skipping.")
                # Self-heal DB if it exists on disk but not in DB
                if not job.get("video_file"):
                    update_job(job_id, video_file=f"video/short.mp4")
                return
            state.update(video_generator_node(state))
        elif task_name == "podcast":
            podcast_path = Path(base_path) / "audio" / "podcast.mp3"
            if job.get("podcast_file") or podcast_path.exists():
                events.emit(job_id, task_name, "completed", "Podcast already exists. Skipping.")
                if not job.get("podcast_file"):
                    update_job(job_id, podcast_file=f"audio/podcast.mp3")
                return
            state.update(podcast_node(state))
        elif task_name == "campaign":
            if job.get("social_linkedin") or job.get("social_twitter"):
                events.emit(job_id, task_name, "completed", "Social media already exists. Skipping.")
                return
            state.update(campaign_generator_node(state))
            updates["social_linkedin"] = state.get("linkedin_post", "")
            updates["social_twitter"] = state.get("twitter_thread", "")
        elif task_name == "qa":
            state.update(qa_agent_node(state))
            if state.get("qa_verdict") == "NEEDS_REVISION":
                state.update(revision_node(state))
                # Optional: score again after revision
                state.update(qa_agent_node(state))
            
            updates["qa_score"] = state.get("qa_score")
            updates["qa_verdict"] = state.get("qa_verdict")
            updates["final_content"] = state.get("final")

        # Create folders dict required for save_blog_content
        folders = {
            "base": base_path,
            "content": f"{base_path}/content",
            "social": f"{base_path}/social_media",
            "reports": f"{base_path}/reports",
            "assets": f"{base_path}/assets/images",
            "research": f"{base_path}/research",
            "audio": f"{base_path}/audio",
            "video": f"{base_path}/video",
            "metadata": f"{base_path}/metadata"
        }

        # Ensure all folders exist
        for folder_path in folders.values():
            os.makedirs(folder_path, exist_ok=True)
        
        # Save output artifacts
        saved = {}
        try:
            saved = save_blog_content(folders, state)
        except Exception as save_err:
            logger.warning(f"save_blog_content failed ({save_err}), falling back to direct DB update")
        
        # Update relative paths for media files in the database
        if saved.get("video"):
            updates["video_file"] = os.path.relpath(saved["video"], base_path)
        elif state.get("video_path") and os.path.exists(state["video_path"]):
            # Fallback: if save_blog_content failed but the video file exists
            video_rel = os.path.relpath(state["video_path"], base_path)
            updates["video_file"] = video_rel

        if saved.get("podcast"):
            updates["podcast_file"] = os.path.relpath(saved["podcast"], base_path)
        elif state.get("podcast_audio_path") and os.path.exists(state["podcast_audio_path"]):
            podcast_rel = os.path.relpath(state["podcast_audio_path"], base_path)
            updates["podcast_file"] = podcast_rel
            
        if "final" in state:
            updates["final_content"] = state["final"]
            updates["blog_file"] = os.path.relpath(saved["blog"], base_path) if saved.get("blog") else None
            updates["blog_html_file"] = os.path.relpath(saved["blog_html"], base_path) if saved.get("blog_html") else None
        
        if updates:
            update_job(job_id, **updates)

        events.emit(job_id, "system", "completed", f"{task_name.capitalize()} completed successfully.")
        
    except Exception as exc:
        logger.exception(f"Manual {task_name} failed: {exc}")
        events.emit(job_id, "system", "error", f"{task_name} failed: {exc}")

@app.post("/api/jobs/{job_id}/generate-images")
async def manual_images(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_manual_task, job_id, "images")
    return {"status": "started", "task": "images"}

@app.post("/api/jobs/{job_id}/generate-video")
async def manual_video(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_manual_task, job_id, "video")
    return {"status": "started", "task": "video"}

@app.post("/api/jobs/{job_id}/generate-podcast")
async def manual_podcast(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_manual_task, job_id, "podcast")
    return {"status": "started", "task": "podcast"}

@app.post("/api/jobs/{job_id}/generate-social")
async def manual_social(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_manual_task, job_id, "campaign")
    return {"status": "started", "task": "campaign"}

@app.post("/api/jobs/{job_id}/run-qa")
async def manual_qa(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_manual_task, job_id, "qa")
    return {"status": "started", "task": "qa"}

# ============================================================================
# WEBSOCKET
# ============================================================================

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Stream agent events to the browser in real-time."""
    await websocket.accept()
    queue = events.subscribe(job_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                try:
                    await websocket.send_json(event)
                except Exception:
                    # Connection closed or error sending
                    break
                # Only close on FINAL completion (system agent) or any error
                if event.get("status") == "error" or (
                    event.get("agent_name") == "system"
                    and event.get("status") == "completed"
                ):
                    await asyncio.sleep(0.5)
                    break
            except asyncio.TimeoutError:
                # Send a keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for job {job_id}")
    finally:
        events.unsubscribe(job_id, queue)
        try:
            from starlette.websockets import WebSocketState
            if websocket.application_state != WebSocketState.DISCONNECTED:
                await websocket.close()
        except Exception:
            pass
