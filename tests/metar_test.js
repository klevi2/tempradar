// Tests for the METAR / observation helpers in calc.js (JavaScript only; the Python
// port covers forecasts, not observations). Run: node tests/metar_test.js
const assert = require("assert");
const C = require("../calc.js");

let n = 0;
function test(name, fn) { fn(); n++; console.log("ok  " + name); }
const t = s => Date.parse(s);

test("parseIemCsv reads rows and skips the header", () => {
  const rows = C.parseIemCsv("station,valid,metar\nLGA,2026-11-19 12:51,KLGA 191251Z 29003KT 10SM FEW250 11/03 A3046 RMK AO2 SLP313 T01060028 $\n\nEGLC,2026-11-19 13:20,EGLC 191320Z AUTO 22008KT 9999 NCD 12/07 Q1003\n");
  assert.strictEqual(rows.length, 2);
  assert.deepStrictEqual(rows[0], { station: "LGA", ts: t("2026-11-19T12:51:00Z"), raw: "KLGA 191251Z 29003KT 10SM FEW250 11/03 A3046 RMK AO2 SLP313 T01060028 $" });
  assert.strictEqual(rows[1].station, "EGLC");
});

test("parseIemCsv ignores error text", () => {
  assert.deepStrictEqual(C.parseIemCsv("Too many requests from your IP address, slow down."), []);
});

test("iemStationId drops the K of US stations only", () => {
  assert.strictEqual(C.iemStationId("KLGA"), "LGA");
  assert.strictEqual(C.iemStationId("KNYC"), "NYC");
  assert.strictEqual(C.iemStationId("EGLC"), "EGLC");
  assert.strictEqual(C.iemStationId("CYYZ"), "CYYZ");
});

function hourly(station, minute, hours, tempTenths) {
  const out = [];
  for (let h = 0; h < hours; h++) {
    const hh = String(h).padStart(2, "0"), mm = String(minute).padStart(2, "0");
    const tc = tempTenths[h % tempTenths.length];
    out.push({ ts: t(`2026-11-19T${hh}:${mm}:00Z`), raw: `${station} 19${hh}${mm}Z 00000KT 10SM CLR ${String(Math.round(tc / 10)).padStart(2, "0")}/01 A3000 RMK AO2 T0${String(tc).padStart(3, "0")}0010` });
  }
  return out;
}

test("routineMinutes finds one routine minute (KLGA :51) and ignores specials", () => {
  const r = hourly("KLGA", 51, 8, [100]).concat([{ ts: t("2026-11-19T03:12:00Z"), raw: "KLGA 190312Z 18/01" }, { ts: t("2026-11-19T05:33:00Z"), raw: "KLGA 190533Z 18/01" }]);
  assert.deepStrictEqual(C.routineMinutes(r), [51]);
});

test("routineMinutes finds two routine minutes (EGLC :20 and :50)", () => {
  const r = hourly("EGLC", 20, 6, [100]).concat(hourly("EGLC", 50, 6, [100]));
  assert.deepStrictEqual(C.routineMinutes(r), [20, 50]);
});

test("routineMinutes gives up with too few reports", () => {
  assert.strictEqual(C.routineMinutes(hourly("KLGA", 51, 1, [100])), null);
});

test("summarizeMetarReports keeps a special report out of the Polymarket maximum", () => {
  const routine = hourly("KLGA", 51, 6, [100, 120, 178, 150]);
  const special = { ts: t("2026-11-19T03:12:00Z"), raw: "KLGA 190312Z 26010KT 10SM FEW250 19/02 A3040 RMK AO2 T01940017" };
  const s = C.summarizeMetarReports(routine.concat([special]), t("2026-11-19T00:00:00Z"), t("2026-11-20T00:00:00Z"));
  assert.strictEqual(s.metarMax.c, 17.8);
  assert.strictEqual(C.roundHalfUp(C.cToF(s.metarMax.c)), 64);
  assert.strictEqual(s.otherMax.c, 19.4);
  assert.strictEqual(s.newest, t("2026-11-19T05:51:00Z"));
  assert.strictEqual(s.count, 7);
});

test("summarizeMetarReports respects the day window", () => {
  const r = hourly("KLGA", 51, 6, [300]);
  const s = C.summarizeMetarReports(r, t("2026-11-19T03:00:00Z"), t("2026-11-20T00:00:00Z"));
  assert.strictEqual(s.count, 3);
  assert.strictEqual(s.metarMax.time, t("2026-11-19T03:51:00Z"));
});

test("six-hour max group counts only when its period is inside the window", () => {
  const inside = { ts: t("2026-11-19T11:51:00Z"), raw: "KLGA 191151Z 10/02 A3044 RMK AO2 T01000017 10133 20089" };
  const partly = { ts: t("2026-11-19T05:51:00Z"), raw: "KLGA 190551Z 11/03 A3044 RMK AO2 T01110028 10150 20111" };
  const s = C.summarizeMetarReports([inside, partly], t("2026-11-19T05:00:00Z"), t("2026-11-20T05:00:00Z"));
  assert.strictEqual(s.sixHourMax.c, 13.3);
});

test("nwsToReports splits METARs from five-minute readings", () => {
  const x = C.nwsToReports([
    { properties: { timestamp: "2026-11-19T12:51:00+00:00", rawMessage: "KLGA 191251Z 11/03 RMK T01060028", temperature: { value: 10.6 } } },
    { properties: { timestamp: "2026-11-19T12:55:00+00:00", rawMessage: "", temperature: { value: 11 } } }
  ]);
  assert.strictEqual(x.reports.length, 1);
  assert.deepStrictEqual(x.fiveMin, [{ ts: t("2026-11-19T12:55:00Z"), c: 11 }]);
});

test("iemFiveMinute reads the tenths T-group of HFMETAR rows", () => {
  const rows = C.parseIemCsv("MIA,2026-11-19 13:05,KMIA 191305Z AUTO 09008KT 10SM SCT024 25/22 A3000 RMK T02500220 MADISHF");
  assert.deepStrictEqual(C.iemFiveMinute(rows), [{ ts: t("2026-11-19T13:05:00Z"), c: 25, tenths: true }]);
  const s = C.summarizeMetarReports([], t("2026-11-19T00:00:00Z"), t("2026-11-20T00:00:00Z"), C.iemFiveMinute(rows));
  assert.strictEqual(s.fiveMinMax.tenths, true);
});

console.log(n + " METAR tests passed.");
