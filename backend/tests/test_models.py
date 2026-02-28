from __future__ import annotations

import pytest
from pydantic import ValidationError

from enrichment.models import EnrichmentHit, EnrichmentRequest, EnrichmentResult
from identification.models import (
    BoundingBox,
    DetectedFace,
    FaceDetectionRequest,
    FaceDetectionResult,
    FaceSearchMatch,
    FaceSearchRequest,
    FaceSearchResult,
)
from synthesis.models import (
    ConnectionEdge,
    SocialProfile,
    SynthesisRequest,
    SynthesisResult,
)

# --- Enrichment models ---


def test_enrichment_request_minimal() -> None:
    req = EnrichmentRequest(name="John Doe")
    assert req.name == "John Doe"
    assert req.company is None
    assert req.additional_context is None


def test_enrichment_request_with_company() -> None:
    req = EnrichmentRequest(name="Jane", company="Acme Corp")
    assert req.company == "Acme Corp"


def test_enrichment_hit_defaults() -> None:
    hit = EnrichmentHit(title="Test", url="https://example.com")
    assert hit.score == 0.0
    assert hit.source == "exa"
    assert hit.snippet is None


def test_enrichment_hit_score_bounds() -> None:
    hit = EnrichmentHit(title="T", url="https://x.com", score=1.0)
    assert hit.score == 1.0

    with pytest.raises(ValidationError):
        EnrichmentHit(title="T", url="https://x.com", score=1.5)


def test_enrichment_result_defaults() -> None:
    result = EnrichmentResult(query="test")
    assert result.hits == []
    assert result.success is True
    assert result.error is None


def test_enrichment_result_with_error() -> None:
    result = EnrichmentResult(query="q", success=False, error="API down")
    assert result.success is False
    assert result.error == "API down"


# --- Identification models ---


def test_bounding_box_valid() -> None:
    bb = BoundingBox(x=0.1, y=0.2, width=0.5, height=0.5)
    assert bb.x == 0.1
    assert bb.width == 0.5


def test_bounding_box_out_of_range() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x=1.5, y=0.0, width=0.5, height=0.5)


def test_detected_face_defaults() -> None:
    face = DetectedFace(
        bbox=BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0),
        confidence=0.9,
    )
    assert face.embedding == []
    assert face.confidence == 0.9


def test_face_detection_request_defaults() -> None:
    req = FaceDetectionRequest(image_data=b"img")
    assert req.max_faces == 10
    assert req.min_confidence == 0.5


def test_face_detection_request_custom() -> None:
    req = FaceDetectionRequest(image_data=b"img", max_faces=5, min_confidence=0.8)
    assert req.max_faces == 5
    assert req.min_confidence == 0.8


def test_face_detection_result_defaults() -> None:
    result = FaceDetectionResult()
    assert result.faces == []
    assert result.success is True


def test_face_search_request_defaults() -> None:
    req = FaceSearchRequest(embedding=[0.1, 0.2, 0.3])
    assert req.search_engines == ["pimeyes"]
    assert req.image_data is None


def test_face_search_match() -> None:
    match = FaceSearchMatch(url="https://x.com/user", similarity=0.95, source="pimeyes")
    assert match.person_name is None
    assert match.thumbnail_url is None


def test_face_search_result_defaults() -> None:
    result = FaceSearchResult()
    assert result.matches == []
    assert result.success is True


# --- Synthesis models ---


def test_social_profile() -> None:
    profile = SocialProfile(platform="twitter", url="https://x.com/user")
    assert profile.username is None
    assert profile.followers is None


def test_connection_edge_defaults() -> None:
    edge = ConnectionEdge(person_name="Bob", relationship="colleague")
    assert edge.confidence == 0.5
    assert edge.context is None


def test_connection_edge_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ConnectionEdge(person_name="Bob", relationship="friend", confidence=1.5)


def test_synthesis_request_minimal() -> None:
    req = SynthesisRequest(person_name="Alice")
    assert req.face_search_urls == []
    assert req.enrichment_snippets == []
    assert req.social_profiles == []
    assert req.raw_agent_data == {}


def test_synthesis_result_defaults() -> None:
    result = SynthesisResult(person_name="Alice")
    assert result.summary == ""
    assert result.occupation is None
    assert result.social_profiles == []
    assert result.connections == []
    assert result.key_facts == []
    assert result.confidence_score == 0.0
    assert result.success is True


def test_synthesis_result_with_data() -> None:
    profile = SocialProfile(
        platform="linkedin", url="https://linkedin.com/in/alice", username="alice",
    )
    edge = ConnectionEdge(person_name="Bob", relationship="coworker", confidence=0.8)
    result = SynthesisResult(
        person_name="Alice",
        summary="AI researcher",
        occupation="Researcher",
        organization="OpenAI",
        location="SF",
        social_profiles=[profile],
        connections=[edge],
        key_facts=["Published 20 papers"],
        confidence_score=0.85,
    )
    assert result.person_name == "Alice"
    assert len(result.social_profiles) == 1
    assert len(result.connections) == 1
    assert result.confidence_score == 0.85
