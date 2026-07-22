# DECISIONS.md — llm-autobench

Architecture / methodology decisions. Newest first. 2–3 lines each: **decided · why · rejected.**
Full context for the 2026-07-18 batch: `SPEC.md` §11 (audit findings) and §12 (remediation plan).

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
