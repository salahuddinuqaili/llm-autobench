# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_smoke_013344.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (NVIDIA NIM, free 40 RPM)  
**Average score:** `0.50` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.00 | 2.5s | 0.0 |
| vision_ocr | 1.00 | 0.3s | 1.0 |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
