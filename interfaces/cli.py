import os
import sys
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

from core.bot_engine import BotEngine


class TerminalCLI:
    """Rich interactive Terminal Command Interface for DokkanBattleBot."""

    def __init__(self, engine: BotEngine):
        self.engine = engine
        self.console = Console()

        # Route bot logs into Rich console
        self.engine.register_log_callback(self._on_log)
        self.engine.register_run_callback(self._on_run_update)

    def _on_log(self, msg: str):
        self.console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim] [cyan][BOT][/cyan] {msg}")

    def _on_run_update(self, curr: int, tot: int):
        self.console.print(f"[bold green]✓ Progresso:[/] {curr}/{tot} completati")

    def print_banner(self):
        banner = Text()
        banner.append("🔥 DOKKAN BATTLE AUTOMATION BOT 🔥\n", style="bold red")
        banner.append("Controllore via ADB & scrcpy | Supporto Terminale & Discord\n", style="yellow")
        banner.append("Digita 'help' per la lista dei comandi disponibili.", style="dim")
        self.console.print(Panel(banner, border_style="red", expand=False))

    def print_help(self):
        table = Table(title="Comandi Disponibili", border_style="cyan")
        table.add_column("Comando", style="bold green")
        table.add_column("Parametri", style="italic")
        table.add_column("Descrizione", style="white")

        table.add_row("devices", "", "Elenca i dispositivi Android connessi via USB/Wi-Fi")
        table.add_row("connect", "[serial]", "Connette al dispositivo (auto-detect se omesso)")
        table.add_row("scrcpy", "", "Apre la finestra di visualizzazione dello schermo via scrcpy")
        table.add_row("scrcpy-stop", "", "Chiude la finestra di scrcpy")
        table.add_row("inspect", "", "Cattura lo schermo e rileva lo stato attuale del gioco")
        table.add_row("shot", "[file.png]", "Salva uno screenshot del gioco")
        table.add_row("farm", "[run=10]", "Avvia il farming a ripetizione dello stage attuale")
        table.add_row("eza", "[livello=30]", "Avvia l'avanzamento automatico di Extreme Z-Battle")
        table.add_row("link", "[run=20]", "Avvia il farming di Link Level (Quest 31-4 / 34-4)")
        table.add_row("status", "", "Mostra lo stato del bot e delle attività in corso")
        table.add_row("stop", "", "Ferma l'attività in esecuzione")
        table.add_row("pause", "", "Mette in pausa l'attività")
        table.add_row("resume", "", "Riprende l'attività in pausa")
        table.add_row("exit / quit", "", "Chiude il programma")

        self.console.print(table)

    def print_status(self):
        info = self.engine.get_status_summary()
        table = Table(title="Stato del Bot", border_style="blue")
        table.add_column("Proprietà", style="bold")
        table.add_column("Valore", style="yellow")

        table.add_row("Dispositivo", str(info["device_serial"] or "Non connesso"))
        table.add_row("Attività in corso", str(info["task_running"]))
        table.add_row("Tipo attività", str(info["task_type"]))
        table.add_row("Run completate", f"{info['runs_completed']} / {info['runs_target']}")
        table.add_row("Stato schermata", str(info["current_state"]))

        self.console.print(table)

    def run(self):
        self.print_banner()

        # Attempt auto-connect initially
        try:
            self.engine.connect()
        except Exception as e:
            self.console.print(f"[yellow]Nota:[/] Nessun dispositivo connesso all'avvio ({e}).")
            self.console.print("[dim]Collega il telefono con USB Debugging e digita 'connect'.[/dim]\n")

        while True:
            try:
                line = Prompt.ask("[bold cyan]dokkan-bot>[/bold cyan]").strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0].lower()
                args = parts[1:]

                if cmd in ("exit", "quit", "q"):
                    if self.engine.is_task_running():
                        self.engine.stop_task()
                    self.engine.stop_scrcpy()
                    self.console.print("[bold yellow]Uscita dal bot... Ciao![/]")
                    break

                elif cmd in ("help", "?"):
                    self.print_help()

                elif cmd == "devices":
                    devices = self.engine.list_devices()
                    if not devices:
                        self.console.print("[red]Nessun dispositivo rilevato da ADB.[/]")
                    else:
                        t = Table(title="Dispositivi Rilevati", border_style="green")
                        t.add_column("Seriale", style="bold")
                        t.add_column("Stato")
                        t.add_column("Modello")
                        for d in devices:
                            t.add_row(d["serial"], d["status"], d["model"])
                        self.console.print(t)

                elif cmd == "connect":
                    serial = args[0] if args else None
                    try:
                        self.engine.connect(serial)
                    except Exception as e:
                        self.console.print(f"[bold red]Errore connessione:[/] {e}")

                elif cmd == "scrcpy":
                    self.engine.start_scrcpy()

                elif cmd == "scrcpy-stop":
                    self.engine.stop_scrcpy()

                elif cmd == "status":
                    self.print_status()

                elif cmd in ("inspect", "state"):
                    try:
                        state = self.engine.inspect_current_state()
                        self.console.print(f"[bold green]Stato schermata attuale:[/] [bold yellow]{state.value}[/]")
                    except Exception as e:
                        self.console.print(f"[red]Errore inspect:[/] {e}")

                elif cmd in ("shot", "screenshot"):
                    filename = args[0] if args else f"screenshot_{int(time.time())}.png"
                    try:
                        path = self.engine.save_screenshot_to_file(filename)
                        self.console.print(f"[green]Screenshot salvato in:[/] {path}")
                    except Exception as e:
                        self.console.print(f"[red]Errore screenshot:[/] {e}")

                elif cmd == "farm":
                    runs = int(args[0]) if args and args[0].isdigit() else 10
                    self.engine.start_stage_farm(runs=runs)

                elif cmd == "eza":
                    target_lvl = int(args[0]) if args and args[0].isdigit() else 30
                    self.engine.start_eza_farm(target_level=target_lvl)

                elif cmd == "link":
                    runs = int(args[0]) if args and args[0].isdigit() else 20
                    self.engine.start_link_level_farm(runs=runs)

                elif cmd == "stop":
                    self.engine.stop_task()

                elif cmd == "pause":
                    self.engine.pause_task()

                elif cmd == "resume":
                    self.engine.resume_task()

                else:
                    self.console.print(f"[red]Comando sconosciuto:[/] '{cmd}'. Digita 'help' per la lista comandi.")

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interruzione rilevata. Digita 'exit' per uscire.[/]")
            except Exception as e:
                self.console.print(f"[bold red]Errore imprevisto:[/] {e}")
