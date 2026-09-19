# DokkanBattleBot - UI Template Assets

This directory contains the Computer Vision template images (.png) used by OpenCV to identify UI elements within Dragon Ball Z: Dokkan Battle (Global).

All images are organized into categorical subdirectories and are indexed recursively and automatically by the `Vision` class ([`core/vision.py`](../core/vision.py)). Subdirectory paths do not need to be specified in calling code: `vision.find_template(screen, "button_ok")` automatically locates `buttons/button_ok.png`.

---

## 📁 Structure and Categories

```text
templates/glb/
├── buttons/               # Interactive and navigation buttons
│   ├── button_cancel.png         # "Cancel" button for modals
│   ├── button_close.png          # "Close" button for news and dialogs
│   ├── button_event.png          # "Event" button in the main start menu
│   ├── button_friend_refresh.png # Refresh icon for Friend Leader list
│   ├── button_ok.png             # Orange "OK" confirmation button
│   ├── button_start.png          # Orange START button on pre-battle screen
│   └── nav_start.png             # Big blue START button on Home screen
│
├── eza/                   # Extreme Z-Battle (EZA) specific UI elements
│   ├── button_eza_battle_info.png# EZA battle information button
│   ├── button_eza_fight.png      # Circular "Fight" button to launch an EZA stage
│   ├── button_eza_select_lv.png  # EZA level selection icon
│   ├── num_999.png               # Golden "999" digits to verify max stage level
│   ├── tag_lv_999.png            # Full "NEXT >> Lv. 999" banner tag
│   ├── tag_next_lv.png           # Banner tag prefix "NEXT >> Lv."
│   └── text_eza_fight.png        # Inner text of Fight button
│
├── popups/                # Modals and system popups
│   └── popup_friend_request.png  # Post-battle friend request dialog
│
├── system/                # Loading and system splash screens
│   ├── text_loading.png          # Animated "Now Loading..." indicator
│   └── text_touch_start.png      # Flashing "Touch Screen" title screen text
│
└── tabs/                  # Event category tabs
    ├── tab_zbattle_active.png    # Active "Z-Battle" tab (blue)
    └── tab_zbattle_inactive.png  # Inactive "Z-Battle" tab (gray)
```

---

## 📐 Reference Resolution
Templates are natively cropped at **1080x2400** (20:9 aspect ratio, standard for modern Samsung Galaxy / Android devices).
The `Vision` module supports automatic multi-scale matching (scales from 0.85x to 1.15x) to accommodate minor density and resolution differences across devices.

---

## 🛠️ Adding New Templates
Use the helper tool in `tools/template_helper.py`:

1. **Capture a screenshot of the current device screen:**
   ```bash
   python tools/template_helper.py --screenshot --out screen.png
   ```

2. **Crop a specific region as a new template:**
   ```bash
   python tools/template_helper.py --crop <x> <y> <w> <h> <template_name>
   ```

3. Move the newly generated `.png` into its respective categorical subdirectory (`buttons`, `eza`, `popups`, `system`, or `tabs`).
