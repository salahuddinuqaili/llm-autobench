#!/usr/bin/env python3
"""
llm-autobench — Telemetry & Token Usage Tracker

Tracks tokens, latency, VRAM, cost for ALL models (local Ollama + cloud OpenRouter).
Persists to telemetry/usage_YYYYMMDD.jsonl for analysis.
"""
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
TELEMETRY_DIR = REPO / "telemetry"
TELEMETRY_DIR.mkdir(exist_ok=True)


@dataclass
class TelemetryRecord:
    timestamp: str
    run_id: str
    model_id: str
    model_provider: str  # "ollama" | "openrouter" | "anthropic" | "custom"
    task_id: str
    task_category: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_seconds: float
    ttft_seconds: Optional[float]  # time to first token (streaming)
    tokens_per_second: float
    vram_peak_mib: Optional[int]
    vram_delta_mib: Optional[int]
    cost_usd: float  # 0 for local/free, calculated for paid
    success: bool
    error: Optional[str] = None


class TelemetryTracker:
    """Thread-safe telemetry logger."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.date_str = datetime.now().strftime("%Y%m%d")
        self.file_path = TELEMETRY_DIR / f"usage_{self.date_str}.jsonl"
        self._lock = threading.Lock()
        self._vram_baseline = None

    def set_vram_baseline(self):
        """Call before model load to capture baseline VRAM."""
        self._vram_baseline = get_vram_used_mib()

    def record(self, record: TelemetryRecord):
        with self._lock:
            with open(self.file_path, "a") as f:
                f.write(json.dumps(asdict(record)) + "\n")

    def get_session_summary(self) -> dict:
        """Aggregate stats for this run_id."""
        if not self.file_path.exists():
            return {}
        records = []
        with open(self.file_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("run_id") == self.run_id:
                        records.append(r)
                except Exception:
                    pass
        if not records:
            return {}
        return {
            "total_calls": len(records),
            "total_prompt_tokens": sum(r["prompt_tokens"] for r in records),
            "total_completion_tokens": sum(r["completion_tokens"] for r in records),
            "total_cost_usd": sum(r["cost_usd"] for r in records),
            "avg_latency": sum(r["latency_seconds"] for r in records) / len(records),
            "avg_tps": sum(r["tokens_per_second"] for r in records) / len(records),
            "max_vram_mib": max((r["vram_peak_mib"] or 0) for r in records),
            "models_used": list(set(r["model_id"] for r in records)),
            "errors": sum(1 for r in records if not r["success"]),
        }


# VRAM tracking
def get_vram_used_mib() -> Optional[int]:
    """Return used VRAM in MiB via nvidia-smi."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return int(out.strip().split("\n")[0])
    except Exception:
        return None


def get_vram_free_mib() -> Optional[int]:
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return int(out.strip().split("\n")[0])
    except Exception:
        return None


# Cost calculation (OpenRouter pricing as of 2026)
MODEL_COSTS = {
    # $ per 1M tokens (input, output)
    "tencent/hy3:free": (0.0, 0.0),
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.0, 0.0),
    # Add paid models as needed
}


def calculate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD for a call."""
    if model_id in MODEL_COSTS:
        in_cost, out_cost = MODEL_COSTS[model_id]
        return (prompt_tokens * in_cost + completion_tokens * out_cost) / 1_000_000
    # Unknown model - assume free for local, flag for cloud
    if "custom:ollama" in model_id or "local" in model_id:
        return 0.0
    return 0.0  # default to 0, log warning elsewhere


# Context manager for easy tracking
class TrackedCall:
    """Context manager that tracks a single model call."""

    def __init__(self, tracker: TelemetryTracker, model_id: str, provider: str,
                 task_id: str, task_category: str):
        self.tracker = tracker
        self.model_id = model_id
        self.provider = provider
        self.task_id = task_id
        self.task_category = task_category
        self.start_time = None
        self.ttft = None
        self.first_token_received = False
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.success = False
        self.error = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        self.tracker.set_vram_baseline()
        return self

    def mark_first_token(self):
        if not self.first_token_received:
            self.ttft = time.perf_counter() - self.start_time
            self.first_token_received = True

    def set_usage(self, prompt: int, completion: int):
        self.prompt_tokens = prompt
        self.completion_tokens = completion

    def set_error(self, err: str):
        self.error = err
        self.success = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = time.perf_counter() - self.start_time
        vram_peak = get_vram_used_mib()
        vram_delta = None
        if self.tracker._vram_baseline is not None and vram_peak is not None:
            vram_delta = vram_peak - self.tracker._vram_baseline

        tps = (self.completion_tokens / latency) if latency > 0 else 0
        cost = calculate_cost(self.model_id, self.prompt_tokens, self.completion_tokens)

        record = TelemetryRecord(
            timestamp=datetime.now().isoformat(),
            run_id=self.tracker.run_id,
            model_id=self.model_id,
            model_provider=self.provider,
            task_id=self.task_id,
            task_category=self.task_category,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
            latency_seconds=latency,
            ttft_seconds=self.ttft,
            tokens_per_second=tps,
            vram_peak_mib=vram_peak,
            vram_delta_mib=vram_delta,
            cost_usd=cost,
            success=self.success and self.error is None,
            error=self.error,
        )
        self.tracker.record(record)
        return False  # don't suppress exceptions


# Global tracker instance (set by run_bench.py)
_current_tracker: Optional[TelemetryTracker] = None


def get_tracker() -> Optional[TelemetryTracker]:
    return _current_tracker


def set_tracker(tracker: TelemetryTracker):
    global _current_tracker
    _current_tracker = tracker


if __name__ == "__main__":
    # Demo
    tracker = TelemetryTracker("test_run")
    set_tracker(tracker)
    with TrackedCall(tracker, "custom:ollama/qwen3.5:9b", "ollama",
                     "arithmetic_reasoning", "reasoning") as call:
        call.set_usage(100, 50)
        call.success = True
    print("Session summary:", tracker.get_session_summary())