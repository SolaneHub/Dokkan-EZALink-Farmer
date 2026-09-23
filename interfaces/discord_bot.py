import asyncio
import io
from typing import Any

import cv2
import discord
from discord import app_commands
from discord.ext import commands

from core.bot_engine import BotEngine
from core.i18n import get_language, t


class DiscordBotClient(commands.Bot):
    """Discord Bot controller for Dokkan Battle Automation."""

    def __init__(self, engine: BotEngine):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.engine = engine
        self._main_channel: discord.abc.Messageable | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

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
            keywords = [
                "complet",
                "Stamina",
                "Game Over",
                "Error",
                "Errore",
                "Start",
                "Inizio",
                "trovat",
                "found",
                "victory",
            ]
            if any(k.lower() in msg.lower() for k in keywords):
                asyncio.run_coroutine_threadsafe(self._main_channel.send(f"🤖 **[Dokkan-EZALink]** {msg}"), self._loop)

    def _on_bot_run(self, curr: int, tot: Any):
        if self._main_channel and self._loop:
            tot_str = str(tot) if tot and tot > 0 else "∞"
            asyncio.run_coroutine_threadsafe(
                self._main_channel.send(f"📊 **Progress:** `{curr}/{tot_str}` runs completed."), self._loop
            )

    async def on_ready(self):
        if self.user:
            print(f"[Discord] Bot logged in as {self.user.name} (ID: {self.user.id})")
        else:
            print("[Discord] Bot logged in")
        try:
            await self.change_presence(
                activity=discord.Activity(type=discord.ActivityType.playing, name="EZA 999 & Link Leveling")
            )
        except Exception:
            pass
        target_channel_id = self.engine.config.get("discord", {}).get("channel_id")
        if target_channel_id:
            channel = self.get_channel(target_channel_id)
            if isinstance(channel, discord.abc.Messageable):
                self._main_channel = channel
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
                color=discord.Color.gold() if info["task_running"] else discord.Color.blue(),
            )
            embed.add_field(
                name=t("discord.field_device"), value=str(info["device_serial"] or t("discord.val_none")), inline=True
            )
            embed.add_field(
                name=t("discord.field_running"),
                value=t("discord.val_yes") if info["task_running"] else t("discord.val_no"),
                inline=True,
            )
            embed.add_field(name=t("discord.field_task"), value=str(info["task_type"]), inline=True)
            runs_target_val = info.get("runs_target")
            target_display = str(runs_target_val) if runs_target_val is not None and runs_target_val > 0 else "∞"
            embed.add_field(
                name=t("discord.field_progress"), value=f"{info['runs_completed']} / {target_display}", inline=True
            )
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

        @self.tree.command(name="eza", description="Starts continuous automated climbing in Extreme Z-Battle")
        @app_commands.describe(target_level="Target level to reach (default: 999)")
        async def cmd_eza(interaction: discord.Interaction, target_level: int | None = 999):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            if isinstance(interaction.channel, discord.abc.Messageable):
                self._main_channel = interaction.channel
            ok = self.engine.start_eza_farm(target_level=target_level or 999)
            if ok:
                await interaction.response.send_message(t("discord.eza_started", level=target_level or 999))
            else:
                await interaction.response.send_message(t("discord.task_conflict"))

        @self.tree.command(name="link", description="Starts Link Level farming (Chamber of Spirit and Time)")
        @app_commands.describe(runs="Number of runs (optional: leave empty to farm until stamina runs out)")
        async def cmd_link(interaction: discord.Interaction, runs: int | None = None):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message(t("discord.not_authorized"), ephemeral=True)
                return

            if isinstance(interaction.channel, discord.abc.Messageable):
                self._main_channel = interaction.channel
            actual_runs = runs if (runs is not None and runs > 0) else None
            ok = self.engine.start_link_level_farm(runs=actual_runs)
            if ok:
                runs_label = str(actual_runs) if actual_runs is not None else t("discord.link_runs_unlimited")
                await interaction.response.send_message(t("discord.link_started", runs=runs_label))
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
        @app_commands.choices(
            action=[app_commands.Choice(name="start", value="start"), app_commands.Choice(name="stop", value="stop")]
        )
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


def setup_discord_interactive(engine: BotEngine) -> bool:
    """Interactively guides the user through setting up Discord bot credentials and saves them to settings.yaml."""
    lang = get_language()
    doc_path = "docs/DISCORD_SETUP.it.md" if lang == "it" else "docs/DISCORD_SETUP.md"
    none_val = t("discord.setup.val_none")
    all_val = t("discord.setup.val_all")

    print("=" * 65)
    print(t("discord.setup.title"))
    print("=" * 65)
    print(t("discord.setup.requirements"))
    print(t("discord.setup.req_token"))
    print(t("discord.setup.req_channel"))
    print(t("discord.setup.guide", doc_path=doc_path))
    print("-" * 65)

    current_discord = engine.config.get("discord", {})
    current_token = current_discord.get("token", "")
    masked_token = f"...{current_token[-6:]}" if len(current_token) > 6 else f"({none_val})"

    try:
        token = input(t("discord.setup.prompt_token", masked=masked_token)).strip()
        if not token and current_token:
            token = current_token

        if not token or token.startswith("YOUR_DISCORD"):
            print(t("discord.setup.token_empty"))
            return False

        current_channel = str(current_discord.get("channel_id", "") or "")
        channel_placeholder = current_channel if current_channel else none_val
        channel_input = input(t("discord.setup.prompt_channel", current=channel_placeholder)).strip()
        if not channel_input and current_channel:
            channel_input = current_channel

        try:
            channel_id = int(channel_input) if channel_input else 0
        except ValueError:
            print(t("discord.setup.channel_invalid"))
            channel_id = 0

        current_users = current_discord.get("allowed_user_ids", [])
        current_users_str = ", ".join(str(u) for u in current_users) if current_users else all_val
        user_input = input(t("discord.setup.prompt_user", current=current_users_str)).strip()
        allowed_user_ids = current_users
        if user_input:
            try:
                allowed_user_ids = [int(user_input)]
            except ValueError:
                pass

        if "discord" not in engine.config:
            engine.config["discord"] = {}

        engine.config["discord"]["token"] = token
        engine.config["discord"]["channel_id"] = channel_id
        engine.config["discord"]["allowed_user_ids"] = allowed_user_ids
        engine.save_config()

        print(t("discord.setup.saved"))
        print("=" * 65)
        return True
    except (KeyboardInterrupt, EOFError):
        print(f"\n{t('discord.setup.cancelled')}")
        return False


def run_discord_bot(engine: BotEngine):
    """Starts the Discord bot client with token from settings."""
    token = (engine.config.get("discord", {}).get("token") or "").strip()
    if not token or token.startswith("YOUR_DISCORD"):
        print(t("discord.missing_token_warning"))
        print(t("discord.missing_token_hint"))
        try:
            choice = input(t("discord.prompt_configure_now")).strip().lower()
            if choice not in ("n", "no"):
                ok = setup_discord_interactive(engine)
                if not ok:
                    return
                token = (engine.config.get("discord", {}).get("token") or "").strip()
            else:
                return
        except (KeyboardInterrupt, EOFError):
            return

    if not token:
        return

    bot = DiscordBotClient(engine)
    bot.run(token)
