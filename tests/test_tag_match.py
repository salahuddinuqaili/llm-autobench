"""Exact-only local tag matching + param parse (M0.2 / M0.3). No ollama required."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import autobench_cycle as ac  # noqa: E402


def test_tag_size_b():
    assert ac._tag_size_b("gemma4:e4b") == 4.0
    assert ac._tag_size_b("gemma4:12b") == 12.0
    assert ac._tag_size_b("qwen2.5:7b-instruct") == 7.0
    assert ac._tag_size_b("llama3") is None


def test_param_from_tag_m0_3():
    """F1.3 / M0.3 accept cases: suffixes, MoE product, unsized, large."""
    assert ac._param_from_tag("qwen:latest") is None
    assert ac._param_from_tag("codellama:7b-instruct") == 7.0
    assert ac._param_from_tag("mixtral:8x7b") == 56.0
    assert ac._param_from_tag("qwen:110b") == 110.0
    assert ac._param_from_tag("7b-instruct") == 7.0
    assert ac._param_from_tag("qwen2.5:7b") == 7.0


def test_exact_only_no_same_size_substitute():
    """M0.2: qwen2.5:7b must NOT resolve to qwen2.5:7b-instruct."""
    ac._local_tags = lambda: ["qwen2.5:7b-instruct"]
    assert ac.model_is_available_locally("qwen2.5:7b") is False
    assert ac.model_is_available_locally("qwen2.5:7b-instruct") == "qwen2.5:7b-instruct"


def test_no_cross_size_substitute():
    ac._local_tags = lambda: ["gemma4:e4b", "qwen3.5:9b"]
    assert ac.model_is_available_locally("gemma4:12b") is False
    assert ac.model_is_available_locally("gemma4:e4b") == "gemma4:e4b"
    assert ac._other_size_local("gemma4:12b") == "gemma4:e4b"


def test_exact_match_when_both_sizes_present():
    ac._local_tags = lambda: ["gemma4:12b", "gemma4:e4b"]
    assert ac.model_is_available_locally("gemma4:12b") == "gemma4:12b"
    assert ac.model_is_available_locally("gemma4:e4b") == "gemma4:e4b"


if __name__ == "__main__":
    test_tag_size_b()
    test_param_from_tag_m0_3()
    test_exact_only_no_same_size_substitute()
    test_no_cross_size_substitute()
    test_exact_match_when_both_sizes_present()
    print("ok")
