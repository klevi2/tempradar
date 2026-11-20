"""Tests for scripts/track.py: measured highs (Polymarket rule) and calibration math.
Usage: python tests/test_track.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import track as T  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    if got != want:
        fails += 1
        print(f"FAIL {name}: got {got!r}, want {want!r}")


def ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


# Local day windows, with and without daylight saving.
s, e = T.day_window("2026-11-20", "America/New_York")
check("window EST", (s.isoformat(), e.isoformat()), ("2026-11-20T05:00:00+00:00", "2026-11-21T05:00:00+00:00"))
s, e = T.day_window("2026-07-04", "America/New_York")
check("window EDT", (s.isoformat(), e.isoformat()), ("2026-07-04T04:00:00+00:00", "2026-07-05T04:00:00+00:00"))
s, e = T.day_window("2026-11-20", "Asia/Seoul")
check("window KST", s.isoformat(), "2026-11-19T15:00:00+00:00")

# Measured high: SPECI ignored, T-group used, next-day report required.
start, end = T.day_window("2026-11-20", "America/New_York")
reports = [
    {"metarType": "METAR", "obsTime": ts("2026-11-20 18:51"), "rawOb": "METAR KLGA 201851Z 17/02 A3040 RMK AO2 T01720022"},
    {"metarType": "METAR", "obsTime": ts("2026-11-20 19:51"), "rawOb": "METAR KLGA 201951Z 18/02 A3040 RMK AO2 T01780022"},
    {"metarType": "SPECI", "obsTime": ts("2026-11-20 20:12"), "rawOb": "SPECI KLGA 202012Z 19/02 A3040 RMK AO2 T01940022"},
    {"metarType": "METAR", "obsTime": ts("2026-11-20 04:51"), "rawOb": "METAR KLGA 200451Z 25/02 A3040 RMK AO2 T02500022"},
]
check("not settled without next-day report", T.high_from_reports(reports, start, end, "F"), None)
reports.append({"metarType": "METAR", "obsTime": ts("2026-11-21 05:51"), "rawOb": "METAR KLGA 210551Z 08/01 A3040 RMK AO2 T00800010"})
h = T.high_from_reports(reports, start, end, "F")
check("high value (17.8 C -> 64 F, SPECI and previous day ignored)", (h["value"], h["c"], h["reports"]), (64, 17.8, 2))
h = T.high_from_reports(reports, start, end, "C")
check("high value in C", h["value"], 18)

# Scoring one forecast.
st = {"id": "klga", "unit": "F", "width": 2, "parity": "even", "consensus": 62.4,
      "buckets": [{"start": 60, "count": 60, "p": 0.6}, {"start": 62, "count": 30, "p": 0.3}, {"start": 58, "count": 10, "p": 0.1}]}
sc = T.score_station(st, 61)
check("top1 hit", (sc["top1_hit"], sc["top1_p"]), (True, 0.6))
check("brier", round(sc["brier"], 6), round(0.4 ** 2 + 0.3 ** 2 + 0.1 ** 2, 6))
check("error", round(sc["error"], 6), round(61 - 62.4, 6))
sc = T.score_station(st, 70)
check("outcome outside all buckets adds a 0% hit", (0.0, True) in sc["events"], True)
check("top3 miss", sc["top3_hit"], False)

# Calibration: 10 forecasts at 60% for the top bucket, 6 of them right -> 60% bin observes 60%.
forecasts, outcomes = [], {}
for i in range(10):
    date = f"2026-11-{10 + i:02d}"
    forecasts.append({"slot": "noon", "date": date, "stations": [dict(st)]})
    outcomes[date] = {"klga": {"value": 60 if i < 6 else 62}}
summary = T.calibration(forecasts, outcomes, datetime(2026, 11, 21, tzinfo=timezone.utc))
b60 = summary["groups"]["all"]["bins"][6]
check("60% bin", (b60["cases"], b60["hits"], b60["predicted"], b60["observed"]), (10, 6, 0.6, 0.6))
b30 = summary["groups"]["all"]["bins"][3]
check("30% bin", (b30["cases"], b30["hits"]), (10, 4))
check("top1 hit rate", summary["groups"]["noon"]["top1"]["hit_rate"], 0.6)
check("days", (summary["days"], summary["first_date"], summary["last_date"]), (10, "2026-11-10", "2026-11-19"))
lo, hi = T.wilson(6, 10)
check("wilson range", (round(lo, 3), round(hi, 3)), (0.313, 0.832))

if fails:
    sys.exit(1)
print("Track tests OK.")
