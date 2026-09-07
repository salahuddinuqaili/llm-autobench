"""Deterministic sandboxed tools for SPEC 13.4 multi-turn agentic tasks.

No network. No writes outside a temp workspace. Tools:
  calc(expression), kv_get(key), kv_set(key, value),
  list_files(dir), read_file(path), finish(answer)

Optional one-shot error injection (SPEC 13.5 error_recovery).
"""
from __future__ import annotations

import ast
import math
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple


# Safe subset for calc(): numbers, + - * / ** %, parentheses, unary minus.
_CALC_ALLOWED = tuple(x for x in (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    getattr(ast, 'Num', ()),  # removed in 3.14+; Constant covers literals
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Load,
) if x != ())


def _safe_calc(expression: str) -> Any:
    expr = (expression or "").strip()
    if not expr:
        raise ValueError("empty expression")
    if len(expr) > 200:
        raise ValueError("expression too long")
    # Reject names / calls / attributes before parse edge-cases.
    if re.search(r"[A-Za-z_]", expr):
        raise ValueError("names not allowed in calc")
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _CALC_ALLOWED):
            raise ValueError(f"disallowed syntax: {type(node).__name__}")
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})


def _norm_path(p: str) -> str:
    """Normalize a sandbox-relative path; reject escapes."""
    p = (p or "").replace("\\", "/").strip().lstrip("/")
    if not p or ".." in p.split("/"):
        raise ValueError("invalid path")
    return p


class ToolSandbox:
    """In-memory + temp-dir tool executor for one multi-turn episode."""

    TOOL_NAMES = ("calc", "kv_get", "kv_set", "list_files", "read_file", "finish")

    def __init__(
        self,
        fixture_dir: Optional[str] = None,
        fixture_files: Optional[Dict[str, str]] = None,
        inject_error: Optional[Dict[str, Any]] = None,
    ):
        self.root = tempfile.mkdtemp(prefix="autobench_tools_")
        self.kv: Dict[str, str] = {}
        self.finished = False
        self.finish_answer: Optional[str] = None
        self.calls: List[Dict[str, Any]] = []
        self._inject = dict(inject_error) if inject_error else None
        self._inject_fired = False
        if fixture_dir and os.path.isdir(fixture_dir):
            for dirpath, _dirs, files in os.walk(fixture_dir):
                for fn in files:
                    src = os.path.join(dirpath, fn)
                    rel = os.path.relpath(src, fixture_dir).replace("\\", "/")
                    dest = os.path.join(self.root, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
        if fixture_files:
            for rel, content in fixture_files.items():
                rel_n = _norm_path(rel)
                dest = os.path.join(self.root, *rel_n.split("/"))
                os.makedirs(os.path.dirname(dest) or self.root, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)

    def close(self) -> None:
        try:
            shutil.rmtree(self.root, ignore_errors=True)
        except Exception:
            pass

    def execute(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run one tool call. Returns a JSON-serializable result dict."""
        args = arguments if isinstance(arguments, dict) else {}
        record: Dict[str, Any] = {"name": name, "arguments": args}
        # Injected soft failure (once) for error_recovery scoring.
        if (
            self._inject
            and not self._inject_fired
            and name == self._inject.get("on_tool")
        ):
            self._inject_fired = True
            msg = self._inject.get("message") or "transient tool error"
            out = {"ok": False, "error": msg, "injected": True}
            record["result"] = out
            self.calls.append(record)
            return out

        try:
            if name == "calc":
                val = _safe_calc(str(args.get("expression", "")))
                out = {"ok": True, "value": val}
            elif name == "kv_set":
                key = str(args.get("key", ""))
                if not key:
                    raise ValueError("key required")
                self.kv[key] = str(args.get("value", ""))
                out = {"ok": True, "key": key}
            elif name == "kv_get":
                key = str(args.get("key", ""))
                if key not in self.kv:
                    out = {"ok": False, "error": f"key not found: {key}"}
                else:
                    out = {"ok": True, "key": key, "value": self.kv[key]}
            elif name == "list_files":
                d = _norm_path(str(args.get("dir", ".") or "."))
                base = self.root if d in (".", "") else os.path.join(self.root, *d.split("/"))
                if not os.path.isdir(base):
                    raise ValueError(f"not a directory: {d}")
                names = sorted(os.listdir(base))
                out = {"ok": True, "dir": d, "files": names}
            elif name == "read_file":
                rel = _norm_path(str(args.get("path", "")))
                path = os.path.join(self.root, *rel.split("/"))
                if not os.path.isfile(path):
                    raise ValueError(f"file not found: {rel}")
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                out = {"ok": True, "path": rel, "content": content}
            elif name == "finish":
                ans = args.get("answer", "")
                self.finished = True
                self.finish_answer = "" if ans is None else str(ans)
                out = {"ok": True, "finished": True, "answer": self.finish_answer}
            else:
                out = {"ok": False, "error": f"unknown tool: {name}", "hallucinated": True}
        except Exception as e:
            out = {"ok": False, "error": str(e)}

        record["result"] = out
        self.calls.append(record)
        return out


def openai_tool_schemas() -> List[Dict[str, Any]]:
    """Standard OpenAI-style tool defs matching SPEC 13.4."""
    def fn(name, desc, props, required):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    return [
        fn("calc", "Evaluate a pure arithmetic expression.", {
            "expression": {"type": "string", "description": "Arithmetic expression, e.g. 42+17"},
        }, ["expression"]),
        fn("kv_set", "Store a string value under a key for later turns.", {
            "key": {"type": "string"},
            "value": {"type": "string"},
        }, ["key", "value"]),
        fn("kv_get", "Read a previously stored key.", {
            "key": {"type": "string"},
        }, ["key"]),
        fn("list_files", "List files in a sandbox directory (read-only fixtures).", {
            "dir": {"type": "string", "description": "Relative directory, default ."},
        }, []),
        fn("read_file", "Read a text file from the sandbox fixture directory.", {
            "path": {"type": "string", "description": "Relative file path"},
        }, ["path"]),
        fn("finish", "Terminate the episode with the final answer.", {
            "answer": {"type": "string", "description": "Final answer string"},
        }, ["answer"]),
    ]
