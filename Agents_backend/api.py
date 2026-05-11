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

# ── Load .env BEFORE any agent module is imported, otherwise ChatOpenAI
#    instantiated at import-time in Graph.agents.utils will fail with
#    "OPENAI_API_KEY not set" on the first /api/trending call.
from dotenv import load_dotenv
load_dotenv(_HERE.parent / ".env")

# ── FastAPI ─────────────────────────────────────────────────────────────────
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
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
# Maps job_id → directly edited Plan object from the outline editor
_direct_plan_updates: dict[str, Any] = {}
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
    audience: str = "general"
    sections: int = 3
    generate_podcast: bool = False
    generate_video: bool = False
    generate_campaign: bool = False
    generate_qa: bool = True
    # — Document upload (optional) —
    upload_id: str | None = None
    source_mode: str = "hybrid"   # "closed_book" | "hybrid" | "auto_topic"


class RevisePlanRequest(BaseModel):
    feedback: str


class UpdatePlanRequest(BaseModel):
    """Accepts a directly-edited plan from the frontend outline editor."""
    blog_title: str
    tone: str = "professional"
    audience: str = "general"
    tasks: list[dict]  # Each dict has: title, goal, bullets, target_words, tags


# ============================================================================
# BACKGROUND WORKER
# ============================================================================

def _run_pipeline(job_id: str, topic: str, tone: str, audience: str,
                  sections: int, generate_podcast: bool, generate_video: bool,
                  generate_campaign: bool, generate_qa: bool,
                  worker_event: threading.Event,
                  upload_id: str | None = None,
                  source_mode: str = "hybrid"):
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
            "target_audience":   audience,
            "target_keywords":   [],
            "target_sections":   sections,
            "generate_images":   False,
            "generate_qa":       generate_qa,
            "generate_campaign": generate_campaign,
            "generate_video":    generate_video,
            "generate_podcast":  generate_podcast,
            "export_formats":    ["html"],
            "_job_id":           job_id,
            # — Document upload —
            "upload_id":         upload_id or "",
            "source_mode":       source_mode,
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

            # Apply direct plan edit or LLM-based revision
            from Graph.agents.orchestrator import _assign_evidence_to_tasks
            evidence = state.get("evidence", [])

            direct_plan = _direct_plan_updates.pop(job_id, None)
            revised = _plan_revisions.pop(job_id, None)

            if direct_plan is not None:
                # User directly edited the outline — use their plan as-is
                new_plan = direct_plan
                if evidence:
                    new_plan = _assign_evidence_to_tasks(new_plan, evidence)
                graph.update_state(thread_cfg, {"plan": new_plan})
                # Update the stored plan in DB so frontend stays in sync
                set_job_awaiting_approval(job_id, json.dumps(new_plan.model_dump()))
                events.emit(job_id, "orchestrator", "plan_revised",
                            "Plan updated with your direct edits.")
            elif revised is not None:
                new_plan = refine_plan_with_llm(plan, revised)
                # ✅ FIX: Re-assign evidence to the revised plan's tasks
                if evidence:
                    new_plan = _assign_evidence_to_tasks(new_plan, evidence)
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
    finally:
        _worker_approval_events.pop(job_id, None)


# ============================================================================
# API ROUTES
# ============================================================================

# ── Document uploads ──────────────────────────────────────────────────────
import uuid as _uuid_mod

_UPLOADS_ROOT = _HERE / "uploads"
_UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
_SUPPORTED_UPLOAD_EXTS = {".pdf", ".docx", ".txt", ".md"}
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


def _safe_upload_name(name: str) -> str:
    """Strip path components and disallow risky characters in filenames."""
    base = os.path.basename(name or "")
    # Replace anything outside [A-Za-z0-9._-] with underscore
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    return cleaned or "upload"


@app.post("/api/uploads")
async def upload_document(file: UploadFile = File(...)):
    """Accept a single document, parse it, extract evidence, and persist
    everything under uploads/<upload_id>/. Returns metadata the frontend
    needs to wire the upload to a subsequent /api/jobs request.
    """
    filename = _safe_upload_name(file.filename or "upload")
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_format",
                "reason": f"File type '{ext or '?'}' is not supported.",
                "supported": sorted(_SUPPORTED_UPLOAD_EXTS),
            },
        )

    # Stream the upload into the chosen folder while enforcing the size cap.
    upload_id = _uuid_mod.uuid4().hex
    upload_dir = _UPLOADS_ROOT / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / filename

    bytes_written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB at a time
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_UPLOAD_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    upload_dir.rmdir()
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error": "file_too_large",
                            "reason": f"Maximum upload size is {_MAX_UPLOAD_BYTES // (1024*1024)} MB.",
                        },
                    )
                out.write(chunk)
    finally:
        await file.close()

    # Heavy work: parse → chunk → LLM-extract evidence. Off the event loop.
    try:
        from Graph.agents.document_ingest import ingest_upload
        meta = await asyncio.to_thread(ingest_upload, upload_dir, filename)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Upload ingest failed for {upload_id}: {exc}")
        # Clean up partial state so a retry doesn't accumulate junk.
        try:
            for child in upload_dir.iterdir():
                child.unlink(missing_ok=True)
            upload_dir.rmdir()
        except OSError:
            pass
        raise HTTPException(
            status_code=422,
            detail={"error": "ingest_failed", "reason": str(exc)},
        )

    return {
        "upload_id": upload_id,
        "filename": meta.get("filename", filename),
        "format": meta.get("format"),
        "bytes": bytes_written,
        "pages": meta.get("pages", 0),
        "chunks": meta.get("chunks", 0),
        "chunks_processed": meta.get("chunks_processed", 0),
        "evidence_count": meta.get("evidence_count", 0),
        "truncated": meta.get("truncated", False),
        "derived_topic": meta.get("derived_topic", ""),
        "preview": meta.get("preview", ""),
    }


@app.get("/api/uploads/{upload_id}")
async def get_upload(upload_id: str):
    """Return previously computed metadata for an upload, or 404."""
    # Defend against path traversal — only accept simple uuid-like strings.
    if not upload_id or any(c in upload_id for c in "/\\.:"):
        raise HTTPException(status_code=400, detail="Invalid upload_id.")
    upload_dir = _UPLOADS_ROOT / upload_id
    if not upload_dir.exists():
        raise HTTPException(status_code=404, detail="Upload not found.")
    from Graph.agents.document_ingest import load_upload_metadata
    meta = load_upload_metadata(upload_dir)
    if not meta:
        raise HTTPException(status_code=404, detail="Upload metadata missing.")
    return {"upload_id": upload_id, **meta}


@app.post("/api/jobs")
async def create_new_job(req: CreateJobRequest, background_tasks: BackgroundTasks):
    """Start a blog generation job."""
    # ── Pre-flight Topic Guard ────────────────────────────────────────────
    # Reject unsafe / nonsensical topics BEFORE creating a job or burning
    # any pipeline tokens. Run in a worker thread so the synchronous LLM
    # call doesn't block the FastAPI event loop.
    from Graph.agents.topic_guard import evaluate_topic
    verdict = await asyncio.to_thread(evaluate_topic, req.topic)
    if not verdict.is_safe:
        logger.warning(
            f"Topic rejected by guard: '{req.topic[:80]}' "
            f"(category={verdict.category}) — {verdict.reason}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "topic_rejected",
                "category": verdict.category,
                "reason": verdict.reason,
                "suggested_topic": verdict.suggested_topic,
            },
        )

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
        job_id            = job_id,
        topic             = req.topic,
        tone              = req.tone,
        audience          = req.audience,
        sections          = req.sections,
        generate_podcast  = req.generate_podcast,
        generate_video    = req.generate_video,
        generate_campaign = req.generate_campaign,
        generate_qa       = req.generate_qa,
        worker_event      = worker_event,
        upload_id         = req.upload_id,
        source_mode       = req.source_mode,
    )
    return job


@app.get("/api/jobs")
async def list_all_jobs():
    """Return all jobs, newest-first."""
    return list_jobs()


# ── Trending topics (cached for 1 hour) ──────────────────────────────────
import time as _time
_trending_cache: dict[str, Any] = {"topics": [], "expires_at": 0.0}
_TRENDING_TTL_SECONDS = 3600  # refresh hourly
_trending_lock = asyncio.Lock()

@app.get("/api/trending")
async def get_trending():
    """Return 4 LLM-suggested trending blog topics for the dashboard empty state."""
    now = _time.time()
    if _trending_cache["topics"] and _trending_cache["expires_at"] > now:
        return {"topics": _trending_cache["topics"], "cached": True}

    async with _trending_lock:
        # Double-check after acquiring lock
        if _trending_cache["topics"] and _trending_cache["expires_at"] > _time.time():
            return {"topics": _trending_cache["topics"], "cached": True}

        try:
            from Graph.agents.trending import get_trending_topics
            topics = await asyncio.to_thread(get_trending_topics)
            _trending_cache["topics"] = topics
            _trending_cache["expires_at"] = _time.time() + _TRENDING_TTL_SECONDS
            return {"topics": topics, "cached": False}
        except Exception as e:
            logger.exception(f"Trending topics endpoint failed: {e}")
            # Always return something so the frontend never breaks
            return {"topics": [
                "AI agents in 2026",
                "Building scalable RAG systems",
                "Multi-modal LLMs explained",
                "The future of voice AI",
            ], "cached": False, "fallback": True}


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


@app.post("/api/jobs/{job_id}/update-plan")
async def update_plan_direct(job_id: str, req: UpdatePlanRequest):
    """Accept a directly-edited plan from the outline editor and unblock the worker."""
    from Graph.state import Plan, Task

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Rebuild Task list with sequential IDs and safe defaults
    tasks = []
    for i, t in enumerate(req.tasks):
        tasks.append(Task(
            id=i,
            title=t.get("title", f"Section {i + 1}"),
            goal=t.get("goal", ""),
            bullets=t.get("bullets", []),
            target_words=t.get("target_words", 350),
            tags=t.get("tags", []),
            assigned_evidence_indices=[],  # will be re-assigned by the worker thread
        ))

    new_plan = Plan(
        blog_title=req.blog_title,
        tone=req.tone,
        audience=req.audience,
        tasks=tasks,
        primary_keywords=job.get("plan", {}).get("primary_keywords", []) if job.get("plan") else [],
        keyword_strategy=job.get("plan", {}).get("keyword_strategy", "") if job.get("plan") else "",
    )

    _direct_plan_updates[job_id] = new_plan
    worker_event = _worker_approval_events.get(job_id)
    if worker_event:
        worker_event.set()
    update_job(job_id, status="running")
    return {"status": "plan_updated", "sections": len(tasks)}


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
    base = Path(job["blog_folder"]).resolve()
    full_path = (base / filepath).resolve()
    if not str(full_path).startswith(str(base)):
        raise HTTPException(403, "Invalid path")
    if not full_path.exists():
        raise HTTPException(404, f"File not found: {filepath}")
    return FileResponse(str(full_path))


# ============================================================================
# MANUAL TASKS (Decoupled generation)
# ============================================================================

# Per-job lock to protect metadata.json writes from concurrent tasks
_job_file_locks: dict[str, threading.Lock] = {}


def _get_job_lock(job_id: str) -> threading.Lock:
    """Get or create a threading lock for a specific job's file operations."""
    if job_id not in _job_file_locks:
        _job_file_locks[job_id] = threading.Lock()
    return _job_file_locks[job_id]


def _update_metadata_json(meta_path: Path, updates: dict, job_lock: threading.Lock):
    """Thread-safe read-modify-write of metadata.json.

    Only merges the provided keys into the existing metadata, so
    concurrent tasks (video, podcast, campaign) never clobber each
    other's entries.
    """
    with job_lock:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        # Merge top-level keys
        for k, v in updates.items():
            if k == "file_paths" and isinstance(v, dict):
                # Deep-merge file_paths so each task only adds its own entry
                meta.setdefault("file_paths", {}).update(v)
            else:
                meta[k] = v
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)


def _run_manual_task(job_id: str, task_name: str):
    """Runs a specific decoupled media or QA task on a completed blog.

    Media tasks (video, podcast, campaign) save ONLY their own artifact
    and do a surgical DB + metadata update — they never call the heavy
    save_blog_content() function. This makes them safe to run in parallel.

    Content-modifying tasks (images, qa) still use save_blog_content()
    because they rewrite the blog markdown, but they acquire a per-job
    file lock to prevent concurrent metadata corruption.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(_HERE.parent / ".env")

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

        job_lock = _get_job_lock(job_id)

        # ── Ensure output directories exist ─────────────────────────────
        for sub in ("content", "social_media", "reports", "assets/images",
                     "research", "audio", "video", "metadata"):
            os.makedirs(Path(base_path) / sub, exist_ok=True)

        # ==================================================================
        # MEDIA TASKS — lightweight, concurrency-safe, no save_blog_content
        # ==================================================================

        if task_name == "video":
            video_out = Path(base_path) / "video" / "short.mp4"
            if job.get("video_file") or video_out.exists():
                events.emit(job_id, task_name, "completed", "Video already exists. Skipping.")
                if not job.get("video_file"):
                    update_job(job_id, video_file="video/short.mp4")
                return
            state.update(video_generator_node(state))
            # Save the video file to the correct location
            import shutil
            if state.get("video_path") and os.path.exists(state["video_path"]):
                dest = str(video_out)
                try:
                    if not os.path.samefile(state["video_path"], dest):
                        shutil.copy(state["video_path"], dest)
                except (OSError, ValueError):
                    shutil.copy(state["video_path"], dest)
            # Surgical DB update — only touch the video column
            rel = "video/short.mp4"
            update_job(job_id, video_file=rel)
            _update_metadata_json(meta_path, {"file_paths": {"video": str(video_out)}}, job_lock)
            events.emit(job_id, "system", "completed", "Video completed successfully.")
            return

        if task_name == "podcast":
            podcast_out = Path(base_path) / "audio" / "podcast.wav"
            podcast_mp3 = Path(base_path) / "audio" / "podcast.mp3"
            if job.get("podcast_file") or podcast_out.exists() or podcast_mp3.exists():
                events.emit(job_id, task_name, "completed", "Podcast already exists. Skipping.")
                if not job.get("podcast_file"):
                    ext = "podcast.mp3" if podcast_mp3.exists() else "podcast.wav"
                    update_job(job_id, podcast_file=f"audio/{ext}")
                return
            state.update(podcast_node(state))
            # Save the podcast file to the correct location
            import shutil
            if state.get("podcast_audio_path") and os.path.exists(state["podcast_audio_path"]):
                dest = str(podcast_out)
                try:
                    if not os.path.samefile(state["podcast_audio_path"], dest):
                        shutil.copy(state["podcast_audio_path"], dest)
                except (OSError, ValueError):
                    shutil.copy(state["podcast_audio_path"], dest)
            # Surgical DB update — only touch the podcast column
            rel = "audio/podcast.wav"
            update_job(job_id, podcast_file=rel)
            _update_metadata_json(meta_path, {"file_paths": {"podcast": str(podcast_out)}}, job_lock)
            events.emit(job_id, "system", "completed", "Podcast completed successfully.")
            return

        if task_name == "campaign":
            if job.get("social_linkedin") or job.get("social_twitter"):
                events.emit(job_id, task_name, "completed", "Social media already exists. Skipping.")
                return
            state.update(campaign_generator_node(state))
            # Save social media text files
            slug = plan_obj.blog_title.replace(" ", "_").lower()[:50] if plan_obj else "blog"
            social_dir = Path(base_path) / "social_media"
            if state.get("linkedin_post"):
                (social_dir / f"linkedin_{slug}.txt").write_text(state["linkedin_post"], encoding="utf-8")
            if state.get("twitter_thread"):
                (social_dir / f"twitter_{slug}.md").write_text(state["twitter_thread"], encoding="utf-8")
            # Surgical DB update — only touch social columns
            update_job(
                job_id,
                social_linkedin=state.get("linkedin_post", ""),
                social_twitter=state.get("twitter_thread", ""),
            )
            events.emit(job_id, "system", "completed", "Campaign completed successfully.")
            return

        # ==================================================================
        # CONTENT-MODIFYING TASKS — use save_blog_content with file lock
        # ==================================================================

        from main import save_blog_content

        updates = {}

        if task_name == "images":
            state.update(decide_images(state))
            state.update(generate_and_place_images(state))

        elif task_name == "qa":
            state.update(qa_agent_node(state))
            if state.get("qa_verdict") == "NEEDS_REVISION":
                state.update(revision_node(state))
                state.update(qa_agent_node(state))
            updates["qa_score"] = state.get("qa_score")
            updates["qa_verdict"] = state.get("qa_verdict")
            updates["final_content"] = state.get("final")

        # Build folders dict for save_blog_content
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

        saved = {}
        with job_lock:
            try:
                saved = save_blog_content(folders, state)
            except Exception as save_err:
                logger.warning(f"save_blog_content failed ({save_err}), falling back to direct DB update")

        if saved.get("blog"):
            updates["blog_file"] = os.path.relpath(saved["blog"], base_path)
        if saved.get("blog_html"):
            updates["blog_html_file"] = os.path.relpath(saved["blog_html"], base_path)
        if task_name == "images" and "final" in state:
            updates["final_content"] = state["final"]

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

    # Count how many events were pre-loaded (replayed from disk history).
    # We must NOT close the WebSocket when replaying a historical
    # "system:completed" event — only close on a LIVE one.
    replay_remaining = queue.qsize()

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                is_replay = replay_remaining > 0
                if is_replay:
                    replay_remaining -= 1

                try:
                    await websocket.send_json(event)
                except Exception:
                    # Connection closed or error sending
                    break

                # Only close on LIVE (non-replayed) terminal events
                if not is_replay:
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

