"""Job scheduler — one job per (product, store) combination."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session

from config import AppConfig
from config import ProductConfig
from db import PriceSnapshot, get_last_snapshot, init_db
from scrapers.microcenter import ScrapeResult, scrape
import notifier

logger = logging.getLogger(__name__)


def run_check(
    cfg: AppConfig,
    product: ProductConfig,
    store_id: str,
    engine,
) -> None:
    store_name = cfg.store_name(store_id)
    logger.info("Checking %s @ %s", product.name, store_name)

    try:
        result: ScrapeResult = scrape(product.url, store_id)
    except Exception as e:
        logger.error("Scrape failed for %s @ %s: %s", product.name, store_name, e)
        return

    with Session(engine) as session:
        last = get_last_snapshot(session, product.url, store_id)

        stock_changed = last is None or last.in_stock != result.in_stock
        price_changed = (
            last is not None
            and last.price is not None
            and result.price is not None
            and last.price != result.price
        )

        # Apply price threshold filter if configured
        if price_changed and product.price_threshold is not None:
            if result.price > product.price_threshold:
                price_changed = False

        if stock_changed and last is not None:
            notifier.stock_changed(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                product_name=result.product_name,
                store_name=store_name,
                in_stock=result.in_stock,
                price=result.price,
                url=product.url,
            )
        elif price_changed:
            notifier.price_changed(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                product_name=result.product_name,
                store_name=store_name,
                old_price=last.price,
                new_price=result.price,
                in_stock=result.in_stock,
                url=product.url,
            )

        snapshot = PriceSnapshot(
            product_url=product.url,
            store_id=store_id,
            product_name=result.product_name,
            price=result.price,
            in_stock=result.in_stock,
            checked_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        session.commit()

    logger.info(
        "%s @ %s — in_stock=%s price=%s",
        result.product_name,
        store_name,
        result.in_stock,
        f"${result.price:.2f}" if result.price else "N/A",
    )


def build_and_start(cfg: AppConfig) -> None:
    engine = init_db(cfg.database_url)
    scheduler = BlockingScheduler()

    for product in cfg.products:
        for store_id in product.stores:
            interval = cfg.interval_for(product)
            job_id = f"{product.url}|{store_id}"
            scheduler.add_job(
                run_check,
                "interval",
                seconds=interval,
                id=job_id,
                args=[cfg, product, store_id, engine],
                next_run_time=datetime.now(timezone.utc),  # run immediately on start
            )
            logger.info(
                "Scheduled: %s @ %s every %ds",
                product.name,
                cfg.store_name(store_id),
                interval,
            )

    logger.info("Starting scheduler with %d job(s)", len(scheduler.get_jobs()))
    scheduler.start()
