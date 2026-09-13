from __future__ import annotations

from app.config import Settings
from app.research.apify_client import ApifyActiveSource, ApifyClient, ApifySoldSource
from app.research.ebay_browse import EbayBrowseSource
from app.research.sources import CompsSource, FixtureCompsSource


def build_comps_sources(settings: Settings) -> list[CompsSource]:
    """Real sources when keys exist, the labeled fixture otherwise, nothing when research is off."""
    if settings.research_mode == "off":
        return []
    if settings.research_mode == "fixture":
        return [FixtureCompsSource()]
    sources: list[CompsSource] = []
    if settings.apify_token:
        client = ApifyClient(settings.apify_token)
        sources.extend([ApifySoldSource(client), ApifyActiveSource(client)])
    if settings.ebay_client_id and settings.ebay_client_secret:
        sources.append(EbayBrowseSource(settings.ebay_client_id, settings.ebay_client_secret))
    return sources or [FixtureCompsSource()]
