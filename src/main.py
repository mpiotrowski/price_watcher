#!/usr/bin/env python3
import logging
import sys
from sqlalchemy.orm import Session

from config import load_config
from db import add_product, add_store, init_db, list_products, list_stores
from notifier import register_commands
from scheduler import build_and_start
from telegram_listener import poll_updates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def seed_from_yaml(engine, cfg) -> None:
    """Populate stores and tracked_products from the YAML config on first run."""
    with Session(engine) as session:
        if list_stores(session) or list_products(session, include_inactive=True):
            logger.info("Database already seeded, skipping YAML migration")
            return

        logger.info("Seeding database from products.yml")

        # Collect all store IDs referenced by products (may exceed the stores list)
        all_store_ids = {sid for p in cfg.products for sid in p.stores}

        for store_id in all_store_ids:
            store_cfg = cfg.stores.get(store_id)
            name = store_cfg.name if store_cfg else store_id
            add_store(session, store_id, name)
            logger.info("  Added store: %s (%s)", store_id, name)

        for product_cfg in cfg.products:
            for store_id in product_cfg.stores:
                add_product(
                    session,
                    url=product_cfg.url,
                    store_id=store_id,
                    check_interval=product_cfg.check_interval,
                    price_threshold=product_cfg.price_threshold,
                )
                logger.info("  Added product: %s @ %s", product_cfg.name, store_id)


def main() -> None:
    cfg = load_config("config/products.yml")

    engine = init_db(cfg.database_url)
    seed_from_yaml(engine, cfg)
    register_commands(cfg.telegram_bot_token)

    with Session(engine) as session:
        product_count = len(list_products(session))
        store_count = len(list_stores(session))
    logger.info("Tracking %d product(s) across %d store(s)", product_count, store_count)

    scheduler = build_and_start(cfg, engine)
    poll_updates(cfg, engine, scheduler)


if __name__ == "__main__":
    main()
