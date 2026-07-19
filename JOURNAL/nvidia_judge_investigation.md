# NVIDIA Judge Investigation & Hardening Report

**Date:** 2026-07-18
**Subject:** `scripts/nvidia_judge.py` — the NVIDIA `meta/llama-3.3-70b-instruct` judge for rubric-llm tasks
**Verdict:** Current direct-curl implementation works and is the right approach. Several concrete hardening gaps remain (timeout crash, no backoff, hardcoded path). Root-cause of the original `hermes -z` failure is confirmed.

---

## 1. Root-Cause Analysis — why `hermes -z --provider nvidia` was unreliable

The original judge invocation was:

```
hermes -z "<prompt>" --provider nvidia --model "meta/llama-3.3-70b-instruct"
```

This was unreliable for **three independent reasons**, all confirmed by inspecting the Hermes CLI and the run logs:

### 1a. `-z/--oneshot` runs the FULL agent loop (tool-misfire)
`hermes -z` is the *oneshot* entry point — it boots the entire agent with the configured toolsets enabled (terminal, file, **web-search**, etc.). It is **not** a raw model call. For a deterministic judge you need a bare completion; instead the agent could decide to call tools, web-search the rubric, and return web results instead of a float. This is the "tool-misfire" symptom.

Confirmed by `hermes -z --help`:
```
usage: hermes [-h] [-z PROMPT] ... [-m MODEL] [--provider PROVIDER] [-t TOOLSETS] ...
```
`-z/--oneshot` is listed alongside `-t TOOLSETS` — the agent loop, with tools, is active.

### 1b. Wrong flag syntax — `--model` is silently ignored
Hermes does **not** accept `--model`. The correct flag is **`-m`** (`[-m MODEL]`). The invocation passed `--model "meta/llama-3.3-70b-instruct"`, which is an unrecognized argument. The CLI either errors out or ignores it and falls back to the agent's default model — never the intended NVIDIA judge. So the judge was frequently not even the model you asked for.

### 1c. No latency/timeout control + 90s+ cold start
`hermes -z` boots the agent runtime (model load, tool setup, provider negotiation) on every call — 90s+ cold, frequently hanging or timing out when driven from a scripted cron loop. There is no `--max-time` equivalent; the caller has no way to bound the call. This is why runs stalled.

### Evidence from the run logs
Before the direct-API fix (`scripts/nvidia_judge.py`, commit `3fd2fd0`), the rubric-llm tasks (`code_generation`, `code_review`) carried:

```json
"score": null,
"score_reason": "JUDGE_ERROR: The api_key client option must be set either by passing api_key to the client or by setting the OPENAI_API_KEY environment variable"
```

(from `runs/20260716_214436.json`, `runs/20260716_214839.json`, etc.). This shows the **old** `judge_report.py` path tried to use the OpenAI SDK with no key (a separate broken path), and the `hermes -z` approach was never reliably producing scores. After the direct-API fix, `runs/20260718_183823.json` shows clean judge output:

```json
"judge": "nvidia/meta/llama-3.3-70b-instruct",
"judge_raw": "0.85",
"score": 0.85
```

**Conclusion:** bypassing Hermes entirely (direct curl to NVIDIA's OpenAI-compatible endpoint) is the correct fix and is confirmed working at ~2s/call vs 90s+/call.

---

## 2. Code Review — `scripts/nvidia_judge.py`

I read the committed file and **empirically executed it** against synthetic runs to verify behavior (I did not modify it).

### 2a. Incremental write-back / re-judging — NOT actually broken (verified)
The task brief flagged a "re-judging already-scored tasks" bug. I tested the exact loop logic:

- Re-run of a file where `B` already scored (`score=0.9`) and `D` still `null` → **only `D` was judged** (1 call). `B` was correctly skipped.
- The skip condition `if r.get("score") is not None: scored.append(r); continue` is correct.
- The write-back `data["results"] = scored + [x for x in results if x not in scored and x.get("score") is None]` uses identity (`x in scored`), and since `scored` holds the *same dict objects* as `results`, identity holds and ordering is preserved. **No duplication/duplication-of-judging bug exists in the current code.**

**The genuine related risk is the opposite:** when `call_judge` returns an error string, `parse_score()` returns `None`, and the task is written back as `score=null`. On the next cron run it will be **retried indefinitely** (every 120 min) with no backoff. If the failure is persistent (bad API key, permanent 4xx), this is a silent infinite-retry loop that burns the 40 RPM budget. See 2c for the fix.

### 2b. Hardcoded `.env` path fragility — REAL
```python
_ENV_PATH = Path.home() / "AppData/Local/hermes/.env"
```
- Hardwires the Windows Hermes config layout. On any Hermes config relocation, `hermes config set`, profile change, or non-Windows host, this silently breaks (`NVIDIA_API_KEY = ""` → immediate `sys.exit(1)`).
- Bypasses Hermes's own key store / `hermes secrets` / environment. It also reads the key by crude line-prefix matching (`line.startswith("NVIDIA_API_KEY=")`), which breaks if the value is quoted or has trailing whitespace after `=`.

**Fix:** resolve the key from, in order: (1) env var `NVIDIA_API_KEY`, (2) `hermes secrets get nvidia_api_key` if available, (3) the `.env` path discovered via `hermes config` / the `HERMES_HOME` env var (not `Path.home()` + literal). Fail with a clear message naming the tried locations.

### 2c. No retry/backoff on 429 / 5xx — REAL
- `call_judge` makes exactly **one** attempt. NVIDIA free tier is **40 RPM**; a burst (e.g. 6 rubric tasks in one run, or re-runs) easily trips `429`. The error JSON (`{"error": {...}}`) has no `choices`, so `data["choices"][0]` raises `KeyError` → caught → returns `"ERROR: ..."` → `score=None` → retried forever (see 2a).
- No `Retry-After` parsing, no exponential backoff, no honoring of NVIDIA's rate limit.

**Fix:** wrap the call in a retry loop (e.g. 4 attempts, base delay 2s, exponential + jitter). On `429`/`5xx`/`5XX` read `Retry-After` if present, else backoff. Treat persistent error as `None` and mark the task `judge_error` so it is not endlessly retried (cap retries per run).

### 2d. Timeout handling — REAL (uncaught crash)
```python
res = subprocess.run(cmd, capture_output=True, text=True, timeout=200)
try:
    data = json.loads(res.stdout)
    ...
except Exception as e:
    return f"ERROR: ..."
```
- `subprocess.run(..., timeout=200)` raises `subprocess.TimeoutExpired` **outside** the `try` block. A slow NVIDIA response (long `code_review` prompt + cold start) that exceeds 180s curl / 200s subprocess **crashes the whole script** — the run aborts, and (worse) the partially-written `scored` list may already be on disk in an inconsistent state.
- `code_review` is explicitly called out in the brief as the long-response task that occasionally exceeds the limit. Input is unbounded (full model response embedded in the prompt); only `max_tokens=20` bounds the *output*.

**Fix:** (1) move the `timeout` inside a `try/except (subprocess.TimeoutExpired, ...)`; on timeout return a sentinel `"TIMEOUT"` so the task is recorded as failed (not crashed) and the run continues; (2) raise `--max-time` to ~300 and `timeout=` to ~320, or stream with a longer bound; (3) optionally truncate very long `response` content before embedding in the prompt (e.g. first 4000 chars + "…").

### 2e. Minor / correctness
- `parse_score` regex `0(?:\.\d+)?|1(?:\.0+)?` correctly accepts `0.0–1.0` and rejects `1.2`. It does **not** handle values like `0` or `1` written without a decimal (e.g. the model returns `1`) — `0` matches via `0`, `1` matches via `1(?:\.0+)?`. OK. But it would also match a `0` embedded in stray text; acceptable for a constrained prompt.
- No validation that NVIDIA returned `finish_reason == "stop"`; a truncated completion is scored as-is. Low risk at `max_tokens=20`.
- The `curl` dependency assumes `curl` is on PATH (true on this host; not portable). Consider `urllib`/ `requests` for portability, or at least check `shutil.which("curl")`.

---

## 3. Corrected Cron Prompt

The paused cron job `7ce664bda386` currently instructs the agent to use `hermes -z` (broken). Replace its `prompt` with the following exact string:

```
Run the llm-autobench autonomous cycle in the llm-autobench repo (workdir: C:\Users\mulli\projects\llm-autobench).

STEPS:
1. Run `python scripts/autobench_cycle.py` — it discovers a new model, pulls it if it fits VRAM, benchmarks locally via Ollama, deletes it, and commits runs/*.json.
2. Identify the NEW run JSON just created in runs/ (newest timestamped file). Run the judge directly (do NOT use hermes -z — it boots the full agent loop and is unreliable):
   `python scripts/nvidia_judge.py runs/<new_run>.json`
   This scores all rubric-llm tasks (changelog_generation, code_generation, code_review, sprint_narrative, summarization, instruction_following) via NVIDIA meta/llama-3.3-70b-instruct (free 40 RPM, direct API) and writes reports/<run_id>.md.
3. Stage and commit BOTH the updated run JSON and the report:
   `git add runs/ reports/ && git commit -m "autobench report: <model> @ <timestamp>"`

CRITICAL: Never invoke `hermes -z` or any hermes subcommand for judging/scoring. Judging is done exclusively by `scripts/nvidia_judge.py`. Do NOT use the anthropic provider (it bills per-token). No interactive input needed.
```

(Replace `<new_run>` / `<model>` / `<timestamp>` at execution time. The cron job's `model`/`provider` fields should also be cleared or left as metadata only — they do not drive the judge anymore.)

---

## 4. Recommendation — direct curl vs SDK/client

**Recommendation: KEEP direct curl (current approach), but harden it. Do NOT move to the `openai` Python SDK as `judge_report.py` did.**

Rationale and trade-offs:

| Dimension | Direct curl (current) | `openai` SDK client |
|---|---|---|
| Latency | ~2s, no SDK import/resolve overhead | +import +client init; fine but heavier |
| Dependencies | only `curl` on PATH | `pip install openai` + version pin; SDK breaking changes (this repo already hit `api_key client option must be set` errors) |
| Reliability as scripted judge | High once hardened (explicit `--max-time`, retry loop) | Medium — SDK version drift caused the earlier `OPENAI_API_KEY` crash in `judge_report.py` |
| Control | Full control of payload, headers, timeout, retries | Convenient but opaque error mapping |
| Portability | Needs `curl`; trivial on Linux/Windows | Pure Python, more portable |

The repo's *own history* already proves the SDK path is fragile: `judge_report.py` used `from openai import OpenAI` and left runs with `JUDGE_ERROR: The api_key client option must be set...`. Direct curl sidesteps SDK version churn entirely.

**Best of both worlds:** keep curl for transport but refactor `call_judge` to use Python's `urllib.request` (stdlib, no `curl` dependency, no SDK) with an explicit retry/backoff wrapper. This removes the Windows-only `curl` assumption *and* the third-party SDK risk. If you prefer a maintained client, use NVIDIA's own `nvidia-genai` / `nim` client — but that adds a heavy dep for a 20-token call and is not worth it here.

**Concrete hardening checklist (do not modify now — logged here):**
1. Key resolution: env → `hermes secrets` → `HERMES_HOME`-aware `.env` (not literal `AppData/Local`).
2. Retry loop: 4 attempts, exp backoff + jitter, honor `Retry-After` on 429, treat persistent error as `judge_error` (no infinite retry).
3. Timeout: wrap `subprocess.run(timeout=)` in `try/except TimeoutExpired`; return `"TIMEOUT"` sentinel; raise `--max-time` to ~300. Truncate long `response` in prompt.
4. Optional: migrate transport to `urllib` to drop the `curl` PATH dependency.
5. Update cron job `7ce664bda386` prompt to the string in §3 (and clear its `model`/`provider` judge fields).

---

## Appendix — what was verified
- `hermes -z --help`: confirmed `-z/--oneshot` = agent loop with `-t TOOLSETS`; model flag is `-m`, not `--model`.
- `git log`: judge path migrated `gemini → nvidia/llama-3.3-70b-instruct` (commit `9e39b24`), then replaced by direct-API `nvidia_judge.py` (commit `3fd2fd0`).
- Run logs: pre-fix `score_reason: JUDGE_ERROR ... OPENAI_API_KEY` (broken SDK); post-fix `judge: nvidia/meta/llama-3.3-70b-instruct` with clean float scores (`runs/20260718_183823.json`).
- Executed `nvidia_judge.py` against synthetic runs: confirmed (a) skip-on-score works (no re-judging of scored tasks), (b) error results written as `null` and retried next run (infinite-retry risk), (c) timeout is uncaught and would crash the run.
