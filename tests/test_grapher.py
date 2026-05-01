from datetime import datetime, timedelta, timezone

from db import PriceSnapshot
from grapher import render_price_chart

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _snap(price, in_stock=True, hours_ago=0):
    return PriceSnapshot(
        product_url="https://example.com/p",
        store_code="055",
        product_name="Test GPU",
        price=price,
        in_stock=in_stock,
        checked_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


class TestRenderPriceChart:
    def test_returns_valid_png_bytes(self):
        snaps = [_snap(299.99, hours_ago=2), _snap(299.99, hours_ago=1)]
        result = render_price_chart(snaps, "Test GPU", "Store", 7)
        assert isinstance(result, bytes)
        assert result[:8] == _PNG_MAGIC

    def test_single_snapshot(self):
        result = render_price_chart([_snap(299.99)], "GPU", "Store", 1)
        assert result[:8] == _PNG_MAGIC

    def test_multiple_snapshots_with_price_changes(self):
        snaps = [
            _snap(399.99, hours_ago=4),
            _snap(349.99, hours_ago=3),
            _snap(299.99, hours_ago=2),
            _snap(299.99, hours_ago=1),
        ]
        result = render_price_chart(snaps, "GPU", "Store", 7)
        assert result[:8] == _PNG_MAGIC

    def test_out_of_stock_periods_render(self):
        snaps = [
            _snap(299.99, in_stock=True, hours_ago=4),
            _snap(299.99, in_stock=False, hours_ago=3),
            _snap(299.99, in_stock=False, hours_ago=2),
            _snap(299.99, in_stock=True, hours_ago=1),
        ]
        result = render_price_chart(snaps, "GPU", "Store", 7)
        assert result[:8] == _PNG_MAGIC

    def test_none_prices_skipped_cleanly(self):
        snaps = [
            _snap(299.99, hours_ago=3),
            _snap(None, hours_ago=2),
            _snap(279.99, hours_ago=1),
        ]
        result = render_price_chart(snaps, "GPU", "Store", 7)
        assert result[:8] == _PNG_MAGIC
