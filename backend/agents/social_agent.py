"""Broader social/web presence agent using Cloud SDK skills + browser-use fallback.

# RESEARCH: Checked PyGithub (7k stars), praw (3.5k stars, Reddit)
# DECISION: Browser Use Cloud SDK for TikTok, Facebook, Linktree ($0.01/run each, parallel)
# FALLBACK: browser-use Agent for Reddit, GitHub, Medium, Substack, Stack Overflow
# ALT: Individual API wrappers (more reliable but 5+ dependencies)
"""

from __future__ import annotations

import asyncio

from loguru import logger

from agents.browser_agent import BaseBrowserAgent
from agents.cloud_skills import CloudSkillRunner
from agents.models import AgentResult, AgentStatus, ResearchRequest, SocialProfile
from config import Settings


class SocialAgent(BaseBrowserAgent):
    """Scrapes broader web presence using Cloud SDK skills + browser-use fallback.

    Primary (parallel): TikTok, Facebook, Linktree via Cloud SDK marketplace skills
    Fallback: browser-use Agent Google search for Reddit, GitHub, Medium, Substack, etc.
    """

    agent_name = "social"

    def __init__(self, settings: Settings, *, inbox_pool=None):
        super().__init__(settings, inbox_pool=inbox_pool)
        self._cloud = CloudSkillRunner(settings)

    async def _run_task(self, request: ResearchRequest) -> AgentResult:
        profiles: list[SocialProfile] = []
        snippets: list[str] = []
        urls_found: list[str] = []

        # Run Cloud SDK skills and browser-use fallback in parallel
        tasks = []

        if self._cloud.configured:
            tasks.append(self._run_cloud_skills(request))

        if self.configured:
            tasks.append(self._run_browser_search(request))

        if not tasks:
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error="No search backend configured",
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("social agent sub-task error: {}", str(result))
                continue
            if isinstance(result, AgentResult) and result.status == AgentStatus.SUCCESS:
                profiles.extend(result.profiles)
                snippets.extend(result.snippets)
                urls_found.extend(result.urls_found)

        return AgentResult(
            agent_name=self.agent_name,
            status=AgentStatus.SUCCESS if (profiles or snippets) else AgentStatus.FAILED,
            profiles=profiles,
            snippets=snippets or ["No broader social presence found"],
            urls_found=urls_found,
        )

    async def _run_cloud_skills(self, request: ResearchRequest) -> AgentResult:
        """Run TikTok, Facebook, and Linktree skills in parallel."""
        query = self._build_search_query(request)
        profiles: list[SocialProfile] = []
        snippets: list[str] = []
        urls_found: list[str] = []

        skill_tasks = [
            self._cloud.run_skill(
                "tiktok_profile",
                f"Get the TikTok profile info for {query}",
                timeout=45.0,
            ),
            self._cloud.run_skill(
                "facebook_page",
                f"Search for Facebook page or profile of {query}",
                timeout=45.0,
            ),
            self._cloud.run_skill(
                "linktree_profile",
                f"Find the Linktree profile for {query}",
                timeout=45.0,
            ),
        ]

        results = await asyncio.gather(*skill_tasks, return_exceptions=True)
        skill_names = ["tiktok", "facebook", "linktree"]

        for skill_name, result in zip(skill_names, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("social cloud skill {} error: {}", skill_name, str(result))
                continue
            if result is None or not result.get("success"):
                continue

            output = result.get("output", "")
            if not output:
                continue

            profile = SocialProfile(
                platform=skill_name,
                url=f"https://{skill_name}.com",
                display_name=request.person_name,
                raw_data={"cloud_skill_output": output},
            )
            profiles.append(profile)
            snippets.append(f"[{skill_name.title()}] {output[:300]}")
            urls_found.append(profile.url)

        return AgentResult(
            agent_name=self.agent_name,
            status=AgentStatus.SUCCESS if profiles else AgentStatus.FAILED,
            profiles=profiles,
            snippets=snippets,
            urls_found=urls_found,
        )

    async def _run_browser_search(self, request: ResearchRequest) -> AgentResult:
        """Fallback: Google search for Reddit, GitHub, Medium, etc."""
        query = self._build_search_query(request)
        logger.info("social agent (browser fallback) searching: {}", query)

        try:
            task = (
                "Go to https://www.google.com/search"
                f"?q={query.replace(' ', '+')}"
                "+site:github.com+OR+site:reddit.com"
                "+OR+site:medium.com+OR+site:substack.com "
                "and extract from the FIRST page only:\n"
                "For each platform found, note: platform name, "
                "profile URL, username, bio snippet.\n"
                f"If no profiles found, say so. Do NOT scroll. Do NOT click into results. "
                f"After extracting, immediately call done with the result."
            )

            agent = self._create_browser_agent(task, max_steps=3)
            result = await agent.run()
            final_result = result.final_result() if result else None

            if final_result:
                output_str = str(final_result)
                profiles: list[SocialProfile] = []
                urls_found: list[str] = []

                platform_indicators = {
                    "github.com": "github",
                    "reddit.com": "reddit",
                    "medium.com": "medium",
                    "substack.com": "substack",
                    "stackoverflow.com": "stackoverflow",
                    "stackexchange.com": "stackexchange",
                    "dev.to": "devto",
                    "hashnode.dev": "hashnode",
                }

                for indicator, platform in platform_indicators.items():
                    if indicator in output_str.lower():
                        url = f"https://{indicator}"
                        profiles.append(
                            SocialProfile(
                                platform=platform,
                                url=url,
                                display_name=request.person_name,
                            )
                        )
                        urls_found.append(url)

                return AgentResult(
                    agent_name=self.agent_name,
                    status=AgentStatus.SUCCESS,
                    profiles=profiles,
                    snippets=[output_str],
                    urls_found=urls_found,
                )

            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.SUCCESS,
                snippets=["No broader social presence found via Google"],
            )

        except ImportError:
            logger.warning("browser-use not available for social agent")
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error="browser-use not installed",
            )

        except Exception as exc:
            logger.error("social agent browser error: {}", str(exc))
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error=f"Social agent error: {exc}",
            )
