# IMPROVEMENTS.md — llm-autobench roadmap

**Status as of 2026-09-07** (M2 judge visibility on branch; M1 #19 merged at `bb904d5`). Grounded in SPEC sections 11-13, DECISIONS.md,
README packaging, and a read of run_bench / nvidia_judge / score_run /
autobench_cycle / aggregate_results / tasks.

**Principle (unchanged):** a benchmark that misreports must be made trustworthy
before it is made bigger (SPEC section 12). Measurement quality before suite ports.

**Public packaging (lina):** the public surface is harness scores / per-run
benchmark reports / scored runs. No medals, ordinal ranks, or crown-a-winner
leaderboard UI until a deliberate greenlight. This file and DECISIONS.md
may describe an internal pathway to a public leaderboard; the README stays
smoke-results framing.

---

## Measurement improvement plan (2026-09-07) — active slice

### Where we are (verified)

| Area | Status at `06baf13` | Notes |
|---|---|---|
| F0 / P0 credibility (extraction, truncation to null, VRAM fail-closed, single judge path, honest Failures) | shipped | Era credibility fixes (`d61170e`); pre-fix runs quarantined |
| F1 loop real (bench pulled model, cycle to judge to aggregate to commit, coverage disclosed, shared-task column) | shipped | One-subject discovery night (#16); baselines via `--baselines-only` |
| N=3 draws + 95% t-CI + sampling-spread table | shipped | N=5 rejected (runtime vs gain); Ollama has no reliable per-call seed |
| Telemetry wired | shipped | `telemetry/` gitignored |
| Public README ranks/medals | removed | First-reader trust pass; smoke results are **not a ranking** |
| Discover `size_band` 6-10B | shipped (M0.1) | `watcher.size_band` 6-10; untested + deterministic pick |
| Exact-only local tag match (SPEC 13.2 / D10) | shipped (M0.2) | Exact tag only; same-size fuzzy removed |
| `_param_from_tag` / F1.3 silent drops | shipped (M0.3) | Suffixes + MoE product; unsized drops logged |
| Execution-based code scoring | shipped (M1) | `python-exec` fixtures via `scripts/code_exec.py`; era `20260907` |
| Judge panel + Cohen kappa | open (M2.2 self-consistency opt-in) | Free-judge + one-GPU constraint; self-consistency is not kappa |
| Agentic tool-call battery (SPEC 13) | specified | Next product question after measurement floor; not ahead of M0-M1 |

### Packaging rules for this pathway (internal)

1. **Public copy** = scored runs + per-run reports + honest aggregate tables that readers can audit. Sorted-by-mean is for scanability, never presented as a ranking (#1 / medals / podium).
2. **Internal docs** (this file, DECISIONS) may say *pathway to public leaderboard* and list **greenlight gates** (below). Implementing those gates does **not** by itself flip the public UI.
3. **Merge gate:** thebotgrok proposes; coder merges only after **lina** explicit OK. No silent README reintroduction of ranks/medals.
4. Nightly contract stays: **one subject LLM per discovery night**; baselines / vision refresh only on `--baselines-only` (no co-bench).

### Priority order — Phase 0-1 residuals and scoring quality first

Do **not** start full HumanEval / MMLU / BBH ports until M0-M1 below are green.
Suite ports without mechanical ground truth on the coding category would scale a
still-soft construct.

#### M0 — Residual Phase 0-1 honesty [S-M] · do first

Closes decisions already locked but not fully reflected in code / docs.

| ID | Fix | Accept |
|---|---|---|
| **M0.1** | Implement watcher.size_band min 6 max 10; selection = untested-in-band, deterministic tie-break; drop prefer-larger | Unit test + one cycle that pulls a new in-band tag, benches it, deletes it |
| **M0.2** | Local-tag match exact only (remove same-size fuzzy); update tests/test_tag_match.py | qwen2.5:7b does not resolve to qwen2.5:7b-instruct; missing tag means pull or honest skip |
| **M0.3** | Harden _param_from_tag / discover drop policy (F1.3 / P2.5): parse sized tags with suffixes; explicitly log drops for unsized tags | Unit test over qwen:latest, codellama:7b-instruct, mixtral:8x7b, qwen:110b |
| **M0.4** | Doc/code claim hygiene: retire stale scoring-is-a-placeholder header in run_bench.py; keep claimed-vs-actual below as pre-fix archive only | First reader of run_bench.py is not told scoring is unimplemented |

#### M1 — Execution-based code scoring [M] · highest measurement unlock

SPEC 5.3 thin path **shipped** for the existing battery item: `code_generation` uses
`python-exec` (fixture execution), not rubric-llm. Full suite ports stay out of scope.

Plan (thin, not a full suite port):
1. Add a mechanical scoring method for Python coding tasks that checks the
   submitted function against fixed fixtures and expected returns.
2. Point code_generation at that method; keep N=3 and CI reporting.
3. Leave rubric-llm for prose and review tasks.
4. Era bump required: measuring the same task differently opens a new ERAS row.

Accept: wrong-but-fluent code scores 0.0 without a judge call; correct code
scores 1.0; truncated or unparseable rows stay null (unscored).

Out of scope for this slice: porting large external coding suites (P2.2 [L]).
Prove the path on the existing battery item first.

#### M2 — Judge visibility / robustness without a second GPU [S-M]

| ID | Fix | Notes |
|---|---|---|
| **M2.1** | Cap persistent JUDGE_ERROR retries; mark judge_error so cron does not burn free-tier RPM forever | **shipped** — `judge_error=true` + skip on later passes (`--retry-judge-errors` to override); see JOURNAL/nvidia_judge_investigation |
| **M2.2** | Optional self-consistency (same judge 3x at temp 0, take median) on rubric rows | **shipped** — `--self-consistency` / `--self-consistency-n`; disclosed as self-consistency, never as inter-rater kappa |
| **M2.3** | Failures / judge-ran status stay derived from outcomes (already true for NVIDIA path — do not regress) | **shipped** — Failures + Judge status derived from outcomes; protect P0.5 |

Multi-provider panel + Cohen kappa (P2.3) stays blocked by free-judge + one-GPU
architecture unless a second free cloud judge appears.

#### M3 — Internal greenlight gates (pathway to public leaderboard)

These are gates, not a promise to ship ranks. Until **lina** signs each row,
public copy stays smoke results / not a ranking.

| Gate | Why it matters |
|---|---|
| M0.1-M0.3 green on nightly | No silent wrong-model / wrong-band measurements |
| M1 mechanical scoring live for coding | Coding cells have ground truth, not only LLM-judge softness |
| Truncation + ingestion + judge_error rates disclosed and stable | Readers can see harness artefacts vs capability |
| N>=3 with CI on every published aggregate cell | Single-draw facts already retired — keep them retired |
| No medals / ordinal ranks / podium language in README or aggregate inject | Packaging contract |
| Explicit lina OK to flip public ranking affordances | Merge gate for the packaging change itself |

#### M4 — After the measurement floor: agentic + established suites

Only after M0-M1 (and preferably M2.1):

1. SPEC 13.3 single-turn tool-call (mechanical; tools_unsupported unscored). **Shipped (this PR)** — separate regime in reports (13.6); not folded into text shared-task avg; no public ranking flip.
2. SPEC 13.4-13.5 multi-turn tools + trajectory sub-scores. *(not this PR)*
3. P2.2 [L] GSM8K + coding-suite slices on the now-proven mechanical / exact paths.
4. Dashboard / trends / post-mortem (P2.6-P2.7) as capacity allows.

Agentic work answers a different question (can it drive tools?) and must stay
a separate regime in reports (SPEC 13.6) — never folded into the text
shared-task average.

### Suggested order (2026-09-07)

1. P0 credibility shipped · P1 legibility + N=3 shipped · one-subject nightly #16 shipped
2. **M0.1-M0.4** residual honesty / discover / tag match
3. **M1** mechanical scoring for code_generation (+ era bump) — shipped
4. **M2.1-M2.2** judge retry cap + optional self-consistency — shipped
5. **M4 / SPEC 13.3** agentic Phase 1 shipped (tool-call); 13.4–13.5 + suite slices next
6. Public ranking UI — only after M3 gates + **lina** greenlight
---

## Archive — claimed-vs-actual (pre-fix snapshot, 2026-07-22)

Historical. All P0 items below shipped 2026-07-22; table preserved so the
audit trail stays readable. Do not treat rows as current defects.

| Remediation | Claimed | Actual pre-2026-07-22 |
|---|---|---|
| F1.1 bench pulled model | yes | done |
| F0.2 Reject truncated output | yes | missing then |
| F0.1 Answer-extraction scorer | yes | substring then |
| F1.4 VRAM guard fail-closed | yes | fail-open then |
| F0.5 Honest derived judge status | yes | hard-coded then |
| F1.2 Cycle calls judge/report | yes | out-of-band then |
| D6 Wire telemetry | planned | dead then |
| F1.3 discover tag parsing | yes | partial (see M0.3) |

## Archive — shipped summary

- P0.1-P0.5 (2026-07-22): truncation to null, answer extraction, VRAM fail-closed, single NVIDIA judge, per-model reports.
- P1.1-P1.3 (to 2026-08-23): aggregate inject, cycle publishes, battery_tags, skip disclosure, shared-task column.
- P2.1 (2026-08-23): samples N, nightly N=3, mean and 95 percent t-CI, sampling-spread.
- P2.4 (2026-07-22): telemetry wired.
- PR 16 (2026-09-06): one subject per discovery nightly; baselines-only for baseline/vision refresh.

## Caveats that remain

| Caveat | Why it survives | What closes it |
|---|---|---|
| Single judge, no kappa | Needs another free cloud judge or local judge on the same 12 GB card | M2.2 optional disclosed self-consistency shipped; true kappa still needs P2.3 |
| Each task is one prompt | N=3 measures sampling noise, not construct depth | M1 on coding + later suite slices |

M1 mechanical scoring for `code_generation` is in-tree (era `20260907`). README numbers remain smoke-test output on a 12 GB box until new current-era
runs accumulate; public packaging stays no ranks/medals until lina greenlights
otherwise.
