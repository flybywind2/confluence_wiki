from pathlib import Path

from app.db.session import create_engine_for_url


def test_create_engine_for_sqlite_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "db" / "app.db"

    engine = create_engine_for_url(f"sqlite:///{db_path}")

    try:
        assert db_path.parent.exists()
    finally:
        engine.dispose()


def test_create_engine_for_sqlite_sets_busy_timeout_and_wal(tmp_path):
    db_path = tmp_path / "db" / "app.db"

    engine = create_engine_for_url(f"sqlite:///{db_path}")

    try:
        with engine.connect() as connection:
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        assert busy_timeout >= 30000
        assert str(journal_mode).lower() == "wal"
    finally:
        engine.dispose()
