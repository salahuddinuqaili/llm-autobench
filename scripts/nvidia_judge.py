#!/usr/bin/env python3
"""NVIDIA judge pass for autobench runs.

Reads a run JSON, scores all rubric-llm tasks via meta/llama-3.3-70b-instruct
(NVIDIA NIM, free 40 RPM), then writes a markdown report.

Uses direct curl to NVIDIA's OpenAI-compatible endpoint (bypasses the slow
`hermes -z` agent loop). API key is read from Hermes's .env file.

Usage:
  python scripts/nvidia_judge.py runs/<run>.json
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

JUDGE_MODEL = "meta/llama-3.3-70b-instruct"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
REPO = Path(__file__).resolve().parent.parent

# Load NVIDIA key from Hermes .env (not in shell env)
_ENV_PATH = Path.home() / "AppData/Local/hermes/.env"
NVIDIA_API_KEY = ""
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        if line.startswith("NVIDIA_API_KEY="):
            NVIDIA_API_KEY = line.split("=", 1)[1].strip()
            break


def call_judge(prompt: str) -> str:
    """Call NVIDIA directly via curl. Returns raw response text."""
    payload = json.dumps({
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 20,
        "temperature": 0.0,
    })
    cmd = [
        "curl", "-s", "--max-time", "180", NVIDIA_URL,
        "-H", f"Authorization: Bearer {NVIDIA_API_KEY}",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=200)
    try:
        data = json.loads(res.stdout)
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: {res.stdout[:200]} ({e})"


def parse_score(text: str):
    m = re.search(r"0(?:\.\d+)?|1(?:\.0+)?", text)
    if not m:
        return None
    return max(0.0, min(1.0, float(m.group(0))))


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
    text = p.read_text()
    m = re.search(r"rubric:\s*\|?\s*\n((?:[ \t]+.*\n?)+)", text)
    if not m:
        return ""
    return re.sub(r"^[ \t]+", "", m.group(1), flags=re.MULTILINE)


def main():
    if not NVIDIA_API_KEY:
        print("ERROR: NVIDIA_API_KEY not found in Hermes .env")
        sys.exit(1)
    if len(sys.argv) < 2:
        print("usage: nvidia_judge.py <run.json>")
        sys.exit(1)

    run_path = Path(sys.argv[1])
    data = json.loads(run_path.read_text())
    results = data["results"]
    scored = []

    for r in results:
        if r.get("score") is not None:
            scored.append(r)
            continue
        task_id = r["task"]
        rubric = load_rubric(task_id)
        if not rubric:
            print(f"  [skip] no rubric for {task_id}")
            scored.append(r)
            continue
        prompt = build_judge_prompt(task_id, rubric, r.get("response", ""))
        print(f"  [judge] {task_id} ...", end=" ", flush=True)
        out = call_judge(prompt)
        score = parse_score(out)
        r["score"] = score
        r["judge"] = f"nvidia/{JUDGE_MODEL}"
        r["judge_raw"] = out[:300]
        print(score)
        scored.append(r)
        # write back incrementally so partial progress survives timeouts
        data["results"] = scored + [x for x in results if x not in scored and x.get("score") is None]
        run_path.write_text(json.dumps(data, indent=2))

    data["results"] = scored
    run_path.write_text(json.dumps(data, indent=2))

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
    out_path.write_text("\n".join(lines))
    print(f"\nReport written: {out_path}")
    print(f"Average score: {avg:.2f}")


if __name__ == "__main__":
    main()
