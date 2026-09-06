"""build_temp_registry keeps exactly one subject — no baseline co-append."""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import autobench_cycle as ac  # noqa: E402


def test_build_temp_registry_subject_only(monkeypatch=None):
    """Even with abundant free VRAM, keep only the subject (no baselines)."""
    # Mock VRAM so a regression that re-introduces co-append would have room
    # to append baselines — and the assertion would still catch it.
    ac.get_vram_free_mib = lambda: 48_000
    ac.estimate_model_vram_mib = lambda params, quantization="q4_k_m": 1024

    model = "unit-test-subject:7b"
    tmp, kept = ac.build_temp_registry(model, watcher={})
    try:
        assert kept == [f"custom:ollama/{model}"], kept
        data = yaml.safe_load(open(tmp))
        entries = data.get("baseline") or []
        assert len(entries) == 1, entries
        assert entries[0]["id"] == f"custom:ollama/{model}"
        # Must not sneak any committed baseline ids into the temp registry.
        cfg = yaml.safe_load(open(os.path.join(ac.REPO, "models", "registry.yaml")))
        baseline_ids = {b["id"] for b in cfg.get("baseline", [])}
        assert entries[0]["id"] not in baseline_ids
        assert not (baseline_ids & set(kept))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    test_build_temp_registry_subject_only()
    print("ok")
