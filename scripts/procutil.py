#!/usr/bin/env python3
"""Subprocess wrappers that never flash a console window.

The nightly scheduled task runs `pythonw.exe`, which is a GUI-subsystem process
and therefore owns no console. On Windows, a console child spawned from a parent
with no console allocates its OWN console -- and that console is a visible
window. The harness shells out constantly (curl per judgement, nvidia-smi per
generation, ollama and git per cycle), so the desktop fills with windows that
appear and vanish.

Measured on this machine (Windows 11, Terminal/ConPTY as console host): five
curl children spawned from a pythonw parent produced **10 visible top-level
windows** -- five `PseudoConsoleWindow` plus five `CASCADIA_HOSTING_WINDOW_CLASS`.
With CREATE_NO_WINDOW: **0**.

Note this is a consequence of using pythonw. Under `python.exe` the parent owns a
console and children inherit it silently -- but then the task itself shows a
window, and closing it kills the run (that cost a run on 2026-08-23).
pythonw + CREATE_NO_WINDOW is the combination with neither failure mode.

Call these wrappers instead of `subprocess.*` directly: a bare `subprocess.run`
in this package is then visibly inconsistent with its neighbours, which is the
point -- a new call site cannot quietly reintroduce the flashing.

Also resolve `ollama.exe` by full path. The 21:00 scheduled task's PATH does
not include %LOCALAPPDATA%\\Programs\\Ollama even after nightly starts the
daemon that way; a bare `ollama` then dies with WinError 2.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# CREATE_NO_WINDOW does not exist off Windows, so the whole thing degrades to an
# empty dict rather than an AttributeError on Linux/macOS.
NO_WINDOW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)


def _merged(kwargs):
    """Caller-supplied creationflags win; otherwise add ours."""
    return {**NO_WINDOW, **kwargs}


def run(*args, **kwargs):
    """subprocess.run, windowless."""
    return subprocess.run(*args, **_merged(kwargs))


def check_output(*args, **kwargs):
    """subprocess.check_output, windowless."""
    return subprocess.check_output(*args, **_merged(kwargs))


def popen(*args, **kwargs):
    """subprocess.Popen, windowless."""
    return subprocess.Popen(*args, **_merged(kwargs))


def ollama_exe() -> Path | None:
    """Absolute ollama.exe, independent of PATH.

    Task Scheduler (even InteractiveToken) often lacks the user-shell PATH
    entry the Ollama installer writes. Nightly already locates the file this
    way to start `serve`; every later `ollama pull`/`list`/`rm` must too.
    """
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    found = shutil.which("ollama")
    return Path(found) if found else None


def ollama_argv(*args: str) -> list[str]:
    """Build an argv that CreateProcess can actually find."""
    exe = ollama_exe()
    if exe is None:
        raise FileNotFoundError(
            "ollama.exe not found (checked %LOCALAPPDATA%\\Programs\\Ollama and PATH)"
        )
    return [str(exe), *args]


def prepend_ollama_dir(exe: Path) -> None:
    """Put ollama's directory first on PATH for this process and its children."""
    d = str(Path(exe).parent)
    path = os.environ.get("PATH", "")
    parts = [p for p in path.split(os.pathsep) if p]
    if sys.platform == "win32":
        if d.lower() in {p.lower() for p in parts}:
            return
    elif d in parts:
        return
    os.environ["PATH"] = d + os.pathsep + path
