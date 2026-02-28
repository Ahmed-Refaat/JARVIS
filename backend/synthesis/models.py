from __future__ import annotations

from pydantic import BaseModel, Field


class SocialProfile(BaseModel):
    """A linked social media profile."""

    platform: str
    url: str
    username: str | None = None
    bio: str | None = None
    followers: int | None = None


class ConnectionEdge(BaseModel):
    """A connection between the subject and another person."""

    person_name: str
    relationship: str
    context: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class SynthesisRequest(BaseModel):
    """Input for report synthesis."""

    person_name: str
    face_search_urls: list[str] = Field(default_factory=list)
    enrichment_snippets: list[str] = Field(default_factory=list)
    social_profiles: list[SocialProfile] = Field(default_factory=list)
    raw_agent_data: dict[str, str] = Field(default_factory=dict)


class SynthesisResult(BaseModel):
    """Structured person intelligence report."""

    person_name: str
    summary: str = ""
    occupation: str | None = None
    organization: str | None = None
    location: str | None = None
    social_profiles: list[SocialProfile] = Field(default_factory=list)
    connections: list[ConnectionEdge] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    success: bool = True
    error: str | None = None
