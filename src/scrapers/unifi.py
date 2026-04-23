from __future__ import annotations

import json
import logging

from bs4 import BeautifulSoup
from curl_cffi import requests

from scrapers.microcenter import ScrapeResult

logger = logging.getLogger(__name__)

_INSTOCK_URI = "https://schema.org/InStock"


def scrape(url: str, store_code: str, debug: bool = False) -> ScrapeResult:
    response = requests.get(
        url,
        impersonate="chrome124",
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    if debug:
        with open("/tmp/unifi_debug.html", "w") as f:
            f.write(html)
        logger.debug("Saved raw HTML to /tmp/unifi_debug.html")

    soup = BeautifulSoup(html, "lxml")
    data = _get_jsonld(soup)

    if not data:
        raise ValueError(f"No JSON-LD Product block found on {url}")

    product_name = data.get("name") or url
    offers = data.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0]

    price_spec = offers.get("priceSpecification") or {}
    raw_price = price_spec.get("price") or offers.get("price")
    price = float(raw_price) if raw_price is not None else None

    in_stock = offers.get("availability") == _INSTOCK_URI

    return ScrapeResult(
        product_name=str(product_name),
        price=price,
        in_stock=in_stock,
        store_code=store_code,
        url=url,
    )


def _get_jsonld(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product":
                        return item
            elif data.get("@type") == "Product":
                return data
        except (json.JSONDecodeError, AttributeError):
            continue
    return None
