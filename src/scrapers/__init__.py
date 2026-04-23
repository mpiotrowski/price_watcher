from __future__ import annotations

from typing import Callable

from scrapers.microcenter import ScrapeResult, scrape as _mc_scrape

_REGISTRY: dict[str, Callable[..., ScrapeResult]] = {
    "microcenter": _mc_scrape,
}


def get_scraper(retailer_id: str) -> Callable[..., ScrapeResult]:
    scraper = _REGISTRY.get(retailer_id)
    if scraper is None:
        raise ValueError(f"No scraper registered for retailer: {retailer_id!r}")
    return scraper
