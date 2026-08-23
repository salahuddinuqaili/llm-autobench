#!/usr/bin/env python3
"""Nightly unattended entry point for llm-autobench.

Wired to a 21:00 scheduled task. Chains the steps that were previously done by an
agent session -- which is why 80 runs never reached the published aggregate.

    preflight -> cycle -> judge -> aggregate -> commit

Deliberately a wrapper rather than an edit to autobench_cycle.py: that file has
uncommitted work, and an unattended entry point should be separately readable from
the interactive one.

Every stage failure is logged and the run stops. It does not retry around a failure
or continue past one -- a partial run that looks complete is worse than a missing one.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
LOG_DIR = REPO / "telemetry" / "nightly"     # gitignored, stays local
OLLAMA = "http://127.0.0.1:11434/api/tags"
MIN_FREE_GB = 30                              # a model pull needs headroom
# Draws per (model, task). N=1 published single draws as if they were measurements;
# 3 is the smallest N that yields a spread the aggregate can report.
SAMPLES = 3


def log(msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / f"{dt.date.today():%Y%m%d}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args: list[str], stage: str, timeout: int = 5400) -> bool:
    log(f"[{stage}] $ {' '.join(args[1:])}")
    try:
        p = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"[{stage}] TIMEOUT after {timeout}s")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"[{stage}] could not run: {exc}")
        return False
    if p.returncode != 0:
        log(f"[{stage}] FAILED rc={p.returncode}")
        for line in (p.stderr or p.stdout or "").strip().splitlines()[-8:]:
            log(f"[{stage}]   {line}")
        return False
    tail = (p.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        log(f"[{stage}]   {line}")
    return True


def preflight() -> bool:
    """Refuse to start rather than fail halfway. Each check is a real failure seen before."""
    try:
        with urllib.request.urlopen(OLLAMA, timeout=10) as r:
            n = len(json.loads(r.read()).get("models", []))
        log(f"preflight: ollama UP, {n} models present")
    except Exception as exc:
        log(f"preflight: ollama UNREACHABLE ({exc.__class__.__name__}) -- aborting")
        return False

    free_gb = shutil.disk_usage(REPO).free / 1e9
    if free_gb < MIN_FREE_GB:
        log(f"preflight: only {free_gb:.0f} GB free, need {MIN_FREE_GB} -- aborting")
        return False
    log(f"preflight: {free_gb:.0f} GB free")

    sys.path.insert(0, str(SCRIPTS))
    try:
        from nvidia_judge import find_nvidia_key
        if not find_nvidia_key():
            log("preflight: NVIDIA_API_KEY not resolvable -- aborting (judge would fail)")
            return False
    except ImportError as exc:
        log(f"preflight: cannot import judge ({exc}) -- aborting")
        return False
    log("preflight: NVIDIA key resolves")

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        log(f"preflight: {len(dirty.splitlines())} uncommitted file(s) present -- "
            "continuing, but the commit stage will stage only runs/ and reports/")
    return True


def newest_run(before: set[str]) -> Path | None:
    """The run file this cycle produced -- identified by diff, not by mtime."""
    now = {p for p in glob.glob(str(REPO / "runs" / "*.json"))}
    new = sorted(now - before)
    return Path(new[-1]) if new else None


def main() -> int:
    log("=" * 62)
    log("nightly start")

    if not preflight():
        log("nightly ABORTED at preflight")
        return 1

    before = {p for p in glob.glob(str(REPO / "runs" / "*.json"))}

    # --no-report: the cycle can now judge + aggregate + commit itself (P1.2),
    # but nightly runs those as separate logged stages so a failure names which
    # one broke. Letting both do it would judge the same run twice.
    if not run([sys.executable, str(SCRIPTS / "autobench_cycle.py"),
                "--no-report", "--samples", str(SAMPLES)], "cycle"):
        log("nightly ABORTED: cycle failed")
        return 1

    produced = newest_run(before)
    if produced is None:
        log("cycle produced no new run file -- nothing to judge, stopping cleanly")
        return 0
    log(f"cycle produced {produced.name}")

    if not run([sys.executable, str(SCRIPTS / "nvidia_judge.py"), str(produced)], "judge"):
        log("nightly STOPPED: judging failed. The run is on disk but UNSCORED "
            "and must not be aggregated as if it were scored.")
        return 1

    # This is the step that was never automated, and why the README froze in July.
    if not run([sys.executable, str(SCRIPTS / "aggregate_results.py"),
                "--inject", "README.md"], "aggregate"):
        log("nightly STOPPED: aggregation failed")
        return 1

    subprocess.run(["git", "add", "runs", "reports", "README.md"], cwd=REPO,
                   capture_output=True)
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()
    if not staged:
        log("nothing to commit")
        return 0

    msg = f"autobench: {produced.stem} nightly run + judge + aggregate"
    if not run(["git", "commit", "-q", "-m", msg], "commit", timeout=120):
        log("commit failed (a hook may have blocked it) -- run left staged, not pushed")
        return 1

    if not run(["git", "push", "-q", "origin", "HEAD"], "push", timeout=300):
        log("push failed -- commit is local, will go up next run")
        return 1

    log("nightly OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
