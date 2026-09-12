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
   ┌─ Cycle · orchestrator + judge = FREE NVIDIA NIM (NVIDIA_JUDGE_MODEL) ─────────
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

## Reading gap (judge outages we didn't count)

The table can look complete while almost nothing was actually *read*. Twice the judge was gone and the harness still published a mean.

1. **Expired model (2026-08-26).** Pin `meta/llama-3.3-70b-instruct` went end-of-life. Every rubric-llm row came back `null`. Mechanical tasks still scored, so README still showed a mean. Thirteen nights of “the model scored X” were really “the judge never ran.” Error bodies looked like a blip (`KeyError: 'choices'`). Keep-going-through-a-failing-model (meant for the *subject*) produced a report that looked ordinary. A later, louder break (repo move, key left behind) is the only reason it was noticed.
2. **Missing catalogue id (2026-09-12).** Pin `meta/llama-3.1-nemotron-70b-instruct` is not on NIM. HTTP body is the plain text `404 page not found`. `json.loads` treats the leading `404` as an int → `Extra data: line 1 column 5`. Same class of miss: 0 rubric rows on an otherwise ordinary-looking report.

Neither was truncated JSON. Neither was `parse_score`.

**Now in the pipeline** (not a claim that 20:00 is proven): live judge preflight; `NVIDIA_JUDGE_MODEL` swap without a code edit; judged-coverage `n/N` on every aggregate; `parse_score` does not guess a float from truncated reasoning; `decode_judge_response` names a 404 and does not retry it.

**This era:** run `20260912_122724` re-judged on default `nvidia/nemotron-3-super-120b-a12b` — **13/15 rubric rows**. Two `summarization` rows still unparseable (reasoning preamble, not Extra data). `structured_output` **0.00** is a real zero. Nightly is **20:00 daily**; Task Scheduler has not yet completed a scheduled run after the PATH fix.

## Results

Current methodology only (runs since 2026-09-07 — earlier harness versions are kept as history, not averaged in). Shared-task column is the like-for-like one — not a model ranking. Methodology that used to live here (old truncation estimates, silent skips) is in the generated block below and in [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

**Read the judged-coverage line under the table before quoting a number.** It states how many rows carry a real score; a low share means the LLM judge did not run and the mean covers mechanical tasks only. Fully-judged nights run to 100%. Current pipeline state: [`STATUS.md`](STATUS.md).

<!-- RESULTS:START (auto-generated by scripts/aggregate_results.py; do not edit by hand) -->
_Current-methodology aggregate across **4 runs** (2026-09-07 → 2026-09-12), **3 models**, **16 tasks**, 160 model×task×sample results (**N=1/3** draws per model×task). Sorted by mean for scanability — **not a ranking**. Judge: free NVIDIA NIM. Regenerate: `python scripts/aggregate_results.py --inject README.md`._

_Judged coverage: **126/160 rows scored (79%)**; 34 row(s) carry no score and are excluded from every mean above. A large unscored share means the LLM judge did not run — read the per-run report before trusting these numbers._

### Smoke results (current-methodology mean score)

| Model | Avg | 95% CI | Shared-task | n | Runs / Tasks | Latency | Err |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen3.5:9b` | **0.84** | 0.75–0.93 | 0.84 | 52 | 2 / 16 | 4.1s | - |
| `aya-expanse:8b` | **0.78** | 0.61–0.94 | 0.78 | 27 | 1 / 16 | 1.7s | - |
| `aya:8b` | **0.33** | 0.17–0.49 | 0.33 | 33 | 1 / 16 | 1.2s | 6 |

> **Avg** is over text/vision tasks a model attempted (agentic excluded — separate regime). **Shared-task avg** is over the 14 text task(s) every general model attempted (`arithmetic_reasoning`, `changelog_generation`, `code_generation`, `code_review`, `gsm8k_s01`, `gsm8k_s02`, `gsm8k_s03`, `gsm8k_s04`, `gsm8k_s05`, `instruction_following`, `logical_reasoning`, `sprint_narrative`, `structured_output`, `summarization`) — that column is the like-for-like one. Agentic tool-call scores are **never** folded into Avg or Shared-task (SPEC 13.6). `—` = vision-only model. `👁` = vision-only coverage (different judging regime).

### Agentic tools (separate regime — not ranked with text)

| Model | Task | Mean | n | notes |
|---|---|---:|---:|---|
| `aya-expanse:8b` | `tool_multiturn_sum` | 0.00 | 3 | mechanical trajectory |
| `aya:8b` | `tool_multiturn_sum` | 0.00 | 3 | mechanical trajectory |
| `qwen3.5:9b` | `tool_multiturn_sum` | 1.00 | 4 | mechanical trajectory |
| `qwen3.5:9b` | `tool_weather` | 1.00 | 4 | mechanical tool-call |

> Agentic regime (SPEC 13.3 single-turn + 13.4/13.5 multi-turn). Primary multi-turn score is `completed`; full trajectory sub-scores live on run rows. `tools_unsupported` rows are **unscored** (not 0.0): 6 this era. No medals/ranks — smoke framing only.

### 🎯 Task difficulty (mean score across all models)

| Task | Avg | 95% CI | Results (n) | Models | |
|---|---:|---:|---:|---:|---|
| `instruction_following` | 1.00 | exact | 7 | 2 | `██████████` |
| `sprint_narrative` | 0.92 | 0.78–1.00 | 6 | 2 | `█████████░` |
| `gsm8k_s02` | 0.90 | 0.67–1.00 | 10 | 3 | `█████████░` |
| `changelog_generation` | 0.78 | 0.67–0.88 | 4 | 1 | `████████░░` |
| `gsm8k_s01` | 0.70 | 0.35–1.00 | 10 | 3 | `███████░░░` |
| `gsm8k_s03` | 0.70 | 0.35–1.00 | 10 | 3 | `███████░░░` |
| `gsm8k_s04` | 0.70 | 0.35–1.00 | 10 | 3 | `███████░░░` |
| `logical_reasoning` | 0.70 | 0.35–1.00 | 10 | 3 | `███████░░░` |
| `code_review` | 0.62 | 0.30–0.94 | 7 | 2 | `██████░░░░` |
| `arithmetic_reasoning` | 0.60 | 0.23–0.97 | 10 | 3 | `██████░░░░` |
| `structured_output` | 0.60 | 0.23–0.97 | 10 | 3 | `██████░░░░` |
| `gsm8k_s05` | 0.50 | 0.12–0.88 | 10 | 3 | `█████░░░░░` |
| `summarization` | 0.38 | 0.00–1.00 | 2 | 2 | `████░░░░░░` |
| `code_generation` | 0.17 | 0.00–0.60 | 6 | 2 | `██░░░░░░░░` |

### 🧮 Model × task score matrix

| Task | `qwen3.5:9b` | `aya-expanse:8b` | `aya:8b` |
|---|---:|---:|---:|
| `instruction_following` | 1.00 <sub>n=4</sub> | · | 1.00 <sub>n=3</sub> |
| `sprint_narrative` | 1.00 <sub>n=4</sub> | · | 0.75 <sub>n=2</sub> |
| `gsm8k_s02` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 0.67 <sub>0.00–1.00, n=3</sub> |
| `changelog_generation` | 0.78 <sub>0.67–0.88, n=4</sub> | · | · |
| `gsm8k_s01` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 0.00 <sub>n=3</sub> |
| `gsm8k_s03` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 0.00 <sub>n=3</sub> |
| `gsm8k_s04` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 0.00 <sub>n=3</sub> |
| `logical_reasoning` | 1.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 0.00 <sub>n=3</sub> |
| `code_review` | 0.71 <sub>0.37–1.00, n=4</sub> | · | 0.50 <sub>0.00–1.00, n=3</sub> |
| `arithmetic_reasoning` | 1.00 <sub>n=4</sub> | 0.67 <sub>0.00–1.00, n=3</sub> | 0.00 <sub>n=3</sub> |
| `structured_output` | 0.00 <sub>n=4</sub> | 1.00 <sub>n=3</sub> | 1.00 <sub>n=3</sub> |
| `gsm8k_s05` | 1.00 <sub>n=4</sub> | 0.33 <sub>0.00–1.00, n=3</sub> | 0.00 <sub>n=3</sub> |
| `summarization` | 0.75 <sub>n=1</sub> | · | 0.00 <sub>n=1</sub> |
| `code_generation` | 0.33 <sub>0.00–1.00, n=3</sub> | 0.00 <sub>n=3</sub> | · |

_Showing the 3 model(s) with ≥2 scored results. `·` = task not attempted (capability tags — see Coverage below). Ranges are 95% t-intervals over that cell's draws, clamped to the `[0, 1]` score range; a cell whose draws all agreed shows no range._

### 🎲 Sampling spread (same model, same prompt, repeated draws)

| Model | Task | Draws | Scores | Mean | Spread |
|---|---|---:|---|---:|---:|
| `aya-expanse:8b` | `arithmetic_reasoning` | 3 | 0, 1, 1 | 0.67 | 1.00 |
| `aya-expanse:8b` | `gsm8k_s05` | 3 | 0, 0, 1 | 0.33 | 1.00 |
| `qwen3.5:9b` | `code_generation` | 3 | 1, 0, 0 | 0.33 | 1.00 |
| `aya:8b` | `code_review` | 3 | 0.5, 0, 1 | 0.50 | 1.00 |
| `aya:8b` | `gsm8k_s02` | 3 | 0, 1, 1 | 0.67 | 1.00 |
| `qwen3.5:9b` | `code_review` | 4 | 1, 0.66, 0.5, 0.67 | 0.71 | 0.50 |
| `qwen3.5:9b` | `changelog_generation` | 4 | 0.8, 0.75, 0.7, 0.85 | 0.78 | 0.15 |

_7 cell(s) returned different scores for the **same prompt at the same settings**. Each of those is a number a single-draw run would have published as fact._

### 📋 Coverage (what was skipped, and why)

| Model | Tasks attempted | Skipped | Reason |
|---|---:|---:|---|
| `aya-expanse:8b` | 16 | 2 | capability tags (no overlap) |
| `aya:8b` | 16 | 2 | capability tags (no overlap) |
| `qwen3.5:9b` | 16 | 2 | capability tags (no overlap) |

- `aya-expanse:8b` did not attempt: `vision_ocr`, `vision_progressive`.
- `aya:8b` did not attempt: `vision_ocr`, `vision_progressive`.
- `qwen3.5:9b` did not attempt: `vision_ocr`, `vision_progressive`.

_Skipped pairs mean the model's capability tags and the task's tags have no intersection (e.g. text models skip `vision_*`; vision-only models skip the text battery). That is by design, not a harness error._

### 🗂 Era history — era = dataset/methodology version (previous versions kept but not averaged in)

| Methodology version | Dates | Runs on disk | In this aggregate |
|---|---|---:|---|
| pre-credibility-fix | … → 2026-07-26 | 93 | no |
| credibility fixes (`d61170e`) | 2026-07-27 → 2026-08-22 | 80 | no |
| multi-sample + disclosed coverage | 2026-08-23 → 2026-09-06 | 16 | no |
| python-exec code_generation | 2026-09-07 → now | 4 | **yes** |

- **pre-credibility-fix** — substring scorer (false-positive 1.00), no truncation guard, two disagreeing judge paths
- **credibility fixes (`d61170e`)** — answer extraction + truncation guard + single judge landed, but N=1 per (model, task) with no variance, and the tag gate skipped pairs silently so coverage gaps were invisible
- **multi-sample + disclosed coverage** — N>1 draws per (model, task) with spread reported, every skipped pair recorded with its reason, truncation counted from recorded `done_reason` instead of estimated from response endings
- **python-exec code_generation** — code_generation scored by in-process Python fixture execution (method: python-exec) instead of rubric-llm; coding cells have mechanical ground truth (M1 / SPEC 5.3 thin path)

_Every run above is still committed in `runs/`. A harness change that alters what is measured makes old runs a different dataset, not a longer time series, so they are cited as history and never averaged with current ones._

### 🔍 Data quality (measured, not estimated)

- **Truncation — counted, not guessed.** 2 of 160 responses hit the token budget and were **retried once at 2× budget**; 2 then completed and were scored, 0 are still cut off and therefore **unscored (`null`), never 0.0** — excluded from every mean above. This is read from Ollama's recorded `done_reason`, not inferred from how a response ends.
- **Zero-scores are real zeros.** 39 of 160 rows scored 0.0 with a complete, untruncated response — answers the scorer or judge rejected, not harness artefacts.
- **Errors:** 6 results errored (Ollama unreachable / model tag failed to pull). Errored rows are excluded from means.
- **tools_unsupported:** 6 agentic row(s) emitted no `tool_calls`. Flagged unscored (not 0.0) — cannot-use-tools is not used-tools-wrongly (SPEC 13.3 / DECISIONS 2026-08-24).
- **Coverage is disclosed, not even.** Tasks attempted: `qwen3.5:9b` 16, `aya-expanse:8b` 16, `aya:8b` 16. Every skipped pair is recorded with its reason (see Coverage) and the table carries a **shared-task column** so cross-model comparison is like-for-like. Vision-only models attempt no text tasks by design — their overall average is not comparable to a text model's and is marked `👁`.
- **Multi-sample, single judge.** N=1/3 draws per (model, task) with the spread reported above, so a number here is a mean with an interval rather than one draw. **The judge is still a single NVIDIA NIM pass** — there is no inter-rater agreement, and there will not be while the free-judge + one-GPU constraint holds (a second judge means either another cloud key or evicting the model-under-test from the 12 GB card).
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
