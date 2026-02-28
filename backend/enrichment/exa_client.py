from __future__ import annotations

from loguru import logger

from config import Settings
from enrichment.models import EnrichmentHit, EnrichmentRequest, EnrichmentResult


class ExaEnrichmentClient:
    """Settings-aware seam for Exa enrichment integration.

    Implements the EnrichmentClient protocol from enrichment/__init__.py.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.exa_api_key)

    def build_person_query(self, name: str, company: str | None = None) -> str:
        if company:
            return f'"{name}" "{company}"'
        return f'"{name}"'

    async def enrich_person(self, request: EnrichmentRequest) -> EnrichmentResult:
        query = self.build_person_query(request.name, request.company)
        logger.info("ExaEnrichmentClient.enrich_person query={}", query)

        if not self.configured:
            return EnrichmentResult(
                query=query,
                success=False,
                error="Exa API key not configured (EXA_API_KEY missing)",
            )

        # Placeholder: real Exa call goes here
        return EnrichmentResult(
            query=query,
            hits=[
                EnrichmentHit(
                    title=f"Result for {request.name}",
                    url="https://example.com",
                    snippet="Placeholder result",
                    score=0.5,
                    source="exa",
                )
            ],
        )
