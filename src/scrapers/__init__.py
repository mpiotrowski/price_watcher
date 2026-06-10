from __future__ import annotations

from typing import Callable

from scrapers.amazon import scrape as _amazon_scrape
from scrapers.microcenter import ScrapeResult, scrape as _mc_scrape
from scrapers.unifi import scrape as _unifi_scrape

_REGISTRY: dict[str, Callable[..., ScrapeResult]] = {
    "amazon": _amazon_scrape,
    "microcenter": _mc_scrape,
    "unifi": _unifi_scrape,
}


def get_scraper(retailer_id: str) -> Callable[..., ScrapeResult]:
    scraper = _REGISTRY.get(retailer_id)
    if scraper is None:
        raise ValueError(f"No scraper registered for retailer: {retailer_id!r}")
    return scraper
