# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_claudefree_023712.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (70B text judge) + Claude vision describer (stage 1)  
**Average score:** `0.23` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.00 | 0.0s | 0.0 |
| vision_progressive | 0.00 | 0.0s | 0.0 |
| vision_ocr | 0.50 | 4.1s | 0.5 |
| vision_progressive | 0.40 | 1.2s | 0.4 |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
