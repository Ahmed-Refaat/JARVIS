"""Deep researcher — unified pipeline that replaces the old orchestrator.

# RESEARCH: Exa returns 10 hits max per query. SixtyFour.ai adds structured
#   lead enrichment + agentic deep search. Combining them doubles discovery.
# DECISION: 4-phase async generator pipeline:
#   Phase 0: Exa multi-query + SixtyFour enrich-lead (parallel, ~3s)
#   Phase 1: Platform skills + OSINT skills (parallel, up to 15 concurrent)
#   Phase 2: Deep URL extraction + SixtyFour deep-search results + dark web
#   Phase 3: Verification loop — retry failed skills with account creation
# ALT: Keep old orchestrator (surface-level, no skill dispatch, no SixtyFour)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from urllib.parse import urlparse

from loguru import logger

from agents.account_manager import AccountManager
from agents.cloud_skills import CloudSkillRunner
from agents.models import AgentResult, AgentStatus, ResearchRequest, SocialProfile
from config import Settings
from enrichment.exa_client import ExaEnrichmentClient
from enrichment.models import EnrichmentRequest
from enrichment.sixtyfour_client import SixtyFourClient

# Platform signup URLs for autonomous account creation
PLATFORM_SIGNUP_URLS = {
    "twitter.com": "https://x.com/i/flow/signup",
    "instagram.com": "https://www.instagram.com/accounts/emailsignup/",
    "tiktok.com": "https://www.tiktok.com/signup",
    "reddit.com": "https://www.reddit.com/register/",
    "github.com": "https://github.com/signup",
    "medium.com": "https://medium.com/m/signin?operation=register",
    "linkedin.com": "https://www.linkedin.com/signup",
}

# Map domains to Cloud SDK skill names for targeted extraction
DOMAIN_TO_SKILL = {
    "github.com": "github_profile",
    "tiktok.com": "tiktok_profile",
    "instagram.com": "instagram_posts",
    "facebook.com": "facebook_page",
    "reddit.com": "reddit_subreddit",
    "linkedin.com": "linkedin_company_posts",
    "youtube.com": "youtube_filmography",
    "linktree.com": "linktree_profile",
    "linktr.ee": "linktree_profile",
    "pinterest.com": "pinterest_pins",
}

# Map skill names to platform domains for signup retry
SKILL_TO_DOMAIN = {v: k for k, v in DOMAIN_TO_SKILL.items()}

# Max concurrency for Browser Use sessions
MAX_CONCURRENT_SESSIONS = 25

# Domains to skip from search results (noise)
SKIP_DOMAINS = frozenset({
    "digitalmarketingwithmustafaa.com",
    "wikipedia.org",
    "wikidata.org",
})


class DeepResearcher:
    """Multi-phase deep research pipeline that streams results.

    Phase 0: Exa + SixtyFour enrich-lead in parallel (~3s)
    Phase 1: Platform + OSINT skills in parallel (~20-35s, up to 15 concurrent)
    Phase 2: Deep URL extraction + SixtyFour deep-search + dark web (~30-60s)
    Phase 3: Verification loop — retry failed skills with account creation (~30-90s)

    Results stream as an async generator so the UI can update live.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._exa = ExaEnrichmentClient(settings)
        self._sixtyfour = SixtyFourClient(settings)
        self._cloud = CloudSkillRunner(settings)
        self._accounts = AccountManager(settings)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)

    async def research(
        self,
        request: ResearchRequest,
    ) -> AsyncGenerator[AgentResult, None]:
        """Stream research results as they complete across all phases."""
        person = request.person_name
        company = request.company
        t0 = time.monotonic()
        seen_urls: set[str] = set()
        failed_skills: list[tuple[str, str]] = []  # (skill_name, task_str)

        # ── Phase 0: Exa + SixtyFour in parallel ──────────────────────
        logger.info("deep_researcher: phase 0 — exa + sixtyfour for {}", person)

        exa_urls, exa_snippets, sixtyfour_result, deep_search_task_id = (
            await self._phase0(person, company, seen_urls)
        )

        # Yield Exa results
        if exa_urls:
            yield AgentResult(
                agent_name="exa_deep",
                status=AgentStatus.SUCCESS,
                snippets=exa_snippets,
                urls_found=exa_urls,
                duration_seconds=time.monotonic() - t0,
            )

        # Yield SixtyFour enrich results
        if sixtyfour_result and sixtyfour_result.success:
            sf_snippets = []
            sf_profiles = []
            sf_urls = []

            if sixtyfour_result.findings:
                sf_snippets.extend(
                    f"[SixtyFour] {f}" for f in sixtyfour_result.findings
                )
            if sixtyfour_result.linkedin:
                sf_urls.append(sixtyfour_result.linkedin)
                sf_profiles.append(
                    SocialProfile(
                        platform="linkedin",
                        url=sixtyfour_result.linkedin,
                        display_name=sixtyfour_result.name or person,
                    )
                )
            if sixtyfour_result.twitter:
                sf_urls.append(sixtyfour_result.twitter)
                sf_profiles.append(
                    SocialProfile(
                        platform="twitter",
                        url=sixtyfour_result.twitter,
                        display_name=sixtyfour_result.name or person,
                    )
                )
            if sixtyfour_result.github:
                sf_urls.append(sixtyfour_result.github)
                sf_profiles.append(
                    SocialProfile(
                        platform="github",
                        url=sixtyfour_result.github,
                        display_name=sixtyfour_result.name or person,
                    )
                )
            if sixtyfour_result.instagram:
                sf_urls.append(sixtyfour_result.instagram)
                sf_profiles.append(
                    SocialProfile(
                        platform="instagram",
                        url=sixtyfour_result.instagram,
                        display_name=sixtyfour_result.name or person,
                    )
                )
            if sixtyfour_result.email:
                sf_snippets.append(
                    f"[SixtyFour] Email: {sixtyfour_result.email}"
                )
            if sixtyfour_result.phone:
                sf_snippets.append(
                    f"[SixtyFour] Phone: {sixtyfour_result.phone}"
                )
            if sixtyfour_result.title:
                sf_snippets.append(
                    f"[SixtyFour] Title: {sixtyfour_result.title}"
                )
            if sixtyfour_result.company:
                sf_snippets.append(
                    f"[SixtyFour] Company: {sixtyfour_result.company}"
                )

            seen_urls.update(sf_urls)

            yield AgentResult(
                agent_name="sixtyfour_enrich",
                status=AgentStatus.SUCCESS,
                snippets=sf_snippets,
                urls_found=sf_urls,
                profiles=sf_profiles,
                duration_seconds=time.monotonic() - t0,
            )

        logger.info(
            "deep_researcher: phase 0 done — {} exa URLs, sixtyfour={}",
            len(exa_urls),
            sixtyfour_result.success if sixtyfour_result else "unconfigured",
        )

        # ── Phase 1: Platform + OSINT skills in parallel ──────────────
        logger.info("deep_researcher: phase 1 — skills for {}", person)

        async for result in self._phase1(
            person, company, exa_urls, sixtyfour_result, seen_urls, failed_skills
        ):
            yield result

        # ── Phase 2: Deep URL extraction + SixtyFour deep search + dark web
        logger.info("deep_researcher: phase 2 — deep extraction for {}", person)

        async for result in self._phase2(
            person, exa_urls, seen_urls, deep_search_task_id
        ):
            yield result

        # ── Phase 3: Verification loop — retry failed skills ──────────
        if failed_skills and self._accounts.configured:
            logger.info(
                "deep_researcher: phase 3 — retrying {} failed skills",
                len(failed_skills),
            )
            async for result in self._phase3(person, failed_skills):
                yield result

        elapsed = time.monotonic() - t0
        logger.info(
            "deep_researcher: completed for {} in {:.1f}s", person, elapsed
        )

    # ─── Phase 0: Exa + SixtyFour ────────────────────────────────────────

    async def _phase0(
        self,
        person: str,
        company: str | None,
        seen_urls: set[str],
    ) -> tuple[list[str], list[str], object | None, str | None]:
        """Run Exa multi-query + SixtyFour enrich-lead in parallel.

        Returns (exa_urls, exa_snippets, sixtyfour_result, deep_search_task_id).
        """
        exa_queries = [
            EnrichmentRequest(name=person, company=company),
            EnrichmentRequest(
                name=person,
                additional_context="social media profiles",
            ),
        ]
        if company:
            exa_queries.append(
                EnrichmentRequest(
                    name=person,
                    additional_context=f"{company} employee",
                )
            )

        # Fire all Phase 0 tasks in parallel
        exa_coros = [self._exa.enrich_person(q) for q in exa_queries]
        sixtyfour_coro = self._sixtyfour.enrich_lead(person, company)
        deep_search_coro = self._sixtyfour.start_deep_search(person)

        all_results = await asyncio.gather(
            *exa_coros,
            sixtyfour_coro,
            deep_search_coro,
            return_exceptions=True,
        )

        # Unpack
        exa_results = all_results[: len(exa_queries)]
        sixtyfour_result = all_results[len(exa_queries)]
        deep_search_task_id = all_results[len(exa_queries) + 1]

        if isinstance(sixtyfour_result, Exception):
            logger.warning("sixtyfour enrich-lead failed: {}", sixtyfour_result)
            sixtyfour_result = None
        if isinstance(deep_search_task_id, Exception):
            logger.warning("sixtyfour deep search start failed: {}", deep_search_task_id)
            deep_search_task_id = None

        # Parse Exa results
        exa_urls: list[str] = []
        exa_snippets: list[str] = []

        for result in exa_results:
            if isinstance(result, Exception) or not result.success:
                continue
            for hit in result.hits:
                if not hit.url or hit.url in seen_urls:
                    continue
                domain = urlparse(hit.url).netloc.lower()
                if any(d in domain for d in SKIP_DOMAINS):
                    continue
                # Relevance: at least one name part in title or snippet
                name_parts = person.lower().split()
                title_lower = (hit.title or "").lower()
                snippet_lower = (hit.snippet or "").lower()
                if not any(
                    part in title_lower or part in snippet_lower
                    for part in name_parts
                ):
                    continue
                seen_urls.add(hit.url)
                exa_urls.append(hit.url)
                snippet = (
                    f"[Exa] {hit.title}: {hit.snippet[:200]}"
                    if hit.snippet
                    else f"[Exa] {hit.title}"
                )
                exa_snippets.append(snippet)

        return exa_urls, exa_snippets, sixtyfour_result, deep_search_task_id

    # ─── Phase 1: Platform + OSINT skills ────────────────────────────────

    async def _phase1(
        self,
        person: str,
        company: str | None,
        exa_urls: list[str],
        sixtyfour_result: object | None,
        seen_urls: set[str],
        failed_skills: list[tuple[str, str]],
    ) -> AsyncGenerator[AgentResult, None]:
        """Run platform + OSINT skills in parallel."""
        skill_tasks: list[tuple[str, str, asyncio.Task]] = []

        # Core platform skills
        core_skills = [
            ("tiktok_profile", f"Get TikTok profile info for {person}"),
            ("github_profile", f"Get GitHub profile and projects for {person}"),
            ("instagram_posts", f"Get Instagram profile and posts for {person}"),
            (
                "linkedin_company_posts",
                f"Find LinkedIn profile and posts for {person}"
                + (f" at {company}" if company else ""),
            ),
            ("facebook_page", f"Get Facebook page or profile for {person}"),
            ("youtube_filmography", f"Find YouTube channel for {person}"),
            ("reddit_subreddit", f"Find Reddit profile for {person}"),
            ("pinterest_pins", f"Find Pinterest profile for {person}"),
            ("linktree_profile", f"Get Linktree links for {person}"),
        ]

        # OSINT skills
        osint_skills = [
            ("osint_scraper", f"Run OSINT search for {person}"),
        ]
        if company:
            osint_skills.extend([
                ("sec_filings", f"Find SEC filings for {company}"),
                ("company_employees", f"Find employees at {company}"),
                ("yc_company", f"Check if {company} is a YC company"),
            ])

        # Domain-matched skills from Exa/SixtyFour URLs
        domain_matched: list[tuple[str, str]] = []
        launched_skills: set[str] = set()

        for skill_name, task_str in core_skills + osint_skills:
            launched_skills.add(skill_name)

        for url in exa_urls:
            domain = urlparse(url).netloc.lower().replace("www.", "")
            skill_name = DOMAIN_TO_SKILL.get(domain)
            if skill_name and skill_name not in launched_skills:
                domain_matched.append(
                    (skill_name, f"Extract all info from {url} about {person}")
                )
                launched_skills.add(skill_name)

        # Also check SixtyFour-discovered URLs
        if sixtyfour_result and hasattr(sixtyfour_result, "references"):
            for ref in sixtyfour_result.references or []:
                if not isinstance(ref, str) or not ref.startswith("http"):
                    continue
                domain = urlparse(ref).netloc.lower().replace("www.", "")
                skill_name = DOMAIN_TO_SKILL.get(domain)
                if skill_name and skill_name not in launched_skills:
                    domain_matched.append(
                        (skill_name, f"Extract info from {ref} about {person}")
                    )
                    launched_skills.add(skill_name)

        # Ancestry + whois (always run)
        always_skills = [
            ("ancestry_records", f"Find ancestry records for {person}"),
        ]

        all_skills = core_skills + osint_skills + domain_matched + always_skills

        # Launch all skill tasks with semaphore
        for skill_name, task_str in all_skills:
            task = asyncio.ensure_future(
                self._run_skill_with_semaphore(skill_name, task_str)
            )
            skill_tasks.append((skill_name, task_str, task))

        # Yield results as they complete
        pending_tasks = [t for _, _, t in skill_tasks]
        task_map = {t: (sn, ts) for sn, ts, t in skill_tasks}

        for coro in asyncio.as_completed(pending_tasks):
            try:
                result = await coro
                skill_name = "unknown"
                task_str = ""
                # Find the task in map
                for t, (sn, ts) in task_map.items():
                    if t is coro:
                        skill_name = sn
                        task_str = ts
                        break

                if result and result.get("success"):
                    output = result.get("output", "")
                    label = result.get("label", skill_name)
                    agent_result = AgentResult(
                        agent_name=f"skill_{label}",
                        status=AgentStatus.SUCCESS,
                        snippets=[output[:500]] if output else [],
                        profiles=[
                            SocialProfile(
                                platform=label,
                                url="",
                                display_name=person,
                                raw_data={"cloud_output": output},
                            )
                        ],
                        confidence=self._compute_confidence(output, person),
                    )
                    if self._verify_result(agent_result, person):
                        yield agent_result
                    else:
                        logger.info(
                            "deep_researcher: filtered low-confidence skill_{}",
                            label,
                        )
                else:
                    # Track failure for Phase 3 retry
                    for t, (sn, ts) in task_map.items():
                        if t is coro:
                            failed_skills.append((sn, ts))
                            break

            except Exception as exc:
                logger.warning("deep_researcher: skill error: {}", str(exc))

    async def _run_skill_with_semaphore(
        self, skill_name: str, task_str: str
    ) -> dict | None:
        """Run a skill task, respecting concurrency limit."""
        async with self._semaphore:
            return await self._cloud.run_skill(
                skill_name, task_str, timeout=60.0
            )

    # ─── Phase 2: Deep extraction + SixtyFour deep search + dark web ─────

    async def _phase2(
        self,
        person: str,
        exa_urls: list[str],
        seen_urls: set[str],
        deep_search_task_id: str | None,
    ) -> AsyncGenerator[AgentResult, None]:
        """Deep URL extraction for uncovered URLs, SixtyFour deep search results, dark web."""
        tasks: list[asyncio.Task] = []
        task_labels: list[str] = []

        # Deep URL extractions (cap at 10)
        covered_domains = set(DOMAIN_TO_SKILL.keys())
        uncovered_urls = [
            url
            for url in exa_urls
            if urlparse(url).netloc.lower().replace("www.", "")
            not in covered_domains
        ][:10]

        for url in uncovered_urls:
            task = asyncio.ensure_future(
                self._deep_extract_with_semaphore(url, person)
            )
            tasks.append(task)
            task_labels.append(f"extract:{url[:60]}")

        # SixtyFour deep search results (if we started one in Phase 0)
        if deep_search_task_id:
            task = asyncio.ensure_future(
                self._sixtyfour.poll_deep_search(deep_search_task_id)
            )
            tasks.append(task)
            task_labels.append("sixtyfour_deep_search")

        # Dark web / HIBP breach check
        if self._settings.hibp_api_key:
            task = asyncio.ensure_future(
                self._cloud.run_skill(
                    "osint_scraper",
                    f"Check Have I Been Pwned for data breaches involving {person}",
                    timeout=30.0,
                )
            )
            tasks.append(task)
            task_labels.append("hibp_check")

        # Yield results as they complete
        for idx, coro in enumerate(asyncio.as_completed(tasks)):
            try:
                result = await coro
                label = task_labels[idx] if idx < len(task_labels) else "phase2"

                if label == "sixtyfour_deep_search":
                    # Parse deep search results
                    if result and result.success and result.rows:
                        snippets = []
                        urls_found = []
                        for row in result.rows[:20]:
                            row_text = ", ".join(
                                f"{k}: {v}" for k, v in row.items() if v
                            )
                            snippets.append(f"[SixtyFour Deep] {row_text[:200]}")
                        urls_found = result.urls_found

                        yield AgentResult(
                            agent_name="sixtyfour_deep",
                            status=AgentStatus.SUCCESS,
                            snippets=snippets,
                            urls_found=urls_found,
                            confidence=0.8,
                            duration_seconds=0.0,
                        )

                elif label == "hibp_check":
                    if result and result.get("success"):
                        output = result.get("output", "")
                        yield AgentResult(
                            agent_name="hibp_breach",
                            status=AgentStatus.SUCCESS,
                            snippets=[output[:500]] if output else [],
                            confidence=0.9,
                        )

                elif isinstance(result, dict) and result.get("success"):
                    output = result.get("output", "")
                    source_url = label.replace("extract:", "")
                    yield AgentResult(
                        agent_name="deep_extract",
                        status=AgentStatus.SUCCESS,
                        snippets=[output[:500]] if output else [],
                        urls_found=[source_url] if source_url.startswith("http") else [],
                        profiles=[
                            SocialProfile(
                                platform="web",
                                url=source_url,
                                display_name=person,
                                raw_data={"extracted": output},
                            )
                        ] if source_url.startswith("http") else [],
                        confidence=self._compute_confidence(output, person),
                    )

            except Exception as exc:
                logger.warning("deep_researcher: phase 2 error: {}", str(exc))

    async def _deep_extract_with_semaphore(
        self, url: str, person: str
    ) -> dict | None:
        async with self._semaphore:
            return await self._cloud.deep_extract_url(
                url, person, timeout=60.0
            )

    # ─── Phase 3: Verification loop + account creation ───────────────────

    async def _phase3(
        self,
        person: str,
        failed_skills: list[tuple[str, str]],
    ) -> AsyncGenerator[AgentResult, None]:
        """Retry failed skills after creating accounts on login-walled platforms."""
        for skill_name, task_str in failed_skills:
            domain = SKILL_TO_DOMAIN.get(skill_name)
            if not domain:
                continue

            signup_url = PLATFORM_SIGNUP_URLS.get(domain)
            if not signup_url:
                continue

            # Try to ensure we have an account
            creds = await self._accounts.ensure_account(
                domain, signup_url, person_name="Specter Agent"
            )
            if not creds:
                logger.info(
                    "deep_researcher: no creds for {}, skipping retry",
                    domain,
                )
                continue

            # Retry with authenticated session
            logger.info(
                "deep_researcher: retrying {} with auth ({})",
                skill_name,
                creds.get("email"),
            )
            try:
                async with self._semaphore:
                    result = await self._cloud.run_skill(
                        skill_name,
                        task_str,
                        timeout=60.0,
                        secrets={
                            domain: f"{creds['email']}:{creds['password']}"
                        },
                    )

                if result and result.get("success"):
                    output = result.get("output", "")
                    yield AgentResult(
                        agent_name=f"skill_{skill_name}_retry",
                        status=AgentStatus.SUCCESS,
                        snippets=[output[:500]] if output else [],
                        profiles=[
                            SocialProfile(
                                platform=skill_name,
                                url="",
                                display_name=person,
                                raw_data={"cloud_output": output, "authenticated": True},
                            )
                        ],
                        confidence=self._compute_confidence(output, person),
                    )
            except Exception as exc:
                logger.warning(
                    "deep_researcher: retry failed for {}: {}",
                    skill_name,
                    exc,
                )

    # ─── Verification helpers ────────────────────────────────────────────

    @staticmethod
    def _verify_result(result: AgentResult, person_name: str) -> bool:
        """Check if a result is about the target person.

        At least one name part must appear in the combined text output.
        Results with no snippets pass (they may have profiles with correct data).
        """
        if not result.snippets:
            return True

        name_parts = person_name.lower().split()
        all_text = " ".join(result.snippets).lower()
        return any(part in all_text for part in name_parts)

    @staticmethod
    def _compute_confidence(output: str, person_name: str) -> float:
        """Compute confidence score based on name match strength."""
        if not output:
            return 0.3

        output_lower = output.lower()
        name_parts = person_name.lower().split()
        matched = sum(1 for part in name_parts if part in output_lower)

        if matched == 0:
            return 0.1
        if matched == len(name_parts):
            # Full name match
            return 1.0
        return 0.3 + (0.7 * matched / len(name_parts))
