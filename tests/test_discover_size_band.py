"""M0.1: size_band filter + deterministic pick (no prefer-larger)."""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import autobench_cycle as ac  # noqa: E402


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


def _stub_library(names, tags_by_name):
    """Avoid network + pretend abundant VRAM; ignore real runs via empty tested."""
    ac.has_vram_headroom = lambda required_mib, buffer_mib=1024: True
    ac.FALLBACK_MODELS = []

    real_exists = os.path.exists

    def fake_exists(p):
        # Force discover to see no prior runs so picks are from candidates only.
        norm = str(p).replace("\\", "/").rstrip("/")
        if norm.endswith("/runs"):
            return False
        return real_exists(p)

    os.path.exists = fake_exists

    def fake_urlopen(req, timeout=15):
        url = getattr(req, "full_url", None) or str(req)
        if url.rstrip("/").endswith("/library"):
            body = "".join(f'/library/{n}"' for n in names)
            return _FakeResp(body)
        for name, tags in tags_by_name.items():
            if url.rstrip("/").endswith("/library/" + name):
                body = "".join(f'/library/{name}:{t}"' for t in tags)
                return _FakeResp(body)
        return _FakeResp("")

    urllib.request.urlopen = fake_urlopen


def test_size_band_excludes_outside_and_picks_deterministic():
    # 3b below band, 12b above band max 10; mid:7b and other:9b in band.
    # Lexicographic among in-band: mid:7b < other:9b.
    _stub_library(
        ["mid", "other", "tiny", "big"],
        {"mid": ["7b"], "other": ["9b"], "tiny": ["3b"], "big": ["12b"]},
    )
    watcher = {"max_params_billions": 14, "size_band": {"min": 6, "max": 10}}
    picked = ac.discover(watcher)
    assert picked == "mid:7b", picked


def test_prefer_larger_removed():
    """With only 9b and 7b in band, must NOT prefer 9b solely for size."""
    _stub_library(["alpha", "beta"], {"alpha": ["9b"], "beta": ["7b"]})
    watcher = {"max_params_billions": 14, "size_band": {"min": 6, "max": 10}}
    picked = ac.discover(watcher)
    # lexicographic: alpha:9b < beta:7b
    assert picked == "alpha:9b", picked


def test_unsized_param_is_none():
    assert ac._param_from_tag("latest") is None
    assert ac._param_from_tag("model:latest") is None


if __name__ == "__main__":
    test_unsized_param_is_none()
    test_size_band_excludes_outside_and_picks_deterministic()
    test_prefer_larger_removed()
    print("ok")
