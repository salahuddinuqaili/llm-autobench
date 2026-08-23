# GENERATED.md

This repository was built by **directing coding agents** rather than by typing the
implementation. That is the working method behind it, and this file records how, so the
provenance is auditable rather than implied.

## Provenance

| Field | Value |
|---|---|
| Method | Built by directing coding agents through a terminal tool-calling loop (file I/O, git, GitHub CLI) |
| Build date | 2026-07-16 |
| Model(s) used | Routed across providers during the build; not a single fixed model |
| Architecture, task battery and scoring design | Salahuddin Uqaili |
| Repo | https://github.com/salahuddinuqaili/llm-autobench |

## Who decided what

The agents wrote the code. The calls that shaped it were mine: which models are worth
benchmarking, what the task battery measures, how answers are extracted and scored, and
the decision to run the judge on a free hosted model so the local GPU stays free for the
model under test. Those trade-offs are recorded in [DECISIONS.md](DECISIONS.md).

Because the routing changes mid-session, there is no meaningful per-file model signature.
The stable thing to attribute is the method and the design decisions, not the model that
happened to emit a given line.

## Honesty statement

Claims in this repo are backed by executable artifacts: the runner executes against local
Ollama, and reports are generated from real run JSON. No benchmark output is fabricated.

**There is currently no automated test suite and no CI in this repository.** Correctness
rests on the artifacts above being reproducible by running the pipeline, not on a green
badge. An earlier version of this file claimed CI coverage; that was inaccurate and has
been corrected.
