from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import (
    PriceSnapshot,
    Retailer,
    Store,
    TrackedProduct,
    add_store,
    backfill_product_name,
    get_last_snapshot,
    get_price_history,
    get_store_by_code,
    list_products,
    record_failure,
    remove_product,
    remove_store,
    reset_failures,
)


def _seed_store(engine, retailer_id="mc", store_code="055", name="Test Store"):
    with Session(engine) as session:
        if not session.get(Retailer, retailer_id):
            session.add(Retailer(id=retailer_id, name="Test Retailer", base_url="https://example.com"))
        store = Store(retailer_id=retailer_id, store_code=store_code, name=name)
        session.add(store)
        session.commit()
        return store.id


def _seed_product(engine, store_id, url="https://example.com/product/1"):
    with Session(engine) as session:
        product = TrackedProduct(url=url, store_id=store_id)
        session.add(product)
        session.commit()
        return product.id


class TestListProducts:
    def test_only_active_by_default(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            remove_product(session, pid)
        with Session(engine) as session:
            assert list_products(session) == []

    def test_include_inactive(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            remove_product(session, pid)
        with Session(engine) as session:
            products = list_products(session, include_inactive=True)
        assert len(products) == 1
        assert products[0].active is False


class TestRemoveProduct:
    def test_soft_delete_sets_inactive(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            assert remove_product(session, pid) is True
        with Session(engine) as session:
            assert session.get(TrackedProduct, pid).active is False

    def test_nonexistent_returns_false(self, engine):
        with Session(engine) as session:
            assert remove_product(session, 9999) is False

    def test_preserves_snapshots(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            session.add(PriceSnapshot(
                product_url="https://example.com/product/1",
                store_code="055",
                product_name="Test",
                price=100.0,
                in_stock=True,
            ))
            session.commit()
        with Session(engine) as session:
            remove_product(session, pid)
        with Session(engine) as session:
            assert session.query(PriceSnapshot).count() == 1


class TestUniqueConstraints:
    def test_duplicate_product_url_and_store(self, engine):
        store_id = _seed_store(engine)
        with Session(engine) as session:
            session.add(TrackedProduct(url="https://example.com/p/1", store_id=store_id))
            session.commit()
        with pytest.raises(IntegrityError):
            with Session(engine) as session:
                session.add(TrackedProduct(url="https://example.com/p/1", store_id=store_id))
                session.commit()

    def test_duplicate_store_code_same_retailer(self, engine):
        with Session(engine) as session:
            session.add(Retailer(id="mc", name="MC", base_url="https://example.com"))
            session.add(Store(retailer_id="mc", store_code="055", name="Store 1"))
            session.commit()
        with pytest.raises(IntegrityError):
            with Session(engine) as session:
                session.add(Store(retailer_id="mc", store_code="055", name="Store 2"))
                session.commit()


class TestSnapshots:
    def test_get_last_snapshot_returns_most_recent(self, engine):
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            session.add(PriceSnapshot(
                product_url="https://example.com/p", store_code="055",
                product_name="P", price=100.0, in_stock=True,
                checked_at=now - timedelta(hours=2),
            ))
            session.add(PriceSnapshot(
                product_url="https://example.com/p", store_code="055",
                product_name="P", price=90.0, in_stock=True,
                checked_at=now - timedelta(hours=1),
            ))
            session.commit()
        with Session(engine) as session:
            snap = get_last_snapshot(session, "https://example.com/p", "055")
        assert snap.price == 90.0

    def test_get_last_snapshot_returns_none_when_empty(self, engine):
        with Session(engine) as session:
            assert get_last_snapshot(session, "https://example.com/p", "055") is None

    def test_get_price_history_filters_by_since(self, engine):
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            session.add(PriceSnapshot(
                product_url="https://example.com/p", store_code="055",
                product_name="P", price=100.0, in_stock=True,
                checked_at=now - timedelta(days=10),
            ))
            session.add(PriceSnapshot(
                product_url="https://example.com/p", store_code="055",
                product_name="P", price=90.0, in_stock=True,
                checked_at=now - timedelta(days=1),
            ))
            session.commit()
        with Session(engine) as session:
            history = get_price_history(
                session, "https://example.com/p", "055",
                since=now - timedelta(days=7),
            )
        assert len(history) == 1
        assert history[0].price == 90.0


class TestFailureTracking:
    def test_record_failure_increments_counter(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            assert record_failure(session, pid) == 1
        with Session(engine) as session:
            assert record_failure(session, pid) == 2

    def test_reset_failures_returns_previous_and_clears(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            record_failure(session, pid)
            record_failure(session, pid)
        with Session(engine) as session:
            assert reset_failures(session, pid) == 2
        with Session(engine) as session:
            assert session.get(TrackedProduct, pid).consecutive_failures == 0

    def test_reset_failures_when_zero_is_noop(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            assert reset_failures(session, pid) == 0

    def test_backfill_product_name_only_sets_when_none(self, engine):
        store_id = _seed_store(engine)
        pid = _seed_product(engine, store_id)
        with Session(engine) as session:
            backfill_product_name(session, pid, "First Name")
        with Session(engine) as session:
            backfill_product_name(session, pid, "Second Name")
        with Session(engine) as session:
            assert session.get(TrackedProduct, pid).name == "First Name"


class TestStoreCRUD:
    def test_add_and_get_store_by_code(self, engine):
        with Session(engine) as session:
            session.add(Retailer(id="mc", name="MC", base_url="https://example.com"))
            session.commit()
        with Session(engine) as session:
            store = add_store(session, "mc", "055", "Test Store")
            store_id = store.id
        with Session(engine) as session:
            found = get_store_by_code(session, "mc", "055")
        assert found is not None
        assert found.name == "Test Store"
        assert found.id == store_id

    def test_remove_store(self, engine):
        with Session(engine) as session:
            session.add(Retailer(id="mc", name="MC", base_url="https://example.com"))
            store = Store(retailer_id="mc", store_code="055", name="Test Store")
            session.add(store)
            session.commit()
            store_id = store.id
        with Session(engine) as session:
            assert remove_store(session, store_id) is True
        with Session(engine) as session:
            assert get_store_by_code(session, "mc", "055") is None

    def test_remove_nonexistent_store_returns_false(self, engine):
        with Session(engine) as session:
            assert remove_store(session, 9999) is False
