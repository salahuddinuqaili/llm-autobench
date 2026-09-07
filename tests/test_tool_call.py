"""Offline tests for M4 / SPEC 13.3 single-turn tool-call scoring. No Ollama."""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import aggregate_results as agg  # noqa: E402
import nvidia_judge as nj  # noqa: E402
import run_bench  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def _task():
    with open(os.path.join(REPO, "tasks", "tool_weather.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_task_schema():
    task = _task()
    assert task["id"] == "tool_weather"
    assert task["category"] == "agentic"
    assert task["scoring"]["method"] == "tool-call"
    assert task["expect_tool_call"]["name"] == "get_weather"
    assert task["expect_tool_call"]["arguments"]["city"] == "Berlin"
    assert task["tools"] and task["tools"][0]["function"]["name"] == "get_weather"
    assert "tools" in task["tags"]


def test_correct_tool_call_scores_one():
    task = _task()
    calls = [{"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}]
    assert run_bench.score_tool_call(task, calls) == 1.0
    assert run_bench.score(task, "", tool_calls=calls) == 1.0


def test_args_as_json_string_ok():
    task = _task()
    calls = [{"function": {"name": "get_weather", "arguments": '{"city": "Berlin"}'}}]
    assert run_bench.score_tool_call(task, calls) == 1.0


def test_wrong_tool_scores_zero():
    task = _task()
    calls = [{"function": {"name": "get_time", "arguments": {"city": "Berlin"}}}]
    assert run_bench.score_tool_call(task, calls) == 0.0


def test_wrong_args_scores_zero():
    task = _task()
    calls = [{"function": {"name": "get_weather", "arguments": {"city": "Paris"}}}]
    assert run_bench.score_tool_call(task, calls) == 0.0


def test_missing_tool_calls_unscored():
    task = _task()
    assert run_bench.score_tool_call(task, []) is None
    assert run_bench.score_tool_call(task, None) is None
    assert run_bench.score(task, "It is sunny in Berlin.", tool_calls=[]) is None


def test_judge_skips_tools_unsupported():
    row = {"score": None, "tools_unsupported": True, "task": "tool_weather"}
    assert nj.should_skip_judge(row) == "tools_unsupported"


def test_tool_call_is_mechanical():
    assert "tool-call" in nj._MECHANICAL


def test_agentic_excluded_from_shared():
    assert "tool_weather" in agg.AGENTIC_TASKS
    # shared computation subtracts AGENTIC_TASKS
    shared = {"arithmetic_reasoning", "tool_weather", "summarization"}
    shared -= agg.AGENTIC_TASKS
    shared -= agg.VISION_TASKS
    assert "tool_weather" not in shared
    assert "arithmetic_reasoning" in shared


if __name__ == "__main__":
    test_task_schema()
    test_correct_tool_call_scores_one()
    test_args_as_json_string_ok()
    test_wrong_tool_scores_zero()
    test_wrong_args_scores_zero()
    test_missing_tool_calls_unscored()
    test_judge_skips_tools_unsupported()
    test_tool_call_is_mechanical()
    test_agentic_excluded_from_shared()
    print("ok")
