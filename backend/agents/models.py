"""Pydantic models for browser research agent results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def parse_human_number(value) -> int | None:
    """Parse human-readable numbers like '5.5K+', '10M', '1,234' into integers."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip().replace(",", "").replace("+", "").upper()
    if not s:
        return None
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except (ValueError, TypeError):
                return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class SocialProfile(BaseModel):
    """A social media profile discovered by an agent."""

    platform: str
    url: str
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    followers: int | None = None
    following: int | None = None
    location: str | None = None
    verified: bool = False
    raw_data: dict | None = None


class AgentResult(BaseModel):
    """Result from a single research agent run."""

    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    profiles: list[SocialProfile] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    urls_found: list[str] = Field(default_factory=list)
    error: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    duration_seconds: float = 0.0
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class ResearchRequest(BaseModel):
    """Input for the research agent orchestrator."""

    person_name: str
    company: str | None = None
    face_search_urls: list[str] = Field(default_factory=list)
    additional_context: str | None = None
    timeout_seconds: float = 90.0


class OrchestratorResult(BaseModel):
    """Aggregated results from all research agents."""

    person_name: str
    agent_results: dict[str, AgentResult] = Field(default_factory=dict)
    all_profiles: list[SocialProfile] = Field(default_factory=list)
    all_snippets: list[str] = Field(default_factory=list)
    total_duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None
