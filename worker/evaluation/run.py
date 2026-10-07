"""Run the sample documents through the real models and score the answers.

Inside Docker (models must be pulled first):
    bash scripts/homeflow.sh eval                       # all 33 samples
    bash scripts/homeflow.sh eval --limit 5             # quick check
    bash scripts/homeflow.sh eval --variant digital --vision-model qwen2.5vl:3b

What is measured, per document:
  stage 1  the real-time check: page one as an image to the small classifier
           model, plus the regex second opinion (same rules as the API)
  stage 2  the worker's classification of every page (worker/pipeline.py)
  extract  the worker's field extraction for the correct type, scored field
           by field against samples/labels.json
Results go to evaluation/results/<name>.json and <name>.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import doc_types
import httpx
import ollama
import pages

from evaluation import report, scoring
from worker import pipeline
from worker.config import config

HERE = Path(__file__).resolve().parent
TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score HomeFlow's models on labelled documents.")
    p.add_argument("--samples", type=Path, default=HERE / "samples", help="folder with labels.json")
    p.add_argument("--out", type=Path, default=HERE / "results")
    p.add_argument("--name", help="name for this run's result files")
    p.add_argument("--limit", type=int, help="only the first N documents")
    p.add_argument("--only", nargs="*", help="document types to include, e.g. w2 paystub")
    p.add_argument("--variant", choices=["digital", "photo", "all"], default="all")
    p.add_argument("--stages", default="1,2,extract", help="comma list of 1, 2, extract")
    p.add_argument("--classifier-model", default=config.classifier_model)
    p.add_argument("--vision-model", default=config.vision_model)
    p.add_argument("--extractor-model", default=config.extractor_model)
    return p.parse_args(argv)


def load_labels(args: argparse.Namespace) -> list[dict]:
    labels = json.loads((args.samples / "labels.json").read_text(encoding="utf-8"))
    if args.only:
        labels = [l for l in labels if l["type"] in args.only]
    if args.variant != "all":
        labels = [l for l in labels if l["variant"] == args.variant]
    return labels[: args.limit] if args.limit else labels


def apply_models(args: argparse.Namespace) -> dict:
    """Point the worker code at the models under test, for this process only."""
    config.classifier_model = args.classifier_model
    config.vision_model = args.vision_model
    config.extractor_model = args.extractor_model
    return {"classifier": args.classifier_model, "vision": args.vision_model,
            "extractor": args.extractor_model}


def missing_models(models: dict) -> list[str]:
    """Names not pulled into Ollama yet. Raises if Ollama is not reachable."""
    tags = httpx.get(f"{ollama.BASE_URL}/api/tags", timeout=10.0).json().get("models", [])
    have = {m["name"] for m in tags} | {m["name"].removesuffix(":latest") for m in tags}
    return sorted({m for m in models.values() if m not in have})


def _timed(fn, *args) -> tuple[object, int, str | None]:
    started = time.perf_counter()
    try:
        result, error = fn(*args), None
    except Exception as exc:          # one bad document must not stop the run
        result, error = None, f"{type(exc).__name__}: {exc}"[:300]
    return result, int((time.perf_counter() - started) * 1000), error


def stage1(body: bytes, content_type: str, name: str) -> str:
    """The API's real-time check: page one as an image, plus the regex vote."""
    image = pages.first_page_image(body, content_type, name)
    text = pages.native_text(body)[:1] if pages.is_pdf(content_type, name) else []
    answer = ollama.generate_json(model=config.classifier_model, prompt=doc_types.classification_prompt(),
                                  images=[image], timeout=120.0)
    detected = str(answer.get("document_type", doc_types.UNKNOWN)).strip().lower()
    if detected not in doc_types.type_ids():
        detected = doc_types.UNKNOWN
    return doc_types.reconcile(detected, doc_types.regex_vote(text[0] if text else ""))


def _stage_entry(detected, ms: int, error: str | None) -> dict:
    return {"detected": detected, "ms": ms, **({"error": error} if error else {})}


def evaluate_one(label: dict, samples: Path, stages: set[str]) -> dict:
    name = label["file"]
    body, ctype = (samples / name).read_bytes(), TYPES.get(Path(name).suffix.lower(), "")
    item = {k: label[k] for k in ("file", "type", "variant", "person")}
    if "1" in stages:
        item["stage1"] = _stage_entry(*_timed(stage1, body, ctype, name))
    document, read_ms, read_error = _timed(pipeline.read, body, ctype, name)
    item["read"] = {"ms": read_ms, "methods": [p["method"] for p in (document or {}).get("pages", [])],
                    **({"error": read_error} if read_error else {})}
    if document is None:
        return item
    if "2" in stages:
        result, ms, error = _timed(pipeline.classify, document, label["type"])
        item["stage2"] = _stage_entry(result and result["detected"], ms, error)
    if "extract" in stages and label["type"] != doc_types.UNKNOWN:
        item["extraction"] = _extraction(document, label)
    return item


def _extraction(document: dict, label: dict) -> dict:
    got, ms, error = _timed(pipeline.extract, document, label["type"])
    if error:
        return {"ms": ms, "error": error, "fields": {}}
    return {"ms": ms, "fields": scoring.score_fields(label["fields"], got or {})}


def _progress(n: int, total: int, item: dict) -> None:
    parts = [f"[{n}/{total}] {item['file']:<34}"]
    for key in ("stage1", "stage2"):
        if key in item:
            ok = "ok" if item[key]["detected"] == item["type"] else f"got {item[key]['detected']}"
            parts.append(f"{key}={ok} ({item[key]['ms'] / 1000:.1f}s)")
    if "extraction" in item:
        states = [f["state"] for f in item["extraction"]["fields"].values()]
        parts.append(f"fields {states.count('correct')}/{len(states)}")
    print("  ".join(parts), flush=True)


def run_name(args: argparse.Namespace, models: dict) -> str:
    if args.name:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", args.name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{stamp}_{models['classifier']}_{models['extractor']}")


def save(args: argparse.Namespace, run: dict) -> Path:
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.out / run["name"]
    base.with_suffix(".json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(report.markdown(run), encoding="utf-8")
    return base.with_suffix(".md")


def evaluate(args: argparse.Namespace, models: dict) -> dict:
    labels, stages = load_labels(args), set(args.stages.split(","))
    started, items = datetime.now(), []
    for n, label in enumerate(labels, start=1):
        items.append(evaluate_one(label, args.samples, stages))
        _progress(n, len(labels), items[-1])
    return {"name": run_name(args, models), "started": started.isoformat(timespec="seconds"),
            "minutes": round((datetime.now() - started).total_seconds() / 60, 1),
            "models": models, "stages": sorted(stages), "items": items,
            "summary": scoring.summarise(items)}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    models = apply_models(args)
    try:
        missing = missing_models(models)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Cannot reach Ollama at {ollama.BASE_URL}: {exc}\nStart it first: bash scripts/homeflow.sh start")
        return 2
    if missing:
        print("These models are not downloaded yet:\n" + "\n".join(
            f"  docker compose --profile models exec ollama ollama pull {m}" for m in missing))
        return 2
    path = save(args, evaluate(args, models))
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
