# AI Content Factory: Viva Preparation Guide & System Reference Manual

This document is a comprehensive technical guide and reference manual designed to help you prepare for your Final Year Project (FYP) Viva. It explains every directory, file, and data property in detail, highlighting the core architectural patterns (stateful LangGraph coordination, parallel workers, Human-in-the-Loop, and G-Eval/DeepEval LLM-as-judge scoring) that examiners are likely to ask about.

---

## 🗺️ Table of Contents
1. [Section 1: System Architecture Overview (The Big Picture)](#section-1-system-architecture-overview-the-big-picture)
2. [Section 2: LangGraph State & Data Schemas (state.py)](#section-2-langgraph-state-data-schemas-statepy)
3. [Section 3: The Multi-Agent Roster (Node-by-Node Explanation)](#section-3-the-multi-agent-roster-node-by-node-explanation)
4. [Section 4: Backend Infrastructure & Live Streaming](#section-4-backend-infrastructure-live-streaming)
5. [Section 5: Frontend React & UI Architecture](#section-5-frontend-react-ui-architecture)
6. [Section 6: Viva Defense Cheat Sheet & Q&A](#section-6-viva-defense-cheat-sheet-qa)

---

## Section 1: System Architecture Overview (The Big Picture)

To succeed in your viva, you must be able to explain **why** this system is built this way, not just **what** it does. This section outlines the key architectural paradigms of your project.

### 1. Why a Multi-Agent Architecture?
In a standard single-prompt LLM setup, the model must handle research, structure planning, drafting, revision, SEO keyword optimization, and multi-modal generation in one go. This leads to:
- **Context Drift**: The LLM loses track of early instructions.
- **Hallucinations**: The model tries to generate facts it doesn't know without a verification step.
- **Role Confusion**: A single prompt cannot easily balance the creative writing style of a blogger with the strict correctness of a fact-checking auditor.

By dividing the system into specialized, coordinated **Agents** (Topic Guard, Router, Researcher, Orchestrator, Worker, QA Auditor, SEO Optimizer, Evaluator, and Media Generators), you enforce:
- **Separation of Concerns**: Each agent runs on a specialized system prompt, keeping them highly focused.
- **Optimized Compute Costs**: Most nodes use the fast, cheap `gpt-4o-mini`, while expensive models like `gpt-4o` or deep evaluation runs (`deepeval`) are reserved only for critical scoring nodes.
- **Modular Debugging**: You can test, refine, or swap any single agent (e.g., changing the Researcher to search a local database instead of Tavily) without breaking the rest of the application.

### 2. Why LangGraph over crewAI or AutoGen?
Examiners frequently ask: *"Why did you use LangGraph instead of standard sequential LangChain or agent frameworks like crewAI?"*
- **Cyclical Graph Native**: Frameworks like crewAI are mostly linear or hierarchy-based. LangGraph models workflows as **state charts (cyclic graphs)**. This is crucial for your **Revision Loop** where the QA Auditor can route the state *back* to the Revision Agent multiple times until the draft is approved.
- **Explicit State Control**: LangGraph stores all system data in a centralized, type-safe `State` schema (defined in [state.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/state.py)). Agents do not pass messages directly to each other; instead, they read from the global state and write updates back to it.
- **Stateful Resumption & Checkpointer**: LangGraph includes native support for **Checkpointers** (`MemorySaver` or `SqliteSaver`). The system saves a snapshot of the entire `State` after each node runs. If a network call fails, or a server crashes, the system does not need to restart from the beginning; it can resume execution from the exact database snapshot of the last successful node.
- **First-Class Human-in-the-Loop (HITL)**: LangGraph supports interrupting the graph execution programmatically (e.g., using `interrupt_after=["orchestrator"]`). This halts the background state execution, allowing the system to wait for UI input, then resume with the updated state.

### 3. The Core System Pipeline (The DAG)
The workflow is divided into five main phases:
```
[Phase 1: Ingestion & Planning]
Topic Guard ➔ Router ➔ Document Ingest / Tavily Research ➔ Orchestrator (Outline Plan)
                                                                 │
                                                       [HITL: Plan Approved?]
                                                                 │
[Phase 2: Parallel Writing]                                      ▼
Worker 0 (H2 Section 0) ──┐
Worker 1 (H2 Section 1) ──┼➔ Reducer Node (Merges Draft & Decides Image Slots)
Worker N (H2 Section N) ──┘
                                                                 │
[Phase 3: QA & Revision Loop]                                    ▼
       ┌────────────────────── qa_verdict == "NEEDS_REVISION" ── QA Auditor Node
       ▼                                                         │
Revision Agent Node ─────────────────────────────────────────────┘
                                                                 │
                                                        qa_verdict == "READY"
                                                                 │
[Phase 4: Optimization]                                          ▼
SEO Keyword Optimizer ➔ Academic Evaluators (G-Eval / DeepEval)
                                                                 │
[Phase 5: Multi-Modal Output]                                    ▼
Campaign Gen | Video Gen (MoviePy) | Podcast Gen (Gemini Audio) ➔ Save files & README
```

### 4. Asynchronous Request Lifecycle
A common viva question is: *"How does the React frontend interact with the python backend during execution?"*
1. **Trigger**: The user sends a request from the React UI to the FastAPI endpoint ([api/routes/jobs.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/api/routes/jobs.py)).
2. **Background Thread**: The API controller inserts a job record into the SQLite database ([db.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/db.py)) and triggers the LangGraph compilation in an asynchronous FastAPI background task (`api/background.py`).
3. **Execution & Event Streaming**: As the graph executes node-by-node, the system intercepts node operations and emits structured progress logs to the `EventBus` ([event_bus.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/event_bus.py)).
4. **WebSocket Connection**: The React frontend connects to a persistent WebSocket channel (`/api/ws/{job_id}`). The event bus serializes the progress events and pushes them down the socket in real-time, allowing the user's console/chat feed to show immediate updates (e.g., "Researcher complete", "Writing Section 2...").
5. **HITL Interrupt**: When the graph reaches the orchestrator node, it hits the `interrupt_after` rule. The backend saves the thread state, updates the job status to `paused`, and notifies the frontend.
6. **Resumption**: The user edits the outline on the React interface and submits the final plan. The frontend calls `/api/jobs/{job_id}/resume`, which writes the updated plan back to the thread and triggers `app.stream(None, thread)` to resume from the paused state.

---


## Section 2: LangGraph State & Data Schemas (state.py)

In [state.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/state.py), you define the data contracts that govern how models outputs are structured and how the graph remembers information.

### 1. Pydantic Models (Structured LLM Outputs)
These schemas are used with `llm.with_structured_output(Model)` to force the LLM to output clean JSON matching a strict validation schema instead of freeform text.

- **`RouterDecision`**:
  - `needs_research` (`bool`): Determines whether the pipeline needs web research.
  - `mode` (`str`): Options are `'closed_book'` (direct writing), `'open_book'` (reading uploaded docs), or `'hybrid'` (docs + web search).
  - `queries` (`List[str]`): Pre-generated Tavily search queries if research is required.
  - `reason` (`str`): Justification for the routing decision.
- **`EvidenceItem`**:
  - Represents a single piece of retrieved information (web page slice or document chunk).
  - Contains fields: `title`, `url`, `snippet` (actual text excerpt), `published_at`, `source` (domain name), and `authors`.
- **`Task`**:
  - Represents a single section H2 block.
  - Contains fields: `id`, `title`, `goal`, `bullets`, `target_words`, and `tags`.
  - **`assigned_evidence_indices` (`List[int]`)**: *Critical Property.* The orchestrator maps specific research evidence index ranges to individual sections. This ensures workers write with relevant constraints, preventing two parallel workers from using and repeating the exact same facts or citations.
- **`Plan`**:
  - Contains fields: `blog_title`, `tone`, `audience`, `tasks` (list of `Task` objects), `primary_keywords`, and `keyword_strategy`.
- **`ImageSpec` / `GlobalImagePlan`**:
  - Defines where and how to generate images.
  - `target_paragraph`: The first 5 words of the paragraph after which to insert the image.
  - `filename`: Dashed-slug filename.
  - `prompt`: Detailed prompt for Gemini Image Generator.
  - `alt`: Accessibility alt text.
  - `caption`: Visual caption shown below the image.

---

### 2. Central Graph State Properties
The central memory is represented by the `State` TypedDict. It stores all transient variables passed between nodes:

| State Property | Type | Description |
| :--- | :--- | :--- |
| `topic` | `str` | The user's input topic. |
| `as_of` | `str` | System execution date (to guide temporal queries). |
| `blog_folder` | `str` | Absolute path of the output folder for this run. |
| `target_tone` | `str` | Chosen tone parameter (e.g. `"professional"`, `"technical"`). |
| `target_keywords` | `List[str]` | Target SEO keywords. |
| `target_sections` | `int` | The count of body sections (excluding intro and outline). |
| `upload_id` | `Optional[str]` | The ID of any uploaded grounding documents. |
| `source_mode` | `Optional[str]` | Source configuration: `"closed_book"`, `"hybrid"`, or `"auto_topic"`. |
| `evidence` | `List[EvidenceItem]` | Shared list of all parsed or scraped research references. |
| `plan` | `Plan` | The structure of the article (approved plan). |
| **`sections`** | **`Annotated[List[tuple], operator.add]`** | *Key Viva Topic: The Reducer.* |
| `merged_md` | `str` | Plain merged markdown text. |
| `md_with_placeholders` | `str` | Markdown text with `[[IMAGE_X]]` slots. |
| `final` | `str` | The finalized post. |
| `qa_verdict` | `str` | Auditor verdict: `"READY"` or `"NEEDS_REVISION"`. |
| `revision_count` | `int` | Loop counter to prevent infinite revision cycles (max 2). |
| `qa_fixed_claims` | `List[str]` | Tracks claims already revised so the auditor doesn't loop forever on them. |
| `blog_evaluator_score` | `float` | In-house average quality score (0.0 to 10.0). |
| `geval_scores` | `Optional[dict]` | G-Eval structured metrics (1.0 to 5.0 scale). |
| `deepeval_scores` | `Optional[dict]` | Official DeepEval framework metrics (0.0 to 1.0 scale). |
| `video_path` / `podcast_audio_path` | `Optional[str]` | Saved output paths for MP4 shorts and WAV podcasts. |

#### 💡 The Reducer Concept: `Annotated[List[tuple], operator.add]`
If examiners ask: *"How did you handle concurrent writes to the same state when workers run in parallel?"*
In LangGraph, if multiple nodes write to a standard key, the last one to finish will overwrite the others (Write Conflict).
By using `Annotated[List[tuple], operator.add]`, you register a **Reducer**. When parallel worker threads return their drafted sections, LangGraph intercepts their updates and applies `operator.add` (list concatenation) to combine their results into a single list of tuples, rather than overwriting. This enables clean multi-agent fan-out and fan-in.

---

## Section 3: The Multi-Agent Roster (Node-by-Node Explanation)

The multi-agent orchestration is implemented in individual Python modules within `Agents_backend/Graph/agents/` and [podcast_studio.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/podcast_studio.py). System prompts governing agent behaviors are centralized in [templates.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/templates.py).

Here is the exact technical breakdown of each agent module and its internal functions:

### 1. Topic Guard Agent ([topic_guard.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/topic_guard.py))
- **Role**: Serves as a pre-flight safety filter to prevent token/cost spend on junk or unsafe inputs.
- **Key Functions**:
  - `_trivial_reject(topic)`: Quick deterministic checks. Rejects empty, too short (< 3 chars), or trivial strings (`"test"`, `"hello"`, `"hi"`) without LLM calls.
  - `evaluate_topic(topic)`: Invokes `gpt-4o-mini` with `TopicGuardVerdict` schema to classify the input. Categories include `self_harm`, `illegal`, `misinformation`, `hate`, `nonsense`, or `ok`. 
  - **Defense Tip**: Explain that this node *fails open* on API/network errors (returns `is_safe=True`) so a flaky API key doesn't block legitimate users.

### 2. Router Agent ([routing.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/routing.py))
- **Role**: Analyzes the topic and determines the context retrieval strategy.
- **Key Functions**:
  - `router_node(state)`: Uses `RouterDecision` schema to determine whether external research is needed (`needs_research`), selects the Mode (`closed_book`, `open_book`, or `hybrid`), and configures the temporal query range (`recency_days`).
  - **Design detail**: Sets `recency_days = 7` (news) for `open_book`, `45` (recent trends) for `hybrid`, and `3650` (10 years, historical) for `closed_book`.

### 3. Deep Research Agent ([research.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/research.py))
- **Role**: Executes web searches, filters duplicate info, scrapes full pages, and extracts structured facts.
- **Key Functions & Optimization**:
  - `_tavily_search(query, max_results, recency_days)`: Queries Tavily Search using the router-defined `recency_days` parameter.
  - `_is_near_duplicate(snippet, seen_fingerprints)`: Runs a **Jaccard Similarity** calculation ($overlap\_words / union\_words$) on text fingerprints. If the word overlap is $\ge 65\%$ (`_DUPLICATE_SIMILARITY_THRESHOLD`), it is flagged as a near-duplicate and skipped. This prevents syndication spam.
  - `scrape_full_webpage(url)`: Visits URLs concurrently. It tries **Jina Reader API** (`https://r.jina.ai/`) first to convert pages to clean Markdown, falling back to `BeautifulSoup` (`scrape_full_webpage_fallback`) on error.
  - `research_node(state)`: Coordinates the research lifecycle. Uses a **`ThreadPoolExecutor`** to query 5 Tavily searches and scrape up to 15 articles in parallel. Finally, invokes the LLM with `EvidencePack` schema to extract 8-10 hard facts.

### 4. Document Ingest / RAG Agent ([document_ingest.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/document_ingest.py))
- **Role**: Ingests, chunks, embeds, and queries user-uploaded documents (PDFs, DOCX, TXT, MD) using Advanced semantic search.
- **Key Logic**:
  - **Sentence-Level Embeddings**: Uses OpenAI's `text-embedding-3-small` model.
  - **Semantic Chunking**: Splits text into paragraphs, embeds sentences, and merges them based on similarity thresholds to create coherent chunks instead of arbitrary word cuts.
  - **Retrieval**: Performs cosine similarity search between the topic vector and document chunk vectors to retrieve grounding evidence.

### 5. Orchestrator Agent ([orchestrator.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/orchestrator.py))
- **Role**: Structures the global blog outline (`Plan` and `Task` lists).
- **Key Functions**:
  - `orchestrator_node(state)`: Prompts the LLM with the overall topic, tone, keywords, and retrieved evidence to build the H2 sections.
  - `_assign_evidence_to_tasks(plan, evidence)`: *Key Innovation.* Distributes specific evidence item indices to matching tasks. For example, if Section 2 is about "AI diagnosis", the orchestrator assigns only evidence pieces discussing medical scans to it. This forces Workers to draw from different data slices, solving duplicate-fact repetition across the blog.

### 6. Parallel Workers & Merger Node ([workers.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/workers.py))
- **Role**: Generates body sections in parallel (fan-out) and merges them back in chronological order (fan-in).
- **Key Functions**:
  - `fanout(state)`: Resolves to multiple parallel `Send("worker", payload)` calls, one for each H2 outline task.
  - `worker_node(payload)`: Individual section drafting. It inputs the section title, goal, target keywords, bullets, and *only* the assigned evidence slice. Strips rogue markdown H1 titles, verifies sentence completion, and checks word counts. Returns `{"sections": [(task_id, content)]}`.
  - `merge_content(state)`: Reassembles the sections. Unpacks tuples, maps them to their respective `task_id` indexes to sort them chronologically, and logs any missing worker sections.

### 7. Quality Control Auditor Agent ([quality_control.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/quality_control.py))
- **Role**: Evaluates the merged draft for accuracy, structural alignment, and citation truth.
- **Key Functions**:
  - `verify_citations(blog_text, evidence)`: *Automated Outbound Link Check.* Parses all markdown URLs (`[text](url)`) in the text. Matches the domains/urls against the search evidence. If a worker invented a citation link, this method flags it as a `critical` hallucination issue.
  - `qa_agent_node(state)`: Invokes the LLM with `QAReport` schema (score, strengths, issues, verdict). It feeds the auditor the draft (up to 30,000 chars), the evidence list, and previous revision counts. If critical issues are found, it sets `qa_verdict = "NEEDS_REVISION"`.

### 8. Revision Agent ([revision.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/revision.py))
- **Role**: Surgical correction of drafts to address issues raised by the QA Auditor.
- **Key Functions**:
  - `revision_node(state)`: Instructs the LLM to rewrite *only* the parts flagged by the QA Auditor.
  - **Loop Gate**: Integrates `MAX_REVISIONS = 2` to prevent infinite feedback loops. It writes fixed claims into `qa_fixed_claims` so the auditor doesn't re-flag them in the next pass.

### 9. SEO Keyword Optimizer Agent ([keyword_optimizer.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/keyword_optimizer.py))
- **Role**: Integrates target SEO keywords naturally without keyword-stuffing.
- **Key Functions**:
  - `keyword_optimizer_node(state)`: Evaluates keyword density, checks keyword placements in headers, and edits paragraphs to merge keywords seamlessly, returning a keyword density report.

### 10. Academic Evaluation Agent ([evaluation.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/evaluation.py))
- **Role**: Academic quality grading using LLM-as-judge rubrics.
- **Key Nodes**:
  - `geval_evaluation_node(state)`: Custom evaluator node that rates the blog from 1.0 to 5.0 on four core rubrics (Coherence, Relevance, Accuracy, Tone Alignment).
  - `deepeval_evaluation_node(state)`: Uses Confident AI's `deepeval` library to execute G-Eval metrics (Liu et al. 2023) using the official packages. Runs on-demand to save costs.

### 11. Multi-Modal Studio Nodes ([campaign.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/campaign.py), [video.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/video.py), [podcast_studio.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/podcast_studio.py))
- **Campaign Node**: Generates copy files (LinkedIn, Facebook, YouTube script, Twitter thread, emails, landing page).
- **Video Node**: Parses the blog summary, queries stock video footages via the **Pexels API** based on keywords, downloads short MP4 files, uses Text-to-Speech (TTS) for the script voiceover, and compiles an MP4 short with synchronized subtitle overlays using **MoviePy**.
- **Podcast Node**: Interfaces with the `google-genai` SDK to run Gemini 2.5 Flash with native audio generation (`response_modalities=["AUDIO"]`), outputting a natural `.wav` voice file containing conversational pacing.

---

## Section 4: Backend Infrastructure & Live Streaming

The backend infrastructure provides SQLite persistence, real-time WebSocket progress streaming, input validations, and CLI/API execution modes.

### 1. FastAPI Web API Server (`api/` and `api/main.py`)
FastAPI serves as the entry point for the frontend, executing LangGraph workflows in background threads.
- **`POST /api/jobs`** ([api/routes/jobs.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/api/routes/jobs.py)): Receives the topic, tone, and active assets toggles, creates a new job record in the database, and schedules `run_app()` inside a FastAPI `BackgroundTask` running on a separate thread.
- **`GET /api/jobs/{id}`**: Retrieves the current status, text, files, and scores of a job.
- **`POST /api/jobs/{id}/resume`**: Feeds plan adjustments into the checkpointer state and resumes a paused graph.
- **`/api/ws/{id}`** ([api/routes/websocket.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/api/routes/websocket.py)): Persistent connection that subscribes to the event bus and streams agent logs down to the React frontend.

---

### 2. SQLite Job Database ([db.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/db.py))
The database manages job states, metadata, scores, and markdown strings. 
- **PRAGMA Optimizations**: 
  - `PRAGMA journal_mode=WAL;` (Write-Ahead Logging)
  - `PRAGMA synchronous=NORMAL;`
  - **viva Explanation**: These optimizations are crucial for a multi-threaded system. WAL mode allows concurrent read operations while another thread is writing to the database, preventing database-locking exceptions when FastAPI queries the database while the LangGraph thread updates it.
- **Job Row Schema**:
  - `id` (`TEXT PRIMARY KEY`): Unique job UUID.
  - `status` (`TEXT`): Track states: `'pending'`, `'running'`, `'awaiting_approval'`, `'completed'`, or `'failed'`.
  - `plan_json` (`TEXT`): Serialized JSON of the approved section outline.
  - `final_content` (`TEXT`): The final generated blog post.
  - `geval_scores`, `deepeval_scores` (`TEXT`): Serialized evaluation scorecards.
  - `podcast_file`, `video_file` (`TEXT`): Local paths to the generated multimedia files.

---

### 3. Asynchronous Event Bus & Streaming (`event_bus.py`)
The event bus handles real-time agent activity tracking and ensures the UI matches the backend state.
- **Data Contract (`AgentEvent`)**:
  - Contains fields: `job_id`, `agent_name`, `status` (`'started'`, `'working'`, `'completed'`, `'error'`), `message`, `timestamp`, and `metrics`.
- **Thread Safety & Loop Bridging**:
  - LangGraph runs inside a background worker thread. FastAPI runs the WebSocket loop inside the main asyncio event loop.
  - The `emit()` function uses **`loop.call_soon_threadsafe()`** to schedule UI event deliveries. Because asyncio's `Queue.put_nowait()` is not thread-safe, calling it from a background thread would corrupt the loop state. `call_soon_threadsafe()` bridges this cross-thread barrier.
- **🩹 Self-Healing Mechanism (`_heal_stuck_events`)**:
  - If the FastAPI server crashes or restarts, ongoing jobs would show as perpetually running on the UI (stuck spins).
  - When a user connects or queries job history, `_heal_stuck_events()` scans the persistent `.jsonl` log file. If it finds a task that was marked as `"started"` but is no longer active in memory, it inserts a recovery event (`"Task aborted (server restarted or crashed)"`) to clean the UI state.

---

### 4. CLI Execution and Core Orchestration ([main.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/main.py))
- **Graph Construction (`build_graph()`)**:
  - Wires all agent nodes together using a `StateGraph(State)`.
  - Registers the memory Saver checkpointer (`MemorySaver`).
  - Calls `workflow.compile(checkpointer=memory, interrupt_after=["orchestrator"])`. The checkpointer acts as a state store, saving a snapshot before hitting the HITL outline interrupt.
- **Folder Scaffolding (`create_blog_structure()`)**:
  - Sanitizes the input topic to generate a safe slug and directory tree under `blogs/{topic}_{timestamp}/`.
  - Creates segregated folders: `/content`, `/social_media`, `/reports`, `/assets/images`, `/research`, `/audio`, and `/video`.
- **CLI Mode**: Runs the same pipeline inside terminal prompts if executed with `python main.py`.

---

### 5. Pre-flight Validation Filters ([validators.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/validators.py))
- Runs before the graph executes to check for topic length, character safety, and baseline semantic properties.

---

## Section 5: Frontend React & UI Architecture

The frontend is a single-page application built on React 19, TypeScript, and Vite. It communicates with the backend via REST endpoints and a real-time WebSocket connection to stream and render agent outputs.

### 1. Root Layout & State Orchestrator ([App.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/App.tsx))
- **Role**: Manages the sidebar navigation, layout structures, tab choices, and global active states (e.g. current job selection, theme states).
- **Key Logic**:
  - Handles polling lists of historical blogs.
  - Controls toggling between different main tabs: "Console Log Feed", "Final Markdown Blog", "Media Center (Podcast/Video)", and "Academic Evaluation Scorecard".

### 2. Live WebSocket Console ([components/ChatView.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/components/ChatView.tsx))
- **Role**: Connects to the backend WebSocket port and displays live terminal logs and agent node statuses.
- **Key Logic**:
  - Connects to `/api/ws/{job_id}`.
  - Appends incoming JSON packets (AgentEvents) in chronological order to render a scroll-locked terminal screen.
  - Translates statuses (started, working, completed, error) into visual signals (e.g., green checkmark for completed, flashing indicators for working).

### 3. Human-in-the-Loop Outline Editor ([components/PlanEditor.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/components/PlanEditor.tsx))
- **Role**: Rendered only when the backend job status is `'awaiting_approval'`. It lets users inspect and restructure the outline before any writing begins.
- **Key Features**:
  - Displays the blog H1 title and tone.
  - Renders section cards representing `Task` items where the user can modify H2 headers, bullet-points targets, and target word counts.
  - **Refine Prompt Form**: Includes a natural language text field. If the user types *"Add a section about future trends"* and clicks Refine, it makes a POST request to `/refine` with the feedback string. The backend triggers the LLM editor to restructure the Plan object, updates the SQLite DB, and returns the modified plan to the UI.
  - **Approve Action**: Once approved, calls the `/resume` endpoint, returning control to the backend to spawn the parallel Workers node.

### 4. Rich Article Viewer ([ContentView.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/frontend/src/ContentView.tsx))
- **Role**: Renders the final outputs.
- **Key Sections**:
  - **Blog Preview**: Renders Markdown strings using standard formatting with placed images.
  - **SEO Keyword Panel**: Displays keyword density maps and distribution audits.
  - **Academic Evaluations Tab**: Displays side-by-side G-Eval scorecards (Coherence, Relevance, Accuracy, Tone Alignment) complete with progress bars, scores, and text reasoning logs.

### 5. Media Studio Player ([MediaView.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/MediaView.tsx))
- **Role**: Dedicated player for generated assets.
- **Key Features**:
  - **Video Player**: Native HTML5 player pointing to `/api/uploads/short.mp4` with interactive controls.
  - **Podcast Player**: Renders an audio wave visualizer and audio player pointing to `/api/uploads/podcast.wav` to playback Gemini's synthesized voiceover.

### 6. Upload Integration Chip ([components/UploadChip.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/components/UploadChip.tsx))
- **Role**: Coordinates the ingestion of PDF, DOCX, TXT, and Markdown reference files.
- **Key Logic**:
  - Sends files to `POST /api/uploads`. Once uploaded, passes the resulting `upload_id` into the job parameters, forcing the backend graph to execute the Document Ingestion RAG node before planning.

---

## Section 6: Viva Defense Cheat Sheet & Q&A

This section compile the 10 most common, challenging, and technical questions examiners are likely to ask during your defense, along with precise answers referencing your codebase.

### Q1: What is LangGraph, and why did you use it instead of LangChain or crewAI?
* **Answer**: LangChain is excellent for linear, chain-of-thought sequences, but it struggles with cyclical loops. crewAI is ideal for role-playing hierarchies but abstracts away graph-edge control. LangGraph compiles workflows into a state machine represented as a **Directed Acyclic Graph (DAG) or Cyclical Graph**. We chose it because:
  1. **Native Loops**: Our *Revision Loop* requires routing state back from the QA Auditor to the Revision Agent iteratively.
  2. **State Control**: Centralizes memory in a type-safe `State` dictionary ([state.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/state.py)).
  3. **Checkpointer Support**: Natively saves database snapshots (`SqliteSaver`) at every node.
  4. **First-class interrupts**: Enables Human-in-the-Loop review of our outline before writing.

### Q2: Explain the "MapReduce" or "Fan-out / Fan-in" writing pattern in workers.py. How do you handle concurrent state writes?
* **Answer**: 
  - **Fan-out (Map)**: In [main.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/main.py), once the orchestrator completes, a conditional edge invokes `fanout()` in [workers.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/workers.py). This returns a list of `Send("worker", payload)` instructions. LangGraph schedules and runs these worker nodes in parallel on separate threads.
  - **The State Reducer**: Normally, if parallel workers write to the same key, they overwrite each other. In [state.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/state.py), we register the reducer `sections: Annotated[List[tuple], operator.add]`. The `operator.add` tells LangGraph to concatenate (append) the worker tuples `(task_id, content)` into a single list as they complete.
  - **Fan-in (Reduce)**: The `merge_content` node receives the accumulated list, unpacks and sorts the tuples chronologically by their `task_id`, and merges them into the final blog post.

### Q3: How did you solve the problem of parallel workers repeating the same facts or citations?
* **Answer**: In standard RAG systems, sending the entire document index to all parallel workers causes them to independently select the same 2-3 prominent statistics, repeating them across different sections. We solved this in [orchestrator.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/orchestrator.py) using the `_assign_evidence_to_tasks()` method. The orchestrator maps specific indices of our global `evidence` array to individual outline tasks. The `fanout` node reads these indices and forwards only the assigned slice to each worker via `_get_assigned_evidence_dicts()`, ensuring workers draw from distinct facts.

### Q4: How does your Human-in-the-Loop (HITL) outline editor work?
* **Answer**: 
  1. We compile the graph using `workflow.compile(checkpointer=memory, interrupt_after=["orchestrator"])` in [main.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/main.py).
  2. When execution completes the orchestrator node, LangGraph interrupts execution, serializes the current state to the checkpointer database, and updates the SQLite status to `'awaiting_approval'`.
  3. The frontend displays [PlanEditor.tsx](file:///d:/Multi_Agent_Blog_generator_FYP/frontend/src/components/PlanEditor.tsx). If the user edits a section or inputs natural language feedback, the backend calls `refine_plan_with_llm()` to update the outline.
  4. Once approved, the frontend hits `/resume`, which updates the checkpointer state and triggers `app.stream(None, thread)` with `None` input, directing the graph to resume from the paused checkpoint.

### Q5: How does your Quality Control (QC) agent audit claims and prevent hallucinated outbound links?
* **Answer**: The QC auditor combines programmatic verification and semantic evaluation:
  1. **Citation Link Verifier**: The `verify_citations()` method in [quality_control.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/quality_control.py) scans the draft for markdown links (`[text](url)`). It extracts the domains and matches them against the domains of the verified research evidence. If a link domain is not in the source evidence list, it flags it as a critical hallucination.
  2. **LLM Fact Auditor**: We prompt `gpt-4o` with the draft and the research evidence using a structured `QAReport` output schema. It maps fact inaccuracies or flow issues, returning a verdict (`"READY"` or `"NEEDS_REVISION"`).

### Q6: How do you prevent infinite loops between the Quality Control and Revision nodes?
* **Answer**: We enforce two guardrails:
  1. **Revision Limit**: The conditional router `_after_qa_manual()` in [main.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/main.py) reads the state's `revision_count` and compares it against `MAX_REVISIONS = 2` (defined in [revision.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/revision.py)). If the limit is reached, it bypasses the revision agent.
  2. **Audit Memory**: The state tracks `qa_fixed_claims`. When the revision agent rewrites a paragraph, it appends the resolved issue to this list. During the next QA audit, these fixed claims are fed back as instructions to the auditor, preventing it from re-flagging already-resolved issues.

### Q7: Explain your LLM-as-judge evaluation approach. Why do you have two evaluator nodes?
* **Answer**: We evaluate the blog post across four academic rubrics (Coherence, Relevance, Accuracy & Grounding, Tone Alignment) using two different methodologies in [evaluation.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/evaluation.py):
  1. **Custom G-Eval Evaluator (`geval_scores`)**: Uses structured JSON prompts to rate the blog sections on a 1.0 to 5.0 scale, calculating a weighted average. This is wired directly into the graph.
  2. **DeepEval Evaluator (`deepeval_scores`)**: Leverages Confident AI's official `deepeval` framework to execute Chain-of-Thought grading based on the G-Eval research paper (Liu et al. 2023). Scores are normalized to a 0.0 to 1.0 scale. To save costs, this runs on-demand when the user clicks "Run Academic Audit" in the UI.

### Q8: How does the Advanced RAG document ingestion work?
* **Answer**: When a user uploads a reference document:
  1. [document_ingest.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/document_ingest.py) parses the file using `pypdf` or `docx`.
  2. It performs **Semantic Chunking** by measuring similarity thresholds between sentence embeddings (OpenAI `text-embedding-3-small`), grouping sentences into context-rich blocks.
  3. When querying, the user's topic vector is compared against the chunk vectors using a **Cosine Similarity** calculation to pull the top matching segments as grounded evidence.

### Q9: How are the audio podcasts and videos synthesized?
* **Answer**:
  - **Gemini Podcast Studio** ([podcast_studio.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/podcast_studio.py)): We invoke the `google-genai` SDK targeting Gemini 2.5 Flash with `response_modalities=["AUDIO"]`. Gemini natively outputs speech waveforms, resulting in highly natural conversational dialogue, pauses, and inflections.
  - **Video Synthesis Studio** ([video.py](file:///d:/Multi_Agent_Blog_generator_FYP/Agents_backend/Graph/agents/video.py)): Splits the blog summary into narration lines, converts them to audio using TTS, queries the **Pexels API** in parallel to download short stock B-rolls matching the narration keywords, maps timelines, and renders an MP4 video with synchronized caption overlays using **MoviePy**.

### Q10: What are the primary bottlenecks or limitations of this system, and how would you scale them in production?
* **Answer**:
  1. **SQLite checkpointer scaling**: SQLite locks the database file on writes, which would fail under high multi-user loads.
     * *Scale Solution*: Replace the default SQLite checkpointer saver with LangGraph's postgres-native `PostgresSaver`.
  2. **MoviePy Rendering Blocks**: MoviePy renders video in-process, which is heavily CPU-bound and blocks our FastAPI threads.
     * *Scale Solution*: Offload video rendering to a task queue (like Celery or Redis Queue) running on separate worker servers.
  3. **In-Memory Event Bus**: The `event_bus.py` caches subscriber lists in memory. If a server scales horizontally behind a load balancer, events published on server A won't reach client connections on server B.
     * *Scale Solution*: Replace the in-memory pub/sub with Redis Pub/Sub.

---
