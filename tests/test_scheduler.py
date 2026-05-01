from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from db import PriceSnapshot, Store, TrackedProduct, record_failure
from scrapers.microcenter import ScrapeResult
from scheduler import run_check

_MC_URL = "https://www.microcenter.com/product/123/gpu"
_STORE_CODE = "055"


def _make_result(**kwargs) -> ScrapeResult:
    defaults = dict(
        product_name="Test GPU",
        price=299.99,
        in_stock=True,
        store_code=_STORE_CODE,
        url=_MC_URL,
    )
    defaults.update(kwargs)
    return ScrapeResult(**defaults)


@pytest.fixture
def product_in_db(seeded_engine):
    """Returns (engine, product_id, store_id, store_code, retailer_id, store_name)."""
    with Session(seeded_engine) as session:
        store = session.query(Store).filter_by(store_code=_STORE_CODE).first()
        product = TrackedProduct(url=_MC_URL, store_id=store.id)
        session.add(product)
        session.commit()
        return (
            seeded_engine,
            product.id,
            store.id,
            store.store_code,
            "microcenter",
            store.name,
        )


def _run(cfg, product_in_db, *, scrape_result=None, scrape_error=None, price_threshold=None):
    engine, product_id, store_id, store_code, retailer_id, store_name = product_in_db
    if scrape_error:
        mock_scraper = MagicMock(side_effect=scrape_error)
    else:
        mock_scraper = MagicMock(return_value=scrape_result or _make_result())

    with patch("scheduler.get_scraper", return_value=mock_scraper), \
         patch("scheduler.notifier") as mock_notifier:
        run_check(
            cfg, product_id, _MC_URL, store_id, store_code,
            retailer_id, store_name, price_threshold, engine,
        )
        return mock_notifier


def _seed_snapshot(engine, price, in_stock=True):
    with Session(engine) as session:
        session.add(PriceSnapshot(
            product_url=_MC_URL,
            store_code=_STORE_CODE,
            product_name="Test GPU",
            price=price,
            in_stock=in_stock,
            checked_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ))
        session.commit()


class TestFirstCheck:
    def test_no_notification_on_first_check(self, cfg, product_in_db):
        mock_notifier = _run(cfg, product_in_db)
        mock_notifier.stock_changed.assert_not_called()
        mock_notifier.price_changed.assert_not_called()

    def test_snapshot_saved_on_first_check(self, cfg, product_in_db):
        engine = product_in_db[0]
        _run(cfg, product_in_db)
        with Session(engine) as session:
            snaps = session.query(PriceSnapshot).all()
        assert len(snaps) == 1
        assert snaps[0].price == 299.99
        assert snaps[0].in_stock is True


class TestPriceChanges:
    def test_price_unchanged_no_notification(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 299.99)
        mock_notifier = _run(cfg, product_in_db, scrape_result=_make_result(price=299.99))
        mock_notifier.price_changed.assert_not_called()

    def test_price_drop_triggers_notification(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 299.99)
        mock_notifier = _run(cfg, product_in_db, scrape_result=_make_result(price=249.99))
        mock_notifier.price_changed.assert_called_once()
        kw = mock_notifier.price_changed.call_args.kwargs
        assert kw["old_price"] == 299.99
        assert kw["new_price"] == 249.99

    def test_price_increase_triggers_notification(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 299.99)
        mock_notifier = _run(cfg, product_in_db, scrape_result=_make_result(price=349.99))
        mock_notifier.price_changed.assert_called_once()

    def test_price_drop_above_threshold_no_notification(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 399.99)
        # drops to 349.99 but threshold is 300.00 — still above, no notification
        mock_notifier = _run(
            cfg, product_in_db,
            scrape_result=_make_result(price=349.99),
            price_threshold=300.0,
        )
        mock_notifier.price_changed.assert_not_called()

    def test_price_drop_at_or_below_threshold_notifies(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 399.99)
        mock_notifier = _run(
            cfg, product_in_db,
            scrape_result=_make_result(price=249.99),
            price_threshold=300.0,
        )
        mock_notifier.price_changed.assert_called_once()


class TestStockChanges:
    def test_out_to_in_stock_notifies(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 299.99, in_stock=False)
        mock_notifier = _run(cfg, product_in_db, scrape_result=_make_result(in_stock=True))
        mock_notifier.stock_changed.assert_called_once()
        assert mock_notifier.stock_changed.call_args.kwargs["in_stock"] is True

    def test_in_to_out_stock_notifies(self, cfg, product_in_db):
        _seed_snapshot(product_in_db[0], 299.99, in_stock=True)
        mock_notifier = _run(cfg, product_in_db, scrape_result=_make_result(in_stock=False))
        mock_notifier.stock_changed.assert_called_once()

    def test_stock_change_suppresses_price_change_notification(self, cfg, product_in_db):
        # both stock and price changed — stock_changed wins
        _seed_snapshot(product_in_db[0], 399.99, in_stock=False)
        mock_notifier = _run(
            cfg, product_in_db,
            scrape_result=_make_result(in_stock=True, price=299.99),
        )
        mock_notifier.stock_changed.assert_called_once()
        mock_notifier.price_changed.assert_not_called()


class TestScrapeFailures:
    def test_first_failure_sends_notification(self, cfg, product_in_db):
        mock_notifier = _run(cfg, product_in_db, scrape_error=RuntimeError("timeout"))
        mock_notifier.scrape_failed.assert_called_once()

    def test_second_failure_no_repeat_notification(self, cfg, product_in_db):
        engine, product_id, *_ = product_in_db
        with Session(engine) as session:
            record_failure(session, product_id)  # pre-seed one failure
        mock_notifier = _run(cfg, product_in_db, scrape_error=RuntimeError("timeout"))
        mock_notifier.scrape_failed.assert_not_called()

    def test_failure_increments_db_counter(self, cfg, product_in_db):
        engine, product_id, *_ = product_in_db
        _run(cfg, product_in_db, scrape_error=RuntimeError("fail"))
        with Session(engine) as session:
            assert session.get(TrackedProduct, product_id).consecutive_failures == 1

    def test_recovery_after_failure_sends_notification(self, cfg, product_in_db):
        engine, product_id, *_ = product_in_db
        with Session(engine) as session:
            record_failure(session, product_id)
        mock_notifier = _run(cfg, product_in_db)
        mock_notifier.scrape_recovered.assert_called_once()

    def test_success_with_no_prior_failures_no_recovery_notification(self, cfg, product_in_db):
        mock_notifier = _run(cfg, product_in_db)
        mock_notifier.scrape_recovered.assert_not_called()

    def test_snapshot_saved_after_successful_scrape(self, cfg, product_in_db):
        engine = product_in_db[0]
        _run(cfg, product_in_db)
        with Session(engine) as session:
            assert session.query(PriceSnapshot).count() == 1

    def test_product_name_backfilled_from_scrape_result(self, cfg, product_in_db):
        engine, product_id, *_ = product_in_db
        _run(cfg, product_in_db, scrape_result=_make_result(product_name="Awesome GPU"))
        with Session(engine) as session:
            assert session.get(TrackedProduct, product_id).name == "Awesome GPU"
