from __future__ import annotations

from typing import Any
from uuid import uuid4

from loguru import logger

from config import Settings


class LaminarTracingClient:
    """Settings-aware seam for Laminar tracing integration.

    Implements the TracingClient protocol from observability/__init__.py.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.laminar_api_key)

    def trace_event(self, event_name: str, payload: dict[str, Any]) -> None:
        logger.debug("LaminarTracingClient.trace_event name={}", event_name)
        if not self.configured:
            logger.warning("Laminar not configured, event discarded: {}", event_name)

    def trace_span_start(self, span_name: str, metadata: dict[str, Any] | None = None) -> str:
        span_id = f"span_{uuid4().hex[:12]}"
        logger.debug("LaminarTracingClient.trace_span_start name={} id={}", span_name, span_id)
        return span_id

    def trace_span_end(self, span_id: str, result: dict[str, Any] | None = None) -> None:
        logger.debug("LaminarTracingClient.trace_span_end id={}", span_id)
