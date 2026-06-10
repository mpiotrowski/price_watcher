from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup
from curl_cffi import requests

from scrapers.microcenter import ScrapeResult

logger = logging.getLogger(__name__)


def scrape(url: str, store_code: str, debug: bool = False) -> ScrapeResult:
    response = requests.get(
        url,
        impersonate="chrome124",
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    if debug:
        with open("/tmp/amazon_debug.html", "w") as f:
            f.write(html)
        logger.debug("Saved raw HTML to /tmp/amazon_debug.html")

    soup = BeautifulSoup(html, "lxml")

    product_name = _parse_name(soup, url)
    price = _parse_price(soup)
    in_stock = _parse_stock(soup)

    return ScrapeResult(
        product_name=product_name,
        price=price,
        in_stock=in_stock,
        store_code=store_code,
        url=url,
    )


def _parse_name(soup: BeautifulSoup, url: str) -> str:
    title_tag = soup.find(id="productTitle")
    if title_tag:
        return title_tag.get_text(strip=True)

    tag = soup.find("title")
    if tag:
        text = tag.get_text(strip=True)
        text = re.sub(r"\s*[-:]\s*Amazon\.com.*$", "", text, flags=re.IGNORECASE)
        if text:
            return text

    return url


def _parse_price(soup: BeautifulSoup) -> float | None:
    # 1. JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), None)
            if data and data.get("@type") == "Product":
                offers = data.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw = offers.get("price")
                if raw is not None:
                    return float(raw)
        except (json.JSONDecodeError, AttributeError, ValueError):
            continue

    # 2. .a-price .a-offscreen (primary displayed price)
    offscreen = soup.select_one(".a-price .a-offscreen")
    if offscreen:
        parsed = _parse_price_string(offscreen.get_text())
        if parsed is not None:
            return parsed

    # 3. Legacy price blocks
    for selector in ("#priceblock_ourprice", "#priceblock_dealprice"):
        tag = soup.select_one(selector)
        if tag:
            parsed = _parse_price_string(tag.get_text())
            if parsed is not None:
                return parsed

    return None


def _parse_stock(soup: BeautifulSoup) -> bool:
    availability = soup.find(id="availability")
    if not availability:
        return False
    text = availability.get_text(separator=" ", strip=True).lower()
    return "in stock" in text


def _parse_price_string(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", raw)
    try:
        return float(cleaned)
    except ValueError:
        return None
