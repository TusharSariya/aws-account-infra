from booker.cli import build_parser


def test_adhoc_flags():
    args = build_parser().parse_args(
        ["--activity", "court1", "--date", "2026-08-17", "--time", "05:00", "--dry-run"]
    )
    assert args.activity == "court1"
    assert args.dry_run is True
    assert args.weekly is False


def test_weekly_flag():
    args = build_parser().parse_args(["--weekly", "--json"])
    assert args.weekly is True
    assert args.json is True
