#!/usr/bin/env python3
"""Daily TempRadar post to a Telegram channel.

Posts tomorrow's model consensus and the three most likely buckets for every station
marked "telegram": true in stations.js. Same data requests and the same calculation
as the website (see scripts/tempradar_calc.py and calc.js).

Environment:
  TELEGRAM_BOT_TOKEN  bot token from @BotFather   (GitHub secret, never in code)
  TELEGRAM_CHAT_ID    channel, e.g. @yourchannel or -100...   (GitHub secret)
  SITE_URL            optional link to the site, e.g. https://user.github.io/tempradar/
  DRY_RUN=1           print the message instead of sending it
Standard library only.
"""
import json
import os
import re
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

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "TempRadar daily post (open source; github.com)"
OM = "https://api.open-meteo.com/v1/forecast"
OM_ENS = "https://ensemble-api.open-meteo.com/v1/ensemble"


def load_config():
    text = (ROOT / "stations.js").read_text(encoding="utf-8")
    m = re.search(r"/\*JSON-BEGIN\*/(.*)/\*JSON-END\*/", text, re.S)
    if not m:
        raise SystemExit("stations.js: JSON markers not found")
    return json.loads(m.group(1))


def annotate(level, message):
    """Print a GitHub Actions annotation (shown on the run page) or a plain line elsewhere."""
    message = message.replace("\n", " ")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{message}", flush=True)
    else:
        print(f"{level}: {message}", file=sys.stderr, flush=True)


def http_json(url, attempts=4):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                reason = json.loads(e.read().decode("utf-8")).get("reason")
            except Exception:
                reason = None
            last = f"HTTP {e.code} {reason or e.reason}"
            if e.code == 429:
                # Shared GitHub runner IPs can hit Open-Meteo's per-minute limit; wait it out.
                time.sleep(65)
            elif 400 <= e.code < 500:
                break  # a bad request will not get better by retrying
            else:
                time.sleep(10 * (i + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = str(getattr(e, "reason", e))
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"{urllib.parse.urlsplit(url).netloc}: {last}")


def elev_param(s):
    return "nan" if s.get("elev") is None else str(s["elev"])


# The URLs below must stay equivalent to detUrl()/ensUrl() in index.html.
def det_url(s, cfg):
    models = [m["id"] for m in cfg["deterministicModels"] if not m.get("usOnly") or s["country"] == "US"]
    q = {
        "latitude": s["lat"], "longitude": s["lon"], "elevation": elev_param(s), "timezone": s["tz"],
        "daily": "temperature_2m_max", "forecast_days": cfg["forecastDays"], "models": ",".join(models),
    }
    if s["unit"] == "F":
        q["temperature_unit"] = "fahrenheit"
    return OM + "?" + urllib.parse.urlencode(q, safe=",/")


def ens_url(s, cfg):
    q = {
        "latitude": s["lat"], "longitude": s["lon"], "elevation": elev_param(s), "timezone": s["tz"],
        "daily": "temperature_2m_max", "forecast_days": cfg["forecastDays"],
        "models": ",".join(m["id"] for m in cfg["ensembleModels"]),
    }
    if s["unit"] == "F":
        q["temperature_unit"] = "fahrenheit"
    return OM_ENS + "?" + urllib.parse.urlencode(q, safe=",/")


def local_date(tz, add_days, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(tz)
    except Exception:  # Windows has no system time zone database
        raise SystemExit(f"Time zone {tz} not found. On Windows run: python -m pip install tzdata")
    return (now.astimezone(zone) + timedelta(days=add_days)).date().isoformat()


def station_summary(s, cfg, date):
    det = http_json(det_url(s, cfg))
    daily = det.get("daily") or {}
    dates = daily.get("time") or []
    if date not in dates:
        raise RuntimeError(f"{date} not in deterministic forecast")
    i = dates.index(date)
    models = [m for m in cfg["deterministicModels"] if not m.get("usOnly") or s["country"] == "US"]
    values = [(daily.get("temperature_2m_max_" + m["id"]) or [None] * (i + 1))[i] for m in models]
    cons = calc.consensus(values)

    ens = calc.parse_ensemble(http_json(ens_url(s, cfg)), cfg["ensembleModels"])
    members = calc.members_for_date(ens, date)
    probs = calc.bucket_probs([m["value"] for m in members], cfg["bucketWidth"][s["unit"]], "even", s["unit"])
    return {"consensus": cons, "probs": probs, "top": calc.top_buckets(probs, 3)}


def html_escape(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt1(v):
    s = f"{calc.js_round(v * 10) / 10:.1f}"
    return s.replace("-", calc.MINUS, 1) if s.startswith("-") else s


def build_message(cfg, results, date, site_url):
    day = datetime.fromisoformat(date).strftime("%a %d %b").replace(" 0", " ")
    lines = [f"<b>Tomorrow’s highs, {day}</b>", "Model consensus and the three most likely buckets.", ""]
    for s, r in results:
        name = f"<b>{html_escape(s['city'])}</b> {html_escape(s['place'])} ({s['icao'] or 'HKO'})"
        lines.append(name)
        if r is None:
            lines.append("Data unavailable today.")
        else:
            unit = calc.DEG + s["unit"]
            cons = f"Consensus {fmt1(r['consensus']['mean'])}{unit}" if r["consensus"] else "Consensus n/a"
            lines.append(cons + f" ({r['probs']['n']} ensemble members)")
            lines.append("   ".join(f"{b['label']} {calc.pct_label(b['p'])}" for b in r["top"]) or "No ensemble data.")
        lines.append("")
    lines.append("Data only, not trading advice. Local calendar day at each station.")
    if site_url:
        lines.append(f'<a href="{html_escape(site_url)}">Full table and rules: TempRadar</a>')
    return "\n".join(lines)


def send_telegram(token, chat_id, text):
    body = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Print Telegram's description only; never the URL, which contains the token.
        try:
            desc = json.loads(e.read().decode("utf-8")).get("description")
        except Exception:
            desc = None
        raise SystemExit(f"Telegram rejected the message: HTTP {e.code} {desc or ''}".strip())
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach Telegram: {e.reason}")
    if not res.get("ok"):
        raise SystemExit(f"Telegram error: {res.get('description')}")


def main():
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    annotate("notice", "Mode: dry run, the message is only printed" if dry_run else "Mode: send to Telegram")
    cfg = load_config()
    stations = [s for s in cfg["stations"] if s.get("telegram")]
    if not stations:
        raise SystemExit('No station has "telegram": true in stations.js')
    now = datetime.now(timezone.utc)
    results, failures = [], 0
    for s in stations:
        date = local_date(s["tz"], 1, now)
        try:
            results.append((s, station_summary(s, cfg, date)))
        except Exception as e:  # one station failing should not stop the post
            failures += 1
            annotate("warning", f"{s['id']}: {e}")
            results.append((s, None))
        time.sleep(1)  # be gentle with the free API
    if failures == len(stations):
        raise SystemExit("All stations failed; nothing posted.")

    date = local_date(stations[0]["tz"], 1, now)
    text = build_message(cfg, results, date, os.environ.get("SITE_URL", "").strip())

    if dry_run:
        print(text)
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (GitHub secrets), or use DRY_RUN=1.")
    send_telegram(token, chat_id, text)
    annotate("notice", f"Posted {len(stations) - failures} of {len(stations)} stations for {date}.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            annotate("error", str(e.code))
        raise
    except Exception as e:
        annotate("error", f"{type(e).__name__}: {e}")
        raise
