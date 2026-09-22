[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 Dokkan-EZALink-Farmer - Commands & Usage Guide

> ⚠️ **IMPORTANT SCOPE NOTICE:**  
> This tool is **strictly specialized** for two endgame routines:
> 1. **Extreme Z-Battle (EZA Lv. 999):** Auto-climbing and infinite Platinum Hercule Statue (Zeni) farming.
> 2. **Chamber of Spirit and Time:** Event-based Link Level grinding with automatic team deck replenishment.
>
> It does **NOT** farm Story Quest mode, summon, or clear generic story/growth events.

---

## 💻 1. Launching the Standalone Executable (`dist/` Folder)

The bot is bundled as a pure terminal (console) executable. It does not require Python or any external packages to be installed on the target machine.

You can launch the bot immediately with a simple **double-click** (no terminal commands needed):
* **On Windows:** Double-click `Launch-Dokkan-EZALink.bat` (or `dokkan-eza-link.exe`).
* **On macOS:** Double-click `Launch-Dokkan-EZALink.command` (automatically opens Terminal and runs the bot).
* **On Linux:** Double-click `Launch-Dokkan-EZALink.sh` (or run `./Launch-Dokkan-EZALink.sh`).

---

Alternatively, you can run it from any shell / terminal (PowerShell, CMD, bash, zsh):

```bash
# Windows:
.\dokkan-eza-link.exe

# macOS / Linux:
./dokkan-eza-link
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
| `--link` | `[runs]` | Starts Link Level farming on the Chamber of Spirit and Time (stage "1. Saiyan Training", SUPER difficulty) with auto-rebuilding of the team using "Released" and "Level Up Possible" filters (optional: default until stamina depleted) |
| `--boost` / `--no-boost` | *none* | Enables (`--boost`) or disables (`--no-boost`) using Boost energy charges during Link Level farming |
| `--scrcpy` | *none* | Opens the zero-latency screen mirroring window |
| `--discord` | *none* | Runs the bot as a background service controlled remotely via Discord |
| `--config` | `<path>` | Path to custom configuration file (default: `config/settings.yaml`) |

### Quick Examples:
```bash
# System diagnostic check in English (default)
./dokkan-eza-link --doctor

# System diagnostic check in Italian
./dokkan-eza-link --lang it --doctor

# Start EZA automated climb up to level 999
./dokkan-eza-link --eza

# Run 30 Link Level farming iterations on Chamber of Spirit and Time
./dokkan-eza-link --link 30

# Launch scrcpy screen mirror
./dokkan-eza-link --scrcpy
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
| `link` | `link [runs] [boost]` | Starts Link Level farming with auto-swap of maxed characters (default: until stamina depleted) |
| `discord` | `discord [setup\|start]` | Starts the interactive configuration wizard (`discord setup`) or runs the bot listener (`discord start`) |
| `status` | `status` | Shows current bot status, statistics, and running tasks |
| `lang` | `lang [en\|it]` | Shows or dynamically changes the bot language at runtime |
| `pause` | `pause` | Temporarily pauses the running farming task |
| `resume` | `resume` | Resumes a paused farming task |
| `stop` | `stop` | Immediately aborts the running farming task |
| `help` | `help` | Displays the command summary table in your active language |
| `exit` / `quit` | `exit` | Safely shuts down the application |

---

## 🤖 4. Remote Control via Discord

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

   # With standalone executable (Windows):
   .\dokkan-eza-link.exe --discord

   # With standalone executable (macOS / Linux):
   ./dokkan-eza-link --discord
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
- From the command line: pass the `--discord` flag (`dokkan-eza-link.exe --discord`)

### 🎮 Available Discord Slash Commands:
- `/status`: Displays an embed card with connected device, completed runs, active state, and Zeni / Platinum Statue statistics.
- `/screenshot`: Captures phone display and sends a real-time screenshot directly to Discord.
- `/eza [target_level]`: Initiates automated EZA navigation and continuous climb to target level (default: 999).
- `/link [runs]`: Starts automated Link Leveling on Chamber of Spirit and Time with automatic character cycling.
- `/stop`: Aborts the current running task remotely and safely.
- `/pause` / `/resume`: Pauses or resumes automation.
- `/scrcpy [start/stop]`: Controls the screen mirroring window on the host computer.

---

## 🛠️ 5. Compiling the Standalone Binary (`scripts/build_dist.py`)

If you modify the source code and wish to recompile the `dist/dokkan-eza-link` distribution:

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
