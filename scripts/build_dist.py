"""
Build script to compile Dokkan-EZALink-Farmer into a standalone distribution in dist/.
Produces standalone, zero-dependency distribution with Launch-Dokkan-EZALink executable and launchers:
- Windows: dist/Launch-Dokkan-EZALink/ (Launch-Dokkan-EZALink.exe & Launch-Dokkan-EZALink.bat)
- macOS: dist/Launch-Dokkan-EZALink/ (Launch-Dokkan-EZALink & Launch-Dokkan-EZALink.command)
- Linux: dist/Launch-Dokkan-EZALink/ (Launch-Dokkan-EZALink & Launch-Dokkan-EZALink.sh)

Usage:
  python scripts/build_dist.py
  python scripts/build_dist.py --onefile
"""

import argparse
import os
import shutil
import subprocess
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def copy_docs(root_dir: str, target_dir: str):
    """Copies documentation to the target distribution folder."""
    for doc_file in ["COMMANDS.md", "COMMANDS.it.md", "DISCORD_SETUP.md", "DISCORD_SETUP.it.md", "README.md"]:
        candidates = [
            os.path.join(root_dir, doc_file),
            os.path.join(root_dir, "docs", doc_file),
        ]
        dst_doc = os.path.join(target_dir, doc_file)
        for src_doc in candidates:
            if os.path.isfile(src_doc):
                shutil.copy2(src_doc, dst_doc)
                print(f"✓ Copied {doc_file} to: {dst_doc}")
                break


def build(onefile: bool = False):
    print("=" * 60)
    print("🔨 DOKKAN BATTLE BOT - STANDALONE TERMINAL BUILDER")
    print("=" * 60)
    os_label = "Windows" if sys.platform == "win32" else "macOS" if sys.platform == "darwin" else "Linux"
    mode_label = "Single File (--onefile)" if onefile else "Distribution Folder (--onedir)"
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
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    main_py = os.path.join(root_dir, "main.py")
    templates_dir = os.path.join(root_dir, "templates")
    locales_dir = os.path.join(root_dir, "locales")
    config_dir = os.path.join(root_dir, "config")
    dist_dir = os.path.join(root_dir, "dist")

    sep = ";" if sys.platform == "win32" else ":"
    add_templates = f"{templates_dir}{sep}templates"
    add_locales = f"{locales_dir}{sep}locales"
    add_config = f"{config_dir}{sep}config"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "Launch-Dokkan-EZALink",
        "--console",
        "--clean",
        "--noconfirm",
        "--add-data",
        add_templates,
        "--add-data",
        add_locales,
        "--add-data",
        add_config,
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "numpy",
        "--hidden-import",
        "yaml",
        "--hidden-import",
        "rich",
        "--hidden-import",
        "rich.table",
        "--hidden-import",
        "rich.panel",
        "--hidden-import",
        "rich.text",
        "--hidden-import",
        "rich.prompt",
        "--hidden-import",
        "discord",
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
    target_output_dir = dist_dir if onefile else os.path.join(dist_dir, "Launch-Dokkan-EZALink")

    copy_docs(root_dir, target_output_dir)

    # Generate 1-click desktop launcher for the target OS
    if sys.platform == "win32":
        launcher_bat = os.path.join(target_output_dir, "Launch-Dokkan-EZALink.bat")
        with open(launcher_bat, "w", encoding="utf-8") as f:
            f.write('@echo off\r\ncd /d "%~dp0"\r\nLaunch-Dokkan-EZALink.exe %*\r\npause\r\n')
        print("✓ Created 1-click launcher: Launch-Dokkan-EZALink.bat (Windows)")
    elif sys.platform == "darwin":
        launcher_mac = os.path.join(target_output_dir, "Launch-Dokkan-EZALink.command")
        with open(launcher_mac, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                '#!/bin/bash\n'
                'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
                'cd "$DIR"\n'
                'xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true\n'
                'if [ -f "./Launch-Dokkan-EZALink" ]; then\n'
                '    ./Launch-Dokkan-EZALink "$@"\n'
                'elif [ -f "./dokkan-eza-link" ]; then\n'
                '    ./dokkan-eza-link "$@"\n'
                'fi\n'
            )
        try:
            os.chmod(launcher_mac, 0o755)
        except Exception:
            pass
        print("✓ Created 1-click launcher: Launch-Dokkan-EZALink.command (macOS)")
    else:
        launcher_linux = os.path.join(target_output_dir, "Launch-Dokkan-EZALink.sh")
        with open(launcher_linux, "w", encoding="utf-8", newline="\n") as f:
            f.write('#!/bin/bash\nDIR="$(cd "$(dirname "$0")" && pwd)"\ncd "$DIR"\n./Launch-Dokkan-EZALink\n')
        try:
            os.chmod(launcher_linux, 0o755)
        except Exception:
            pass
        print("✓ Created 1-click launcher: Launch-Dokkan-EZALink.sh (Linux)")

    bin_name = "Launch-Dokkan-EZALink.exe" if sys.platform == "win32" else "Launch-Dokkan-EZALink"
    bin_path = os.path.join(target_output_dir, bin_name)

    print("\n" + "=" * 60)
    print("🎉 BUILD COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"Distribution directory: {target_output_dir}")
    print(f"Terminal binary:        {bin_path}")
    print("\nYou can test it now from your terminal:")
    if sys.platform == "win32":
        print(f"  .\\dist\\Launch-Dokkan-EZALink\\{bin_name} --doctor")
        print(f"  .\\dist\\Launch-Dokkan-EZALink\\{bin_name} --lang it --doctor")
    else:
        print(f"  ./dist/Launch-Dokkan-EZALink/{bin_name} --doctor")
        print(f"  ./dist/Launch-Dokkan-EZALink/{bin_name} --lang it --doctor")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone terminal builder for Dokkan-EZALink-Farmer")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Compile into a single executable file instead of a directory",
    )
    args = parser.parse_args()
    build(onefile=args.onefile)
