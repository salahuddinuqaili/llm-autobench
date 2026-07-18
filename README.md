# llm-autobench

**An autonomous, local-first LLM benchmarking pipeline — and a public portfolio piece.**

`llm-autobench` watches for new open-source model releases, **pulls** them onto a
local GPU, **benchmarks** them against a fixed task battery, **reports** the results,
then **deletes** the model to keep the machine free. The whole cycle runs unattended.

> Public repo. No secrets, no private data. Only **public** models are benchmarked,
> and the judge is a **free NVIDIA NIM model** (Llama 3.3 70B, 40 RPM) — keeps the
> local GPU free for the model-under-test. This satisfies the "free cloud = public
> repos only" rule by design.

## The autonomous lifecycle

```
   ┌──────────────────────────── Hermes cron (model: hy3:free, FREE) ───────────────────────────┐
   │                                                                                              │
   │  1. discover   find a new model tag (watcher) ── fits 12GB? (≤ ~14B) ── yes ─┐               │
   │  2. pull       `ollama pull <model>`                                         │               │
   │  3. bench      run_bench.py → Ollama runs the model locally (heavy compute)  │               │
   │  4. judge      free NVIDIA NIM model scores outputs vs task rubrics (Llama 3.3 70B)     │               │
   │  5. report     write reports/<run_id>.md (leaderboard + cost)               │               │
   │  6. delete     `ollama rm <model>`  (free disk/VRAM)                          │               │
   │  7. commit     git commit runs/ + reports/  → push to public GitHub          │               │
   └─────────────────────────────────────────────────────────────────────────────┘               │
                                                                                                  │
   Local Ollama (127.0.0.1:11434) does stages 3 only. Everything else is light enough for FREE.  │
```

The **free NVIDIA NIM model is the judge** (steps 1, 4, 5, 7). The **local GPU does
only step 3** (running the model-under-test). That separation is the point: a 12GB box
can't host a judge *and* a model-under-test, so the judge lives on free cloud (NVIDIA
Llama 3.3 70B, 40 RPM — no credit cap). The orchestrating cron agent itself runs on the
same free NVIDIA model.

## Quick start (manual)
```bash
# benchmark the baseline local models (no pull/delete)
python scripts/run_bench.py --tier local

# run one model through the full lifecycle (pull → bench → delete → commit)
python scripts/autobench_cycle.py --model qwen3.5:9b
```

## Layout
- `models/registry.yaml` — `baseline:` known models (comparison refs) + `watcher:` discovery config (size cap, judge model, delete-after-bench).
- `tasks/*.yaml` — eval tasks (prompt + scoring method + tags).
- `runs/` — raw per-run JSON (one per `run_id`), committed for diffable history.
- `reports/` — markdown summaries (leaderboard + cost split), one per `run_id`.
- `scripts/run_bench.py` — the benchmark runner (calls Ollama directly).
- `scripts/autobench_cycle.py` — the lifecycle orchestrator (pull/bench/delete/commit).

## Constraints (by design)
- **12GB VRAM ceiling** — the watcher only pulls models ≤ `max_params_billions` (default 14).
- **Public only** — no per-x / private-repo data ever enters this repo.
- **Free judge** — scoring uses a free NVIDIA NIM model (Llama 3.3 70B, 40 RPM); no paid spend on this public pipeline.

## Conventions
See `CLAUDE.md` (Claude Code) and `AGENTS.md` (generic agents) for operating rules.
Commits are prefixed `bench:` (result runs) or `autobench:` (lifecycle runs).
