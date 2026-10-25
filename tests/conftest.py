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

from tests.harness.fake_clock import VirtualClock
from tests.harness.fake_dokkandb import FakeDokkanDBClient, fake_dokkandb_requests_get

SLOW_MODULE_NAMES = {
    "test_eza_farm_integration",
    "test_link_level_integration",
    "test_link_leveling",
    "test_stage_farm",
    "test_stage_farm_integration",
    "test_box_scanner",
    "test_box_scanner_integration",
    "test_team_formation",
    "test_endgame_runner",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Classifies tests dynamically: any test in tests/e2e/ or slow modules/marks belongs to 'slow'."""
    _ = config
    slow_mark = pytest.mark.slow

    for item in items:
        # Check if already marked as slow
        item_marks = {m.name for m in item.iter_markers()}
        if "slow" in item_marks:
            continue

        file_path = getattr(item, "path", None)
        fspath_str = ""
        if file_path is not None:
            stem = file_path.stem
            fspath_str = str(file_path).replace("\\", "/")
        elif hasattr(item, "fspath") and item.fspath:
            p = Path(str(item.fspath))
            stem = p.stem
            fspath_str = str(p).replace("\\", "/")
        else:
            stem = ""

        # Any test in tests/e2e/ or in designated slow modules belongs to slow
        if (
            "/tests/e2e/" in fspath_str
            or fspath_str.endswith("/tests/e2e")
            or stem in SLOW_MODULE_NAMES
        ):
            item.add_marker(slow_mark)


@pytest.fixture(scope="session")
def session_fake_dokkandb() -> FakeDokkanDBClient:
    """Provides a session-scoped in-memory FakeDokkanDBClient instance for the static catalog."""
    return FakeDokkanDBClient()


@pytest.fixture
def fake_dokkandb(session_fake_dokkandb: FakeDokkanDBClient) -> FakeDokkanDBClient:
    """Provides an in-memory FakeDokkanDBClient instance backed by the session static catalog."""
    return session_fake_dokkandb


@pytest.fixture(autouse=True)
def auto_virtual_clock_suite(
    request: pytest.FixtureRequest,
) -> Generator[VirtualClock | None, None, None]:
    """Automatically applies VirtualClock across the entire suite unless marked with 'real_time'."""
    if request.node.get_closest_marker("real_time"):
        yield None
        return

    clock = VirtualClock()
    with clock:
        yield clock


@pytest.fixture
def virtual_clock(
    auto_virtual_clock_suite: VirtualClock | None,
) -> Generator[VirtualClock, None, None]:
    """Provides the active VirtualClock fixture for time simulation."""
    if auto_virtual_clock_suite is not None:
        yield auto_virtual_clock_suite
    else:
        clock = VirtualClock()
        with clock:
            yield clock


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
