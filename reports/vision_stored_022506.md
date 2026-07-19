# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_stored_022506.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (70B text judge) + Claude vision describer (stage 1)  
**Average score:** `0.38` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.00 | 13.1s | 0.0 |
| vision_progressive | 0.00 | 2.5s | 0.0 |
| vision_ocr | 0.50 | 4.7s | 0.5 |
| vision_progressive | 1.00 | 0.5s | 1.0 |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
