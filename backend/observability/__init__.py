from __future__ import annotations

from typing import Any, Protocol


class TracingClient(Protocol):
    """Contract for observability and tracing (Laminar, etc.)."""

    @property
    def configured(self) -> bool: ...

    def trace_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Record a single trace event."""
        ...

    def trace_span_start(self, span_name: str, metadata: dict[str, Any] | None = None) -> str:
        """Begin a trace span. Returns a span ID."""
        ...

    def trace_span_end(self, span_id: str, result: dict[str, Any] | None = None) -> None:
        """End a previously started trace span."""
        ...
