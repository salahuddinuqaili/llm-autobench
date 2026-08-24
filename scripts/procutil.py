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
"""
import subprocess
import sys

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
