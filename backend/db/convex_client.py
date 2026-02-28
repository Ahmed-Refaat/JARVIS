from __future__ import annotations

from typing import Any

from loguru import logger

from config import Settings


class ConvexGateway:
    """Thin settings-aware placeholder until the real Convex client is linked.

    Implements the DatabaseGateway protocol from db/__init__.py.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.convex_url)

    async def store_person(self, person_id: str, data: dict[str, Any]) -> str:
        logger.info("ConvexGateway.store_person called for {}", person_id)
        if not self.configured:
            raise RuntimeError("Convex is not configured (CONVEX_URL missing)")
        return person_id

    async def get_person(self, person_id: str) -> dict[str, Any] | None:
        logger.info("ConvexGateway.get_person called for {}", person_id)
        if not self.configured:
            raise RuntimeError("Convex is not configured (CONVEX_URL missing)")
        return None

    async def update_person(self, person_id: str, data: dict[str, Any]) -> None:
        logger.info("ConvexGateway.update_person called for {}", person_id)
        if not self.configured:
            raise RuntimeError("Convex is not configured (CONVEX_URL missing)")

    async def store_capture(self, capture_id: str, metadata: dict[str, Any]) -> str:
        logger.info("ConvexGateway.store_capture called for {}", capture_id)
        if not self.configured:
            raise RuntimeError("Convex is not configured (CONVEX_URL missing)")
        return capture_id
