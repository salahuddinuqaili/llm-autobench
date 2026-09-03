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

import argparse
import ctypes
import datetime as dt
import glob
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import procutil

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
LOG_DIR = REPO / "telemetry" / "nightly"     # gitignored, stays local
OLLAMA = "http://127.0.0.1:11434/api/tags"
MIN_FREE_GB = 30                              # a model pull needs headroom
# Draws per (model, task). N=1 published single draws as if they were measurements;
# 3 is the smallest N that yields a spread the aggregate can report.
SAMPLES = 3

# --- power management, for the wake-at-21:00-then-sleep-again pattern ----------
# A machine woken by a WAKE TIMER is in an "unattended" state and Windows will
# put it straight back to sleep once the triggering task returns -- and can do so
# mid-run if nothing holds a power request. ES_SYSTEM_REQUIRED is that request.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
# Do not suspend a machine somebody is sitting at. LogonUI presence is NOT a
# reliable lock signal on this box (it lingers while unlocked), so the guard is
# real user input: keyboard/mouse within this many minutes means stay awake.
IDLE_BEFORE_SLEEP_MIN = 10


def log(msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / f"{dt.date.today():%Y%m%d}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def keep_awake(on: bool) -> None:
    """Hold (or release) a system power request for the duration of the run."""
    try:
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if on else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as exc:  # noqa: BLE001 - never let power management kill a run
        log(f"keep-awake: could not set execution state ({exc})")


def idle_minutes() -> float:
    """Minutes since the last real keyboard/mouse input. -1.0 if unreadable."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return -1.0
        delta = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        # GetTickCount wraps at ~49.7 days; a negative delta means it wrapped, and
        # guessing would be worse than admitting we do not know.
        return -1.0 if delta < 0 else delta / 60000.0
    except Exception:  # noqa: BLE001
        return -1.0


WAKE_GRACE_SEC = 180

def _last_wake_event():
    """Return {time: datetime (UTC), source: str} or None. Fail closed.

    Microsoft-Windows-Power-Troubleshooter Event 1 lives in the System log
    on this box (verified on Sapne), not a separate Operational channel.
    """
    try:
        p = procutil.run(
            ["wevtutil", "qe", "System",
             "/q:*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and (EventID=1)]]",
             "/c:1", "/rd:true", "/f:text"],
            capture_output=True, text=True, timeout=15,
        )
        out = (p.stdout or "").strip()
        if p.returncode != 0 or not out:
            return None
        t = None
        src = ""
        for line in out.splitlines():
            s = line.strip()
            if s.lower().startswith("date:"):
                raw = s.split(":", 1)[1].strip().replace("?", "")
                # wevtutil: 2026-09-03T09:43:23.0230000Z
                raw = raw.replace("0000Z", "Z") if raw.endswith("0000Z") else raw
                try:
                    t = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    t = None
            if s.lower().startswith("wake source:"):
                src = s.split(":", 1)[1].strip().strip(chr(0))
        if t is None:
            return None
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        if not src:
            src = _powercfg_lastwake_source() or ""
        return {"time": t, "source": src}
    except Exception:
        return None


def _powercfg_lastwake_source() -> str:
    """Source-only fallback. No timestamp — caller still needs Event 1 time."""
    try:
        p = procutil.run(
            ["powercfg", "/lastwake"],
            capture_output=True, text=True, timeout=10,
        )
        if p.returncode != 0:
            return ""
        return (p.stdout or "").strip()[:800]
    except Exception:
        return ""


def this_run_woke_machine(started: dt.datetime) -> bool:
    """True only if a wake-timer / scheduled-task resume happened just before start.

    Fail closed (False): unreadable event, unknown time, unknown source, too old,
    or source is a device/keyboard/mouse/power button.
    """
    info = _last_wake_event()
    if not info or not info.get("time"):
        log("power: last wake unreadable -- treating as already awake")
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    age = (started - info["time"]).total_seconds()
    src = info.get("source") or ""
    log(f"power: last wake {age:.0f}s ago source={src!r}")
    if age < -30 or age > WAKE_GRACE_SEC:
        return False
    if not src:
        return False
    low = src.lower()
    if not any(k in low for k in ("wake timer", "timer", "scheduled", "task scheduler")):
        return False
    if "device" in low and "timer" not in low:
        return False
    return True


def maybe_sleep(enabled: bool, woke: bool) -> None:
    """Suspend after the run only if this task woke the PC from sleep.

    Already-S0 at start: never suspend, ignore idle (a long bench always looks
    idle). Wake-from-sleep path keeps the idle guard so a user who sat down
    mid-run is not put to sleep.
    """
    if not enabled:
        return
    if not woke:
        log("sleep-when-done: machine was already awake at start -- staying awake")
        return
    idle = idle_minutes()
    if idle < 0:
        log("sleep-when-done: idle unreadable -- staying awake")
        return
    if idle < IDLE_BEFORE_SLEEP_MIN:
        log(f"sleep-when-done: last input {idle:.1f} min ago -- staying awake")
        return
    log(f"sleep-when-done: this run woke the machine and idle {idle:.0f} min -- suspending to S3")
    keep_awake(False)
    try:
        ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
    except Exception as exc:  # noqa: BLE001
        log(f"sleep-when-done: suspend failed ({exc}); left awake")


def run(args: list[str], stage: str, timeout: int = 5400) -> bool:
    log(f"[{stage}] $ {' '.join(args[1:])}")
    try:
        p = procutil.run(args, cwd=REPO, capture_output=True, text=True, timeout=timeout)
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


def wait_for_network(timeout_s: int = 90) -> bool:
    """Wait for outbound connectivity, bounded. Returns False if it never arrives.

    A run started by a WAKE TIMER begins seconds after resume, while the NIC is
    often still reassociating. Discovery scrapes ollama.com almost immediately, so
    without this the first network call of a wake-from-sleep run is the one most
    likely to fail -- and it would look like "no candidates" rather than "no
    network". Cheap insurance for a case that only happens unattended.
    """
    import time
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            urllib.request.urlopen("https://ollama.com/library", timeout=10).read(64)
            if attempt > 1:
                log(f"preflight: network up after {attempt} attempt(s)")
            return True
        except Exception:  # noqa: BLE001 - any failure means "not yet"
            time.sleep(5)
    log(f"preflight: no outbound network after {timeout_s}s")
    return False


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

    if not wait_for_network():
        log("preflight: network unreachable -- aborting (discovery and the judge "
            "both need it; better to skip a night than half-run one)")
        return False

    dirty = procutil.run(["git", "status", "--porcelain"], cwd=REPO,
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
    ap = argparse.ArgumentParser(description="unattended llm-autobench run")
    ap.add_argument("--sleep-when-done", action="store_true",
                    help="suspend afterwards only if this task woke the PC from sleep "
                         "(never if it was already awake at start)")
    args = ap.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    woke = this_run_woke_machine(started)
    log(f"power: this_run_woke_machine={woke}")

    # Hold the machine awake for the WHOLE run. Without this a wake-timer wake can
    # return to sleep mid-benchmark, which would look like a mysteriously truncated
    # nightly rather than a power event.
    keep_awake(True)
    try:
        rc = _run_pipeline()
    finally:
        keep_awake(False)
        maybe_sleep(args.sleep_when_done, woke)
    return rc


def _run_pipeline() -> int:
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

    procutil.run(["git", "add", "runs", "reports", "README.md"], cwd=REPO,
                   capture_output=True)
    staged = procutil.run(["git", "diff", "--cached", "--name-only"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()
    if not staged:
        log("nothing to commit")
        return 0

    msg = f"autobench: {produced.stem} nightly run + judge + aggregate"
    if not run(["git", "commit", "-q", "-m", msg], "commit", timeout=120):
        log("commit failed (a hook may have blocked it) -- run left staged, not pushed")
        return 1

    # Publish to master explicitly rather than to the current branch. The repo is
    # worked on in feature branches, so pushing HEAD would park the refreshed
    # README on whatever branch happened to be checked out and leave the public
    # default branch stale -- which is how the README froze in July.
    # Git refuses a non-fast-forward push, so this self-guards: if the checked-out
    # branch does not contain origin/master, the push fails loudly instead of
    # publishing unrelated work.
    if not run(["git", "push", "-q", "origin", "HEAD:master"], "push", timeout=300):
        log("push to master failed (not a fast-forward, or no network) -- the "
            "commit is local and will go up once the branch contains origin/master")
        return 1

    log("nightly OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
