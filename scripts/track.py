#!/usr/bin/env python3
"""Forecast log and calibration for the TempRadar Telegram posts.

Question it answers: when the bot gives a bucket 60%, does that bucket come true about
60% of the time?

Data lives on the repository's "data" branch, which the workflows check out into ./track:
  forecasts/<date>/<slot>.json   what the bot posted: the full bucket distribution
  outcomes/<date>.json           measured daily highs per station (Polymarket rule)
  calibration.json               summary read by the website

The measured high follows the Polymarket rule: routine METARs only (no SPECI), the
T-group in tenths of a degree C (body group if missing), the station's local calendar
day, rounded halves up in the market unit. Source: aviationweather.gov, the source
Polymarket names, which marks every report as METAR or SPECI.

Usage:
  python3 scripts/track.py verify --dir track     score finished days, rebuild calibration.json
Standard library only.
"""
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tempradar_calc as calc  # noqa: E402

USER_AGENT = "TempRadar calibration (open source; github.com)"
AWC = "https://aviationweather.gov/api/data/metar"
# Polymarket settles at the first report of the next day; wait a little longer than that.
SETTLE_AFTER = timedelta(hours=2)
BINS = [i / 10 for i in range(11)]  # 0-10%, 10-20%, ... 90-100%
MIN_CASES = 20  # bins with fewer cases are shown as "not enough data yet"


# ---- Forecast records -------------------------------------------------------------

def forecast_record(slot, date, cfg, results, posted_at):
    """The full distribution behind one post (stations that failed are left out)."""
    stations = []
    for s, r in results:
        if r is None or not r["probs"]["n"]:
            continue
        n = r["probs"]["n"]
        stations.append({
            "id": s["id"], "icao": s["icao"], "unit": s["unit"], "tz": s["tz"],
            "width": cfg["bucketWidth"][s["unit"]], "parity": "even",
            "consensus": r["consensus"]["mean"] if r["consensus"] else None,
            "members": n,
            "buckets": [{"start": b["start"], "count": b["count"], "p": b["count"] / n} for b in r["probs"]["buckets"]],
        })
    return {"version": 1, "slot": slot, "date": date, "posted_at": posted_at, "stations": stations}


def save_forecast(track_dir, rec):
    path = Path(track_dir) / "forecasts" / rec["date"] / f"{rec['slot']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---- Measured highs -------------------------------------------------------------

def day_window(date, tz):
    """UTC start and end of the local calendar day `date` (daylight saving included)."""
    zone = ZoneInfo(tz)
    d = datetime.fromisoformat(date)
    start = d.replace(tzinfo=zone).astimezone(timezone.utc)
    end = (d + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc)
    return start, end


def http_json(url, attempts=4):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8")
                return json.loads(body) if body.strip() else []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"aviationweather.gov: {last}")


def observed_high(icao, tz, unit, date, now):
    """Polymarket-rule daily high, or None while the day is not settled yet."""
    start, end = day_window(date, tz)
    if now < end + SETTLE_AFTER:
        return None
    hours = math.ceil((end - start).total_seconds() / 3600) + 3
    q = {"ids": icao, "format": "json", "date": (end + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": hours}
    return high_from_reports(http_json(AWC + "?" + urllib.parse.urlencode(q)), start, end, unit)


def high_from_reports(reports, start, end, unit):
    """Daily high from aviationweather.gov JSON reports; None until the next day's first
    routine report is in (that is when Polymarket settles)."""
    routine = [x for x in reports if x.get("metarType") == "METAR"]
    if not any(x.get("obsTime", 0) >= end.timestamp() for x in routine):
        return None
    best = None
    count = 0
    for x in routine:
        if not (start.timestamp() <= x.get("obsTime", 0) < end.timestamp()):
            continue
        count += 1
        t = calc.metar_temp(x.get("rawOb", ""))
        if t and (best is None or t["c"] > best["c"]):
            best = {"c": t["c"], "tenths": t["tenths"], "time": x["obsTime"], "raw": x.get("rawOb", "")}
    if best is None:
        return {"value": None, "reports": count, "note": "no routine METAR with a temperature"}
    value = calc.round_half_up(calc.c_to_f(best["c"])) if unit == "F" else calc.round_half_up(best["c"])
    return {"value": value, "c": best["c"], "tenths": best["tenths"], "reports": count,
            "time": datetime.fromtimestamp(best["time"], timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "raw": best["raw"]}


# ---- Scoring ------------------------------------------------------------------------

def wilson(hits, n, z=1.96):
    """95% range for an observed frequency (Wilson score interval)."""
    if n == 0:
        return None, None
    p = hits / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def score_station(st, value):
    """Events (p, hit) and scores for one station forecast against the measured value."""
    observed = calc.bucket_start(value, st["width"], st.get("parity", "even"))
    probs = {b["start"]: b["p"] for b in st["buckets"]}
    events = [(p, start == observed) for start, p in probs.items()]
    if observed not in probs:
        events.append((0.0, True))  # the outcome landed in a bucket the bot gave 0%
    brier = sum((p - (1.0 if hit else 0.0)) ** 2 for p, hit in events)
    ranked = sorted(st["buckets"], key=lambda b: (-b["count"], -b["start"]))
    top1 = ranked[0] if ranked else None
    top3 = ranked[:3]
    return {
        "events": events, "brier": brier,
        "top1_p": top1["p"] if top1 else 0.0, "top1_hit": bool(top1 and top1["start"] == observed),
        "top3_p": sum(b["p"] for b in top3), "top3_hit": any(b["start"] == observed for b in top3),
        "error": None if st.get("consensus") is None else value - st["consensus"],
    }


def empty_group():
    return {"forecasts": 0, "bins": [{"lo": BINS[i], "hi": BINS[i + 1], "n": 0, "hits": 0, "p_sum": 0.0} for i in range(10)],
            "brier_sum": 0.0, "top1_p_sum": 0.0, "top1_hits": 0, "top3_p_sum": 0.0, "top3_hits": 0,
            "err": {"F": [], "C": []}}


def add_to_group(g, st, sc):
    g["forecasts"] += 1
    g["brier_sum"] += sc["brier"]
    g["top1_p_sum"] += sc["top1_p"]
    g["top1_hits"] += 1 if sc["top1_hit"] else 0
    g["top3_p_sum"] += sc["top3_p"]
    g["top3_hits"] += 1 if sc["top3_hit"] else 0
    for p, hit in sc["events"]:
        i = min(9, int(p * 10 + 1e-9))
        b = g["bins"][i]
        b["n"] += 1
        b["hits"] += 1 if hit else 0
        b["p_sum"] += p
    if sc["error"] is not None:
        g["err"][st["unit"]].append(sc["error"])


def finish_group(g):
    n = g["forecasts"]
    out = {"forecasts": n, "bins": []}
    for b in g["bins"]:
        lo, hi = wilson(b["hits"], b["n"])
        out["bins"].append({
            "range": [b["lo"], b["hi"]], "cases": b["n"], "hits": b["hits"],
            "predicted": round(b["p_sum"] / b["n"], 4) if b["n"] else None,
            "observed": round(b["hits"] / b["n"], 4) if b["n"] else None,
            "observed_95": [round(lo, 4), round(hi, 4)] if b["n"] else None,
            "enough": b["n"] >= MIN_CASES,
        })
    out["brier"] = round(g["brier_sum"] / n, 4) if n else None
    out["top1"] = {"predicted": round(g["top1_p_sum"] / n, 4) if n else None, "hit_rate": round(g["top1_hits"] / n, 4) if n else None, "hits": g["top1_hits"]}
    out["top3"] = {"predicted": round(g["top3_p_sum"] / n, 4) if n else None, "hit_rate": round(g["top3_hits"] / n, 4) if n else None, "hits": g["top3_hits"]}
    out["consensus_error"] = {}
    for unit, errs in g["err"].items():
        if errs:
            out["consensus_error"][unit] = {"n": len(errs), "bias": round(sum(errs) / len(errs), 2),
                                            "mae": round(sum(abs(e) for e in errs) / len(errs), 2)}
    return out


def calibration(forecasts, outcomes, now):
    """Summary over every scored station forecast, overall and per post slot."""
    groups = {"all": empty_group(), "morning": empty_group(), "noon": empty_group(), "evening": empty_group()}
    per_station = {}  # consensus errors per station: the basis for a later bias correction
    dates = set()
    pending = 0
    for rec in forecasts:
        day = outcomes.get(rec["date"], {})
        for st in rec["stations"]:
            o = day.get(st["id"])
            if not o or o.get("value") is None:
                pending += 1
                continue
            sc = score_station(st, o["value"])
            add_to_group(groups["all"], st, sc)
            if rec["slot"] in groups:
                add_to_group(groups[rec["slot"]], st, sc)
            if sc["error"] is not None:
                ps = per_station.setdefault(st["id"], {"unit": st["unit"], "errors": [], "top1_hits": 0, "n": 0})
                ps["errors"].append(sc["error"])
                ps["n"] += 1
                ps["top1_hits"] += 1 if sc["top1_hit"] else 0
            dates.add(rec["date"])
    return {
        "version": 1,
        "updated": now.strftime("%Y-%m-%dT%H:%MZ"),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "days": len(dates),
        "pending": pending,
        "min_cases": MIN_CASES,
        "groups": {k: finish_group(v) for k, v in groups.items()},
        # error = measured high minus consensus; a positive bias means the forecast ran cold
        "stations": {sid: {"unit": v["unit"], "forecasts": v["n"], "top1_hits": v["top1_hits"],
                           "bias": round(sum(v["errors"]) / len(v["errors"]), 2),
                           "mae": round(sum(abs(x) for x in v["errors"]) / len(v["errors"]), 2)}
                     for sid, v in sorted(per_station.items())},
    }


# ---- Verify command ---------------------------------------------------------------------

def load_forecasts(track_dir):
    out = []
    for p in sorted((Path(track_dir) / "forecasts").glob("*/*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def verify(track_dir, now=None):
    now = now or datetime.now(timezone.utc)
    track_dir = Path(track_dir)
    forecasts = load_forecasts(track_dir)
    outcomes = {}
    # Stations to measure per date: every station that appears in a forecast for that date.
    wanted = {}
    for rec in forecasts:
        for st in rec["stations"]:
            wanted.setdefault(rec["date"], {})[st["id"]] = st
    for date, stations in sorted(wanted.items()):
        path = track_dir / "outcomes" / f"{date}.json"
        day = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        changed = False
        for sid, st in stations.items():
            if sid in day and day[sid].get("value") is not None:
                continue
            try:
                o = observed_high(st["icao"], st["tz"], st["unit"], date, now)
            except Exception as e:
                print(f"::warning::{sid} {date}: {e}", flush=True)
                o = None
            time.sleep(1)
            if o is not None:
                day[sid] = o
                changed = True
                print(f"{date} {sid}: {o.get('value')}{st['unit']} ({o.get('reports')} routine reports)")
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(day, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        outcomes[date] = day
    summary = calibration(forecasts, outcomes, now)
    (track_dir / "calibration.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    a = summary["groups"]["all"]
    print(f"::notice::Scored {a['forecasts']} station forecasts over {summary['days']} days; {summary['pending']} waiting for their day to end.")
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 1 and args[0] == "verify":
        d = args[args.index("--dir") + 1] if "--dir" in args else "track"
        verify(d)
    else:
        print(__doc__)
        sys.exit(2)
