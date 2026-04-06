from pathlib import Path

from app.db.session import create_engine_for_url


def test_create_engine_for_sqlite_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "db" / "app.db"

    engine = create_engine_for_url(f"sqlite:///{db_path}")

    try:
        assert db_path.parent.exists()
    finally:
        engine.dispose()
