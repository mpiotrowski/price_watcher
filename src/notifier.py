"""Telegram notification sender."""
from __future__ import annotations

import html
import logging

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


COMMANDS = [
    ("list",        "Show all tracked products"),
    ("add",         "Track a product: <url> <store_id> [threshold] [interval]"),
    ("remove",      "Stop tracking a product: <id>"),
    ("stores",      "List configured stores"),
    ("addstore",    "Add a store: <store_id> <name>"),
    ("removestore", "Remove a store: <store_id>"),
]


def send(bot_token: str, chat_id: str, text: str) -> None:
    url = TELEGRAM_API.format(token=bot_token) + "/sendMessage"
    try:
        r = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Failed to send Telegram notification: %s — %s", e, e.response.text)
    except httpx.HTTPError as e:
        logger.error("Failed to send Telegram notification: %s", e)


def register_commands(bot_token: str) -> None:
    url = TELEGRAM_API.format(token=bot_token) + "/setMyCommands"
    payload = {"commands": [{"command": cmd, "description": desc} for cmd, desc in COMMANDS]}
    try:
        r = httpx.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Registered %d bot command(s) with Telegram", len(COMMANDS))
    except httpx.HTTPStatusError as e:
        logger.error("Failed to register bot commands: %s — %s", e, e.response.text)
    except httpx.HTTPError as e:
        logger.error("Failed to register bot commands: %s", e)


def stock_changed(
    *,
    bot_token: str,
    chat_id: str,
    product_name: str,
    store_name: str,
    in_stock: bool,
    price: float | None,
    url: str,
) -> None:
    status = "✅ Back in stock" if in_stock else "❌ Out of stock"
    price_line = f"\n💰 <b>${price:.2f}</b>" if price is not None else ""
    text = (
        f"{status}\n"
        f"📦 <b>{html.escape(product_name)}</b>\n"
        f"🏪 {html.escape(store_name)}"
        f"{price_line}\n"
        f'<a href="{html.escape(url)}">View on MicroCenter</a>'
    )
    send(bot_token, chat_id, text)


def check_result(
    *,
    bot_token: str,
    chat_id: str,
    product_name: str,
    store_name: str,
    in_stock: bool,
    price: float | None,
    url: str,
) -> None:
    stock_line = "✅ In stock" if in_stock else "❌ Out of stock"
    price_line = f"\n💰 <b>${price:.2f}</b>" if price is not None else ""
    text = (
        f"🔍 Check complete\n"
        f"📦 <b>{html.escape(product_name)}</b>\n"
        f"🏪 {html.escape(store_name)}\n"
        f"{stock_line}"
        f"{price_line}\n"
        f'<a href="{html.escape(url)}">View on MicroCenter</a>'
    )
    send(bot_token, chat_id, text)


def unauthorized_access(
    *,
    bot_token: str,
    chat_id: str,
    from_chat_id: str,
    username: str | None,
    text: str,
) -> None:
    who = f"@{html.escape(username)}" if username else f"chat <code>{html.escape(from_chat_id)}</code>"
    text_preview = html.escape(text[:200]) if text else "<i>(no text)</i>"
    msg = (
        f"🚫 Unauthorized message\n"
        f"From: {who} (id: <code>{html.escape(from_chat_id)}</code>)\n"
        f"Message: {text_preview}"
    )
    send(bot_token, chat_id, msg)


def scrape_failed(
    *,
    bot_token: str,
    chat_id: str,
    product_name: str,
    store_name: str,
    error: str,
    url: str,
) -> None:
    text = (
        f"⚠️ Scrape failed\n"
        f"📦 <b>{html.escape(product_name)}</b>\n"
        f"🏪 {html.escape(store_name)}\n"
        f"❌ <code>{html.escape(error)}</code>\n"
        f'<a href="{html.escape(url)}">View on MicroCenter</a>'
    )
    send(bot_token, chat_id, text)


def scrape_recovered(
    *,
    bot_token: str,
    chat_id: str,
    product_name: str,
    store_name: str,
    url: str,
) -> None:
    text = (
        f"✅ Scrape recovered\n"
        f"📦 <b>{html.escape(product_name)}</b>\n"
        f"🏪 {html.escape(store_name)}\n"
        f'<a href="{html.escape(url)}">View on MicroCenter</a>'
    )
    send(bot_token, chat_id, text)


def price_changed(
    *,
    bot_token: str,
    chat_id: str,
    product_name: str,
    store_name: str,
    old_price: float,
    new_price: float,
    in_stock: bool,
    url: str,
) -> None:
    direction = "📉 Price drop" if new_price < old_price else "📈 Price increase"
    stock_line = "✅ In stock" if in_stock else "❌ Out of stock"
    text = (
        f"{direction}\n"
        f"📦 <b>{html.escape(product_name)}</b>\n"
        f"🏪 {html.escape(store_name)}\n"
        f"💰 <b>${new_price:.2f}</b> <s>${old_price:.2f}</s>\n"
        f"{stock_line}\n"
        f'<a href="{html.escape(url)}">View on MicroCenter</a>'
    )
    send(bot_token, chat_id, text)
