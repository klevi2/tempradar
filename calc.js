// TempRadar calculation core. Pure functions, no network access.
// Runs in the browser (window.TRCalc) and in Node (module.exports) for tests.
// scripts/tempradar_calc.py is a line-for-line port; tests/parity.* keep the two identical.
(function (root) {
  "use strict";

  // Round to the nearest whole degree, exact halves upward (toward +infinity).
  // Same rule as the Polymarket resolution text: 64.5 -> 65, -8.5 -> -8.
  // The 1e6 snap removes float noise such as 64.49999999997 from unit conversion.
  function roundHalfUp(x) {
    return Math.floor(Math.round(x * 1e6) / 1e6 + 0.5);
  }

  function cToF(c) {
    return c * 9 / 5 + 32;
  }

  function mod(a, n) {
    return ((a % n) + n) % n;
  }

  // First degree of the bucket that holds the whole-degree value v.
  // width 1: every degree is its own bucket (Celsius markets).
  // width 2, parity "even": 80-81, 82-83 (Polymarket Fahrenheit markets).
  // width 2, parity "odd":  79-80, 81-82 (some Kalshi days).
  function bucketStart(v, width, parity) {
    if (width === 1) return v;
    var offset = parity === "odd" ? 1 : 0;
    return v - mod(v - offset, width);
  }

  function fmtDeg(v) {
    return (v < 0 ? "−" : "") + Math.abs(v);
  }

  function bucketLabel(start, width, unit) {
    if (width === 1) return fmtDeg(start) + "°" + unit;
    return fmtDeg(start) + "–" + fmtDeg(start + width - 1) + "°" + unit;
  }

  // Parse an Open-Meteo ensemble response (daily=temperature_2m_max, several models).
  // Keys look like temperature_2m_max_<model> (control) and
  // temperature_2m_max_member07_<model>. Returns members grouped by model key.
  function parseEnsemble(json, ensembleModels) {
    var daily = json.daily || {};
    var known = ensembleModels.map(function (m) { return m.key; });
    var members = [];
    Object.keys(daily).sort().forEach(function (k) {
      if (k.indexOf("temperature_2m_max") !== 0) return;
      var rest = k.slice("temperature_2m_max".length);
      var m = /^(?:_member(\d+))?_(.+)$/.exec(rest);
      var model = m ? m[2] : (known.length === 1 ? known[0] : "unknown");
      members.push({ model: model, member: m && m[1] ? parseInt(m[1], 10) : 0, values: daily[k] });
    });
    return { dates: daily.time || [], members: members };
  }

  // Member daily maxima for one date. Missing values are dropped.
  function membersForDate(ens, date) {
    var i = ens.dates.indexOf(date);
    if (i < 0) return [];
    var out = [];
    ens.members.forEach(function (m) {
      var v = m.values[i];
      if (v !== null && v !== undefined && isFinite(v)) out.push({ model: m.model, value: v });
    });
    return out;
  }

  // Bucket probabilities from member values: every member counts once.
  // floorValue (optional): the day's observed maximum so far; a member below it is
  // raised to it, since the final daily high cannot be lower than what was measured.
  function bucketProbs(values, width, parity, unit, floorValue) {
    var counts = {};
    var n = 0;
    values.forEach(function (raw) {
      var v = raw;
      if (floorValue !== null && floorValue !== undefined && v < floorValue) v = floorValue;
      var start = bucketStart(roundHalfUp(v), width, parity);
      counts[start] = (counts[start] || 0) + 1;
      n += 1;
    });
    var buckets = Object.keys(counts).map(function (k) {
      var start = parseInt(k, 10);
      return { start: start, label: bucketLabel(start, width, unit), count: counts[k], p: counts[k] / n };
    });
    buckets.sort(function (a, b) { return a.start - b.start; });
    return { n: n, buckets: buckets };
  }

  // The three most likely buckets; ties go to the warmer bucket so the order is stable.
  function topBuckets(probs, k) {
    return probs.buckets.slice().sort(function (a, b) {
      return b.count - a.count || b.start - a.start;
    }).slice(0, k || 3);
  }

  // P(whole-degree high >= x) for every x across the member range.
  function chanceAtOrAbove(values, floorValue) {
    if (!values.length) return [];
    var rounded = values.map(function (v) {
      if (floorValue !== null && floorValue !== undefined && v < floorValue) v = floorValue;
      return roundHalfUp(v);
    });
    var lo = Math.min.apply(null, rounded), hi = Math.max.apply(null, rounded);
    var out = [];
    for (var x = lo; x <= hi + 1; x++) {
      var c = 0;
      for (var j = 0; j < rounded.length; j++) if (rounded[j] >= x) c++;
      out.push({ x: x, p: c / rounded.length });
    }
    return out;
  }

  // Deterministic consensus: plain mean of the models that returned a value.
  function consensus(modelValues) {
    var vals = modelValues.filter(function (v) { return v !== null && v !== undefined && isFinite(v); });
    if (!vals.length) return null;
    var sum = 0;
    vals.forEach(function (v) { sum += v; });
    var mean = sum / vals.length;
    return {
      mean: Math.round(mean * 10) / 10,
      min: Math.min.apply(null, vals),
      max: Math.max.apply(null, vals),
      n: vals.length
    };
  }

  // ---- Time helpers -------------------------------------------------------

  // UTC offset (minutes, east positive) of time zone tz at instant ms.
  function tzOffsetMinutes(tz, ms) {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    }).formatToParts(new Date(ms));
    var p = {};
    parts.forEach(function (x) { p[x.type] = x.value; });
    var asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
    return Math.round((asUTC - Math.floor(ms / 1000) * 1000) / 60000);
  }

  // Local calendar date (YYYY-MM-DD) in tz, shifted by addDays.
  function localDate(tz, addDays, nowMs) {
    var ms = (nowMs === undefined ? Date.now() : nowMs);
    var off = tzOffsetMinutes(tz, ms);
    var d = new Date(ms + off * 60000);
    d.setUTCDate(d.getUTCDate() + (addDays || 0));
    return d.toISOString().slice(0, 10);
  }

  // UTC instant of local midnight on date (YYYY-MM-DD) in tz.
  // standardTime=true uses the zone's standard (winter) offset all year, which is how
  // the NWS climate day is defined: during daylight saving it runs 1:00 a.m. to 12:59 a.m.
  function localMidnightUTC(date, tz, standardTime) {
    var y = +date.slice(0, 4), m = +date.slice(5, 7), d = +date.slice(8, 10);
    var guess = Date.UTC(y, m - 1, d);
    if (standardTime) {
      var jan = tzOffsetMinutes(tz, Date.UTC(y, 0, 1)), jul = tzOffsetMinutes(tz, Date.UTC(y, 6, 1));
      return guess - Math.min(jan, jul) * 60000;
    }
    var t = guess - tzOffsetMinutes(tz, guess) * 60000;
    t = guess - tzOffsetMinutes(tz, t) * 60000;
    return t;
  }

  function isDaylightTime(tz, ms) {
    var y = new Date(ms).getUTCFullYear();
    var std = Math.min(tzOffsetMinutes(tz, Date.UTC(y, 0, 1)), tzOffsetMinutes(tz, Date.UTC(y, 6, 1)));
    return tzOffsetMinutes(tz, ms) > std;
  }

  // ---- METAR / NWS observations ---------------------------------------------

  // Temperature from one METAR text, following the Polymarket wording:
  // the RMK T-group in tenths of a degree C, else the body group in whole degrees C.
  function metarTemp(raw) {
    if (!raw) return null;
    var t = /(?:^|\s)T([01])(\d{3})([01])(\d{3})(?=\s|$)/.exec(raw);
    if (t) return { c: (t[1] === "1" ? -1 : 1) * parseInt(t[2], 10) / 10, tenths: true };
    var body = raw.split(/\sRMK\s/)[0];
    var g = /(?:^|\s)(M?\d{2})\/(M?\d{2})?(?=\s|$)/.exec(body);
    if (g) {
      var s = g[1];
      return { c: (s[0] === "M" ? -1 : 1) * parseInt(s.replace("M", ""), 10), tenths: false };
    }
    return null;
  }

  // Six-hour maximum group 1snTTT from the remarks (tenths of a degree C).
  function metarSixHourMax(raw) {
    if (!raw) return null;
    var parts = raw.split(/\sRMK\s/);
    if (parts.length < 2) return null;
    var g = /(?:^|\s)1([01])(\d{3})(?=\s|$)/.exec(parts[1]);
    return g ? (g[1] === "1" ? -1 : 1) * parseInt(g[2], 10) / 10 : null;
  }

  // Summarise api.weather.gov observations for one station-day window [startMs, endMs).
  // Returns the Polymarket-rule maximum (routine METARs only) plus the other readings.
  //
  // api.weather.gov drops the METAR/SPECI prefix from rawMessage, so special reports
  // cannot be recognised from the text. Routine reports of an automated station go out
  // at the same minute every hour (KLGA :51, KMIA :53), so the most common minute is
  // taken as the routine one and reports at other minutes are kept apart as "other".
  // When no minute covers at least half of the reports, every report counts as routine.
  function summarizeNwsObservations(features, startMs, endMs) {
    var out = { metarMax: null, otherMax: null, fiveMinMax: null, sixHourMax: null, latest: null, count: 0, routineMinute: null };
    var reports = [];
    (features || []).forEach(function (f) {
      var p = f.properties || {};
      var ts = Date.parse(p.timestamp);
      if (!(ts >= startMs && ts < endMs)) return;
      out.count++;
      var raw = (p.rawMessage || "").trim();
      var tv = p.temperature && p.temperature.value;
      if (raw) reports.push({ ts: ts, raw: raw });
      else if (tv !== null && tv !== undefined) {
        if (!out.fiveMinMax || tv > out.fiveMinMax.c) out.fiveMinMax = { c: tv, time: ts };
      }
      if (tv !== null && tv !== undefined && (!out.latest || ts > out.latest.time)) out.latest = { c: tv, time: ts };
    });

    var byMinute = {};
    reports.forEach(function (r) { var m = new Date(r.ts).getUTCMinutes(); byMinute[m] = (byMinute[m] || 0) + 1; });
    var best = null;
    Object.keys(byMinute).forEach(function (m) { if (best === null || byMinute[m] > byMinute[best]) best = m; });
    if (best !== null && byMinute[best] * 2 >= reports.length) out.routineMinute = +best;

    reports.forEach(function (r) {
      var routine = !/^SPECI\b/.test(r.raw) && (out.routineMinute === null || new Date(r.ts).getUTCMinutes() === out.routineMinute);
      var t = metarTemp(r.raw);
      if (t) {
        var key = routine ? "metarMax" : "otherMax";
        if (!out[key] || t.c > out[key].c) out[key] = { c: t.c, tenths: t.tenths, time: r.ts, raw: r.raw };
      }
      var six = metarSixHourMax(r.raw);
      // Only use a six-hour group whose whole period lies inside the day window.
      if (six !== null && r.ts - 6 * 3600000 >= startMs - 60000 && (!out.sixHourMax || six > out.sixHourMax.c)) {
        out.sixHourMax = { c: six, time: r.ts };
      }
    });
    return out;
  }

  var api = {
    roundHalfUp: roundHalfUp, cToF: cToF, bucketStart: bucketStart, bucketLabel: bucketLabel, fmtDeg: fmtDeg,
    parseEnsemble: parseEnsemble, membersForDate: membersForDate, bucketProbs: bucketProbs, topBuckets: topBuckets,
    chanceAtOrAbove: chanceAtOrAbove, consensus: consensus, tzOffsetMinutes: tzOffsetMinutes, localDate: localDate,
    localMidnightUTC: localMidnightUTC, isDaylightTime: isDaylightTime, metarTemp: metarTemp,
    metarSixHourMax: metarSixHourMax, summarizeNwsObservations: summarizeNwsObservations
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TRCalc = api;
})(this);
