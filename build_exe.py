import subprocess
import sys


def build():
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
