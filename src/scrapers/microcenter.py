"""
MicroCenter product scraper.

Uses curl_cffi to impersonate a real browser TLS fingerprint, bypassing
Cloudflare. Sets the `storeSelected` cookie so the page returns stock for
the requested store.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from curl_cffi import requests

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    product_name: str
    price: float | None
    in_stock: bool
    store_id: str
    url: str


def scrape(url: str, store_id: str, debug: bool = False) -> ScrapeResult:
    """
    Fetch a MicroCenter product page for the given store and extract
    price and stock status.

    Args:
        url: Full MicroCenter product URL.
        store_id: MicroCenter store ID (e.g. "055").
        debug: When True, saves raw HTML to /tmp/mc_debug.html.
    """
    response = requests.get(
        url,
        impersonate="chrome124",
        cookies={"storeSelected": store_id},
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    if debug:
        with open("/tmp/mc_debug.html", "w") as f:
            f.write(html)
        logger.debug("Saved raw HTML to /tmp/mc_debug.html")

    soup = BeautifulSoup(html, "lxml")

    product_name = _parse_name(soup, url)
    price = _parse_price(soup)
    in_stock = _parse_stock(soup)

    return ScrapeResult(
        product_name=product_name,
        price=price,
        in_stock=in_stock,
        store_id=store_id,
        url=url,
    )


def _parse_name(soup: BeautifulSoup, url: str) -> str:
    # Try <h1> first (most product pages)
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    # Try JSON-LD
    name = _jsonld_value(soup, "name")
    if name:
        return str(name)

    # Try <title>
    title = soup.find("title")
    if title:
        return title.get_text(strip=True).split("|")[0].strip()

    return url


def _parse_price(soup: BeautifulSoup) -> float | None:
    # 1. JSON-LD offers.price (most stable)
    price = _jsonld_offer_price(soup)
    if price is not None:
        return price

    # 2. itemprop="price"
    el = soup.find(attrs={"itemprop": "price"})
    if el:
        raw = el.get("content") or el.get_text(strip=True)
        parsed = _parse_price_string(raw)
        if parsed is not None:
            return parsed

    # 3. Common CSS selectors used by MicroCenter
    for selector in ("#pricing", ".price", ".product-price", '[class*="price"]'):
        el = soup.select_one(selector)
        if el:
            parsed = _parse_price_string(el.get_text(strip=True))
            if parsed is not None:
                return parsed

    logger.warning("Could not parse price — run with debug=True to inspect HTML")
    return None


def _parse_stock(soup: BeautifulSoup) -> bool:
    # Primary: MicroCenter's inventory div
    el = soup.find("div", class_="inventory")
    if el:
        text = el.get_text(strip=True).lower()
        if "out of stock" in text:
            return False
        if re.search(r"\d+\s+in\s+stock", text) or "in stock" in text:
            return True
        # Div exists but text is unexpected — log it for debugging
        logger.warning("Unexpected inventory div text: %r", el.get_text(strip=True))
        return False

    logger.warning("No .inventory div found — run with debug=True to inspect HTML")
    return False


# ── JSON-LD helpers ──────────────────────────────────────────────────────────

def _get_jsonld(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") in ("Product", "IndividualProduct"):
                        return item
            elif data.get("@type") in ("Product", "IndividualProduct"):
                return data
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def _jsonld_value(soup: BeautifulSoup, key: str):
    data = _get_jsonld(soup)
    return data.get(key) if data else None


def _jsonld_offer_price(soup: BeautifulSoup) -> float | None:
    data = _get_jsonld(soup)
    if not data:
        return None
    offers = data.get("offers") or data.get("Offers")
    if not offers:
        return None
    if isinstance(offers, list):
        offers = offers[0]
    raw = offers.get("price") or offers.get("lowPrice")
    return _parse_price_string(str(raw)) if raw is not None else None


# ── Price string parser ──────────────────────────────────────────────────────

def _parse_price_string(text: str | None) -> float | None:
    if not text:
        return None
    # Strip currency symbols and commas, then extract the first number
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    match = re.search(r"\d+\.?\d*", cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None
