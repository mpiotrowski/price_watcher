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
from db import (
    Store,
    add_product, add_store, get_store_by_code,
    list_products, list_retailers, list_stores,
    remove_product, remove_store,
)
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
        store_map = {s.id: s for s in list_stores(session)}

    if not products:
        return "No products are currently being tracked."

    lines = ["<b>Tracked products:</b>\n"]
    for product in products:
        store = store_map.get(product.store_id)
        store_display = f"{store.store_code} ({store.name})" if store else str(product.store_id)
        display_name = product.name or product.url
        interval = product.check_interval or cfg.check_interval
        threshold_line = ""
        if product.price_threshold is not None:
            threshold_line = f" | threshold: ${product.price_threshold:.2f}"
        lines.append(
            f"#{product.id} <b>{html.escape(display_name)}</b>\n"
            f"   🏪 {html.escape(store_display)}\n"
            f"   ⏱ every {interval}s{threshold_line}\n"
            f"   <a href=\"{html.escape(product.url)}\">View product</a>"
        )
    return "\n".join(lines)


def _handle_stores(engine: Engine) -> str:
    with Session(engine) as session:
        retailers = list_retailers(session)
        stores = list_stores(session)

    if not stores:
        return "No stores configured. Add one with /addstore &lt;retailer_id&gt; &lt;store_code&gt; &lt;name&gt;"

    retailer_name_map = {r.id: r.name for r in retailers}
    by_retailer: dict[str, list[Store]] = {}
    for store in stores:
        by_retailer.setdefault(store.retailer_id, []).append(store)

    lines = ["<b>Configured stores:</b>\n"]
    for retailer_id, retailer_stores in by_retailer.items():
        retailer_name = retailer_name_map.get(retailer_id, retailer_id)
        lines.append(f"<b>{html.escape(retailer_name)}:</b>")
        for store in retailer_stores:
            lines.append(
                f"  #{store.id}  <code>{html.escape(store.store_code)}</code> — {html.escape(store.name)}"
            )
    return "\n".join(lines)


def _handle_addstore(args: list[str], engine: Engine) -> str:
    if len(args) < 3:
        return (
            "Usage: /addstore &lt;retailer_id&gt; &lt;store_code&gt; &lt;name&gt;\n"
            "Example: /addstore microcenter 065 <i>Westmont, IL</i>"
        )

    retailer_id, store_code = args[0], args[1]
    name = " ".join(args[2:])

    with Session(engine) as session:
        retailers = list_retailers(session)
        if not any(r.id == retailer_id for r in retailers):
            known = ", ".join(f"<code>{html.escape(r.id)}</code>" for r in retailers)
            return f"Unknown retailer <code>{html.escape(retailer_id)}</code>. Known retailers: {known or 'none'}"

        if get_store_by_code(session, retailer_id, store_code) is not None:
            return f"Store <code>{html.escape(store_code)}</code> already exists under {html.escape(retailer_id)}."

        store = add_store(session, retailer_id, store_code, name)
        store_db_id = store.id

    logger.info("Added store: %s/%s (%s) [#%d]", retailer_id, store_code, name, store_db_id)
    return (
        f"Added store #{store_db_id}: <code>{html.escape(store_code)}</code> — "
        f"{html.escape(name)} (under {html.escape(retailer_id)})"
    )


def _handle_removestore(args: list[str], engine: Engine) -> str:
    if not args or not args[0].isdigit():
        return "Usage: /removestore &lt;store_id&gt;\nGet the numeric ID from /stores"

    store_db_id = int(args[0])

    with Session(engine) as session:
        store = session.get(Store, store_db_id)
        if store is None:
            return f"Store #{store_db_id} not found."

        active_products = [p for p in list_products(session) if p.store_id == store_db_id]
        if active_products:
            names = ", ".join(
                f"#{p.id} {html.escape(p.name or p.url)}" for p in active_products
            )
            return (
                f"Cannot remove store #{store_db_id} (<code>{html.escape(store.store_code)}</code>) — "
                f"it still has active products: {names}\n"
                f"Remove them first with /remove &lt;id&gt;"
            )
        store_code = store.store_code
        remove_store(session, store_db_id)

    logger.info("Removed store: #%d (%s)", store_db_id, store_code)
    return f"Removed store #{store_db_id} (<code>{html.escape(store_code)}</code>)"


def _handle_add(args: list[str], cfg: AppConfig, engine: Engine, scheduler: BackgroundScheduler) -> str:
    if len(args) < 2:
        return (
            "Usage: /add &lt;url&gt; &lt;store_code&gt; [price_threshold] [interval_seconds]\n"
            "Example: /add https://www.microcenter.com/product/123/name 055 29.99 300"
        )

    url, store_code = args[0], args[1]

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
        retailers = list_retailers(session)
        matched_retailer = next(
            (r for r in retailers if r.base_url and url.startswith(r.base_url)),
            None,
        )
        if matched_retailer is None:
            known_urls = ", ".join(
                f"<code>{html.escape(r.base_url)}</code>" for r in retailers if r.base_url
            )
            return (
                f"Invalid URL — must start with a known retailer's base URL.\n"
                f"Known: {known_urls or 'none configured'}"
            )

        store = get_store_by_code(session, matched_retailer.id, store_code)
        if store is None:
            return (
                f"Unknown store <code>{html.escape(store_code)}</code> for {html.escape(matched_retailer.name)}. "
                f"Add it first with /addstore, or check available stores with /stores."
            )
        store_name = store.name
        store_id = store.id
        retailer_id = matched_retailer.id

        existing = list_products(session)
        if any(p.url == url and p.store_id == store_id for p in existing):
            return f"Already tracking that product at store <code>{html.escape(store_code)}</code>."

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
        product_id, url, store_id, store_code, retailer_id, store_name,
        check_interval, price_threshold,
        engine,
    )

    logger.info("Added product #%d @ %s/%s", product_id, retailer_id, store_code)
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
        store = session.get(Store, store_id)
        store_display = store.store_code if store else str(store_id)
        remove_product(session, product_id)

    unschedule_product(scheduler, product_id, store_id)
    logger.info("Removed product #%d", product_id)
    return f"Removed <b>{display_name}</b> @ <code>{html.escape(store_display)}</code>"


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
            time.sleep(1)
