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
import subprocess
import sys
import time
import base64
from pathlib import Path

JUDGE_MODEL = "meta/llama-3.3-70b-instruct"
# Vision judge: a multimodal NVIDIA NIM model used for tasks that carry an
# `image:`. It actually SEES the image and scores the model's response against
# what is really in the picture (stronger than inferring from text alone).
VISION_JUDGE_MODEL = "meta/llama-3.2-11b-vision-instruct"
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
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=200)
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


def call_vision_judge(prompt: str, image_b64: str, image_media: str,
                      api_key: str, max_retries: int = 4,
                      max_tokens: int = 256) -> str:
    """Multimodal judge: sends the image + prompt to the vision judge model.
    `image_media` is e.g. 'image/png' or 'image/jpeg'."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": f"data:{image_media};base64,{image_b64}"}},
    ]
    payload = json.dumps({
        "model": VISION_JUDGE_MODEL,
        "messages": [{"role": "user", "content": content}],
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
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=200)
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


def build_vision_judge_prompt(task_id, rubric, response):
    return f"""You are an objective benchmark judge WITH VISION. You can see the image.

TASK: {task_id}

RUBRIC (what the image actually contains / what a correct answer looks like):
{rubric}

MODEL RESPONSE (a vision model's description of the image):
{response}

Look at the image yourself. Does the MODEL RESPONSE correctly describe what is
actually in the image, per the rubric? Return ONLY a single float between 0.0
and 1.0 (e.g. 0.85). Do not explain."""


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


def _writeback(results, scored, run_path):
    """Incremental write-back so partial progress survives timeouts."""
    pending = [x for x in results if x.get("score") is None]
    data = {"results": scored + pending}
    run_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
        if r.get("score") is not None:
            scored.append(r)
            continue
        task_id = r["task"]
        rubric = load_rubric(task_id)
        if not rubric:
            print(f"  [skip] no rubric for {task_id}", file=sys.stderr)
            scored.append(r)
            continue
        # Vision tasks: the judge SEES the image (multimodal judge).
        img = r.get("image")
        if img:
            img_path = img if os.path.isabs(img) else str(REPO / img)
            try:
                with open(img_path, "rb") as fh:
                    img_b64 = base64.b64encode(fh.read()).decode("utf-8")
                media = "image/png" if img_path.lower().endswith(".png") else "image/jpeg"
                prompt = build_vision_judge_prompt(task_id, rubric, r.get("response", ""))
                print(f"  [vision-judge] {task_id} ...", end=" ", flush=True)
                out = call_vision_judge(prompt, img_b64, media, api_key,
                                        max_retries=args.max_retries)
                score = parse_score(out)
                r["score"] = score
                r["judge"] = f"nvidia/{VISION_JUDGE_MODEL}"
                r["judge_raw"] = out[:300]
                print(score, file=sys.stderr, flush=True)
                scored.append(r)
                _writeback(results, scored, run_path)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] vision-judge failed ({e}); falling back to text judge",
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
        _writeback(results, scored, run_path)

    data["results"] = scored
    run_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    model = scored[0]["model"] if scored else "unknown"
    scores = [r["score"] for r in scored if r.get("score") is not None]
    avg = sum(scores) / len(scores) if scores else 0.0

    lines = []
    lines.append(f"# autobench report — {model}")
    lines.append("")
    lines.append(f"**Run:** `{run_path.name}`  ")
    lines.append(f"**Judge:** `nvidia/{JUDGE_MODEL}` (NVIDIA NIM, free 40 RPM)  ")
    lines.append(f"**Average score:** `{avg:.2f}` / 1.00")
    lines.append("")
    lines.append("## Per-task")
    lines.append("")
    lines.append("| Task | Score | Latency | Judge reason |")
    lines.append("|---|---|---|---|")
    for r in scored:
        sc = r.get("score")
        sc_s = f"{sc:.2f}" if sc is not None else "—"
        lat = r.get("latency_s", 0)
        reason = (r.get("judge_raw", "") or "")[:120].replace("\n", " ")
        lines.append(f"| {r['task']} | {sc_s} | {lat:.1f}s | {reason} |")
    lines.append("")
    lines.append("## Lifecycle")
    lines.append("")
    lines.append("- Model pulled, benchmarked on Ollama, then deleted.")
    lines.append("- Judge: nvidia/meta/llama-3.3-70b-instruct (NVIDIA NIM, free tier, direct API).")
    lines.append("")

    out_path = REPO / "reports" / f"{run_path.stem}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {out_path}")
    print(f"Average score: {avg:.2f}")


if __name__ == "__main__":
    main()
