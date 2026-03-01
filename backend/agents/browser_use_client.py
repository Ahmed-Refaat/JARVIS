# RESEARCH: Browser Use Cloud API v2 (docs.cloud.browser-use.com)
# DECISION: Using httpx async client — pure REST, no SDK needed
# ALT: browser-use pip package (not needed for Cloud API)

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from config import Settings

BU_BASE = "https://api.browser-use.com/api/v2"


class BrowserUseError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Browser Use API {status_code}: {message}")


class BrowserUseClient:
    """Async client for Browser Use Cloud API v2."""

    def __init__(self, settings: Settings):
        self._key = settings.browser_use_api_key
        self._headers = {"X-Browser-Use-API-Key": self._key or ""}

    def _check(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            logger.error("Browser Use API error: {} {}", resp.status_code, resp.text[:200])
            raise BrowserUseError(resp.status_code, resp.text[:200])
        return resp.json()

    async def create_session(
        self,
        start_url: str | None = None,
        width: int = 1280,
        height: int = 800,
    ) -> dict[str, Any]:
        """POST /api/v2/sessions — create a cloud browser session."""
        body: dict[str, Any] = {
            "browserScreenWidth": width,
            "browserScreenHeight": height,
            "keepAlive": True,
        }
        if start_url:
            body["startUrl"] = start_url
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(f"{BU_BASE}/sessions", json=body, headers=self._headers)
        result = self._check(resp)
        logger.info("Created BU session: {}", result.get("id"))
        return result

    async def create_task(
        self,
        session_id: str,
        task: str,
        start_url: str | None = None,
        allowed_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/v2/tasks — create a task attached to a session."""
        body: dict[str, Any] = {
            "task": task,
            "sessionId": session_id,
            "maxSteps": 50,
            "vision": True,
        }
        if start_url:
            body["startUrl"] = start_url
        if allowed_domains:
            body["allowedDomains"] = allowed_domains
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(f"{BU_BASE}/tasks", json=body, headers=self._headers)
        result = self._check(resp)
        logger.info("Created BU task: {} on session {}", result.get("id"), session_id)
        return result

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """GET /api/v2/sessions/{id} — get session with liveUrl and tasks."""
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(f"{BU_BASE}/sessions/{session_id}", headers=self._headers)
        return self._check(resp)

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """GET /api/v2/tasks/{id} — get task with steps and status."""
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(f"{BU_BASE}/tasks/{task_id}", headers=self._headers)
        return self._check(resp)

    async def make_session_public(self, session_id: str) -> dict[str, Any]:
        """POST /api/v2/sessions/{id}/public-share — get public replay URL."""
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                f"{BU_BASE}/sessions/{session_id}/public-share",
                headers=self._headers,
            )
        result = self._check(resp)
        logger.info("Public share created for session {}: {}", session_id, result.get("shareUrl"))
        return result
