#!/usr/bin/env python3
"""
llm-autobench autonomous lifecycle (the "autobench" pipeline).

Stages — the FREE Hermes agent orchestrating the cron does discovery decisions,
judging, and reporting. This script does the mechanical LOCAL work:

  1. discover()  -> find a new model tag not yet benchmarked (VRAM-aware)
  2. pull()      -> `ollama pull <model>` if it fits VRAM
  3. bench()     -> calls run_bench.py for the discovered subject only
                    (baselines refresh via --baselines-only, not co-appended)
  4. report()    -> score_run.py (free NVIDIA judge) then aggregate_results.py
                    --inject README.md. Wired in-process as of P1.2/F1.2: this
                    used to be an agent session job, which is why 80 runs of data
                    never reached the published README.
  5. delete()    -> `ollama rm <model>` to free disk/VRAM
  6. commit()    -> git add runs/ reports/ README.md && commit

Run manually:
    python autobench_cycle.py --model qwen3.5:9b
    python autobench_cycle.py --model qwen3.5:9b --no-delete   # keep for inspection
    python autobench_cycle.py --baselines-only --samples 3     # no pull, N=3 draws
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

import procutil

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
        out = procutil.check_output(
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
    """Check if free VRAM >= required + buffer.

    Fails CLOSED: if the nvidia-smi probe fails we cannot prove there is room, so
    we refuse the pull rather than risk OOM-ing a shared 12GB box mid-bench.
    """
    free = get_vram_free_mib()
    if free is None:
        print("[autobench] VRAM probe failed (nvidia-smi unavailable); "
              "failing CLOSED — skipping pull to protect the shared GPU",
              file=sys.stderr)
        return False
    return free >= (required_mib + buffer_mib)


def _tag_size_b(tag):
    """Extract the model parameter size in billions from a tag, robust to
    size suffixes such as '-instruct' (e.g. 'qwen2.5:7b-instruct' -> 7.0,
    'gemma4:e4b' -> 4.0). Returns None when no size indicator is present.
    """
    m = re.search(r"(\d+(?:\.\d+)?)b", tag, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _local_tags():
    """Return the list of locally-pulled Ollama tags (first column of `ollama list`).

    Returns [] on any failure so callers fail closed (treat as "not present").
    """
    try:
        out = procutil.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
        return [line.split()[0] for line in out.splitlines() if line.split()]
    except Exception:
        return []


def model_is_available_locally(model_tag):
    """Check if the exact model tag exists in Ollama (already pulled).

    Exact match only (SPEC 13.2 / D10 / M0.2). Same-size variants such as
    'qwen2.5:7b' vs 'qwen2.5:7b-instruct' are NOT interchangeable — family or
    size-strict fuzzy matching silently re-benches the wrong local model and
    livelocks discovery. Missing tag means pull that exact tag, or honest skip.

    Returns the local tag name if found, or False.
    """
    local_tags = _local_tags()
    if model_tag in local_tags:
        return model_tag
    return False


def _other_size_local(model_tag):
    """Return a local tag sharing model_tag's base name but a DIFFERENT parameter
    size (e.g. 'gemma4:e4b' when 'gemma4:12b' is requested), or None.

    Used only to emit an honest log line when we cannot run the requested model,
    so a cycle never silently substitutes a wrong-sized local model.
    """
    base = model_tag.split(":")[0]
    req_param = _tag_size_b(model_tag)
    for tag in _local_tags():
        if tag == model_tag:
            continue
        if not tag.startswith(base + ":"):
            continue
        loc_param = _tag_size_b(tag)
        if req_param is None or loc_param is None or loc_param != req_param:
            return tag
    return None


def _param_from_tag(tag):
    """Parse parameter size in billions from an Ollama tag or name:tag.

    Handles sized tags with suffixes (codellama:7b-instruct -> 7) and MoE
    products (mixtral:8x7b -> 56). Returns None for unsized tags (latest, etc.)
    so discover can drop them explicitly (F1.3 / M0.3).
    """
    part = tag.split(":")[-1] if ":" in tag else tag
    moe = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*b", part, re.IGNORECASE)
    if moe:
        return float(moe.group(1)) * float(moe.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)b", part, re.IGNORECASE)
    return float(m.group(1)) if m else None


def discover(watcher):
    """Return a new model tag to test, or None.

    Strategy: scrape the Ollama library for model names, resolve each model's
    available tags (concurrent), filter by watcher.size_band (default 6-10B) and
    the absolute max_params_billions VRAM ceiling, exclude already-benchmarked
    models (present in runs/ or baseline), and require CURRENT free VRAM headroom.
    Prefer untested-in-band tags with a deterministic (lexicographic) tie-break —
    never "largest that fits". Unsized tags are logged and dropped (F1.3).
    Long-CoT models (deepseek-r1) are excluded (fixed token budgets).
    """
    max_b = watcher.get("max_params_billions", 14)
    band = watcher.get("size_band") or {}
    band_min = float(band["min"]) if band.get("min") is not None else None
    band_max = float(band["max"]) if band.get("max") is not None else None

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
        if param_b is None:
            print(f"[discover] drop unsized tag: {full}", file=sys.stderr)
            return
        if param_b > max_b:
            return
        if band_min is not None and param_b < band_min:
            return
        if band_max is not None and param_b > band_max:
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
            full = name + ":" + tg
            pb = _param_from_tag(tg)
            if pb is None:
                print(f"[discover] drop unsized tag: {full}", file=sys.stderr)
                continue
            out.append((pb, full))
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
        # Untested-in-band already filtered; deterministic tie-break by tag name.
        # Do NOT prefer larger (M0.1 / DECISIONS 2026-08-24).
        cands.sort(key=lambda t: t[1])
        band_note = ""
        if band_min is not None or band_max is not None:
            band_note = f" in size_band [{band_min},{band_max}]"
        print(f"[discover] {len(cands)} candidate(s){band_note}; "
              f"picking untested (deterministic): {cands[0][1]}",
              file=sys.stderr)
        return cands[0][1]
    return None


def build_temp_registry(model, watcher):
    """Build a temporary registry containing ONLY the subject model.

    Discovery / `--model` cycles measure one subject per night. Baselines are
    not co-appended here — refresh them with `--baselines-only` (multi-baseline
    path; no pull/delete of baselines). `watcher` is accepted for call-site
    compatibility and unused. Returns (path, kept_ids).
    """
    cfg = yaml.safe_load(open(os.path.join(REPO, "models", "registry.yaml")))

    disc = {
        "id": "custom:ollama/" + model,
        "display_name": model + " (local, discovered)",
        "provider": "custom:ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "tier": "local",
        "context_window": 8000,
        # Full task battery, read from registry.yaml `battery_tags` — the SAME list
        # the baselines carry. Hardcoding it here is what let discovered models be
        # measured on 9 tasks while baselines got 4 (see DECISIONS.md 2026-08-15).
        "tags": list(cfg.get("battery_tags") or []),
        "enabled": True,
    }
    if not disc["tags"]:
        raise SystemExit(
            "registry.yaml is missing `battery_tags`; refusing to run rather than "
            "silently benchmark the discovered model on zero tasks.")

    keep = [disc]
    tmp = os.path.join(REPO, ".autobench_tmp_registry.yaml")
    with open(tmp, "w") as f:
        yaml.safe_dump({"baseline": keep}, f)
    return tmp, [e["id"] for e in keep]


def pull(model):
    print(f"[autobench] ollama pull {model}")
    procutil.run(["ollama", "pull", model], check=True)


def _runs_snapshot():
    import glob
    return {os.path.basename(p) for p in glob.glob(os.path.join(REPO, "runs", "*.json"))}


def _new_run_since(before):
    """The run file this cycle produced, identified by diff rather than mtime."""
    new = sorted(_runs_snapshot() - before)
    return os.path.join(REPO, "runs", new[-1]) if new else None


def bench(model, tier="local", samples=1):
    """Benchmark the discovered subject only (no baseline co-append). Returns the
    path of the run file produced, so the caller can judge exactly that file."""
    tmp, kept = build_temp_registry(model, load_watcher()[0])
    before = _runs_snapshot()
    try:
        print(f"[autobench] bench {model} (registry includes {kept})")
        procutil.run(
            [
                sys.executable,
                os.path.join(REPO, "scripts", "run_bench.py"),
                "--tier",
                tier,
                "--registry",
                tmp,
                "--out",
                os.path.join(REPO, "runs"),
                "--samples",
                str(samples),
            ],
            check=True,
        )
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return _new_run_since(before)


def bench_baselines(tier="local", samples=1):
    """Run the committed registry baselines with no pull and no delete. This is
    the entry point the README documents as --baselines-only, which until now did
    not exist as a flag."""
    before = _runs_snapshot()
    print(f"[autobench] bench baselines from models/registry.yaml (samples={samples})")
    procutil.run(
        [
            sys.executable,
            os.path.join(REPO, "scripts", "run_bench.py"),
            "--tier", tier,
            "--registry", os.path.join(REPO, "models", "registry.yaml"),
            "--out", os.path.join(REPO, "runs"),
            "--samples", str(samples),
        ],
        check=True,
    )
    return _new_run_since(before)


def report(run_path):
    """Judge the run, then refresh the published aggregate (P1.2 / F1.2).

    This is the step that used to live in an agent session, which is why 80 runs
    of data never reached the README. A cycle that benches but does not score and
    publish is a cycle whose output nobody can read.

    Judging failure is FATAL: an unscored run must never be aggregated as if it
    had been scored.
    """
    if not run_path or not os.path.exists(run_path):
        print("[autobench] no run file produced; nothing to judge", file=sys.stderr)
        return False
    print(f"[autobench] judge {os.path.basename(run_path)}")
    j = procutil.run(
        [sys.executable, os.path.join(REPO, "scripts", "score_run.py"), run_path])
    if j.returncode != 0:
        print("[autobench] JUDGE FAILED - run is on disk but UNSCORED; refusing to "
              "aggregate it as if it were scored", file=sys.stderr)
        return False
    print("[autobench] aggregate -> README.md")
    a = procutil.run(
        [sys.executable, os.path.join(REPO, "scripts", "aggregate_results.py"),
         "--inject", "README.md"], cwd=REPO)
    return a.returncode == 0


def delete(model):
    print(f"[autobench] ollama rm {model}")
    procutil.run(["ollama", "rm", model], check=True)


def commit(msg):
    # README carries the injected aggregate, so it is part of the run product,
    # not an unrelated edit that happens to be dirty.
    procutil.run(["git", "-C", REPO, "add", "runs/", "reports/", "README.md"],
                   check=True)
    staged = procutil.run(["git", "-C", REPO, "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout.strip()
    if not staged:
        print("[autobench] nothing staged; skipping commit")
        return
    procutil.run(["git", "-C", REPO, "commit", "-m", msg], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="test a specific model (skip discover())")
    ap.add_argument("--no-delete", action="store_true")
    ap.add_argument("--baselines-only", action="store_true",
                    help="bench the registry baselines only: no discover, no pull, "
                         "no delete")
    ap.add_argument("--samples", type=int, default=1,
                    help="draws per (model, task); >1 makes variance measurable")
    ap.add_argument("--no-report", action="store_true",
                    help="skip judge+aggregate+commit (nightly.py runs those "
                         "itself, with per-stage logging)")
    args = ap.parse_args()

    watcher, _baseline = load_watcher()

    # Baselines-only: a full local cycle with no model lifecycle at all.
    if args.baselines_only:
        run_path = bench_baselines(samples=args.samples)
        if args.no_report:
            return
        if not report(run_path):
            raise SystemExit(1)
        commit(f"autobench: baselines @ {dt.datetime.now():%Y%m%d_%H%M%S} "
               f"(N={args.samples})")
        return

    model = args.model or discover(watcher)
    if not model:
        print("[autobench] nothing new to benchmark")
        return

    # VRAM guard before pulling (skip if already available locally)
    already_local = model_is_available_locally(model)
    param_b = _param_from_tag(model)
    pulled = False
    if param_b is not None and not already_local:
        required = estimate_model_vram_mib(param_b)
        if not has_vram_headroom(required):
            note = ""
            other = _other_size_local(model)
            if other:
                note = (f" (note: '{other}' is present locally but is a different "
                        f"size and is NOT a substitute for '{model}')")
            print(f"[autobench] SKIP {model}: insufficient VRAM headroom "
                  f"(need ~{required}MiB){note}")
            return
        print(f"[autobench] VRAM check OK: {model} (~{required}MiB)")
        print(f"[autobench] pull {model}")
        pull(model)
        pulled = True
    elif already_local:
        print(f"[autobench] model {model} already available locally, skipping pull")

    print(f"[autobench] bench {model}")
    run_path = bench(model, samples=args.samples)
    # Only delete models we pulled — never delete pre-existing local models
    if pulled and not args.no_delete and watcher.get("delete_after_bench", True):
        print(f"[autobench] delete {model}")
        delete(model)
    elif not pulled:
        print(f"[autobench] skipping delete — model was pre-existing locally")
    if args.no_report:
        return
    if not report(run_path):
        raise SystemExit(1)
    commit(f"autobench: {model} @ {dt.datetime.now():%Y%m%d_%H%M%S}")


if __name__ == "__main__":
    main()
