#!/usr/bin/env python3
"""NVIDIA judge pass for autobench runs.

Reads a run JSON, scores remaining rubric-llm tasks via
meta/llama-3.3-70b-instruct (NVIDIA NIM, free 40 RPM), then writes a markdown
report. Mechanical methods (exact / json-exact / python-exec / tool-call / tool-trajectory) are left alone or
backfilled in-process - never sent to the LLM judge.

Uses direct curl to NVIDIA's OpenAI-compatible endpoint (bypasses the slow
`hermes -z` agent loop). The API key is resolved with this precedence:
  1. env var NVIDIA_API_KEY
  2. a project-owned .env outside the repo: %LOCALAPPDATA%/llm-autobench/.env
     on Windows, ~/.config/llm-autobench/.env on Linux/macOS (legacy Hermes
     .env paths are still checked after these, for existing boxes)
  3. --key CLI arg

Hardened vs v1: cross-platform key load, exponential backoff retry, larger
token budget for judge reasoning, robust float parsing, incremental write-back.

Usage:
  python scripts/nvidia_judge.py runs/<run>.json [--key SK] [--max-retries 4]
      [--self-consistency] [--self-consistency-n 3] [--retry-judge-errors]

M2: persistent JUDGE_ERROR rows are marked judge_error=true and skipped on later
cron passes (unless --retry-judge-errors). Optional --self-consistency re-asks the
same judge N times at temperature 0 and takes the median — disclosed as
self-consistency, never as inter-rater kappa.
"""
import json
import statistics
import os
import re
import sys
import time
import base64
import urllib.request
from pathlib import Path

import procutil

# The judge model is configurable because a hosted model can be retired out from
# under us: meta/llama-3.3-70b-instruct reached end of life on 2026-08-26 and
# every rubric-llm task silently went unscored for 13 nights. Override without
# editing code: NVIDIA_JUDGE_MODEL=<id>. See STATUS.md.
JUDGE_MODEL = os.environ.get("NVIDIA_JUDGE_MODEL", "nvidia/nemotron-3-super-120b-a12b")


# A reasoning judge spends tokens thinking before it answers. At 256 every
# candidate tested truncated mid-thought and emitted no verdict at all.
JUDGE_MAX_TOKENS = int(os.environ.get("NVIDIA_JUDGE_MAX_TOKENS", "1024"))


def _redact(text: str, api_key: str = "") -> str:
    """Strip anything key-shaped. This repo is public and judge error strings
    are written into runs/*.json and reports/*.md, both committed."""
    if api_key:
        text = text.replace(api_key, "<REDACTED>")
    return re.sub(r"nvapi-[A-Za-z0-9_\-]{8,}", "<REDACTED>", text)
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

    # Candidate .env locations, ours first. The key lives OUTSIDE the repo
    # (public repo, rule 1) but in a directory this project owns, so another
    # tool reinstalling or relocating its config cannot take the judge down.
    local_appdata = os.environ.get("LOCALAPPDATA")
    candidates = [
        Path(local_appdata) / "llm-autobench" / ".env" if local_appdata
        else Path.home() / "AppData" / "Local" / "llm-autobench" / ".env",
        Path.home() / ".config" / "llm-autobench" / ".env",            # POSIX
        # Legacy Hermes locations, kept so an existing box keeps working.
        Path.home() / "AppData" / "Local" / "hermes" / ".env",         # Windows
        Path.home() / ".local" / "share" / "hermes" / ".env",          # Linux XDG
        Path.home() / ".config" / "hermes" / ".env",                   # Linux alt
        Path.home() / ".hermes" / ".env",                              # generic
    ]
    for cand in candidates:
        if cand.exists():
            for line in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("NVIDIA_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


def call_judge(prompt: str, api_key: str, max_retries: int = 4,
               max_tokens: int = JUDGE_MAX_TOKENS) -> str:
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
            # The key is fed through a stdin config file, never argv: argv is
            # visible in any process listing, and subprocess exceptions embed
            # the whole command in their message -- which is returned below as
            # an ERROR string and committed into runs/ and reports/.
            cmd = [
                "curl", "-s", "--max-time", "180", NVIDIA_URL,
                "-H", "Content-Type: application/json",
                "-d", payload, "--config", "-",
            ]
            res = procutil.run(cmd, capture_output=True, text=True, timeout=200,
                               input=f'header = "Authorization: Bearer {api_key}"\n')
            out = res.stdout.strip()
            if not out:
                last_err = f"empty response (HTTP {res.returncode})"
                raise RuntimeError(last_err)
            data = json.loads(out)
            if "choices" not in data:
                # An HTTP error body parses as JSON perfectly well. Indexing
                # straight to ["choices"] turned a 410 "model has reached end of
                # life" into the message "'choices'", which is why a dead judge
                # looked like a transient glitch for 13 nights.
                detail = (data.get("detail") or data.get("title")
                          or data.get("error") or out[:300])
                last_err = f"judge API said: {_redact(str(detail), api_key)}"
                raise RuntimeError(last_err)
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001
            last_err = _redact(str(e), api_key)
            if attempt < max_retries:
                backoff = 2 ** attempt
                print(f"    retry {attempt}/{max_retries} after {backoff}s ({last_err})",
                      file=sys.stderr, flush=True)
                time.sleep(backoff)
    return f"ERROR: {last_err}"


def check_judge_alive(api_key: str = "") -> tuple[bool, str]:
    """One cheap call to prove the configured judge model still answers.

    Exists because the failure it catches is invisible otherwise: when a hosted
    model is retired, every judged task returns an error string, the row is
    written back with score=null, and the run still 'succeeds' with a report and
    a mean computed from the mechanically-scored rows only. That is what
    happened between 2026-08-26 and 2026-09-07 (see STATUS.md).
    """
    api_key = api_key or find_nvidia_key()
    if not api_key:
        return False, "no API key resolvable"
    reply = call_judge("Reply with exactly: OK", api_key, max_retries=1, max_tokens=8)
    if reply.startswith("ERROR:"):
        return False, _redact(reply[len("ERROR:"):].strip(), api_key)
    return True, reply.strip()[:40]


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


# A verdict is a number the judge *stated*, not a number that happens to appear
# somewhere in its reasoning. Prose with a stray float is unscored, not guessed.
_PROSE_CHARS = 220


def parse_score(text: str):
    # Prefer an explicit "score: 0.85" or "0.85/1.0" form, else a bare float.
    m = re.search(r"score[\"']?\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?)", text, re.I)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))
    m = re.search(r"(0(?:\.\d+)?|1(?:\.0+)?)\s*/\s*1", text)
    if m:
        return max(0.0, min(1.0, float(m.group(1))))
    stripped = (text or "").strip()
    # The bare-float fallback applies ONLY to a terse reply, and to the LAST
    # float in it (a verdict closes a reply, it does not open one). Long prose
    # with no explicit score means the judge never reached a verdict: return
    # None so the row is written back unscored. Guessing here scored a garbage
    # summarization 1.0 off the "1.0" in a restated rubric.
    if len(stripped) > _PROSE_CHARS:
        return None
    hits = re.findall(r"\b(0(?:\.\d+)?|1(?:\.0+)?)\b", stripped)
    if hits:
        return max(0.0, min(1.0, float(hits[-1])))
    return None


def is_error_output(text: str) -> bool:
    """True when call_judge returned a transport/API failure sentinel."""
    return (text or "").lstrip().startswith("ERROR:")


def median_score(scores):
    """Median of numeric scores, or None if empty."""
    vals = [float(s) for s in scores if isinstance(s, (int, float)) and not isinstance(s, bool)]
    if not vals:
        return None
    return float(statistics.median(vals))


def should_skip_judge(row, *, retry_judge_errors: bool = False) -> str | None:
    """Return a skip reason, or None if this row still needs the LLM judge.

    M2.1: rows already marked judge_error are skipped so cron does not burn
    free-tier RPM forever. Pass retry_judge_errors to force another attempt.
    """
    if row.get("truncated"):
        return "truncated"
    if row.get("ingestion_failed"):
        return "ingestion_failed"
    if row.get("tools_unsupported"):
        return "tools_unsupported"
    if row.get("score") is not None:
        return "already_scored"
    if row.get("judge_error") and not retry_judge_errors:
        return "judge_error"
    return None


def mark_judge_error(row, raw: str, *, judge_label: str) -> None:
    """Record a persistent judge failure: score stays null, cron will not retry."""
    reason = raw if is_error_output(raw) else f"JUDGE_ERROR: unparseable judge output: {(raw or '')[:200]}"
    if not reason.startswith("JUDGE_ERROR") and reason.startswith("ERROR:"):
        reason = "JUDGE_ERROR: " + reason[len("ERROR:"):].lstrip()
    elif not reason.startswith("JUDGE_ERROR"):
        reason = f"JUDGE_ERROR: {reason}"
    row["score"] = None
    row["judge_error"] = True
    row["judge"] = judge_label
    row["judge_raw"] = (raw or "")[:300]
    row["score_reason"] = reason[:300]


def apply_parsed_score(row, score, raw: str, *, judge_label: str,
                       judge_draws=None) -> None:
    """Write a successful (or partially successful) judge outcome onto the row."""
    row["score"] = score
    row["judge"] = judge_label
    row["judge_raw"] = (raw or "")[:300]
    row.pop("judge_error", None)
    row.pop("score_reason", None)
    if judge_draws is not None:
        row["judge_draws"] = list(judge_draws)
        row["judge_aggregation"] = "self-consistency-median"


def judge_rubric(prompt: str, api_key: str, *, max_retries: int = 4,
                 self_consistency_n: int = 1, call_fn=None) -> tuple:
    """Call the judge once, or N times for self-consistency.

    Returns (score_or_None, raw_summary, draws_or_None).
    draws is a list of per-call parse results (float|None) when N>1, else None.
    """
    call = call_fn or call_judge
    n = max(1, int(self_consistency_n))
    if n == 1:
        out = call(prompt, api_key, max_retries=max_retries)
        if is_error_output(out):
            return None, out, None
        return parse_score(out), out, None

    draws = []
    raws = []
    for i in range(n):
        out = call(prompt, api_key, max_retries=max_retries)
        raws.append(out)
        if is_error_output(out):
            draws.append(None)
        else:
            draws.append(parse_score(out))
    parsed = [d for d in draws if d is not None]
    # Prefer a compact raw that still shows all draw texts for debugging.
    raw_summary = " | ".join((r or "")[:80] for r in raws)
    if not parsed:
        # All draws failed or unparseable — surface the first ERROR if any.
        err = next((r for r in raws if is_error_output(r)), raws[0] if raws else "ERROR: empty")
        return None, err if is_error_output(err) else f"ERROR: no parseable self-consistency draws ({raw_summary})", draws
    return median_score(parsed), raw_summary, draws


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


def load_scoring_method(task_id):
    """Return scoring.method from tasks/<id>.yaml (default rubric-llm)."""
    p = REPO / "tasks" / f"{task_id}.yaml"
    if not p.exists():
        return "rubric-llm"
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^\s*method:\s*(\S+)", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else "rubric-llm"


_MECHANICAL = frozenset({"exact", "json-exact", "python-exec", "tool-call", "tool-trajectory"})
# Agentic tasks (SPEC 13.3/13.6) — separate regime; never fold into text avg.
AGENTIC_TASKS = frozenset({"tool_weather", "tool_multiturn_sum"})


def _mechanical_score(task_id, response, tool_calls=None):
    """Backfill exact / json-exact / python-exec / tool-call via run_bench.score."""
    try:
        import yaml
    except ImportError:
        return None
    p = REPO / "tasks" / f"{task_id}.yaml"
    if not p.exists():
        return None
    task = yaml.safe_load(p.read_text(encoding="utf-8"))
    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_bench
    return run_bench.score(task, response or "", tool_calls=tool_calls)


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


def build_report(run_stem, scored, *, self_consistency_n: int = 1):
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
        # SPEC 13.6: agentic is a separate regime — do not fold into text avg.
        vals = [r["score"] for r in rows
                if _is_num(r.get("score"))
                and r.get("task") not in AGENTIC_TASKS]
        return (sum(vals) / len(vals)) if vals else None

    models = list(by_model)
    lines = []
    lines.append(f"# autobench report — {run_stem}")
    lines.append("")
    lines.append(f"**Run:** `{run_stem}.json`  ")
    lines.append(f"**Models:** {', '.join('`' + m + '`' for m in models)}  ")
    judge_note = f"**Judge:** `nvidia/{JUDGE_MODEL}` (70B text judge) + Claude vision describer (stage 1)"
    if self_consistency_n and self_consistency_n > 1:
        judge_note += (f"  \n**Self-consistency:** median of {self_consistency_n} draws at "
                       f"temperature 0 (same judge — **not** inter-rater kappa)")
    lines.append(judge_note + "  ")
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

    # ---- Failures: derived from outcomes only (P0.5 / M2.3 — never hard-coded) ----
    fails = [r for r in scored
             if r.get("error") or r.get("truncated") or r.get("ingestion_failed")
             or r.get("tools_unsupported")
             or r.get("judge_error") or not _is_num(r.get("score"))]
    lines.append("## Failures")
    lines.append("")
    if not fails:
        lines.append("None.")
    else:
        for r in fails:
            if r.get("error"):
                why = r.get("error")
            elif r.get("truncated"):
                why = "truncated at token budget (unscored, not 0.0)"
            elif r.get("ingestion_failed"):
                why = ("model reported no image was supplied — ingestion failure, "
                       "NOT a vision-capability score (unscored, not 0.0)")
            elif r.get("tools_unsupported"):
                why = ("no tool_calls emitted — tools_unsupported "
                       "(unscored, not 0.0; cannot vs wrong are different findings)")
            elif r.get("judge_error"):
                why = (r.get("score_reason")
                       or r.get("judge_raw")
                       or "JUDGE_ERROR (persistent; not retried by cron)")
            else:
                why = "unscored (judge returned no parseable score)"
            lines.append(f"- **{r.get('model')} × {r.get('task')}**: {why}")
    lines.append("")

    # Derived judge status (M2.3 / F0.5): never hard-code "judge ran: yes".
    judged_ok = sum(1 for r in scored
                    if _is_num(r.get("score")) and str(r.get("judge", "")).startswith("nvidia/"))
    judged_err = sum(1 for r in scored if r.get("judge_error"))
    lines.append("## Judge status")
    lines.append("")
    lines.append(f"- Rubric rows scored by NVIDIA judge: **{judged_ok}**")
    lines.append(f"- Persistent judge_error (capped; cron will not re-burn RPM): **{judged_err}**")
    if self_consistency_n and self_consistency_n > 1:
        lines.append(f"- Aggregation: self-consistency median of {self_consistency_n} "
                     f"temperature-0 draws (same judge — not kappa)")
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


def main(argv=None, call_fn=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file")
    ap.add_argument("--key", help="NVIDIA API key (else env/.env)")
    ap.add_argument("--max-retries", type=int, default=4,
                    help="per-call transport retries with exp backoff (default 4)")
    ap.add_argument("--self-consistency", action="store_true",
                    help="ask the same judge N times at temp 0; score = median "
                         "(disclosed as self-consistency, never kappa)")
    ap.add_argument("--self-consistency-n", type=int, default=3,
                    help="draw count when --self-consistency is set (default 3)")
    ap.add_argument("--retry-judge-errors", action="store_true",
                    help="re-attempt rows previously marked judge_error (default: skip)")
    args = ap.parse_args(argv)

    api_key = args.key or find_nvidia_key()
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not found (env, Hermes .env, or --key)", file=sys.stderr)
        sys.exit(1)

    sc_n = args.self_consistency_n if args.self_consistency else 1
    if sc_n < 1:
        print("ERROR: --self-consistency-n must be >= 1", file=sys.stderr)
        sys.exit(1)

    run_path = Path(args.run_file)
    data = json.loads(run_path.read_text(encoding="utf-8"))
    results = data["results"]
    scored = []
    judge_label = f"nvidia/{JUDGE_MODEL}"

    for r in results:
        skip = should_skip_judge(r, retry_judge_errors=args.retry_judge_errors)
        if skip == "truncated":
            # A response cut off at the token budget is a non-answer (run_bench's P0.1
            # guard already set score=null, truncated=true). NEVER let the judge score it.
            r.setdefault("judge", "skipped: truncated (unscored)")
            scored.append(r)
            continue
        if skip == "ingestion_failed":
            r.setdefault("judge", "skipped: image not ingested (unscored)")
            scored.append(r)
            continue
        if skip == "tools_unsupported":
            r.setdefault("judge", "skipped: tools_unsupported (unscored)")
            scored.append(r)
            continue
        if skip == "already_scored":
            scored.append(r)
            continue
        if skip == "judge_error":
            # M2.1: persistent failure already recorded — do not burn RPM again.
            print(f"  [skip] judge_error capped for {r.get('task')}",
                  file=sys.stderr, flush=True)
            scored.append(r)
            continue

        task_id = r["task"]
        method = load_scoring_method(task_id)
        # Mechanical methods must never hit the LLM judge (M1). Backfill if the
        # runner left score=null (e.g. re-judge after retargeting a task).
        if method in _MECHANICAL:
            # tool-trajectory scores are produced only by the multi-turn runner
            # (sandbox + trajectory). Never overwrite from score() (always None).
            if method == "tool-trajectory":
                if r.get("tools_unsupported"):
                    r["score"] = None
                    r["judge"] = "tool-trajectory"
                    r.setdefault("judge_raw", "tools_unsupported/unscored")
                    print(f"  [{method}] {task_id} ... tools_unsupported",
                          file=sys.stderr, flush=True)
                else:
                    r["judge"] = method
                    r.pop("judge_error", None)
                    print(f"  [{method}] {task_id} ... {r.get('score')}",
                          file=sys.stderr, flush=True)
                scored.append(r)
                _writeback(data, results, scored, run_path)
                continue
            sc = _mechanical_score(
                task_id, r.get("response", ""),
                tool_calls=r.get("tool_calls"))
            # tool-call with no calls must stay tools_unsupported, never 0.0
            if method == "tool-call" and sc is None:
                r["score"] = None
                r["tools_unsupported"] = True
                r["judge"] = "tool-call"
                r.setdefault("judge_raw", "tools_unsupported/unscored")
                print(f"  [{method}] {task_id} ... tools_unsupported",
                      file=sys.stderr, flush=True)
            else:
                r["score"] = sc
                r["judge"] = method
                r.pop("judge_error", None)
                if sc is None:
                    r.setdefault("judge_raw", "unparseable/unscored")
                print(f"  [{method}] {task_id} ... {sc}", file=sys.stderr, flush=True)
            scored.append(r)
            _writeback(data, results, scored, run_path)
            continue
        rubric = load_rubric(task_id)
        if not rubric:
            print(f"  [skip] no rubric for {task_id}", file=sys.stderr)
            scored.append(r)
            continue

        # Vision tasks: Stage 1 -- describe the image ONCE. Stage 2 -- 70B text judge.
        img = r.get("image")
        prompt = None
        vision_suffix = ""
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
                    vision_suffix = "+claude-vision"
                tag = "judge+vision"
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] vision describe failed ({e}); text judge",
                      file=sys.stderr)
                prompt = None
                tag = "judge"
        if prompt is None:
            prompt = build_judge_prompt(task_id, rubric, r.get("response", ""))
            tag = "judge"

        sc_tag = f"+sc{sc_n}" if sc_n > 1 else ""
        print(f"  [{tag}{sc_tag}] {task_id} ...", end=" ", flush=True)
        score, out, draws = judge_rubric(
            prompt, api_key, max_retries=args.max_retries,
            self_consistency_n=sc_n, call_fn=call_fn)
        label = judge_label + vision_suffix
        if sc_n > 1:
            label = label + f"+self-consistency-{sc_n}"

        if score is None:
            mark_judge_error(r, out, judge_label=label)
            if draws is not None:
                r["judge_draws"] = list(draws)
                r["judge_aggregation"] = "self-consistency-median"
            print(f"JUDGE_ERROR ({(out or '')[:80]})", file=sys.stderr, flush=True)
        else:
            apply_parsed_score(r, score, out, judge_label=label, judge_draws=draws)
            print(score, file=sys.stderr, flush=True)
        scored.append(r)
        _writeback(data, results, scored, run_path)

    data["results"] = scored
    run_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    report = build_report(run_path.stem, scored, self_consistency_n=sc_n)
    out_path = REPO / "reports" / f"{run_path.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    overall = [r["score"] for r in scored if _is_num(r.get("score"))]
    avg = sum(overall) / len(overall) if overall else 0.0
    print(f"\nReport written: {out_path}")
    print(f"Overall average (all scored rows, all models): {avg:.2f}")


if __name__ == "__main__":
    main()
