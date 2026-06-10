from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from db import PriceSnapshot, Store, TrackedProduct
from telegram_listener import (
    _handle_add,
    _handle_addstore,
    _handle_history,
    _handle_list,
    _handle_remove,
    _handle_removestore,
    _handle_stores,
)

_MC_URL = "https://www.microcenter.com/product/123/gpu"
_UNIFI_URL = "https://store.ui.com/products/unifi-switch-pro-24"
_AMAZON_URL = "https://www.amazon.com/dp/B0EXAMPLE123"


@pytest.fixture
def mock_scheduler():
    sched = MagicMock()
    sched.get_job.return_value = MagicMock()  # truthy so unschedule_product removes it
    return sched


# ── /list ────────────────────────────────────────────────────────────────────

class TestHandleList:
    def test_no_products_returns_empty_message(self, cfg, seeded_engine):
        reply = _handle_list(cfg, seeded_engine)
        assert "No products" in reply

    def test_shows_product_name_store_interval_and_threshold(self, cfg, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            session.add(TrackedProduct(
                url=_MC_URL, store_id=store.id, name="RTX 4090",
                check_interval=180, price_threshold=999.99,
            ))
            session.commit()
        reply = _handle_list(cfg, seeded_engine)
        assert "RTX 4090" in reply
        assert "055" in reply
        assert "180" in reply
        assert "999.99" in reply


# ── /stores ──────────────────────────────────────────────────────────────────

class TestHandleStores:
    def test_no_stores_returns_usage_hint(self, cfg, engine):
        reply = _handle_stores(engine)
        assert "No stores" in reply

    def test_shows_stores_grouped_by_retailer(self, cfg, seeded_engine):
        reply = _handle_stores(seeded_engine)
        assert "MicroCenter" in reply
        assert "055" in reply
        assert "Unifi Store" in reply
        assert "online" in reply


# ── /addstore ────────────────────────────────────────────────────────────────

class TestHandleAddstore:
    def test_too_few_args_returns_usage(self, seeded_engine):
        reply = _handle_addstore(["microcenter", "065"], seeded_engine)
        assert "Usage" in reply

    def test_unknown_retailer_returns_error(self, seeded_engine):
        reply = _handle_addstore(["unknown_retailer", "999", "Some Store"], seeded_engine)
        assert "Unknown retailer" in reply

    def test_duplicate_store_code_returns_error(self, seeded_engine):
        reply = _handle_addstore(["microcenter", "055", "Duplicate"], seeded_engine)
        assert "already exists" in reply

    def test_valid_args_creates_store(self, seeded_engine):
        reply = _handle_addstore(["microcenter", "065", "Westmont", "IL"], seeded_engine)
        assert "065" in reply
        from db import get_store_by_code
        with Session(seeded_engine) as session:
            store = get_store_by_code(session, "microcenter", "065")
        assert store is not None
        assert store.name == "Westmont IL"


# ── /removestore ─────────────────────────────────────────────────────────────

class TestHandleRemovestore:
    def test_non_digit_arg_returns_usage(self, seeded_engine):
        reply = _handle_removestore(["abc"], seeded_engine)
        assert "Usage" in reply

    def test_nonexistent_id_returns_not_found(self, seeded_engine):
        reply = _handle_removestore(["9999"], seeded_engine)
        assert "not found" in reply

    def test_blocked_when_store_has_active_products(self, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            session.add(TrackedProduct(url=_MC_URL, store_id=store.id, name="GPU"))
            session.commit()
            store_id = store.id
        reply = _handle_removestore([str(store_id)], seeded_engine)
        assert "Cannot remove" in reply or "active products" in reply

    def test_valid_removes_store(self, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            store_id = store.id
        reply = _handle_removestore([str(store_id)], seeded_engine)
        assert "Removed" in reply
        from db import get_store_by_code
        with Session(seeded_engine) as session:
            assert get_store_by_code(session, "microcenter", "055") is None


# ── /add ─────────────────────────────────────────────────────────────────────

class TestHandleAdd:
    def test_too_few_args_returns_usage(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_MC_URL], cfg, seeded_engine, mock_scheduler)
        assert "Usage" in reply

    def test_unrecognised_base_url_returns_error(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add(["https://unknown.com/product/1", "055"], cfg, seeded_engine, mock_scheduler)
        assert "Invalid URL" in reply

    def test_unknown_store_code_returns_error(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_MC_URL, "999"], cfg, seeded_engine, mock_scheduler)
        assert "Unknown store" in reply

    def test_duplicate_product_returns_error(self, cfg, seeded_engine, mock_scheduler):
        _handle_add([_MC_URL, "055"], cfg, seeded_engine, mock_scheduler)
        reply = _handle_add([_MC_URL, "055"], cfg, seeded_engine, mock_scheduler)
        assert "Already tracking" in reply

    def test_invalid_threshold_returns_error(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_MC_URL, "055", "notanumber"], cfg, seeded_engine, mock_scheduler)
        assert "Invalid price threshold" in reply

    def test_invalid_interval_returns_error(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_MC_URL, "055", "29.99", "notanumber"], cfg, seeded_engine, mock_scheduler)
        assert "Invalid interval" in reply

    def test_add_microcenter_product(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_MC_URL, "055", "299.99", "180"], cfg, seeded_engine, mock_scheduler)
        assert "tracking" in reply.lower()
        mock_scheduler.add_job.assert_called_once()
        with Session(seeded_engine) as session:
            products = session.query(TrackedProduct).filter_by(url=_MC_URL).all()
        assert len(products) == 1
        assert products[0].price_threshold == 299.99
        assert products[0].check_interval == 180

    def test_add_unifi_product(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_UNIFI_URL, "online"], cfg, seeded_engine, mock_scheduler)
        assert "tracking" in reply.lower()
        mock_scheduler.add_job.assert_called_once()
        with Session(seeded_engine) as session:
            products = session.query(TrackedProduct).filter_by(url=_UNIFI_URL).all()
        assert len(products) == 1

    def test_add_amazon_product(self, cfg, seeded_engine, mock_scheduler):
        reply = _handle_add([_AMAZON_URL, "us"], cfg, seeded_engine, mock_scheduler)
        assert "tracking" in reply.lower()
        mock_scheduler.add_job.assert_called_once()
        with Session(seeded_engine) as session:
            products = session.query(TrackedProduct).filter_by(url=_AMAZON_URL).all()
        assert len(products) == 1


# ── /remove ──────────────────────────────────────────────────────────────────

class TestHandleRemove:
    def test_non_digit_arg_returns_usage(self, seeded_engine, mock_scheduler):
        reply = _handle_remove(["abc"], seeded_engine, mock_scheduler)
        assert "Usage" in reply

    def test_nonexistent_product_returns_error(self, seeded_engine, mock_scheduler):
        reply = _handle_remove(["9999"], seeded_engine, mock_scheduler)
        assert "No active product" in reply

    def test_valid_soft_deletes_and_unschedules(self, cfg, seeded_engine, mock_scheduler):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            product = TrackedProduct(url=_MC_URL, store_id=store.id, name="GPU")
            session.add(product)
            session.commit()
            product_id = product.id
        reply = _handle_remove([str(product_id)], seeded_engine, mock_scheduler)
        assert "Removed" in reply
        mock_scheduler.remove_job.assert_called_once()
        with Session(seeded_engine) as session:
            assert session.get(TrackedProduct, product_id).active is False


# ── /history ─────────────────────────────────────────────────────────────────

class TestHandleHistory:
    def test_no_args_returns_usage(self, cfg, seeded_engine):
        reply = _handle_history([], cfg, seeded_engine)
        assert "Usage" in reply

    def test_days_out_of_range_returns_error(self, cfg, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            product = TrackedProduct(url=_MC_URL, store_id=store.id)
            session.add(product)
            session.commit()
            product_id = product.id
        reply = _handle_history([str(product_id), "0"], cfg, seeded_engine)
        assert "between 1 and 365" in reply

    def test_nonexistent_product_returns_error(self, cfg, seeded_engine):
        reply = _handle_history(["9999"], cfg, seeded_engine)
        assert "No product" in reply

    def test_no_price_data_returns_error(self, cfg, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            product = TrackedProduct(url=_MC_URL, store_id=store.id)
            session.add(product)
            session.commit()
            product_id = product.id
        reply = _handle_history([str(product_id)], cfg, seeded_engine)
        assert "No price data" in reply

    def test_valid_renders_and_sends_chart(self, cfg, seeded_engine):
        with Session(seeded_engine) as session:
            store = session.query(Store).filter_by(store_code="055").first()
            product = TrackedProduct(url=_MC_URL, store_id=store.id, name="GPU")
            session.add(product)
            session.commit()
            product_id = product.id
            session.add(PriceSnapshot(
                product_url=_MC_URL, store_code="055",
                product_name="GPU", price=299.99, in_stock=True,
                checked_at=datetime.now(timezone.utc),
            ))
            session.commit()

        with patch("telegram_listener.grapher.render_price_chart", return_value=b"fake_png") as mock_render, \
             patch("telegram_listener.notifier.send_photo") as mock_send:
            reply = _handle_history([str(product_id)], cfg, seeded_engine)

        assert reply is None  # None means chart was sent successfully
        mock_render.assert_called_once()
        mock_send.assert_called_once()
