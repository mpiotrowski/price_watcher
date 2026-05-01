import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config import AppConfig
from db import Base, Retailer, Store


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def cfg():
    return AppConfig(
        telegram_bot_token="test-token",
        telegram_chat_id="12345",
        database_url="sqlite:///:memory:",
        check_interval=300,
        stores={},
        products=[],
    )


@pytest.fixture
def seeded_engine(engine):
    """Engine pre-loaded with both retailers and one store each."""
    with Session(engine) as session:
        session.add(Retailer(
            id="microcenter",
            name="MicroCenter",
            base_url="https://www.microcenter.com",
        ))
        session.add(Retailer(
            id="unifi",
            name="Unifi Store",
            base_url="https://store.ui.com",
        ))
        session.add(Store(retailer_id="microcenter", store_code="055", name="Madison Heights, MI"))
        session.add(Store(retailer_id="unifi", store_code="online", name="Online Store"))
        session.commit()
    return engine
