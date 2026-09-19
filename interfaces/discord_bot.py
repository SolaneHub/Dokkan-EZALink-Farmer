import os
import io
import time
import asyncio
import cv2
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from core.bot_engine import BotEngine
from core.i18n import t


class DiscordBotClient(commands.Bot):
    """Discord Bot controller for Dokkan Battle Automation."""

    def __init__(self, engine: BotEngine):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.engine = engine
        self._main_channel: Optional[discord.TextChannel] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def setup_hook(self):
        self._loop = asyncio.get_running_loop()

        # Connect engine callbacks to Discord notifications
        self.engine.register_log_callback(self._on_bot_log)
        self.engine.register_run_callback(self._on_bot_run)

        # Register slash commands
        await self._register_slash_commands()
        await self.tree.sync()

    def _is_user_allowed(self, user_id: int) -> bool:
        allowed = self.engine.config.get("discord", {}).get("allowed_user_ids", [])
        if not allowed:
            return True
        return user_id in allowed

    def _on_bot_log(self, msg: str):
        if self._main_channel and self._loop:
            # Relay notification if message indicates a significant state change
            keywords = ["complet", "Stamina", "Game Over", "Error", "Errore", "Start", "Inizio", "trovat", "found", "victory"]
            if any(k.lower() in msg.lower() for k in keywords):
                asyncio.run_coroutine_threadsafe(
                    self._main_channel.send(f"🤖 **[DokkanBot]** {msg}"),
                    self._loop
                )

    def _on_bot_run(self, curr: int, tot: int):
        if self._main_channel and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._main_channel.send(f"📊 **Progress:** `{curr}/{tot}` runs completed."),
                self._loop
            )

    async def on_ready(self):
        print(f"[Discord] Bot logged in as {self.user.name} (ID: {self.user.id})")
        target_channel_id = self.engine.config.get("discord", {}).get("channel_id")
        if target_channel_id:
            self._main_channel = self.get_channel(target_channel_id)
            if self._main_channel:
                await self._main_channel.send(t("discord.bot_ready"))

    async def _register_slash_commands(self):
        @self.tree.command(name="status", description="Shows current status of the bot and device")
        async def cmd_status(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            info = self.engine.get_status_summary()
            embed = discord.Embed(
                title=t("discord.status_title"),
                color=discord.Color.gold() if info["task_running"] else discord.Color.blue()
            )
            embed.add_field(name=t("discord.field_device"), value=str(info["device_serial"] or t("discord.val_none")), inline=True)
            embed.add_field(name=t("discord.field_running"), value=t("discord.val_yes") if info["task_running"] else t("discord.val_no"), inline=True)
            embed.add_field(name=t("discord.field_task"), value=str(info["task_type"]), inline=True)
            embed.add_field(name=t("discord.field_progress"), value=f"{info['runs_completed']} / {info['runs_target']}", inline=True)
            embed.add_field(name=t("discord.field_screen"), value=str(info["current_state"]), inline=True)

            await interaction.response.send_message(embed=embed)

        @self.tree.command(name="screenshot", description="Captures and sends a real-time game screenshot")
        async def cmd_screenshot(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            await interaction.response.defer()
            try:
                screen = self.engine.get_screenshot()
                _, buffer = cv2.imencode(".png", screen)
                file = discord.File(io.BytesIO(buffer.tobytes()), filename="dokkan_screen.png")
                await interaction.followup.send(content=t("discord.screenshot_caption"), file=file)
            except Exception as e:
                await interaction.followup.send(t("discord.screenshot_error", error=str(e)))

        @self.tree.command(name="farm", description="Starts repeated automated farming of the current stage")
        @app_commands.describe(runs="Desired completion count (default: 10)")
        async def cmd_farm(interaction: discord.Interaction, runs: Optional[int] = 10):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_stage_farm(runs=runs or 10)
            if ok:
                await interaction.response.send_message(t("discord.farm_started", runs=runs or 10))
            else:
                await interaction.response.send_message(t("discord.task_conflict"))

        @self.tree.command(name="eza", description="Starts continuous automated climbing in Extreme Z-Battle")
        @app_commands.describe(target_level="Target level to reach (default: 999)")
        async def cmd_eza(interaction: discord.Interaction, target_level: Optional[int] = 999):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_eza_farm(target_level=target_level or 999)
            if ok:
                await interaction.response.send_message(t("discord.eza_started", level=target_level or 999))
            else:
                await interaction.response.send_message(t("discord.task_conflict"))

        @self.tree.command(name="link", description="Starts Link Level farming (Quest 31-4 / 34-4)")
        @app_commands.describe(runs="Number of runs to execute (default: 20)")
        async def cmd_link(interaction: discord.Interaction, runs: Optional[int] = 20):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_link_level_farm(runs=runs or 20)
            if ok:
                await interaction.response.send_message(t("discord.link_started", runs=runs or 20))
            else:
                await interaction.response.send_message(t("discord.task_conflict"))

        @self.tree.command(name="stop", description="Stops currently active automation task")
        async def cmd_stop(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self.engine.stop_task()
            await interaction.response.send_message(t("discord.task_stopped"))

        @self.tree.command(name="pause", description="Pauses active automation task")
        async def cmd_pause(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self.engine.pause_task()
            await interaction.response.send_message(t("discord.task_paused"))

        @self.tree.command(name="resume", description="Resumes paused automation task")
        async def cmd_resume(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            self.engine.resume_task()
            await interaction.response.send_message(t("discord.task_resumed"))

        @self.tree.command(name="scrcpy", description="Starts or stops scrcpy screen mirroring on host computer")
        @app_commands.describe(action="start or stop")
        @app_commands.choices(action=[
            app_commands.Choice(name="start", value="start"),
            app_commands.Choice(name="stop", value="stop")
        ])
        async def cmd_scrcpy(interaction: discord.Interaction, action: app_commands.Choice[str]):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            if action.value == "start":
                ok = self.engine.start_scrcpy()
                msg = t("discord.scrcpy_started") if ok else t("discord.scrcpy_failed")
            else:
                self.engine.stop_scrcpy()
                msg = t("discord.scrcpy_stopped")
            await interaction.response.send_message(msg)


def run_discord_bot(engine: BotEngine):
    """Starts the Discord bot client with token from settings."""
    token = engine.config.get("discord", {}).get("token")
    if not token or token == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print(t("discord.missing_token_warning"))
        print(t("discord.missing_token_hint"))
        return

    bot = DiscordBotClient(engine)
    bot.run(token)
