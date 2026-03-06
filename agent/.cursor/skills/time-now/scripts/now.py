import argparse
from datetime import datetime, timezone


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--utc", action="store_true", help="Output UTC time (default)")
    g.add_argument("--local", action="store_true", help="Output local time with offset")
    p.add_argument("--format", default="", help="strftime format; if provided, output uses this format")
    args = p.parse_args()

    if args.local:
        now = datetime.now().astimezone()
    else:
        now = datetime.now(timezone.utc)

    if args.format:
        print(now.strftime(args.format))
        return

    if args.local:
        # e.g. 2026-03-05T15:12:34+08:00
        print(now.isoformat(timespec="seconds"))
        return

    # UTC ISO8601 with Z suffix.
    print(now.replace(microsecond=0).isoformat().replace("+00:00", "Z"))


if __name__ == "__main__":
    main()
