"""Turn one evaluation run into a markdown report a person can read."""
from __future__ import annotations

STATES = ("correct", "wrong", "missed", "invented")
MAX_ROWS = 40


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _secs(ms) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f}s"


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _cell(block: dict, extraction: bool = False) -> str:
    if not block or not block.get("documents"):
        return "not run"
    if extraction:
        expected = sum(block["states"].get(s, 0) for s in ("correct", "wrong", "missed"))
        return f"{_pct(block['accuracy'])} ({block['states'].get('correct', 0)}/{expected} fields), avg {_secs(block['avg_ms'])}"
    return f"{_pct(block['accuracy'])} ({block['correct']}/{block['documents']} docs), avg {_secs(block['avg_ms'])}"


def headline(summary: dict) -> list[str]:
    variants = list(summary["by_variant"])
    header = ["Step", "All documents"] + [f"{v.title()} only" for v in variants]
    rows = []
    for key, title in (("stage1", "Stage 1: real-time type check"),
                       ("stage2", "Stage 2: worker type check"), ("extraction", "Field extraction")):
        cells = [_cell(summary[key], key == "extraction")]
        cells += [_cell(summary["by_variant"][v][key], key == "extraction") for v in variants]
        rows.append([title] + cells)
    return ["## Summary", ""] + _table(header, rows)


def confusion(summary: dict, key: str, title: str) -> list[str]:
    matrix = summary[key]["confusion"]
    if not matrix:
        return []
    predicted = sorted({p for row in matrix.values() for p in row})
    rows = [[actual] + [matrix[actual].get(p, 0) for p in predicted] for actual in sorted(matrix)]
    return [f"### {title}", "", "Rows are the real type, columns are what the model said.", ""] + \
        _table(["Real type"] + predicted, rows)


def per_type(summary: dict) -> list[str]:
    rows = [[t] + [v.get(s, 0) for s in STATES] + [_pct(v["accuracy"])]
            for t, v in sorted(summary["extraction"]["per_type"].items())]
    return ["## Field accuracy by document type", ""] + _table(["Type", *STATES, "Accuracy"], rows) if rows else []


def weak_fields(summary: dict) -> list[str]:
    weak = [(k, v) for k, v in summary["extraction"]["per_field"].items()
            if v.get("wrong") or v.get("missed") or v.get("invented")]
    weak.sort(key=lambda kv: (kv[1]["accuracy"] if kv[1]["accuracy"] is not None else 101))
    rows = [[k] + [v.get(s, 0) for s in STATES] + [_pct(v["accuracy"])] for k, v in weak]
    if not rows:
        return ["## Weakest fields", "", "Every field was read correctly.", ""]
    return ["## Weakest fields", ""] + _table(["Field", *STATES, "Accuracy"], rows)


def field_mistakes(items: list[dict]) -> list[str]:
    rows = [[i["file"], name, r["expected"], r["got"], r["state"]]
            for i in items for name, r in (i.get("extraction") or {}).get("fields", {}).items()
            if r["state"] in STATES[1:]]
    if not rows:
        return []
    note = [f"Showing {MAX_ROWS} of {len(rows)}.", ""] if len(rows) > MAX_ROWS else []
    return ["## Field mistakes", ""] + note + _table(["File", "Field", "Expected", "Model said", "Result"], rows[:MAX_ROWS])


def type_mistakes(items: list[dict]) -> list[str]:
    def said(item, key):
        return (item.get(key) or {}).get("detected", "not run")
    rows = [[i["file"], i["type"], said(i, "stage1"), said(i, "stage2")] for i in items
            if any(k in i and i[k]["detected"] != i["type"] for k in ("stage1", "stage2"))]
    if not rows:
        return []
    return ["## Classification mistakes", ""] + _table(["File", "Real type", "Stage 1 said", "Stage 2 said"], rows)


def errors(items: list[dict]) -> list[str]:
    rows = [[i["file"], key, i[key]["error"]] for i in items
            for key in ("stage1", "read", "stage2", "extraction") if (i.get(key) or {}).get("error")]
    return ["## Errors", ""] + _table(["File", "Step", "Error"], rows) if rows else []


def markdown(run: dict) -> str:
    m, s = run["models"], run["summary"]
    lines = [f"# Model evaluation: {run['name']}", "",
             f"Run {run['started']}, {len(run['items'])} documents, {run['minutes']} minutes.", "",
             f"Models: classifier `{m['classifier']}`, vision `{m['vision']}`, extractor `{m['extractor']}`.", ""]
    lines += headline(s) + ["## Classification detail", ""]
    lines += confusion(s, "stage1", "Stage 1") + confusion(s, "stage2", "Stage 2")
    lines += per_type(s) + weak_fields(s) + type_mistakes(run["items"])
    lines += field_mistakes(run["items"]) + errors(run["items"])
    lines += ["## How to read this", "",
              "- Accuracy for fields counts only fields that are printed on the document.",
              "- `invented` means the model returned a value that is not on the page. It should be 0.",
              "- All sample documents are fictional (see evaluation/sample_data.py).", ""]
    return "\n".join(lines)
