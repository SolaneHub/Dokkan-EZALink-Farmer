"""Pytest configuration and automatic test tier classification.

Classifies test items into 'slow' (vision processing, OCR, or multi-round integration)
and 'fast' (purely logical in-memory tests).
"""

from __future__ import annotations

import os

# Prevent OpenMP and threadpool contention during C++ teardown across runtimes
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.harness.fake_dokkandb import FakeDokkanDBClient, fake_dokkandb_requests_get

SLOW_MODULE_NAMES = {
    "test_eza_farm_integration",
    "test_link_level_integration",
    "test_link_leveling",
    "test_stage_farm",
    "test_box_scanner",
    "test_team_formation",
    "test_endgame_runner",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Classifies tests dynamically as fast or slow based on module file name if not already marked."""
    _ = config
    slow_mark = pytest.mark.slow
    fast_mark = pytest.mark.fast

    for item in items:
        # If test already has fast or slow mark, do not overwrite
        item_marks = {m.name for m in item.iter_markers()}
        if "slow" in item_marks or "fast" in item_marks:
            continue

        file_path = getattr(item, "path", None)
        if file_path is not None:
            stem = file_path.stem
        elif hasattr(item, "fspath") and item.fspath:
            stem = Path(str(item.fspath)).stem
        else:
            stem = ""

        if stem in SLOW_MODULE_NAMES:
            item.add_marker(slow_mark)
        else:
            item.add_marker(fast_mark)


@pytest.fixture
def fake_dokkandb() -> FakeDokkanDBClient:
    """Provides a fresh in-memory FakeDokkanDBClient instance."""
    return FakeDokkanDBClient()


@pytest.fixture
def mock_dokkandb_requests() -> Generator[None, None, None]:
    """Intercepts requests.get to simulate DokkanDB API endpoints completely in-memory."""
    with patch("requests.get", side_effect=fake_dokkandb_requests_get):
        yield


def pytest_unconfigure(config: pytest.Config) -> None:
    """Safely terminate on Linux when all tests have passed to bypass known glibc 2.39+ thread teardown crashes."""
    import sys

    sys.stdout.flush()
    sys.stderr.flush()

    if sys.platform.startswith("linux"):
        tr = config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            failed = len(tr.stats.get("failed", []))
            error = len(tr.stats.get("error", []))
            if failed == 0 and error == 0:
                os._exit(0)
