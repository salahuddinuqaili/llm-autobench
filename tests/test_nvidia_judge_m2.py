"""Offline tests for M2 judge visibility / robustness. No network."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import nvidia_judge as nj  # noqa: E402


def test_median_score():
    assert nj.median_score([0.2, 0.8, 0.5]) == 0.5
    assert nj.median_score([0.1, 0.9]) == 0.5
    assert nj.median_score([]) is None


def test_should_skip_judge_error_cap():
    row = {"score": None, "judge_error": True, "task": "summarization"}
    assert nj.should_skip_judge(row) == "judge_error"
    assert nj.should_skip_judge(row, retry_judge_errors=True) is None


def test_should_skip_truncated_and_scored():
    assert nj.should_skip_judge({"truncated": True, "score": None}) == "truncated"
    assert nj.should_skip_judge({"ingestion_failed": True}) == "ingestion_failed"
    assert nj.should_skip_judge({"score": 0.7}) == "already_scored"


def test_mark_judge_error_sets_persistent_flag():
    row = {}
    nj.mark_judge_error(row, "ERROR: 429 rate limit", judge_label="nvidia/x")
    assert row["score"] is None
    assert row["judge_error"] is True
    assert row["score_reason"].startswith("JUDGE_ERROR:")
    assert "429" in row["score_reason"]


def test_judge_rubric_single_ok():
    def fake(prompt, key, max_retries=4):
        return "0.75"

    score, raw, draws = nj.judge_rubric("p", "k", call_fn=fake)
    assert score == 0.75
    assert draws is None
    assert raw == "0.75"


def test_judge_rubric_single_error():
    def fake(prompt, key, max_retries=4):
        return "ERROR: boom"

    score, raw, draws = nj.judge_rubric("p", "k", call_fn=fake)
    assert score is None
    assert nj.is_error_output(raw)
    assert draws is None


def test_self_consistency_median_not_kappa():
    outs = iter(["0.4", "0.9", "0.5"])

    def fake(prompt, key, max_retries=4):
        return next(outs)

    score, raw, draws = nj.judge_rubric(
        "p", "k", self_consistency_n=3, call_fn=fake)
    assert score == 0.5
    assert draws == [0.4, 0.9, 0.5]
    assert "kappa" not in (raw or "").lower()


def test_self_consistency_all_errors():
    def fake(prompt, key, max_retries=4):
        return "ERROR: down"

    score, raw, draws = nj.judge_rubric(
        "p", "k", self_consistency_n=3, call_fn=fake)
    assert score is None
    assert draws == [None, None, None]
    assert nj.is_error_output(raw)


def test_failures_and_judge_status_derived(tmp_path: Path | None = None):
    scored = [
        {"model": "m", "task": "a", "score": 0.8, "judge": "nvidia/meta/x",
         "latency_s": 1.0, "judge_raw": "0.8"},
        {"model": "m", "task": "b", "score": None, "judge_error": True,
         "score_reason": "JUDGE_ERROR: 429", "latency_s": 1.0,
         "judge_raw": "ERROR: 429"},
        {"model": "m", "task": "c", "score": None, "truncated": True,
         "latency_s": 1.0},
    ]
    report = nj.build_report("run1", scored, self_consistency_n=3)
    assert "## Failures" in report
    assert "JUDGE_ERROR: 429" in report
    assert "truncated at token budget" in report
    assert "## Judge status" in report
    assert "Persistent judge_error" in report
    assert "self-consistency" in report.lower()
    assert "not" in report.lower() and "kappa" in report.lower()
    # Must not claim kappa / inter-rater agreement as a metric we computed.
    assert "cohen" not in report.lower()
    assert "inter-rater" in report.lower()  # disclosure that we are NOT that
    # No hard-coded success claim
    assert "Free judge: yes" not in report
    assert "Judge ran: yes" not in report


def _write_run(path: Path, results):
    path.write_text(json.dumps({"run_id": "t", "results": results}, indent=2),
                    encoding="utf-8")


def test_main_marks_judge_error_and_second_pass_skips(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        run = td / "20260907_m2.json"
        results = [{
            "model": "custom:ollama/demo:7b",
            "task": "summarization",
            "score": None,
            "response": "hello world summary",
            "latency_s": 0.5,
        }]
        _write_run(run, results)

        # Point REPO tasks at real repo so load_rubric works.
        calls = {"n": 0}

        def boom(prompt, key, max_retries=4):
            calls["n"] += 1
            return "ERROR: 429 rate limited"

        with mock.patch.object(nj, "find_nvidia_key", return_value="fake-key"):
            with mock.patch.object(nj, "load_rubric", return_value="Be fair."):
                with mock.patch.object(nj, "load_scoring_method",
                                       return_value="rubric-llm"):
                    # Avoid writing reports into the real reports/ dir — patch REPO reports via build path
                    report_dir = td / "reports"
                    report_dir.mkdir()
                    real_build = nj.build_report

                    def build_and_redirect(stem, scored, **kw):
                        text = real_build(stem, scored, **kw)
                        (report_dir / f"{stem}.md").write_text(text, encoding="utf-8")
                        return text

                    with mock.patch.object(nj, "build_report", side_effect=build_and_redirect):
                        # Also redirect out_path by patching Path write in main — simpler: patch REPO
                        with mock.patch.object(nj, "REPO", td):
                            # Need tasks dir? load_rubric mocked. mechanical path unused.
                            nj.main([str(run), "--max-retries", "1"], call_fn=boom)

        data = json.loads(run.read_text(encoding="utf-8"))
        row = data["results"][0]
        assert row["judge_error"] is True
        assert row["score"] is None
        assert calls["n"] == 1

        # Second pass must not call the judge again.
        def must_not_call(*a, **k):
            raise AssertionError("judge must not be called for capped judge_error")

        with mock.patch.object(nj, "find_nvidia_key", return_value="fake-key"):
            with mock.patch.object(nj, "load_rubric", return_value="Be fair."):
                with mock.patch.object(nj, "load_scoring_method",
                                       return_value="rubric-llm"):
                    with mock.patch.object(nj, "REPO", td):
                        with mock.patch.object(nj, "build_report",
                                               return_value="# noop\n"):
                            nj.main([str(run)], call_fn=must_not_call)

        data2 = json.loads(run.read_text(encoding="utf-8"))
        assert data2["results"][0]["judge_error"] is True


def test_main_self_consistency_writes_draws():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        run = td / "20260907_sc.json"
        _write_run(run, [{
            "model": "custom:ollama/demo:7b",
            "task": "summarization",
            "score": None,
            "response": "summary text",
            "latency_s": 0.2,
        }])
        (td / "reports").mkdir(exist_ok=True)
        outs = iter(["0.2", "0.8", "0.5"])

        def fake(prompt, key, max_retries=4):
            return next(outs)

        with mock.patch.object(nj, "find_nvidia_key", return_value="fake-key"):
            with mock.patch.object(nj, "load_rubric", return_value="Be fair."):
                with mock.patch.object(nj, "load_scoring_method",
                                       return_value="rubric-llm"):
                    with mock.patch.object(nj, "REPO", td):
                        with mock.patch.object(nj, "build_report",
                                               return_value="# noop\n"):
                            nj.main(
                                [str(run), "--self-consistency",
                                 "--self-consistency-n", "3"],
                                call_fn=fake,
                            )
        row = json.loads(run.read_text(encoding="utf-8"))["results"][0]
        assert row["score"] == 0.5
        assert row["judge_draws"] == [0.2, 0.8, 0.5]
        assert row["judge_aggregation"] == "self-consistency-median"
        assert "self-consistency" in row["judge"]
        assert "kappa" not in row["judge"].lower()


def test_build_report_uses_judge_model_once():
    """Report labels the live NIM id once — no nvidia/nvidia and no llama-3.3."""
    md = nj.build_report("x", [{
        "model": "m",
        "task": "t",
        "score": 0.5,
        "latency_s": 1,
        "method": "exact",
        "status": "ok",
    }])
    assert f"`{nj.JUDGE_MODEL}`" in md
    assert f"nvidia/{nj.JUDGE_MODEL}" not in md
    assert "llama-3.3-70b-instruct" not in md
    assert "70B text judge" not in md


if __name__ == "__main__":
    # Allow running without pytest.
    test_median_score()
    test_should_skip_judge_error_cap()
    test_should_skip_truncated_and_scored()
    test_mark_judge_error_sets_persistent_flag()
    test_judge_rubric_single_ok()
    test_judge_rubric_single_error()
    test_self_consistency_median_not_kappa()
    test_self_consistency_all_errors()
    test_failures_and_judge_status_derived()
    test_main_marks_judge_error_and_second_pass_skips()
    test_main_self_consistency_writes_draws()
    test_build_report_uses_judge_model_once()
    print("all m2 tests passed")
