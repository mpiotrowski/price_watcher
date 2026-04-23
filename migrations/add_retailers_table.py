#!/usr/bin/env python3
"""
Migration: introduce retailers table; give stores a surrogate integer PK and
store_code column; update tracked_products.store_id to integer FK; rename
price_snapshots.store_id to store_code.

Run once against an existing database:
    DATABASE_URL=sqlite:////data/mc_watcher.db python migrations/add_retailers_table.py
"""

import os
import sys
import sqlite3


def run(database_url: str) -> None:
    db_path = database_url.replace("sqlite:///", "")

    conn = sqlite3.connect(db_path)
    # Must be set outside a transaction to take effect
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")

    cur = conn.cursor()

    # Guard: skip if already fully migrated (check stores has the new store_code column)
    stores_columns = {row[1] for row in cur.execute("PRAGMA table_info(stores)")}
    if "store_code" in stores_columns:
        print("Migration already applied.")
        conn.close()
        return

    # Clean up any partial state from a previous failed attempt
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for tmp in ("stores_new", "tracked_products_new", "price_snapshots_new"):
        if tmp in tables:
            cur.execute(f"DROP TABLE {tmp}")
            print(f"Dropped leftover table: {tmp}")
    if "retailers" not in tables:
        pass  # will be created below
    else:
        print("Partial migration detected — resuming from clean state.")

    # 1. Create retailers table and seed MicroCenter (may already exist from partial run)
    if "retailers" not in tables:
        cur.execute("""
            CREATE TABLE retailers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT,
                created_at DATETIME DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            INSERT INTO retailers (id, name, base_url)
            VALUES ('microcenter', 'MicroCenter', 'https://www.microcenter.com')
        """)
        print("Created retailers table and seeded MicroCenter.")
    else:
        print("retailers table already present, skipping create.")

    # 2. Rebuild stores: integer surrogate PK, retailer_id, store_code
    cur.execute("""
        CREATE TABLE stores_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer_id TEXT NOT NULL,
            store_code TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT (datetime('now')),
            UNIQUE (retailer_id, store_code)
        )
    """)
    cur.execute("""
        INSERT INTO stores_new (retailer_id, store_code, name, created_at)
        SELECT 'microcenter', id, name, created_at FROM stores
    """)
    store_map = {row[1]: row[0] for row in cur.execute("SELECT id, store_code FROM stores_new")}
    print(f"Rebuilt stores table ({len(store_map)} store(s)).")

    # 3. Rebuild tracked_products: store_id TEXT -> INTEGER
    cur.execute("""
        CREATE TABLE tracked_products_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            name TEXT,
            check_interval INTEGER,
            price_threshold REAL,
            active INTEGER NOT NULL DEFAULT 1,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT (datetime('now')),
            UNIQUE (url, store_id)
        )
    """)
    product_rows = cur.execute("""
        SELECT id, url, store_id, name, check_interval, price_threshold,
               active, consecutive_failures, created_at
        FROM tracked_products
    """).fetchall()
    skipped = 0
    for row in product_rows:
        new_store_id = store_map.get(row[2])
        if new_store_id is None:
            print(f"  WARNING: store_code {row[2]!r} not found — skipping product #{row[0]}")
            skipped += 1
            continue
        cur.execute("""
            INSERT INTO tracked_products_new
                (id, url, store_id, name, check_interval, price_threshold,
                 active, consecutive_failures, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (row[0], row[1], new_store_id, row[3], row[4], row[5], row[6], row[7], row[8]))
    print(f"Rebuilt tracked_products table ({len(product_rows) - skipped} product(s), {skipped} skipped).")

    # 4. Rebuild price_snapshots: rename store_id -> store_code
    cur.execute("""
        CREATE TABLE price_snapshots_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_url TEXT NOT NULL,
            store_code TEXT NOT NULL,
            product_name TEXT NOT NULL,
            price REAL,
            in_stock INTEGER NOT NULL,
            checked_at DATETIME DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        INSERT INTO price_snapshots_new
            (id, product_url, store_code, product_name, price, in_stock, checked_at)
        SELECT id, product_url, store_id, product_name, price, in_stock, checked_at
        FROM price_snapshots
    """)
    snapshot_count = cur.execute("SELECT COUNT(*) FROM price_snapshots_new").fetchone()[0]
    print(f"Rebuilt price_snapshots table ({snapshot_count} snapshot(s)).")

    # 5. Swap in new tables
    cur.execute("DROP TABLE price_snapshots")
    cur.execute("ALTER TABLE price_snapshots_new RENAME TO price_snapshots")

    cur.execute("DROP TABLE tracked_products")
    cur.execute("ALTER TABLE tracked_products_new RENAME TO tracked_products")

    cur.execute("DROP TABLE stores")
    cur.execute("ALTER TABLE stores_new RENAME TO stores")

    # 6. Recreate indexes
    cur.execute("CREATE INDEX ix_price_snapshots_product_url ON price_snapshots (product_url)")
    cur.execute("CREATE INDEX ix_price_snapshots_store_code ON price_snapshots (store_code)")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    run(url)
