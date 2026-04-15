"""Telegram bot long-polling listener for incoming commands."""
from __future__ import annotations

import html
import logging
import time

import httpx

from config import AppConfig
from notifier import send

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


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


def _handle_list(cfg: AppConfig) -> str:
    if not cfg.products:
        return "No products are currently being tracked."

    lines = ["<b>Tracked products:</b>\n"]
    for i, product in enumerate(cfg.products, start=1):
        store_names = ", ".join(cfg.store_name(s) for s in product.stores)
        interval = cfg.interval_for(product)
        threshold_line = ""
        if product.price_threshold is not None:
            threshold_line = f" | threshold: ${product.price_threshold:.2f}"
        lines.append(
            f"{i}. <b>{html.escape(product.name)}</b>\n"
            f"   🏪 {html.escape(store_names)}\n"
            f"   ⏱ every {interval}s{threshold_line}\n"
            f"   <a href=\"{product.url}\">View on MicroCenter</a>"
        )
    return "\n".join(lines)


def poll_updates(cfg: AppConfig) -> None:
    """Long-polling loop. Intended to run in a daemon thread."""
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
                logger.warning("Ignoring message from unauthorized chat_id: %s", chat_id)
                continue

            text = message.get("text", "").strip()
            command = text.split()[0].split("@")[0].lower() if text else ""

            if command == "/list":
                logger.info("Received /list command")
                reply = _handle_list(cfg)
                send(cfg.telegram_bot_token, cfg.telegram_chat_id, reply)
            elif command.startswith("/"):
                send(
                    cfg.telegram_bot_token,
                    cfg.telegram_chat_id,
                    f"Unknown command: <code>{html.escape(command)}</code>",
                )

        if not updates:
            # Brief pause on empty poll to avoid tight loop on network errors
            time.sleep(1)
