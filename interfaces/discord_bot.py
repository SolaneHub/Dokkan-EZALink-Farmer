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
            # Post log message if it's important
            if any(k in msg for k in ["completat", "Stamina", "Game Over", "Errore", "Inizio"]):
                asyncio.run_coroutine_threadsafe(
                    self._main_channel.send(f"🤖 **[DokkanBot]** {msg}"),
                    self._loop
                )

    def _on_bot_run(self, curr: int, tot: int):
        if self._main_channel and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._main_channel.send(f"📊 **Progresso:** `{curr}/{tot}` run completate."),
                self._loop
            )

    async def on_ready(self):
        print(f"[Discord] Bot connesso come {self.user.name} (ID: {self.user.id})")
        target_channel_id = self.engine.config.get("discord", {}).get("channel_id")
        if target_channel_id:
            self._main_channel = self.get_channel(target_channel_id)
            if self._main_channel:
                await self._main_channel.send("🟢 **Dokkan Battle Bot online e pronto ai comandi!**")

    async def _register_slash_commands(self):
        @self.tree.command(name="status", description="Mostra lo stato attuale del bot e del dispositivo")
        async def cmd_status(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato a usare questo comando.", ephemeral=True)
                return

            info = self.engine.get_status_summary()
            embed = discord.Embed(
                title="⚡ Dokkan Bot Status",
                color=discord.Color.gold() if info["task_running"] else discord.Color.blue()
            )
            embed.add_field(name="📱 Dispositivo", value=str(info["device_serial"] or "Nessuno"), inline=True)
            embed.add_field(name="⚙️ In Esecuzione", value="Sì" if info["task_running"] else "No", inline=True)
            embed.add_field(name="🎯 Attività", value=str(info["task_type"]), inline=True)
            embed.add_field(name="📊 Progresso", value=f"{info['runs_completed']} / {info['runs_target']}", inline=True)
            embed.add_field(name="🔍 Schermata", value=str(info["current_state"]), inline=True)

            await interaction.response.send_message(embed=embed)

        @self.tree.command(name="screenshot", description="Cattura e invia uno screenshot in tempo reale del gioco")
        async def cmd_screenshot(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            await interaction.response.defer()
            try:
                screen = self.engine.get_screenshot()
                _, buffer = cv2.imencode(".png", screen)
                file = discord.File(io.BytesIO(buffer.tobytes()), filename="dokkan_screen.png")
                await interaction.followup.send(content="📸 **Schermata attuale di Dokkan Battle:**", file=file)
            except Exception as e:
                await interaction.followup.send(f"❌ Errore cattura schermo: {e}")

        @self.tree.command(name="farm", description="Avvia il farming automatico a ripetizione dello stage attuale")
        @app_commands.describe(runs="Numero di completamenti desiderati (default: 10)")
        async def cmd_farm(interaction: discord.Interaction, runs: Optional[int] = 10):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_stage_farm(runs=runs or 10)
            if ok:
                await interaction.response.send_message(f"▶️ **Farming stage avviato:** {runs} run impostate.")
            else:
                await interaction.response.send_message("⚠️ Impossibile avviare: un'attività è già in esecuzione.")

        @self.tree.command(name="eza", description="Avvia la scalata automatica continua in Extreme Z-Battle")
        @app_commands.describe(target_level="Livello target da raggiungere (default: 999)")
        async def cmd_eza(interaction: discord.Interaction, target_level: Optional[int] = 999):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_eza_farm(target_level=target_level or 999)
            if ok:
                await interaction.response.send_message(f"⚔️ **EZA Farming avviato:** scalata continua fino al Livello {target_level or 999}!")
            else:
                await interaction.response.send_message("⚠️ Impossibile avviare: un'attività è già in esecuzione.")

        @self.tree.command(name="link", description="Avvia il farming di Link Level (Quest 31-4 / 34-4)")
        @app_commands.describe(runs="Numero di run da eseguire (default: 20)")
        async def cmd_link(interaction: discord.Interaction, runs: Optional[int] = 20):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self._main_channel = interaction.channel
            ok = self.engine.start_link_level_farm(runs=runs or 20)
            if ok:
                await interaction.response.send_message(f"🔗 **Link Level farming avviato:** {runs} run impostate.")
            else:
                await interaction.response.send_message("⚠️ Impossibile avviare: un'attività è già in esecuzione.")

        @self.tree.command(name="stop", description="Arresta l'attività attualmente in esecuzione")
        async def cmd_stop(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self.engine.stop_task()
            await interaction.response.send_message("🛑 **Attività fermata con successo.**")

        @self.tree.command(name="pause", description="Mette in pausa l'attività")
        async def cmd_pause(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self.engine.pause_task()
            await interaction.response.send_message("⏸️ **Attività in pausa.**")

        @self.tree.command(name="resume", description="Riprende l'attività")
        async def cmd_resume(interaction: discord.Interaction):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            self.engine.resume_task()
            await interaction.response.send_message("▶️ **Attività ripresa.**")

        @self.tree.command(name="scrcpy", description="Avvia o chiude la finestra di mirroring scrcpy su Mac")
        @app_commands.describe(action="start o stop")
        @app_commands.choices(action=[
            app_commands.Choice(name="start", value="start"),
            app_commands.Choice(name="stop", value="stop")
        ])
        async def cmd_scrcpy(interaction: discord.Interaction, action: app_commands.Choice[str]):
            if not self._is_user_allowed(interaction.user.id):
                await interaction.response.send_message("❌ Non sei autorizzato.", ephemeral=True)
                return

            if action.value == "start":
                ok = self.engine.start_scrcpy()
                msg = "🖥️ Finestra scrcpy avviata sul Mac." if ok else "❌ Errore nell'avvio di scrcpy."
            else:
                self.engine.stop_scrcpy()
                msg = "🖥️ Finestra scrcpy chiusa."
            await interaction.response.send_message(msg)


def run_discord_bot(engine: BotEngine):
    token = engine.config.get("discord", {}).get("token")
    if not token or token == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("[Discord] Errore: Nessun token specificato in config/settings.yaml under discord.token!")
        print("[Discord] Inserisci il token del bot in config/settings.yaml per utilizzare l'integrazione Discord.")
        return

    bot = DiscordBotClient(engine)
    bot.run(token)
