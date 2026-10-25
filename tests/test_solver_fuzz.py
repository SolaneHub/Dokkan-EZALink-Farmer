"""Integration tests for DokkanConstraintSolver using generative fuzzing.

Asserts high-level black-box invariants under randomized Dokkan boxes and mission constraints:
1. Zero unhandled exceptions or crashes.
2. Recommended teams contain exactly 6 unique cards (no duplicate IDs).
3. If solved, all mission conditions (categories, rainbow typings, super/extreme class) are met.
4. If mathematically impossible or unsatisfiable, the solver gracefully degrades via ValueError.
"""

from __future__ import annotations

import pytest
from tools.fuzz_team_solver import execute_fuzz_run, run_fuzzer

from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from tests.harness.fake_dokkandb import FakeDokkanDBClient


@pytest.mark.fast
class TestDokkanSolverFuzz:
    """Parametrized high-level fuzzed robustness tests for DokkanConstraintSolver."""

    @pytest.mark.parametrize("seed", [42, 1337, 2026, 9999])
    def test_generative_fuzz_runs(self, seed: int):
        """Verifies solver invariants across 25 procedural runs per seed."""
        solved, unsat, elapsed = run_fuzzer(
            num_runs=25,
            min_box=10,
            max_box=100,
            seed=seed,
            verbose=False,
        )
        assert solved + unsat == 25, "All runs must complete either as SOLVED or UNSATISFIABLE"
        assert elapsed < 3.0, f"25 fuzz runs took {elapsed:.3f}s (must complete under 3s)"

    def test_extreme_small_box_degradation(self):
        """Boxes with fewer than 6 distinct cards must gracefully degrade without crash."""
        solver = DokkanConstraintSolver(dokkandb=FakeDokkanDBClient())
        import random

        rng = random.Random(777)
        result = execute_fuzz_run(solver, run_idx=1, box_size=5, rng=rng)
        assert result.status == "UNSATISFIABLE"
        assert result.error_message is not None
        assert "Need at least 6 distinct cards" in result.error_message

    def test_full_fuzz_suite_under_three_seconds(self):
        """Validates that a 50-run batch finishes in under 3.0 seconds with zero crashes."""
        solved, unsat, elapsed = run_fuzzer(
            num_runs=50,
            min_box=10,
            max_box=100,
            seed=101,
            verbose=False,
        )
        assert solved > 0, "Expected at least some valid team solutions in 50 runs"
        assert solved + unsat == 50
        assert elapsed < 3.0, f"50 runs took {elapsed:.3f}s (target < 3.0s)"
