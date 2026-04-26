# Price Watcher

Monitors product pages for price and stock changes, then sends Telegram notifications when something changes. Runs as a lightweight Docker container backed by SQLite. Currently supports MicroCenter; designed to accommodate additional retailers.

## Features

- Multi-retailer architecture — add new retailers by dropping in a scraper module
- Per-store inventory and price tracking
- Telegram bot interface — add/remove products without touching config files
- Configurable check intervals and price-drop thresholds per product
- Consecutive-failure tracking with recovery alerts

## Quick Start with Docker

### Pull and run the pre-built image

```bash
docker pull mpiotrowski91/price_watcher:latest

mkdir -p data config
cp .env.example .env
cp config/products.yml.example config/products.yml

docker run -d \
  --name price-watcher \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/data:/data \
  -v $(pwd)/config:/app/config \
  mpiotrowski91/price_watcher:latest
```

### Using docker compose (recommended)

Update `docker-compose.yml` to reference the pre-built image instead of building:

```yaml
services:
  watcher:
    image: mpiotrowski91/price_watcher:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
      - ./config:/app/config
```

Then run:

```bash
docker compose up -d
docker compose logs -f
```

## Build from Source

```bash
git clone https://github.com/mpiotrowski/price_watcher.git
cd price_watcher
cp .env.example .env
docker compose up --build -d
docker compose logs -f
```

## Configuration

### Environment variables (`.env`)

```
TELEGRAM_BOT_TOKEN=your_bot_token_here    # from @BotFather
TELEGRAM_CHAT_ID=your_chat_id_here        # your chat or group ID
DATABASE_URL=sqlite:////data/mc_watcher.db
```

### Products (`config/products.yml`)

```yaml
check_interval: 300   # global default in seconds

stores:
  - id: "055"
    name: "Madison Heights, MI"
    retailer_id: "microcenter"   # optional, defaults to "microcenter"

products:
  - name: "Display name"
    url: "https://www.microcenter.com/product/..."
    stores: ["055"]
    check_interval: 180    # optional per-product override
    price_threshold: 29.99 # optional: only notify on price drop if price <= this
```

Find your MicroCenter store ID at [microcenter.com/site/stores](https://www.microcenter.com/site/stores/default.aspx). Common IDs:

| ID  | Location              |
|-----|-----------------------|
| 025 | Westmont, IL          |
| 055 | Madison Heights, MI   |
| 065 | St. Louis Park, MN    |
| 075 | Sharonville, OH       |
| 095 | Houston, TX           |
| 105 | Cambridge, MA         |
| 115 | Rockville, MD         |
| 121 | Yonkers, NY           |
| 131 | Denver, CO            |
| 141 | Dallas, TX            |
| 150 | Brooklyn, NY          |
| 160 | Tustin, CA            |
| 191 | San Jose, CA          |

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/list` | Show all tracked products |
| `/add <url> <store_code> [price_threshold] [interval]` | Start tracking a product |
| `/remove <id>` | Stop tracking a product |
| `/stores` | List configured stores grouped by retailer |
| `/addstore <retailer_id> <store_code> <name>` | Add a store |
| `/removestore <store_id>` | Remove a store (use numeric ID from `/stores`) |

The retailer for `/add` is inferred from the URL — no need to specify it explicitly.

## Database Migrations

Migrations are standalone scripts in `migrations/` and must be run manually. To run against a live deployment:

```bash
docker compose run --rm watcher python migrations/<script>.py
```

| Script | Description |
|--------|-------------|
| `add_retailers_table.py` | Introduces `retailers` table; restructures `stores` with surrogate PK and `store_code` |
| `add_consecutive_failures.py` | Adds `consecutive_failures` column to `tracked_products` |

## Local Development

```bash
pip install -e ".[dev]"
PYTHONPATH=src python src/main.py
```

Run tests:

```bash
pytest
pytest tests/test_scraper.py
```

Lint:

```bash
ruff check src/
ruff format src/
```

## Data Persistence

SQLite database is stored in `./data/mc_watcher.db` (mounted into the container). Products removed via Telegram are soft-deleted (`active=False`) to preserve price history.
