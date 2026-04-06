from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.services.sync_service import SyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence-wiki")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--space", required=True)
    bootstrap.add_argument("--page-id", required=True)

    sync = subparsers.add_parser("sync")
    sync.add_argument("--space", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = SyncService(settings=get_settings())

    if args.command == "bootstrap":
        service.run_bootstrap(space_key=args.space, root_page_id=args.page_id)
    elif args.command == "sync":
        service.run_incremental(space_key=args.space)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
