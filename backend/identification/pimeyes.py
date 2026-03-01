# RESEARCH: Checked Nix4444/Pimeyes-scraper (Selenium-based, XPath scraping)
# DECISION: Browser Use with paid account login — most reliable for authenticated searches
# ALT: httpx + reverse-engineered API (brittle, endpoints change frequently)
# NOTE: For the demo we target a single person, so 1 account is sufficient.
from __future__ import annotations

import base64
import json
import os
import tempfile
from typing import Any

import httpx
from loguru import logger

from config import Settings
from identification.models import FaceSearchMatch, FaceSearchRequest, FaceSearchResult

# PimEyes endpoints (reverse-engineered from web client) — used as fast-path
_PIMEYES_UPLOAD_URL = "https://pimeyes.com/api/upload/file"
_PIMEYES_SEARCH_URL = "https://pimeyes.com/api/search/new"
_PIMEYES_RESULTS_URL = "https://pimeyes.com/api/search/results"

_DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://pimeyes.com",
    "Referer": "https://pimeyes.com/en",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class PimEyesSearcher:
    """Face searcher using PimEyes with Browser Use for authenticated access.

    Strategy:
    1. Browser Use: Log in with paid account, upload face, extract results.
       Most reliable — handles UI changes, CAPTCHAs, session management.
    2. Fallback: httpx API calls (no auth, limited free-tier results).

    For the demo, we optimize for 1 person at a time with 1 paid account.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._email = settings.pimeyes_email
        self._password = settings.pimeyes_password
        self._accounts: list[dict[str, str]] = self._parse_account_pool(
            settings.pimeyes_account_pool
        )

    @property
    def configured(self) -> bool:
        return bool(self._email and self._password) or bool(self._accounts)

    @staticmethod
    def _parse_account_pool(pool_json: str) -> list[dict[str, str]]:
        try:
            accounts = json.loads(pool_json)
            if isinstance(accounts, list):
                return accounts
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    async def search_face(self, request: FaceSearchRequest) -> FaceSearchResult:
        """Upload a face image to PimEyes and retrieve matching URLs."""
        if not request.image_data:
            return FaceSearchResult(
                success=False,
                error="PimEyes requires image_data (not just embeddings)",
            )

        # Try Browser Use first (authenticated, best results)
        if self._email and self._password and self._settings.browser_use_api_key:
            try:
                return await self._search_via_browser(request.image_data)
            except Exception as exc:
                logger.warning("PimEyes browser search failed, trying API fallback: {}", exc)

        # Fallback to direct API
        try:
            return await self._do_api_search(request.image_data)
        except httpx.TimeoutException:
            logger.warning("PimEyes API search timed out")
            return FaceSearchResult(success=False, error="PimEyes request timed out")
        except Exception as exc:
            logger.error("PimEyes search failed: {}", exc)
            return FaceSearchResult(success=False, error=f"PimEyes error: {exc}")

    async def _search_via_browser(self, image_data: bytes) -> FaceSearchResult:
        """Use Browser Use to log into PimEyes and run face search."""
        from browser_use import Agent, Browser

        # Ensure BROWSER_USE_API_KEY is in env
        if self._settings.browser_use_api_key and not os.environ.get("BROWSER_USE_API_KEY"):
            os.environ["BROWSER_USE_API_KEY"] = self._settings.browser_use_api_key

        # Write image to temp file for upload
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_data)
            image_path = f.name

        try:
            llm = self._build_llm()
            browser = Browser(use_cloud=True)

            task = (
                f"1. Go to https://pimeyes.com/en\n"
                f"2. If not logged in, click 'Log In', enter email {{pimeyes_email}} "
                f"and password {{pimeyes_password}}, then submit.\n"
                f"3. Once logged in, upload the face image from the search bar "
                f"(the file is at: {image_path}).\n"
                f"4. Wait for search results to load (up to 30 seconds).\n"
                f"5. Use the extract tool to get this JSON from the results:\n"
                f'{{"results": [{{"url": "", "similarity": 0.0, "thumbnail_url": "", '
                f'"source_domain": ""}}]}}\n'
                f"Extract the top 10 results. Return ONLY the JSON."
            )

            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                max_failures=2,
                flash_mode=True,
                enable_planning=False,
                step_timeout=60,
                max_actions_per_step=3,
                use_vision="auto",
                sensitive_data={
                    "pimeyes_email": self._email,
                    "pimeyes_password": self._password,
                },
            )

            result = await agent.run()
            final = result.final_result() if result else None

            if final:
                return self._parse_browser_results(str(final))

            return FaceSearchResult(success=False, error="No results from PimEyes browser agent")

        finally:
            # Clean up temp file
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def _build_llm(self):
        """Build LLM for Browser Use agent."""
        if self._settings.browser_use_api_key:
            try:
                from browser_use import ChatBrowserUse
                return ChatBrowserUse(model="bu-2-0")
            except (ImportError, Exception):
                pass

        if self._settings.openai_api_key:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model="gpt-4o-mini", api_key=self._settings.openai_api_key)

        raise RuntimeError("No LLM configured for PimEyes browser agent")

    def _parse_browser_results(self, raw: str) -> FaceSearchResult:
        """Parse browser agent output into FaceSearchResult."""
        # Extract JSON from potential markdown wrapping
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
        cleaned = cleaned.strip()

        data = {}
        for text in [cleaned, raw]:
            try:
                data = json.loads(text)
                break
            except (json.JSONDecodeError, ValueError):
                pass
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                    break
                except (json.JSONDecodeError, ValueError):
                    pass

        results = data.get("results", [])
        matches: list[FaceSearchMatch] = []

        for item in results[:20]:
            url = item.get("url", "")
            similarity = float(item.get("similarity", 0.0))
            if similarity > 1.0:
                similarity = similarity / 100.0
            similarity = max(0.0, min(1.0, similarity))

            matches.append(FaceSearchMatch(
                url=url,
                thumbnail_url=item.get("thumbnail_url"),
                similarity=similarity,
                source="pimeyes",
                person_name=item.get("name"),
            ))

        if matches:
            logger.info("PimEyes browser search returned {} matches", len(matches))
            return FaceSearchResult(matches=matches, success=True)

        return FaceSearchResult(success=False, error="PimEyes returned no parseable results")

    # ── Direct API fallback ──────────────────────────────────────────

    async def _do_api_search(self, image_data: bytes) -> FaceSearchResult:
        """Execute PimEyes search via reverse-engineered API (no auth)."""
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
        ) as client:
            upload_resp = await self._upload_image(client, image_data)
            if not upload_resp:
                return FaceSearchResult(success=False, error="PimEyes upload failed")

            search_id = upload_resp.get("id") or upload_resp.get("searchHash")
            if not search_id:
                logger.warning("PimEyes upload response missing search ID: {}", upload_resp)
                return FaceSearchResult(success=False, error="No search ID in upload response")

            search_resp = await self._trigger_search(client, search_id)
            if not search_resp:
                return FaceSearchResult(success=False, error="PimEyes search trigger failed")

            results = await self._fetch_results(client, search_id)
            return self._parse_api_results(results)

    async def _upload_image(
        self, client: httpx.AsyncClient, image_data: bytes
    ) -> dict[str, Any] | None:
        b64 = base64.b64encode(image_data).decode()
        payload = {"image": f"data:image/jpeg;base64,{b64}"}

        resp = await client.post(_PIMEYES_UPLOAD_URL, json=payload)
        if resp.status_code != 200:
            logger.warning("PimEyes upload returned {}: {}", resp.status_code, resp.text[:200])
            return None
        return resp.json()

    async def _trigger_search(
        self, client: httpx.AsyncClient, search_id: str
    ) -> dict[str, Any] | None:
        payload = {"searchId": search_id, "searchType": "FACE"}
        cookies = self._get_cookies()
        resp = await client.post(_PIMEYES_SEARCH_URL, json=payload, cookies=cookies)
        if resp.status_code != 200:
            logger.warning("PimEyes search trigger returned {}", resp.status_code)
            return None
        return resp.json()

    async def _fetch_results(
        self, client: httpx.AsyncClient, search_id: str
    ) -> list[dict[str, Any]]:
        params = {"searchId": search_id}
        cookies = self._get_cookies()
        resp = await client.get(_PIMEYES_RESULTS_URL, params=params, cookies=cookies)
        if resp.status_code != 200:
            logger.warning("PimEyes results returned {}", resp.status_code)
            return []
        data = resp.json()
        return data.get("results", [])

    def _get_cookies(self) -> dict[str, str]:
        if self._accounts:
            account = self._accounts[0]
            return {k: v for k, v in account.items() if k.startswith("__")}
        return {}

    @staticmethod
    def _parse_api_results(results: list[dict[str, Any]]) -> FaceSearchResult:
        matches: list[FaceSearchMatch] = []
        for item in results[:20]:
            url = item.get("sourceUrl") or item.get("url", "")
            thumbnail = item.get("thumbnailUrl") or item.get("thumbnail")
            similarity = float(item.get("similarity", item.get("score", 0.0)))
            if similarity > 1.0:
                similarity = similarity / 100.0
            similarity = max(0.0, min(1.0, similarity))

            matches.append(FaceSearchMatch(
                url=url,
                thumbnail_url=thumbnail,
                similarity=similarity,
                source="pimeyes",
                person_name=item.get("name"),
            ))

        logger.info("PimEyes API returned {} matches", len(matches))
        return FaceSearchResult(matches=matches, success=True)
