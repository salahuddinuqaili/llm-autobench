# AGENTS.md — llm-autobench

For **any coding agent** (Hermes, Codex, Claude Code, OpenCode) in this repo.

## What this repo is
A **PUBLIC** autonomous LLM-benchmarking pipeline: discover new open models → pull locally →
bench → report → delete. It runs unattended ("dark factory" pattern: it runs, reports, stops).

## Hard rules
1. **Public repo.** No secrets, no private-repo data (per-x, profile-x, hardware-x, tether,
   dark-factory). Only public models + public task prompts.
2. **Free judge.** Orchestration/judging/reporting uses a free model (hy3:free). No paid spend.
   The model-under-test runs on local Ollama — that's the only heavy compute.
3. **Finish the run.** A triggered benchmark produces a report even if some models fail.
   Skip-and-continue; never block on a missing model or clarification mid-run.
4. **Delete after bench.** `ollama rm` the pulled model when done (unless `--no-delete`).
5. **VRAM cap.** Only pull models ≤ `watcher.max_params_billions` (default 14 for 12GB).
6. **No `ANTHROPIC_API_KEY`.** Premium routing (if ever) uses OAuth, not per-token billing.
7. **Don't fabricate.** Empty/garbage output reported as such, not scored correct.

## Where things live
- `models/registry.yaml` — `baseline:` (comparison models) + `watcher:` (discovery/judge config).
- `tasks/*.yaml` — eval tasks.
- `runs/` — raw JSON per run (committed).
- `reports/` — markdown summaries per run (committed).
- `scripts/run_bench.py` — runner (Ollama direct).
- `scripts/autobench_cycle.py` — lifecycle (pull/bench/delete/commit).

## Common agent tasks
- **Add a baseline model:** edit `registry.yaml` → `baseline:`. For `custom:ollama/*`, the
  harness strips the prefix and passes the colon-name to Ollama (e.g. `qwen3.5:9b`). Don't use
  `ollama cp` aliases — they don't persist across Ollama restarts.
- **Add a task:** create `tasks/<name>.yaml` (prompt + `scoring.method` + `tags`).
- **Run:** `python scripts/run_bench.py --tier local` (smoke), or
  `python scripts/autobench_cycle.py --model <tag>` (full lifecycle).
- **Extend the harness:** keep model/provider knowledge in `registry.yaml`; the script must
  not hardcode base URLs or keys.

## Model-string note (learned the hard way)
Ollama names contain a colon (`qwen3.5:9b`). Hermes's `/model` command mis-parses these on the
first colon, but this harness does its own slug split and passes the colon-name to Ollama's
OpenAI endpoint, which accepts it. Use the real name (`custom:ollama/qwen3.5:9b`) in the
registry. Qwen3.x reasoning models emit their answer in the `reasoning` field and may leave
`content` empty — the harness reads `content` then falls back to `reasoning`.
