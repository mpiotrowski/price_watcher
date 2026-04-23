#!/usr/bin/env python3
"""One-time migration: add consecutive_failures column to tracked_products."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text
from db import init_db


def run(database_url: str) -> None:
    engine = init_db(database_url)
    with engine.connect() as conn:
        # Check if the column already exists
        result = conn.execute(text("PRAGMA table_info(tracked_products)"))
        columns = [row[1] for row in result]
        if "consecutive_failures" in columns:
            print("Column already exists, nothing to do.")
            return

        conn.execute(text(
            "ALTER TABLE tracked_products ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
    print("Done — added consecutive_failures column.")


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    run(url)
