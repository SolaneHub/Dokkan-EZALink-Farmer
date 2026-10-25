#!/usr/bin/env python3
"""Fast Test Loop runner for Dokkan-EZALink-Farmer (< 3s target).

Runs non-slow unit and logic tests with pytest directly in-process or via pytest.main,
providing instant feedback during active development.
"""

from __future__ import annotations

import os
import sys
import time

import pytest


def main() -> int:
    # Ensure standard thread pool bounds to avoid contention
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")

    # Command arguments: fast non-slow tests, quiet mode
    args = ["-m", "not slow", "-q", *sys.argv[1:]]

    t0 = time.perf_counter()
    exit_code = pytest.main(args)
    elapsed = time.perf_counter() - t0

    # Ensure integer return code
    code = int(exit_code)
    print(f"\n[FAST-TEST] Completed in {elapsed:.2f}s with exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
