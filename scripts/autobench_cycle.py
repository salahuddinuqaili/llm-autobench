#!/usr/bin/env python3
"""
llm-autobench autonomous lifecycle (the "autobench" pipeline).

Stages — the FREE Hermes agent orchestrating the cron does discovery decisions,
judging, and reporting. This script does the mechanical LOCAL work:

  1. discover()  -> find a new model tag not yet benchmarked (VRAM-aware)
  2. pull()      -> `ollama pull <model>` if it fits VRAM
  3. bench()     -> calls run_bench.py for the discovered model (+ baselines)
  4. judge/report-> done by the agent reading runs/<id>.json (see CLAUDE.md)
  5. delete()    -> `ollama rm <model>` to free disk/VRAM
  6. commit()    -> git add runs/ reports/ && commit

Run manually:
    python autobench_cycle.py --model qwen3.5:9b
    python autobench_cycle.py --model qwen3.5:9b --no-delete   # keep for inspection
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Curated fallback models (untested, VRAM-friendly) used only if the live
# library scrape fails entirely. These are full "name:tag" strings.
FALLBACK_MODELS = [
    "llama3.2:3b", "qwen2.5:7b", "mistral:7b",
    "cogito:14b", "deepcoder:14b", "gemma2:9b",
]

_UA = {"User-Agent": "llm-autobench/1.0"}


def load_watcher():
    with open(os.path.join(REPO, "models", "registry.yaml")) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("watcher", {}), cfg.get("baseline", [])


def get_vram_free_mib():
    """Return free VRAM in MiB via nvidia-smi. Returns None on failure."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        # Take the first GPU (assume single GPU)
        return int(out.strip().split("\n")[0])
    except Exception:
        return None


def estimate_model_vram_mib(param_billions, quantization="q4_k_m"):
    """Rough VRAM estimate for a quantized model. q4_k_m ~ 0.5 * params GB + overhead."""
    # param_billions * 1024 * 0.5 (4-bit) + ~1GB context/overhead
    return int(param_billions * 512 + 1024)


def has_vram_headroom(required_mib, buffer_mib=1024):
    """Check if free VRAM >= required + buffer."""
    free = get_vram_free_mib()
    if free is None:
        return True  # if we can't check, allow (fail fast at pull time)
    return free >= (required_mib + buffer_mib)


def model_is_available_locally(model_tag):
    """Check if the model tag exists in Ollama (already pulled)."""
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
        return model_tag in out
    except Exception:
        return False


def _param_from_tag(tag):
    m = re.search(r"(\d+(?:\.\d+)?)b?$", tag, re.IGNORECASE)
    return float(m.group(1)) if m else None


def discover(watcher):
    """Return a new model tag to test, or None.

    Strategy: scrape the Ollama library for model names, resolve each model's
    available tags (concurrent), filter by size <= max_params_billions, exclude
    already-benchmarked models (present in runs/ or baseline), and require that
    the model fits the CURRENT free VRAM (so the later pull gate will not skip
    it). Prefer the largest remaining model. Long-CoT models (deepseek-r1) are
    excluded because the task battery uses fixed small token budgets.
    """
    max_b = watcher.get("max_params_billions", 14)

    # Get already tested models from runs/
    tested = set()
    runs_dir = os.path.join(REPO, "runs")
    if os.path.exists(runs_dir):
        for fn in os.listdir(runs_dir):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(runs_dir, fn)) as f:
                        data = json.load(f)
                    for r in data.get("results", []):
                        m = r.get("model", "")
                        if m.startswith("custom:ollama/"):
                            tested.add(m.split("/", 1)[1])
                except Exception:
                    pass

    # Also exclude baseline
    for b in load_watcher()[1]:
        if b.get("id", "").startswith("custom:ollama/"):
            tested.add(b["id"].split("/", 1)[1])

    cands = []

    def consider(full, param_b):
        if param_b is None or param_b > max_b:
            return
        if full in tested:
            return
        if "r1" in full.lower():  # skip long-CoT deepseek-r1 (fixed token budgets)
            return
        if not has_vram_headroom(estimate_model_vram_mib(param_b)):
            return
        cands.append((param_b, full))

    # Live scrape of the Ollama library.
    names = []
    try:
        req = urllib.request.Request("https://ollama.com/library", headers=_UA)
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        names = sorted(set(re.findall(r"/library/([a-z0-9_.-]+)", html)))
    except Exception as e:
        print(f"[discover] warning: library query failed: {e}", file=sys.stderr)

    def fetch_tags(name):
        try:
            h = urllib.request.urlopen(
                urllib.request.Request("https://ollama.com/library/" + name, headers=_UA),
                timeout=15,
            ).read().decode("utf-8", errors="ignore")
        except Exception:
            return []
        out = []
        for tg in re.findall(r"/library/" + re.escape(name) + r":([a-z0-9_.-]+)", h):
            pb = _param_from_tag(tg)
            if pb is not None:
                out.append((pb, name + ":" + tg))
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(fetch_tags, n) for n in names[:80]]
        for f in concurrent.futures.as_completed(futs):
            try:
                for pb, full in f.result():
                    consider(full, pb)
            except Exception:
                pass

    # Always consider curated fallbacks (they are full "name:tag" strings).
    for full in FALLBACK_MODELS:
        consider(full, _param_from_tag(full))

    if cands:
        cands.sort(reverse=True)  # prefer larger models
        print(f"[discover] {len(cands)} candidate(s); picking largest fitting VRAM: {cands[0][1]}",
              file=sys.stderr)
        return cands[0][1]
    return None


def build_temp_registry(model, watcher):
    """Build a temporary registry containing the discovered model + baselines,
    VRAM-trimmed so the run stays within available memory. Returns (path, kept_ids).
    """
    cfg = yaml.safe_load(open(os.path.join(REPO, "models", "registry.yaml")))
    baselines = [b for b in cfg.get("baseline", []) if b.get("enabled", True)]
    # The vision baseline (gemma4) is large and irrelevant to the text battery;
    # drop it from discovered-model runs to save VRAM.
    baselines = [b for b in baselines if "gemma4" not in b.get("id", "")]

    disc = {
        "id": "custom:ollama/" + model,
        "display_name": model + " (local, discovered)",
        "provider": "custom:ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "tier": "local",
        "context_window": 8000,
        # Broad tags so the discovered model is attempted on the full task battery.
        "tags": [
            "general", "reasoning", "coding", "writing", "summarization",
            "instruction_following", "structured_output", "communication",
            "security", "python", "json",
        ],
        "enabled": True,
    }

    def est_of(entry):
        m = re.search(r":(\d+(?:\.\d+)?)b?$", entry["id"], re.IGNORECASE)
        return estimate_model_vram_mib(float(m.group(1))) if m else 2048

    keep = [disc]
    free = get_vram_free_mib() or 0
    budget = free - est_of(disc) - 1024  # keep discovered model always
    # Include baselines (largest first) only if they fit alongside the discovered model.
    for b in sorted(baselines, key=est_of, reverse=True):
        if est_of(b) <= budget:
            keep.append(b)
            budget -= est_of(b)

    tmp = os.path.join(REPO, ".autobench_tmp_registry.yaml")
    with open(tmp, "w") as f:
        yaml.safe_dump({"baseline": keep}, f)
    return tmp, [e["id"] for e in keep]


def pull(model):
    print(f"[autobench] ollama pull {model}")
    subprocess.run(["ollama", "pull", model], check=True)


def bench(model, tier="local"):
    tmp, kept = build_temp_registry(model, load_watcher()[0])
    try:
        print(f"[autobench] bench {model} (registry includes {kept})")
        subprocess.run(
            [
                sys.executable,
                os.path.join(REPO, "scripts", "run_bench.py"),
                "--tier",
                tier,
                "--registry",
                tmp,
                "--out",
                os.path.join(REPO, "runs"),
            ],
            check=True,
        )
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def delete(model):
    print(f"[autobench] ollama rm {model}")
    subprocess.run(["ollama", "rm", model], check=True)


def commit(msg):
    subprocess.run(["git", "-C", REPO, "add", "runs/", "reports/"], check=True)
    subprocess.run(["git", "-C", REPO, "commit", "-m", msg], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="test a specific model (skip discover())")
    ap.add_argument("--no-delete", action="store_true")
    args = ap.parse_args()

    watcher, _baseline = load_watcher()
    model = args.model or discover(watcher)
    if not model:
        print("[autobench] nothing new to benchmark")
        return

    # VRAM guard before pulling (skip if already available locally)
    match = re.search(r":(\d+(?:\.\d+)?)b?$", model, re.IGNORECASE)
    if match and not model_is_available_locally(model):
        param_b = float(match.group(1))
        required = estimate_model_vram_mib(param_b)
        if not has_vram_headroom(required):
            print(f"[autobench] SKIP {model}: insufficient VRAM headroom (need ~{required}MiB)")
            return
        print(f"[autobench] VRAM check OK: {model} (~{required}MiB)")
        print(f"[autobench] pull {model}")
        pull(model)
    elif model_is_available_locally(model):
        print(f"[autobench] model {model} already available locally, skipping pull")

    print(f"[autobench] bench {model}")
    bench(model)
    if not args.no_delete and watcher.get("delete_after_bench", True):
        print(f"[autobench] delete {model}")
        delete(model)
    commit(f"autobench: {model} @ {dt.datetime.now():%Y%m%d_%H%M%S}")


if __name__ == "__main__":
    main()
