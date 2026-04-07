import sys

import app.cli as cli_module
from app.cli import build_parser
from app.services.sync_service import SyncResult


def test_build_parser_accepts_verbose_for_bootstrap():
    parser = build_parser()

    args = parser.parse_args(["bootstrap", "--space", "DEMO", "--page-id", "123", "--verbose"])

    assert args.command == "bootstrap"
    assert args.verbose is True


def test_build_parser_accepts_verbose_for_sync():
    parser = build_parser()

    args = parser.parse_args(["sync", "--space", "DEMO", "--verbose"])

    assert args.command == "sync"
    assert args.verbose is True


def test_main_prints_skipped_attachments_at_end(monkeypatch, capsys):
    class _FakeSyncService:
        def __init__(self, settings):
            self.settings = settings

        def run_incremental(self, space_key: str):
            return SyncResult(
                mode="incremental",
                space_key=space_key,
                processed_pages=1,
                processed_assets=0,
                skipped_attachments=["DEMO/100 diagram.png", "DEMO/100 missing-inline.png"],
            )

    monkeypatch.setattr(cli_module, "SyncService", _FakeSyncService)
    monkeypatch.setattr(cli_module, "get_settings", lambda: object())
    monkeypatch.setattr(sys, "argv", ["confluence-wiki", "sync", "--space", "DEMO"])

    exit_code = cli_module.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.splitlines() == ["- DEMO/100 diagram.png", "- DEMO/100 missing-inline.png"]
