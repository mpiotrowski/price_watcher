#!/usr/bin/env python3
"""
Fetch all MicroCenter store IDs and names from their website.

Usage (inside container):
    python src/list_stores.py

Usage (local, with venv active):
    PYTHONPATH=src python src/list_stores.py
"""
from __future__ import annotations

import json
import re
import sys

from bs4 import BeautifulSoup
from curl_cffi import requests


def fetch_stores() -> list[dict[str, str]]:
    response = requests.get(
        "https://www.microcenter.com/",
        impersonate="chrome124",
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    soup = BeautifulSoup(html, "lxml")
    stores: list[dict[str, str]] = []

    # Strategy 1: <select> or <ul> store picker with option values
    for select in soup.find_all("select"):
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            name = option.get_text(strip=True)
            if val.isdigit() and len(val) <= 3 and name:
                stores.append({"id": val.zfill(3), "name": name})

    if stores:
        return _dedupe(stores)

    # Strategy 2: JSON blob in a <script> tag
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for patterns like {storeID: "055", storeName: "..."} or similar
        matches = re.findall(
            r'"(?:storeID?|store_id|storeid)"\s*:\s*"?(\d{2,3})"?.*?"(?:storeName?|store_name|name)"\s*:\s*"([^"]+)"',
            text,
            re.IGNORECASE,
        )
        for store_id, name in matches:
            stores.append({"id": store_id.zfill(3), "name": name})

    if stores:
        return _dedupe(stores)

    # Strategy 3: anchor links like /store/055/madison-heights
    for a in soup.find_all("a", href=True):
        m = re.search(r"/store/(\d{2,3})/", a["href"])
        if m:
            store_id = m.group(1).zfill(3)
            name = a.get_text(strip=True)
            if name:
                stores.append({"id": store_id, "name": name})

    return _dedupe(stores)


def _dedupe(stores: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for s in stores:
        if s["id"] not in seen:
            seen.add(s["id"])
            result.append(s)
    return sorted(result, key=lambda s: s["id"])


if __name__ == "__main__":
    print("Fetching store list from microcenter.com …", flush=True)
    stores = fetch_stores()

    if not stores:
        print("No stores found — the page structure may have changed.", file=sys.stderr)
        sys.exit(1)

    print(f"\nFound {len(stores)} store(s):\n")
    print(f"{'ID':<6} {'Name'}")
    print("-" * 40)
    for s in stores:
        print(f"{s['id']:<6} {s['name']}")

    # Also emit YAML-ready block for easy copy-paste into products.yml
    print("\n# --- Copy into products.yml stores section ---")
    for s in stores:
        print(f'  - id: "{s["id"]}"\n    name: "{s["name"]}"')
