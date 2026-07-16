#!/usr/bin/env python3
"""
llm-autobench autonomous lifecycle (the "autobench" pipeline).

Stages — the FREE Hermes agent orchestrating the cron does discovery decisions,
judging, and reporting. This script does the mechanical LOCAL work:

  1. discover()  -> find a new model tag not yet benchmarked
  2. pull()      -> `ollama pull <model>` if it fits VRAM
  3. bench()     -> calls run_bench.py for that model (Ollama does the compute)
  4. judge/report-> done by the agent reading runs/<id>.json (see CLAUDE.md)
  5. delete()    -> `ollama rm <model>` to free disk/VRAM
  6. commit()    -> git add runs/ reports/ && commit

Run manually:
    python autobench_cycle.py --model qwen3.5:9b
    python autobench_cycle.py --model qwen3.5:9b --no-delete   # keep for inspection
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def discover(watcher):
    """Return a new model tag to test, or None.

    Strategy: query Ollama library for popular tags, filter by size <= max_params_billions,
    exclude already-benchmarked models (present in runs/ or baseline).
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

    # Query Ollama library (simple HTML scrape)
    try:
        url = "https://ollama.com/library"
        req = urllib.request.Request(url, headers={"User-Agent": "llm-autobench/1.0"})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        # Find model tags like /library/qwen3.5:9b
        model_tags = re.findall(r'/library/([a-z0-9_.-]+:[a-z0-9_.-]+)', html)
        candidates = []
        for tag in sorted(set(model_tags)):
            # Heuristic: tag like qwen3.5:9b -> extract param count
            match = re.search(r':(\d+(?:\.\d+)?)b?$', tag, re.IGNORECASE)
            if match:
                param_b = float(match.group(1))
                if param_b <= max_b and tag not in tested:
                    candidates.append((param_b, tag))
        if candidates:
            candidates.sort(reverse=True)  # prefer larger models
            return candidates[0][1]
    except Exception as e:
        print(f"[discover] warning: library query failed: {e}", file=sys.stderr)
    return None


def pull(model):
    print(f"[autobench] ollama pull {model}")
    subprocess.run(["ollama", "pull", model], check=True)


def bench(model, tier="local"):
    subprocess.run(
        [
            sys.executable,
            os.path.join(REPO, "scripts", "run_bench.py"),
            "--tier",
            tier,
            "--out",
            os.path.join(REPO, "runs"),
        ],
        check=True,
    )


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
    match = re.search(r':(\d+(?:\.\d+)?)b?$', model, re.IGNORECASE)
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