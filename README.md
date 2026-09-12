# llm-autobench

**A zero-cost harness that pulls, benches, judges off-box, then deletes — on a 12 GB card you already own.**

> **Public models only · no secrets / private data · free NVIDIA NIM judge · no paid API.** The local GPU never holds a judge and a subject at the same time.

The scores are instrumentation. The product is the lifecycle.

Use it to decide whether an Ollama model is worth keeping on a 12 GB workstation — not to crown a winner.

## What it's good for

| Question | Answered here |
|---|---|
| Does this model fit and run on 12 GB VRAM? | ✅ measured, not estimated |
| How slow is it on consumer hardware? | ✅ per-task latency, real hardware |
| What does continuous benchmarking cost? | ✅ **nothing** — free judge, local compute |
| Can it run unattended without filling the disk? | ✅ that is what the lifecycle is for |
| Which model is *better*? | ❌ **not from this data** |

## Architecture — delete is the feature

```
   ┌─ Cycle · orchestrator + judge = FREE NVIDIA NIM (70B-class text judge) ─────────
   │
   │   1. discover   find a model id not yet benchmarked ── fits 12 GB VRAM? (≤ ~14B)
   │   2. pull       ollama pull <model>
   │   3. bench      run_bench.py → local Ollama runs ONE subject per discovery night  (heavy)
   │   4. judge      free NVIDIA NIM scores each output against the task rubric
   │   5. report     write reports/<run_id>.md
   │   6. delete     ollama rm <model>          (free disk + VRAM for the next cycle)
   │   7. commit     git commit runs/ + reports/
   │
   └─ Local Ollama does step 3 only; everything else runs FREE in the cloud ─────────
```

A 12 GB box cannot host a judge *and* a subject, so the judge is cloud-side on a free tier. **Step 6 is the one nobody else does.** Without deleting the model, a machine that is also your workstation fills its disk within days.

An Ollama **tag** is the model id / name (`qwen3.5:9b` = name:variant).

**From 2026-09-04**, a requested Ollama tag's parameter size is what runs (`gemma4:12b` is never silently substituted for `gemma4:e4b`). Rows dated before that may predate the fix.

## Limits

- **Not a ranking.** Smoke-test battery. Do not pick a "better model" from this table.
- **11 tasks × 1 prompt each.** N=3 measures draw noise, not category depth. Real suites: [`IMPROVEMENTS.md`](IMPROVEMENTS.md).
- **Single free judge** — no κ. Architectural choice (one GPU for the subject).
- **Label ≠ content** — e.g. `logical_reasoning` is an arithmetic word problem.
- **Public only** — MIT; run JSONs are model outputs on fixed public tasks. Don't paste secrets into custom tasks if you fork.

## Reading gap (expired judge)

The table can look complete while almost nothing was actually *read*.

From 2026-08-26 the NVIDIA NIM judge we were using (`meta/llama-3.3-70b-instruct`) was end-of-life. Every rubric-llm row came back `null`. Mechanical tasks still scored, so the README still showed a mean. Thirteen nights of “the model scored X” were really “the judge never ran.”

That was not treated as a failure mode. The harness already knew how to leave a subject-model miss unscored. It did **not** treat “the judge model itself expired” as an outage. Error bodies looked like a blip; keep-going-through-a-failing-model (meant for the *subject*) produced a report that looked ordinary. A later, louder break (repo move, key left behind) is the only reason the quiet outage was noticed.

Fixes in the pipeline (not a claim that tonight is proven): live judge preflight, `NVIDIA_JUDGE_MODEL` swap without a code edit, judged-coverage on every aggregate (`n/N` rows scored), `parse_score` no longer guessing a float out of truncated reasoning.

A later, different miss — `summarization` on run `20260911_122458` — is a **judge parse error** (unscored, not a 0.00). `structured_output` **0.00** on that run is a real zero.

Ad hoc 2026-09-12 run `20260912_122724` (N=3, `qwen3.5:9b`, judge pinned to `meta/llama-3.1-nemotron-70b-instruct` because llama-3.3 is EOL): **0 rubric rows scored**. Persistent `JUDGE_ERROR: Extra data: line 1 column 5 (char 4)` on changelog / code_review / instruction_following / sprint_narrative / summarization. Mechanical tasks still scored; `structured_output` is again a real 0.00. Swapping the judge model is not enough if the parser still cannot read the reply.

## Results

Current methodology only (runs since 2026-09-07 — earlier harness versions are kept as history, not averaged in). Shared-task column is the like-for-like one — not a model ranking. Methodology that used to live here (old truncation estimates, silent skips) is in the generated block below and in [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

**Read the judged-coverage line under the table before quoting a number.** It states how many rows carry a real score; a low share means the LLM judge did not run and the mean covers mechanical tasks only. Fully-judged nights run to 100%. Current pipeline state: [`STATUS.md`](STATUS.md).

<!-- RESULTS:START (auto-generated by scripts/aggregate_results.py; do not edit by hand) -->
_Current-methodology aggregate across **3 runs** (2026-09-07 → 2026-09-12), **2 models**, **15 tasks**, 112 model×task×sample results (**N=1/3** draws per model×task). Sorted by mean for scanability — **not a ranking**. Judge: free NVIDIA NIM. Regenerate: `python scripts/aggregate_results.py --inject README.md`._

_Judged coverage: **77/112 rows scored (69%)**; 35 row(s) carry no score and are excluded from every mean above. A large unscored share means the LLM judge did not run — read the per-run report before trusting these numbers._

### Smoke results (current-methodology mean score)

| Model | Avg | 95% CI | Shared-task | n | Runs / Tasks | Latency |
|---|---:|---:|---:|---:|---:|---:|
| `qwen3.5:9b` | **0.84** | 0.72–0.96 | 0.84 | 39 | 2 / 16 | 4.1s |
| `aya-expanse:8b` | **0.78** | 0.61–0.94 | 0.78 | 27 | 1 / 16 | 1.7s |

> **Avg** is over text/vision tasks a model attempted (agentic excluded — separate regime). **Shared-task avg** is over the 14 text task(s) every general model attempted (`arithmetic_reasoning`, `changelog_generation`, `code_generation`, `code_review`, `gsm8k_s01`, `gsm8k_s02`, `gsm8k_s03`, `gsm8k_s04`, `gsm8k_s05`, `instruction_following`, `logical_reasoning`, `sprint_narrative`, `structured_output`, `summarization`) — that column is the like-for-like one. Agentic tool-call scores are **never** folded into Avg or Shared-task (SPEC 13.6). `—` = vision-only model. `👁` = vision-only coverage (different judging regime).

### Agentic tools (separate regime — not ranked with text)

| Model | Task | Mean | n | notes |
|---|---|---:|---:|---|
| `aya-expanse:8b` | `tool_multiturn_sum` | 0.00 | 3 | mechanical trajectory |
| `qwen3.5:9b` | `tool_multiturn_sum` | 1.00 | 4 | mechanical trajectory |
| `qwen3.5:9b` | `tool_weather` | 1.00 | 4 | mechanical tool-call |

> Agentic regime (SPEC 13.3 single-turn + 13.4/13.5 multi-turn). Primary multi-turn score is `completed`; full trajectory sub-scores live on run rows. `tools_unsupported` rows are **unscored** (not 0.0): 3 this era. No medals/ranks — smoke framing only.

### 🎯 Task difficulty (mean score across all models)

| Task | Avg | 95% CI | Results (n) | Models | |
|---|---:|---:|---:|---:|---|
| `gsm8k_s01` | 1.00 | exact | 7 | 2 | `██████████` |
| `gsm8k_s02` | 1.00 | exact | 7 | 2 | `██████████` |
| `gsm8k_s03` | 1.00 | exact | 7 | 2 | `██████████` |
| `gsm8k_s04` | 1.00 | exact | 7 | 2 | `██████████` |
| `logical_reasoning` | 1.00 | exact | 7 | 2 | `██████████` |
| `code_review` | 1.00 | n<2 | 1 | 1 | `██████████` |
| `instruction_following` | 1.00 | n<2 | 1 | 1 | `██████████` |
| `sprint_narrative` | 1.00 | n<2 | 1 | 1 | `██████████` |
| `arithmetic_reasoning` | 0.86 | 0.51–1.00 | 7 | 2 | `█████████░` |
| `changelog_generation` | 0.80 | n<2 | 1 | 1 | `████████░░` |
| `gsm8k_s05` | 0.71 | 0.26–1.00 | 7 | 2 | `███████░░░` |
| `structured_output` | 0.43 | 0.00–0.92 | 7 | 2 | `████░░░░░░` |
| `code_generation` | 0.17 | 0.00–0.60 | 6 | 2 | `██░░░░░░░░` |

### 🧮 Model × task score matrix

| Task | `qwen3.5:9b` | `aya-expanse:8b` |
|---|---:|---:|
| `gsm8k_s01` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `gsm8k_s02` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `gsm8k_s03` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `gsm8k_s04` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `logical_reasoning` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `code_review` | 1.00 <sub>n=1</sub> | · |
| `instruction_following` | 1.00 <sub>n=1</sub> | · |
| `sprint_narrative` | 1.00 <sub>n=1</sub> | · |
| `arithmetic_reasoning` | 1.00 <sub>n=4</sub> | 0.67 <sub>0.00–1.00, n=3</sub> |
| `changelog_generation` | 0.80 <sub>n=1</sub> | · |
| `gsm8k_s05` | 1.00 <sub>n=4</sub> | 0.33 <sub>0.00–1.00, n=3</sub> |
| `structured_output` | 0.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> |
| `code_generation` | 0.33 <sub>0.00–1.00, n=3</sub> | 0.00 <sub>n=3</sub> |

_Showing the 2 model(s) with ≥2 scored results. `·` = task not attempted (capability tags — see Coverage below). Ranges are 95% t-intervals over that cell's draws, clamped to the `[0, 1]` score range; a cell whose draws all agreed shows no range._

### 🎲 Sampling spread (same model, same prompt, repeated draws)

| Model | Task | Draws | Scores | Mean | Spread |
|---|---|---:|---|---:|---:|
| `aya-expanse:8b` | `arithmetic_reasoning` | 3 | 0, 1, 1 | 0.67 | 1.00 |
| `aya-expanse:8b` | `gsm8k_s05` | 3 | 0, 0, 1 | 0.33 | 1.00 |
| `qwen3.5:9b` | `code_generation` | 3 | 1, 0, 0 | 0.33 | 1.00 |

_3 cell(s) returned different scores for the **same prompt at the same settings**. Each of those is a number a single-draw run would have published as fact._

### 📋 Coverage (what was skipped, and why)

| Model | Tasks attempted | Skipped | Reason |
|---|---:|---:|---|
| `aya-expanse:8b` | 16 | 2 | capability tags (no overlap) |
| `qwen3.5:9b` | 16 | 2 | capability tags (no overlap) |

- `aya-expanse:8b` did not attempt: `vision_ocr`, `vision_progressive`.
- `qwen3.5:9b` did not attempt: `vision_ocr`, `vision_progressive`.

_Skipped pairs mean the model's capability tags and the task's tags have no intersection (e.g. text models skip `vision_*`; vision-only models skip the text battery). That is by design, not a harness error._

### 🗂 Era history — era = dataset/methodology version (previous versions kept but not averaged in)

| Methodology version | Dates | Runs on disk | In this aggregate |
|---|---|---:|---|
| pre-credibility-fix | … → 2026-07-26 | 93 | no |
| credibility fixes (`d61170e`) | 2026-07-27 → 2026-08-22 | 80 | no |
| multi-sample + disclosed coverage | 2026-08-23 → 2026-09-06 | 16 | no |
| python-exec code_generation | 2026-09-07 → now | 3 | **yes** |

- **pre-credibility-fix** — substring scorer (false-positive 1.00), no truncation guard, two disagreeing judge paths
- **credibility fixes (`d61170e`)** — answer extraction + truncation guard + single judge landed, but N=1 per (model, task) with no variance, and the tag gate skipped pairs silently so coverage gaps were invisible
- **multi-sample + disclosed coverage** — N>1 draws per (model, task) with spread reported, every skipped pair recorded with its reason, truncation counted from recorded `done_reason` instead of estimated from response endings
- **python-exec code_generation** — code_generation scored by in-process Python fixture execution (method: python-exec) instead of rubric-llm; coding cells have mechanical ground truth (M1 / SPEC 5.3 thin path)

_Every run above is still committed in `runs/`. A harness change that alters what is measured makes old runs a different dataset, not a longer time series, so they are cited as history and never averaged with current ones._

### 🔍 Data quality (measured, not estimated)

- **Truncation — counted, not guessed.** 2 of 112 responses hit the token budget and were **retried once at 2× budget**; 2 then completed and were scored, 0 are still cut off and therefore **unscored (`null`), never 0.0** — excluded from every mean above. This is read from Ollama's recorded `done_reason`, not inferred from how a response ends.
- **Zero-scores are real zeros.** 15 of 112 rows scored 0.0 with a complete, untruncated response — answers the scorer or judge rejected, not harness artefacts.
- **Errors:** 0 results errored (Ollama unreachable / model tag failed to pull). Errored rows are excluded from means.
- **tools_unsupported:** 3 agentic row(s) emitted no `tool_calls`. Flagged unscored (not 0.0) — cannot-use-tools is not used-tools-wrongly (SPEC 13.3 / DECISIONS 2026-08-24).
- **Coverage is disclosed, not even.** Tasks attempted: `qwen3.5:9b` 16, `aya-expanse:8b` 16. Every skipped pair is recorded with its reason (see Coverage) and the table carries a **shared-task column** so cross-model comparison is like-for-like. Vision-only models attempt no text tasks by design — their overall average is not comparable to a text model's and is marked `👁`.
- **Multi-sample, single judge.** N=1/3 draws per (model, task) with the spread reported above, so a number here is a mean with an interval rather than one draw. **The judge is still a single NVIDIA-70B pass** — there is no inter-rater agreement, and there will not be while the free-judge + one-GPU constraint holds (a second judge means either another cloud key or evicting the model-under-test from the 12 GB card).
- **Item count is the real ceiling.** Each task is still **one prompt** graded binary. Repeating a draw measures sampling noise; it cannot fix a battery of 11 items. Retiring that needs suites with mechanical ground truth (`IMPROVEMENTS.md` P2.2) — until then these are smoke-test numbers.

<!-- RESULTS:END -->

## Quick start

**One discovery cycle** = one subject: pull (optional) → local Ollama bench → free NVIDIA NIM judge → report → delete → refresh this README. Baselines are refreshed separately with `--baselines-only`.

Prerequisites (nothing else):

1. **Ollama** running locally (`ollama serve`, default `127.0.0.1:11434`) with enough free VRAM for the model under test.
2. **`NVIDIA_API_KEY`** in the environment (or a Hermes `.env` the judge already knows how to read) — free NVIDIA NIM tier; no paid API.
3. **Python 3** + `PyYAML` (`pip install pyyaml`). The aggregator is stdlib-only; the cycle script needs YAML to read `models/registry.yaml`.

```bash
# discovery night: ONE subject through the full lifecycle (pull → bench → delete)
python scripts/autobench_cycle.py --model qwen3.5:9b

# keep the subject afterwards, for inspection
python scripts/autobench_cycle.py --model qwen3.5:9b --no-delete

# refresh baselines / vision (no pull, never ollama rm baselines), N=3 draws
python scripts/autobench_cycle.py --baselines-only --samples 3
```

## Layout

| Path | What |
|---|---|
| `scripts/` | The pipeline — cycle, bench, judge, score, aggregate, telemetry |
| `tasks/` | The task battery, one YAML per task — **one prompt each** |
| `models/registry.yaml` | Model ids, VRAM gating, baselines |
| `runs/` | Raw results, one JSON per run |
| `reports/` | Per-run markdown |
| `telemetry/` | Timing and resource data |

## Vision tasks

`vision_ocr` and `vision_progressive` run only against vision-capable model ids. `runs/vision_*.json` are development smoke tests, not benchmark runs — they predate the naming convention and are excluded from aggregates.

## Conventions

Operating rules are in [`AGENTS.md`](AGENTS.md); `CLAUDE.md` imports it. Commits are prefixed `bench:` (result runs) or `autobench:` (lifecycle runs).

## Roadmap

The honest next step is **a real task battery** — many items per category with mechanical ground truth. See [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

## Licence

MIT. Results are generated from public models; nothing here contains third-party proprietary content.
