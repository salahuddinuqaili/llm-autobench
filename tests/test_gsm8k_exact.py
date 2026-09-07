"""Offline pass/fail coverage for P2.2 thin GSM8K-style exact slice. No Ollama / judge."""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import run_bench  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")
SLICE_IDS = [f"gsm8k_s0{i}" for i in range(1, 6)]
ANSWERS = {
    "gsm8k_s01": "14",
    "gsm8k_s02": "18",
    "gsm8k_s03": "24",
    "gsm8k_s04": "60",
    "gsm8k_s05": "44",
}


def _load(task_id: str) -> dict:
    path = os.path.join(REPO, "tasks", f"{task_id}.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_slice_tasks_are_exact_and_tagged():
    for tid in SLICE_IDS:
        task = _load(tid)
        assert task["id"] == tid
        assert task["scoring"]["method"] == "exact"
        assert task["expected"]["answer"] == ANSWERS[tid]
        assert "reasoning" in task["tags"]
        assert "gsm8k" in task["tags"]
        assert "Final answer:" in task["prompt"]


def test_correct_final_answer_scores_one():
    for tid, ans in ANSWERS.items():
        task = _load(tid)
        resp = f"scratch\n...\nFinal answer: {ans}\n"
        assert run_bench.score(task, resp) == 1.0, tid
        # float-equivalent form
        resp_f = f"Final answer: {ans}.0"
        assert run_bench.score(task, resp_f) == 1.0, tid


def test_wrong_final_despite_correct_scratch_scores_zero():
    task = _load("gsm8k_s01")
    # Correct intermediate (70 sold / 14 left) but wrong labelled final.
    resp = (
        "Total 84. Sold 70. Left 14.\n"
        "Final answer: 70\n"
    )
    assert run_bench.score(task, resp) == 0.0


def test_empty_response_scores_zero():
    task = _load("gsm8k_s02")
    assert run_bench.score(task, "") == 0.0


def test_provenance_committed():
    path = os.path.join(REPO, "tasks", "fixtures", "GSM8K_SLICE_PROVENANCE.md")
    assert os.path.isfile(path)
    text = open(path, encoding="utf-8").read()
    assert "Not** a dump" in text or "Not a dump" in text or "**Not** a dump" in text
    assert "original" in text.lower()


def test_registry_wires_gsm8k_tag():
    path = os.path.join(REPO, "models", "registry.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "gsm8k" in data["battery_tags"]
    # Baselines that carry the full text battery must include gsm8k (symmetry).
    for m in data["baseline"]:
        tags = m.get("tags") or []
        if "reasoning" in tags and "coding" in tags:
            assert "gsm8k" in tags, m["id"]
        if tags == ["vision", "ocr", "progressive"] or set(tags) <= {"vision", "ocr", "progressive"}:
            assert "gsm8k" not in tags, m["id"]


def test_load_tasks_includes_slice():
    tasks = run_bench.load_tasks(os.path.join(REPO, "tasks"))
    ids = {t["id"] for t in tasks}
    for tid in SLICE_IDS:
        assert tid in ids


if __name__ == "__main__":
    test_slice_tasks_are_exact_and_tagged()
    test_correct_final_answer_scores_one()
    test_wrong_final_despite_correct_scratch_scores_zero()
    test_empty_response_scores_zero()
    test_provenance_committed()
    test_registry_wires_gsm8k_tag()
    test_load_tasks_includes_slice()
    print("ok")
