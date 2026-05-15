#!/usr/bin/env python3
"""
Startup benchmark script for hermes-agent.

Measures cold startup time of the `hermes` CLI binary and optionally
enforces budget constraints. Budget thresholds can be overridden via
environment variables.

Usage:
    python3 scripts/bench_startup.py --runs 5          # print stats only
    python3 scripts/bench_startup.py --check --runs 5  # fail if budget exceeded

Environment variables (all optional):
    HERMES_STARTUP_BUDGET_MS     Max allowed median startup time in ms (default: 2000)
    HERMES_STARTUP_P95_BUDGET_MS Max allowed p95 startup time in ms (default: 5000)
    HERMES_STARTUP_TIMEOUT_S     Per-run timeout in seconds (default: 30)
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time
from typing import NamedTuple


# ── Default budgets ────────────────────────────────────────────────────────────
DEFAULT_BUDGET_MS: int = 2000      # HERMES_STARTUP_BUDGET_MS
DEFAULT_P95_BUDGET_MS: int = 5000  # HERMES_STARTUP_P95_BUDGET_MS
DEFAULT_TIMEOUT_S: int = 30        # HERMES_STARTUP_TIMEOUT_S

# Path to the hermes entry point (resolved relative to this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
HERMES_CMD: list[str] = [sys.executable, "-m", "hermes_cli.main"]


class RunResult(NamedTuple):
    elapsed_ms: float
    timed_out: bool


def read_env_int(name: str, default: int) -> int:
    """Read an integer from an environment variable, falling back to default."""
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


def measure_startup(timeout_s: int) -> RunResult:
    """Run the hermes binary once and return elapsed time in ms."""
    start = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            HERMES_CMD + ["--help"],
            capture_output=True,
            timeout=timeout_s,
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        elapsed_ms = timeout_s * 1000
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
    return RunResult(elapsed_ms=elapsed_ms, timed_out=timed_out)


def run_benchmark(runs: int, timeout_s: int) -> tuple[list[float], bool]:
    """Run the startup benchmark `runs` times. Returns (times_ms, had_timeout)."""
    times: list[float] = []
    had_timeout = False
    for i in range(runs):
        print(f"  Run {i + 1}/{runs} ...", end=" ", flush=True)
        result = measure_startup(timeout_s)
        if result.timed_out:
            print("TIMEOUT")
            had_timeout = True
            # Use timeout value as the time so the median isn't artificially deflated
            times.append(timeout_s * 1000)
        else:
            print(f"{result.elapsed_ms:.1f} ms")
            times.append(result.elapsed_ms)
    return times, had_timeout


def print_stats(times: list[float]) -> tuple[float, float]:
    """Print benchmark stats and return (median_ms, p95_ms)."""
    n = len(times)
    median = statistics.median(times)
    sorted_times = sorted(times)
    p95_idx = max(0, int(0.95 * n) - 1)
    p95 = sorted_times[p95_idx]
    mean = statistics.mean(times)
    print(f"\n  Median : {median:.1f} ms")
    print(f"  Mean   : {mean:.1f} ms")
    print(f"  P95    : {p95:.1f} ms")
    print(f"  Min    : {min(times):.1f} ms")
    print(f"  Max    : {max(times):.1f} ms")
    return median, p95


def check_budget(median_ms: float, p95_ms: float, budget_ms: int, p95_budget_ms: int) -> bool:
    """Check whether median and p95 are within budget. Print results. Returns True if OK."""
    median_ok = median_ms <= budget_ms
    p95_ok = p95_ms <= p95_budget_ms
    status = "OK" if (median_ok and p95_ok) else "EXCEEDED"
    print(f"\n  Budget median : {budget_ms} ms  →  {median_ok and '✓' or '✗ FAIL'}")
    print(f"  Budget P95    : {p95_budget_ms} ms  →  {p95_ok and '✓' or '✗ FAIL'}")
    print(f"\n  Result: {status}")
    return median_ok and p95_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark hermes-agent startup time.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail with non-zero exit code if budget thresholds are exceeded.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of startup runs to measure (default: 5).",
    )
    args = parser.parse_args()

    budget_ms = read_env_int("HERMES_STARTUP_BUDGET_MS", DEFAULT_BUDGET_MS)
    p95_budget_ms = read_env_int("HERMES_STARTUP_P95_BUDGET_MS", DEFAULT_P95_BUDGET_MS)
    timeout_s = read_env_int("HERMES_STARTUP_TIMEOUT_S", DEFAULT_TIMEOUT_S)

    print(f"hermes-agent startup benchmark ({args.runs} runs)")
    print(f"  Budget median : {budget_ms} ms  (HERMES_STARTUP_BUDGET_MS)")
    print(f"  Budget P95    : {p95_budget_ms} ms  (HERMES_STARTUP_P95_BUDGET_MS)")
    print(f"  Per-run timeout: {timeout_s} s  (HERMES_STARTUP_TIMEOUT_S)")
    print()

    times, had_timeout = run_benchmark(args.runs, timeout_s)
    median_ms, p95_ms = print_stats(times)

    if args.check:
        ok = check_budget(median_ms, p95_ms, budget_ms, p95_budget_ms)
        if not ok or had_timeout:
            print("\n::error::Startup budget exceeded — CI run FAILED", file=sys.stderr)
            sys.exit(1)
        print("\n✓ All budget checks passed.")
        sys.exit(0)
    else:
        # Informational only — always succeed in non-check mode
        sys.exit(0)


if __name__ == "__main__":
    main()