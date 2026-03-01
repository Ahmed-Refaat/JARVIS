from __future__ import annotations

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from agents.browser_use_client import BrowserUseClient, BrowserUseError
from capture.frame_handler import FrameHandler
from capture.service import CaptureService
from config import get_settings
from schemas import (
    AgentInfo,
    AgentStartRequest,
    AgentStartResponse,
    FrameProcessedResponse,
    FrameSubmission,
    HealthResponse,
    ServiceStatus,
    SessionStatusResponse,
    TaskInfo,
    TaskPhase,
    TaskStep,
)
from tasks import TASK_PHASES

settings = get_settings()
capture_service = CaptureService()
frame_handler = FrameHandler()
bu_client = BrowserUseClient(settings)
upload_file = File(...)

# Task prompts keyed by source type
SOURCE_CONFIGS: dict[str, dict[str, str]] = {
    "linkedin": {
        "tp": "SOCIAL",
        "nm": "LinkedIn Profile",
        "prompt": (
            "Search LinkedIn for '{name}'. Navigate to their profile. "
            "Extract: current role, company, work history (last 3 positions), "
            "education, notable connections, and recent posts."
        ),
        "start_url": "https://linkedin.com",
    },
    "twitter": {
        "tp": "SOCIAL",
        "nm": "Twitter/X Activity",
        "prompt": (
            "Search Twitter/X for '{name}'. Find their profile. "
            "Extract: bio, follower count, recent tweets (last 10), "
            "and accounts they interact with most."
        ),
        "start_url": "https://twitter.com",
    },
    "google": {
        "tp": "MEDIA",
        "nm": "Google Search Results",
        "prompt": (
            "Search Google for '{name}'. Look for news articles, "
            "company mentions, and public records. Extract all relevant "
            "results with their URLs and summaries."
        ),
        "start_url": "https://google.com",
    },
    "crunchbase": {
        "tp": "CORPORATE",
        "nm": "Crunchbase Profile",
        "prompt": (
            "Search Crunchbase for '{name}'. Find their profile or companies. "
            "Extract: role, companies, funding rounds, investors, and exits."
        ),
        "start_url": "https://crunchbase.com",
    },
}

# Cache share URLs so we only call make_session_public once
_share_url_cache: dict[str, str] = {}

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    summary="Control plane and service seams for the SPECTER hackathon stack",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        services=settings.service_flags(),
    )


@app.get("/api/services", response_model=list[ServiceStatus])
async def services() -> list[ServiceStatus]:
    descriptions = {
        "convex": "Real-time board subscriptions and mutations",
        "mongodb": "Persistent raw captures and dossiers",
        "exa": "Fast pass research and person lookup",
        "browser_use": "Deep research browser agents",
        "openai": "Transcription and fallback LLM integrations",
        "gemini": "Primary vision and synthesis model",
        "laminar": "Tracing and evaluation telemetry",
        "telegram": "Glasses-side media intake",
        "pimeyes_pool": "Rotating account pool for identification",
    }
    flags = settings.service_flags()
    return [
        ServiceStatus(name=name, configured=configured, notes=descriptions.get(name))
        for name, configured in flags.items()
    ]


@app.get("/api/tasks", response_model=list[TaskPhase])
async def tasks() -> list[TaskPhase]:
    return TASK_PHASES


@app.post("/api/capture")
async def capture(file: UploadFile = upload_file, source: str = "manual_upload"):
    return await capture_service.enqueue_upload(file=file, source=source)


@app.post("/api/capture/frame", response_model=FrameProcessedResponse)
async def capture_frame(submission: FrameSubmission) -> FrameProcessedResponse:
    result = await frame_handler.process_frame(
        frame_b64=submission.frame,
        timestamp=submission.timestamp,
        source=submission.source,
    )
    return FrameProcessedResponse(**result)


# --- Browser Use agent research ---


@app.post("/api/agents/research", response_model=AgentStartResponse)
async def start_research(req: AgentStartRequest) -> AgentStartResponse:
    """Spawn Browser Use sessions/tasks per source type. Returns immediately."""
    agents: list[AgentInfo] = []
    for source_key in req.sources:
        cfg = SOURCE_CONFIGS.get(source_key)
        if not cfg:
            logger.warning("Unknown source type: {}", source_key)
            continue
        try:
            session = await bu_client.create_session(start_url=cfg["start_url"])
            session_id = session["id"]
            prompt = cfg["prompt"].replace("{name}", req.person_name)
            task = await bu_client.create_task(
                session_id=session_id,
                task=prompt,
                start_url=cfg["start_url"],
            )
            agents.append(AgentInfo(
                source_tp=cfg["tp"],
                source_nm=cfg["nm"],
                session_id=session_id,
                task_id=task["id"],
                live_url=session.get("liveUrl"),
                session_status="running",
            ))
        except BrowserUseError as e:
            logger.error("Failed to create agent for {}: {}", source_key, e)
            continue
        except Exception as e:
            logger.error("Unexpected error creating agent for {}: {}", source_key, e)
            continue
    return AgentStartResponse(person_id=req.person_id, agents=agents)


def _map_bu_status(bu_status: str | None) -> str:
    """Map Browser Use status strings to our status enum."""
    mapping = {
        "active": "running",
        "created": "pending",
        "started": "running",
        "running": "running",
        "idle": "running",
        "finished": "completed",
        "stopped": "completed",
        "timed_out": "failed",
        "error": "failed",
    }
    return mapping.get(bu_status or "", "pending")


@app.get("/api/agents/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str) -> SessionStatusResponse:
    """Proxy Browser Use session + task status for frontend polling."""
    try:
        session = await bu_client.get_session(session_id)
    except BrowserUseError as e:
        logger.error("Failed to get session {}: {}", session_id, e)
        return SessionStatusResponse(session_id=session_id, session_status="failed")

    session_status = _map_bu_status(session.get("status"))
    live_url = session.get("liveUrl")
    share_url = session.get("publicShareUrl") or _share_url_cache.get(session_id)

    # On first completed fetch, create public share for replay
    if session_status == "completed" and not share_url and session_id not in _share_url_cache:
        try:
            share_data = await bu_client.make_session_public(session_id)
            share_url = share_data.get("shareUrl")
            if share_url:
                _share_url_cache[session_id] = share_url
        except BrowserUseError:
            logger.warning("Could not create public share for session {}", session_id)

    # Get task details if available
    task_info = None
    tasks_list = session.get("tasks", [])
    if tasks_list:
        task_id = tasks_list[0].get("id") if isinstance(tasks_list[0], dict) else tasks_list[0]
        try:
            task_data = await bu_client.get_task(task_id)
            raw_steps = task_data.get("steps", [])
            steps = [
                TaskStep(
                    number=s.get("number", i + 1),
                    url=s.get("url"),
                    screenshot_url=s.get("screenshotUrl"),
                    next_goal=s.get("nextGoal"),
                )
                for i, s in enumerate(raw_steps)
            ]
            task_info = TaskInfo(
                task_id=task_id,
                status=task_data.get("status"),
                steps=steps,
                output=task_data.get("output"),
            )
        except BrowserUseError:
            logger.warning("Could not get task {} for session {}", task_id, session_id)

    return SessionStatusResponse(
        session_id=session_id,
        session_status=session_status,
        live_url=live_url,
        share_url=share_url,
        task=task_info,
    )
