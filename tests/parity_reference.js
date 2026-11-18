// Prints the JavaScript (calc.js) results for the shared test cases as JSON.
// tests/test_parity.py computes the same cases in Python and requires identical output.
const fs = require("fs");
const path = require("path");
const C = require("../calc.js");

const src = fs.readFileSync(path.join(__dirname, "..", "stations.js"), "utf8");
const cfg = JSON.parse(src.split("/*JSON-BEGIN*/")[1].split("/*JSON-END*/")[0]);
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "cases.json"), "utf8"));

const out = { rounding: [], buckets: [], consensus: [], fixtures: [] };

cases.rounding.forEach(x => out.rounding.push({ x, r: C.roundHalfUp(x), f: C.roundHalfUp(C.cToF(x)) }));
cases.bucketStart.forEach(([v, w, par]) => out.buckets.push({ v, w, par, start: C.bucketStart(v, w, par), label: C.bucketLabel(C.bucketStart(v, w, par), w, w === 2 ? "F" : "C") }));
cases.consensus.forEach(vals => out.consensus.push(C.consensus(vals)));

cases.fixtures.forEach(fx => {
  const json = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", fx.file), "utf8"));
  const ens = C.parseEnsemble(json, cfg.ensembleModels);
  ens.dates.forEach(date => {
    const values = C.membersForDate(ens, date).map(m => m.value);
    (fx.unit === "F" ? ["even", "odd"] : ["even"]).forEach(par => {
      [null, fx.floor].forEach(floor => {
        const probs = C.bucketProbs(values, cfg.bucketWidth[fx.unit], par, fx.unit, floor);
        out.fixtures.push({
          file: fx.file, date, par, floor, n: probs.n, buckets: probs.buckets,
          top: C.topBuckets(probs, 3), atLeast: C.chanceAtOrAbove(values, floor)
        });
      });
    });
  });
});

process.stdout.write(JSON.stringify(out));
