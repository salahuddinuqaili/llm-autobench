# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_claudefree2_023950.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (70B text judge) + Claude vision describer (stage 1)  
**Average score:** `0.45` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.00 | 11.3s | 0.0 |
| vision_progressive | 0.00 | 2.5s | 0.0 |
| vision_ocr | 1.00 | 4.5s | 1.0 |
| vision_progressive | 0.80 | 1.3s | 0.8 |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
