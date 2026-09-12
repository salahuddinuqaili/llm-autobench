"""Nightly preflight aborts loudly when the interpreter lacks cycle deps."""
from __future__ import annotations

import builtins
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nightly as ny  # noqa: E402


def test_preflight_aborts_before_ollama_when_yaml_missing():
    """Wrong interpreter (no PyYAML) must die before any Ollama/network work."""
    logs = []
    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return orig_import(name, *args, **kwargs)

    with mock.patch.object(ny, "log", logs.append):
        with mock.patch.dict(sys.modules):
            sys.modules.pop("yaml", None)
            with mock.patch("builtins.__import__", fake_import):
                with mock.patch.object(ny.urllib.request, "urlopen") as urlopen:
                    urlopen.side_effect = RuntimeError("ollama-must-not-be-contacted")
                    ok = ny.preflight()

    assert ok is False
    urlopen.assert_not_called()
    text = "\n".join(logs)
    assert sys.executable in text
    assert r".venv\Scripts\pythonw.exe" in text


def test_ensure_ollama_skips_start_when_already_up():
    pops = []

    def fake_popen(*_a, **_k):
        pops.append(1)
        raise AssertionError("must not start ollama when 11434 is up")

    with mock.patch.object(ny, "ollama_up", return_value=(True, 0)):
        with mock.patch.object(ny.subprocess, "Popen", fake_popen):
            with mock.patch.object(ny, "log", lambda _m: None):
                assert ny.ensure_ollama(timeout_s=1) is True
    assert pops == []


def test_ensure_ollama_starts_serve_then_succeeds():
    pops = []

    def fake_up():
        return (len(pops) > 0, 0 if pops else None)

    def fake_popen(args, **kwargs):
        pops.append((list(args), kwargs))
        return mock.Mock(pid=1)

    with mock.patch.object(ny, "ollama_up", fake_up):
        with mock.patch.object(ny, "ollama_exe", return_value=ny.Path(r"C:\Ollama\ollama.exe")):
            with mock.patch.object(ny.subprocess, "Popen", fake_popen):
                with mock.patch.object(ny, "log", lambda _m: None):
                    assert ny.ensure_ollama(timeout_s=5) is True
    assert pops[0][0] == [r"C:\Ollama\ollama.exe", "serve"]


def test_ensure_ollama_aborts_when_exe_missing():
    with mock.patch.object(ny, "ollama_up", return_value=(False, None)):
        with mock.patch.object(ny, "ollama_exe", return_value=None):
            logs = []
            with mock.patch.object(ny, "log", logs.append):
                assert ny.ensure_ollama(timeout_s=1) is False
    assert "ollama.exe not found" in "\n".join(logs)


if __name__ == "__main__":
    test_preflight_aborts_before_ollama_when_yaml_missing()
    test_ensure_ollama_skips_start_when_already_up()
    test_ensure_ollama_starts_serve_then_succeeds()
    test_ensure_ollama_aborts_when_exe_missing()
    print("ok")
