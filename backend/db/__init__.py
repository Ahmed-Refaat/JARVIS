from __future__ import annotations

from typing import Any, Protocol


class DatabaseGateway(Protocol):
    """Contract for real-time database operations (Convex, etc.)."""

    @property
    def configured(self) -> bool: ...

    async def store_person(self, person_id: str, data: dict[str, Any]) -> str:
        """Persist a person record. Returns the stored document ID."""
        ...

    async def get_person(self, person_id: str) -> dict[str, Any] | None:
        """Retrieve a person record by ID."""
        ...

    async def update_person(self, person_id: str, data: dict[str, Any]) -> None:
        """Merge new data into an existing person record."""
        ...

    async def store_capture(self, capture_id: str, metadata: dict[str, Any]) -> str:
        """Persist capture metadata. Returns the stored document ID."""
        ...
