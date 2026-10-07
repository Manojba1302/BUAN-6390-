"""Put several evaluation runs side by side, to choose between models.

    python -m evaluation.compare                     # every run in evaluation/results
    python -m evaluation.compare results/a.json results/b.json
Writes evaluation/results/comparison.md and prints it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluation.report import _pct, _secs, _table

RESULTS = Path(__file__).resolve().parent / "results"


def row(run: dict) -> list:
    s, m = run["summary"], run["models"]
    states = s["extraction"]["states"]
    return [run["name"], m["classifier"], m["vision"], m["extractor"], len(run["items"]),
            _pct(s["stage1"]["accuracy"]), _secs(s["stage1"]["avg_ms"]),
            _pct(s["stage2"]["accuracy"]), _pct(s["extraction"]["accuracy"]),
            states.get("invented", 0), _secs(s["extraction"]["avg_ms"])]


def comparison(runs: list[dict]) -> str:
    header = ["Run", "Classifier", "Vision", "Extractor", "Docs", "Stage 1 acc", "Stage 1 time",
              "Stage 2 acc", "Field acc", "Invented", "Extract time"]
    lines = ["# Model comparison", "",
             "Higher accuracy is better. Invented should be 0. Times are averages per document.", ""]
    return "\n".join(lines + _table(header, [row(r) for r in runs]))


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(RESULTS.glob("*.json"))
    if not paths:
        print("No results yet. Run: python -m evaluation.run")
        return 1
    text = comparison([json.loads(p.read_text(encoding="utf-8")) for p in paths])
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "comparison.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
