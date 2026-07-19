# autobench report — custom:ollama/gemma4:e4b

**Run:** `vision_vjudge2_015546.json`  
**Judge:** `nvidia/meta/llama-3.3-70b-instruct` (NVIDIA NIM, free 40 RPM)  
**Average score:** `0.38` / 1.00

## Per-task

| Task | Score | Latency | Judge reason |
|---|---|---|---|
| vision_ocr | 0.50 | 2.5s | 0.5 |
| vision_progressive | 0.00 | 2.4s | 0.0 |
| vision_ocr | 0.00 | 0.4s | The model response incorrectly describes the image, as the red square is actually located in the top-left corner, not th |
| vision_progressive | 1.00 | 0.5s | The model response correctly describes the image, with a score of 1.0. |

## Lifecycle

- Model pulled, benchmarked on Ollama, then deleted.
- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).
