#!/usr/bin/env python3
import logging
import sys

from config import load_config
from scheduler import build_and_start

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config("config/products.yml")
    logger.info(
        "Loaded %d product(s) across %d store(s)",
        len(cfg.products),
        len(cfg.stores),
    )
    build_and_start(cfg)


if __name__ == "__main__":
    main()
