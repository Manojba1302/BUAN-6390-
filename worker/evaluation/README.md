# Model evaluation

Vijay asked us to measure the models before choosing them. This tool runs labelled
documents through the **same code the app uses** and scores every answer.

## What it measures

| Step | What runs | Score |
|---|---|---|
| Stage 1 (real-time check) | Page one as an image to the small classifier model, plus the regex second opinion | % of documents typed correctly, time per document |
| Stage 2 (worker check) | `worker/pipeline.py` classify, every page | % typed correctly |
| Extraction | `worker/pipeline.py` extract, for the correct type | % of printed fields read correctly, time per document |

Each field ends as `correct`, `wrong`, `missed` or `invented` (a value the model returned that is
not on the page; it should always be 0). Values are compared after normalising, so `$3,250.00`
equals `3250` and `Sep 1, 2026` equals `2026-09-01`.

## The sample documents

`samples/` holds 33 **fictional** documents with an answer key in `samples/labels.json`:

- 3 invented people x 5 types (pay stub, W-2, bank statement, driver's license, SSN card)
- each as a **digital PDF** (has a text layer, the easy case) and a **phone photo** JPG
  (tilted, soft, no text layer, the hard case)
- 3 documents that are none of our types (utility bill, lease letter), where the right answer is `unknown`
- one pay stub has no pay frequency printed, to catch models that invent values

Every name and number is made up; SSNs start with 000, which is never issued.
To rebuild them: `python -m evaluation.make_samples`. Do **not** add real customer documents to this repo.

## Run it

```bash
bash scripts/homeflow.sh models                       # once: download gemma3:4b, llama3.1:8b, nomic-embed-text
bash scripts/homeflow.sh eval --limit 5               # quick check, a few minutes
bash scripts/homeflow.sh eval                         # all 33 documents (slow on CPU)
bash scripts/homeflow.sh eval --variant digital       # only digital PDFs
bash scripts/homeflow.sh eval --only w2 paystub       # only some types
bash scripts/homeflow.sh eval --stages 1              # only the real-time check
```

Windows: `.\scripts\homeflow.ps1 eval --limit 5` and so on.

The report is written to `worker/evaluation/results/<run name>.md` (and `.json`).

## Compare models

Pull another model, run again with it, then compare:

```bash
bash scripts/homeflow.sh models qwen2.5vl:3b
bash scripts/homeflow.sh eval --classifier-model qwen2.5vl:3b --vision-model qwen2.5vl:3b --name qwen-vision
bash scripts/homeflow.sh eval-compare                 # writes results/comparison.md
```

Vision-capable candidates for the classifier: `gemma3:4b` (default), `qwen2.5vl:3b`, `llama3.2-vision:11b`.
Text candidates for extraction: `llama3.1:8b` (default), `qwen2.5:7b`, `mistral:7b`.

## Limits to tell people about

- Synthetic documents are cleaner than real ones. Good scores here are a minimum bar, not proof.
  The next step is a set of real, redacted documents from Vijay, labelled the same way.
- On a laptop CPU each model call can take 10 to 60 seconds. Use `--limit` while trying things.
