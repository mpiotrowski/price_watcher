#!/usr/bin/env python3
import logging
import sys
from sqlalchemy.orm import Session

from config import load_config
from db import Retailer, add_product, add_retailer, add_store, get_store_by_code, init_db, list_products, list_stores
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
    """Populate retailers, stores and tracked_products from the YAML config on first run."""
    with Session(engine) as session:
        if list_stores(session) or list_products(session, include_inactive=True):
            logger.info("Database already seeded, skipping YAML migration")
            return

        logger.info("Seeding database from products.yml")

        # Seed the default retailer
        if session.get(Retailer, "microcenter") is None:
            add_retailer(session, "microcenter", "MicroCenter", "https://www.microcenter.com")
            logger.info("  Added retailer: microcenter")

        # Collect all store codes referenced by products (may exceed the stores list)
        all_store_codes = {code for p in cfg.products for code in p.stores}

        for store_code in all_store_codes:
            store_cfg = cfg.stores.get(store_code)
            name = store_cfg.name if store_cfg else store_code
            retailer_id = store_cfg.retailer_id if store_cfg else "microcenter"
            add_store(session, retailer_id, store_code, name)
            logger.info("  Added store: %s/%s (%s)", retailer_id, store_code, name)

        for product_cfg in cfg.products:
            for store_code in product_cfg.stores:
                store_cfg = cfg.stores.get(store_code)
                retailer_id = store_cfg.retailer_id if store_cfg else "microcenter"
                store = get_store_by_code(session, retailer_id, store_code)
                if store is None:
                    logger.warning("  Store %s/%s not found, skipping product %s", retailer_id, store_code, product_cfg.name)
                    continue
                add_product(
                    session,
                    url=product_cfg.url,
                    store_id=store.id,
                    check_interval=product_cfg.check_interval,
                    price_threshold=product_cfg.price_threshold,
                )
                logger.info("  Added product: %s @ %s/%s", product_cfg.name, retailer_id, store_code)


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
