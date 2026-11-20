"""TempRadar calculation core, ported line for line from calc.js.

Only the parts the daily post needs: rounding, buckets, ensemble parsing, consensus.
tests/test_parity.py runs both implementations on the same input and requires
identical output, so change calc.js and this file together.
"""
import math
import re

MINUS = "−"
EN_DASH = "–"
DEG = "°"


def js_round(x):
    """JavaScript Math.round: halves go toward +infinity (Python's round() does not)."""
    return math.floor(x + 0.5)


def round_half_up(x):
    """Nearest whole degree, exact halves upward: 64.5 -> 65, -8.5 -> -8."""
    return math.floor(js_round(x * 1e6) / 1e6 + 0.5)


def c_to_f(c):
    return c * 9 / 5 + 32


def bucket_start(v, width, parity):
    if width == 1:
        return v
    offset = 1 if parity == "odd" else 0
    return v - ((v - offset) % width)  # Python % is already non-negative for width > 0


def fmt_deg(v):
    return (MINUS if v < 0 else "") + str(abs(v))


def bucket_label(start, width, unit):
    if width == 1:
        return fmt_deg(start) + DEG + unit
    return fmt_deg(start) + EN_DASH + fmt_deg(start + width - 1) + DEG + unit


_MEMBER_KEY = re.compile(r"^(?:_member(\d+))?_(.+)$")


def parse_ensemble(data, ensemble_models):
    daily = data.get("daily") or {}
    known = [m["key"] for m in ensemble_models]
    members = []
    for k in sorted(daily.keys()):
        if not k.startswith("temperature_2m_max"):
            continue
        rest = k[len("temperature_2m_max"):]
        m = _MEMBER_KEY.match(rest)
        model = m.group(2) if m else (known[0] if len(known) == 1 else "unknown")
        member = int(m.group(1)) if m and m.group(1) else 0
        members.append({"model": model, "member": member, "values": daily[k]})
    return {"dates": daily.get("time") or [], "members": members}


def members_for_date(ens, date):
    if date not in ens["dates"]:
        return []
    i = ens["dates"].index(date)
    out = []
    for m in ens["members"]:
        v = m["values"][i] if i < len(m["values"]) else None
        if v is not None and math.isfinite(v):
            out.append({"model": m["model"], "value": v})
    return out


def bucket_probs(values, width, parity, unit, floor_value=None):
    counts = {}
    n = 0
    for raw in values:
        v = raw
        if floor_value is not None and v < floor_value:
            v = floor_value
        start = bucket_start(round_half_up(v), width, parity)
        counts[start] = counts.get(start, 0) + 1
        n += 1
    buckets = [
        {"start": s, "label": bucket_label(s, width, unit), "count": c, "p": c / n}
        for s, c in counts.items()
    ]
    buckets.sort(key=lambda b: b["start"])
    return {"n": n, "buckets": buckets}


def top_buckets(probs, k=3):
    return sorted(probs["buckets"], key=lambda b: (-b["count"], -b["start"]))[:k]


def chance_at_or_above(values, floor_value=None):
    if not values:
        return []
    rounded = []
    for v in values:
        if floor_value is not None and v < floor_value:
            v = floor_value
        rounded.append(round_half_up(v))
    lo, hi = min(rounded), max(rounded)
    return [{"x": x, "p": sum(1 for r in rounded if r >= x) / len(rounded)} for x in range(lo, hi + 2)]


def consensus(model_values):
    vals = [v for v in model_values if v is not None and math.isfinite(v)]
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    return {"mean": js_round(mean * 10) / 10, "min": min(vals), "max": max(vals), "n": len(vals)}


_T_GROUP = re.compile(r"(?:^|\s)T([01])(\d{3})([01])(\d{3})(?=\s|$)")
_BODY_TEMP = re.compile(r"(?:^|\s)(M?\d{2})/(M?\d{2})?(?=\s|$)")


def metar_temp(raw):
    """Temperature of one METAR, as in calc.js metarTemp: the RMK T-group in tenths of a
    degree C, else the body group in whole degrees C. Returns {"c", "tenths"} or None."""
    if not raw:
        return None
    t = _T_GROUP.search(raw)
    if t:
        return {"c": (-1 if t.group(1) == "1" else 1) * int(t.group(2)) / 10, "tenths": True}
    body = re.split(r"\sRMK\s", raw)[0]
    g = _BODY_TEMP.search(body)
    if g:
        s = g.group(1)
        return {"c": (-1 if s[0] == "M" else 1) * int(s.replace("M", "")), "tenths": False}
    return None


def pct_label(p):
    """Same text as the site: <1%, >99%, otherwise a whole percent."""
    if 0 < p < 0.005:
        return "<1%"
    if 0.995 < p < 1:
        return ">99%"
    return str(js_round(p * 100)) + "%"
