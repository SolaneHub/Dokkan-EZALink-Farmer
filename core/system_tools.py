import os
import sys
import glob
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple


def get_resource_path(relative_path: str) -> str:
    """
    Resolves the absolute path to a project resource (templates, assets).
    Works seamlessly both in development and when bundled into a standalone
    executable via PyInstaller (using sys._MEIPASS).
    """
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.normpath(os.path.join(base_dir, relative_path))


def get_config_path(config_filename: str = "config/settings.yaml") -> str:
    """
    Locates the configuration file. Prioritizes user-editable configurations
    in the current working directory or adjacent to the executable, falling
    back to the bundled default configuration.
    """
    # 1. Check current working directory
    cwd_path = os.path.abspath(config_filename)
    if os.path.isfile(cwd_path):
        return cwd_path

    # 2. Check next to the executable (for standalone distribution)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_config = os.path.join(exe_dir, config_filename)
        if os.path.isfile(exe_config):
            return os.path.abspath(exe_config)

    # 3. Fallback to resource path
    bundled_path = get_resource_path(config_filename)
    if os.path.isfile(bundled_path):
        return bundled_path

    return cwd_path


class ToolLocator:
    """
    Universal multi-tier discovery engine for ADB and scrcpy.
    Operates agnostically on Windows, macOS, and Linux without hardcoded user paths.
    """

    _cached_adb: Optional[str] = None
    _cached_scrcpy: Optional[str] = None

    @classmethod
    def find_scrcpy(cls, configured_path: Optional[str] = None) -> Optional[str]:
        """Discovers scrcpy executable using multi-tier resolution."""
        if cls._cached_scrcpy and os.path.isfile(cls._cached_scrcpy):
            return cls._cached_scrcpy

        path, _ = cls._resolve("scrcpy", configured_path)
        if path:
            cls._cached_scrcpy = path
            # Co-location bonus: check if adb is adjacent to scrcpy
            if not cls._cached_adb:
                adj_adb = cls._check_adjacent(path, "adb")
                if adj_adb:
                    cls._cached_adb = adj_adb
        return path

    @classmethod
    def find_adb(cls, configured_path: Optional[str] = None) -> Optional[str]:
        """Discovers adb executable using multi-tier resolution."""
        if cls._cached_adb and os.path.isfile(cls._cached_adb):
            return cls._cached_adb

        path, _ = cls._resolve("adb", configured_path)
        if path:
            cls._cached_adb = path
            # Co-location bonus: check if scrcpy is adjacent to adb
            if not cls._cached_scrcpy:
                adj_scrcpy = cls._check_adjacent(path, "scrcpy")
                if adj_scrcpy:
                    cls._cached_scrcpy = adj_scrcpy
        return path

    @classmethod
    def _check_adjacent(cls, base_file: str, target_name: str) -> Optional[str]:
        folder = os.path.dirname(base_file)
        exe_name = f"{target_name}.exe" if sys.platform == "win32" else target_name
        candidate = os.path.join(folder, exe_name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK if sys.platform != "win32" else os.F_OK):
            return os.path.abspath(candidate)
        return None

    @classmethod
    def _resolve(cls, tool_name: str, configured_path: Optional[str]) -> Tuple[Optional[str], str]:
        """
        Executes the hierarchical discovery sequence:
        Tier 1: Explicit config
        Tier 2: Environment variables
        Tier 3: System PATH & Registry (Windows)
        Tier 4: OS-specific package managers and canonical directories
        Tier 5: Dynamic wildcard scan in personal folders (Downloads/Desktop)
        """
        exe_name = f"{tool_name}.exe" if sys.platform == "win32" else tool_name

        # Tier 1: Configured path in settings.yaml
        if configured_path:
            clean_cfg = configured_path.strip()
            if clean_cfg and clean_cfg != tool_name and clean_cfg != exe_name:
                if os.path.isfile(clean_cfg):
                    return (os.path.abspath(clean_cfg), "Tier 1 (Explicit config)")
                # If configured path is a directory
                if os.path.isdir(clean_cfg):
                    joined = os.path.join(clean_cfg, exe_name)
                    if os.path.isfile(joined):
                        return (os.path.abspath(joined), "Tier 1 (Explicit config dir)")

        # Tier 2: Dedicated Environment Variables
        env_vars = {
            "scrcpy": ["SCRCPY_PATH", "SCRCPY_DIR", "SCRCPY_HOME", "SCRCPY_BIN"],
            "adb": ["ADB_PATH", "ANDROID_HOME", "ANDROID_SDK_ROOT"]
        }.get(tool_name, [])

        for var in env_vars:
            val = os.environ.get(var)
            if val:
                val = val.strip().strip('"')
                if os.path.isfile(val):
                    return (os.path.abspath(val), f"Tier 2 (Environment variable {var})")
                if os.path.isdir(val):
                    joined = os.path.join(val, exe_name)
                    if os.path.isfile(joined):
                        return (os.path.abspath(joined), f"Tier 2 (Environment variable {var})")
                    # For ANDROID_HOME/platform-tools
                    sub_joined = os.path.join(val, "platform-tools", exe_name)
                    if os.path.isfile(sub_joined):
                        return (os.path.abspath(sub_joined), f"Tier 2 (Environment variable {var}/platform-tools)")

        # Tier 3: System PATH via shutil.which
        which_path = shutil.which(tool_name) or shutil.which(exe_name)
        if which_path:
            return (os.path.abspath(which_path), "Tier 3 (System PATH)")

        # Tier 3b: Windows Registry PATH inspection (picks up fresh PATH changes without shell restart)
        if sys.platform == "win32":
            reg_path = cls._scan_windows_registry_path(exe_name)
            if reg_path:
                return (reg_path, "Tier 3b (Windows Registry PATH)")

        # Tier 4: OS-Specific Canonical Paths & Package Managers
        if sys.platform == "darwin":
            mac_paths = [
                f"/opt/homebrew/bin/{tool_name}",  # Apple Silicon Homebrew
                f"/usr/local/bin/{tool_name}",    # Intel Mac Homebrew
                os.path.expanduser(f"~/Library/Android/sdk/platform-tools/{tool_name}"),  # Android Studio macOS
                f"/opt/local/bin/{tool_name}",     # MacPorts
                f"/Applications/scrcpy.app/Contents/MacOS/{tool_name}",
                os.path.expanduser(f"~/Applications/{tool_name}"),
            ]
            for p in mac_paths:
                if os.path.isfile(p):
                    return (os.path.abspath(p), "Tier 4 (macOS canonical/Homebrew)")

        elif sys.platform == "win32":
            user_home = os.path.expanduser("~")
            local_appdata = os.environ.get("LOCALAPPDATA", os.path.join(user_home, "AppData", "Local"))
            program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")

            win_candidates = [
                # WinGet
                os.path.join(local_appdata, "Microsoft", "WinGet", "Links", exe_name),
                # Scoop
                os.path.join(user_home, "scoop", "shims", exe_name),
                os.path.join(user_home, "scoop", "apps", "scrcpy", "current", exe_name),
                os.path.join(program_data, "scoop", "shims", exe_name),
                # Chocolatey
                os.path.join(program_data, "chocolatey", "bin", exe_name),
                os.path.join(r"C:\tools", "scrcpy", exe_name),
                # Android SDK Windows
                os.path.join(local_appdata, "Android", "Sdk", "platform-tools", exe_name),
                # Canonical Windows directories
                rf"C:\platform-tools\{exe_name}",
                rf"C:\scrcpy\{exe_name}",
                rf"C:\Program Files\scrcpy\{exe_name}",
                rf"C:\Program Files (x86)\scrcpy\{exe_name}",
            ]
            for c in win_candidates:
                if os.path.isfile(c):
                    return (os.path.abspath(c), "Tier 4 (Windows canonical/Package Manager)")

        else:
            # Linux
            linux_paths = [
                f"/usr/bin/{tool_name}",
                f"/usr/local/bin/{tool_name}",
                f"/snap/bin/{tool_name}",
                os.path.expanduser(f"~/.local/bin/{tool_name}"),
            ]
            for p in linux_paths:
                if os.path.isfile(p):
                    return (os.path.abspath(p), "Tier 4 (Linux canonical)")

        # Tier 5: Dynamic Wildcard Globbing in user extraction folders
        glob_res = cls._scan_dynamic_globs(tool_name, exe_name)
        if glob_res:
            return (glob_res, "Tier 5 (Personal folders dynamic scan)")

        return (None, "Not found")

    @classmethod
    def _scan_windows_registry_path(cls, exe_name: str) -> Optional[str]:
        """Reads User and Machine PATH directly from Windows Registry."""
        try:
            import winreg
            for root_key, sub_key in [
                (winreg.HKEY_CURRENT_USER, r"Environment"),
                (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            ]:
                try:
                    with winreg.OpenKey(root_key, sub_key) as key:
                        raw_path, _ = winreg.QueryValueEx(key, "Path")
                        for folder in raw_path.split(";"):
                            folder = folder.strip().strip('"')
                            if not folder:
                                continue
                            candidate = os.path.join(folder, exe_name)
                            if os.path.isfile(candidate):
                                return os.path.abspath(candidate)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    @classmethod
    def _scan_dynamic_globs(cls, tool_name: str, exe_name: str) -> Optional[str]:
        """
        Dynamically searches user folders for extracted scrcpy or platform-tools releases
        (e.g., Downloads/scrcpy-win64-v4.0, Desktop/scrcpy, etc.).
        Picks the most recently modified matching binary.
        """
        user_home = os.path.expanduser("~")
        search_roots = [
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Desktop"),
            os.path.join(user_home, "Documents"),
        ]

        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                search_roots.append(os.path.join(local_appdata, "Programs"))
                search_roots.append(os.path.join(local_appdata, "Microsoft", "WinGet", "Packages"))
            search_roots.append(r"C:\Program Files")
            search_roots.append(r"C:\Program Files (x86)")
            search_roots.append("C:\\")

        patterns = []
        if tool_name == "scrcpy":
            for root in search_roots:
                if not os.path.isdir(root):
                    continue
                patterns.append(os.path.join(root, "scrcpy*", exe_name))
                patterns.append(os.path.join(root, "scrcpy*", "**", exe_name))
        elif tool_name == "adb":
            for root in search_roots:
                if not os.path.isdir(root):
                    continue
                patterns.append(os.path.join(root, "platform-tools*", exe_name))
                patterns.append(os.path.join(root, "scrcpy*", exe_name))
                patterns.append(os.path.join(root, "scrcpy*", "**", exe_name))

        matches: List[str] = []
        for pat in patterns:
            try:
                for hit in glob.glob(pat, recursive=True):
                    if os.path.isfile(hit) and not hit.endswith(".lnk"):
                        matches.append(hit)
            except Exception:
                continue

        if not matches:
            return None

        # Sort matches by modification time descending to select latest version
        matches.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        return os.path.abspath(matches[0])

    @classmethod
    def get_tool_version(cls, tool_path: str) -> Optional[str]:
        """Extracts version string from tool executable."""
        if not tool_path or not os.path.isfile(tool_path):
            return None
        try:
            res = subprocess.run(
                [tool_path, "--version"],
                capture_output=True,
                text=True,
                timeout=4
            )
            out = res.stdout.strip() or res.stderr.strip()
            first_line = out.splitlines()[0] if out else "Unknown"
            return first_line
        except Exception:
            try:
                res = subprocess.run(
                    [tool_path, "version"],
                    capture_output=True,
                    text=True,
                    timeout=4
                )
                out = res.stdout.strip()
                return out.splitlines()[0] if out else "Available"
            except Exception:
                return "Available"

    @classmethod
    def diagnose_system(cls, configured_adb: Optional[str] = None, configured_scrcpy: Optional[str] = None) -> Dict[str, Any]:
        """Produces a comprehensive system diagnostics report for the doctor command."""
        scrcpy_path = cls.find_scrcpy(configured_scrcpy)
        adb_path = cls.find_adb(configured_adb)

        scrcpy_ver = cls.get_tool_version(scrcpy_path) if scrcpy_path else None
        adb_ver = cls.get_tool_version(adb_path) if adb_path else None

        os_name = {
            "darwin": "macOS",
            "win32": "Windows",
            "linux": "Linux"
        }.get(sys.platform, sys.platform)

        # Installation guidance per platform
        install_help = {
            "macOS": {
                "scrcpy": "brew install scrcpy",
                "adb": "brew install android-platform-tools",
                "all": "brew install scrcpy android-platform-tools",
                "note": "On Mac, make sure 'Android File Transfer' is closed if ADB does not detect the phone."
            },
            "Windows": {
                "scrcpy": "winget install Genymobile.scrcpy",
                "adb": "Included automatically in scrcpy package or: winget install Google.PlatformTools",
                "all": "winget install Genymobile.scrcpy",
                "note": "Alternatively, download and extract the ZIP from: https://github.com/Genymobile/scrcpy/releases"
            },
            "Linux": {
                "scrcpy": "sudo apt install scrcpy",
                "adb": "sudo apt install adb",
                "all": "sudo apt install scrcpy adb",
                "note": "Ensure your user belongs to the 'plugdev' group."
            }
        }.get(os_name, {})

        return {
            "os": os_name,
            "platform": sys.platform,
            "python_version": sys.version.split()[0],
            "is_frozen": getattr(sys, "frozen", False),
            "scrcpy": {
                "found": scrcpy_path is not None,
                "path": scrcpy_path,
                "version": scrcpy_ver,
            },
            "adb": {
                "found": adb_path is not None,
                "path": adb_path,
                "version": adb_ver,
            },
            "install_help": install_help,
        }
