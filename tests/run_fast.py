"""Fast test runner for rapid developer feedback (< 2 seconds).

Runs all logical in-memory tests tagged with `fast` via pytest.
"""

from __future__ import annotations

import sys

import pytest


def main() -> int:
    args = ["-m", "fast", "-q"] + sys.argv[1:]
    return pytest.main(args)


if __name__ == "__main__":
    sys.exit(main())
