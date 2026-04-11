from pathlib import Path

from app.db.session import create_engine_for_url, run_sqlite_maintenance_for_url


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
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            temp_store = connection.exec_driver_sql("PRAGMA temp_store").scalar_one()
            wal_autocheckpoint = connection.exec_driver_sql("PRAGMA wal_autocheckpoint").scalar_one()
        assert busy_timeout >= 30000
        assert str(journal_mode).lower() == "wal"
        assert int(foreign_keys) == 1
        assert int(temp_store) == 2
        assert int(wal_autocheckpoint) >= 1000
    finally:
        engine.dispose()


def test_run_sqlite_maintenance_executes_optimize_and_checkpoint(tmp_path):
    db_path = tmp_path / "db" / "app.db"
    engine = create_engine_for_url(f"sqlite:///{db_path}")

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
            connection.exec_driver_sql("INSERT INTO sample(name) VALUES ('demo')")

        run_sqlite_maintenance_for_url(f"sqlite:///{db_path}")

        with engine.connect() as connection:
            count = connection.exec_driver_sql("SELECT COUNT(*) FROM sample").scalar_one()
        assert count == 1
    finally:
        engine.dispose()
