from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dokkan_eza_link_farmer import __version__
from dokkan_eza_link_farmer.core.bot_engine import BotEngine
from dokkan_eza_link_farmer.core.i18n import set_language
from dokkan_eza_link_farmer.core.system_tools import SingleInstanceMutex
from dokkan_eza_link_farmer.core.updater import check_for_updates
from dokkan_eza_link_farmer.integrations.discord_bot import run_discord_bot
from dokkan_eza_link_farmer.ui.cli import TerminalCLI


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dokkan-farmer",
        description="Dokkan-EZALink-Farmer: Automated EZA Climbing & Link Level Grinder (CLI & Discord)",
    )
    parser.add_argument(
        "--lang",
        "-l",
        type=str,
        choices=["en", "it"],
        default=None,
        help="Set interface language ('en' for English, 'it' for Italian)",
    )
    parser.add_argument("--discord", action="store_true", help="Launch Discord Bot interface")
    parser.add_argument(
        "--scrcpy", action="store_true", help="Launch scrcpy zero-latency screen mirroring"
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run full environment diagnostics (scrcpy, adb, OS, devices)",
    )
    parser.add_argument(
        "--devices", action="store_true", help="List connected Android devices and exit"
    )
    parser.add_argument(
        "--check-updates",
        action="store_true",
        help="Check official GitHub Releases for newer version",
    )
    parser.add_argument(
        "--eza",
        type=int,
        nargs="?",
        const=999,
        help="Directly start EZA continuous climbing up to specified level (default: 999)",
    )
    parser.add_argument(
        "--link",
        type=int,
        nargs="?",
        const=-1,
        default=None,
        help="Directly start Link Level farming (optional: N runs, default: until stamina depleted)",
    )
    parser.add_argument(
        "--boost",
        dest="boost",
        action="store_true",
        default=None,
        help="Enable Boost for Link Level farming",
    )
    parser.add_argument(
        "--no-boost",
        dest="boost",
        action="store_false",
        help="Disable Boost for Link Level farming",
    )
    parser.add_argument(
        "--config", type=str, default="config/settings.yaml", help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--version", "-v", action="version", version=f"Dokkan-EZALink-Farmer v{__version__}"
    )

    args = parser.parse_args()

    # CLI flag takes precedence over configuration
    if args.lang:
        set_language(args.lang)

    if args.check_updates:
        print(f"Current version: v{__version__}")
        print("Checking GitHub Releases...")
        update = check_for_updates(__version__)
        if update:
            print(f"✨ New release available: {update['tag']}!")
            print(f"Download page: {update['html_url']}")
        else:
            print("✓ You are running the latest version.")
        return

    engine = BotEngine(config_path=args.config)

    if args.doctor:
        cli = TerminalCLI(engine)
        cli.print_doctor()
        return

    if args.devices:
        devices = engine.list_devices()
        print("Detected Android devices:")
        for d in devices:
            print(f" - {d['serial']} ({d['status']}) [{d['model']}]")
        return

    # Acquire single-instance mutex for active game automation / interface runs
    mutex = SingleInstanceMutex()
    if not mutex.acquire():
        print("[Warning] Another instance of Dokkan-EZALink-Farmer appears to be running.")
        print("Continuing with existing process mutex...")

    try:
        if args.discord:
            print("[Startup] Discord Bot mode selected...")
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            run_discord_bot(engine)
            return

        if args.scrcpy:
            try:
                engine.connect()
                engine.start_scrcpy()
                print("Press CTRL+C to close scrcpy...")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                engine.stop_scrcpy()
            return

        # Direct task execution flags (EZA or Link Level)
        if args.eza is not None:
            engine.connect()
            engine.start_eza_farm(target_level=args.eza)
            cli = TerminalCLI(engine)
            cli.run()
            return

        if args.link is not None:
            engine.connect()
            runs = args.link if args.link > 0 else None
            engine.start_link_level_farm(runs=runs, use_boost=args.boost)
            cli = TerminalCLI(engine)
            cli.run()
            return

        # Default: Interactive Terminal CLI
        cli = TerminalCLI(engine)
        cli.run()
    finally:
        mutex.release()


if __name__ == "__main__":
    main()
