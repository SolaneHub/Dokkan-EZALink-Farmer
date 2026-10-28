import subprocess
import sys
import time


def kill_existing_processes():
    """Terminates any running instances of Launch-Dokkan-EZALink to avoid WinError 5 lock."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "Launch-Dokkan-EZALink.exe", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
        except Exception:
            pass


def build():
    kill_existing_processes()
    print("Building Launch-Dokkan-EZALink.exe...")
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--console",
        "--name",
        "Launch-Dokkan-EZALink",
        "--add-data",
        f"src/dokkan_eza_link_farmer/assets/templates{sep}templates",
        "--add-data",
        f"src/dokkan_eza_link_farmer/assets/locales{sep}locales",
        "--add-data",
        f"src/dokkan_eza_link_farmer/assets/config{sep}config",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.models",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.boss_models",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.card_models",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.passive_parser",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.card_heuristics",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.dokkandb_parser",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.client",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.synergy",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.llm_advisor",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.solver",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.damage_engine",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.syncer",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.formatters",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.boss_catalog",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.support_catalog",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.endgame",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.team_builder",
        "--hidden-import",
        "dokkan_eza_link_farmer.ai.mission_solver",
        "--hidden-import",
        "dokkan_eza_link_farmer.automation.tasks.challenge_task",
        "--hidden-import",
        "dokkan_eza_link_farmer.automation.tasks.box_scanner",
        "--collect-all",
        "rapidocr_onnxruntime",
        "--paths",
        "src",
        "--clean",
        "main.py",
    ]
    print("Command:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n=============================================")
        print(" BUILD SUCCESSFUL! ")
        print(" Binary location: dist\\Launch-Dokkan-EZALink.exe")
        print("=============================================")
    else:
        print(f"Build failed with exit code: {res.returncode}")
        sys.exit(res.returncode)


if __name__ == "__main__":
    build()
