# IMPROVEMENTS.md — llm-autobench roadmap

**Status as of 2026-07-22.** Grounded in a firsthand read of all five harness scripts,
every task, the registry, and a deterministic aggregate of all 98 committed runs
(`scripts/aggregate_results.py`). Priorities: **P0 = the benchmark must be *trustworthy*
before it is made *bigger*** (its own SPEC §12 principle), **P1 = make results legible**,
**P2 = scale**.

---

## The honest through-line

The engineering is genuinely strong: an autonomous `discover → pull → bench → judge → delete
→ commit` loop, a free-cloud judge kept off the local GPU so a 12GB box can host the
model-under-test alone, and a two-stage vision judge (strong describer → 70B text judge).
The project also **audited itself** on 2026-07-18 (SPEC §11) and wrote an excellent
credibility-first remediation plan (SPEC §12, `DECISIONS.md`).

**The gap: most of that remediation was logged as "decided" but never landed in the code.**
Cross-checking the claimed fixes against the current scripts shows the harness still carries
the credibility bugs it diagnosed. That is the single most valuable thing to fix — and it's a
strong Technical-PM story ("I audited my own benchmark, then closed the audit").

### Claimed-vs-actual (verified)

| Remediation (SPEC §12 / DECISIONS) | Claimed | Actual in code | Evidence |
|---|---|---|---|
| F1.1 `bench()` benchmarks the *pulled* model | ✅ | ✅ **done** | `autobench_cycle.py:195` `build_temp_registry` injects the tag |
| F0.2 Reject truncated output (`finish_reason==length`) | ✅ | ❌ **not implemented** | `grep done_reason\|finish_reason\|truncat scripts/` → 0 matches; ~107/178 zero-scores are truncated |
| F0.1 Answer-extraction scorer (word-boundary) | ✅ | ❌ **still substring** | `run_bench.py:147` `expected in response` |
| F1.4 VRAM guard fail-closed | ✅ | ❌ **still fails open** | `autobench_cycle.py:73` `return True` on `nvidia-smi` failure |
| F0.5 Honest (derived) judge status | ✅ | ❌ **hard-coded** | `judge_report.py:152` `"Free judge: yes (OpenRouter free tier)"` |
| Report attributes rows to the right model | — | ❌ **mixing bug** | `nvidia_judge.py:301` titles report `scored[0].model`, then dumps *all* models' rows (`:316`) |
| F1.2 Cycle calls the judge/report | ✅ | ❌ **not wired** | `autobench_cycle.py` has no judge reference; judging is out-of-band |
| D6 Wire `telemetry.py` | planned | ❌ **dead code** | only self-references; never imported |
| F1.3 `discover()` parses real tags | ✅ | ⚠️ **partial** | `_param_from_tag` (`autobench_cycle.py:100`) still drops `:instruct`/`:latest`/`8x7b` |

---

## P0 — Credibility (the benchmark currently misreports)

> ✅ **All P0 items (P0.1-P0.5) shipped 2026-07-22**, each proven against its real failing
> case. The claimed-vs-actual table above is the pre-fix snapshot; the code now matches the
> 2026-07-18 remediation plan. See `DECISIONS.md` (2026-07-22 entries).

### P0.1 · Implement the truncation guard · ✅ **shipped 2026-07-22** `[S]`
**Problem.** No script reads Ollama's `done_reason`. Reasoning models spend their whole token
budget on chain-of-thought and get cut off *before* stating an answer, which the scorer then
reads as a wrong answer. This is the biggest single distortion in the data: `arithmetic_reasoning`
sits at **0.36** and `qwen3.5:9b` scores **0.16** on it and only **0.76** on `logical_reasoning`
— not capability, truncation (~107 of 178 zero-scores end mid-sentence).
**Actions.**
1. In `call_model` (`run_bench.py:95-108`) capture `resp.get("done_reason")` / `done`.
2. If `done_reason == "length"`, set `truncated: true` and **re-run once at 2× `max_tokens`**;
   if still truncated, score `null` (unscored/±), never `0.0`.
3. Split think/answer budgets or raise `max_tokens` for reasoners (arithmetic/logical already
   at 1024 — still too small for `qwen3.5`; try 2048 + a "state your final answer on the last
   line" instruction).
**Files.** `run_bench.py` (`call_model`, `score`, `main`). **Accept.** `qwen3.5:9b`
`logical_reasoning` stops returning 0.0 from cutoff; the truncated-zero count in
`aggregate_results.py` drops sharply.

### P0.2 · Fix the report model-attribution bug · ✅ **shipped 2026-07-22** `[S]`
**Problem.** `nvidia_judge.py` titles each report with `scored[0]["model"]` but its table iterates
**every** model's rows — so `reports/20260722_030027.md` is titled `gemma4:e4b` yet contains
`qwen3.5:9b` rows, and its "0.72 average" mixes two models.
**Actions.** Group by model (as `judge_report.py:98` already does); emit a per-run leaderboard +
one section per model + a Failures section. **Files.** `nvidia_judge.py:298-331`.
**Accept.** A 2-model run renders a 2-row leaderboard with rows under the correct model.

### P0.3 · Real answer-extraction scorer · ✅ **shipped 2026-07-22** `[S]`
**Problem.** `run_bench.py:147` still does `expected in response`; the exact D1 false-positive
(`"5:00"` matching inside `"15:00"`) is still latent for any response mentioning `15:00`/`25:00`.
**Actions.** Extract the final answer (labelled line / last number / per-task regex) and match on
word boundaries. **Files.** `run_bench.py` `score()`. **Accept.** A response containing `15:00`
but not a standalone `5:00` scores **0** on `arithmetic_reasoning`.

### P0.4 · VRAM guard fails closed · ✅ **shipped 2026-07-22** `[S]`
**Problem.** `autobench_cycle.py:73` returns `True` when `nvidia-smi` fails — an oversized pull can
OOM a shared 12GB box mid-bench. DECISIONS.md says this was fixed; it wasn't.
**Actions.** Return `False` (skip + log) on probe failure. **Files.** `autobench_cycle.py:69-74`.
**Accept.** A simulated `nvidia-smi` failure logs a skip and does not pull.

### P0.5 · One judge path, no hard-coded status · ✅ **shipped 2026-07-22** `[S]`
**Problem.** Two report generators disagree: `nvidia_judge.py` (NVIDIA, the real path) and the
legacy `judge_report.py` (OpenRouter + hard-coded `"Free judge: yes"`). The README/registry say
NVIDIA; the legacy file contradicts both.
**Actions.** Make `nvidia_judge.py` the single generator (delete or clearly quarantine
`judge_report.py`); ensure every status line is derived from run outcomes. **Files.**
`judge_report.py`, `score_run.py`. **Accept.** Repo has one judge path; no static status strings.

---

## P1 — Legibility (make 6+ days of data visible)

### P1.1 · All-time aggregate results — ✅ **shipped 2026-07-22** `[S]`
`scripts/aggregate_results.py` computes the all-time leaderboard, task-difficulty, model×task
matrix, and honest caveats, and injects them into the README (`RESULTS:START/END` markers) +
`reports/LEADERBOARD.md`. Before this, 98 runs of data had **no** aggregate view anywhere.

### P1.2 · Regenerate results every cycle · ✅ **shipped 2026-08-23** `[S]`
**Actions.** `autobench_cycle.report()` runs `score_run.py` (free NVIDIA judge) then
`aggregate_results.py --inject README.md`, and `commit()` stages `README.md` alongside
`runs/`+`reports/`. Judge failure is fatal: an unscored run is never aggregated as if it were
scored. `nightly.py` passes the new `--no-report` so the same run is not judged twice.
Closes **F1.2** (cycle → judge → report). **Files.** `autobench_cycle.py` (`report`, `commit`,
`main`), `nightly.py`.
**Accept.** One `autobench_cycle.py --baselines-only --samples 3` yielded run + report +
refreshed README + commit with no manual step — see the run cited under P2.1 below.
Also added `--baselines-only`, a flag the README had documented for weeks without it existing.

### P1.3 · Even out task coverage + disclose skips · ✅ **shipped 2026-08-23** `[M]`
**Problem (as diagnosed).** Tag-gating meant `qwen3.5:9b` attempted **5** tasks and `gemma4:e4b`
**11**; the leaderboard cross-model averages were not apples-to-apples.
**What actually shipped.** Three parts, because the diagnosis was only half the problem:
1. `registry.yaml` gained `battery_tags` as the single source of truth for the text battery, and
   both baselines and the discovered-model entry read it (2026-08-15). qwen went 5 → **9** tasks.
2. The tag gate no longer skips in silence: `run_bench.py` records **every** refused
   `(model, task)` pair with its reason, model tags and task tags into `runs/<id>.json`
   (`skipped: [...]`), and the aggregate renders a Coverage table from it (**F1.6/D5**).
3. The leaderboard gained a **shared-task avg** column over the tasks every general model
   attempted — the like-for-like number — next to the whole-coverage average.
**Residual, by design.** Coverage is *disclosed*, not *equal*: `minicpm-v` is a vision-only VLM
and attempts no text battery at all. Forcing it to would publish nonsense; it is marked 👁 and
excluded from the shared column instead.
**Files.** `models/registry.yaml`, `run_bench.py` (gate + run record), `aggregate_results.py`.

---

## P2 — Scale (only after P0 is green — SPEC §4–§8 roadmap)

- **P2.1 Multi-run + confidence `[M]` · ✅ shipped 2026-08-23.** `run_bench.py --samples N` draws N
  responses per (model, task) — N=1 had been *structural*, not a setting: there was no sample loop
  in the runner at all. `nightly.py` runs N=3. The aggregate reports mean ± 95% CI (Student t, not
  a flat 1.96, because these sample sizes are small) on the leaderboard, per task, and in every
  matrix cell, plus a **sampling-spread** table listing each (model, task) that disagreed with
  itself across identical draws — the direct evidence that a single draw was never a measurement.
  Not seeded: Ollama exposes no reliable per-call seed, and a fixed seed would suppress the very
  variance being reported (see `DECISIONS.md` 2026-08-23).
- **P2.2 Established suites `[L]`.** Port a GSM8K + HumanEval slice with **execution-based** code
  scoring (run the code, check tests) — removes judge subjectivity on code and counters
  "my tasks are easy for my models" bias (SPEC §4/§5.3).
- **P2.3 Judge robustness `[M]`.** Self-consistency (judge each response 3× at temp 0, take the
  median) and/or a small judge panel with inter-rater κ (SPEC §5.2).
- **P2.4 Wire telemetry `[S]` · ✅ shipped 2026-07-22.** `run_bench.py` now records tokens /
  tok-per-s / VRAM / cost (`$0` local) per call to `telemetry/usage_*.jsonl` (gitignored),
  killing the dead code (**D6**). Perf axis on the leaderboard is still TODO (data now exists).
- **P2.5 Fix `discover()` tag parsing `[S]`.** Parse `:instruct`/`:latest`/quantized/`8x7b` and drop
  non-sized tags explicitly, not silently (**F1.3/D8**); add a unit test over sample tags.
- **P2.6 Genuinely-unattended `[M]`.** Real scheduler + `git push` so "while I sleep" is wired
  end-to-end (**D9**); a static `dashboard/` (Chart.js) rendering `trends.csv` over time (SPEC §8).
- **P2.7 The post-mortem `[S]`.** A short "**What I found auditing my own benchmark**" write-up —
  the strongest Technical-PM signal in the whole repo (SPEC §12 Phase 3).

---

## What the caveats block still cannot retire (2026-08-23)

The README "Data quality" caveats were rewritten to be **measured rather than asserted**, and three
of the four causes were fixed. These two are structural, and saying so is the point:

| Caveat | Why it survives | What would actually close it |
|---|---|---|
| **Single judge, no inter-rater agreement** | A second opinion needs either a second cloud judge (another provider, another key — the constraint is *one free judge*) or a local judge, which would have to share the 12 GB card with the model-under-test. That contention is the exact thing the architecture exists to avoid. | A second **free** cloud judge and Cohen κ between them (**P2.3**). Judge self-consistency (same judge 3× at temp 0) is cheap but is *not* inter-rater agreement and must not be reported as if it were. |
| **Each task is one prompt, graded binary** | Multi-sampling (**P2.1**, shipped) measures *sampling* noise. It cannot fix *construct* validity: 11 prompts is 11 prompts, and one ambiguous item still swings a category between 1.00 and 0.00. | Suites with mechanical ground truth — a GSM8K + HumanEval slice with execution-based scoring (**P2.2**, sized `[L]`). This is the honest next step and it is a project, not an afternoon. |

Until both land, the numbers in the README are **smoke-test output on a 12 GB box**, which is what
the README says above the leaderboard. That framing is not modesty; it is the accurate scope.

---

## Suggested order

1. ~~**P0.1–P0.5** credibility sprint~~ — ✅ shipped 2026-07-22.
2. ~~**P1.2–P1.3**~~ — ✅ shipped 2026-08-23 (self-updating README + disclosed coverage).
3. **P2.2** (established suites, execution-based code scoring) is now the highest-value item left:
   it is the only thing that lifts this from a smoke test to a benchmark. **P2.3** (judge panel + κ)
   second, **P2.5–P2.7** as capacity allows.
