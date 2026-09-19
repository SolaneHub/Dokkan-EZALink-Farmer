"""
Helper script to capture screenshots and crop UI templates from connected Android device.
Usage:
  python tools/template_helper.py --screenshot
  python tools/template_helper.py --crop <x> <y> <width> <height> <template_name>
"""

import sys
import os
import argparse
import cv2

# Add parent dir to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.adb_client import ADBClient
from core.vision import Vision


def main():
    parser = argparse.ArgumentParser(description="Template capture helper for Dokkan Battle")
    parser.add_argument("--screenshot", action="store_true", help="Cattura e salva lo screenshot corrente dal telefono")
    parser.add_argument("--out", type=str, default="screen_sample.png", help="Nome file di output per lo screenshot")
    parser.add_argument("--crop", nargs=5, metavar=("X", "Y", "W", "H", "NAME"), help="Ritaglia una regione e salvala come template")
    parser.add_argument("--device", type=str, default=None, help="Seriale dispositivo specifico")

    args = parser.parse_args()

    adb = ADBClient(serial=args.device)
    try:
        adb.auto_connect()
    except Exception as e:
        print(f"Errore connessione: {e}")
        return

    vision = Vision(template_dir="templates/glb")

    if args.screenshot:
        img = adb.screencap()
        cv2.imwrite(args.out, img)
        h, w = img.shape[:2]
        print(f"Screenshot salvato con successo in '{args.out}' (Risoluzione: {w}x{h})")

    if args.crop:
        x, y, w, h = int(args.crop[0]), int(args.crop[1]), int(args.crop[2]), int(args.crop[3])
        name = args.crop[4]
        img = adb.screencap()
        path = vision.save_template_crop(img, (x, y, w, h), name)
        print(f"Template salvato in: {path}")


if __name__ == "__main__":
    main()
