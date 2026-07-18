#!/usr/bin/env python3
"""Single entry point to score + report an autobench run.

Wraps scripts/nvidia_judge.py (the canonical NVIDIA NIM judge). The autobench
cron agent calls THIS after autobench_cycle.py finishes, so the cron prompt
never has to remember the right judge script.

Usage:
    python scripts/score_run.py runs/<run_id>.json
    python scripts/score_run.py            # defaults to latest run in runs/
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def _latest_run() -> Path | None:
    runs = sorted((REPO / "runs").glob("*.json"))
    return runs[-1] if runs else None


def main() -> int:
    if len(sys.argv) > 1:
        run_file = sys.argv[1]
    else:
        latest = _latest_run()
        if not latest:
            print("No run file given and none found in runs/", file=sys.stderr)
            return 1
        run_file = str(latest)
        print(f"[score_run] defaulting to latest: {run_file}", file=sys.stderr)

    # Delegate to the NVIDIA judge (handles scoring + report writing).
    import nvidia_judge

    nvidia_judge.main.__globals__  # no-op to ensure import side effects
    # Re-run main() with the chosen run file by re-invoking via subprocess so
    # the judge's own arg parsing is authoritative.
    import subprocess

    cmd = [sys.executable, str(REPO / "scripts" / "nvidia_judge.py"), run_file]
    res = subprocess.run(cmd)
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
