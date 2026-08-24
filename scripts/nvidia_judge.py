#!/usr/bin/env python3
"""NVIDIA judge pass for autobench runs.

Reads a run JSON, scores all rubric-llm tasks via meta/llama-3.3-70b-instruct
(NVIDIA NIM, free 40 RPM), then writes a markdown report.

Uses direct curl to NVIDIA's OpenAI-compatible endpoint (bypasses the slow
`hermes -z` agent loop). The API key is resolved with this precedence:
  1. env var NVIDIA_API_KEY
  2. Hermes .env (cross-platform: ~/AppData/Local/hermes/.env on Windows,
     ~/.local/share/hermes/.env or ~/.config/hermes/.env on Linux/macOS)
  3. --key CLI arg

Hardened vs v1: cross-platform key load, exponential backoff retry, larger
token budget for judge reasoning, robust float parsing, incremental write-back.

Usage:
  python scripts/nvidia_judge.py runs/<run>.json [--key SK] [--max-retries 4]
"""
import json
import os
import re
import sys
import time
import base64
import urllib.request
from pathlib import Path

import procutil

JUDGE_MODEL = "meta/llama-3.3-70b-instruct"
# Two-stage vision judging (per user direction):
#   1. ONE good local vision model looks at the image ONCE and writes a detailed
#      factual description (ground truth). We use the benchmark's best vision
#      model (minicpm-v) as the describer -- it is promoted by promote_vision_
#      model.py, so the judge reuses the fleet's chosen vision model.
#   2. The 70B TEXT judge (meta/llama-3.3-70b-instruct) scores the benchmarked
#      model's response against that description. Text-vs-text at 70B is far more
#      reliable than a small 11B vision judge scoring directly.
VISION_DESCRIBER = "minicpm-v:latest"
VISION_DESCRIBER_URL = "http://127.0.0.1:11434/api/chat"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
REPO = Path(__file__).resolve().parent.parent


def find_nvidia_key() -> str:
    """Resolve the NVIDIA API key cross-platform."""
    env_key = os.environ.get("NVIDIA_API_KEY")
    if env_key:
        return env_key.strip()

    # Candidate .env locations (Hermes stores it gitignored, not in shell env).
    candidates = [
        Path.home() / "AppData" / "Local" / "hermes" / ".env",       # Windows
        Path.home() / ".local" / "share" / "hermes" / ".env",         # Linux XDG
        Path.home() / ".config" / "hermes" / ".env",                  # Linux alt
        Path.home() / ".hermes" / ".env",                             # generic
    ]
    for cand in candidates:
        if cand.exists():
            for line in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


def call_judge(prompt: str, api_key: str, max_retries: int = 4,
               max_tokens: int = 256) -> str:
    """Call NVIDIA directly via curl with exponential backoff retry."""
    payload = json.dumps({
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    })
    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            cmd = [
                "curl", "-s", "--max-time", "180", NVIDIA_URL,
                "-H", f"Authorization: Bearer {api_key}",
                "-H", "Content-Type: application/json",
                "-d", payload,
            ]
            res = procutil.run(cmd, capture_output=True, text=True, timeout=200)
            out = res.stdout.strip()
            if not out:
                last_err = f"empty response (HTTP {res.returncode})"
                raise RuntimeError(last_err)
            data = json.loads(out)
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            if attempt < max_retries:
                backoff = 2 ** attempt
                print(f"    retry {attempt}/{max_retries} after {backoff}s ({last_err})",
                      file=sys.stderr, flush=True)
                time.sleep(backoff)
    return f"ERROR: {last_err}"


def describe_image(img_path: str, max_retries: int = 2) -> str:
    """Stage 1: one detailed, factual description of the image, used as ground
    truth for the 70B text judge.

    PREFERRED: a stored description file next to the image
    (<image>.desc.txt), baked in ONCE by a strong vision model (e.g. Claude via
    the `claude` CLI, Max quota, $0). This keeps the benchmark free of per-run
    vision calls. Falls back to a fresh Claude CLI call, then to the local
    VISION_DESCRIBER (Ollama). Descriptions are cached per path."""
    cache = describe_image._cache
    if img_path in cache:
        return cache[img_path]
    # Preferred: a stored ground-truth description alongside the image
    # (e.g. progressive_photo_user.desc.txt). Baked in once by a strong vision
    # model so the benchmark never calls a vision model per run.
    desc_path = os.path.splitext(img_path)[0] + ".desc.txt"
    if os.path.exists(desc_path):
        desc = open(desc_path, encoding="utf-8").read().strip()
        if desc:
            cache[img_path] = desc
            return desc
    prompt = ("Describe this image in thorough, factual detail: every object, "
              "its color and position, any text/labels, the scene type, and "
              "overall lighting. Be specific and literal; do not speculate.")
    # Preferred: Claude CLI (Max quota, zero marginal cost, top vision).
    try:
        cmd = ["claude", "-p", prompt, "--model", "claude-sonnet-4-5",
               "--max-turns", "1", "--output-format", "text"]
        # pass the image as a file argument Claude can read
        res = procutil.run(cmd + [img_path], capture_output=True, text=True,
                      timeout=180)
        if res.returncode == 0 and res.stdout.strip():
            desc = res.stdout.strip()
            cache[img_path] = desc
            return desc
    except Exception:
        pass
    # Fallback: local vision model via Ollama.
    try:
        with open(img_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        payload = json.dumps({
            "model": VISION_DESCRIBER,
            "messages": [{"role": "user", "content": prompt,
                          "images": [b64]}],
            "stream": False, "options": {"num_predict": 400},
        })
        req = urllib.request.Request(
            VISION_DESCRIBER_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=180).read().decode())
        desc = out.get("message", {}).get("content", "").strip()
        if desc:
            cache[img_path] = desc
            return desc
    except Exception as exc:  # noqa: BLE001 - describer is best-effort
        # This used to be `except Exception: pass`, which swallowed a NameError:
        # urllib was never imported, so the local-describer fallback could not
        # work at all and failed silently into the text-only judge path.
        print(f"  [warn] local vision describer failed: "
              f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
    return ""


describe_image._cache = {}


def build_described_judge_prompt(task_id, rubric, response, description):
    return f"""You are an objective benchmark judge. Score the MODEL RESPONSE against
the RUBRIC, using the GROUND-TRUTH IMAGE DESCRIPTION (written by a strong vision
model that actually saw the image) as the factual reference.

TASK: {task_id}

GROUND-TRUTH IMAGE DESCRIPTION (factual reference):
{description}

RUBRIC:
{rubric}

MODEL RESPONSE (a vision model's description of the same image):
{response}

Does the MODEL RESPONSE correctly describe what is in the image, per the rubric
and the ground-truth description? Return ONLY a single float between 0.0 and 1.0
(e.g. 0.85). Do not explain."""


def parse_score(text: str):
    # Prefer an explicit "score: 0.85" or "0.85/1.0" form, else first float 0..1.
    m = re.search(r"score[\"']?\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?)", text, re.I)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))
    m = re.search(r"(0(?:\.\d+)?|1(?:\.0+)?)\s*/\s*1", text)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))
    m = re.search(r"\b(0(?:\.\d+)?|1(?:\.0+)?)\b", text)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))
    return None


def build_judge_prompt(task_id, rubric, response):
    return f"""You are an objective benchmark judge. Score the model response against the rubric.

TASK: {task_id}

RUBRIC:
{rubric}

MODEL RESPONSE:
{response}

Return ONLY a single float between 0.0 and 1.0 (e.g. 0.85). Do not explain."""


def load_rubric(task_id):
    p = REPO / "tasks" / f"{task_id}.yaml"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    m = re.search(r"rubric:\s*\|?\s*\n((?:[ \t]+.*\n?)+)", text)
    if not m:
        return ""
    return re.sub(r"^[ \t]+", "", m.group(1), flags=re.MULTILINE)


def _writeback(envelope, results, scored, run_path):
    """Incremental write-back so partial progress survives timeouts.

    Writes the WHOLE envelope, not just results. It used to rebuild the file as
    {"results": ...}, which meant a judge that died midway left the run stripped
    of run_id, provenance and the recorded `skipped` coverage block - crash
    safety for scores bought by silently destroying the run metadata.
    """
    # The tail of `results` not yet processed. It used to be "every row whose
    # score is None", which quietly dropped rows the RUNNER had already scored
    # (exact / json-exact) but the judge loop had not yet walked past - so a
    # mid-judge crash lost them entirely. `scored` grows in iteration order and
    # every row is appended exactly once, so the remainder is the tail.
    pending = results[len(scored):]
    data = dict(envelope)
    data["results"] = scored + pending
    run_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def build_report(run_stem, scored):
    """Render the run report GROUPED BY MODEL.

    Fixes the attribution bug where a report was titled with one model
    (`scored[0]["model"]`) but its single table iterated *every* model's rows —
    so a two-model run showed one title over a mixed table and a blended average.
    This emits: a per-run leaderboard (one row per model), one detail section per
    model, and a Failures section — each row attributed to the model that produced it.
    """
    from collections import OrderedDict

    by_model = OrderedDict()
    for r in scored:
        by_model.setdefault(r.get("model", "unknown"), []).append(r)

    def avg_of(rows):
        vals = [r["score"] for r in rows if _is_num(r.get("score"))]
        return (sum(vals) / len(vals)) if vals else None

    models = list(by_model)
    lines = []
    lines.append(f"# autobench report — {run_stem}")
    lines.append("")
    lines.append(f"**Run:** `{run_stem}.json`  ")
    lines.append(f"**Models:** {', '.join('`' + m + '`' for m in models)}  ")
    lines.append(f"**Judge:** `nvidia/{JUDGE_MODEL}` (70B text judge) + Claude vision describer (stage 1)  ")
    lines.append("")

    # ---- Leaderboard: one row PER MODEL ----
    lines.append("## Leaderboard")
    lines.append("")
    # Tasks and draws are different numbers once a run samples N times per pair.
    # This column used to print len(rows) under a "Tasks" header, which read as
    # "qwen attempted 27 tasks" for a 9-task battery drawn 3 times.
    lines.append("| Model | Avg score | Tasks | Draws | Scored | Unscored | Avg latency |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    lb = []
    for m, rows in by_model.items():
        avg = avg_of(rows)
        scored_n = sum(1 for r in rows if _is_num(r.get("score")))
        lats = [r.get("latency_s", 0) or 0 for r in rows]
        latm = sum(lats) / len(lats) if lats else 0.0
        # Truncated / ingestion-failed rows are UNSCORED, not errors. Filing them
        # under "Errors" implied the harness broke; it means the row was withheld.
        unscored = sum(1 for r in rows if not _is_num(r.get("score")))
        ntasks = len({r.get("task") for r in rows})
        lb.append((m, avg, ntasks, len(rows), scored_n, unscored, latm))
    lb.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))  # best avg first, None last
    for m, avg, ntasks, ndraws, scored_n, unscored, latm in lb:
        avg_s = f"{avg:.2f}" if avg is not None else "—"
        lines.append(f"| `{m}` | {avg_s} | {ntasks} | {ndraws} | {scored_n} | "
                     f"{unscored or '—'} | {latm:.1f}s |")
    lines.append("")

    # ---- Per-model detail ----
    for m, rows in by_model.items():
        lines.append(f"## {m}")
        lines.append("")
        lines.append("| Task | Draw | Score | Latency | Judge reason |")
        lines.append("|---|---:|---|---|---|")
        for r in rows:
            sc = r.get("score")
            sc_s = (f"{sc:.2f}" if _is_num(sc)
                    else ("trunc" if r.get("truncated")
                          else ("no-image" if r.get("ingestion_failed") else "—")))
            lat = r.get("latency_s", 0) or 0
            reason = (r.get("judge_raw", "") or "")[:120].replace("\n", " ")
            draw = (f"{r['sample'] + 1}/{r['samples']}"
                    if r.get("samples") else "1/1")
            lines.append(f"| {r['task']} | {draw} | {sc_s} | {lat:.1f}s | {reason} |")
        lines.append("")

    # ---- Failures: errored, truncated, or unscored (honest, per SPEC §12) ----
    fails = [r for r in scored
             if r.get("error") or r.get("truncated") or r.get("ingestion_failed")
             or not _is_num(r.get("score"))]
    lines.append("## Failures")
    lines.append("")
    if not fails:
        lines.append("None.")
    else:
        for r in fails:
            why = (r.get("error") or
                   ("truncated at token budget (unscored, not 0.0)" if r.get("truncated")
                    else ("model reported no image was supplied — ingestion failure, "
                          "NOT a vision-capability score (unscored, not 0.0)"
                          if r.get("ingestion_failed")
                          else "unscored (judge returned no parseable score)")))
            lines.append(f"- **{r.get('model')} × {r.get('task')}**: {why}")
    lines.append("")

    # ---- Lifecycle ----
    lines.append("## Lifecycle")
    lines.append("")
    # This used to read "Model pulled, benchmarked on Ollama, then deleted." on
    # every report, including --baselines-only runs where nothing was pulled or
    # deleted. The judge cannot observe the lifecycle, so it no longer asserts one.
    lines.append("- Model-under-test ran locally on Ollama; the judge ran in the cloud, "
                 "so the GPU never hosted both.")
    lines.append("- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, "
                 "direct API). No paid API spend.")
    lines.append("- Pull/delete is handled by `autobench_cycle.py` and recorded in its "
                 "commit, not observable from this run file.")
    lines.append("")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file")
    ap.add_argument("--key", help="NVIDIA API key (else env/.env)")
    ap.add_argument("--max-retries", type=int, default=4)
    args = ap.parse_args()

    api_key = args.key or find_nvidia_key()
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not found (env, Hermes .env, or --key)", file=sys.stderr)
        sys.exit(1)

    run_path = Path(args.run_file)
    data = json.loads(run_path.read_text(encoding="utf-8"))
    results = data["results"]
    scored = []

    for r in results:
        # A response cut off at the token budget is a non-answer (run_bench's P0.1
        # guard already set score=null, truncated=true). NEVER let the judge score a
        # truncated chain-of-thought — that would reintroduce the exact distortion the
        # guard removes (and make the row both "scored" and a Failure). Keep it unscored.
        if r.get("truncated"):
            r.setdefault("judge", "skipped: truncated (unscored)")
            scored.append(r)
            continue
        # Same defeat pattern, second instance: run_bench flags a response that
        # claims no image was supplied as `ingestion_failed`, but the judge would
        # happily score that non-answer 0.0 — republishing a harness/ingestion
        # failure as a capability result (it dragged gemma4:e4b from ~0.95 to 0.78).
        # Keep it unscored; the Failures section reports what actually happened.
        if r.get("ingestion_failed"):
            r.setdefault("judge", "skipped: image not ingested (unscored)")
            scored.append(r)
            continue
        if r.get("score") is not None:
            scored.append(r)
            continue
        task_id = r["task"]
        rubric = load_rubric(task_id)
        if not rubric:
            print(f"  [skip] no rubric for {task_id}", file=sys.stderr)
            scored.append(r)
            continue
        # Vision tasks: Stage 1 -- describe the image ONCE with a strong cloud
        # vision model (Claude CLI, Max quota). Stage 2 -- the 70B TEXT judge
        # scores the model response against that description.
        img = r.get("image")
        if img:
            img_path = img if os.path.isabs(img) else str(REPO / img)
            try:
                description = describe_image(img_path, max_retries=args.max_retries)
                if not description:
                    print(f"  [warn] image description failed for {task_id}; "
                          f"falling back to text judge", file=sys.stderr)
                    prompt = build_judge_prompt(task_id, rubric, r.get("response", ""))
                else:
                    prompt = build_described_judge_prompt(
                        task_id, rubric, r.get("response", ""), description)
                print(f"  [judge+vision] {task_id} ...", end=" ", flush=True)
                out = call_judge(prompt, api_key, max_retries=args.max_retries)
                score = parse_score(out)
                r["score"] = score
                r["judge"] = f"nvidia/{JUDGE_MODEL}" + ("+claude-vision" if description else "")
                r["judge_raw"] = out[:300]
                print(score, file=sys.stderr, flush=True)
                scored.append(r)
                _writeback(data, results, scored, run_path)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] vision describe failed ({e}); text judge",
                      file=sys.stderr)
        prompt = build_judge_prompt(task_id, rubric, r.get("response", ""))
        print(f"  [judge] {task_id} ...", end=" ", flush=True)
        out = call_judge(prompt, api_key, max_retries=args.max_retries)
        score = parse_score(out)
        r["score"] = score
        r["judge"] = f"nvidia/{JUDGE_MODEL}"
        r["judge_raw"] = out[:300]
        print(score, file=sys.stderr, flush=True)
        scored.append(r)
        _writeback(data, results, scored, run_path)

    data["results"] = scored
    run_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    report = build_report(run_path.stem, scored)
    out_path = REPO / "reports" / f"{run_path.stem}.md"
    out_path.write_text(report, encoding="utf-8")

    overall = [r["score"] for r in scored if _is_num(r.get("score"))]
    avg = sum(overall) / len(overall) if overall else 0.0
    print(f"\nReport written: {out_path}")
    print(f"Overall average (all scored rows, all models): {avg:.2f}")


if __name__ == "__main__":
    main()
