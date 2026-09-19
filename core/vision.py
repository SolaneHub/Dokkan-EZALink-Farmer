import os
import cv2
import numpy as np
from typing import Optional, Tuple, List, Dict
from core.system_tools import get_resource_path


class Vision:
    """Handles Computer Vision, template matching, and UI element detection for Dokkan."""

    def __init__(self, template_dir: str = "templates/glb", default_threshold: float = 0.78):
        self.template_dir = template_dir if os.path.isabs(template_dir) else get_resource_path(template_dir)
        self.default_threshold = default_threshold
        self._template_cache: Dict[str, Optional[np.ndarray]] = {}
        self._template_map: Dict[str, str] = {}
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

    def list_templates_by_category(self) -> Dict[str, List[str]]:
        """Returns a dict of subfolder categories and their template filenames."""
        categories: Dict[str, List[str]] = {}
        for root, _, files in os.walk(self.template_dir):
            cat = os.path.relpath(root, self.template_dir).replace("\\", "/")
            if cat == ".":
                cat = "root"
            img_files = [f for f in sorted(files) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
            if img_files:
                categories[cat] = img_files
        return categories

    def load_template(self, template_name: str) -> Optional[np.ndarray]:
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
        threshold: Optional[float] = None,
        scales: List[float] = [0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15]
    ) -> Optional[Tuple[int, int, float]]:
        """
        Locates a template on the screen using multi-scale template matching.
        Returns: (center_x, center_y, max_val) or None
        """
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
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: float = 0.78,
        min_distance: int = 80
    ) -> List[Tuple[int, int, float]]:
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
        for pt in zip(*loc[::-1]):
            candidates.append((pt[0] + t_w // 2, pt[1] + t_h // 2, float(res[pt[1], pt[0]])))

        if not candidates:
            return []

        # Sort candidates descending by confidence
        candidates.sort(key=lambda c: c[2], reverse=True)

        filtered: List[Tuple[int, int, float]] = []
        for c in candidates:
            if not any(abs(c[0] - f[0]) < min_distance and abs(c[1] - f[1]) < min_distance for f in filtered):
                filtered.append(c)

        return filtered

    def find_ok_button(self, screen: np.ndarray, threshold: float = 0.80) -> Optional[Tuple[int, int, float]]:
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
        for pt in zip(*loc[::-1]):
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

    def find_any_template(
        self,
        screen: np.ndarray,
        template_names: List[str],
        threshold: Optional[float] = None
    ) -> Optional[Tuple[str, int, int, float]]:
        """Tests multiple templates and returns the first match found with (name, x, y, conf)."""
        for name in template_names:
            match = self.find_template(screen, name, threshold)
            if match:
                return (name, match[0], match[1], match[2])
        return None

    def save_template_crop(
        self,
        screen: np.ndarray,
        box: Tuple[int, int, int, int],
        name: str,
        category: Optional[str] = None
    ) -> str:
        """
        Saves a cropped region as a template file for future matching.
        box: (x, y, width, height)
        """
        x, y, w, h = box
        crop = screen[y:y+h, x:x+w]
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
    def get_dominant_color_in_rect(
        screen: np.ndarray,
        x1: int, y1: int, x2: int, y2: int
    ) -> Tuple[int, int, int]:
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
        """
        h, w = screen.shape[:2]
        # Relative horizontal centers for slots 0 to 5 (Leader = 0, Sub units = 1..5)
        slot_centers_x = [0.15, 0.29, 0.43, 0.57, 0.71, 0.85]
        if slot_idx < 0 or slot_idx >= len(slot_centers_x):
            return False

        cx = int(w * slot_centers_x[slot_idx])
        cy = int(h * 0.48)

        # Region around the character's link skill badge (lower portion of character circle)
        badge_h = int(h * 0.05)
        badge_w = int(w * 0.10)
        y1 = cy + int(h * 0.015)
        y2 = min(h, y1 + badge_h)
        x1 = max(0, cx - badge_w // 2)
        x2 = min(w, cx + badge_w // 2)

        roi = screen[y1:y2, x1:x2]
        if roi.size == 0:
            return False

        # 1. Try template match if badge_link_max.png exists
        tmpl_match = self.find_template(roi, "badge_link_max", threshold=0.72)
        if tmpl_match is not None:
            return True

        # 2. Color analysis: Gold/Yellow badge detection in HSV
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower_gold = np.array([18, 100, 140], dtype=np.uint8)
        upper_gold = np.array([38, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_gold, upper_gold)
        gold_ratio = np.count_nonzero(mask) / float(roi.shape[0] * roi.shape[1])

        return gold_ratio > 0.12
