# llm-autobench — Specification

**Version:** 0.3 (draft) · **Status:** Tier A shipped **but flagship run misreports scores** — see §11–§12
**Owner:** Salahuddin Uqaili · **Visibility:** PUBLIC (portfolio piece)

---

## 1. Purpose

`llm-autobench` is an **autonomous, local-first LLM benchmarking pipeline** that runs
unattended. On a schedule it:

1. **Discovers** newly released open models
2. **Pulls** them onto the local GPU (if they fit VRAM)
3. **Benchmarks** them against a fixed, versioned task battery
4. **Judges** the outputs (local reward model + free cloud panel)
5. **Reports** results (leaderboard + per-model breakdown)
6. **Deletes** the model (keeps disk/VRAM free)
7. **Commits** raw data + report to git

The pipeline demonstrates a self-operating evaluation factory — the headline portfolio
claim is *"a pipeline that tests models while I sleep, then cleans up after itself."*

### Design constraints (non-negotiable)
- **Public repo.** No secrets, no private-repo data (per-x, profile-x, hardware-x, tether,
  dark-factory). Only public models + public task prompts.
- **Free judge only.** Judging/reporting uses a free model (hy3:free) or a **local** reward
  model. No paid spend on this pipeline.
- **Local compute for the model-under-test.** Ollama (127.0.0.1:11434) runs the model being
  benchmarked. The judge lives on free cloud or local — never competing for the same VRAM.
- **12GB VRAM ceiling.** `watcher.max_params_billions: 14` is the hard cap for this box.
- **Self-cleaning.** Every pulled model is `ollama rm`'d after its run.

---

## 2. Architecture

```
┌──────────────── Hermes cron (daily 02:00, no_agent gateway) ────────────────┐
│                                                                               │
│  autobench_cycle.py  (mechanical local work)                                 │
│   ├─ discover()      poll ollama.com/library, filter ≤14B, exclude tested    │
│   ├─ VRAM guard      nvidia-smi free check; skip if headroom insufficient    │
│   ├─ pull()          ollama pull <model>                                     │
│   ├─ bench()         run_bench.py  → Ollama runs model-under-test (heavy)    │
│   ├─ delete()        ollama rm <model>                                       │
│   └─ commit()        git add runs/ reports/ && commit                       │
│                                                                               │
│  judge_report.py  (scoring + reporting; run by free Hermes agent)            │
│   ├─ score rubric tasks via local reward model / free judge panel           │
│   ├─ telemetry.track()  log tokens, latency, VRAM, cost for ALL models       │
│   └─ generate_report() → reports/<run_id>.md (leaderboard + detail)         │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Separation of concerns:** the GPU only does step `bench()`. Everything else is light
enough for free cloud or local. This is the core trick that makes 12GB viable.

---

## 3. Current implementation (Tier A — shipped)

| Component | File | Status |
|---|---|---|
| Task battery | `tasks/*.yaml` | 8 tasks, 4 categories (reasoning, coding, writing, structured) |
| Runner | `scripts/run_bench.py` | Loads `baseline:` models × tasks; writes `runs/<run_id>.json` |
| Lifecycle | `scripts/autobench_cycle.py` | discover → VRAM guard → pull → bench → delete → commit |
| Judge/report | `scripts/judge_report.py` | rubric scoring + markdown report (free judge when key set) |
| Telemetry | `scripts/telemetry.py` | `TelemetryTracker` + `TrackedCall` context manager (tokens, latency, VRAM, cost) |
| Registry | `models/registry.yaml` | `baseline:` + `watcher:` (max 14B, judge, delete_after_bench) |
| Cron | `llm-autobench daily cycle` | `0 2 * * *`, job `7ce664bda386` |

**Verified:** full cycle runs end-to-end (qwen3.5:9b, nemotron-3-nano:4b); reports generated;
git commits succeed.

---

## 4. World-class task suite (planned)

Replace hand-rolled tasks with **curated, versioned, contamination-guarded** suites. Each
suite is a directory under `benchmarks/` with `tasks.jsonl` (prompt, expected, metadata) and
a `scorer.py`.

| Suite | Source | Size | Category | Score method |
|---|---|---|---|---|
| **HumanEval** | open (164 problems) | 164 | codegen | pass@k (exec) |
| **MBPP** | open | 500 | codegen | pass@k (exec) |
| **GSM8K** | open | 8.5k | math | exact match |
| **MMLU** | open | 57 subjects | knowledge | accuracy |
| **BBH** | open | 27 tasks | hard reasoning | accuracy |
| **IFEval** | open | 500+ | instruction-following | verifiable rules |
| **MT-Bench** | open | 80 (multi-turn) | chat | judge (RM) |
| **SWE-bench-lite** | open | 300 | real issues | test pass |
| **Custom** | this repo | ~10 | domain (changelog, sprint, etc.) | rubric-RM |

**Principles:**
- Pull from **established** suites (avoids "my tasks are easy for my model" bias).
- **Versioned** (`benchmarks/v1/`) so scores are comparable over time.
- **Contamination guard:** hash all prompts; flag if a model-under-test's training data
  overlaps (heuristic for open models; documented limitation for closed).
- **Difficulty gradient:** tag each task easy/medium/hard for calibrated reporting.

---

## 5. Judging (planned — the "world-class" core)

### 5.1 Local reward model (primary)
A reward model trained on human preferences, run locally via Ollama:
- `sfairXC/FsfairX-LLaMA3-RM-v0.1` (~7B) or `Ray2333/GRM-Llama3-8B-rewardmodel-ft` (~8B)
- Takes `(prompt, response)` → scalar score 0.0–1.0
- **Calibrated, fast, free, no cloud** — fits 12GB alongside model-under-test

### 5.2 Judge panel (secondary / cross-check)
- 3 judges: local RM + 1 free cloud model (hy3:free) + 1 local small model
- Majority vote or mean; report **inter-rater agreement** (Cohen's κ)
- Exposes judge bias (length, sycophancy) in the report

### 5.3 Code tasks use execution, not judges
- HumanEval/MBPP/SWE-bench: **run the generated code**, check test pass
- No LLM judge needed — ground truth is the test suite

---

## 6. Statistics (planned)

| Feature | Method |
|---|---|
| **Multi-run** | Each (model, task) run **N=3–5×** (seeded) |
| **Confidence** | Report mean ± 95% CI per task and overall |
| **Regression detection** | Alert if model's score drops >5% vs its own history (git-diff runs/) |
| **Baselines** | Publish reference numbers for GPT-4o, Claude 3.5, Llama 3.1 (from public sources) for context |
| **Significance** | Pairwise model comparison via bootstrap or t-test on per-task scores |

---

## 7. Telemetry (partially built — `telemetry.py`)

Track **every** call for **every** model (local + cloud):

| Field | Source |
|---|---|
| `prompt_tokens`, `completion_tokens`, `total_tokens` | model usage / estimate |
| `latency_seconds`, `ttft_seconds` | perf_counter |
| `tokens_per_second` | derived |
| `vram_peak_mib`, `vram_delta_mib` | nvidia-smi before/after |
| `cost_usd` | `calculate_cost()` (0 for local/free, priced for paid) |
| `model_provider`, `task_id`, `run_id` | context |

Persisted to `telemetry/usage_YYYYMMDD.jsonl`. **Why:** even free models have rate limits;
owning the usage data is good portfolio signal and enables cost projection if paid models
are ever added.

**OpenRouter note:** free tier is $0, but `GET /api/v1/auth/key` (paid keys only) can show
usage. For free, rely on local tracking. No external call needed.

---

## 8. Reporting

| Output | Format | Audience |
|---|---|---|
| `runs/<run_id>.json` | raw | machine / diff |
| `reports/<run_id>.md` | leaderboard + per-model | human (committed) |
| `telemetry/usage_*.jsonl` | time-series | analysis |
| `dashboard/` (planned) | static HTML + Chart.js | portfolio viewers |
| `trends.csv` (planned) | model × date × score | regression detection |

---

## 9. Constraints recap

- **VRAM:** `estimate_model_vram_mib(b) = b * 512 + 1024` MiB; guard checks `nvidia-smi`
  free ≥ required + 1024 buffer. Models already local skip the check.
- **Public-only:** CI lint rejects any private import (manual review for now).
- **Free judge:** `registry.yaml` → `watcher.judge: tencent/hy3:free`; reward model is local.
- **Self-clean:** `watcher.delete_after_bench: true` (override with `--no-delete`).

---

## 10. Roadmap

| Phase | Scope | Effort |
|---|---|---|
| **A — done** | 8 tasks, lifecycle, judge stub, telemetry skeleton, cron | ✅ |
| **B** | Port HumanEval + GSM8K + IFEval; local RM scorer; 3-run CI | ~2 days |
| **C** | Full suite (MMLU, BBH, MT-Bench, SWE-lite); judge panel + κ; dashboard | ~1 week |
| **D** | Contamination hashing; regression alerts; public GitHub Actions run | ~3 days |

**Next action:** ⚠️ **Superseded by §12.** A 2026-07-18 audit found the flagship run misreports its
scores (a false-positive `1.00`). Do **Phase 0 (credibility)** before Phase B. See §11–§12 and
`DECISIONS.md`.

---

## 11. Audit findings (2026-07-18) — the flagship run is not trustworthy

A four-lens self-audit (methodology · robustness · autonomy · positioning) with adversarial
verification (10 findings confirmed, 4 partial, 0 refuted) found that the committed
"verified end-to-end" run (`runs/20260716_214839.json`, `reports/20260716_214839.md`)
**misreports its results.** Confirmed defects, most severe first:

| # | Sev | Defect | Evidence |
|---|-----|--------|----------|
| **D1** | 🔴 | Leaderboard `1.00` is a **false positive**. Exact scorer is raw substring containment; expected `5:00` matched inside `15:00` on an arithmetic response **truncated before any answer**. | `run_bench.py:92`; response ends "…= 30 km/h", `score: 1.0` |
| **D2** | 🔴 | Autonomous `bench(model)` **ignores its arg** and re-runs the static baseline via `--tier local`; the pulled model is never benchmarked, then deleted (pull+delete = wasted work). | `autobench_cycle.py:133-144, 184`; committed run has only the baseline id |
| **D3** | 🟠 | Judge **never ran** (no `OPENROUTER_API_KEY` → `JUDGE_ERROR` on 2/4 tasks), yet report hard-codes `Free judge: yes` and `Failures: None` (Failures scans `error`; judge errors live in `score_reason`). | `judge_report.py:47, 150-151, 156` |
| **D4** | 🟠 | `max_tokens: 512` is the **entire** budget for thinking-token models → truncation before the final answer on every task. | `*.yaml` max_tokens; all 4 responses cut mid-thought |
| **D5** | 🟠 | **No real comparison**: 2nd baseline `gemma4:e4b` tags `[vision, general]` intersect **zero** tasks → 0/9 attempted, every run effectively **N=1**. | `registry.yaml:24`; gate at `run_bench.py:118` |
| **D6** | 🟠 | `telemetry.py` is **dead code** — never imported by any script (SPEC §7/§10 "next action" already admits this). | grep: only self-references; `telemetry/` never written |
| **D7** | 🟠 | VRAM guard **fails open**: `nvidia-smi` error → `return True` → pull proceeds; `discover()` "prefer larger" biases toward the 14B ceiling. | `autobench_cycle.py:62-63, 121` |
| **D8** | 🟠 | `discover()` regex `:(\d+…)b?$` **silently drops** most real tags (`:latest`, `:instruct`, quantized, MoE `8x7b`). | `autobench_cycle.py:115` |
| **D9** | 🟡 | `judge_report.py` **never called** from the cycle; no cron job actually scheduled (`CronList` empty); `commit()` is local-only (no push) with no empty-index guard. | `autobench_cycle.py:main`, `:152-154`; README step 7 |

**Honesty nuance (verified):** the *second* `1.00` (logical_reasoning → `720`) is **legitimate** —
the model genuinely derived it. Only the **arithmetic** `1.00` is a false positive. One
demonstrably-fake headline number is still enough to violate the "Honesty in reporting" rule
(CLAUDE.md §9). Do not overstate the case: the harness is fixable, not fraudulent.

---

## 12. Remediation plan (credibility-first) — supersedes §10 Phase B as the next action

**Principle:** a benchmark that reports wrong scores must be made *trustworthy* before it is made
*bigger*. Fix scoring / loop / reporting (Phase 0–1) before porting suites (Phase 2).
Every fix ships with the acceptance test below **run against the real failing case** (CLAUDE.md
"run the actual failing case" rule).

### Phase 0 — Credibility (fix the lie; ~0.5 day, all S)
- **F0.1 Answer-extraction scorer.** Replace `expected in response` (`run_bench.py:92`) with
  final-answer extraction (last line / labelled answer / per-task regex) + word-boundary match.
  *Accept:* the arithmetic response that ends at "30 km/h" scores **0.0**, not 1.0. **(D1)**
- **F0.2 Reject truncated output.** In `call_model`, read `finish_reason`; if `length`, mark the
  result truncated and score 0.0 (or re-run with a larger budget). *Accept:* all 4 flagship
  responses flagged truncated. **(D1/D4)**
- **F0.3 Token budget for reasoners.** Raise `max_tokens` (≥1536) or split think/answer budgets so
  a final answer can appear. *Accept:* qwen emits a final `5:00` / `720`, not just scratch-work. **(D4)**
- **F0.4 Loud judge failures.** Failures section reads `score_reason` too; count `JUDGE_ERROR` as a
  failure. *Accept:* a keyless run shows the 2 judge failures under Failures, not "None." **(D3)**
- **F0.5 Honest judge status.** Derive "judge ran / didn't" from actual outcomes; drop the
  hard-coded `Free judge: yes`. *Accept:* a keyless run's report states the judge did not run. **(D3)**
- **F0.6 Regenerate the flagship run.** Re-run + re-commit with the fixed scorer and honest report.
  *Accept:* the committed leaderboard contains **no unearned 1.00.** **(D1)**

### Phase 1 — Make the loop real (~1 day)
- **F1.1** `bench()` benchmarks the **pulled** model (inject the discovered tag into the run set —
  temp registry entry or a `--model` flag on `run_bench.py`). *Accept:* a discovered model appears
  in `runs/…json` and the report. **(D2)**
- **F1.2** Call `judge_report.py` from `autobench_cycle.py` so unattended runs score + report.
  *Accept:* one cycle produces `reports/<id>.md` with no manual step. **(D9)**
- **F1.3** Fix `discover()` regex to parse real tags; drop non-sized tags **explicitly**, not
  silently. *Accept:* a unit test over sample tags (`qwen:latest`, `codellama:7b-instruct`,
  `mixtral:8x7b`, `qwen:110b`). **(D8)**
- **F1.4** VRAM guard **fail closed** (skip on `nvidia-smi` error) + stop biasing to the ceiling.
  *Accept:* a simulated `nvidia-smi` failure → pull skipped and logged. **(D7)**
- **F1.5** Give the 2nd baseline task-intersecting tags (a leaderboard of two). *Accept:* both
  baselines appear in the report. **(D5)**
- **F1.6** Disclose skipped `(model, task)` pairs in the report. *Accept:* the report lists what it
  did **not** run and why.

### Phase 2 — Scale (only after 0–1 are green)  *(was §10 Phase B/C)*
Wire `telemetry.py` into `run_bench.py` **(D6)** · adopt a GSM8K + HumanEval slice with
**execution-based** code scoring (SPEC §5.3) · N=3–5 seeded runs with mean ± 95% CI (SPEC §6).

### Phase 3 — Portfolio
"**What I found auditing my own benchmark**" post-mortem (the strongest Technical-PM signal here) ·
reconcile SPEC/README with code state (telemetry = skeleton, judge panel + κ = planned, push + cron
= not wired) · add a real scheduler + `git push` so "while I sleep" is genuinely wired **(D9)**.

**Next action (revised):** start **Phase 0** in a fresh session. Locked-in choices are in
`DECISIONS.md`; each fix must run its acceptance test against the real failing case before it's
called done.
