# Upload baseline restoration — October 21, 2026

Baseline: pushed commit ce0e907 on integration/homeflow-main-2026-10-08.

Restored local EXTRACTOR_MODEL from llama3.2:3b to llama3.1:8b, matching the pushed setup. VISION_MODEL and CLASSIFIER_MODEL remain gemma3:4b. Worker recreated so the environment change is active. Unrelated agent, chat, template and interface work was preserved; this is a model-baseline restoration, not a complete source rollback. Native-text classification, queue heartbeat and retry fixes were retained.

Added an extraction completeness gate: a recognized W-2 must include employee_name, employer_name and box1_wages before the worker can report successful completion. Partial output raises a readable error through the existing worker failure path. Explicit zero wages remain valid. Existing completed records are not automatically relabelled or reprocessed.

Validation: 44 worker tests passed and backend code standards passed. Direct live extraction of the previously incomplete W-2 using the original stored PDF and restored 8B model timed out after 180.98 seconds. No customer extraction data or saved corrections were overwritten by that diagnostic. This proves restoring the previous model setting alone does not resolve current processing latency; resource pressure and generation/output workload still require investigation. No Git push performed.
