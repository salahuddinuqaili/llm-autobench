# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_2stage_020300.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (70B text judge) + Claude vision describer (stage 1)  
**Average score:** `0.50` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.00 | 11.1s | 0.0 |
| vision_progressive | 0.00 | 1.8s | 0.0 |
| vision_ocr | 1.00 | 4.1s | 1.0 |
| vision_progressive | 1.00 | 0.7s | 1.0 |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
