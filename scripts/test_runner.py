#!/usr/bin/env python3
"""Cross-platform test runner supporting dual granularity test execution.

Fast feedback loop (< 3s):
    python scripts/test_runner.py fast
    (runs 'uv run pytest -m fast')

Full pre-release matrix:
    python scripts/test_runner.py full
    (runs 'uv run pytest')
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def run_tests(mode: str, extra_args: list[str] | None = None) -> int:
    extra = extra_args or []
    if mode == "fast":
        cmd = ["uv", "run", "pytest", "-m", "fast", *extra]
        print("[TEST-RUNNER] Running Fast Feedback Test Suite (target < 3s)...")
    else:
        cmd = ["uv", "run", "pytest", *extra]
        print("[TEST-RUNNER] Running Full Test Matrix (pre-release)...")

    start_time = time.perf_counter()
    result = subprocess.run(cmd)
    elapsed = time.perf_counter() - start_time

    print(f"\n[TEST-RUNNER] Completed in {elapsed:.2f}s (Exit code: {result.returncode})")
    if mode == "fast" and elapsed > 3.0:
        print("[TEST-RUNNER] Warning: Fast feedback suite exceeded 3.0 seconds threshold.")

    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dokkan-EZALink-Farmer Test Runner (Dual Granularity)"
    )
    parser.add_argument(
        "mode",
        choices=["fast", "full"],
        nargs="?",
        default="fast",
        help="Test granularity: 'fast' for rapid dev feedback (<3s) or 'full' for complete test matrix.",
    )
    args, unknown = parser.parse_known_args()
    code = run_tests(args.mode, extra_args=unknown)
    sys.exit(code)


if __name__ == "__main__":
    main()
