"""Tests for the Telegram posting slots (scripts/post_telegram.py: plan, SLOTS).

Checks that every post gets the right target date, that late scheduled runs are
skipped, and that the cron strings match the workflow file.
Usage: python tests/test_post_slots.py
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import post_telegram as P  # noqa: E402


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


CASES = [
    # (now UTC, kind, schedule, expected)
    ("2026-11-20 06:16", "auto", "15 6 * * *", ("morning", "2026-11-20")),
    ("2026-11-20 12:20", "auto", "15 12 * * *", ("noon", "2026-11-21")),
    ("2026-11-20 15:14", "auto", "15 12 * * *", ("noon", "2026-11-21")),       # 2 h 59 min late: still posts
    ("2026-11-20 20:32", "auto", "15 12 * * *", None),                         # 8 h late, like 19 Nov: skipped
    ("2026-11-20 21:40", "auto", "15 21 * * *", ("evening", "2026-11-21")),
    ("2026-11-21 00:10", "auto", "15 21 * * *", ("evening", "2026-11-21")),    # after midnight, 2 h 55 min late
    ("2026-11-21 00:20", "auto", "15 21 * * *", None),                         # 3 h 5 min late: skipped
    ("2026-11-20 09:30", "auto", "15 6 * * *", None),
    ("2026-11-20 14:50", "auto", "", ("noon", "2026-11-21")),                  # push / manual, auto by time
    ("2026-11-20 07:00", "auto", "", ("morning", "2026-11-20")),
    ("2026-11-20 22:00", "auto", "", ("evening", "2026-11-21")),
    ("2026-11-21 01:00", "auto", "", ("evening", "2026-11-21")),               # just after midnight
    ("2026-11-20 07:00", "evening", "", ("evening", "2026-11-21")),            # manual choice wins
    ("2026-11-20 23:00", "morning", "", ("morning", "2026-11-20")),
    ("2026-11-20 12:20", "auto", "0 9 * * *", None),                           # unknown cron
]


def main():
    bad = 0
    for now, kind, schedule, expected in CASES:
        slot, value = P.plan(at(now), kind, schedule)
        got = (slot, value) if slot else None
        if got != expected:
            bad += 1
            print(f"FAIL {now} kind={kind} schedule={schedule!r}: got {got}, expected {expected} ({value})")
    crons = re.findall(r'cron:\s*"([^"]+)"', (ROOT / ".github" / "workflows" / "telegram.yml").read_text(encoding="utf-8"))
    if sorted(crons) != sorted(v["cron"] for v in P.SLOTS.values()):
        bad += 1
        print(f"FAIL workflow crons {crons} do not match SLOTS")
    if bad:
        sys.exit(1)
    print(f"Post slots OK: {len(CASES)} cases, workflow crons match.")


if __name__ == "__main__":
    main()
