import os
import subprocess
import time
from typing import List, Optional, Tuple
import cv2
import numpy as np


class ADBClient:
    """Manages ADB communication, input emulation, and screen capture."""

    def __init__(self, serial: Optional[str] = None, adb_path: str = "adb"):
        self.adb_path = adb_path
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

    def auto_connect(self) -> str:
        """Finds the first available authorized device and connects to it."""
        devices = self.list_devices()
        authorized = [d for d in devices if d["status"] == "device"]
        if not authorized:
            if any(d["status"] == "unauthorized" for d in devices):
                raise RuntimeError("Dispositivo trovato ma non autorizzato. Controlla il display del telefono e consenti il debug USB!")
            raise RuntimeError("Nessun dispositivo Android connesso. Collega il telefono via USB con Debug USB attivo.")
        
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
        raise RuntimeError(f"Impossibile determinare la risoluzione dello schermo: {out}")

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
            raise RuntimeError(f"Cattura schermo fallita: {proc.stderr.decode('utf-8', errors='ignore')}")
        
        # Decode raw PNG bytes to OpenCV image
        img_array = np.frombuffer(proc.stdout, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Decodifica immagine dello screenshot fallita.")
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

        cmd = [scrcpy_path]
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
