from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Retailer(Base):
    """A supported retailer (e.g. MicroCenter, Amazon)."""

    __tablename__ = "retailers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug e.g. "microcenter"
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)  # prefix for URL validation
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Store(Base):
    """A store location belonging to a retailer."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    retailer_id: Mapped[str] = mapped_column(String, ForeignKey("retailers.id"), nullable=False)
    store_code: Mapped[str] = mapped_column(String, nullable=False)  # retailer-specific code e.g. "055"
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (UniqueConstraint("retailer_id", "store_code"),)


class TrackedProduct(Base):
    """A product+store combination to monitor."""

    __tablename__ = "tracked_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("stores.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    check_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (UniqueConstraint("url", "store_id"),)


class PriceSnapshot(Base):
    """One record per check per (product_url, store_code) combination."""

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_url: Mapped[str] = mapped_column(String, index=True)
    store_code: Mapped[str] = mapped_column(String, index=True)
    product_name: Mapped[str] = mapped_column(String)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


def init_db(database_url: str):
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_last_snapshot(
    session: Session, product_url: str, store_code: str
) -> PriceSnapshot | None:
    return (
        session.query(PriceSnapshot)
        .filter_by(product_url=product_url, store_code=store_code)
        .order_by(PriceSnapshot.checked_at.desc())
        .first()
    )


# --- Retailer CRUD ---

def list_retailers(session: Session) -> list[Retailer]:
    return session.query(Retailer).order_by(Retailer.id).all()


def add_retailer(
    session: Session, retailer_id: str, name: str, base_url: str | None = None
) -> Retailer:
    retailer = Retailer(id=retailer_id, name=name, base_url=base_url)
    session.add(retailer)
    session.commit()
    return retailer


# --- Store CRUD ---

def list_stores(session: Session) -> list[Store]:
    return session.query(Store).order_by(Store.retailer_id, Store.store_code).all()


def get_store_by_code(session: Session, retailer_id: str, store_code: str) -> Store | None:
    return (
        session.query(Store)
        .filter_by(retailer_id=retailer_id, store_code=store_code)
        .first()
    )


def add_store(session: Session, retailer_id: str, store_code: str, name: str) -> Store:
    store = Store(retailer_id=retailer_id, store_code=store_code, name=name)
    session.add(store)
    session.commit()
    return store


def remove_store(session: Session, store_id: int) -> bool:
    store = session.get(Store, store_id)
    if store is None:
        return False
    session.delete(store)
    session.commit()
    return True


# --- TrackedProduct CRUD ---

def list_products(session: Session, *, include_inactive: bool = False) -> list[TrackedProduct]:
    q = session.query(TrackedProduct)
    if not include_inactive:
        q = q.filter_by(active=True)
    return q.order_by(TrackedProduct.id).all()


def add_product(
    session: Session,
    *,
    url: str,
    store_id: int,
    check_interval: int | None = None,
    price_threshold: float | None = None,
) -> TrackedProduct:
    product = TrackedProduct(
        url=url,
        store_id=store_id,
        check_interval=check_interval,
        price_threshold=price_threshold,
    )
    session.add(product)
    session.commit()
    return product


def remove_product(session: Session, product_id: int) -> bool:
    """Soft-delete: sets active=False to preserve price history."""
    product = session.get(TrackedProduct, product_id)
    if product is None or not product.active:
        return False
    product.active = False
    session.commit()
    return True


def backfill_product_name(session: Session, product_id: int, name: str) -> None:
    product = session.get(TrackedProduct, product_id)
    if product and product.name is None:
        product.name = name
        session.commit()


def record_failure(session: Session, product_id: int) -> int:
    """Increment consecutive_failures. Returns the new count."""
    product = session.get(TrackedProduct, product_id)
    if product is None:
        return 0
    product.consecutive_failures += 1
    session.commit()
    return product.consecutive_failures


def reset_failures(session: Session, product_id: int) -> int:
    """Reset consecutive_failures to 0. Returns the previous count."""
    product = session.get(TrackedProduct, product_id)
    if product is None:
        return 0
    previous = product.consecutive_failures
    if previous:
        product.consecutive_failures = 0
        session.commit()
    return previous
