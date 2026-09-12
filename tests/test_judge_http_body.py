"""NVIDIA NIM can return plain-text HTTP errors, not JSON.

2026-09-12: meta/llama-3.1-nemotron-70b-instruct answered
`404 page not found\\n`. json.loads parsed the leading 404 as an int, then
raised Extra data: line 1 column 5 (char 4). That string was written as
JUDGE_ERROR on every rubric row. A missing/retired model must be named as
404, not as a JSON parse glitch.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nvidia_judge as nj  # noqa: E402


from unittest import mock


def test_plain_404_is_named_not_extra_data():
    try:
        nj.decode_judge_response("404 page not found\n")
    except ValueError as e:
        msg = str(e)
        assert "404" in msg
        assert "Extra data" not in msg
        assert "not found" in msg.lower() or "NIM" in msg or "model" in msg.lower()
        return
    raise AssertionError("expected ValueError for plain-text 404")


def test_eol_json_is_named_not_choices_keyerror():
    body = (
        '{"status": 410, "title": "model has reached end of life", '
        '"detail": "meta/llama-3.3-70b-instruct is retired"}'
    )
    try:
        nj.decode_judge_response(body)
    except ValueError as e:
        msg = str(e)
        assert "end of life" in msg.lower() or "retired" in msg.lower()
        assert "choices" not in msg.lower() or "end of life" in msg.lower()
        return
    raise AssertionError("expected ValueError for 410 JSON")


def test_valid_chat_completion_returns_choices():
    body = (
        '{"id": "x", "choices": [{"index": 0, "message": '
        '{"role": "assistant", "content": "0.8"}}]}'
    )
    data = nj.decode_judge_response(body)
    assert data["choices"][0]["message"]["content"] == "0.8"


def test_call_judge_404_does_not_retry_or_say_extra_data():
    class Fake:
        stdout = "404 page not found\n"
        stderr = ""
        returncode = 0

    n = {"calls": 0}

    def fake_run(*_a, **_k):
        n["calls"] += 1
        return Fake()

    with mock.patch.object(nj.procutil, "run", fake_run):
        out = nj.call_judge("score this", "nvapi-fake", max_retries=4)
    assert out.startswith("ERROR:")
    assert "404" in out
    assert "Extra data" not in out
    assert n["calls"] == 1


if __name__ == "__main__":
    test_plain_404_is_named_not_extra_data()
    test_eol_json_is_named_not_choices_keyerror()
    test_valid_chat_completion_returns_choices()
    test_call_judge_404_does_not_retry_or_say_extra_data()
    print("ok")
