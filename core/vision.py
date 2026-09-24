import os
from typing import Any

import cv2
import numpy as np

from core.system_tools import get_resource_path


class Vision:
    """Handles Computer Vision, template matching, and UI element detection for Dokkan."""

    def __init__(self, template_dir: str = "templates/glb", default_threshold: float = 0.78):
        self.template_dir = template_dir if os.path.isabs(template_dir) else get_resource_path(template_dir)
        self.default_threshold = default_threshold
        self._template_cache: dict[str, np.ndarray | None] = {}
        self._template_map: dict[str, str] = {}
        os.makedirs(self.template_dir, exist_ok=True)
        self.refresh_template_index()

    def refresh_template_index(self):
        """Scans the template directory recursively and maps template names to file paths."""
        self._template_map.clear()
        if not os.path.exists(self.template_dir):
            return

        for root, _, files in os.walk(self.template_dir):
            for file in files:
                if file.lower().endswith((".png", ".jpg", ".jpeg")):
                    full_path = os.path.abspath(os.path.join(root, file))
                    rel_path = os.path.relpath(full_path, self.template_dir).replace("\\", "/")
                    name_without_ext = os.path.splitext(file)[0]
                    rel_without_ext = os.path.splitext(rel_path)[0]

                    # Map multiple lookup keys for seamless compatibility:
                    # 1. Base filename with ext: "button_ok.png"
                    # 2. Base filename without ext: "button_ok"
                    # 3. Relative path with ext: "buttons/button_ok.png"
                    # 4. Relative path without ext: "buttons/button_ok"
                    self._template_map[file] = full_path
                    self._template_map[name_without_ext] = full_path
                    self._template_map[rel_path] = full_path
                    self._template_map[rel_without_ext] = full_path

    def list_templates_by_category(self) -> dict[str, list[str]]:
        """Returns a dict of subfolder categories and their template filenames."""
        categories: dict[str, list[str]] = {}
        for root, _, files in os.walk(self.template_dir):
            cat = os.path.relpath(root, self.template_dir).replace("\\", "/")
            if cat == ".":
                cat = "root"
            img_files = [f for f in sorted(files) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
            if img_files:
                categories[cat] = img_files
        return categories

    def load_template(self, template_name: str) -> np.ndarray | None:
        """Loads and caches a template image from disk, supporting nested category subfolders."""
        # Check cache first
        if template_name in self._template_cache:
            return self._template_cache[template_name]

        norm_key = template_name.replace("\\", "/")
        if norm_key in self._template_cache:
            return self._template_cache[norm_key]

        # Look up in indexed mapping
        path = self._template_map.get(norm_key)
        if not path and not norm_key.endswith((".png", ".jpg", ".jpeg")):
            path = self._template_map.get(norm_key + ".png")

        # Fallback to direct path in template_dir
        if not path:
            candidate = os.path.join(self.template_dir, norm_key)
            if not candidate.endswith((".png", ".jpg", ".jpeg")):
                candidate += ".png"
            if os.path.exists(candidate):
                path = candidate

        if not path or not os.path.exists(path):
            self._template_cache[template_name] = None
            self._template_cache[norm_key] = None
            return None

        # Check if already cached by resolved path
        if path in self._template_cache:
            img = self._template_cache[path]
            self._template_cache[template_name] = img
            return img

        img = cv2.imread(path, cv2.IMREAD_COLOR)
        self._template_cache[path] = img
        self._template_cache[template_name] = img
        self._template_cache[norm_key] = img
        return img

    def find_template(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: float | None = None,
        scales: list[float] | None = None,
    ) -> tuple[int, int, float] | None:
        """
        Locates a template on the screen using multi-scale template matching.
        Returns: (center_x, center_y, max_val) or None
        """
        if scales is None:
            scales = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]
        template = self.load_template(template_name)
        if template is None:
            return None

        thresh = threshold if threshold is not None else self.default_threshold
        t_h, t_w = template.shape[:2]
        s_h, s_w = screen.shape[:2]

        # 1. Check 1.0 scale first for instant matching on native resolution
        if t_w <= s_w and t_h <= s_h:
            res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= thresh:
                center_x = max_loc[0] + t_w // 2
                center_y = max_loc[1] + t_h // 2
                return (int(center_x), int(center_y), float(max_val))
            best_val = max_val
            best_loc = max_loc
        else:
            best_val = -1.0
            best_loc = None

        best_w, best_h = t_w, t_h

        # 2. Multi-scale fallback only if native scale showed plausible candidate (>= 0.65)
        if best_val >= 0.65:
            for scale in scales:
                if scale == 1.0:
                    continue
                scaled_w = int(t_w * scale)
                scaled_h = int(t_h * scale)

                if scaled_w > s_w or scaled_h > s_h or scaled_w < 10 or scaled_h < 10:
                    continue

                scaled_template = cv2.resize(template, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(screen, scaled_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val > best_val:
                    best_val = max_val
                    best_loc = max_loc
                    best_w, best_h = scaled_w, scaled_h
                    if best_val >= thresh:
                        break

        if best_val >= thresh and best_loc is not None:
            center_x = best_loc[0] + best_w // 2
            center_y = best_loc[1] + best_h // 2
            return (int(center_x), int(center_y), float(best_val))

        return None

    def find_all_templates(
        self, screen: np.ndarray, template_name: str, threshold: float = 0.78, min_distance: int = 80
    ) -> list[tuple[int, int, float]]:
        """
        Finds all occurrences of a template on screen, filtered by non-maximum suppression.
        Returns: list of (center_x, center_y, confidence)
        """
        template = self.load_template(template_name)
        if template is None:
            return []

        s_h, s_w = screen.shape[:2]
        t_h, t_w = template.shape[:2]
        if t_w > s_w or t_h > s_h:
            return []

        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        candidates = []
        for pt in zip(*loc[::-1], strict=False):
            candidates.append((pt[0] + t_w // 2, pt[1] + t_h // 2, float(res[pt[1], pt[0]])))

        if not candidates:
            return []

        # Sort candidates descending by confidence
        candidates.sort(key=lambda c: c[2], reverse=True)

        filtered: list[tuple[int, int, float]] = []
        for c in candidates:
            if not any(abs(c[0] - f[0]) < min_distance and abs(c[1] - f[1]) < min_distance for f in filtered):
                filtered.append(c)

        return filtered

    def find_ok_button(self, screen: np.ndarray, threshold: float = 0.80) -> tuple[int, int, float] | None:
        """
        Finds OK button. If a modal dialog OK button is present (between 40% and 75% Y),
        returns that modal OK button with priority to dismiss the dialog.
        Otherwise returns the bottom results OK button (80-95% Y).
        """
        template = self.load_template("button_ok")
        if template is None:
            return None

        s_h, s_w = screen.shape[:2]
        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        candidates = []
        for pt in zip(*loc[::-1], strict=False):
            candidates.append((pt[0], pt[1], float(res[pt[1], pt[0]])))

        if not candidates:
            return None

        # Sort candidates descending by confidence so true peaks are chosen first (proper NMS)
        candidates.sort(key=lambda c: c[2], reverse=True)

        matches = []
        for pt_x, pt_y, conf in candidates:
            cx = pt_x + template.shape[1] // 2
            cy = pt_y + template.shape[0] // 2
            if not any(abs(cx - m[0]) < 30 and abs(cy - m[1]) < 30 for m in matches):
                matches.append((int(cx), int(cy), conf))

        if not matches:
            return None

        # Separate into modal popup OK (40% to 75% Y) and bottom OK (> 75% Y)
        modal_matches = [m for m in matches if 0.40 <= (m[1] / s_h) <= 0.75]
        if modal_matches:
            modal_matches.sort(key=lambda x: x[2], reverse=True)
            best = modal_matches[0]
            return (int(best[0]), int(best[1]), float(best[2]))

        bottom_matches = [m for m in matches if (m[1] / s_h) > 0.75]
        if bottom_matches:
            bottom_matches.sort(key=lambda x: x[2], reverse=True)
            best = bottom_matches[0]
            return (int(best[0]), int(best[1]), float(best[2]))

        matches.sort(key=lambda x: x[2], reverse=True)
        best = matches[0]
        return (int(best[0]), int(best[1]), float(best[2]))

    def find_attempt_again_button(self, screen: np.ndarray) -> tuple[int, int] | None:
        """
        Detects the 'Attempt Again' button on the stage results / clear screen.
        Checks:
        1. Template 'button_attempt_again' if present.
        2. Geometry of bottom OK button: when 'Attempt Again' is present, Dokkan places
           the 'OK' button on the left (cx / w < 0.42, typically ~0.28).
           The 'Attempt Again' button is positioned on the right (~0.72 * w, at the same Y height).
        Returns (x, y) coordinates of the 'Attempt Again' button, or None if single centered OK.
        """
        # 1. Template match
        m = self.find_template(screen, "button_attempt_again", threshold=0.75)
        if m:
            return (m[0], m[1])

        # 2. Bottom OK geometry
        s_h, s_w = screen.shape[:2]
        ok_match = self.find_ok_button(screen)
        if ok_match:
            ok_x, ok_y = ok_match[0], ok_match[1]
            if (ok_y / s_h) > 0.75 and (ok_x / s_w) < 0.42:
                attempt_x = int(s_w * 0.72)
                attempt_y = ok_y
                return (attempt_x, attempt_y)

        return None

    def find_any_template(
        self, screen: np.ndarray, template_names: list[str], threshold: float | None = None
    ) -> tuple[str, int, int, float] | None:
        """Tests multiple templates and returns the first match found with (name, x, y, conf)."""
        for name in template_names:
            match = self.find_template(screen, name, threshold)
            if match:
                return (name, match[0], match[1], match[2])
        return None

    def save_template_crop(
        self, screen: np.ndarray, box: tuple[int, int, int, int], name: str, category: str | None = None
    ) -> str:
        """
        Saves a cropped region as a template file for future matching.
        box: (x, y, width, height)
        """
        x, y, w, h = box
        crop = screen[y : y + h, x : x + w]
        if not name.endswith(".png"):
            name += ".png"

        if category:
            target_dir = os.path.join(self.template_dir, category)
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, name)
        else:
            path = os.path.join(self.template_dir, name)

        cv2.imwrite(path, crop)
        # Refresh index and clear cache for this template
        self.refresh_template_index()
        self._template_cache.pop(name, None)
        self._template_cache.pop(os.path.splitext(name)[0], None)
        self._template_cache.pop(path, None)
        return path

    @staticmethod
    def get_dominant_color_in_rect(screen: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int]:
        """Returns average BGR color in a given rectangular area."""
        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return (0, 0, 0)
        mean_bgr = cv2.mean(roi)[:3]
        return (int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2]))

    def is_slot_link_max(self, screen: np.ndarray, slot_idx: int) -> bool:
        """
        Inspects character slot (0 to 5) on the Team Preview screen to determine
        if all links are MAX (Lv. 10). Checks for golden MAX badge or template match.
        Supports both modern UI and legacy layouts.
        """
        h, w = screen.shape[:2]
        # Relative horizontal centers for slots 0 to 5 (Leader = 0, Sub units = 1..5)
        # Modern UI: [0.123, 0.256, 0.393, 0.530, 0.667, 0.804]
        # Legacy UI: [0.15, 0.29, 0.43, 0.57, 0.71, 0.85]
        slot_centers_modern = [0.123, 0.256, 0.393, 0.530, 0.667, 0.804]
        slot_centers_legacy = [0.15, 0.29, 0.43, 0.57, 0.71, 0.85]

        if slot_idx < 0 or slot_idx >= len(slot_centers_modern):
            return False

        # Try both modern vertical center (~0.43) and legacy (~0.48)
        candidate_coords = [(slot_centers_modern[slot_idx], 0.429), (slot_centers_legacy[slot_idx], 0.480)]

        for rx, ry in candidate_coords:
            cx = int(w * rx)
            cy = int(h * ry)

            # Region around the character's link skill badge (lower portion of character circle)
            badge_h = int(h * 0.05)
            badge_w = int(w * 0.10)
            y1 = cy + int(h * 0.015)
            y2 = min(h, y1 + badge_h)
            x1 = max(0, cx - badge_w // 2)
            x2 = min(w, cx + badge_w // 2)

            roi = screen[y1:y2, x1:x2]
            if roi.size == 0:
                continue

            # 1. Try template match if badge_link_max exists
            tmpl_match = self.find_template(roi, "badge_link_max", threshold=0.82)
            if tmpl_match is not None:
                return True

            # 2. Color analysis: Gold/Yellow badge detection in HSV
            # High threshold prevents false positives from character artwork (yellow hair, armor, background)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            lower_gold = np.array([18, 140, 160], dtype=np.uint8)
            upper_gold = np.array([32, 255, 255], dtype=np.uint8)
            mask = cv2.inRange(hsv, lower_gold, upper_gold)
            gold_ratio = np.count_nonzero(mask) / float(roi.shape[0] * roi.shape[1])

            if gold_ratio > 0.35:
                return True

        return False

    def find_banner_on_screen(
        self, screen: np.ndarray, banner_img: np.ndarray, threshold: float = 0.72, scales: list[float] | None = None
    ) -> tuple[int, int, float] | None:
        """
        Locates a DokkanDB banner on the game screen using multi-scale template matching.
        Crops the inner graphic region (10% to 88% width) including artwork for maximum recognition.
        Returns (center_x, center_y, confidence) or None.
        """
        if banner_img is None or screen is None:
            return None

        # Clean 4-channel BGRA to 3-channel BGR if needed
        banner_bgr = banner_img[:, :, :3] if len(banner_img.shape) == 3 and banner_img.shape[2] == 4 else banner_img

        bh, bw = banner_bgr.shape[:2]
        s_h, s_w = screen.shape[:2]

        # Crop inner portion (both logo and character artwork, omitting outer bezels)
        crop = banner_bgr[int(bh * 0.10) : int(bh * 0.90), int(bw * 0.10) : int(bw * 0.88)]
        ch, cw = crop.shape[:2]

        if scales is None:
            # Game banners typically span ~88-92% of screen width.
            ideal_scale = (s_w * 0.90) / max(1, bw)
            scales = [ideal_scale * f for f in [0.88, 0.94, 1.0, 1.06, 1.12]]

        best_val = -1.0
        best_loc = None
        best_w, best_h = cw, ch

        for s in scales:
            scaled_w = int(cw * s)
            scaled_h = int(ch * s)

            if scaled_w > s_w or scaled_h > s_h or scaled_w < 20 or scaled_h < 20:
                continue

            scaled_crop = cv2.resize(crop, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen, scaled_crop, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_w, best_h = scaled_w, scaled_h
                if best_val >= threshold:
                    break

        if best_val >= threshold and best_loc is not None:
            center_x = best_loc[0] + best_w // 2
            center_y = best_loc[1] + best_h // 2
            return (int(center_x), int(center_y), float(best_val))

        return None

    def is_filter_dialog_open(self, screen: np.ndarray) -> bool:
        """Determines if the Filter / Sort modal is currently displayed."""
        return (
            self.find_template(screen, "button_remove_all", threshold=0.80) is not None
            or self.find_template(screen, "header_link_skill_level", threshold=0.80) is not None
        )

    def get_link_level_filter_status(self, screen: np.ndarray) -> dict[str, Any]:
        """
        Inspects the Filter / Sort modal (specifically the Link Skill Level section at the bottom)
        and detects the state and click coordinates of:
        - 'Level Up Possible' (unmaxed units)
        - 'All at Max Level' (maxed units)
        - 'OK' button
        - 'Remove All' button
        """
        h, w = screen.shape[:2]
        header_link = self.find_template(screen, "header_link_skill_level", threshold=0.80)
        has_link_section = header_link is not None
        default_btn_y = int(header_link[1] + 95) if header_link else int(h * 0.63)

        res: dict[str, Any] = {
            "is_open": self.is_filter_dialog_open(screen),
            "has_link_section": has_link_section,
            "level_up_possible": {"selected": False, "coords": (int(w * 0.27), default_btn_y)},
            "all_at_max": {"selected": False, "coords": (int(w * 0.66), default_btn_y)},
            "ok_button": None,
            "remove_all": None,
        }

        # Check OK and Remove All buttons
        ok_match = self.find_ok_button(screen)
        if ok_match:
            res["ok_button"] = (ok_match[0], ok_match[1])
        else:
            res["ok_button"] = (int(w * 0.50), int(h * 0.85))

        rm_match = self.find_template(screen, "button_remove_all", threshold=0.80)
        if rm_match:
            res["remove_all"] = (rm_match[0], rm_match[1])

        # Detect 'Level Up Possible' (threshold 0.85 to avoid false matches on unscrolled screens)
        lu_sel = self.find_template(screen, "btn_level_up_possible_selected", threshold=0.88)
        if lu_sel:
            res["level_up_possible"]["selected"] = True
            res["level_up_possible"]["coords"] = (lu_sel[0], lu_sel[1])
        else:
            lu_unsel = self.find_template(screen, "btn_level_up_possible_unselected", threshold=0.85)
            if lu_unsel:
                res["level_up_possible"]["coords"] = (lu_unsel[0], lu_unsel[1])

        # Detect 'All at Max Level' (threshold 0.85)
        max_sel = self.find_template(screen, "btn_all_at_max_selected", threshold=0.88)
        if max_sel:
            res["all_at_max"]["selected"] = True
            res["all_at_max"]["coords"] = (max_sel[0], max_sel[1])
        else:
            max_unsel = self.find_template(screen, "btn_all_at_max_unselected", threshold=0.85)
            if max_unsel:
                res["all_at_max"]["coords"] = (max_unsel[0], max_unsel[1])

        return res

    def get_team_slots_in_box(self, screen: np.ndarray) -> list[int]:
        """
        Scans the character box screen for active team slot badges (1 to 6).
        Returns a list of integer slot numbers (1..6) that are currently visible on cards in the box.
        """
        found_slots: list[int] = []
        for slot in range(1, 7):
            tmpl = f"badge_team_slot_{slot}"
            m = self.find_template(screen, tmpl, threshold=0.85)
            if m:
                found_slots.append(slot)
        return found_slots

    def find_first_unselected_card(self, screen: np.ndarray) -> tuple[int, int]:
        """
        Locates the first available card coordinate in the Character Box grid (Rows 1-4, Cols 1-5)
        that does not have an active team slot badge.
        Returns (x, y) tap coordinates.
        """
        h, w = screen.shape[:2]
        cols = [0.097, 0.296, 0.500, 0.699, 0.898]
        rows = [0.215, 0.323, 0.431, 0.539]

        # Find all active team slot badges and their locations
        badge_locations: list[tuple[int, int]] = []
        for slot in range(1, 7):
            tmpl = f"badge_team_slot_{slot}"
            m = self.find_template(screen, tmpl, threshold=0.85)
            if m:
                badge_locations.append((m[0], m[1]))

        for ry in rows:
            for rx in cols:
                cx = int(w * rx)
                cy = int(h * ry)
                # Check if this card slot has a team badge (within badge area)
                has_badge = False
                for bx, by in badge_locations:
                    if abs(cx - bx) < int(w * 0.10) and abs(cy - by) < int(h * 0.08):
                        has_badge = True
                        break
                if not has_badge:
                    return (cx, cy)

        # Fallback to Row 1, Col 1 coordinates
        return (int(w * cols[0]), int(h * rows[0]))

    def is_boost_off(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Returns (x, y) coordinates of the BOOST OFF button if boost is currently disabled, else None."""
        m = self.find_template(screen, "button_boost_off", threshold=0.80)
        if m:
            return (m[0], m[1])
        return None

    def find_stage_saiyan_training(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Finds '1. Saiyan Training' stage header on event stage select screen."""
        m = self.find_template(screen, "stage_saiyan_training", threshold=0.80)
        if m:
            return (m[0], m[1])
        return None

    def find_deck_remove_all(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Finds the 'Remove All' button on the team deck in Team Formation."""
        m = self.find_template(screen, "button_deck_remove_all", threshold=0.80)
        if m:
            return (m[0], m[1])
        return None

    def find_yellow_sort_button(self, screen: np.ndarray) -> tuple[int, int] | None:
        """
        Locates the yellow/gold Display Order & Filter button in the bottom right of the Character Box / Team Formation screen.
        First tries template matching for 'tag_sort_released'.
        If not found, falls back to the exact bottom-right position (X: ~80%, Y: ~96%).
        """
        m = self.find_template(screen, "tag_sort_released", threshold=0.75)
        if m:
            return (m[0], m[1])
        h, w = screen.shape[:2]
        return (int(w * 0.80), int(h * 0.958))

    def is_sort_released(self, screen: np.ndarray) -> bool:
        """Checks if character box sort order tag is currently set to 'Released'."""
        return self.find_template(screen, "tag_sort_released", threshold=0.80) is not None

    def is_filter_released_selected(self, screen: np.ndarray) -> bool:
        """Checks if 'Released' is selected in the Display Order filter dialog."""
        return self.find_template(screen, "btn_released_selected", threshold=0.80) is not None

    def get_top_box_card_coords(self, screen: np.ndarray, count: int = 6) -> list[tuple[int, int]]:
        """
        Calculates coordinates for the top cards in the character box,
        ordered strictly top-to-bottom and left-to-right (Row 1 Cols 1..5, Row 2 Cols 1..5, etc.).
        Dynamically adapts between standard 16:9 (1080x1920) and tall 20:9 (1080x2400) aspect ratios.
        """
        h, w = screen.shape[:2]
        cols = [0.10, 0.30, 0.50, 0.70, 0.90]
        aspect = h / float(w)
        # Standard 16:9 display (e.g. 1080x1920) vs tall 20:9 display with top padding (e.g. 1080x2400)
        rows = [0.172, 0.284, 0.396, 0.508, 0.620] if aspect < 1.85 else [0.215, 0.323, 0.431, 0.539]

        coords: list[tuple[int, int]] = []
        for ry in rows:
            for rx in cols:
                coords.append((int(w * rx), int(h * ry)))
                if len(coords) >= count:
                    return coords
        return coords

    def find_auto_map_off(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Returns (x, y) coordinates of the Auto Map button if it is currently OFF (grey), else None."""
        m = self.find_template(screen, "btn_auto_map_off", threshold=0.82)
        return (m[0], m[1]) if m else None

    def find_auto_battle_off(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Returns (x, y) coordinates of the Auto Battle button if it is currently OFF (grey), else None."""
        m = self.find_template(screen, "btn_auto_battle_off", threshold=0.82)
        return (m[0], m[1]) if m else None

    def find_auto_map_on(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Returns (x, y) coordinates of the Auto Map button if it is currently ON (green), else None."""
        m = self.find_template(screen, "btn_auto_map_on", threshold=0.82)
        return (m[0], m[1]) if m else None

    def find_auto_battle_on(self, screen: np.ndarray) -> tuple[int, int] | None:
        """Returns (x, y) coordinates of the Auto Battle button if it is currently ON (green), else None."""
        m = self.find_template(screen, "btn_auto_battle_on", threshold=0.82)
        return (m[0], m[1]) if m else None

    def has_auto_controls(self, screen: np.ndarray) -> bool:
        """Checks if Auto Map or Auto Battle buttons are visible on screen."""
        return (
            self.find_auto_map_off(screen) is not None
            or self.find_auto_map_on(screen) is not None
            or self.find_auto_battle_off(screen) is not None
            or self.find_auto_battle_on(screen) is not None
        )
