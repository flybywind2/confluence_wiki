from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


@lru_cache(maxsize=8)
def create_engine_for_url(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return engine


@lru_cache(maxsize=8)
def create_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=create_engine_for_url(database_url),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine_for_url(settings.database_url)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    return create_session_factory(settings.database_url)


def db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
