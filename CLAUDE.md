# CLAUDE.md — llm-autobench

You are operating inside **llm-autobench**: a **PUBLIC** autonomous LLM-benchmarking repo.
It watches for new open-source model releases, pulls them locally, benchmarks them against
a fixed task battery, reports results, and deletes the model to keep the machine free.

## ⚠️ PUBLIC REPO — HARD RULES
1. **No secrets. No private data.** This repo is public. Never commit credentials, and
   never benchmark or ingest anything from private repos (per-x, profile-x, hardware-x,
   tether, dark-factory). Only **public** models, tested locally, with public task prompts.
2. **Free judge only.** The orchestration/judge/reporting uses a **free** model (hy3:free).
   No paid spend on this pipeline. The model-under-test runs on local Ollama (free compute).
3. **The free model is the orchestrator; Ollama is the compute.** The cron agent (hy3:free)
   does discovery, judging, reporting, and commit. Ollama (127.0.0.1:11434) only *runs* the
   model-under-test. Don't invert this — a 12GB box can't host a judge + a model at once.

## Operating principles
4. **Autonomy over interactivity.** When a run is triggered (cron / subagent / user), execute
   end-to-end: discover → pull → bench → judge → report → delete → commit. **Don't pause for
   clarification mid-run.** If a model is unreachable or errors, record it in the report and
   continue. A run always produces a report, even if partial.
5. **Local-first, VRAM-aware.** Only pull models that fit the GPU. `watcher.max_params_billions`
   (default 14) is the hard ceiling for 12GB. Check headroom before pulling.
6. **Delete after bench.** Every pulled model is `ollama rm`'d after its run (unless
   `--no-delete`). Disk and VRAM stay free for the next cycle. This is the repo's core promise.
7. **Reproducibility.** Each run is timestamped `run_id` (YYYYMMDD_HHMMSS). Raw JSON in `runs/`,
   markdown in `reports/`, both committed so runs are diffable over time.
8. **No `ANTHROPIC_API_KEY`.** Claude (if ever used) routes via OAuth against the Max quota.
   For this public repo, prefer the free model; paid is unnecessary and off-policy.
9. **Honesty in reporting.** Empty/garbage output is reported as such, never scored as correct.
   Uncertain scores marked `±` with reason.

## Repo layout
```
llm-autobench/
├── CLAUDE.md            # this file
├── AGENTS.md            # generic coding-agent conventions
├── README.md            # public overview + lifecycle diagram
├── models/
│   └── registry.yaml    # baseline: models to compare;  watcher: discovery + judge config
├── tasks/               # eval tasks (prompt + scoring + tags)
├── runs/                # raw per-run JSON (committed)
├── reports/             # markdown summaries (committed)
└── scripts/
    ├── run_bench.py     # runner: calls Ollama directly, scores, writes JSON
    └── autobench_cycle.py  # lifecycle: pull → bench → delete → commit
```

## How to run
```bash
# baseline local bench (no pull/delete) — fast smoke test
python scripts/run_bench.py --tier local

# full lifecycle for one model
python scripts/autobench_cycle.py --model qwen3.5:9b

# (autonomous) the cron agent invokes autobench_cycle.py on a schedule,
# does discovery+judging+reporting itself, and commits the result.
```

## How to add a model to the baseline
Edit `models/registry.yaml` → `baseline:` (copy an entry). For `custom:ollama/*`, the harness
strips the `custom:ollama/` prefix and passes the colon-name (e.g. `qwen3.5:9b`) to Ollama's
OpenAI endpoint, which accepts it. **Don't rely on `ollama cp` aliases** — they don't persist.

## How to add a task
Drop `tasks/<name>.yaml`:
```yaml
id: my_task
category: reasoning
requires_frontier: false
prompt: |
  <prompt; {placeholder} for run-time substitution>
expected:
  answer: "5:00"            # optional, for exact/reference scoring
scoring:
  method: rubric-llm       # exact | reference-compare | rubric-llm
  rubric: |
    Award full marks if ... partial if ...
max_tokens: 512
tags: [reasoning]          # which model tags may attempt this
```
The harness skips a (model, task) pair if the model's tags don't intersect the task's tags
(unless `requires_frontier`, which forces premium — not used in this public repo).

## Report schema (reports/<run_id>.md)
1. **Header** — run_id, timestamp, models tested, task count, total cost (local = €0).
2. **Leaderboard** — model | avg score | avg latency | tier | VRAM fit.
3. **Per-model** — strengths/weaknesses per task, notable quotes (≤200 chars).
4. **Lifecycle** — model pulled at, VRAM before/after, deleted: true/false.
5. **Failures** — errored/empty models with the error.

## Conventions
- Commits: `bench:` (manual result runs) or `autobench:` (lifecycle runs).
- Models referenced by Hermes model-string; never hardcode API bases in code.
- `scripts/` stays provider-agnostic — all model/provider knowledge lives in `registry.yaml`.
