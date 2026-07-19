#!/usr/bin/env python3
"""
llm-autobench judge & report generator.

Reads a run JSON from runs/<run_id>.json, scores all rubric-llm tasks using the
configured free judge model (NVIDIA NIM meta/llama-3.3-70b-instruct, free 40 RPM),
and writes a markdown report to reports/<run_id>.md with:
  - Header (run_id, timestamp, models, tasks)
  - Leaderboard table
  - Per-model breakdown
  - Lifecycle info (pulled/deleted)
  - Failures

Run manually:
    python scripts/judge_report.py runs/20260716_214321.json

NOTE: for the canonical NVIDIA judging path, prefer scripts/nvidia_judge.py
(this module is kept for the OpenRouter-fallback reporting shape and legacy runs).
"""
import argparse
import datetime as dt
import json
import os
import sys

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_run(run_path):
    with open(run_path) as f:
        return json.load(f)


def load_judge_config():
    with open(os.path.join(REPO, "models", "registry.yaml")) as f:
        return yaml.safe_load(f).get("watcher", {}).get("judge", "nvidia/meta/llama-3.3-70b-instruct")


def call_judge(judge_model, prompt, max_tokens=1024):
    """Call the judge model via OpenRouter (free tier). Returns text or None."""
    try:
        from openai import OpenAI
        # OpenRouter endpoint
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),  # needs to be set
        )
        resp = client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"JUDGE_ERROR: {e}"


def score_with_rubric(judge_model, task, response):
    """Score a response using the judge model and the task's rubric."""
    rubric = task.get("scoring", {}).get("rubric", "")
    if not rubric:
        return None, "no rubric"

    prompt = f"""You are an impartial evaluator. Score the following response on a scale of 0.0 to 1.0 based on the rubric.

RUBRIC:
{rubric}

RESPONSE:
{response or "(empty)"}

Return ONLY a JSON object with two keys:
  "score": <float 0.0-1.0>
  "reason": "<one-sentence justification>"

No extra text, no markdown."""
    result = call_judge(judge_model, prompt, max_tokens=256)
    if not result or result.startswith("JUDGE_ERROR"):
        return None, result or "empty judge response"
    try:
        data = json.loads(result)
        score = float(data.get("score", 0))
        reason = data.get("reason", "")
        return max(0.0, min(1.0, score)), reason
    except Exception as e:
        return None, f"parse error: {e}"


def generate_report(run_data, judge_model):
    """Generate the markdown report string."""
    run_id = run_data["run_id"]
    results = run_data["results"]
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group by model
    by_model = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)

    # Compute average scores per model (only scored tasks)
    leaderboard = []
    for model, res_list in by_model.items():
        scored = [r for r in res_list if r["score"] is not None]
        if scored:
            avg = sum(r["score"] for r in scored) / len(scored)
            avg_lat = sum(r["latency_s"] for r in res_list) / len(res_list)
        else:
            avg = None
            avg_lat = sum(r["latency_s"] for r in res_list) / len(res_list) if res_list else 0
        errors = [r for r in res_list if r["error"]]
        leaderboard.append({
            "model": model, "avg_score": avg, "avg_latency": avg_lat,
            "tasks": len(res_list), "scored": len(scored), "errors": len(errors),
        })

    # Sort by avg_score desc (None last)
    leaderboard.sort(key=lambda x: (x["avg_score"] is None, -(x["avg_score"] or 0)))

    # Build markdown
    md = []
    md.append(f"# llm-autobench Report — {run_id}")
    md.append(f"**Generated:** {ts}  \n")

    # Leaderboard
    md.append("## Leaderboard")
    md.append("| Model | Avg Score | Avg Latency (s) | Tasks | Scored | Errors |")
    md.append("|-------|-----------|-----------------|-------|--------|--------|")
    for lb in leaderboard:
        score_str = f"{lb['avg_score']:.2f}" if lb['avg_score'] is not None else "—"
        md.append(f"| {lb['model']} | {score_str} | {lb['avg_latency']:.1f} | {lb['tasks']} | {lb['scored']} | {lb['errors']} |")
    md.append("")

    # Per-model detail
    md.append("## Per-Model Details")
    for model, res_list in by_model.items():
        md.append(f"### {model}")
        for r in res_list:
            score_str = f"{r['score']:.2f}" if r['score'] is not None else "±"
            md.append(f"- **{r['task']}** — score: {score_str} | latency: {r['latency_s']:.1f}s")
            if r["error"]:
                md.append(f"  - ⚠️ ERROR: {r['error']}")
            resp_preview = (r["response"] or "(empty)")[:200].replace("\n", " ")
            md.append(f"  - response: `{resp_preview}...`")
        md.append("")

    # Lifecycle
    md.append("## Lifecycle")
    md.append("- Models tested: " + ", ".join(by_model.keys()))
    md.append("- Judge model: " + judge_model)
    md.append("- Free judge: yes (OpenRouter free tier)")
    md.append("- Local compute: Ollama (127.0.0.1:11434)")
    md.append("")

    # Failures
    all_errors = [(r["model"], r["task"], r["error"]) for r in results if r["error"]]
    if all_errors:
        md.append("## Failures")
        for model, task, err in all_errors:
            md.append(f"- **{model} × {task}**: {err}")
    else:
        md.append("## Failures")
        md.append("None.")

    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file", nargs="?", help="Path to runs/<run_id>.json (defaults to latest)")
    args = ap.parse_args()

    runs_dir = os.path.join(REPO, "runs")
    if args.run_file:
        run_path = args.run_file
    else:
        files = sorted([f for f in os.listdir(runs_dir) if f.endswith(".json")])
        if not files:
            print("No run files found", file=sys.stderr)
            return 1
        run_path = os.path.join(runs_dir, files[-1])

    run_data = load_run(run_path)
    judge_model = load_judge_config()

    # Score rubric-llm tasks
    tasks_dir = os.path.join(REPO, "tasks")
    task_map = {}
    for fn in os.listdir(tasks_dir):
        if fn.endswith((".yaml", ".yml")):
            with open(os.path.join(tasks_dir, fn)) as f:
                t = yaml.safe_load(f)
            task_map[t["id"]] = t

    print(f"[judge] Scoring run {run_data['run_id']} with judge {judge_model}")
    for r in run_data["results"]:
        if r["error"] or not r["response"]:
            continue
        task = task_map.get(r["task"])
        if not task:
            continue
        method = task.get("scoring", {}).get("method", "rubric-llm")
        if method == "rubric-llm" and r["score"] is None:
            score, reason = score_with_rubric(judge_model, task, r["response"])
            if score is not None:
                r["score"] = score
                r["score_reason"] = reason
                print(f"  {r['model']} × {r['task']}: {score:.2f} ({reason})")
            else:
                r["score"] = None
                r["score_reason"] = reason
                print(f"  {r['model']} × {r['task']}: FAILED ({reason})")

    # Write updated run JSON (with scores)
    with open(run_path, "w") as f:
        json.dump(run_data, f, indent=2)

    # Generate markdown report
    report_md = generate_report(run_data, judge_model)
    reports_dir = os.path.join(REPO, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"{run_data['run_id']}.md")
    with open(report_path, "w") as f:
        f.write(report_md)

    print(f"[judge] Report written to {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())