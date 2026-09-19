import argparse
import sys
from core.bot_engine import BotEngine
from interfaces.cli import TerminalCLI
from interfaces.discord_bot import run_discord_bot


def main():
    parser = argparse.ArgumentParser(description="Dokkan Battle Automation Bot (CLI & Discord)")
    parser.add_argument("--discord", action="store_true", help="Avvia l'interfaccia bot Discord")
    parser.add_argument("--scrcpy", action="store_true", help="Avvia la finestra di mirroring scrcpy")
    parser.add_argument("--devices", action="store_true", help="Elenca i dispositivi collegati ed esce")
    parser.add_argument("--farm", type=int, nargs="?", const=10, help="Avvia direttamente il farming di N run")
    parser.add_argument("--eza", type=int, nargs="?", const=30, help="Avvia direttamente EZA fino al livello specificato")
    parser.add_argument("--link", type=int, nargs="?", const=20, help="Avvia direttamente il Link Level farming")
    parser.add_argument("--config", type=str, default="config/settings.yaml", help="Percorso del file di configurazione")

    args = parser.parse_args()

    engine = BotEngine(config_path=args.config)

    if args.devices:
        devices = engine.list_devices()
        print("Dispositivi Android rilevati:")
        for d in devices:
            print(f" - {d['serial']} ({d['status']}) [{d['model']}]")
        return

    if args.discord:
        print("[Avvio] Modalità Discord Bot selezionata...")
        try:
            engine.connect()
        except Exception as e:
            print(f"[Avviso] Connessione dispositivo: {e}")
        run_discord_bot(engine)
        return

    if args.scrcpy:
        try:
            engine.connect()
            engine.start_scrcpy()
            print("Premi CTRL+C per chiudere...")
            while True:
                pass
        except KeyboardInterrupt:
            engine.stop_scrcpy()
        return

    # Direct task execution flags
    if args.farm is not None:
        engine.connect()
        engine.start_stage_farm(runs=args.farm)
        cli = TerminalCLI(engine)
        cli.run()
        return

    if args.eza is not None:
        engine.connect()
        engine.start_eza_farm(target_level=args.eza)
        cli = TerminalCLI(engine)
        cli.run()
        return

    if args.link is not None:
        engine.connect()
        engine.start_link_level_farm(runs=args.link)
        cli = TerminalCLI(engine)
        cli.run()
        return

    # Default: Interactive Terminal CLI
    cli = TerminalCLI(engine)
    cli.run()


if __name__ == "__main__":
    main()
