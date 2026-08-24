"""CLI: python3 -m reveille [JOURNAL...] [--label N] [--now EPOCH]
[--ends-at EPOCH] [--config FILE] [--json] [--statusline]"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from . import core


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reveille",
        description="Session-start briefing compiler: authoritative journal "
                    "session counter, sprint clock, standing items.",
    )
    p.add_argument("journals", nargs="*",
                   help="journal files (default: ~/journal/STATE.md)")
    p.add_argument("--label", default=None,
                   help="harness briefing label to reconcile, e.g. '#4' or 4")
    p.add_argument("--now", type=int, default=None,
                   help="current unix epoch (default: actual now)")
    p.add_argument("--ends-at", dest="ends_at", type=int, default=None,
                   help="sprint end unix epoch (overrides config)")
    p.add_argument("--config", default=None,
                   help="TOML config (default: ~/.config/reveille/config.toml)")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--statusline", action="store_true")
    p.add_argument("--version", action="version",
                   version=f"reveille {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = args.now if args.now is not None else int(time.time())
    paths = [Path(j).expanduser() for j in args.journals] or \
            [Path("~/journal/STATE.md").expanduser()]

    for p in paths:
        if not p.is_file():
            print(f"reveille: journal not found: {p}", file=sys.stderr)
            return 2

    try:
        cfg = core.load_config(args.config)
    except Exception as e:
        print(f"reveille: malformed config: {e}", file=sys.stderr)
        return 2
    ends_at = args.ends_at if args.ends_at is not None else cfg["ends_at"]
    cfg = {"ends_at": ends_at, "items": cfg["items"],
           "labels": cfg.get("labels") or {}}

    texts = []
    for p in paths:
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            print(f"reveille: unreadable journal {p}: {e}", file=sys.stderr)
            return 2
    merged = "\n".join(texts)

    js = core.build_report(merged, str(paths[0]), args.label, now, cfg)

    if args.as_json:
        print(json.dumps(js))
        exit_code = 0 if js["match"] is not False else 1
        return exit_code
    if args.statusline:
        print(core.statusline(js))
        exit_code = 0 if js["match"] is not False else 1
        return exit_code

    print(core.render_human(js))
    return 0 if js["match"] is not False else 1


if __name__ == "__main__":
    sys.exit(main())
