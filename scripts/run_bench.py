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
import re
import sys
import urllib.request

import yaml

import procutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Bump when the shape of a run record changes, so a reader can tell which records
# are comparable. Runs written before this existed carry no provenance block at all.
SCHEMA_VERSION = 1


def _shell(args, default=""):
    """Best-effort capture; provenance must never break a benchmark run."""
    try:
        p = procutil.run(args, capture_output=True, text=True, timeout=15, cwd=REPO)
        return p.stdout.strip() if p.returncode == 0 else default
    except Exception:
        return default


def build_provenance():
    """What a reader needs to know to decide whether two runs are comparable.

    Deliberately records hardware CLASS (GPU model, VRAM) and never machine
    identity -- no hostname, no username, no absolute paths. This repo is public.
    """
    import hashlib

    tasks_dir = os.path.join(REPO, "tasks")
    battery = ""
    try:
        h = hashlib.sha256()
        for name in sorted(os.listdir(tasks_dir)):
            if name.endswith(".yaml"):
                with open(os.path.join(tasks_dir, name), "rb") as f:
                    h.update(name.encode()); h.update(f.read())
        battery = h.hexdigest()[:12]
    except OSError:
        pass

    gpu = _shell(["nvidia-smi", "--query-gpu=name,memory.total",
                  "--format=csv,noheader"]).splitlines()
    ollama = _shell(["ollama", "--version"])

    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "pipeline_sha": _shell(["git", "rev-parse", "--short", "HEAD"]),
        "pipeline_dirty": bool(_shell(["git", "status", "--porcelain"])),
        "task_battery_sha": battery,
        "task_count": len([n for n in os.listdir(tasks_dir)
                           if n.endswith(".yaml")]) if os.path.isdir(tasks_dir) else None,
        # The judge is asserted here so a run can be checked rather than trusted.
        "judge": {"provider": "nvidia_nim", "model": "meta/llama-3.3-70b-instruct"},
        "hardware": {"gpu": gpu[0].strip() if gpu else None},
        "ollama_version": ollama or None,
    }


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


def call_model(model, prompt, max_tokens, image_path=None):
    """Call a model. Returns (text, latency_s, error, meta).

    `meta` carries provider signals used downstream: `done_reason` (Ollama's
    stop reason — "stop" vs "length"/truncated), and token counts for telemetry.
    An empty dict is returned when a provider does not expose them.
    """
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
            message = {"role": "user", "content": prompt}
            payload = {
                "model": ollama_model,
                "messages": [message],
                "stream": False,
                "options": {"num_predict": max_tokens},
                # Thinking OFF is this benchmark's standard condition, for two
                # measured reasons (see DECISIONS.md 2026-08-15):
                #   1. Ollama DROPS the image when thinking is on, so a vision
                #      model reports "no image provided" and scores 0 for what is
                #      a harness artefact, not a capability (gemma4:e4b).
                #   2. Thinking does not always terminate: qwen3.5:9b spends 4730+
                #      words on `arithmetic_reasoning` and is still truncated at an
                #      8192 budget, while think-off answers it in 484 tokens.
                # Ollama accepts this key for non-thinking models too (no-op).
                "think": False,
            }
            # Vision tasks carry an `image:` path (relative to REPO). Ollama's
            # /api/chat expects `images` INSIDE the message that carries the
            # image (not at the payload root). Models without vision simply
            # ignore it / error -> reported via the error path.
            if image_path:
                img_path = image_path if os.path.isabs(image_path) else os.path.join(REPO, image_path)
                try:
                    with open(img_path, "rb") as fh:
                        import base64
                        message["images"] = [base64.b64encode(fh.read()).decode("utf-8")]
                except Exception:
                    # image missing -> let the model answer without it; the
                    # judge will score the (likely wrong) response.
                    pass
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
            # Strip inline <think>...</think> blocks that CoT models (deepcoder,
            # qwen3, deepseek-r1) emit before the actual answer. Score only the
            # deliverable, not the reasoning trace.
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            # done_reason == "length" means Ollama cut the response at the token
            # budget — the model likely never reached its answer. Captured here so
            # the caller can retry / refuse to score it (see call_model_guarded).
            meta = {
                "done_reason": resp.get("done_reason"),
                "prompt_tokens": resp.get("prompt_eval_count"),
                "completion_tokens": resp.get("eval_count"),
                # Non-zero despite `think: False` means the model ignored the flag;
                # surfaced so a silent regression to thinking mode is visible in the
                # run JSON rather than showing up as mystery truncation.
                "thinking_chars": len(msg.get("thinking") or ""),
                "think_disabled": True,
            }
            return text, latency, None, meta
        except Exception as e:
            return None, 0.0, f"ollama api error: {e}", {}
    # Anthropic models: call via `claude -p` CLI which uses OAuth / Claude Max
    # quota — no ANTHROPIC_API_KEY env var needed or wanted.
    if model.get("provider") == "anthropic":
        try:
            model_name = model.get("model_name", "claude-sonnet-4-5")
            cmd = [
                "claude", "-p", prompt,
                "--model", model_name,
                "--max-turns", "1",
                "--output-format", "json",
            ]
            t0 = dt.datetime.now()
            result = procutil.run(cmd, capture_output=True, text=True, timeout=120)
            latency = (dt.datetime.now() - t0).total_seconds()
            if result.returncode != 0:
                return None, latency, f"claude cli error: {result.stderr.strip()}", {}
            data = json.loads(result.stdout)
            text = data.get("result", "") or ""
            # Strip CoT thinking blocks if any
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text, latency, None, {}
        except Exception as e:
            return None, 0.0, f"claude cli error: {e}", {}
    return None, 0.0, f"provider {model.get('provider')} not wired in skeleton", {}


def call_model_guarded(model, prompt, max_tokens, image_path=None):
    """Call the model and guard against token-budget truncation.

    If Ollama reports `done_reason == "length"` (the response was cut off before
    the model finished — the single biggest distortion in this benchmark, since
    reasoning models spend their budget on chain-of-thought and never reach the
    answer), re-run ONCE at 2x `max_tokens`. Returns (text, latency, error, meta)
    where `meta["truncated"]` is True only if it was STILL cut off after the retry
    — the caller must then score it `null`, never `0.0`.
    """
    text, latency, err, meta = call_model(model, prompt, max_tokens, image_path)
    meta = dict(meta or {})
    meta["attempts"] = 1
    meta["max_tokens_used"] = max_tokens
    # `gen_latency_s` is the wall-clock of the attempt whose tokens we keep, so
    # tokens-per-second is computed against the matching generation (not the summed
    # latency of a wasted-then-retried pair, which would understate throughput).
    meta["gen_latency_s"] = latency
    if err is None and meta.get("done_reason") == "length":
        bigger = max_tokens * 2
        text2, latency2, err2, meta2 = call_model(model, prompt, bigger, image_path)
        latency += latency2  # report total wall-clock incl. the wasted first attempt
        if err2 is None:
            text, err = text2, err2
            meta2 = dict(meta2 or {})
            meta2["attempts"] = 2
            meta2["max_tokens_used"] = bigger
            meta2["gen_latency_s"] = latency2
            meta = meta2
        else:
            # Retry itself errored: keep the first (truncated) response but record
            # that a second attempt happened and why it failed — don't silently drop it.
            meta["attempts"] = 2
            meta["retry_error"] = err2
    meta["truncated"] = bool(err is None and meta.get("done_reason") == "length")
    return text, latency, err, meta


# Clock time HH:MM, but NOT the H:MM slice of an HH:MM:SS timestamp and NOT the
# tail of a longer number (lookarounds reject an adjacent digit or colon on either
# side). A trailing am/pm is allowed (it is a non-digit, so extraction still fires).
_TIME_RE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
# A number token: optional sign, digits with optional thousands separators, and an
# optional fractional part. Lookarounds keep "720" from being pulled out of "x720y"
# and keep a range/minus hyphen ("2-5") from being read as the number's own sign.
_NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w])")
# The model is asked to end with "Final answer: X"; we score THAT, not an
# intermediate value mentioned mid-working.
_FINAL_RE = re.compile(r"final\s*answer", re.I)


def _norm_time(s):
    """Normalise a clock time so "05:00" and "5:00" compare equal, but "15:00"
    stays distinct (this is the exact false-positive the substring scorer had:
    "5:00" is a substring of "15:00")."""
    m = re.match(r"0*(\d{1,2}):(\d{2})$", s.strip())
    return f"{int(m.group(1))}:{m.group(2)}" if m else s.strip()


# A vision model that answers "you have not provided an image" did not FAIL the
# task, it never received it. Scoring that as a capability result is the inverse
# of the honesty rule (CLAUDE.md 9): a harness/ingestion failure published as a
# low OCR score. Flagged separately so reports can say which one happened.
# gemma4:e4b emits this intermittently on tasks/images/ocr_card.png even with a
# correctly attached image and `think: False`.
_NO_IMAGE_RE = re.compile(
    r"(not|n't|no)\s+(been\s+)?(provided|attached|given|uploaded|include)"
    r"|need\s+an?\s+image|cannot\s+see\s+(an?\s+)?image|unable\s+to\s+see"
    r"|please\s+(provide|upload|share)\s+(the|an?)\s+(image|picture|photo)",
    re.I,
)


def looks_like_ingestion_failure(response):
    """True when a response to an IMAGE task claims no image was supplied."""
    return bool(response and _NO_IMAGE_RE.search(response))


def _to_float(tok):
    try:
        return float(tok.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _answer_region(response):
    """Prefer the model's explicitly labelled final answer. The reasoning tasks
    instruct the model to end with "Final answer: X", and their rubrics award full
    marks only for that final answer — so a correct intermediate value paired with a
    WRONG final answer must not score. Falls back to the whole response when the
    model omitted the label."""
    hits = list(_FINAL_RE.finditer(response))
    return response[hits[-1].end():] if hits else response


def score_exact(expected, response):
    """Match the model's stated answer against `expected` by *extracting* answer
    tokens from the final-answer region and comparing on value/word boundaries —
    never raw substring containment. Keeps "15:00" from scoring as a correct "5:00",
    and a "Final answer: 6:00" (with 5:00 mentioned earlier) from scoring correct."""
    if not response:
        return 0.0
    exp = expected.strip()
    region = _answer_region(response)
    # Clock-time answers (e.g. "5:00"): compare normalised HH:MM tokens.
    if re.fullmatch(r"\d{1,2}:\d{2}", exp):
        want = _norm_time(exp)
        found = {_norm_time(f"{h}:{m}") for h, m in _TIME_RE.findall(region)}
        return 1.0 if want in found else 0.0
    # Numeric answers (e.g. "720"): compare by VALUE so 720 == 720.0 == 720.00, while
    # "1720"/"7200"/"x720y" (different value / not a standalone token) still fail.
    want_f = _to_float(exp)
    if want_f is not None and re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?", exp):
        for tok in _NUM_RE.findall(region):
            if _to_float(tok) == want_f:
                return 1.0
        return 0.0
    # General string answer: case-insensitive, boundary-guarded, but only on sides
    # where `exp` itself ends in a word char (so "C++"/".NET"/"(a)" still match).
    left = r"(?<!\w)" if exp[:1].isalnum() else ""
    right = r"(?!\w)" if exp[-1:].isalnum() else ""
    return 1.0 if re.search(left + re.escape(exp) + right, region, re.I) else 0.0


def score(task, response):
    """Score a response. Handles exact, json-exact, and rubric-llm methods."""
    method = task.get("scoring", {}).get("method", "rubric-llm")
    expected = task.get("expected", {}).get("answer", "")

    if method == "exact":
        if not expected:
            # No expected answer string — fall through to rubric-llm
            return None
        return score_exact(expected, response)

    if method == "json-exact":
        # Parse both sides and compare dicts (key order / whitespace insensitive)
        try:
            exp = json.loads(expected)
            got = json.loads(response)
            return 1.0 if got == exp else 0.0
        except Exception:
            return 0.0

    # rubric-llm / reference-compare: implement with a scorer model.
    return None  # None = unscored (report as ±)


def _record_telemetry(tracker, run_id, model, task, latency, meta, err):
    """Best-effort telemetry write. Uses the token counts Ollama already returned
    (meta) rather than a streaming wrapper, so it adds no extra model call."""
    try:
        import telemetry
        prov = model.get("provider", "") or ""
        provider = "ollama" if prov.startswith("custom") else (prov or "unknown")
        prompt_toks = meta.get("prompt_tokens") or 0
        completion_toks = meta.get("completion_tokens") or 0
        gen_latency = meta.get("gen_latency_s") or latency
        tps = (completion_toks / gen_latency) if gen_latency > 0 else 0.0
        tracker.record(telemetry.TelemetryRecord(
            timestamp=dt.datetime.now().isoformat(),
            run_id=run_id,
            model_id=model["id"],
            model_provider=provider,
            task_id=task["id"],
            task_category=task.get("category", ""),
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            total_tokens=prompt_toks + completion_toks,
            latency_seconds=latency,
            ttft_seconds=None,
            tokens_per_second=tps,
            vram_peak_mib=telemetry.get_vram_used_mib(),
            vram_delta_mib=None,
            cost_usd=telemetry.calculate_cost(model["id"], prompt_toks, completion_toks),
            success=(err is None),
            error=err,
        ))
    except Exception as e:  # noqa: BLE001 — telemetry must never break a run
        print(f"[{run_id}] telemetry record failed: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=os.path.join(REPO, "models", "registry.yaml"))
    ap.add_argument("--tasks", default=os.path.join(REPO, "tasks"))
    ap.add_argument("--out", default=os.path.join(REPO, "runs"))
    ap.add_argument("--tier", default=None, help="comma list to filter, e.g. local,free")
    # N=1 was structural, not a setting: there was no sample loop at all, so every
    # published number was a single draw with no way to tell signal from noise.
    ap.add_argument("--samples", type=int, default=1,
                    help="draws per (model, task); >1 makes variance measurable")
    args = ap.parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")

    models = load_registry(args.registry)
    tasks = load_tasks(args.tasks)
    if args.tier:
        wanted = set(args.tier.split(","))
        models = [m for m in models if m.get("tier") in wanted]
    models = [m for m in models if m.get("enabled", True)]

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Telemetry (tokens / tok-per-s / VRAM / cost) — optional; a broken import
    # must never take down a bench run, so it is best-effort.
    tracker = None
    try:
        import telemetry
        tracker = telemetry.TelemetryTracker(run_id)
    except Exception as e:  # noqa: BLE001
        print(f"[{run_id}] telemetry disabled: {e}", file=sys.stderr)

    results = []
    # Every (model, task) pair the tag gate refuses, with its reason. The gate used
    # to `continue` in silence, so a 9-task average and an 11-task average were
    # published side by side as if they measured the same thing (F1.6/D5).
    skipped = []
    for model in models:
        mtags = set(model.get("tags", []))
        for task in tasks:
            ttags = set(task.get("tags", []))
            if not (mtags & ttags) and not task.get("requires_frontier"):
                skipped.append({
                    "model": model["id"],
                    "task": task["id"],
                    "reason": "tag mismatch: model tags do not intersect task tags",
                    "model_tags": sorted(mtags),
                    "task_tags": sorted(ttags),
                })
                print(f"[{run_id}] {model['id']} x {task['id']}: SKIP (tag mismatch)")
                continue
            for sample_i in range(args.samples):
                text, latency, err, meta = call_model_guarded(
                    model, task["prompt"], task.get("max_tokens", 512),
                    image_path=task.get("image"))
                # A response cut off at the token budget is a non-answer: score it
                # `null` (unscored), NEVER 0.0 - a truncated CoT is not a wrong answer.
                truncated = bool(meta.get("truncated"))
                if truncated:
                    sc = None
                else:
                    sc = score(task, text) if text else None
                tps = None
                gen_latency = meta.get("gen_latency_s") or latency
                if meta.get("completion_tokens") and gen_latency > 0:
                    tps = round(meta["completion_tokens"] / gen_latency, 1)
                results.append({
                    "model": model["id"], "task": task["id"],
                    # Which draw this is. Rows are only comparable within a
                    # (model, task, run); the aggregate uses these to compute
                    # spread instead of asserting a single draw is the truth.
                    "sample": sample_i,
                    "samples": args.samples,
                    "response": text, "latency_s": latency,
                    "score": sc, "error": err,
                    "image": task.get("image"),
                    "truncated": truncated,
                    "done_reason": meta.get("done_reason"),
                    "attempts": meta.get("attempts", 1),
                    "max_tokens_used": meta.get("max_tokens_used", task.get("max_tokens", 512)),
                    "prompt_tokens": meta.get("prompt_tokens"),
                    "completion_tokens": meta.get("completion_tokens"),
                    "tokens_per_s": tps,
                    "thinking_chars": meta.get("thinking_chars"),
                    "think_disabled": meta.get("think_disabled"),
                    "ingestion_failed": bool(
                        task.get("image") and looks_like_ingestion_failure(text)),
                })
                if tracker is not None:
                    _record_telemetry(tracker, run_id, model, task, latency, meta, err)
                flag = ("ERR" if err else
                        ("TRUNC/unscored" if truncated else
                         ("INGEST-FAIL/unscored" if results[-1]["ingestion_failed"] else
                          ("score=" + str(sc) if sc is not None else "unscored"))))
                tag = (f" [sample {sample_i + 1}/{args.samples}]"
                       if args.samples > 1 else "")
                print(f"[{run_id}] {model['id']} x {task['id']}{tag}: {flag}"
                      + (f" (attempts={meta.get('attempts')})" if meta.get("attempts", 1) > 1 else ""))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{run_id}.json"), "w") as f:
        prov = build_provenance()
        prov["samples_per_pair"] = args.samples
        json.dump({
            "run_id": run_id,
            "provenance": prov,
            "results": results,
            # What this run did NOT measure, and why. A reader can now tell a
            # coverage gap from a capability gap without reading the registry.
            "skipped": skipped,
        }, f, indent=2)
    # TODO: generate reports/<run_id>.md from results (leaderboard + cost split).
    pairs = len({(r["model"], r["task"]) for r in results})
    print(f"Wrote {args.out}/{run_id}.json  ({pairs} model/task pairs x "
          f"{args.samples} sample(s) = {len(results)} rows; "
          f"{len(skipped)} pair(s) skipped)")


if __name__ == "__main__":
    main()
