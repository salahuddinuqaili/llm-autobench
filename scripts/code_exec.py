#!/usr/bin/env python3
"""Mechanical Python scoring for coding tasks (M1 / SPEC 5.3 thin path).

Extracts a submitted function from a model response, runs it against fixed
fixtures from the task YAML, and returns 1.0 / 0.0. Unparseable submissions
return None (unscored) — same honesty rule as truncation. Not a HumanEval
suite port: one battery item, fixture-driven.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_DEF_RE = re.compile(r"^(?:async\s+)?def\s+\w+", re.MULTILINE)


def extract_python(response: str) -> str | None:
    """Pull the Python source to exec from a model response.

    Prefers a fenced block that contains a ``def``; falls back to the first
    fence, then to bare text starting at the first ``def``.
    """
    if not response or not str(response).strip():
        return None
    fences = _FENCE_RE.findall(response)
    if fences:
        for block in fences:
            if _DEF_RE.search(block):
                return textwrap.dedent(block).strip()
        return textwrap.dedent(fences[0]).strip() or None
    m = _DEF_RE.search(response)
    if m:
        return textwrap.dedent(response[m.start():]).strip() or None
    return None


_HARNESS = '''# auto-generated mechanical check harness — do not edit
import json
import sys
from pathlib import Path

CODE = Path("submission.py").read_text(encoding="utf-8")
CHECKS = json.loads(Path("checks.json").read_text(encoding="utf-8"))
FUNC = {func_name!r}

ns = {{}}
try:
    exec(compile(CODE, "submission.py", "exec"), ns, ns)
except SyntaxError as e:
    print(json.dumps({{"status": "unparseable", "detail": f"syntax: {{e}}"}}))
    sys.exit(0)
except Exception as e:  # noqa: BLE001
    print(json.dumps({{"status": "unparseable", "detail": f"import: {{type(e).__name__}}: {{e}}"}}))
    sys.exit(0)

fn = ns.get(FUNC)
if not callable(fn):
    print(json.dumps({{"status": "unparseable", "detail": f"missing callable {{FUNC}}"}}))
    sys.exit(0)

for i, check in enumerate(CHECKS):
    args = check.get("args", [])
    kwargs = check.get("kwargs", {{}}) or {{}}
    expect = check.get("expect")
    try:
        got = fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({{
            "status": "fail",
            "detail": f"check {{i}}: raised {{type(e).__name__}}: {{e}}",
        }}))
        sys.exit(0)
    if got != expect:
        print(json.dumps({{
            "status": "fail",
            "detail": f"check {{i}}: got {{got!r}} expected {{expect!r}}",
        }}))
        sys.exit(0)

print(json.dumps({{"status": "pass"}}))
'''


def score_python_exec(task: dict, response: str) -> float | None:
    """Run task.scoring.checks against the extracted function.

    Returns:
      1.0 — all fixtures pass
      0.0 — function loaded but failed a check / timed out / runtime error
      None — no extractable code, missing function, or SyntaxError (unscored)
    """
    scoring = task.get("scoring") or {}
    func_name = scoring.get("function")
    checks = scoring.get("checks") or []
    if not func_name or not checks:
        return None

    code = extract_python(response)
    if not code:
        return None

    timeout = float(scoring.get("timeout_s") or 2.0)
    with tempfile.TemporaryDirectory(prefix="autobench_pyexec_") as td:
        tdir = Path(td)
        (tdir / "submission.py").write_text(code, encoding="utf-8")
        (tdir / "checks.json").write_text(
            json.dumps(checks, ensure_ascii=False), encoding="utf-8")
        harness = _HARNESS.format(func_name=func_name)
        (tdir / "harness.py").write_text(harness, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(tdir / "harness.py")],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(tdir),
            )
        except subprocess.TimeoutExpired:
            return 0.0

    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        return 0.0
    try:
        payload = json.loads(raw[-1])
    except json.JSONDecodeError:
        return 0.0

    status = payload.get("status")
    if status == "pass":
        return 1.0
    if status == "unparseable":
        return None
    return 0.0
