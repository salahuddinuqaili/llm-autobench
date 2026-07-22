_All-time aggregate across **98 runs** (2026-07-16 → 2026-07-22), **13 models**, **11 tasks**, 970 model×task results. Judge: free NVIDIA NIM Llama-3.3-70B. Regenerate: `python scripts/aggregate_results.py --inject README.md`._

### 🏆 Leaderboard (all-time mean score)

| Rank | Model | Avg | Results (n) | Runs | Tasks | Avg latency | Err |
|---:|---|---:|---:|---:|---:|---:|---:|
| 🥇 | `qwen2.5-coder:14b` | **0.92** | 9 | 1 | 9 | 3.7s | — |
| 🥈 | `llama3.2:3b` | **0.82** | 9 | 1 | 9 | 2.0s | — |
| 🥉 | `minicpm-v:latest` ·👁 | **0.82** | 17 | 9 | 2 | 1.8s | — |
| 4 | `gemma4:e4b` | **0.77** | 557 | 70 | 11 | 5.2s | 3 |
| 5 | `codellama:13b` | **0.73** | 7 | 1 | 7 | 12.2s | — |
| 6 | `claude-sonnet-4-5` | **0.71** | 7 | 2 | 9 | 11.3s | — |
| 7 | `qwen3.5:9b` | **0.71** | 246 | 72 | 5 | 10.7s | — |
| 8 | `codeup:13b` | **0.69** | 9 | 1 | 9 | 4.9s | — |
| 9 | `qwen2.5:7b-instruct` | **0.67** | 3 | 1 | 9 | 2.1s | — |
| 10 | `cogito:14b` | **0.50** | 4 | 1 | 9 | 3.0s | — |
| 11 | `deepcoder:14b` | **0.38** | 13 | 2 | 9 | 10.5s | — |
| 12 | `everythinglm:13b` | **0.33** | 3 | 1 | 9 | 14.4s | — |
| 13 | `gemma3n:e4b` | **0.00** | 9 | 1 | 9 | 0.0s | 9 |

> ⚠️ **Read with the sample size.** Baselines (`gemma4:e4b`, `qwen3.5:9b`) have tens of runs; most discovered models have a single run (n≈7–9). A one-run average is a first impression, not a ranking. `👁` = vision-only coverage (different judging regime).

### 🎯 Task difficulty (mean score across all models)

| Task | Avg | Results (n) | Models | |
|---|---:|---:|---:|---|
| `sprint_narrative` | 0.96 | 66 | 7 | `██████████` |
| `instruction_following` | 0.93 | 69 | 9 | `█████████░` |
| `code_review` | 0.93 | 126 | 8 | `█████████░` |
| `logical_reasoning` | 0.88 | 133 | 11 | `█████████░` |
| `changelog_generation` | 0.81 | 67 | 7 | `████████░░` |
| `summarization` | 0.73 | 66 | 7 | `███████░░░` |
| `code_generation` | 0.71 | 127 | 8 | `███████░░░` |
| `structured_output` | 0.64 | 69 | 10 | `██████░░░░` |
| `vision_progressive` 👁 | 0.43 | 16 | 2 | `████░░░░░░` |
| `vision_ocr` 👁 | 0.42 | 18 | 2 | `████░░░░░░` |
| `arithmetic_reasoning` | 0.36 | 136 | 12 | `████░░░░░░` |

### 🧮 Model × task score matrix

| Task | `minicpm-v:latest` | `gemma4:e4b` | `claude-sonnet-4-5` | `qwen3.5:9b` | `deepcoder:14b` |
|---|---:|---:|---:|---:|---:|
| `sprint_narrative` | · | 0.97 | · | · | 1.00 |
| `instruction_following` | · | 1.00 | 0.00 | · | 0.00 |
| `code_review` | · | 0.88 | · | 0.99 | 1.00 |
| `logical_reasoning` | · | 1.00 | 1.00 | 0.76 | 0.75 |
| `changelog_generation` | · | 0.85 | · | · | 0.00 |
| `summarization` | · | 0.76 | · | · | 0.00 |
| `code_generation` | · | 0.81 | · | 0.62 | 0.00 |
| `structured_output` | · | 0.71 | 0.50 | · | 0.00 |
| `vision_progressive` | 0.86 | 0.00 | · | · | · |
| `vision_ocr` | 0.78 | 0.06 | · | · | · |
| `arithmetic_reasoning` | · | 0.16 | 1.00 | 0.49 | 0.75 |

_Showing the 5 repeat-tested models (≥2 runs); each cell is a mean of ≥2 samples. Single-run models are in the leaderboard above. `·` = task not attempted (model/task tag mismatch)._

### 🔍 Data quality (honest caveats)

- **Truncation inflates the hard tasks.** ~107 of 178 zero-scores are responses cut off at the token budget *before stating an answer* (estimated from response endings). Reasoning models (`qwen3.5:9b`) are hit hardest — `arithmetic_reasoning` and `structured_output` scores are partly a harness limit, not a capability signal. *(Tracked: no `done_reason` truncation guard is implemented yet.)*
- **Errors:** 34 results errored (mostly Ollama `HTTP 404` — a model tag that failed to pull). Errored rows are excluded from means.
- **Uneven coverage:** tag-gating means `qwen3.5:9b` attempts 5 tasks while `gemma4:e4b` attempts 11 — cross-model comparison is only fair within shared tasks (see the matrix).
- **Single judge, single sample:** one NVIDIA-70B judge pass, N=1 per (model, task). No confidence intervals or inter-rater agreement yet.

