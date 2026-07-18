#!/usr/bin/env python3
"""
llm-autobench harness (starter skeleton).

Loads models/registry.yaml + tasks/*.yaml, then for each enabled model x each
matching task: calls the model, scores the response, and writes:
  - runs/<run_id>.json   (raw)
  - reports/<run_id>.md  (summary)

This is a STARTING POINT, not a finished runner:
  - call_model() has a real OpenAI-compatible path for local/custom models
    (verified working against Ollama on 127.0.0.1:11434).
  - The Anthropic (Claude Max) path is stubbed: wire it to Hermes's OAuth-routed
    client or the Anthropic SDK with `auth=oauth`, NOT an API key.
  - Scoring is currently a placeholder; implement exact / reference-compare /
    rubric-llm per task.scoring.method.

Run:  python run_bench.py --tier local,free
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_registry(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    # New registry format: baseline: [] + watcher: {}
    models = data.get("baseline", [])
    # Also support legacy "models:" key for backwards compat
    if not models:
        models = data.get("models", [])
    return models


def load_tasks(task_dir):
    tasks = []
    for fn in sorted(os.listdir(task_dir)):
        if fn.endswith((".yaml", ".yml")):
            with open(os.path.join(task_dir, fn)) as f:
                tasks.append(yaml.safe_load(f))
    return tasks


def call_model(model, prompt, max_tokens):
    """Call a model. Returns (text, latency_s, error)."""
    # Local / custom Ollama endpoint. We call Ollama's NATIVE /api/chat REST
    # endpoint directly (no OpenAI SDK) so the harness has zero third-party
    # dependencies and never breaks on a missing/broken `pydantic_core`.
    if model.get("provider", "").startswith("custom"):
        try:
            ollama_model = model["id"]
            if ollama_model.startswith("custom:ollama/"):
                ollama_model = ollama_model.split("/", 1)[1]
            base = model.get("base_url", "http://127.0.0.1:11434/v1")
            # registry base_url ends in /v1 (OpenAI-style); Ollama's native API
            # lives at the root. Normalise either form.
            base = base.replace("/v1", "").rstrip("/")
            url = base + "/api/chat"
            payload = {
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            t0 = dt.datetime.now()
            raw = urllib.request.urlopen(req, timeout=600).read().decode("utf-8")
            latency = (dt.datetime.now() - t0).total_seconds()
            resp = json.loads(raw)
            msg = resp.get("message", {})
            # Qwen3.x / DeepSeek reasoning models may emit thinking tokens in a
            # separate `thinking` field and leave `content` empty.
            text = msg.get("content") or ""
            if not text.strip():
                text = msg.get("thinking") or ""
            return text, latency, None
        except Exception as e:
            return None, 0.0, f"ollama api error: {e}"
    # Nous free / Anthropic premium: route through Hermes's auth, not raw keys.
    # TODO: integrate with Hermes gateway client (OAuth for anthropic).
    return None, 0.0, f"provider {model.get('provider')} not wired in skeleton"


def score(task, response):
    """Placeholder scorer. Implement exact/reference-compare/rubric-llm."""
    method = task.get("scoring", {}).get("method", "rubric-llm")
    if method == "exact":
        expected = task.get("expected", {}).get("answer")
        return 1.0 if response and expected and expected in response else 0.0
    # rubric-llm / reference-compare: implement with a scorer model.
    return None  # None = unscored (report as ±)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=os.path.join(REPO, "models", "registry.yaml"))
    ap.add_argument("--tasks", default=os.path.join(REPO, "tasks"))
    ap.add_argument("--out", default=os.path.join(REPO, "runs"))
    ap.add_argument("--tier", default=None, help="comma list to filter, e.g. local,free")
    args = ap.parse_args()

    models = load_registry(args.registry)
    tasks = load_tasks(args.tasks)
    if args.tier:
        wanted = set(args.tier.split(","))
        models = [m for m in models if m.get("tier") in wanted]
    models = [m for m in models if m.get("enabled", True)]

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    for model in models:
        for task in tasks:
            mtags = set(model.get("tags", []))
            ttags = set(task.get("tags", []))
            if not (mtags & ttags) and not task.get("requires_frontier"):
                continue
            text, latency, err = call_model(model, task["prompt"], task.get("max_tokens", 512))
            sc = score(task, text) if text else None
            results.append({
                "model": model["id"], "task": task["id"],
                "response": text, "latency_s": latency,
                "score": sc, "error": err,
            })
            print(f"[{run_id}] {model['id']} x {task['id']}: "
                  f"{'ERR' if err else ('score='+str(sc) if sc is not None else 'unscored')}")

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{run_id}.json"), "w") as f:
        json.dump({"run_id": run_id, "results": results}, f, indent=2)
    # TODO: generate reports/<run_id>.md from results (leaderboard + cost split).
    print(f"Wrote {args.out}/{run_id}.json  ({len(results)} model/task pairs)")


if __name__ == "__main__":
    main()
