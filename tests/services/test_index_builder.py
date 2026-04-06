from datetime import datetime
from pathlib import Path

from app.services.index_builder import append_space_log


def test_append_space_log_does_not_overwrite_newer_entries_when_read_snapshot_is_stale(tmp_path, monkeypatch):
    root = tmp_path
    log_path = root / "spaces" / "DEMO" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "# DEMO Activity Log\n\n"
        "## [2026-04-07T03:00:00+09:00] sync | DEMO | bootstrap\n"
        "- pages: [[DEMO/root-page-100]]\n\n"
        "## [2026-04-07T03:10:00+09:00] sync | DEMO | incremental\n"
        "- pages: [[DEMO/child-page-200]]\n",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def stale_read_text(self: Path, *args, **kwargs):
        if self == log_path:
            return (
                "# DEMO Activity Log\n\n"
                "## [2026-04-07T03:00:00+09:00] sync | DEMO | bootstrap\n"
                "- pages: [[DEMO/root-page-100]]\n"
            )
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", stale_read_text)

    append_space_log(
        root=root,
        space_key="DEMO",
        mode="incremental",
        timestamp=datetime.fromisoformat("2026-04-07T03:20:00+09:00"),
        documents=[{"slug": "root-page-100"}],
    )

    log_text = original_read_text(log_path, encoding="utf-8")
    assert "## [2026-04-07T03:10:00+09:00] sync | DEMO | incremental" in log_text
    assert "## [2026-04-07T03:20:00+09:00] sync | DEMO | incremental" in log_text
