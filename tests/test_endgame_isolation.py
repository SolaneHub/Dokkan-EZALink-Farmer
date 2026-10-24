"""Tests verifying the decoupling and isolation of the AI Endgame subsystem.

Verifies:
1. BotEngine() startup does not eagerly load or allocate AI telemetry / episodic memory.
2. EZAFarmTask, StageFarmTask, and LinkLevelFarmTask have zero import dependencies on
   ai.telemetry or ai.endgame_runner.
3. Endgame combat & telemetry components export cleanly via lazy interfaces and backward-compatible shims.
4. start_ai_endgame_run() correctly loads and initializes EndgameRunner on demand.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from unittest.mock import patch

import pytest

import dokkan_eza_link_farmer.ai as ai
from dokkan_eza_link_farmer.ai.endgame import (
    CombatRingBuffer,
    EndgameResult,
    EndgameRunner,
)
from dokkan_eza_link_farmer.ai.models import BossPhase, BossStage, DokkanCard
from dokkan_eza_link_farmer.automation.tasks import (
    box_scanner,
    challenge_task,
    eza_farm,
    link_level_farm,
    stage_farm,
)
from dokkan_eza_link_farmer.core import bot_engine
from dokkan_eza_link_farmer.core.bot_engine import BotEngine


@pytest.mark.fast
class TestSubsystemIsolation:
    """Verifies that core bot startup and farming tasks are completely decoupled from endgame subsystem."""

    def test_core_bot_startup_zero_endgame_telemetry_imports(self):
        """Verifies through AST and runtime inspection that BotEngine does not eagerly import or allocate endgame telemetry."""
        source = inspect.getsource(bot_engine)
        tree = ast.parse(source)

        # Check top-level statements: no import of endgame or telemetry
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    assert "telemetry" not in alias.name
                    assert "endgame" not in alias.name
            elif isinstance(stmt, ast.ImportFrom):
                mod_name = stmt.module or ""
                assert "telemetry" not in mod_name
                assert "endgame" not in mod_name

        engine = BotEngine()
        assert not hasattr(engine, "telemetry_tracker")
        assert not hasattr(engine, "ring_buffer")
        assert not hasattr(engine, "episodic_memory")

    def test_farming_tasks_zero_endgame_imports(self):
        """Verifies through AST analysis that farming tasks have zero imports of telemetry or endgame."""
        for mod in (eza_farm, stage_farm, link_level_farm, box_scanner, challenge_task):
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "telemetry" not in alias.name
                        assert "endgame" not in alias.name
                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    assert "telemetry" not in mod_name
                    assert "endgame" not in mod_name

    def test_lazy_export_interface_on_ai_package(self):
        """Verifies that accessing endgame exports on dokkan_eza_link_farmer.ai works via __getattr__."""
        # EndgameRunner
        runner_cls = ai.EndgameRunner
        assert runner_cls is EndgameRunner

        # CombatRingBuffer
        ring_cls = ai.CombatRingBuffer
        assert ring_cls is CombatRingBuffer

        # apply_team_in_game
        apply_fn = ai.apply_team_in_game
        assert callable(apply_fn)

        # Submodules exposed lazily
        assert ai.telemetry is not None
        assert ai.endgame_runner is not None
        assert ai.endgame is not None

        # Verify all lazy exports resolve cleanly and are present in dir(ai)
        ai_dir = dir(ai)
        for sym in ai._LAZY_ENDGAME_EXPORTS:
            assert sym in ai_dir, f"Expected {sym} to be present in dir(ai)"
            val = getattr(ai, sym)
            assert val is not None, f"Expected {sym} to resolve to non-None value"

        # Attribute error for unknown symbol
        with pytest.raises(AttributeError):
            _ = ai.NonExistentAIComponent

    def test_concurrent_lazy_export_access(self):
        """Verifies thread-safe concurrent access to lazy exports on dokkan_eza_link_farmer.ai."""
        import concurrent.futures

        def load_symbol(sym_name: str):
            return getattr(ai, sym_name)

        symbols = [
            "EndgameRunner",
            "CombatRingBuffer",
            "telemetry",
            "endgame_runner",
            "apply_team_in_game",
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(load_symbol, s) for s in symbols * 5]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                assert res is not None

    def test_backward_compatible_shims(self):
        """Verifies that legacy import paths and subpackage alias modules remain operational."""
        import dokkan_eza_link_farmer.ai.endgame as endgame
        from dokkan_eza_link_farmer.ai.endgame.endgame_runner import (
            EndgameRunner as SubpkgAliasRunner,
        )
        from dokkan_eza_link_farmer.ai.endgame_runner import EndgameRunner as LegacyRunner
        from dokkan_eza_link_farmer.ai.telemetry import CombatRingBuffer as LegacyRingBuffer

        assert LegacyRunner is EndgameRunner
        assert LegacyRingBuffer is CombatRingBuffer
        assert SubpkgAliasRunner is EndgameRunner
        assert endgame.endgame_runner.EndgameRunner is EndgameRunner
        assert "endgame_runner" in endgame.__all__
        assert "runner" in endgame.__all__
        assert "telemetry" in endgame.__all__

    def test_start_ai_endgame_run_contract_and_alias(self):
        """Verifies start_ai_endgame_run public contract and on-demand initialization."""
        engine = BotEngine()
        assert hasattr(engine, "start_ai_endgame_run")
        assert engine.start_ai_endgame_run == engine.start_ai_endgame

        fake_stage = BossStage(
            stage_id=10101,
            event_id=101,
            event_name="Red Zone",
            stage_name="Stage 1",
            phases=[
                BossPhase(
                    phase_index=1,
                    element=1,
                    hp=1000000,
                )
            ],
        )

        dummy_card = DokkanCard(
            id=101,
            name="Goku",
            element=1,
            rarity=4,
            leader_skill="Super class Ki +3",
            passive_skill="ATK +100%",
            links=["Super Saiyan", "Prepared for Battle"],
            categories=["Pure Saiyans"],
        )

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_run:
            mock_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=[dummy_card] * 6,
                stage=fake_stage,
            )
            started = engine.start_ai_endgame_run(stage_identifier=fake_stage, dry_run=True)
            assert started is True
            assert engine.current_task is not None
            engine.stop_task()


@pytest.mark.slow
class TestSubsystemIsolationSubprocess:
    """End-to-end multi-process verification that standard engine and farming tasks don't touch endgame."""

    def test_isolated_clean_process_startup(self):
        check_code = (
            "import sys\n"
            "from dokkan_eza_link_farmer.core.bot_engine import BotEngine\n"
            "from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask\n"
            "from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask\n"
            "from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask\n"
            "from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask\n"
            "from dokkan_eza_link_farmer.automation.tasks.challenge_task import ChallengeTask\n"
            "engine = BotEngine()\n"
            "loaded = [m for m in sys.modules if 'dokkan_eza_link_farmer.ai.endgame' in m or 'telemetry' in m]\n"
            "assert len(loaded) == 0, f'Subsystem eagerly loaded in clean process: {loaded}'\n"
            "print('SUCCESS')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", check_code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Subprocess failed:\n{result.stderr}\n{result.stdout}"
        assert "SUCCESS" in result.stdout

    def test_ai_module_import_does_not_eagerly_import_endgame(self):
        """Verifies that importing dokkan_eza_link_farmer.ai in a clean process does not load endgame subsystem."""
        check_code = (
            "import sys\n"
            "import dokkan_eza_link_farmer.ai as ai\n"
            "assert 'dokkan_eza_link_farmer.ai.endgame' not in sys.modules, 'endgame package eagerly imported'\n"
            "assert 'dokkan_eza_link_farmer.ai.endgame.telemetry' not in sys.modules, 'telemetry eagerly imported'\n"
            "assert 'dokkan_eza_link_farmer.ai.endgame.runner' not in sys.modules, 'runner eagerly imported'\n"
            "# Now access EndgameRunner lazily\n"
            "_ = ai.EndgameRunner\n"
            "assert 'dokkan_eza_link_farmer.ai.endgame' in sys.modules, 'endgame package not imported on demand'\n"
            "print('SUCCESS')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", check_code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Subprocess failed:\n{result.stderr}\n{result.stdout}"
        assert "SUCCESS" in result.stdout

    def test_legacy_backward_compatibility_across_clean_process(self):
        """Verifies that legacy shims in a clean process resolve to identical types as new endgame package."""
        check_code = (
            "import dokkan_eza_link_farmer.ai.endgame_runner as er\n"
            "import dokkan_eza_link_farmer.ai.telemetry as tel\n"
            "import dokkan_eza_link_farmer.ai.endgame.runner as reg\n"
            "import dokkan_eza_link_farmer.ai.endgame.telemetry as teg\n"
            "import dokkan_eza_link_farmer.ai.endgame.endgame_runner as eger\n"
            "import dokkan_eza_link_farmer.ai.endgame as eg\n"
            "assert er.EndgameRunner is reg.EndgameRunner\n"
            "assert er.apply_team_in_game is reg.apply_team_in_game\n"
            "assert tel.CombatRingBuffer is teg.CombatRingBuffer\n"
            "assert tel.EpisodicMemory is teg.EpisodicMemory\n"
            "assert tel.DEFAULT_MEMORY_CACHE_PATH == teg.DEFAULT_MEMORY_CACHE_PATH\n"
            "assert eger.EndgameRunner is reg.EndgameRunner\n"
            "assert eg.endgame_runner.EndgameRunner is reg.EndgameRunner\n"
            "assert eg.runner.EndgameRunner is reg.EndgameRunner\n"
            "assert eg.telemetry.CombatRingBuffer is teg.CombatRingBuffer\n"
            "assert 'endgame_runner' in eg.__all__\n"
            "print('SUCCESS')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", check_code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Subprocess failed:\n{result.stderr}\n{result.stdout}"
        assert "SUCCESS" in result.stdout
