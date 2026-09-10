# STATUS.md — llm-autobench

Operational status of the nightly pipeline. Newest entry first. This file is the
place for "is the harness actually working right now"; `DECISIONS.md` records why
the design is the way it is, and `IMPROVEMENTS.md` tracks planned work.

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

### Still open

- **A live judge model has not been chosen.** Every 70B-class candidate probed on
  this account returned `404 Not found for account`
  (`nvidia/llama-3.1-nemotron-70b-instruct`, `nvidia/llama-3.1-nemotron-ultra-253b-v1`,
  `mistralai/mistral-large-2-instruct`). `/v1/models` lists 80 ids, but that is a
  catalog, not this account's entitlements. Needs an entitlement check against a
  valid key before the nightly can resume scoring rubric tasks.
- Until then preflight aborts every night by design. Mechanical scoring still
  works; running with a dead judge would only reproduce the hole this entry is about.

### The learning

**A dependency that dies quietly is worse than one that dies loudly.** The harness
had honest scoring, honest null handling, and a resilience rule that kept partial
runs alive — and the combination still published thirteen nights of confident,
unrepresentative numbers. Correct per-row behaviour does not add up to a correct
report. Every external dependency now needs a liveness check at preflight and a
coverage figure in the output, so "the judge is gone" can never again look like
"the judge scored fewer tasks tonight".
