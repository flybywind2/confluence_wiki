from alembic import command
from alembic.config import Config


def test_alembic_upgrade_runs_against_sqlite(tmp_path):
    db_path = tmp_path / "app.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    assert db_path.exists()
