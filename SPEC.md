# llm-autobench — Specification

**Version:** 0.2 (draft) · **Status:** Tier A shipped, world-class hardening planned
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

**Next action:** Phase B — add `benchmarks/humaneval/`, wire `telemetry.track()` into
`run_bench.py`, and replace the heuristic scorer with the local reward model.
