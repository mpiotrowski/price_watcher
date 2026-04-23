#!/usr/bin/env python3
"""One-time migration: populate the stores table with all known Microcenter locations."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy.orm import Session
from db import Store, init_db

STORES = [
    ("205", "AZ - Phoenix"),
    ("195", "CA - Santa Clara"),
    ("101", "CA - Tustin"),
    ("181", "CO - Denver"),
    ("185", "FL - Miami"),
    ("065", "GA - Duluth"),
    ("041", "GA - Marietta"),
    ("151", "IL - Chicago"),
    ("025", "IL - Westmont"),
    ("165", "IN - Indianapolis"),
    ("191", "KS - Overland Park"),
    ("121", "MA - Cambridge"),
    ("085", "MD - Rockville"),
    ("125", "MD - Parkville"),
    ("055", "MI - Madison Heights"),
    ("045", "MN - St. Louis Park"),
    ("095", "MO - Brentwood"),
    ("175", "NC - Charlotte"),
    ("075", "NJ - North Jersey"),
    ("171", "NY - Westbury"),
    ("115", "NY - Brooklyn"),
    ("145", "NY - Flushing"),
    ("105", "NY - Yonkers"),
    ("141", "OH - Columbus"),
    ("051", "OH - Mayfield Heights"),
    ("071", "OH - Sharonville"),
    ("061", "PA - St. Davids"),
    ("155", "TX - Houston"),
    ("131", "TX - Dallas"),
    ("081", "VA - Fairfax"),
    ("029", "Shippable Items"),
]


def run(database_url: str) -> None:
    engine = init_db(database_url)
    with Session(engine) as session:
        existing_ids = {s.id for s in session.query(Store).all()}
        added = 0
        for store_id, name in STORES:
            if store_id in existing_ids:
                print(f"  skip  {store_id}  {name}")
                continue
            session.add(Store(id=store_id, name=name))
            print(f"  add   {store_id}  {name}")
            added += 1
        session.commit()
    print(f"\nDone — {added} store(s) inserted, {len(STORES) - added} already present.")


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    run(url)
