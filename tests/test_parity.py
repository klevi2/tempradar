"""Parity test: calc.js and scripts/tempradar_calc.py must give identical results.

Runs tests/parity_reference.js with Node, computes the same cases in Python and
compares the two outputs value by value. Exit code 1 on any difference.
Usage: python tests/test_parity.py   (needs node on PATH)
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import tempradar_calc as C  # noqa: E402


def python_results():
    src = (ROOT / "stations.js").read_text(encoding="utf-8")
    cfg = json.loads(src.split("/*JSON-BEGIN*/")[1].split("/*JSON-END*/")[0])
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    out = {"rounding": [], "buckets": [], "consensus": [], "metar": [], "fixtures": []}
    for raw in cases["metar"]:
        out["metar"].append(C.metar_temp(raw))
    for x in cases["rounding"]:
        out["rounding"].append({"x": x, "r": C.round_half_up(x), "f": C.round_half_up(C.c_to_f(x))})
    for v, w, par in cases["bucketStart"]:
        start = C.bucket_start(v, w, par)
        out["buckets"].append({"v": v, "w": w, "par": par, "start": start, "label": C.bucket_label(start, w, "F" if w == 2 else "C")})
    for vals in cases["consensus"]:
        out["consensus"].append(C.consensus(vals))
    for fx in cases["fixtures"]:
        data = json.loads((HERE / "fixtures" / fx["file"]).read_text(encoding="utf-8"))
        ens = C.parse_ensemble(data, cfg["ensembleModels"])
        for date in ens["dates"]:
            values = [m["value"] for m in C.members_for_date(ens, date)]
            for par in (["even", "odd"] if fx["unit"] == "F" else ["even"]):
                for floor in (None, fx["floor"]):
                    probs = C.bucket_probs(values, cfg["bucketWidth"][fx["unit"]], par, fx["unit"], floor)
                    out["fixtures"].append({
                        "file": fx["file"], "date": date, "par": par, "floor": floor, "n": probs["n"],
                        "buckets": probs["buckets"], "top": C.top_buckets(probs, 3),
                        "atLeast": C.chance_at_or_above(values, floor),
                    })
    return out


def diff(a, b, where="$", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{where}.{k}: missing on one side")
            else:
                diff(a[k], b[k], f"{where}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{where}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{where}[{i}]", out)
    elif isinstance(a, bool) or isinstance(b, bool) or a != b:
        if not (a == b and type(a) is type(b)):
            # JSON has one number type: 65 and 65.0 are the same value.
            if not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and a == b):
                out.append(f"{where}: js={a!r} py={b!r}")
    return out


def main():
    js = json.loads(subprocess.run(["node", str(HERE / "parity_reference.js")], check=True,
                                   capture_output=True, text=True, encoding="utf-8").stdout)
    py = json.loads(json.dumps(python_results()))
    problems = diff(js, py)
    n_cases = sum(len(v) for v in js.values())
    if problems:
        print(f"PARITY FAILED: {len(problems)} differences in {n_cases} cases")
        for p in problems[:40]:
            print("  " + p)
        sys.exit(1)
    print(f"Parity OK: {n_cases} cases identical in JavaScript and Python.")


if __name__ == "__main__":
    main()
