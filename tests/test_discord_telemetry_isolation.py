"""Tests for Discord Bot isolation and zero-dependency startup."""

from __future__ import annotations

from unittest.mock import MagicMock

from dokkan_eza_link_farmer.ai.telemetry import (
    CombatRingBuffer,
    CombatTelemetryTracker,
    is_debug_telemetry_enabled,
    set_debug_telemetry,
)
from dokkan_eza_link_farmer.core.bot_engine import BotEngine


class TestDiscordBotIsolation:
    """Verifies that Discord Bot is treated as a secondary optional integration."""

    def test_bot_engine_init_does_not_attach_discord_listener(self):
        """Engine startup should never instantiate DiscordBotClient or attach discord listeners."""
        engine = BotEngine()
        # Engine log and run callbacks should only contain CLI listeners when CLI attaches, none initially
        assert len(engine.log_callbacks) == 0
        assert len(engine.run_callbacks) == 0

    def test_discord_callbacks_swallow_exceptions_safely(self):
        """No exception from discord background notification callbacks can crash automation."""
        from dokkan_eza_link_farmer.integrations.discord_bot import DiscordBotClient

        mock_engine = MagicMock()
        mock_engine.config = {"discord": {"allowed_user_ids": []}}

        bot = DiscordBotClient(mock_engine)
        bot._main_channel = MagicMock()
        bot._loop = MagicMock()
        # Simulate broken loop or communication error
        bot._loop.is_running.side_effect = RuntimeError("Event loop is closed")

        # Calling _on_bot_log and _on_bot_run should handle errors gracefully without raising
        bot._on_bot_log("Test Victory Completed!")
        bot._on_bot_run(5, 10)


class TestTelemetryFreezing:
    """Verifies that extended telemetry ring-buffer accumulation is disabled during standard farming."""

    def test_standard_farming_ring_buffer_frozen_by_default(self):
        """In standard mode without --debug-telemetry, CombatTelemetryTracker skips ring_buffer frames."""
        set_debug_telemetry(False)
        assert is_debug_telemetry_enabled() is False

        ring = CombatRingBuffer(capacity=4)
        tracker = CombatTelemetryTracker(ring_buffer=ring)

        frame = tracker.record_action(
            active_slot=1,
            target_card_id=101,
            incoming_damage=50000,
            player_hp_after=80.0,
            is_lethal=False,
        )

        assert frame is not None
        # Since debug_telemetry is frozen, ring buffer remains empty to conserve memory
        assert len(ring) == 0

    def test_debug_telemetry_flag_enables_ring_buffer_accumulation(self):
        """When --debug-telemetry is set or debug_telemetry=True, ring_buffer records frames."""
        set_debug_telemetry(True)
        assert is_debug_telemetry_enabled() is True

        ring = CombatRingBuffer(capacity=4)
        tracker = CombatTelemetryTracker(ring_buffer=ring)

        frame = tracker.record_action(
            active_slot=2,
            target_card_id=102,
            incoming_damage=700000,
            player_hp_after=0.0,
            is_lethal=True,
        )

        assert frame is not None
        assert len(ring) == 1
        assert ring.get_pre_ko_frames()[0].target_card_id == 102

        # Reset flag
        set_debug_telemetry(False)
