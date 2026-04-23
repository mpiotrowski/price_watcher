from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class StoreConfig:
    id: str
    name: str
    retailer_id: str = "microcenter"


@dataclass
class ProductConfig:
    name: str
    url: str
    stores: list[str]  # store codes
    check_interval: int | None = None  # seconds; None means use global default
    price_threshold: float | None = None  # notify on price drop only below this


@dataclass
class AppConfig:
    telegram_bot_token: str
    telegram_chat_id: str
    database_url: str
    check_interval: int
    stores: dict[str, StoreConfig]  # keyed by store code
    products: list[ProductConfig]

    def store_name(self, store_code: str) -> str:
        store = self.stores.get(store_code)
        return store.name if store else store_code

    def interval_for(self, product: ProductConfig) -> int:
        return product.check_interval or self.check_interval


def load_config(config_path: str | Path = "config/products.yml") -> AppConfig:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    database_url = os.environ.get("DATABASE_URL", "sqlite:////data/mc_watcher.db")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID environment variable is required")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    stores = {
        s["id"]: StoreConfig(
            id=s["id"],
            name=s["name"],
            retailer_id=s.get("retailer_id", "microcenter"),
        )
        for s in raw.get("stores", [])
    }

    products = [
        ProductConfig(
            name=p["name"],
            url=p["url"],
            stores=p["stores"],
            check_interval=p.get("check_interval"),
            price_threshold=p.get("price_threshold"),
        )
        for p in raw.get("products", [])
    ]

    return AppConfig(
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
        database_url=database_url,
        check_interval=raw.get("check_interval", 300),
        stores=stores,
        products=products,
    )
