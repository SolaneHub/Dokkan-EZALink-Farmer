"""
Silent Auto-Updater and Cryptographic Verification Engine.

Provides cryptographically verified release updates, SHA-256 integrity checks,
process environment sanitization (removing PyInstaller _MEIPASS artifacts),
and silent background execution without terminal windows flashing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

REPO_OWNER = "SolaneHub"
REPO_NAME = "Dokkan-EZALink-Farmer"
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


def sanitize_process_env() -> dict[str, str]:
    """
    Sanitizes environment variables for child processes.
    Removes PyInstaller temporary paths (_MEIPASS, LD_LIBRARY_PATH modifications)
    to prevent child processes or updated executables from colliding with current runtime.
    """
    env = os.environ.copy()
    keys_to_clean = ["_MEIPASS", "_MEIPASS2", "PYTHONPATH", "PYTHONHOME"]
    for key in keys_to_clean:
        env.pop(key, None)
    return env


def compute_file_sha256(file_path: str) -> str:
    """Computes hexadecimal SHA-256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest().lower()


def verify_sha256(file_path: str, expected_sha256: str) -> bool:
    """Verifies that the file's SHA-256 matches the expected digest."""
    if not os.path.isfile(file_path):
        return False
    actual = compute_file_sha256(file_path)
    return actual.strip().lower() == expected_sha256.strip().lower()


def check_for_updates(current_version: str) -> dict[str, Any] | None:
    """
    Checks the official GitHub Releases API for a newer tag.
    Returns release information dictionary if an update is available, else None.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_LATEST,
            headers={
                "User-Agent": f"Dokkan-EZALink-Farmer/{current_version}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))

        latest_tag = data.get("tag_name", "").lstrip("v")
        curr = current_version.lstrip("v")

        # Basic SemVer comparison (major, minor, patch)
        def parse_v(v_str: str) -> tuple[int, ...]:
            try:
                return tuple(int(x) for x in v_str.split("."))
            except Exception:
                return (0, 0, 0)

        if parse_v(latest_tag) > parse_v(curr):
            return {
                "tag": data.get("tag_name"),
                "version": latest_tag,
                "html_url": data.get("html_url"),
                "assets": data.get("assets", []),
                "body": data.get("body", ""),
            }
    except Exception as e:
        logger.debug("Failed checking for updates: %s", e)

    return None


def launch_detached_process(command_args: list[str]) -> bool:
    """
    Launches a command as a fully detached background process without flashing terminal windows.
    On Windows: uses DETACHED_PROCESS and CREATE_NO_WINDOW flags.
    On POSIX: uses start_new_session=True.
    """
    env = sanitize_process_env()
    try:
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            subprocess.Popen(
                command_args,
                env=env,
                creationflags=creationflags,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                command_args,
                env=env,
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as e:
        logger.error("Failed to launch detached background process: %s", e)
        return False


def run_powershell_hidden(script_content: str) -> bool:
    """
    Executes a PowerShell script completely silently on Windows with -WindowStyle Hidden.
    """
    if sys.platform != "win32":
        return False

    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as tf:
        tf.write(script_content)
        ps_file = tf.name

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        ps_file,
    ]
    return launch_detached_process(cmd)
