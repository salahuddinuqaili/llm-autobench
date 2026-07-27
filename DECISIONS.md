# DECISIONS.md — llm-autobench

Architecture / methodology decisions. Newest first. 2–3 lines each: **decided · why · rejected.**
Full context for the 2026-07-18 batch: `SPEC.md` §11 (audit findings) and §12 (remediation plan).

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
