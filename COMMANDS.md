[ 🇬🇧 English ](COMMANDS.md) | [ 🇮🇹 Italiano ](COMMANDS.it.md)

---

# 🎮 DokkanBattleBot - Commands & Usage Guide

This guide provides a comprehensive overview of all available commands, command-line startup options, interactive CLI usage, and remote Discord integration.

---

## 💻 1. Launching the Standalone Executable (`dist/` Folder)

The bot is bundled as a pure terminal (console) executable. It does not require Python or any external packages to be installed on the target machine.

Open your terminal (PowerShell / Command Prompt on Windows, Terminal / iTerm on macOS / Linux), navigate to the extracted folder, and run:

### On Windows:
```powershell
cd dist\dokkan-bot
.\dokkan-bot.exe
```

### On macOS / Linux:
```bash
cd dist/dokkan-bot
chmod +x dokkan-bot
./dokkan-bot
```

*(Alternatively, in a Python development environment, you can run `python main.py`)*.

---

## ⚡ 2. Command-Line Arguments & Flags

You can pass arguments directly to the executable to perform specific tasks without opening the interactive console:

| Flag | Argument | Description |
|---|---|---|
| `--lang`, `-l` | `[en\|it]` | Sets the interface language (default: `en`, options: `en`, `it`) |
| `--doctor` | *none* | Runs a complete system diagnostic check (scrcpy, adb, OS, connected devices) |
| `--devices` | *none* | Displays all connected Android devices (USB or Wi-Fi) |
| `--eza` | `[level=999]` | Automatically navigates to EZA Events, scrolls to the bottom, finds the first uncompleted EZA (< 999), and farms up to the target level (default: `999`) |
| `--farm` | `[runs=10]` | Starts continuous stage farming for the currently selected stage for N runs (default: `10`) |
| `--link` | `[runs=20]` | Starts continuous Link Level farming with automatic swapping of maxed units (default: `20`) |
| `--scrcpy` | *none* | Opens the zero-latency screen mirroring window |
| `--discord` | *none* | Runs the bot as a background service controlled remotely via Discord |
| `--config` | `<path>` | Path to custom configuration file (default: `config/settings.yaml`) |

### Quick Examples:
```bash
# System diagnostic check in English (default)
./dokkan-bot --doctor

# System diagnostic check in Italian
./dokkan-bot --lang it --doctor

# Start EZA automated climb up to level 999
./dokkan-bot --eza

# Run 30 Link Level farming iterations
./dokkan-bot --link 30

# Launch scrcpy screen mirror
./dokkan-bot --scrcpy
```

---

## ⌨️ 3. Interactive CLI Console (`dokkan-bot>`)

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
| `eza` | `eza [level]` | Starts automated navigation and EZA climbing (default: 999) |
| `farm` | `farm [runs]` | Starts repetitive farming on the current stage |
| `link` | `link [runs]` | Starts Link Level farming with auto-swap of maxed characters |
| `status` | `status` | Shows current bot status, statistics, and running tasks |
| `lang` | `lang [en\|it]` | Shows or dynamically changes the bot language at runtime |
| `pause` | `pause` | Temporarily pauses the running farming task |
| `resume` | `resume` | Resumes a paused farming task |
| `stop` | `stop` | Immediately aborts the running farming task |
| `help` | `help` | Displays the command summary table in your active language |
| `exit` / `quit` | `exit` | Safely shuts down the application |

---

## 🤖 4. Remote Control via Discord

You can control and monitor the bot from any authorized Discord channel using full Slash Commands:

### Configuration (`config/settings.yaml`):
```yaml
discord:
  token: "YOUR_DISCORD_BOT_TOKEN"
  channel_id: 123456789012345678  # Channel ID for notifications and screenshots
  allowed_user_ids: []             # Authorized user IDs (empty = anyone in channel)
```

### Starting Discord Mode:
```bash
./dokkan-bot --discord
```

### Available Discord Slash Commands:
- `/status`: Displays an embed card with connected device, completed runs, active state, and Zeni / Platinum Statue statistics.
- `/screenshot`: Captures phone display and sends an instant screenshot to Discord.
- `/eza [target_level]`: Initiates automated EZA navigation and climb to target level.
- `/farm [runs]`: Starts automated stage farming.
- `/link [runs]`: Starts automated Link Leveling.
- `/stop`: Aborts the current running task remotely.
- `/pause` / `/resume`: Pauses or resumes automation.
- `/scrcpy [start/stop]`: Controls the screen mirroring window on the host computer.

---

## 🛠️ 5. Compiling the Standalone Binary (`build_dist.py`)

If you modify the source code and wish to recompile the `dist/dokkan-bot` distribution:

```bash
# Compile standalone distribution directory (--onedir)
python build_dist.py

# Or compile into a single standalone executable (--onefile)
python build_dist.py --onefile
```
The build script automatically handles:
1. Bundling Python runtime and all dependencies (`opencv`, `numpy`, `rich`, `discord.py`).
2. Setting `console=True` (strictly terminal-only, no GUI wrappers).
3. Embedding all CV template assets from `templates/glb/`.
4. Copying `config/settings.yaml`, translation catalogs `locales/`, and documentation files `COMMANDS.md`, `COMMANDS.it.md`, and `README.md` into the distribution folder.
