"""Instagram research agent using Browser Use Cloud SDK skills with browser-use fallback.

# RESEARCH: Checked instaloader (8k stars), instagram-private-api (archived), instagrapi (5k stars)
# DECISION: Browser Use Cloud SDK skill (Instagram Profile Posts, $0.01/run, ~23s, deterministic)
# FALLBACK: browser-use Agent with Google-first scraping
# ALT: instagrapi for heavier scraping needs (risk of account bans)
"""

from __future__ import annotations

import json

from loguru import logger

from agents.browser_agent import BaseBrowserAgent
from agents.cloud_skills import CloudSkillRunner
from agents.models import (
    AgentResult,
    AgentStatus,
    ResearchRequest,
    SocialProfile,
    parse_human_number,
)
from config import Settings


class InstagramAgent(BaseBrowserAgent):
    """Scrapes Instagram profiles via Cloud SDK skill, falls back to browser-use.

    Primary: Cloud SDK Instagram Profile Posts skill (deterministic, $0.01/run)
    Fallback: browser-use Agent + Google snippet extraction
    """

    agent_name = "instagram"

    def __init__(self, settings: Settings, *, inbox_pool=None):
        super().__init__(settings, inbox_pool=inbox_pool)
        self._cloud = CloudSkillRunner(settings)

    async def _run_task(self, request: ResearchRequest) -> AgentResult:
        # Try Cloud SDK skill first (faster, more reliable)
        if self._cloud.configured:
            cloud_result = await self._try_cloud_skill(request)
            if (
                cloud_result
                and cloud_result.status == AgentStatus.SUCCESS
                and cloud_result.profiles
            ):
                return cloud_result

        # Fallback to Google-scraping via browser-use Agent
        return await self._try_browser_use(request)

    async def _try_cloud_skill(self, request: ResearchRequest) -> AgentResult | None:
        """Try the Instagram Profile Posts marketplace skill."""
        query = self._build_search_query(request)
        task = (
            f"Search for Instagram profile of {query} and extract profile info "
            f"including username, bio, followers, following, and post count."
        )

        try:
            result = await self._cloud.run_skill(
                "instagram_posts",
                task,
                timeout=60.0,
            )

            if not result or not result.get("success"):
                logger.info("instagram cloud skill returned no result, falling back")
                return None

            output = result.get("output", "")
            parsed = _parse_instagram_output(output, request.person_name)

            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.SUCCESS,
                profiles=[parsed["profile"]],
                snippets=parsed["snippets"],
                urls_found=[parsed["profile"].url] if parsed["profile"].url else [],
            )

        except Exception as exc:
            logger.warning("instagram cloud skill error: {}", str(exc))
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
        logger.info("instagram agent (fallback) searching: {}", query)

        try:
            task = (
                "Go to https://www.google.com/search"
                f"?q={query.replace(' ', '+')}+site:instagram.com "
                f"and use the extract tool to get this JSON from the Google results:\n"
                f'{{"username": "", "display_name": "", "bio": "", '
                f'"followers": 0, "following": 0, "post_count": 0, '
                f'"profile_url": ""}}\n'
                f"Extract from Google snippets. Do NOT click into Instagram. Do NOT scroll. "
                f"After extracting, immediately call done with the JSON result."
            )

            agent = self._create_browser_agent(task, max_steps=3)
            result = await agent.run()
            final_result = result.final_result() if result else None

            if final_result:
                parsed = _parse_instagram_output(str(final_result), request.person_name)
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
                snippets=["No Instagram profile found"],
            )

        except ImportError:
            logger.warning("browser-use not available for instagram agent")
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error="browser-use not installed",
            )

        except Exception as exc:
            logger.error("instagram agent error: {}", str(exc))
            return AgentResult(
                agent_name=self.agent_name,
                status=AgentStatus.FAILED,
                error=f"Instagram agent error: {exc}",
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


def _parse_instagram_output(raw_output: str, person_name: str) -> dict:
    """Parse browser-use or Cloud SDK output into structured Instagram profile data."""
    data = _extract_json(raw_output)

    username = data.get("username", "")
    display_name = data.get("display_name", person_name)
    bio = data.get("bio", "")
    followers = parse_human_number(data.get("followers"))
    following = parse_human_number(data.get("following"))
    post_count = parse_human_number(data.get("post_count"))
    is_verified = data.get("is_verified", False)
    is_private = data.get("is_private", False)
    recent_posts = data.get("recent_posts", [])
    profile_url = data.get("profile_url", "")

    raw_data = {
        "post_count": post_count,
        "is_private": is_private,
        "recent_posts": recent_posts,
        "browser_use_output": raw_output,
    }

    profile = SocialProfile(
        platform="instagram",
        url=profile_url if profile_url else f"https://instagram.com/{username}" if username else "",
        username=username or None,
        display_name=display_name,
        bio=bio or None,
        followers=followers,
        following=following,
        verified=bool(is_verified),
        raw_data=raw_data,
    )

    snippets: list[str] = []
    if bio:
        snippets.append(
            f"@{username}: {bio}" if username else f"Instagram: {bio}"
        )
    if followers is not None:
        snippets.append(f"Followers: {followers:,}" if isinstance(followers, int) else "")
    if post_count is not None:
        snippets.append(f"Posts: {post_count}")
    if is_private:
        snippets.append("Account is private")
    if recent_posts:
        for post in recent_posts[:3]:
            caption = post.get("caption", "")
            if caption:
                snippets.append(f"Post: {caption[:150]}")
    if not snippets:
        snippets.append(raw_output[:500])

    snippets = [s for s in snippets if s]

    return {"profile": profile, "snippets": snippets}
