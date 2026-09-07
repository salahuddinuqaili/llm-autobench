"""Offline tests for SPEC 13.4 multi-turn tools + 13.5 trajectory sub-scores.

No Ollama. Hand-written trajectories exercise the sandbox and scorer.
"""
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import aggregate_results as agg  # noqa: E402
import nvidia_judge as nj  # noqa: E402
import run_bench  # noqa: E402
import tool_sandbox as ts  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def _task():
    with open(os.path.join(REPO, "tasks", "tool_multiturn_sum.yaml"), encoding="utf-8") as f:
        task = yaml.safe_load(f)
    task["tools"] = ts.openai_tool_schemas()
    return task


def test_task_schema():
    task = _task()
    assert task["id"] == "tool_multiturn_sum"
    assert task["category"] == "agentic"
    assert task["multi_turn"] is True
    assert task["scoring"]["method"] == "tool-trajectory"
    assert task["scoring"]["expect_finish"] == "59"
    assert task["inject_error"]["on_tool"] == "read_file"
    assert "tools" in task["tags"]


def test_sandbox_calc_and_files():
    fixture = os.path.join(REPO, "tasks", "fixtures", "tool_multiturn")
    sb = ts.ToolSandbox(fixture_dir=fixture)
    try:
        assert sb.execute("list_files", {"dir": "notes"})["files"] == ["n.txt"]
        assert sb.execute("read_file", {"path": "notes/n.txt"})["content"].strip() == "42"
        assert sb.execute("calc", {"expression": "42+17"})["value"] == 59
        sb.execute("kv_set", {"key": "x", "value": "59"})
        assert sb.execute("kv_get", {"key": "x"})["value"] == "59"
        fin = sb.execute("finish", {"answer": "59"})
        assert fin["finished"] and sb.finished and sb.finish_answer == "59"
    finally:
        sb.close()


def test_sandbox_rejects_escape_and_names():
    sb = ts.ToolSandbox()
    try:
        assert sb.execute("read_file", {"path": "../secret"})["ok"] is False
        assert sb.execute("calc", {"expression": "__import__('os').system('x')"})["ok"] is False
        assert sb.execute("nope", {})["hallucinated"] is True
    finally:
        sb.close()


def test_inject_error_once():
    fixture = os.path.join(REPO, "tasks", "fixtures", "tool_multiturn")
    sb = ts.ToolSandbox(
        fixture_dir=fixture,
        inject_error={"on_tool": "read_file", "message": "boom"},
    )
    try:
        r1 = sb.execute("read_file", {"path": "notes/n.txt"})
        assert r1["ok"] is False and r1.get("injected")
        r2 = sb.execute("read_file", {"path": "notes/n.txt"})
        assert r2["ok"] is True and r2["content"].strip() == "42"
    finally:
        sb.close()


def _perfect_call_fn(script):
    """Return a call_fn that replays a list of (content, tool_calls) per turn."""
    state = {"i": 0}

    def call_fn(model, messages, max_tokens, tools):
        i = state["i"]
        state["i"] = i + 1
        if i >= len(script):
            return "", 0.01, None, {"tool_calls": [], "done_reason": "stop"}
        content, tcs = script[i]
        return content, 0.01, None, {"tool_calls": tcs, "done_reason": "stop"}

    return call_fn


def _tc(name, **args):
    return {"function": {"name": name, "arguments": args}}


def test_perfect_trajectory_all_subscores_one():
    """SPEC accept: hand-written perfect trajectory scores 1.0 on every sub-score."""
    task = _task()
    # Optimal with inject: fail read, retry read, calc, finish = 4 turns
    script = [
        ("reading", [_tc("read_file", path="notes/n.txt")]),
        ("retry", [_tc("read_file", path="notes/n.txt")]),
        ("calc", [_tc("calc", expression="42 + 17")]),
        ("done", [_tc("finish", answer="59")]),
    ]
    out = run_bench.run_tool_loop({"id": "dummy", "provider": "custom"}, task, call_fn=_perfect_call_fn(script))
    assert out["tools_unsupported"] is False
    assert out["score"] == 1.0
    subs = out["trajectory_scores"]
    assert subs["completed"] == 1.0
    assert subs["tool_choice"] == 1.0
    assert subs["efficiency"] == 1.0
    assert subs["error_recovery"] == 1.0
    assert subs["no_hallucinated_tools"] == 1.0
    assert subs["terminated"] == 1.0
    assert subs["turns_used"] == 4


def test_cap_hit_terminated_zero():
    """SPEC accept: looping to the cap scores terminated: 0; other subs kept."""
    task = _task()
    task["turn_cap"] = 3
    # Never finish; keep calling calc
    script = [
        ("a", [_tc("calc", expression="1+1")]),
        ("b", [_tc("calc", expression="2+2")]),
        ("c", [_tc("calc", expression="3+3")]),
    ]
    out = run_bench.run_tool_loop({"id": "dummy", "provider": "custom"}, task, call_fn=_perfect_call_fn(script))
    assert out["score"] == 0.0
    subs = out["trajectory_scores"]
    assert subs["terminated"] == 0.0
    assert subs["completed"] == 0.0
    assert subs["no_hallucinated_tools"] == 1.0
    assert subs["turns_used"] == 3


def test_tools_unsupported_unscored():
    task = _task()
    script = [("I cannot use tools, the answer is 59.", [])]
    out = run_bench.run_tool_loop({"id": "dummy", "provider": "custom"}, task, call_fn=_perfect_call_fn(script))
    assert out["tools_unsupported"] is True
    assert out["score"] is None
    assert out["trajectory_scores"] is None


def test_hallucinated_tool_subscore():
    task = _task()
    script = [
        ("x", [_tc("launch_missiles", target="moon")]),
        ("y", [_tc("finish", answer="59")]),
    ]
    out = run_bench.run_tool_loop({"id": "dummy", "provider": "custom"}, task, call_fn=_perfect_call_fn(script))
    assert out["trajectory_scores"]["no_hallucinated_tools"] == 0.0


def test_wrong_finish_completed_zero():
    task = _task()
    script = [
        ("r", [_tc("read_file", path="notes/n.txt")]),
        ("r2", [_tc("read_file", path="notes/n.txt")]),
        ("c", [_tc("calc", expression="42+17")]),
        ("f", [_tc("finish", answer="0")]),
    ]
    out = run_bench.run_tool_loop({"id": "dummy", "provider": "custom"}, task, call_fn=_perfect_call_fn(script))
    assert out["score"] == 0.0
    assert out["trajectory_scores"]["completed"] == 0.0
    assert out["trajectory_scores"]["terminated"] == 1.0


def test_agentic_excluded_from_shared():
    assert "tool_multiturn_sum" in agg.AGENTIC_TASKS
    assert "tool_multiturn_sum" in nj.AGENTIC_TASKS
    assert "tool-trajectory" in nj._MECHANICAL
    shared = {"arithmetic_reasoning", "tool_weather", "tool_multiturn_sum"}
    shared -= agg.AGENTIC_TASKS
    assert "tool_multiturn_sum" not in shared
    assert "tool_weather" not in shared


def test_judge_skips_tools_unsupported():
    row = {"score": None, "tools_unsupported": True, "task": "tool_multiturn_sum"}
    assert nj.should_skip_judge(row) == "tools_unsupported"


if __name__ == "__main__":
    test_task_schema()
    test_sandbox_calc_and_files()
    test_sandbox_rejects_escape_and_names()
    test_inject_error_once()
    test_perfect_trajectory_all_subscores_one()
    test_cap_hit_terminated_zero()
    test_tools_unsupported_unscored()
    test_hallucinated_tool_subscore()
    test_wrong_finish_completed_zero()
    test_agentic_excluded_from_shared()
    test_judge_skips_tools_unsupported()
    print("ok")
