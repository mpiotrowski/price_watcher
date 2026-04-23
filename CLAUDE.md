# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run locally (development):**
```bash
PYTHONPATH=src python src/main.py
```

**Docker (production):**
```bash
docker compose up --build -d
docker compose logs -f
```

**Lint:**
```bash
ruff check src/
ruff format src/
```

**Tests:**
```bash
pytest
pytest tests/test_scraper.py  # single file
```

**Install dev dependencies:**
```bash
pip install -e ".[dev]"
```

**Scrape a single product interactively (debug mode):**
```python
# run with PYTHONPATH=src python -c "..."
from scrapers.microcenter import scrape
result = scrape("https://www.microcenter.com/product/.../name", "055", debug=True)
# HTML saved to /tmp/mc_debug.html
```

## Environment

Copy `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — your Telegram chat/group ID
- `DATABASE_URL` — defaults to `sqlite:////data/mc_watcher.db`

## Architecture

The app is a long-running Python process with two concurrent threads:

1. **APScheduler (background thread)** — `src/scheduler.py`  
   Runs one `run_check` job per `(TrackedProduct, store)` pair on an interval. Each job: scrapes the product page, compares to the last `PriceSnapshot`, sends a Telegram notification if stock or price changed, then saves a new snapshot.

2. **Telegram long-poll loop (main thread)** — `src/telegram_listener.py`  
   Calls `getUpdates` in a blocking loop. Handles commands: `/list`, `/add`, `/remove`, `/stores`, `/addstore`, `/removestore`. Commands that add/remove products also add/remove the corresponding scheduler job in real time.

**Data flow:**
- `config/products.yml` → parsed by `src/config.py` → seeded into SQLite on first run by `main.py:seed_from_yaml`
- After first seed, products/stores are managed exclusively via Telegram bot commands
- `config/products.yml` is mounted as a live volume in Docker — changes there only take effect if the DB is empty (seed only runs once)

**Key modules:**
- `src/db.py` — SQLAlchemy ORM models (`Store`, `TrackedProduct`, `PriceSnapshot`) and CRUD functions. `remove_product` soft-deletes (sets `active=False`) to preserve price history.
- `src/scrapers/microcenter.py` — uses `curl_cffi` to impersonate Chrome TLS (bypasses Cloudflare). Sets `storeSelected` cookie to get per-store inventory. Parses price via JSON-LD → `itemprop` → CSS selectors, in that priority order.
- `src/notifier.py` — thin wrappers around Telegram `sendMessage` with HTML parse mode. All message formatting lives here.

**Failure handling:**
- `consecutive_failures` on `TrackedProduct` tracks scrape errors. Telegram alert fires on the **first** failure only; a recovery alert fires when scraping succeeds again after failures.

**Migrations:**
- `migrations/` contains standalone scripts run manually, not auto-applied. Run them directly with `python migrations/<script>.py` against the DB.

## Configuration

`config/products.yml` structure:
```yaml
check_interval: 300        # global default in seconds
stores:
  - id: "055"
    name: "Madison Heights, MI"
products:
  - name: "Display name"
    url: "https://www.microcenter.com/product/..."
    stores: ["055"]
    check_interval: 180    # optional override
    price_threshold: 29.99 # optional: only notify on price drop if price <= this
```

Store IDs are MicroCenter's internal numeric codes (e.g. `055` for Madison Heights, MI). A list of known IDs is in `config/products.yml`.
