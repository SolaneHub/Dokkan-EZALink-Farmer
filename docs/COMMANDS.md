[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 Dokkan-EZALink-Farmer - Commands & Usage Guide

> ⚠️ **SPECIALIZED ENDGAME CAPABILITIES:**  
> 1. **Extreme Z-Battle (EZA Lv. 999):** Auto-climbing and infinite Platinum Hercule Statue (Zeni) farming.
> 2. **Chamber of Spirit and Time / Quest Link Leveling:** High-speed Link Level grinding with automatic team deck replenishment.
> 3. **Autonomous Character Box Scanner:** Full on-device RapidOCR box cataloging into `config/box.json` with DokkanDB sync.
> 4. **AI Team Builder & Challenge Solver:** DeepSeek/Qwen strategic mission solving and mathematically optimal rotation planning.

---

## 💻 1. Launching the Bot (1-Click Launchers & Standalone)

You can launch the bot immediately with a simple **double-click** (no terminal commands needed):
* **On Windows:** Double-click `Launch-Dokkan-EZALink.bat`.
* **On macOS:** Double-click `Launch-Dokkan-EZALink.command` (automatically opens Terminal, removes browser quarantine, and runs standalone binary).
* **On Linux:** Double-click `Launch-Dokkan-EZALink.sh` (or run `./Launch-Dokkan-EZALink.sh`).

> 💡 **macOS Note:** If executing the binary directly from terminal rather than using `.command`, remove browser download quarantine with: `xattr -dr com.apple.quarantine .`

---

Alternatively, you can run it from any shell / terminal (PowerShell, CMD, bash, zsh):

```bash
# Windows (PowerShell / CMD):
.\Launch-Dokkan-EZALink.bat
# or with Python directly:
python main.py

# macOS / Linux:
./Launch-Dokkan-EZALink
```

---

## ⚡ 2. Command-Line Arguments & Flags

You can pass arguments directly to the executable to perform specific tasks without opening the interactive console:

| Flag | Argument | Description |
|---|---|---|
| `--lang`, `-l` | `[en\|it]` | Sets the interface language (default: `en`, options: `en`, `it`) |
| `--doctor` | *none* | Runs a complete system diagnostic check (scrcpy, adb, OS, connected devices) |
| `--devices` | *none* | Displays all connected Android devices (USB or Wi-Fi) |
| `--eza` | `[level=999]` | Automatically navigates to EZA Events, scrolls to the bottom, finds the first uncompleted EZA (< 999), and farms up to the target level (default: `999`) |
| `--link` | `[runs]` | Starts Link Level farming for N runs (or until stamina depleted if omitted). Prompts for stage (Area 39-3, Area 35-1, Chamber) if not preset. Auto-loops using "Attempt Again" and configures filters on Run 1 only |
| `--stage` | `[stage_id\|runs]` | Sets target stage for AI Endgame run (e.g. `10101`, `rz_broly`) or runs repeated farming |
| `--ur` | *none* | Filters character box for UR rarity unmaxed cards during Link Level farming (can combine with `--lr`) |
| `--lr` | *none* | Filters character box for LR rarity unmaxed cards during Link Level farming (can combine with `--ur`) |
| `--scan-box` | `[max_cards]` | Autonomously scans character box using on-device RapidOCR, enriches metadata via DokkanDB, and saves to `~/.dokkan-farmer/cache/user_box.json` (debug logs in `~/.dokkan-farmer/box_scan.log`) |
| `--ai-run` | `[stage_id]` | Starts autonomous Trial & Error loop with episodic memory against Red Zone and Blue Zone challenge bosses (default: `10101` Broly) |
| `--challenge` | `[event_name]` | Analyzes challenge event missions using AI and builds optimal team compositions from `config/box.json` |
| `--boost` / `--no-boost` | *none* | Enables (`--boost`) or disables (`--no-boost`) using Boost energy charges during Link Level farming |
| `--scrcpy` | *none* | Opens the zero-latency screen mirroring window |
| `--discord` | *none* | Runs the bot as a background service controlled remotely via Discord |
| `--config` | `<path>` | Path to custom configuration file (default: `config/settings.yaml`) |

### Quick Examples:
```bash
# Full box synchronization and scan with DokkanDB enrichment:
dokkan-farmer scan-box

# Start AI Trial & Error loop against Red Zone Broly:
dokkan-farmer ai-run --stage 10101
# or using string slug:
dokkan-farmer ai-run --stage rz_broly

# Start AI Trial & Error loop against Beast Gohan (Blue Zone / SMB):
dokkan-farmer ai-run --stage 20101

# Run system doctor in English (default):
./Launch-Dokkan-EZALink --doctor

# Run system doctor in Italian:
./Launch-Dokkan-EZALink --lang it --doctor

# Start automatic EZA climbing directly:
./Launch-Dokkan-EZALink --eza

# Farm 30 runs of Link Leveling with UR and LR cards:
./Launch-Dokkan-EZALink --link 30 --ur --lr

# Farm Link Leveling with only LR cards:
./Launch-Dokkan-EZALink --link --lr

# Scan the first 100 character cards:
./Launch-Dokkan-EZALink --scan-box 100

# Launch phone screen mirroring window:
./Launch-Dokkan-EZALink --scrcpy
```

---

## ⌨️ 3. Interactive CLI Console (`dokkan-farmer>`)

Running the executable without extra arguments enters the interactive Rich terminal console with real-time colored log output.

### Available Console Commands:

| Command | Syntax | Description |
|---|---|---|
| `doctor` / `check` | `doctor` | Validates ADB, scrcpy, OS compatibility, and connected devices |
| `devices` | `devices` | Lists all detected Android devices |
| `connect` | `connect [serial]` | Connects to a specific device or auto-detects the first available |
| `scrcpy` | `scrcpy` | Opens the phone screen mirroring window |
| `scrcpy-stop` | `scrcpy-stop` | Closes the scrcpy mirroring process |
| `inspect` / `state` | `inspect` | Captures the active screen and prints the detected game state |
| `shot` | `shot [name.png]` | Takes and saves a screenshot of the current screen |
| `eza` | `eza [level\|auto]` | Opens interactive DokkanDB selector (arrow keys & search) or starts directly if specified |
| `link` | `link [runs] [--ur] [--lr] [--boost]` | Opens interactive stage selection dropdown (Area 39 Stage 3, Area 35 Stage 1, Chamber of Spirit and Time). Supports cumulative `--ur` and `--lr` rarity flags. Loops directly via "Attempt Again" and configures box filters on Run 1 only |
| `stage` / `farm` | `stage [runs] [--boost]` | Repeatedly clears manually selected stage in-game until stamina runs out (or for N runs). Re-runs stage using "Attempt Again" and automatically exits when stamina is depleted |
| `scan-box` | `scan-box [max]` | Scans character box in automated swipe cycles, detecting titles, rainbow stars, copies, and saves to `~/.dokkan-farmer/cache/user_box.json` (debug logs in `~/.dokkan-farmer/box_scan.log`) |
| `ai-run` | `ai-run [stage_id]` | Starts autonomous Trial & Error loop with combat telemetry against Red Zone and Blue Zone challenge bosses (e.g. `10101`, `20101`, `rz_broly`) |
| `challenge` / `ai-team` | `challenge [event]` | Synthesizes optimal team compositions and rotations for event missions using AI and scanned box |
| `discord` | `discord [setup\|start]` | Starts the interactive configuration wizard (`discord setup`) or runs the bot listener (`discord start`) |
| `status` | `status` | Shows current bot status, statistics, and running tasks |
| `lang` | `lang [en\|it]` | Shows or dynamically changes the bot language at runtime |
| `pause` | `pause` | Temporarily pauses the running farming task |
| `resume` | `resume` | Resumes a paused farming task |
| `stop` | `stop` | Immediately aborts the running farming task |
| `help` | `help` | Displays the command summary table in your active language |
| `exit` / `quit` | `exit` | Safely shuts down the application |

---

## 🧠 4. AI Autonomous Endgame Runner & Box Scanner (Red Zone / Blue Zone)

Dokkan-EZALink-Farmer integrates a local LLM inference engine (Ollama DeepSeek-R1 / Qwen) with mathematical constraint solving and episodic memory to autonomously conquer Dokkan Battle's hardest endgame stages:

### 1. Character Box Scan (`scan-box`):
Performs on-device RapidOCR scans of your character box, queries DokkanDB to enrich passives, leader skills, and link skills, and saves the inventory to `~/.dokkan-farmer/cache/user_box.json` while continuously capturing debug logs in `~/.dokkan-farmer/box_scan.log`.
```bash
dokkan-farmer scan-box
```

### 2. Endgame Boss Catalog (`boss_stages.json`):
Contains iconic challenge stages with full sequential phases, elements, and real gimmicks:
* **Red Zone: Movie Edition - Broly (`10101` / `rz_broly`):** 4 phases (AGL -> TEQ -> STR AoE -> AGL Cancels Dodge).
* **Red Zone: Red Ribbon Army - Cell Max (`10102` / `rz_cell_max`):** 3 phases (PHY -> INT -> TEQ AoE + Cancels Dodge + Locks Slots).
* **Red Zone: Dismal Future - Fusion Zamasu (`10103` / `rz_zamasu`):** 2 phases (INT AoE -> PHY Locks Slots).
* **Red Zone: Majin Buu Saga - Kid Buu (`10104` / `rz_kid_buu`):** 2 phases (TEQ -> PHY Cancels Dodge).
* **Red Zone: GT Edition - Omega Shenron (`10105` / `rz_omega`):** 3 phases (AGL -> STR AoE -> INT Locks Slots + Cancels Dodge).
* **Supreme Magnificent Battle (Blue Zone): Beast Gohan (`20101` / `smb_beast_gohan`):** 3 phases (TEQ -> PHY Locks Slots -> STR Cancels Dodge + Locks Slots).
* **Supreme Magnificent Battle (Blue Zone): Super Gogeta (`20102` / `smb_gogeta`):** 3 phases (AGL -> STR AoE -> PHY Cancels Dodge).
* **Supreme Magnificent Battle (Blue Zone): Evo Blue Vegeta & UI Goku (`20103` / `smb_evo_ui`):** 3 phases (INT -> AGL -> TEQ Cancels Dodge + Locks Slots).

### 3. 4-Step Gameplay Loop State Machine (`ai-run`):
* **Step A (Initialization):** Loads `user_box.json` and `ai_memory.json`, then synthesizes the best initial team via `TeamBuilder` and constraint solver.
* **Step B (Formation):** If recommended team differs from equipped team, automatically applies team formation in-game via ADB.
* **Step C (Launch & Telemetry):** Selects Friend Leader (refreshing if needed), clicks start, verifies Auto-Battle is ON (`btn_auto_battle_on.png`), and starts telemetry loop (4-frame pre-KO rolling FIFO buffer).
* **Step D (Outcome):**
  * **Victory (`button_ok.png`):** Registers team as *Winning Team* in `ai_memory.json` and exits with success.
  * **Defeat (`button_attempt_again.png`):** Generates `FailureReport` and executes adaptive decision tree:
    1. `InstantRetry`: Boss HP < 20% in final phase or Friend Leader defeat (Slot 7).
    2. `SurgicalSwap` (`SurgicalReplace`): Surgical single-card replacement with orphan link check (< 3 links) or Pair Swap.
    3. `LeaderSwitch` (`DemoteLeader`): Demotes leader to 2nd best leader after 3 consecutive Turn 1-2 defeats.

```bash
# Example invocation:
dokkan-farmer ai-run --stage 10101
```

---

## 🤖 5. Remote Control via Discord

Dokkan-EZALink-Farmer comes with an integrated Discord bot allowing you to fully monitor and control farming sessions remotely using Slash Commands (`/status`, `/screenshot`, `/eza`, `/link`, etc.).

### ⚡ Interactive Setup Wizard (Recommended Method):

You do NOT need to edit YAML files manually! You can set up your Discord bot in seconds through the interactive wizard:

1. **From the Interactive CLI Console:**
   ```text
   dokkan-farmer> discord setup
   ```
2. **Or from the Terminal / Command Prompt:**
   ```bash
   # With Python:
   python main.py --discord

   # With standalone executable (macOS / Linux):
   ./Launch-Dokkan-EZALink --discord
   ```
   If not yet configured, the setup wizard will launch automatically and prompt you to input:
   - **Bot Token**: Your bot token copied from the Discord Developer Portal
   - **Channel ID**: The text channel ID for status messages and screenshots
   - **User ID (optional)**: Your Discord User ID to restrict commands strictly to yourself

   The wizard validates and persists these credentials automatically.

> 📖 For a complete step-by-step tutorial on creating your bot application on Discord Developer Portal in under 2 minutes, see the [Discord Setup Guide](DISCORD_SETUP.md).

### 🚀 Starting the Discord Bot:

Once configured, run the Discord bot anytime:
- From the interactive console: type `discord start`
- From the command line: pass the `--discord` flag (`.\Launch-Dokkan-EZALink.bat --discord` on Windows or `./Launch-Dokkan-EZALink --discord` on macOS/Linux)

### 🎮 Available Discord Slash Commands:
- `/status`: Displays an embed card with connected device, completed runs, active state, and Zeni / Platinum Statue statistics.
- `/screenshot`: Captures phone display and sends a real-time screenshot directly to Discord.
- `/eza [target_level]`: Initiates automated EZA navigation and continuous climb to target level (default: 999).
- `/link [runs] [stage] [filter_rarity] [boost]`: Starts automated Link Leveling with selectable stage (`Area 39 Stage 3`, `Area 35 Stage 1`, `Chamber of Spirit and Time`), cumulative rarity filters (`UR + LR`, `UR`, `LR`), automatic "Attempt Again" rapid restart looping, and single-setup Run 1 filter optimization.
- `/stop`: Aborts the current running task remotely and safely.
- `/pause` / `/resume`: Pauses or resumes automation.
- `/scrcpy [start/stop]`: Controls the screen mirroring window on the host computer.

---

## 🧠 5. AI Team & Mission Solver (Universal Models)

Dokkan-EZALink-Farmer integrates local and remote LLM reasoning to solve challenge event missions (Red Zone, Supreme Magnificent Battle) and optimize team rotations.

### 🌟 Officially Supported Universal Models (PC & Mac):

| Model Name | Model Family | Key Capabilities | Best For |
|---|---|---|---|
| **`deepseek-r1:7b`** | `deepseek_r1` | Full step-by-step Chain of Thought (`<think>`) reasoning, multi-phase boss mechanics analysis | **Recommended for PC (RTX 3060 Ti) & Mac (Apple Silicon M2)** |
| **`qwen2.5:7b`** | `qwen` | Direct structured Markdown output, immediate tactical breakdown | High-speed direct analysis on PC & Mac |
| **`qwen2.5:3b`** | `qwen` | Ultra-compact (2GB VRAM), zero CPU/battery pressure | MacBook Air M2 on battery saving mode |

### 🛠️ Switching Models via CLI:
From the interactive console:
```text
dokkan-farmer> ai switch
```
Select between the 3 universal models or enter a custom model name.

---

## 🛠️ 5. Compiling Standalone Executables (`scripts/build_dist.py`)

If you modify the source code and wish to recompile the `dist/Launch-Dokkan-EZALink` distribution:

```bash
# Compile standalone distribution directory (--onedir)
python scripts/build_dist.py

# Or compile into a single standalone executable (--onefile)
python scripts/build_dist.py --onefile
```
The build script automatically handles:
1. Bundling Python runtime and all dependencies (`opencv`, `numpy`, `rich`, `discord.py`).
2. Setting `console=True` (strictly terminal-only, no GUI wrappers).
3. Embedding all CV template assets from `templates/glb/`.
4. Copying `config/settings.yaml`, translation catalogs `locales/`, and documentation files into the distribution folder.
5. Generating 1-click launchers (`Launch-Dokkan-EZALink.bat`, `Launch-Dokkan-EZALink.command`, `Launch-Dokkan-EZALink.sh`).
