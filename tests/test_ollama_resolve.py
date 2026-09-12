"""Scheduled-task PATH is not the user shell PATH.

2026-09-11 21:00 nightly started ollama via the full
%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe path, then autobench_cycle.py
called bare `ollama` and died with WinError 2 in 4s. Resolution must not
depend on PATH.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import autobench_cycle as ac  # noqa: E402
import procutil  # noqa: E402


def test_ollama_exe_prefers_localappdata_when_path_empty(tmp_path, monkeypatch=None):
    root = Path(tmp_path) if not hasattr(tmp_path, "joinpath") else tmp_path
    # unittest-style: allow running without pytest monkeypatch.
    fake_home = root / "lad"
    exe = fake_home / "Programs" / "Ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(fake_home)
    env["PATH"] = str(root / "empty-path-dir")
    (root / "empty-path-dir").mkdir(exist_ok=True)
    with mock.patch.dict(os.environ, env, clear=False):
        found = procutil.ollama_exe()
    assert found is not None
    assert Path(found) == exe


def test_ollama_exe_none_when_missing(tmp_path):
    root = Path(tmp_path)
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(root / "no-ollama")
    env["PATH"] = str(root / "empty")
    (root / "empty").mkdir()
    with mock.patch.dict(os.environ, env, clear=False):
        assert procutil.ollama_exe() is None


def test_ollama_argv_uses_resolved_exe_not_bare_name():
    fake = Path(r"C:\Users\x\AppData\Local\Programs\Ollama\ollama.exe")
    with mock.patch.object(procutil, "ollama_exe", return_value=fake):
        argv = procutil.ollama_argv("pull", "qwen3.5:9b")
    assert argv[0] == str(fake)
    assert argv[0] != "ollama"
    assert argv[1:] == ["pull", "qwen3.5:9b"]


def test_ollama_argv_raises_clear_error_when_missing():
    with mock.patch.object(procutil, "ollama_exe", return_value=None):
        try:
            procutil.ollama_argv("list")
        except FileNotFoundError as exc:
            msg = str(exc)
            assert "ollama.exe" in msg
            assert "PATH" in msg
        else:
            raise AssertionError("expected FileNotFoundError")


def test_cycle_pull_list_rm_use_resolved_exe():
    """The 21:00 crash: pull(['ollama', ...]) with no PATH entry."""
    fake = Path(r"C:\Users\x\AppData\Local\Programs\Ollama\ollama.exe")
    seen = []

    def capture(args, **kwargs):
        seen.append(list(args))
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch.object(procutil, "ollama_exe", return_value=fake):
        with mock.patch.object(ac.procutil, "run", capture):
            with mock.patch.object(
                ac.procutil, "check_output", lambda args, **k: "qwen3.5:9b\n"
            ):
                ac.pull("qwen3.5:9b")
                ac.delete("qwen3.5:9b")
                tags = ac._local_tags()
    assert tags == ["qwen3.5:9b"]
    assert seen, "pull/delete must call procutil.run"
    for argv in seen:
        assert argv[0] == str(fake), argv
        assert argv[0] != "ollama"
    assert any(a[1] == "pull" for a in seen)
    assert any(a[1] == "rm" for a in seen)


def test_prepend_ollama_dir_puts_exe_dir_first():
    fake = Path(r"C:\Users\x\AppData\Local\Programs\Ollama\ollama.exe")
    with mock.patch.dict(os.environ, {"PATH": r"C:\Windows\System32"}, clear=False):
        procutil.prepend_ollama_dir(fake)
        parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == str(fake.parent)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_ollama_exe_prefers_localappdata_when_path_empty(d)
        test_ollama_exe_none_when_missing(d)
    test_ollama_argv_uses_resolved_exe_not_bare_name()
    test_ollama_argv_raises_clear_error_when_missing()
    test_cycle_pull_list_rm_use_resolved_exe()
    test_prepend_ollama_dir_puts_exe_dir_first()
    print("ok")
