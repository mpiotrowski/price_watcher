# MicroCenter Price Watcher

Monitors MicroCenter product pages for price and stock changes, then sends Telegram notifications when something changes. Runs as a lightweight Docker container backed by SQLite.

## Features

- Per-store inventory and price tracking
- Telegram bot interface — add/remove products without touching config files
- Configurable check intervals and price-drop thresholds per product
- Consecutive-failure tracking with recovery alerts

## Quick Start with Docker

### Pull and run the pre-built image

```bash
# Pull the image
docker pull ghcr.io/mpiotrowski91/price-watcher:latest

# Create required directories
mkdir -p data config

# Copy and fill in environment variables
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

# Copy the example config
cp config/products.yml.example config/products.yml
# Edit config/products.yml with your products and store IDs

# Run
docker run -d \
  --name price-watcher \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/data:/data \
  -v $(pwd)/config:/app/config \
  ghcr.io/mpiotrowski91/price-watcher:latest
```

### Using docker compose (recommended)

Update `docker-compose.yml` to reference the pre-built image instead of building:

```yaml
services:
  watcher:
    image: ghcr.io/mpiotrowski91/price-watcher:latest
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
git clone https://github.com/mpiotrowski91/price-watcher.git
cd price-watcher
cp .env.example .env   # fill in your tokens
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

products:
  - name: "Display name"
    url: "https://www.microcenter.com/product/..."
    stores: ["055"]
    check_interval: 180    # optional per-product override
    price_threshold: 29.99 # optional: only notify on price drop if price <= this
```

Find your store ID at [microcenter.com/site/stores](https://www.microcenter.com/site/stores/default.aspx). Common IDs:

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
| `/list` | Show all tracked products and their current status |
| `/add <url> [store_id]` | Start tracking a product |
| `/remove <id>` | Stop tracking a product |
| `/stores` | List configured stores |
| `/addstore <id> <name>` | Add a store |
| `/removestore <id>` | Remove a store |

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
