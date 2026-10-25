# Upload performance diagnosis - October 21, 2026

Read-only comparison against the same stored license photo. No document records or corrections were modified. Baseline request uses the previous nested value/page/quote prompt; current request uses compact flat fields and a JSON schema. Both use gemma3:4b, the same image and OCR, temperature zero, and unload after completion. This is a request comparison, not a complete historical environment replay. Runs were sequential, one trial per configuration; OS cache and background workloads can differ.

| Request | Total seconds | Model load | Input processing | Output generation | Output tokens | Fields |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Previous | 145.74 | 15.85 | 78.32 | 50.77 | 466 | 11 |
| Current | 86.78 | 8.19 | 63.40 | 14.92 | 147 | 11 |

Both matched normalized birth/issue/expiry dates, state and ZIP, but failed exact license-number and surname checks. Previous request included complete name and correct street spelling; current request failed those checks too. Thus compact generation was faster in this trial but did not preserve accuracy. Field counts are not an accuracy metric. OCR contained the exact license number, surname and street spelling, so useful evidence was available before model generation.

Resource snapshots: Intel Core Ultra 7 255U, CPU load 99 percent during generation, vision model about 2.69 GiB RAM and zero VRAM. Windows free RAM was about 1.94 GiB before loading and 1.21 GiB during the run. These observations do not establish historical memory conditions or prove paging.

Code findings: pre-upload and worker classification already existed before the current changes. Current document calls explicitly unload models, trading memory use for repeated load time. Native-text fast paths reduce PDF classification calls. The local text extractor changed from 8B to 3B; photographed licenses still use gemma3:4b. Worker queue prefetch is one, but API preflight requests and chat can compete with the worker on the same inference server. Prior logs show a preflight timeout overlapping W-2 extraction.

Next: coordinate model requests across services; manage model lifetime around a document job; retain existing PDF recovery fixes; restore evidence-bearing photo extraction only after controlled accuracy checks; validate exact fields against OCR and flag disagreements for review; record repeated serial/concurrent benchmarks for all four documents. No production rollback, database reset, push, or model replacement was performed.
