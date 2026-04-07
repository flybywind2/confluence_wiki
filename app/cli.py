from __future__ import annotations

import argparse
import logging

from app.core.config import get_settings
from app.services.sync_service import SyncService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence-wiki")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    bootstrap.add_argument("--space", required=True)
    bootstrap.add_argument("--page-id", required=True)
    bootstrap.add_argument("--verbose", action="store_true")

    sync = subparsers.add_parser("sync")
    sync.add_argument("--space", required=True)
    sync.add_argument("--verbose", action="store_true")
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.verbose)
    service = SyncService(settings=get_settings())

    result = None
    if args.command == "bootstrap":
        result = service.run_bootstrap(space_key=args.space, root_page_id=args.page_id)
    elif args.command == "sync":
        result = service.run_incremental(space_key=args.space)
    if result and result.skipped_attachments:
        for item in result.skipped_attachments:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
