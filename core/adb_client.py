import os
import shutil
import subprocess
import time
from typing import List, Optional, Tuple
import cv2
import numpy as np


from core.system_tools import ToolLocator


class ADBClient:
    """Manages ADB communication, input emulation, and screen capture."""

    @staticmethod
    def resolve_executable(name: str) -> str:
        """Finds executable path using ToolLocator multi-tier engine."""
        if not name:
            return name
        if os.path.isfile(name):
            return os.path.abspath(name)

        lower = os.path.basename(name).lower()
        if "adb" in lower:
            found = ToolLocator.find_adb(name)
            if found:
                return found
        elif "scrcpy" in lower:
            found = ToolLocator.find_scrcpy(name)
            if found:
                return found

        # Fallback to shutil.which
        which = shutil.which(name)
        return which if which else name

    def __init__(self, serial: Optional[str] = None, adb_path: str = "adb"):
        self.adb_path = self.resolve_executable(adb_path)
        self.serial = serial
        self._screen_size: Optional[Tuple[int, int]] = None
        self._scrcpy_proc: Optional[subprocess.Popen] = None

    def _build_cmd(self, args: List[str]) -> List[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd

    def run_cmd(self, args: List[str], timeout: int = 15) -> str:
        """Executes an adb command and returns stdout."""
        cmd = self._build_cmd(args)
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True
            )
            return res.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ADB command failed ({' '.join(cmd)}): {e.stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"ADB command timed out ({' '.join(cmd)}) after {timeout}s")

    def list_devices(self) -> List[dict]:
        """Lists connected devices with their serial, model, and status."""
        out = self.run_cmd(["devices", "-l"])
        devices = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            serial = parts[0]
            status = parts[1]
            model = "Unknown"
            for part in parts[2:]:
                if part.startswith("model:"):
                    model = part.split(":", 1)[1]
            devices.append({"serial": serial, "status": status, "model": model})
        return devices

    COMMON_EMULATOR_PORTS = [
        5555,   # BlueStacks, LDPlayer, default ADB over TCP
        5554,   # Android Studio AVD
        7555,   # MuMu Player 6/X
        16384,  # MuMu Player 12
        62001,  # NoxPlayer
        21503,  # MEmu Play
        5556,   # Multi-instance emulator 2
        5558,   # Multi-instance emulator 3
    ]

    def probe_and_connect_emulators(self) -> List[str]:
        """Probes standard emulator loopback ports on localhost and connects if open."""
        import socket
        connected = []
        for port in self.COMMON_EMULATOR_PORTS:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.04)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        res = self.run_cmd(["connect", f"127.0.0.1:{port}"], timeout=3)
                        if "connected" in res.lower():
                            connected.append(f"127.0.0.1:{port}")
            except Exception:
                pass
        return connected

    def auto_connect(self) -> str:
        """Finds the first available authorized device and connects to it, auto-probing emulators if needed."""
        devices = self.list_devices()
        authorized = [d for d in devices if d["status"] == "device"]
        if not authorized:
            # Probe common local emulator ports (BlueStacks, LDPlayer, MuMu, Nox, AVD)
            self.probe_and_connect_emulators()
            devices = self.list_devices()
            authorized = [d for d in devices if d["status"] == "device"]

        if not authorized:
            if any(d["status"] == "unauthorized" for d in devices):
                raise RuntimeError("Device found but unauthorized. Please check your phone display and allow USB debugging!")
            raise RuntimeError("No Android device or emulator detected. Connect via USB or start your emulator with ADB enabled.")
        
        self.serial = authorized[0]["serial"]
        self.get_screen_size(force_refresh=True)
        return self.serial

    def get_screen_size(self, force_refresh: bool = False) -> Tuple[int, int]:
        """Returns (width, height) of the device screen."""
        if self._screen_size and not force_refresh:
            return self._screen_size
        out = self.run_cmd(["shell", "wm", "size"])
        # Format: "Physical size: 1080x2400"
        for line in out.splitlines():
            if "size:" in line:
                dims = line.split(":")[-1].strip().split("x")
                self._screen_size = (int(dims[0]), int(dims[1]))
                return self._screen_size
        raise RuntimeError(f"Unable to determine screen resolution: {out}")

    def tap(self, x: int, y: int, delay_after: float = 0.5):
        """Sends a tap event to coordinates (x, y)."""
        self.run_cmd(["shell", "input", "tap", str(int(x)), str(int(y))])
        if delay_after > 0:
            time.sleep(delay_after)

    def tap_ratio(self, rx: float, ry: float, delay_after: float = 0.5):
        """Taps screen using relative coordinates (0.0 to 1.0)."""
        w, h = self.get_screen_size()
        self.tap(int(w * rx), int(h * ry), delay_after)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, delay_after: float = 0.5):
        """Simulates a swipe gesture."""
        self.run_cmd(["shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration_ms)])
        if delay_after > 0:
            time.sleep(delay_after)

    def key_back(self):
        """Presses the Android back button (KEYCODE_BACK = 4)."""
        self.run_cmd(["shell", "input", "keyevent", "4"])

    def key_home(self):
        """Presses the Android home button (KEYCODE_HOME = 3)."""
        self.run_cmd(["shell", "input", "keyevent", "3"])

    def screencap(self) -> np.ndarray:
        """Captures device screen directly into an OpenCV BGR image without disk I/O."""
        cmd = self._build_cmd(["exec-out", "screencap", "-p"])
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"Screen capture failed: {proc.stderr.decode('utf-8', errors='ignore')}")
        
        # Decode raw PNG bytes to OpenCV image
        img_array = np.frombuffer(proc.stdout, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Decoding screenshot image buffer failed.")
        return img

    def is_app_running(self, package_name: str) -> bool:
        """Checks if package is running in the foreground."""
        out = self.run_cmd(["shell", "dumpsys", "window", "windows"])
        return package_name in out

    def launch_app(self, package_name: str):
        """Launches the app using monkey or intent."""
        self.run_cmd(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    def start_scrcpy(self, scrcpy_path: str = "scrcpy", extra_args: Optional[List[str]] = None) -> bool:
        """Starts a scrcpy mirror window in background."""
        if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
            return True # Already running

        resolved = self.resolve_executable(scrcpy_path)
        cmd = [resolved]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(["--window-title", f"Dokkan Battle - {self.serial or 'Default'}"])
        if extra_args:
            cmd.extend(extra_args)

        try:
            self._scrcpy_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except FileNotFoundError:
            return False

    def stop_scrcpy(self):
        """Stops running scrcpy process."""
        if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
            self._scrcpy_proc.terminate()
            self._scrcpy_proc = None
