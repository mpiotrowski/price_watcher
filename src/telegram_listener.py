"""Telegram bot long-polling listener for incoming commands."""
from __future__ import annotations

import html
import logging
import time

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from config import AppConfig
from db import add_product, add_store, list_products, list_stores, remove_product, remove_store
import notifier
from notifier import TELEGRAM_API, send
from scheduler import schedule_product, unschedule_product

logger = logging.getLogger(__name__)


def _get_updates(bot_token: str, offset: int, timeout: int = 30) -> list[dict]:
    url = TELEGRAM_API.format(token=bot_token) + "/getUpdates"
    try:
        r = httpx.get(
            url,
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 5,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except httpx.HTTPError as e:
        logger.error("getUpdates failed: %s", e)
        return []


def _handle_list(cfg: AppConfig, engine: Engine) -> str:
    with Session(engine) as session:
        products = list_products(session)
        store_map = {s.id: s.name for s in list_stores(session)}

    if not products:
        return "No products are currently being tracked."

    lines = ["<b>Tracked products:</b>\n"]
    for product in products:
        store_name = store_map.get(product.store_id, product.store_id)
        display_name = product.name or product.url
        interval = product.check_interval or cfg.check_interval
        threshold_line = ""
        if product.price_threshold is not None:
            threshold_line = f" | threshold: ${product.price_threshold:.2f}"
        lines.append(
            f"#{product.id} <b>{html.escape(display_name)}</b>\n"
            f"   🏪 {html.escape(store_name)}\n"
            f"   ⏱ every {interval}s{threshold_line}\n"
            f"   <a href=\"{html.escape(product.url)}\">View on MicroCenter</a>"
        )
    return "\n".join(lines)


def _handle_stores(engine: Engine) -> str:
    with Session(engine) as session:
        stores = list_stores(session)

    if not stores:
        return "No stores configured. Add one with /addstore &lt;store_id&gt; &lt;name&gt;"

    lines = ["<b>Configured stores:</b>\n"]
    for store in stores:
        lines.append(f"  <code>{html.escape(store.id)}</code> — {html.escape(store.name)}")
    return "\n".join(lines)


def _handle_addstore(args: list[str], engine: Engine) -> str:
    if len(args) < 2:
        return "Usage: /addstore &lt;store_id&gt; &lt;name&gt;\nExample: /addstore 055 <i>Madison Heights, MI</i>"

    store_id = args[0]
    name = " ".join(args[1:])

    with Session(engine) as session:
        existing = list_stores(session)
        if any(s.id == store_id for s in existing):
            return f"Store <code>{html.escape(store_id)}</code> already exists."
        add_store(session, store_id, name)

    logger.info("Added store: %s (%s)", store_id, name)
    return f"Added store <code>{html.escape(store_id)}</code> — {html.escape(name)}"


def _handle_removestore(args: list[str], engine: Engine) -> str:
    if not args:
        return "Usage: /removestore &lt;store_id&gt;"

    store_id = args[0]

    with Session(engine) as session:
        active_products = [p for p in list_products(session) if p.store_id == store_id]
        if active_products:
            names = ", ".join(
                f"#{p.id} {html.escape(p.name or p.url)}" for p in active_products
            )
            return (
                f"Cannot remove store <code>{html.escape(store_id)}</code> — "
                f"it still has active products: {names}\n"
                f"Remove them first with /remove &lt;id&gt;"
            )
        removed = remove_store(session, store_id)

    if not removed:
        return f"Store <code>{html.escape(store_id)}</code> not found."

    logger.info("Removed store: %s", store_id)
    return f"Removed store <code>{html.escape(store_id)}</code>"


def _handle_add(args: list[str], cfg: AppConfig, engine: Engine, scheduler: BackgroundScheduler) -> str:
    if len(args) < 2:
        return (
            "Usage: /add &lt;url&gt; &lt;store_id&gt; [price_threshold] [interval_seconds]\n"
            "Example: /add https://www.microcenter.com/product/123/name 055 29.99 300"
        )

    url, store_id = args[0], args[1]

    if not url.startswith("https://www.microcenter.com/product/"):
        return "Invalid URL — must be a MicroCenter product URL (https://www.microcenter.com/product/...)."

    price_threshold: float | None = None
    check_interval: int | None = None

    if len(args) >= 3:
        try:
            price_threshold = float(args[2])
        except ValueError:
            return f"Invalid price threshold: <code>{html.escape(args[2])}</code> — must be a number."

    if len(args) >= 4:
        try:
            check_interval = int(args[3])
        except ValueError:
            return f"Invalid interval: <code>{html.escape(args[3])}</code> — must be a whole number of seconds."

    with Session(engine) as session:
        store = next((s for s in list_stores(session) if s.id == store_id), None)
        if store is None:
            return (
                f"Unknown store <code>{html.escape(store_id)}</code>. "
                f"Add it first with /addstore, or check available stores with /stores."
            )
        store_name = store.name

        existing = list_products(session)
        if any(p.url == url and p.store_id == store_id for p in existing):
            return f"Already tracking that product at store <code>{html.escape(store_id)}</code>."

        product = add_product(
            session,
            url=url,
            store_id=store_id,
            check_interval=check_interval,
            price_threshold=price_threshold,
        )
        product_id = product.id

    schedule_product(
        scheduler, cfg,
        product_id, url, store_id, store_name,
        check_interval, price_threshold,
        engine,
    )

    logger.info("Added product #%d @ %s", product_id, store_id)
    threshold_line = f"\n   threshold: ${price_threshold:.2f}" if price_threshold is not None else ""
    interval_line = f"\n   interval: {check_interval}s" if check_interval is not None else ""
    return (
        f"Now tracking <a href=\"{html.escape(url)}\">product #{product_id}</a> "
        f"@ <code>{html.escape(store_name)}</code>"
        f"{threshold_line}{interval_line}"
    )


def _handle_remove(args: list[str], engine: Engine, scheduler: BackgroundScheduler) -> str:
    if not args or not args[0].isdigit():
        return "Usage: /remove &lt;id&gt;\nGet the ID from /list"

    product_id = int(args[0])

    with Session(engine) as session:
        products = list_products(session)
        product = next((p for p in products if p.id == product_id), None)
        if product is None:
            return f"No active product with ID #{product_id}."
        display_name = html.escape(product.name or product.url)
        store_id = product.store_id
        remove_product(session, product_id)

    unschedule_product(scheduler, product_id, store_id)
    logger.info("Removed product #%d", product_id)
    return f"Removed <b>{display_name}</b> @ <code>{html.escape(store_id)}</code>"


def poll_updates(cfg: AppConfig, engine: Engine, scheduler: BackgroundScheduler) -> None:
    """Long-polling loop. Blocks the calling thread indefinitely."""
    offset = 0
    logger.info("Telegram listener started")

    while True:
        updates = _get_updates(cfg.telegram_bot_token, offset)

        for update in updates:
            offset = update["update_id"] + 1

            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            # Only respond to the configured chat
            chat_id = str(message.get("chat", {}).get("id", ""))
            if chat_id != cfg.telegram_chat_id:
                username = message.get("from", {}).get("username")
                msg_text = message.get("text", "")
                logger.warning("Unauthorized message from chat_id=%s user=%s", chat_id, username)
                notifier.unauthorized_access(
                    bot_token=cfg.telegram_bot_token,
                    chat_id=cfg.telegram_chat_id,
                    from_chat_id=chat_id,
                    username=username,
                    text=msg_text,
                )
                continue

            text = message.get("text", "").strip()
            parts = text.split() if text else []
            command = parts[0].split("@")[0].lower() if parts else ""
            args = parts[1:]

            if command == "/list":
                logger.info("Received /list command")
                reply = _handle_list(cfg, engine)
            elif command == "/stores":
                logger.info("Received /stores command")
                reply = _handle_stores(engine)
            elif command == "/addstore":
                logger.info("Received /addstore command")
                reply = _handle_addstore(args, engine)
            elif command == "/removestore":
                logger.info("Received /removestore command")
                reply = _handle_removestore(args, engine)
            elif command == "/add":
                logger.info("Received /add command")
                reply = _handle_add(args, cfg, engine, scheduler)
            elif command == "/remove":
                logger.info("Received /remove command")
                reply = _handle_remove(args, engine, scheduler)
            elif command.startswith("/"):
                reply = f"Unknown command: <code>{html.escape(command)}</code>"
            else:
                continue

            send(cfg.telegram_bot_token, cfg.telegram_chat_id, reply)

        if not updates:
            # Brief pause on empty poll to avoid tight loop on network errors
            time.sleep(1)
