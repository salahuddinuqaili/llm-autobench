_All-time aggregate across **1 runs** (2026-08-23 → 2026-08-23), **3 models**, **11 tasks**, 66 model×task×sample results (**N=3** draws per model×task). Judge: free NVIDIA NIM Llama-3.3-70B. Regenerate: `python scripts/aggregate_results.py --inject README.md`._

### 🏆 Leaderboard (all-time mean score)

| Rank | Model | Avg | 95% CI | Shared-task avg | Results (n) | Runs | Tasks | Avg latency | Err |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 🥇 | `qwen3.5:9b` | **0.90** | 0.81–0.99 | 0.90 | 25 | 1 | 9 | 8.2s | - |
| 🥈 | `gemma4:e4b` | **0.75** | 0.60–0.90 | 0.86 | 31 | 1 | 11 | 3.6s | - |
| 🥉 | `minicpm-v:latest` ·👁 | **0.40** | 0.18–0.62 | — | 6 | 1 | 2 | 1.6s | - |

> **Avg** is over every task a model attempted, so two models with different coverage are not comparable there. **Shared-task avg** is over the 9 task(s) every general model attempted (`arithmetic_reasoning`, `changelog_generation`, `code_generation`, `code_review`, `instruction_following`, `logical_reasoning`, `sprint_narrative`, `structured_output`, `summarization`) — that column is the like-for-like one. `—` = vision-only model, which attempts none of the shared text battery. `👁` = vision-only coverage (different judging regime).

### 🎯 Task difficulty (mean score across all models)

| Task | Avg | 95% CI | Results (n) | Models | |
|---|---:|---:|---:|---:|---|
| `arithmetic_reasoning` | 1.00 | exact | 6 | 2 | `██████████` |
| `instruction_following` | 1.00 | exact | 6 | 2 | `██████████` |
| `logical_reasoning` | 1.00 | exact | 6 | 2 | `██████████` |
| `sprint_narrative` | 0.96 | 0.94–0.98 | 6 | 2 | `██████████` |
| `code_review` | 0.95 | 0.87–1.00 | 6 | 2 | `██████████` |
| `changelog_generation` | 0.93 | 0.88–0.97 | 6 | 2 | `█████████░` |
| `summarization` | 0.91 | 0.86–0.95 | 6 | 2 | `█████████░` |
| `code_generation` | 0.80 | 0.37–1.00 | 4 | 2 | `████████░░` |
| `structured_output` | 0.33 | 0.00–0.88 | 6 | 2 | `███░░░░░░░` |
| `vision_progressive` 👁 | 0.28 | 0.00–0.61 | 5 | 2 | `███░░░░░░░` |
| `vision_ocr` 👁 | 0.20 | 0.00–0.54 | 5 | 2 | `██░░░░░░░░` |

### 🧮 Model × task score matrix

| Task | `qwen3.5:9b` | `gemma4:e4b` | `minicpm-v:latest` |
|---|---:|---:|---:|
| `arithmetic_reasoning` | 1.00 <sub>n=3</sub> | 1.00 <sub>n=3</sub> | · |
| `instruction_following` | 1.00 <sub>n=3</sub> | 1.00 <sub>n=3</sub> | · |
| `logical_reasoning` | 1.00 <sub>n=3</sub> | 1.00 <sub>n=3</sub> | · |
| `sprint_narrative` | 0.97 <sub>0.89–1.00, n=3</sub> | 0.95 <sub>n=3</sub> | · |
| `code_review` | 0.90 <sub>0.68–1.00, n=3</sub> | 1.00 <sub>n=3</sub> | · |
| `changelog_generation` | 0.95 <sub>0.83–1.00, n=3</sub> | 0.90 <sub>n=3</sub> | · |
| `summarization` | 0.87 <sub>0.77–0.97, n=3</sub> | 0.94 <sub>0.90–0.98, n=3</sub> | · |
| `code_generation` | 0.40 <sub>n=1</sub> | 0.93 <sub>0.86–1.00, n=3</sub> | · |
| `structured_output` | 0.67 <sub>0.00–1.00, n=3</sub> | 0.00 <sub>n=3</sub> | · |
| `vision_progressive` | · | 0.00 <sub>n=2</sub> | 0.47 <sub>0.18–0.75, n=3</sub> |
| `vision_ocr` | · | 0.00 <sub>n=2</sub> | 0.33 <sub>0.00–1.00, n=3</sub> |

_Showing the 3 model(s) with ≥2 scored results. `·` = task not attempted (tag mismatch — see Coverage below). Ranges are 95% t-intervals over that cell's draws, clamped to the `[0, 1]` score range; a cell whose draws all agreed shows no range._

### 🎲 Sampling spread (same model, same prompt, repeated draws)

| Model | Task | Draws | Scores | Mean | Spread |
|---|---|---:|---|---:|---:|
| `qwen3.5:9b` | `structured_output` | 3 | 0, 1, 1 | 0.67 | 1.00 |
| `minicpm-v:latest` | `vision_ocr` | 3 | 0.5, 0, 0.5 | 0.33 | 0.50 |
| `minicpm-v:latest` | `vision_progressive` | 3 | 0.4, 0.4, 0.6 | 0.47 | 0.20 |
| `qwen3.5:9b` | `code_review` | 3 | 1, 0.85, 0.85 | 0.90 | 0.15 |
| `qwen3.5:9b` | `changelog_generation` | 3 | 1, 0.95, 0.9 | 0.95 | 0.10 |
| `qwen3.5:9b` | `summarization` | 3 | 0.85, 0.92, 0.85 | 0.87 | 0.07 |
| `qwen3.5:9b` | `sprint_narrative` | 3 | 0.95, 1, 0.95 | 0.97 | 0.05 |
| `gemma4:e4b` | `code_generation` | 3 | 0.95, 0.95, 0.9 | 0.93 | 0.05 |
| `gemma4:e4b` | `summarization` | 3 | 0.95, 0.92, 0.95 | 0.94 | 0.03 |

_9 cell(s) returned different scores for the **same prompt at the same settings**. Each of those is a number a single-draw run would have published as fact._

### 📋 Coverage (what was skipped, and why)

| Model | Tasks attempted | Skipped | Why |
|---|---:|---:|---|
| `gemma4:e4b` | 11 | 0 | nothing skipped |
| `minicpm-v:latest` | 2 | 9 | `arithmetic_reasoning`, `changelog_generation`, `code_generation`, `code_review`, `instruction_following`, `logical_reasoning`, `sprint_narrative`, `structured_output`, `summarization` — tag mismatch |
| `qwen3.5:9b` | 9 | 2 | `vision_ocr`, `vision_progressive` — tag mismatch |

### 🗂 Era history (previous datasets, kept but not averaged in)

| Era | Dates | Runs on disk | In this aggregate | Why separated |
|---|---|---:|---|---|
| pre-credibility-fix | … → 2026-07-26 | 93 | no | substring scorer (false-positive 1.00), no truncation guard, two disagreeing judge paths |
| credibility fixes (`d61170e`) | 2026-07-27 → 2026-08-22 | 80 | no | answer extraction + truncation guard + single judge landed, but N=1 per (model, task) with no variance, and the tag gate skipped pairs silently so coverage gaps were invisible |
| multi-sample + disclosed coverage | 2026-08-23 → now | 1 | **yes** | N>1 draws per (model, task) with spread reported, every skipped pair recorded with its reason, truncation counted from recorded `done_reason` instead of estimated from response endings |

_Every run above is still committed in `runs/`. A harness change that alters what is measured makes old runs a different dataset, not a longer time series, so they are cited as history and never averaged with current ones._

### 🔍 Data quality (measured, not estimated)

- **Truncation — counted, not guessed.** 3 of 66 responses hit the token budget and were **retried once at 2× budget**; 1 then completed and was scored, 2 are still cut off and therefore **unscored (`null`), never 0.0** — excluded from every mean above. This is read from Ollama's recorded `done_reason`, not inferred from how a response ends. (The caveat this replaces estimated truncation from trailing punctuation and published "~2 of 143 zero-scores" for the previous era — a figure that could not have been right in principle, since a truncated row is unscored and so is never in the zero-score pool being counted. The same data, read from the recorded fields: 77 retried, 31 rescued, 46 still truncated.)
- **Zero-scores are real zeros.** 9 of 66 rows scored 0.0 with a complete, untruncated response — answers the scorer or judge rejected, not harness artefacts.
- **Errors:** 0 results errored (Ollama unreachable / model tag failed to pull). Errored rows are excluded from means.
- **Image-ingestion failures:** 2 vision row(s) where the model replied that no image was supplied. Those are harness/ingestion failures, **unscored** rather than published as a vision-capability score.
- **Coverage is disclosed, not even.** Tasks attempted: `qwen3.5:9b` 9, `gemma4:e4b` 11, `minicpm-v:latest` 2. Every skipped pair is recorded with its reason (see Coverage) and the leaderboard carries a **shared-task column** so cross-model comparison is like-for-like. Vision-only models attempt no text tasks by design — their overall average is not comparable to a text model's and is marked `👁`.
- **Multi-sample, single judge.** N=3 draws per (model, task) with the spread reported above, so a number here is a mean with an interval rather than one draw. **The judge is still a single NVIDIA-70B pass** — there is no inter-rater agreement, and there will not be while the free-judge + one-GPU constraint holds (a second judge means either another cloud key or evicting the model-under-test from the 12 GB card).
- **Item count is the real ceiling.** Each task is still **one prompt** graded binary. Repeating a draw measures sampling noise; it cannot fix a battery of 11 items. Retiring that needs suites with mechanical ground truth (`IMPROVEMENTS.md` P2.2) — until then these are smoke-test numbers.

