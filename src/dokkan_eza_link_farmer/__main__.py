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
        "--stage",
        "-s",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Specify stage for farming, or target stage for AI Endgame run (e.g. 10101, rz_broly)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run AI Endgame loop or tasks in dry-run mode (simulation without live device taps)",
    )
    parser.add_argument(
        "--force-solve",
        action="store_true",
        default=False,
        help="Ignore cached winning teams and force re-running the teambuilder solver",
    )
    parser.add_argument(
        "--enrich-box",
        action="store_true",
        default=False,
        help="Enrich character box JSON with category IDs, leader skills, and passives from DokkanDB",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Maximum retry attempts for AI Endgame runner (default: 10 from settings.yaml)",
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
        "--challenge",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Directly start autonomous Challenge & Mission solver (Red Zone, SMB)",
    )
    parser.add_argument(
        "--ai",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Open AI Team Builder & Tactical Advisor",
    )
    parser.add_argument(
        "--ai-run",
        dest="ai_run",
        type=str,
        nargs="?",
        const="",
        default=None,
        help="Directly start autonomous AI Endgame Trial & Error run (e.g. --ai-run --stage 10101)",
    )
    parser.add_argument(
        "--scan-box",
        action="store_true",
        help="Directly start autonomous Character Box scanner to build ~/.dokkan-farmer/cache/user_box.json",
    )
    parser.add_argument(
        "subcommand",
        nargs="?",
        default=None,
        help="Optional subcommand: 'enrich-box', 'ai-run', 'scan-box', 'challenge', 'ai', 'team', 'eza', 'link', 'stage', 'doctor', 'devices'",
    )
    parser.add_argument(
        "subcommand_args",
        nargs="*",
        default=[],
        help="Arguments for the subcommand",
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

        cmd = (args.subcommand or "").lower()
        if cmd in ("enrich-box", "enrich_box", "enrich") or args.enrich_box:
            cli = TerminalCLI(engine)
            cli.handle_enrich_box(args.subcommand_args)
            return

        if cmd in ("ai-run", "ai_run", "endgame", "ai-endgame") or args.ai_run is not None:
            stage_target = None
            if args.stage and str(args.stage).strip():
                stage_target = str(args.stage).strip()
            elif args.ai_run and str(args.ai_run).strip():
                stage_target = str(args.ai_run).strip()
            elif args.subcommand_args:
                for idx, a in enumerate(args.subcommand_args):
                    if a in ("--stage", "-s") and idx + 1 < len(args.subcommand_args):
                        stage_target = args.subcommand_args[idx + 1]
                        break
                    elif not a.startswith("-") and stage_target is None:
                        stage_target = a

            # If not specified, stage_target remains None so handle_ai_endgame_run()
            # can open interactive DokkanDB Challenge event selection

            is_dry = bool(args.dry_run or ("--dry-run" in (args.subcommand_args or [])))
            is_force = bool(
                args.force_solve
                or ("--force-solve" in (args.subcommand_args or []))
                or ("--force" in (args.subcommand_args or []))
            )
            if not is_dry:
                try:
                    engine.connect()
                except Exception as e:
                    print(f"[Warning] Device connection: {e}")

            cli = TerminalCLI(engine)
            kwargs = {
                "dry_run": is_dry,
                "max_attempts": args.max_attempts,
            }
            if is_force:
                kwargs["force_solve"] = True
            cli.handle_ai_endgame_run(
                stage_target,
                **kwargs,
            )
            return

        if args.stage is not None and cmd not in ("ai-run", "ai_run", "endgame", "ai-endgame"):
            engine.connect()
            runs = int(args.stage) if str(args.stage).isdigit() and int(args.stage) > 0 else None
            engine.start_stage_farm(runs=runs, use_boost=args.boost)
            cli = TerminalCLI(engine)
            cli.run()
            return

        if cmd in ("challenge", "redzone", "smb") or args.challenge is not None:
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            cli = TerminalCLI(engine)
            sub_args = args.subcommand_args or ([args.challenge] if args.challenge else [])
            cli.handle_challenge_interactive(sub_args)
            if engine.is_task_running():
                cli.run()
            return

        if cmd in ("scan-box", "box-scan", "scan") or args.scan_box:
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            cli = TerminalCLI(engine)
            cli.handle_box_scan_interactive(args.subcommand_args)
            if engine.is_task_running():
                cli.run()
            return

        if cmd in ("ai", "team") or args.ai is not None:
            cli = TerminalCLI(engine)
            sub_args = args.subcommand_args or ([args.ai] if args.ai else [])
            cli.handle_ai_interactive(sub_args)
            return

        if cmd == "eza":
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            cli = TerminalCLI(engine)
            cli.handle_eza_interactive(args.subcommand_args)
            if engine.is_task_running():
                cli.run()
            return

        if cmd == "link":
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            cli = TerminalCLI(engine)
            cli.handle_link_interactive(args.subcommand_args)
            if engine.is_task_running():
                cli.run()
            return

        if cmd in ("stage", "farm", "repeat", "clear", "farm-stage"):
            try:
                engine.connect()
            except Exception as e:
                print(f"[Warning] Device connection: {e}")
            cli = TerminalCLI(engine)
            sub_args = list(args.subcommand_args)
            if args.boost is not None and not any(
                a in sub_args for a in ("--boost", "-b", "--no-boost", "-nb")
            ):
                sub_args.append("--boost" if args.boost else "--no-boost")
            cli.handle_stage_farm_interactive(sub_args)
            if engine.is_task_running():
                cli.run()
            return

        # Default: Interactive Terminal CLI
        cli = TerminalCLI(engine)
        cli.run()
    finally:
        mutex.release()


if __name__ == "__main__":
    main()
