"""
Build script to compile DokkanBattleBot into a standalone terminal-only distribution in dist/.
Works on Windows (producing dist/dokkan-bot/dokkan-bot.exe) and macOS/Linux (producing dist/dokkan-bot/dokkan-bot).

Usage:
  python build_dist.py
  python build_dist.py --onefile
"""

import os
import sys
import shutil
import argparse
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def build(onefile: bool = False):
    print("=" * 60)
    print("🔨 DOKKAN BATTLE BOT - STANDALONE TERMINAL BUILDER")
    print("=" * 60)
    os_label = 'Windows' if sys.platform == 'win32' else 'macOS' if sys.platform == 'darwin' else 'Linux'
    mode_label = 'Single File (--onefile)' if onefile else 'Distribution Folder (--onedir)'
    print(f"Target platform: {sys.platform} ({os_label})")
    print(f"Build mode:      {mode_label}")

    # 1. Verify PyInstaller installation
    try:
        import PyInstaller
        print(f"✓ PyInstaller found: v{PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller not found. Installing now...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Paths configuration
    root_dir = os.path.abspath(os.path.dirname(__file__))
    main_py = os.path.join(root_dir, "main.py")
    templates_dir = os.path.join(root_dir, "templates")
    locales_dir = os.path.join(root_dir, "locales")
    config_dir = os.path.join(root_dir, "config")
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")

    # Separator for PyInstaller --add-data: ';' on Windows, ':' on Unix/macOS
    sep = ";" if sys.platform == "win32" else ":"
    add_templates = f"{templates_dir}{sep}templates"
    add_locales = f"{locales_dir}{sep}locales"
    add_config = f"{config_dir}{sep}config"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", "dokkan-bot",
        "--console",  # Strictly console/terminal (no GUI window wrapper)
        "--clean",
        "--noconfirm",
        "--add-data", add_templates,
        "--add-data", add_locales,
        "--add-data", add_config,
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "yaml",
        "--hidden-import", "rich",
        "--hidden-import", "rich.table",
        "--hidden-import", "rich.panel",
        "--hidden-import", "rich.text",
        "--hidden-import", "rich.prompt",
        "--hidden-import", "discord",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.append(main_py)

    print("\nExecuting PyInstaller command...")
    print(" ".join(cmd))
    res = subprocess.run(cmd, cwd=root_dir)
    if res.returncode != 0:
        print(f"\n❌ Build error (Exit code: {res.returncode})")
        sys.exit(res.returncode)

    # 3. Post-build distribution directory setup
    print("\n📦 Setting up distribution package in dist/...")
    target_output_dir = dist_dir if onefile else os.path.join(dist_dir, "dokkan-bot")
    target_config_dir = os.path.join(target_output_dir, "config")
    target_locales_dir = os.path.join(target_output_dir, "locales")
    os.makedirs(target_config_dir, exist_ok=True)
    os.makedirs(target_locales_dir, exist_ok=True)

    # Copy user-editable settings.yaml next to binary
    src_settings = os.path.join(config_dir, "settings.yaml")
    dst_settings = os.path.join(target_config_dir, "settings.yaml")
    if os.path.isfile(src_settings) and not os.path.isfile(dst_settings):
        shutil.copy2(src_settings, dst_settings)
        print(f"✓ User-editable config copied to: {dst_settings}")

    # Copy locales catalogs
    if os.path.isdir(locales_dir):
        for f in os.listdir(locales_dir):
            if f.endswith(".yaml") or f.endswith(".yml"):
                shutil.copy2(os.path.join(locales_dir, f), os.path.join(target_locales_dir, f))
        print(f"✓ Translation catalogs copied to: {target_locales_dir}")

    # Copy documentation files and assets
    for doc_file in ["COMMANDS.md", "COMMANDS.it.md", "README.md"]:
        src_doc = os.path.join(root_dir, doc_file)
        dst_doc = os.path.join(target_output_dir, doc_file)
        if os.path.isfile(src_doc):
            shutil.copy2(src_doc, dst_doc)
            print(f"✓ Copied {doc_file} to: {dst_doc}")

    src_assets = os.path.join(root_dir, "assets")
    dst_assets = os.path.join(target_output_dir, "assets")
    if os.path.isdir(src_assets):
        shutil.copytree(src_assets, dst_assets, dirs_exist_ok=True)
        print(f"✓ Copied assets to: {dst_assets}")

    exe_name = "dokkan-bot.exe" if sys.platform == "win32" else "dokkan-bot"
    exe_path = os.path.join(target_output_dir, exe_name)

    print("\n" + "=" * 60)
    print("🎉 BUILD COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"Distribution directory: {target_output_dir}")
    print(f"Terminal binary:        {exe_path}")
    print("\nYou can test it now from your terminal:")
    if sys.platform == "win32":
        print(f"  .\\dist\\dokkan-bot\\{exe_name} --doctor")
        print(f"  .\\dist\\dokkan-bot\\{exe_name} --lang it --doctor")
    else:
        print(f"  ./dist/dokkan-bot/{exe_name} --doctor")
        print(f"  ./dist/dokkan-bot/{exe_name} --lang it --doctor")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone terminal builder for DokkanBattleBot")
    parser.add_argument("--onefile", action="store_true", help="Compile into a single executable file instead of a directory")
    args = parser.parse_args()
    build(onefile=args.onefile)
