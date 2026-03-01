from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str
    services: dict[str, bool]


class CaptureQueuedResponse(BaseModel):
    capture_id: str
    filename: str
    content_type: str
    status: Literal["queued"]
    source: str


class ServiceStatus(BaseModel):
    name: str
    configured: bool
    notes: str | None = None


class TaskItem(BaseModel):
    id: str
    title: str
    area: str
    status: Literal["pending", "in_progress", "done"] = "pending"
    acceptance: str
    notes: str | None = None


class TaskPhase(BaseModel):
    id: str
    title: str
    timebox: str
    tasks: list[TaskItem] = Field(default_factory=list)


# --- Stream frame capture & YOLO detection ---


class FrameSubmission(BaseModel):
    frame: str  # base64-encoded JPEG
    timestamp: int  # client-side ms since epoch
    source: str = "glasses_stream"


class Detection(BaseModel):
    bbox: list[float]  # [x1, y1, x2, y2]
    confidence: float
    track_id: int | None = None


class FrameProcessedResponse(BaseModel):
    capture_id: str
    detections: list[Detection]
    new_persons: int
    timestamp: int
    source: str
