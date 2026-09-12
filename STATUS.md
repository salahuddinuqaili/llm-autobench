# STATUS.md — llm-autobench

Operational status of the nightly pipeline. Newest entry first. This file is the
place for "is the harness actually working right now"; `DECISIONS.md` records why
the design is the way it is, and `IMPROVEMENTS.md` tracks planned work.

---

## 2026-09-12 · Nightly 21:00 WinError 2 (bare `ollama`)

**Status: code fix landed. Not re-run. Next proof is the 21:00 task or an explicit `--no-report` cycle.**

11 Sep 21:00: preflight started ollama via the full installer path; `autobench_cycle.py` then spawned bare `ollama` and died in ~4s with `FileNotFoundError: [WinError 2]`. Reproduced this session: PATH without the Ollama dir → bare `ollama` is WinError 2; `procutil.ollama_argv("list")` hits `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` and `ollama list` returns 0 (`qwen3.5:9b` present).

Every cycle `list` / `pull` / `rm` and `run_bench --version` now use that absolute path. Nightly also prepends the exe dir to PATH for children.

Limited 11 Sep midday cycle (`4ec6a40`, `qwen3.5:9b` avg 0.91, judged 45/64) is unchanged. Did not pull models. Did not fire 21:00.

Tests this pass: `tests/test_ollama_resolve.py`, `test_nightly_preflight_imports.py`, `test_install_nightly_task.py`, plus `test_tag_match` / `test_python_exec` / `test_gsm8k_exact` / `test_discover_size_band` / `test_build_temp_registry` / `test_tool_call` — all EXIT:0.

---

## 2026-09-11 · Current state after interpreter retarget (disk check)

**Status: nightly is still PAUSED at preflight. The scheduled-task interpreter
is no longer the blocker. Ollama is not answering on 127.0.0.1:11434.**

Verified this pass by reading disk and probing the host — not by trusting the
kanban card if it disagreed.

### Scheduled task / interpreter

Live `schtasks /query` from this session returned `Access is denied`. Exported
task XML / LIST dumps under `%TEMP%\ab_fix` (`task.xml`,
`titan2_schtasks_before.xml`, `task_after_xml.txt`) all show:

- Name: `llm-autobench nightly (salahuddin)`
- Command: `C:\projects\llm-autobench\.venv\Scripts\pythonw.exe`
- Args: `C:\projects\llm-autobench\scripts\nightly.py`

`.venv\Scripts\pythonw.exe` exists (alongside `python.exe`). The venv has
PyYAML 6.0.3 (`pyyaml-6.0.3.dist-info`). The 08 Sep wrong interpreter
(`C:\Users\salahuddin\.local\bin\python3.14.exe`) is still on disk; it is not
what the task runs.

`pythonw` (not `python`) remains the right host: a console window on the task
would flash, and closing it kills the run (`scripts/procutil.py`).

### Ollama

Queried just now:

- `curl http://127.0.0.1:11434/api/tags` → `{"models":[]}` after a manual
  `ollama serve` (v0.34.0). No models pulled (nightly discover owns that).
- `sc query ollama` → the specified service does not exist (1060). Windows
  build is a user-local app under `%LOCALAPPDATA%\Programs\Ollama\`, not a
  Windows service.
- Binaries: `ollama.exe` + `ollama app.exe`. winget `Ollama.Ollama` 0.34.0
  dropped files at 10:18; daemon was started by default (`Listening on
  127.0.0.1:11434`). Venv preflight then passed (judge answers). Zero models
  on disk until the 21:00 cycle pulls one.

Nightly log `telemetry/nightly/20260911.log` (one line):

`2026-09-11T01:26:35  preflight: ollama UNREACHABLE (URLError) -- aborting`

Nights 08–10 Sep still had Ollama up (7 models, then 2 on the 10th) and aborted
on `NVIDIA_API_KEY not resolvable`. The 11 Sep abort is a different failure:
nothing listening on 11434.

### Judge

Code default is `nvidia/nemotron-3-super-120b-a12b`
(`scripts/nvidia_judge.py`, overridable via `NVIDIA_JUDGE_MODEL`). Not
re-probed this pass. Preflight will not reach the judge until Ollama answers.

### What default / titans were asked to do (sibling cards, not this one)

- **default:** retarget the live scheduled task onto `.venv\Scripts\pythonw.exe`.
  XML dumps already match that.
- **titan1:** loud preflight abort if the interpreter cannot `import yaml`,
  before any Ollama/network work. On disk: `scripts/nightly.py` does that;
  `tests/test_nightly_preflight_imports.py` pins the abort. Pytest was **not**
  run this pass — no pass-count claimed.
- **titan2:** durable repo-local installer so the task cannot regress onto
  `python.exe` or the uv interpreter. On disk: `scripts/install_nightly_task.ps1`.
  This card did not register the task and did not add that script.

This card did not edit `scripts/nightly.py`, did not pull Ollama models, and
did not git commit.

### Still open

- **Ollama is not listening.** 11434 refused; Windows service `ollama` is not
  installed. Binaries exist but the daemon is down. Nightly cannot pass
  preflight until 11434 answers. Do not pull models from this card.
- **Judge liveness at the next night that clears Ollama.** Key resolution failed
  08–10 Sep (the 08 Sep move left the NVIDIA key behind); the later hardening
  reads `%LOCALAPPDATA%\llm-autobench\.env`. Not re-verified here.

---

## 2026-09-11 · Judge outage: retired model, silent for 13 nights

**Status: nightly is PAUSED at preflight. Awaiting a live judge model id.**

### What happened

`meta/llama-3.3-70b-instruct` — the free NVIDIA NIM model this repo judges with —
reached end of life on **2026-08-26T09:00:00Z**. NIM answers a call to it with:

```
HTTP 410  {"title":"Gone","detail":"The model 'meta/llama-3.3-70b-instruct' has
           reached its end of life on 2026-08-26T09:00:00Z and is no longer available."}
```

Nothing in the pipeline said so. The nightly kept running, kept committing, and
kept publishing a mean — computed from the mechanically-scored rows only.

| Run window | Rows | Scored | Unscored |
|---|---:|---:|---:|
| 2026-08-25 (last healthy) | 54 | **54** | 0 |
| 2026-08-26 → 2026-09-06 (12 nights) | 27–33 | **9** each | 18–24 each |
| 2026-09-07 (last run) | 48 | 30 | 18 |

From 26 Aug, every `rubric-llm` task went unscored. The rows that still scored
were the mechanical ones (`exact`, `python-exec`, tool-trajectory), which need no
judge. The 2026-09-07 headline of `0.78` is a mean over mechanical tasks alone.

**No result was ever scored *wrongly*.** Unscored rows were written back
`score=null` and excluded from every mean, per the honesty rule — so the numbers
that exist are real, they just cover a fraction of the battery. What failed was
disclosure: nothing announced how small that fraction had become.

### Why it stayed silent

Three failures stacked, each individually reasonable:

1. **The error was swallowed by an index.** `call_judge` did
   `data["choices"][0]...` on the parsed response. An HTTP error body is valid
   JSON, so the 410 became a `KeyError` whose entire message is `'choices'`. The
   run report showed `ERROR: 'choices'` — which reads like a transient blip, not
   a dead dependency.
2. **`judge_error` throttling worked as designed.** M2.1 caps repeated judge
   retries so a persistent failure cannot burn the free-tier RPM. It did its job
   and made the failure quieter.
3. **A partial run is a successful run.** The lifecycle is built to continue
   through a failing model and still produce a report (CLAUDE.md rule 4). Applied
   to a failing *judge*, that same rule turned a total judging outage into a
   report that looked ordinary.

A second, unrelated break masked it further: on **2026-09-08** the repo moved from
`C:\Users\mulli\projects\llm-autobench` to `C:\projects\llm-autobench`, leaving the
NVIDIA key behind. Preflight then aborted three nights on
`NVIDIA_API_KEY not resolvable`. That abort is the only reason the outage was
noticed at all — the loud failure exposed the quiet one.

### Fixed in this release

| Fix | File |
|---|---|
| API error bodies surface their real `detail` instead of `KeyError 'choices'` | `scripts/nvidia_judge.py` |
| Preflight makes one live judge call and **aborts the night** if it fails | `scripts/nightly.py` |
| Judge model configurable via `NVIDIA_JUDGE_MODEL` — no code edit to swap | `scripts/nvidia_judge.py` |
| README aggregate always prints **judged coverage** (`n/N rows scored`) | `scripts/aggregate_results.py` |
| Key read from a project-owned `.env`, not another tool's config dir | `scripts/nvidia_judge.py` |
| Key passed to `curl` via stdin config, never argv; all error text redacted | `scripts/nvidia_judge.py` |

The last two are a separate hardening. The key used to be read only from Hermes'
`.env`, so a Hermes reinstall or a machine move silently disarmed the judge — that
is what 8 Sep was. And the key was passed as a `curl` argv argument, which meant a
`subprocess.TimeoutExpired` message containing the full command line could be
returned as an `ERROR:` string and **committed to this public repo**. History was
scanned: `git grep nvapi- $(git rev-list --all)` is clean, no key was ever
committed. The path was latent, not exercised — it is now closed at both ends.

### Judge replacement (chosen 2026-09-11)

**`nvidia/nemotron-3-super-120b-a12b`** is now the default, verified live on this
account. Selection was not free: of 69 chat-capable catalog ids, **9** are
invokable here — `/v1/models` is NVIDIA's catalog, not an entitlement list, and
every 70B-class dense candidate (`nemotron-70b`, `nemotron-ultra-253b`,
`mistral-large-2`) returns `404 Not found for account`.

Candidates were scored on this repo's own rubric and parser, good vs garbage:

| Model | latency | garbage @256 tok | garbage @1024 tok |
|---|---:|---|---|
| `nemotron-3-super-120b-a12b` | 2.9s | **1.0** ❌ | 0.0 ✅ |
| `nemotron-3-ultra-550b-a55b` | 2.7s | **1.0** ❌ | 0.0 ✅ |
| `nemotron-3.5-lightning-30b-a3b` | 15.5s | **1.0** ❌ | 0.0 ✅ |

**The near-miss worth recording:** every replacement is a *reasoning* model. It
spends tokens thinking before answering, and the old 256-token judge budget —
sized for a model that replied with a bare float — truncated it mid-thought, so
no verdict was ever emitted. `parse_score` then fell through to "first float
anywhere in the text" and lifted the **1.0 out of the restated rubric**, scoring a
deliberately garbage summarization as perfect. Swapping the judge without
noticing would have been strictly worse than the outage it fixed: the outage
produced honest nulls, this produces confident wrong scores.

Both halves are fixed: the budget is now 1024 (`NVIDIA_JUDGE_MAX_TOKENS`), and
`parse_score` no longer guesses — a stated verdict (`score: 0.4`, `0.4/1`) or a
terse numeric reply is parsed, prose without a verdict returns `None` and the row
is written back unscored. `tests/test_judge_parse_score.py` pins the exact
truncated-reasoning string that mis-scored. Full suite: 18/18 offline tests pass.

### Also broken by the 08 Sep move

The scheduled task was re-registered pointing at `~/.local/bin/python3.14.exe`, a
uv-managed interpreter with **no PyYAML** — which `run_bench.py` and
`autobench_cycle.py` import at module top. Preflight never reached them, so this
never surfaced in a log; it would have crashed the first night the judge worked.
A project venv now exists (`.venv/`, gitignored) with pyyaml 6.0.3, and every
pipeline module imports under it.

### Still open (closed later the same day — see current-state above)

- **The scheduled task still points at the interpreter without PyYAML.** Closed
  2026-09-11: exported task XML now runs `.venv\Scripts\pythonw.exe`. The 08 Sep
  re-registration *did* lose `pythonw` for a uv-managed `python3.14.exe` with no
  PyYAML; that was the crash waiting behind the key/judge aborts. Lesson stands.
  Nightly is still paused, but the remaining blocker is Ollama on 11434, not the
  interpreter.

### The learning

**A dependency that dies quietly is worse than one that dies loudly.** The harness
had honest scoring, honest null handling, and a resilience rule that kept partial
runs alive — and the combination still published thirteen nights of confident,
unrepresentative numbers. Correct per-row behaviour does not add up to a correct
report. Every external dependency now needs a liveness check at preflight and a
coverage figure in the output, so "the judge is gone" can never again look like
"the judge scored fewer tasks tonight".
