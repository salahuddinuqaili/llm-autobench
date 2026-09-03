"""Size-strict local tag matching. No ollama required."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import autobench_cycle as ac  # noqa: E402


def test_tag_size_b():
    assert ac._tag_size_b("gemma4:e4b") == 4.0
    assert ac._tag_size_b("gemma4:12b") == 12.0
    assert ac._tag_size_b("qwen2.5:7b-instruct") == 7.0
    assert ac._tag_size_b("llama3") is None


def test_no_cross_size_substitute(monkey_tags):
    ac._local_tags = lambda: monkey_tags
    assert ac.model_is_available_locally("gemma4:12b") is False
    assert ac.model_is_available_locally("gemma4:e4b") == "gemma4:e4b"
    assert ac._other_size_local("gemma4:12b") == "gemma4:e4b"


def test_same_size_variant():
    ac._local_tags = lambda: ["qwen2.5:7b-instruct"]
    assert ac.model_is_available_locally("qwen2.5:7b") == "qwen2.5:7b-instruct"


if __name__ == "__main__":
    test_tag_size_b()
    test_no_cross_size_substitute(["gemma4:e4b", "qwen3.5:9b"])
    test_same_size_variant()
    # both sizes present: exact 12b wins, 12b request must not become e4b
    ac._local_tags = lambda: ["gemma4:12b", "gemma4:e4b"]
    assert ac.model_is_available_locally("gemma4:12b") == "gemma4:12b"
    assert ac.model_is_available_locally("gemma4:e4b") == "gemma4:e4b"
    print("ok")
