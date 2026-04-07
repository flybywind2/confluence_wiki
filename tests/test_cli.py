from app.cli import build_parser


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
