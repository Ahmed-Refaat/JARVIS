"""LinkedIn research agent using Cloud SDK skills with browser-use fallback.

# RESEARCH: Checked linkedin-api (2k stars, unofficial), linkedin-scraper (archived)
# DECISION: Browser Use Cloud SDK skills (LinkedIn Company Posts $0.01/run, deterministic)
# FALLBACK: browser-use Agent + Google snippet extraction
# ALT: linkedin-api (gets rate-limited fast, account bans)
"""

from __future__ import annotations

import json

from loguru import logger

from agents.browser_agent import BaseBrowserAgent
from agents.cloud_skills import CloudSkillRunner
from agents.models import AgentResult, AgentStatus, ResearchRequest, SocialProfile
from config import Settings


class LinkedInAgent(BaseBrowserAgent):
    """Scrapes LinkedIn profiles via Cloud SDK skill, falls back to browser-use.

    Primary: Cloud SDK LinkedIn Company Posts skill (no cookies needed, $0.01/run)
    Fallback: browser-use Agent + Google snippet extraction
    """

    agent_name = "linkedin"

    def __init__(self, settings: Settings, *, inbox_pool=None):
        super().__init__(settings, inbox_pool=inbox_pool)
        self._cloud = CloudSkillRunner(settings)

    async def _run_task(self, request: ResearchRequest) -> AgentResult:
        # Try Cloud SDK skill first
        if self._cloud.configured:
            cloud_result = await self._try_cloud_skill(request)
            if (
                cloud_result
                and cloud_result.status == AgentStatus.SUCCESS
                and cloud_result.profiles
            ):
                return cloud_result

        # Fallback to Google-scraping
        return await self._try_browser_use(request)

    async def _try_cloud_skill(self, request: ResearchRequest) -> AgentResult | None:
        """Try LinkedIn marketplace skills via Cloud SDK."""
        query = self._build_search_query(request)

        # Use LinkedIn Company Posts skill for company-affiliated searches
        task = (
            f"Find the LinkedIn profile for {query} and extract their professional information "
            f"including full name, headline, current company, title, location, and about section."
        )

        try:
            result = await self._cloud.run_skill(
                "linkedin_company_posts",
                task,
                timeout=45.0,
            )

            if not result or not result.get("success"):
                logger.info("linkedin cloud skill returned no result, falling back")
                return None

            output = result.get("output", "")
            parsed = _parse_linkedin_output(output, request.person_name)

            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.SUCCESS,
                profiles=[parsed["profile"]],
                snippets=parsed["snippets"],
                urls_found=[parsed["profile"].url] if parsed["profile"].url else [],
            )

        except Exception as exc:
            logger.warning("linkedin cloud skill error: {}", str(exc))
            return None

    async def _try_browser_use(self, request: ResearchRequest) -> AgentResult:
        """Fallback: Google-first scraping via browser-use Agent."""
        if not self.configured:
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error="Browser Use not configured (BROWSER_USE_API_KEY or OPENAI_API_KEY missing)",
            )

        query = self._build_search_query(request)
        logger.info("linkedin agent (fallback) searching: {}", query)

        try:
            task = (
                f"Go to https://www.google.com/search?q={query.replace(' ', '+')}+LinkedIn+profile "
                f"and use the extract tool on the search results to get this JSON:\n"
                f'{{"full_name": "", "headline": "", "location": "", "about": "", '
                f'"current_company": "", "current_title": "", "profile_url": ""}}\n'
                f"Extract from Google's snippets and knowledge panel. "
                f"Do NOT click into LinkedIn. Do NOT scroll. "
                f"After extracting, immediately call done with the JSON result."
            )

            agent = self._create_browser_agent(task, max_steps=3)
            result = await agent.run()
            final_result = result.final_result() if result else None

            if final_result:
                parsed = _parse_linkedin_output(str(final_result), request.person_name)
                return AgentResult(
                    agent_name=self.agent_name,
                    status=AgentStatus.SUCCESS,
                    profiles=[parsed["profile"]],
                    snippets=parsed["snippets"],
                    urls_found=[parsed["profile"].url] if parsed["profile"].url else [],
                )

            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.SUCCESS,
                snippets=["No LinkedIn profile found"],
            )

        except ImportError:
            logger.warning("browser-use not available, returning empty result")
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error="browser-use not installed",
            )

        except Exception as exc:
            logger.error("linkedin agent error: {}", str(exc))
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error=f"LinkedIn agent error: {exc}",
            )


def _extract_json(raw: str) -> dict:
    """Robustly extract JSON from browser-use output."""
    cleaned = raw.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
    cleaned = cleaned.strip()

    for text in [cleaned, raw]:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                pass
    return {}


def _parse_linkedin_output(
    raw_output: str, person_name: str
) -> dict:
    """Parse browser-use or Cloud SDK output into structured profile data."""
    data = _extract_json(raw_output)

    profile_url = data.get("profile_url", "")
    display_name = data.get("full_name", person_name)
    headline = data.get("headline", "")
    location = data.get("location")
    about = data.get("about", "")
    current_company = data.get("current_company", "")
    current_title = data.get("current_title", "")
    experience = data.get("experience", [])
    education = data.get("education", [])
    skills = data.get("skills", [])
    connections = data.get("connections_count")
    recent_posts = data.get("recent_posts", [])

    raw_data = {
        "headline": headline,
        "about": about,
        "current_company": current_company,
        "current_title": current_title,
        "experience": experience,
        "education": education,
        "skills": skills,
        "connections_count": connections,
        "recent_posts": recent_posts,
        "browser_use_output": raw_output,
    }

    followers_count = None
    if connections:
        try:
            cleaned = str(connections).replace(",", "").replace("+", "").strip()
            followers_count = int(cleaned)
        except (ValueError, TypeError):
            pass

    profile = SocialProfile(
        platform="linkedin",
        url=profile_url if profile_url else f"https://linkedin.com/search?q={person_name}",
        display_name=display_name,
        bio=headline if headline else about[:200] if about else None,
        followers=followers_count,
        location=location,
        raw_data=raw_data,
    )

    snippets: list[str] = []
    if headline:
        snippets.append(f"LinkedIn: {display_name} — {headline}")
    if about:
        snippets.append(f"About: {about[:300]}")
    if experience:
        exp_strs = [
            f"{e.get('title', '?')} at {e.get('company', '?')}" for e in experience[:3]
        ]
        snippets.append(f"Experience: {'; '.join(exp_strs)}")
    if education:
        edu_strs = [
            f"{e.get('degree', '')} {e.get('field', '')} @ {e.get('school', '?')}"
            for e in education[:2]
        ]
        snippets.append(f"Education: {'; '.join(edu_strs)}")
    if skills:
        snippets.append(f"Skills: {', '.join(skills[:10])}")
    if recent_posts:
        for post in recent_posts[:2]:
            text = post.get("text", "")
            if text:
                snippets.append(f"Post: {text[:150]}")
    if not snippets:
        snippets.append(raw_output[:500])

    return {"profile": profile, "snippets": snippets}
