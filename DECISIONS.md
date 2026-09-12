# DECISIONS.md — llm-autobench

Architecture / methodology decisions. Newest first. 2–3 lines each: **decided · why · rejected.**
Full context for the 2026-07-18 batch: `SPEC.md` §11 (audit findings) and §12 (remediation plan).

## 2026-09-12 · NIM 404 is a named error, not Extra data

**Decided:** `decode_judge_response` maps a plain-text `404 page not found` body to a named error and does not retry; reports label `JUDGE_MODEL` as-is (no `nvidia/` prefix).
**Why:** `json.loads` treats `404` as an int then Extra data at column 5, which looked like a parser miss. Pin `meta/llama-3.1-nemotron-70b-instruct` is not on NIM; default `nvidia/nemotron-3-super-120b-a12b` is.
**Rejected:** retrying 404s (same miss, burns RPM); treating Extra data as truncated JSON; hardcoding llama-3.3 in reports/provenance.

## 2026-09-12 · ollama argv is an absolute path

**Decided:** every `ollama` CLI spawn goes through `procutil.ollama_exe` / `ollama_argv`; nightly also prepends that directory to PATH for child processes.
**Why:** Task Scheduler PATH does not include `%LOCALAPPDATA%\Programs\Ollama` even after preflight starts `serve` by full path. Bare `ollama` is WinError 2 in four seconds.
**Rejected:** relying on the user-shell PATH; `cmd /c ollama`; attaching the task to an interactive console.

## 2026-09-11 · A verdict must be stated, never inferred from prose

**Decided:** `parse_score` accepts an explicit verdict (`score: 0.4`, `0.4/1`) or a
terse numeric reply, and returns `None` for prose that never states one; the judge
token budget rises 256 -> 1024 (`NVIDIA_JUDGE_MAX_TOKENS`). New judge default is
`nvidia/nemotron-3-super-120b-a12b` (9 of 69 catalog ids are invokable on this
account; every 70B-class dense one 404s).
**Why:** every available replacement is a reasoning model. At 256 tokens it
truncates mid-thought without a verdict, and the old "first float anywhere"
fallback then read the 1.0 out of the *restated rubric* — scoring a garbage
summarization 1.0. Confident wrong scores are worse than the outage that
prompted the swap, which at least produced honest nulls.
**Rejected:** raising max_tokens alone (fixes today's models, not tomorrow's
verbose one); prompt-engineering the judge into terseness (unenforceable — the
parser is the only place the guarantee can actually hold).

## 2026-09-11 · Preflight proves the judge answers; coverage is always published

**Decided:** one live judge call at preflight, aborting the night on failure, plus a
judged-coverage line (`n/N rows scored`) in every generated README aggregate. Judge
model moves to `NVIDIA_JUDGE_MODEL` so a retirement is a config change, not a patch.
**Why:** `meta/llama-3.3-70b-instruct` was retired 2026-08-26 and the pipeline
published 13 nights of means computed from mechanical rows only — the 410 surfaced
as `KeyError: 'choices'`, which reads as a blip. Per-row honesty (null, excluded)
was already correct; what was missing was any statement of how little was covered.
**Rejected:** scoring through a dead judge (guarantees the same hole); alerting only
in the log (the log is gitignored and nobody reads a healthy-looking night); pinning
a model forever (retirement is the normal case for hosted models, not the exception).
See `STATUS.md`.

## 2026-09-07 · P2.2 thin GSM8K-style exact slice (mechanical path)

Five original grade-school word problems (`gsm8k_s01`..`gsm8k_s05`) scored by the
existing `exact` extractor (labelled Final answer + numeric value). Tag `gsm8k`
added to `battery_tags` and full-text baselines so coverage stays symmetric;
watcher `size_band` 6–10 unchanged. Fixtures are **not** the GSM8K corpus —
provenance in `tasks/fixtures/GSM8K_SLICE_PROVENANCE.md`. **ERA_CUTOFF unchanged:**
adding tasks ≠ re-scoring an existing cell (DECISIONS 2026-08-24); current-era
published aggregate is empty so means are not polluted; shared-task column still
handles partial coverage. Agentic regime untouched; no medals/ranks; no M3 public
ranking flip. Why: prove P2.2-style suite slice on the mechanical exact path after
M0–M2 + SPEC 13.3–13.5, without a full 8.5k dump or download step. Rejected: full
GSM8K port; rubric-llm grading for these items; era bump with nothing to quarantine;
folding into a ranked leaderboard.

## 2026-09-07 · M4 / SPEC 13.4–13.5 multi-turn tools + trajectory sub-scores
Harness gains `multi_turn` / `turn_cap` tasks, `scripts/tool_sandbox.py` (calc, kv_*, list_files, read_file, finish; no network / no escape), `run_tool_loop` with full trajectory in run JSON, and mechanical method `tool-trajectory` with SPEC 13.5 sub-scores (`completed` is the primary row score; others recorded separately). First task: `tool_multiturn_sum` (injects one `read_file` error for error_recovery). `tools_unsupported` stays unscored; agentic remains a **separate regime** in reports (13.6); no medals/ranks; `ERA_CUTOFF` unchanged. Why: measure whether 6–10B models can *drive* tools across turns without judge subjectivity or contaminating the text shared-task average. Rejected: folding into text avg; scoring unsupported as 0.0; collapsing sub-scores into one opaque number; real network/shell tools.

## 2026-09-07 · M4 / SPEC 13.3 thin agentic slice (single-turn tool-call)
Harness gains `tools:` / `expect_tool_call:` on tasks, `call_model(..., tools=)`, mechanical
scoring method `tool-call`, and `tools_unsupported` (unscored, not 0.0) when no `tool_calls`
are emitted. First task: `tasks/tool_weather.yaml`. Agentic rows are a **separate regime** in
`aggregate_results.py` / per-run reports (SPEC 13.6) — excluded from text shared-task Avg;
no medals/ranks; README stays smoke framing. `ERA_CUTOFF` unchanged (adding tasks ≠ new era).
Multi-turn 13.4–13.5 was deferred from the 13.3 PR (now shipped separately). Why 13.3 alone: publish whether 6–10B models can emit a correct single
tool call without conflating "cannot" with "wrong", and without contaminating the text
leaderboard. Rejected: folding tool-call into shared-task mean (coverage error); scoring
unsupported as 0.0 (honesty rule); shipping multi-turn in the same PR (scope / runtime).

## 2026-09-07 · M2 judge visibility / robustness (no second GPU)
Persistent NVIDIA judge failures set `judge_error=true` with `score=null` and are
skipped on later cron passes (override: `--retry-judge-errors`) so free-tier RPM is
not burned forever. Optional `--self-consistency` re-asks the same judge N times at
temperature 0 and takes the median — disclosed as self-consistency, **never** as
inter-rater / Cohen kappa. Failures and Judge status stay derived from outcomes
(P0.5 / M2.3). Why: JOURNAL/nvidia_judge_investigation infinite-retry risk + IMPROVEMENTS M2
without a second free cloud judge. Rejected: scoring judge failures as 0.0; calling
self-consistency kappa; hard-coded "judge ran: yes".

## 2026-09-07 · M1 python-exec mechanical scoring for code_generation
`tasks/code_generation.yaml` uses `scoring.method: python-exec`: extract the submitted
function, run fixed fixtures in a subprocess (`scripts/code_exec.py`), score 1.0/0.0.
Unparseable stays null (unscored). `run_bench.score` and `nvidia_judge` (backfill / never
LLM) wired; era bumped to `20260907` (`python-exec code_generation`). Why: SPEC §5.3 /
IMPROVEMENTS M1 — coding cells need ground truth, not only rubric-llm softness.
Rejected: full HumanEval suite port this slice; scoring unparseable as 0.0 (conflates
missing extract with wrong code); leaving judge on coding rows after retarget.

## 2026-09-07 · M0 residual honesty coded (size_band, exact tags, param parse, header)
Implemented M0.1–M0.4 from IMPROVEMENTS: `watcher.size_band` 6–10 with untested +
deterministic pick (no prefer-larger); local-tag match exact-only; hardened
`_param_from_tag` (suffixes + MoE product) with explicit unsized drops; retired the
stale "scoring is a placeholder" `run_bench.py` header. Why: 2026-08-24 decisions were
locked but code still preferred largest-fit and same-size fuzzy tags (D10 risk).
Rejected: leaving size-strict fuzzy as a half-fix; documenting without coding.

## 2026-09-07 · Measurement-quality backlog before new suite ports
Active plan lives in `IMPROVEMENTS.md` (M0–M4). Why: Phase 0–1 credibility and N=3 are shipped; residual discover/tag honesty and mechanical scoring for `code_generation` still limit construct validity. Rejected: jumping to SPEC §13 agentic or full suite ports before closing M0–M1.

## 2026-09-07 · Public copy stays harness scores until packaging OK
Public README/aggregate stay smoke-results framing (no medals or ordinal ranks) until deliberate OK. `IMPROVEMENTS.md` may describe internal gates (M3). Rejected: changing public ranking affordances in the same change as the measurement-plan docs.

## 2026-09-06 · One subject LLM per discovery nightly cycle
`build_temp_registry` for discover / `--model` keeps **only** the subject — no baseline
co-append. Why: co-running baselines on every discovery night burned VRAM/time on already-
measured models, blurred the pull→bench→delete subject lifecycle, and made each night's
run a multi-model stew instead of one new measurement. Baselines (and vision refresh) stay
on the explicit `--baselines-only` path, which never `ollama rm`s baseline tags. Rejected:
keeping VRAM-trimmed co-append (still couples discovery to baseline freshness); deleting
baselines after a mixed night (breaks the "baselines stay local" contract).

## 2026-08-24 · Discovery targets a 6–10B band, not the largest model that fits
`watcher.size_band: {min: 6, max: 10}`; `max_params_billions: 14` stays as the absolute VRAM guard;
selection prefers models never benchmarked within the band, tie-broken deterministically. Why: a
12GB box is not interesting as a home for the biggest model it can barely hold — it is interesting
as a home for one small enough to be useful repeatedly, and 6–10B is where local agentic work is
plausible. Rejected: strict 7–9B (candidate pool runs dry and nights are skipped); keeping the 14B
ceiling with a mere preference (dilutes the focus and keeps re-selecting the same 12B tag).

## 2026-08-24 · Local-tag matching is EXACT; family matching is removed
`model_is_available_locally()` returns a tag only on exact match. Why: family matching resolved the
discovered `gemma4:12b` to the already-local `gemma4:e4b`, so no pull and no delete happened and the
baseline was re-benchmarked in its place — and since the discovered tag never reached `runs/`, it was
never marked tested, so the substitution repeated every night (observed 2026-08-23 and 2026-08-24,
logged as D10). In a 6–10B band it would get worse: `qwen3.5:8b` → local `qwen3.5:9b`. Rejected:
family match plus a size check (still guesses at equivalence); leaving it (livelocks the core
promise of the repo). Accepted cost: may re-pull `qwen2.5:7b` when `qwen2.5:7b-instruct` is local —
correctness over disk, and `delete_after_bench` reclaims it.

## 2026-08-24 · Agentic tasks are scored mechanically, never by the judge
Trajectory sub-scores (`completed`, `tool_choice`, `efficiency`, `error_recovery`,
`no_hallucinated_tools`, `terminated`) are computed in code and recorded separately rather than
collapsed into one number. Why: tool use has ground truth — the right call with the right arguments
either happened or it did not — so a judge would add subjectivity to the one category that does not
need it, plus free-tier load. Rejected: judging the whole transcript (makes agentic scores as soft as
the rubric ones); mechanical trajectory plus a judged final answer (reintroduces variance into half
the score for little gain).

## 2026-08-24 · A model with no tool support is unscored, not zero
Absence of `tool_calls` is flagged `tools_unsupported` and left unscored, mirroring `truncated` and
`ingestion_failed`. Why: "cannot use tools" and "used tools wrongly" are different findings, and
publishing the first as a 0.0 is the inverse of the honesty rule (CLAUDE.md 9) — the same defeat
pattern already fixed twice in this repo. Rejected: scoring 0.0 (conflates capability with absence);
excluding such models from agentic tasks entirely (hides a real and useful finding about 6–10B
models).

## 2026-08-24 · Adding tasks does not open a new era
`ERA_CUTOFF` stays `20260823` when agentic tasks land. Why: an era exists to separate runs where the
*same thing was measured differently*. New tasks leave existing task measurements untouched, and
per-task means plus the shared-task column already handle models with differing coverage. Rejected:
bumping on any battery change (would reset the published aggregate to zero runs for no methodological
gain, having just refilled it).

## 2026-08-23 · Eras are a table, not a constant; era 3 opens on the multi-sample harness
`aggregate_results.py` now carries an `ERAS` list (dates + label + why-separated) and derives
`ERA_CUTOFF` from its last entry, which the README renders as an era-history table. Why: bumping a
bare cutoff constant silently erased the existence of the runs it excluded — a reader could not tell
whether 80 runs were deleted or quarantined. Rejected: keeping the single constant with a hand-written
README note (drifts); back-filling old runs through the new harness (they were produced by a different
measurement — re-scoring them would invent history).

## 2026-08-23 · N=3 draws per (model, task) is the default for unattended runs
`run_bench.py --samples N` (nightly passes 3). Why: N=1 was structural, not a setting — there was no
sample loop at all, so every published cell was a single draw presented as a measurement, with no way
to distinguish a capable model from a lucky one. 3 is the smallest N that yields a reportable spread
on a 12GB box. Rejected: N=5 (run time roughly doubles for a marginally tighter interval on a battery
whose real limit is 11 items); seeding for determinism (Ollama exposes no reliable per-call seed, and
a fixed seed would hide exactly the variance being measured).

## 2026-08-23 · Shared-task column ADDED alongside the overall average, not instead of it
The leaderboard now shows both a whole-coverage `Avg` and a `Shared-task avg` over the tasks every
general model attempted. Why: the 2026-08-15 entry rejected a shared-task-only column because it
hid data while the underlying tag gate was still unfair. The gate is fixed; a second column is now
additive disclosure rather than a substitute for the fix. Rejected: replacing `Avg` (hides coverage
differences); dropping vision-only models from the board (they are real results, just not comparable
— they are marked and excluded from the shared column instead).

## 2026-08-23 · Truncation is counted from `done_reason`, never estimated from response text
The aggregate reads recorded `truncated` / `attempts` fields. Why: it had been guessing truncation
from trailing punctuation and publishing "~2 of 143 zero-scores are truncated" — a figure that could
not be right in principle, since a truncated row is scored `null` and is therefore never in the
zero-score pool. Real figures for the same data: 77 retried at 2x budget, 46 still truncated (unscored).
Rejected: keeping the heuristic as a cross-check (a wrong number next to a right one is not a check).

## 2026-08-23 · The cycle publishes; nightly stays the logged wrapper
`autobench_cycle.py` now runs judge -> aggregate -> commit itself (P1.2/F1.2), and `nightly.py` passes
`--no-report` so the same run is not judged twice. Why: judging lived in an agent session, which is
why 80 runs of data never reached the README. Rejected: moving judging wholly into nightly (leaves the
interactive path publishing nothing); letting both run it (double judge calls on a free-tier quota).

## 2026-08-15 · Thinking OFF (`think: false`) is the benchmark's standard condition
All Ollama calls send `think: false`, disclosed in every report. Why: measured, thinking broke
the harness two ways — Ollama DROPS the attached image when thinking is on (gemma4:e4b answered
"no image provided" and scored 0.00 for a harness artefact), and thinking does not always
terminate (qwen3.5:9b spent 4730+ words on `arithmetic_reasoning` and was still truncated at an
8192 budget, vs 484 tokens / 16s with thinking off). Rejected: keeping thinking on and publishing
permanent nulls; raising budgets (8192 still failed); running both modes (doubles run time —
revisit as a separate reported axis).

## 2026-08-15 · Ingestion failure is reported separately from a wrong answer
A response to an image task that claims no image was supplied is flagged `ingestion_failed` and
left unscored, not graded as a capability result. Why: the inverse of the honesty rule (CLAUDE.md 9)
was live — gemma4:e4b's intermittent "you have not provided an image" was published as
`vision_ocr 0.06`, i.e. a harness/ingestion failure presented as poor OCR. Rejected: scoring the
non-answer 0.0, which conflates "cannot ingest" with "read it wrong" — very different signals for
a reader choosing a model.

## 2026-08-15 · Two benchmark tasks were mis-specified and have been corrected
`vision_ocr` asked for "the square in the top-left corner" while the red square is in the
TOP-RIGHT, and its rubric awarded marks for answering "red" — rewarding agreement with a false
premise over accurate perception. `arithmetic_reasoning` was ambiguous between a 12- and 24-hour
clock (qwen3.5:9b reasoned correctly to 5:00, answered "17:00", and was marked wrong). Both now
ask non-leading, unambiguous questions. Why: a task that rewards sycophancy measures the wrong
thing. Rejected: keeping them for historical comparability — the pre-fix aggregate is quarantined
anyway.

## 2026-08-15 · Tag gate biases the leaderboard; baselines get the full text battery
`build_temp_registry` gives DISCOVERED models 11 broad tags (all 9 text tasks) while BASELINE
models carry narrow hand-written tags — `qwen3.5:9b` attempted only 4, and they are the hardest
in the battery (no easy writing tasks). The public leaderboard therefore compared a 9-task average
against a 4-task average as though they were the same quantity. Baseline tags now match the
battery. Why: this reorders the rankings; it is a correctness bug, not a fairness nicety.
Rejected: a "shared-task only" column (hides data); leaving discovered/baseline asymmetric.

## 2026-07-22 · P0 credibility sprint: the 2026-07-18 audit fixes actually landed
Implemented P0.1-P0.5 (truncation guard, answer-extraction scorer, per-model report
grouping, VRAM fail-closed, single judge path), which were logged "decided" on 2026-07-18
but never reached the code. Each shipped with its acceptance test run against the real
failing case. Rejected: scaling the suite (Phase 2) on top of an untrustworthy harness.

## 2026-07-22 · Truncation: one retry at 2x budget, then score null (never 0.0)
On `done_reason == "length"`, re-run once at 2x `max_tokens`; if still cut off, score null
(unscored), not 0.0. Why: a truncated chain-of-thought is a non-answer, not a wrong answer
(the old substring scorer even read a mid-thought "5:00" as a fake 1.0). Rejected: unbounded
retries (cost) and scoring truncated scratch-work as 0.0.

## 2026-07-22 · Truncated rows must skip the JUDGE stage too (caught in adversarial review)
`run_bench` marks truncated rows `score=null`, but `nvidia_judge` skipped only rows where
`score is not None`, so the 70B judge re-scored the cut-off CoT (~0.0) and silently defeated
the guard (and made the row both "scored" and a Failure). Fix: skip rows where `truncated`.
Found by a multi-agent review of the diff, which also flagged scorer edge cases (see below).
Rejected: judging any `score is None` row without checking `truncated`.

## 2026-07-22 · Score the labelled "Final answer" line, and compare numbers by value
Exact scoring extracts from the text after the last "Final answer:" (falling back to the whole
response), and numeric answers compare by float value with boundary-guarded tokens. Why: a
correct intermediate value + a WRONG final answer must score 0.0, "720" == "720.0", and "720"
must not be pulled from "x720y"/"7200". Rejected: scanning the whole response; string-equality
on numbers. (All from adversarial-review findings, each reproduced then fixed + unit-tested.)

## 2026-07-22 · Reasoners: 2048-token budget + "final answer on the last line"
Bumped arithmetic/logical to 2048 and instruct the model to end with "Final answer: X".
Why: qwen3.5:9b spends its budget on CoT; a labelled final line makes extraction reliable
and gives room to answer. Rejected: 1024 (too small) and extraction with no answer anchor.

## 2026-07-22 · Answer-extraction is type-aware (time / number / string)
Exact scoring extracts answer tokens and matches by type: normalized HH:MM, word-boundary
numbers, or word-boundary strings. Why: "5:00" must not match inside "15:00", yet "05:00"
must still pass. Rejected: raw `expected in response` substring containment.

## 2026-07-22 · Deleted the legacy judge_report.py (one judge path)
Removed the OpenRouter + hard-coded "Free judge: yes" generator; `nvidia_judge.py` (via
`score_run.py`) is now the only report path, with a Failures section derived from run
outcomes. Rejected: keeping it as a fallback shim (it contradicted the real NVIDIA path).

## 2026-07-22 · Wired telemetry.py; gitignore its output
`run_bench.py` now records tokens / tok-per-s / VRAM / cost per call (dead code before). The
`telemetry/` jsonl is runtime data, so it is gitignored; the leaderboard stays derived from
committed `runs/`. Rejected: leaving telemetry dead, and committing the per-run logs.

## 2026-07-22 — All-time results view + auto-injected README leaderboard
Aggregate every `runs/*.json` via `scripts/aggregate_results.py` (deterministic, stdlib-only) into a
leaderboard / task-difficulty / model×task matrix + honest caveats, injected into README between
RESULTS markers. Why: 100+ runs had no aggregate view; per-run reports can't show trends or fair
cross-model comparison. Rejected: an LLM-summarized section (non-reproducible) and a dashboard/DB
(overkill; paid infra is off-policy for this public repo).

## 2026-07-18 — Credibility-first remediation sequencing
Fix scoring, truncation, judge visibility, and the `bench()`/report wiring (Phase 0–1) **before**
porting HumanEval/MMLU/reward models (Phase 2). Why: a self-audit found the flagship run reports a
false-positive `1.00`; a benchmark that misreports must be made trustworthy before it is scaled.
Rejected: proceeding to SPEC §10 Phase B (new suites) on top of an untrustworthy harness.

## 2026-07-18 — Answer-extraction scoring, not substring containment
Score exact tasks by extracting the final answer + word-boundary match. Why: `expected in response`
matched `5:00` inside `15:00` on a truncated, answer-less response (a fake `1.00`).
Rejected: raw `expected in response` (`run_bench.py:92`).

## 2026-07-18 — Reject truncated responses; give reasoning models room to answer
Treat `finish_reason == 'length'` as a non-answer (score 0 / re-run) and raise the token budget.
Why: qwen spent all 512 tokens on chain-of-thought and never stated an answer on any task.
Rejected: scoring truncated scratch-work as if it were a complete answer.

## 2026-07-18 — Report status is derived from outcomes, never hard-coded
"Judge ran?", "Failures", and "Errors" must reflect real run outcomes, incl. `score_reason`.
Why: the report said `Free judge: yes` / `Failures: None` while the judge errored on half the tasks.
Rejected: static `Free judge: yes` strings and a Failures section that only reads `error`.

## 2026-07-18 — The cycle must benchmark the model it pulls
`bench()` injects the discovered/pulled tag into the run set, and the cycle calls `judge_report.py`.
Why: `bench(model)` ignored its arg and re-ran the static baseline, so pull→delete was wasted work
and unattended runs were never scored or reported.
Rejected: benchmarking the static baseline as a proxy for the discovered model.

## 2026-07-18 — VRAM guard fails closed
On `nvidia-smi` failure, **skip** the pull (don't allow it); stop biasing discovery to the 14B ceiling.
Why: fail-open allowed an oversized pull onto a shared 12GB box, OOM-ing mid-bench after disk spend.
Rejected: `return True` on nvidia-smi failure (`autobench_cycle.py:62-63`).
