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
    parser.add_argument("--screenshot", action="store_true", help="Capture and save current phone screenshot to file")
    parser.add_argument("--out", type=str, default="screen_sample.png", help="Output filename for captured screenshot")
    parser.add_argument("--crop", nargs=5, metavar=("X", "Y", "W", "H", "NAME"), help="Crop a bounding box region and save as template")
    parser.add_argument("--category", type=str, default=None, choices=["buttons", "eza", "popups", "system", "tabs"], help="Target category subfolder for cropped template")
    parser.add_argument("--list", action="store_true", help="List all categorized templates currently available")
    parser.add_argument("--device", type=str, default=None, help="Target specific Android device serial")

    args = parser.parse_args()

    vision = Vision(template_dir="templates/glb")

    if args.list:
        cats = vision.list_templates_by_category()
        print("=== Dokkan-EZALink-Farmer UI Templates ===")
        for cat, files in sorted(cats.items()):
            print(f"[{cat}] ({len(files)} templates):")
            for f in files:
                print(f"  - {f}")
        return

    adb = ADBClient(serial=args.device)
    try:
        adb.auto_connect()
    except Exception as e:
        print(f"Connection error: {e}")
        return

    if args.screenshot:
        img = adb.screencap()
        cv2.imwrite(args.out, img)
        h, w = img.shape[:2]
        print(f"Screenshot successfully saved to '{args.out}' (Resolution: {w}x{h})")

    if args.crop:
        x, y, w, h = int(args.crop[0]), int(args.crop[1]), int(args.crop[2]), int(args.crop[3])
        name = args.crop[4]
        img = adb.screencap()
        path = vision.save_template_crop(img, (x, y, w, h), name, category=args.category)
        print(f"Template saved to: {path}")


if __name__ == "__main__":
    main()
