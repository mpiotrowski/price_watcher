"""Job scheduler — one job per (product, store) combination."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from config import AppConfig
from db import PriceSnapshot, backfill_product_name, get_last_snapshot, list_products, list_stores, record_failure, reset_failures
from scrapers.microcenter import ScrapeResult, scrape
import notifier

logger = logging.getLogger(__name__)


def run_check(
    cfg: AppConfig,
    product_id: int,
    product_url: str,
    store_id: str,
    store_name: str,
    price_threshold: float | None,
    engine,
) -> None:
    logger.info("Checking product #%d @ %s", product_id, store_name)

    try:
        result: ScrapeResult = scrape(product_url, store_id)
    except Exception as e:
        logger.error("Scrape failed for #%d @ %s: %s", product_id, store_name, e)
        with Session(engine) as session:
            failure_count = record_failure(session, product_id)
        if failure_count == 1:
            notifier.scrape_failed(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                product_name=f"#{product_id}",
                store_name=store_name,
                error=str(e),
                url=product_url,
            )
        return

    with Session(engine) as session:
        previous_failures = reset_failures(session, product_id)

    if previous_failures:
        notifier.scrape_recovered(
            bot_token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
            product_name=result.product_name,
            store_name=store_name,
            url=product_url,
        )

    with Session(engine) as session:
        backfill_product_name(session, product_id, result.product_name)

        last = get_last_snapshot(session, product_url, store_id)

        stock_changed = last is None or last.in_stock != result.in_stock
        price_changed = (
            last is not None
            and last.price is not None
            and result.price is not None
            and last.price != result.price
        )

        # Apply price threshold filter if configured
        if price_changed and price_threshold is not None:
            if result.price > price_threshold:
                price_changed = False

        if stock_changed and last is not None:
            notifier.stock_changed(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                product_name=result.product_name,
                store_name=store_name,
                in_stock=result.in_stock,
                price=result.price,
                url=product_url,
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
                url=product_url,
            )

        snapshot = PriceSnapshot(
            product_url=product_url,
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


def _job_id(product_id: int, store_id: str) -> str:
    return f"product:{product_id}:{store_id}"


def schedule_product(
    scheduler: BackgroundScheduler,
    cfg: AppConfig,
    product_id: int,
    product_url: str,
    store_id: str,
    store_name: str,
    check_interval: int | None,
    price_threshold: float | None,
    engine,
) -> None:
    interval = check_interval or cfg.check_interval
    scheduler.add_job(
        run_check,
        "interval",
        seconds=interval,
        id=_job_id(product_id, store_id),
        args=[cfg, product_id, product_url, store_id, store_name, price_threshold, engine],
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info("Scheduled: #%d @ %s every %ds", product_id, store_name, interval)


def unschedule_product(scheduler: BackgroundScheduler, product_id: int, store_id: str) -> None:
    job_id = _job_id(product_id, store_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled: #%d @ %s", product_id, store_id)


def build_and_start(cfg: AppConfig, engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)

    with Session(engine) as session:
        products = list_products(session)
        store_map = {s.id: s.name for s in list_stores(session)}

    for product in products:
        store_name = store_map.get(product.store_id, product.store_id)
        schedule_product(
            scheduler, cfg,
            product.id, product.url, product.store_id, store_name,
            product.check_interval, product.price_threshold,
            engine,
        )

    logger.info("Starting scheduler with %d job(s)", len(scheduler.get_jobs()))
    scheduler.start()
    return scheduler
