#!/usr/bin/env python3
"""One-time migration: add Unifi retailer and online store."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy.orm import Session
from db import add_retailer, add_store, init_db, Retailer


def run(database_url: str) -> None:
    engine = init_db(database_url)
    with Session(engine) as session:
        if session.get(Retailer, "unifi") is not None:
            print("Unifi retailer already exists, skipping.")
            return

        add_retailer(session, "unifi", "Unifi", "https://store.ui.com")
        print("Added retailer: unifi")

        add_store(session, "unifi", "online", "Unifi Online Store")
        print("Added store: unifi/online")


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    run(url)
