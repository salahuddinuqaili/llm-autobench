"""String contract for scripts/install_nightly_task.ps1.

The live Task Scheduler job must stay on pythonw + nightly.py. A later edit
must not silently switch Command back to python.exe or a uv interpreter.
This test does not call Register-ScheduledTask.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PS1 = REPO / "scripts" / "install_nightly_task.ps1"


def _text() -> str:
    return PS1.read_text(encoding="utf-8")


def test_installer_file_exists():
    assert PS1.is_file(), f"missing {PS1}"


def test_command_is_venv_pythonw_not_python_exe():
    text = _text()
    assert r".venv\Scripts\pythonw.exe" in text
    # Desired Command is pythonw; python.exe may appear only as a warning.
    assert "Join-Path $repo \".venv\\Scripts\\pythonw.exe\"" in text
    assert "Join-Path $repo \".venv\\Scripts\\python.exe\"" not in text
    assert "python3.14.exe" not in text
    assert re.search(r'(?i)uv\.exe|uv run', text) is None


def test_arguments_are_nightly_py():
    text = _text()
    assert r"scripts\nightly.py" in text
    assert "Join-Path $repo \"scripts\\nightly.py\"" in text


def test_task_name_and_schedule_and_logon():
    text = _text()
    assert "llm-autobench nightly (salahuddin)" in text
    assert '-Daily -At "21:00"' in text
    assert "-LogonType Interactive" in text
    assert "InteractiveToken" in text
    assert "[switch]$DryRun" in text
    assert "[switch]$Force" in text


def test_empty_working_directory_is_tolerated_without_force():
    text = _text()
    assert "Empty Start-In is tolerated" in text
    assert "nightly.py locates the repo from __file__" in text or "resolves REPO from __file__" in text
    assert "-Force rewrites it" in text
    # Must not treat empty WorkingDirectory as a mismatch.
    assert "if ($wd -and ($wd -ne (Get-NormalizedPath $Desired.Repo)))" in text


def test_no_secrets_embedded():
    text = _text()
    assert "NVIDIA_API_KEY" in text  # mentioned as runtime-only
    assert re.search(r"nvapi-[A-Za-z0-9_-]{8,}", text) is None
    assert "sk-" not in text
    assert "PASSWORD" not in text.upper() or "no stored password" in text.lower() or "Never embed" in text


def test_register_is_gated_by_mismatch_and_force():
    text = _text()
    assert "already correct" in text
    assert "skipping Register-ScheduledTask" in text
    assert "if ($DryRun)" in text
    assert "Register-NightlyTask $desired" in text
    # DryRun must exit before register.
    dry_idx = text.index("if ($DryRun)")
    reg_idx = text.index("Register-NightlyTask $desired")
    assert dry_idx < reg_idx


def test_dry_run_subprocess_is_noop():
    """Invoke -DryRun; must exit 0 and never require a password."""
    powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.isfile(powershell):
        powershell = "powershell.exe"
    proc = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "pythonw" in out.lower() or "already correct" in out.lower() or "DryRun" in out
    assert "Register-ScheduledTask" in out or "already correct" in out
    assert "password" not in out.lower()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ok")
