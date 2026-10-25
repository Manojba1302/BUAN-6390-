# Chat refinement diagnostic — 2026-10-14

Configured and observed chat model: llama3.1:8b, Q4_K_M, context 4096. No automatic switch to Qwen/Mistral/smaller models. Ollama reported approximately 5.58 GB model residency and size_vram 0; embeddings approximately 376 MB and size_vram 0. Machine: Intel Core Ultra 7 255U, Intel integrated graphics, 15.43 GiB usable physical RAM. Available RAM measured 1.51 GiB before startup and 0.26 GiB during generation. These observations indicate severe memory pressure and CPU-only model execution; they do not separately measure paging or prove its exact share of latency.

Docker Desktop was stopped. Started existing services without resetting volumes. Startup briefly encountered a port bind conflict; existing containers were subsequently running and backend requests returned 200.

Refinement: request-local short source IDs replace long UUIDs only inside LLM evidence; responses are mapped back to original file IDs before citation and quote validation. This reduces identifier token overhead without changing document scope or switching the model. Added regression coverage for round-trip restoration and rejection of unknown source IDs. Thirty targeted tests ran: 26 passed, four isolated-database tests skipped. Git whitespace checks passed.

Live broad question: Explain the key amounts and statement period in my bank statement. Result: timeout/unavailable at 121.82 seconds. Short IDs have not resolved general generation speed. Fast saved-field routes remain separate optimizations. Changes are local and not pushed. A useful next benchmark requires lower memory contention or an explicitly selected alternate inference setup; no unrelated applications were closed or system settings changed.
