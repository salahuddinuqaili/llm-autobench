"""Size-strict local tag matching. No Ollama required — _local_tags is stubbed."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autobench_cycle as ac


def test_tag_size_b():
    assert ac._tag_size_b("gemma4:12b") == 12.0
    assert ac._tag_size_b("gemma4:e4b") == 4.0
    assert ac._tag_size_b("qwen2.5:7b-instruct") == 7.0
    assert ac._tag_size_b("llama3") is None


def test_gemma4_12b_does_not_resolve_to_e4b():
    with patch.object(ac, "_local_tags", return_value=["gemma4:e4b"]):
        assert ac.model_is_available_locally("gemma4:12b") is False
        assert ac._other_size_local("gemma4:12b") == "gemma4:e4b"


def test_same_size_instruct_variant():
    with patch.object(ac, "_local_tags", return_value=["qwen2.5:7b-instruct"]):
        assert ac.model_is_available_locally("qwen2.5:7b") == "qwen2.5:7b-instruct"


def test_exact_match_wins():
    locals_ = ["gemma4:e4b", "gemma4:12b"]
    with patch.object(ac, "_local_tags", return_value=locals_):
        assert ac.model_is_available_locally("gemma4:12b") == "gemma4:12b"


def test_no_size_request_resolves_same_base():
    with patch.object(ac, "_local_tags", return_value=["llama3:8b"]):
        assert ac.model_is_available_locally("llama3") == "llama3:8b"


if __name__ == "__main__":
    tests = [
        test_tag_size_b,
        test_gemma4_12b_does_not_resolve_to_e4b,
        test_same_size_instruct_variant,
        test_exact_match_wins,
        test_no_size_request_resolves_same_base,
    ]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("all passed")
