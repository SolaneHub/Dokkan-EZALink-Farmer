# ⚡ Dokkan-EZALink-Farmer ⚡

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build & Release](https://img.shields.io/badge/releases-GitHub%20Actions-orange.svg)]()

> 📖 **Language Guides / Guide di Utilizzo:**  
> [ 🇬🇧 Full Commands Guide ](docs/COMMANDS.md) | [ 🇮🇹 Guida ai Comandi in Italiano ](docs/COMMANDS.it.md)

---

### 🛑 What this bot is NOT
* This is **NOT** a general-purpose "do everything" bot or full-game emulator assistant.
* It does **NOT** farm Story Quest mode (e.g. Area 31/32/34).
* It does **NOT** summon, sell characters, farm medals, or clear story events.

### 🎯 What this bot IS
A laser-focused, lightweight computer-vision automation tool designed exclusively for the **two most tedious, repetitive endgame chores** in *Dragon Ball Z: Dokkan Battle*:
1. 💰 **Endless Zeni Farming via EZA (Extreme Z-Battle):** Automatically climbs Z-Battles up to Level 999 to farm endless Platinum Hercule Statues (~1.5M Zeni per stage clear).
2. 🥋 **Event-Based Link Leveling (Chamber of Spirit and Time):** Clears the daily *Ultimate Leveling Up! Chamber of Spirit and Time* (*Stanza dello Spirito e del Tempo*) event with automated deck rotation (Release Order & Level Up Possible filters).

---

## 🎯 Core Features

### ⚔️ 1. Extreme Z-Battle (EZA) Auto-Climbing (Infinite Zeni)
* **Automatic Navigation:** Navigates from Home/Events straight to the **Z-Battle** tab.
* **Smart Detection:** Rapidly scrolls to the bottom of the list and automatically targets the first uncompleted EZA (< Lv. 999), or challenges a specific event selected via DokkanDB.
* **Endless Zeni Farming:** Automates continuous consecutive battles up to Level 999 to farm infinite Platinum Hercule Statues (~1.5M Zeni each).
* **Speed & Safety:** Auto-assigns friend leaders, enables 2x Auto-Battle, skips reward screens, dismisses friend requests, and stops safely on Game Over or when your character box is full.

### 🥋 2. Chamber of Spirit and Time (Event Link Leveling)
* **Dedicated Event Integration:** Automatically identifies the *Ultimate Leveling Up! Chamber of Spirit and Time* (*Stanza dello Spirito e del Tempo*) in the BONUS tab using DokkanDB templates.
* **Stage & Difficulty:** Targets *1. Saiyan Training* on **SUPER** difficulty (40 STA).
* **Intelligent Team Rotation:**
  * Opens the Character Box and applies the **Released** (Acquisition Order) and **Level Up Possible** filters (excluding characters whose links are all MAX Lv. 10).
  * Uses *Remove All* to clear the deck and reloads the top 6 cards needing leveling.
  * Replaces units as soon as their link skills reach Level 10.
* **Boost Energy Support:** Toggle Boost on or off via CLI flags (`--boost` / `--no-boost`) or configuration.
* **Rapid Looping:** Leverages the 'Attempt Again' button to chain runs quickly and detects daily attempt limits automatically.

---

## 📱 Supported Devices & Connection

### 1. Android Emulators (Windows & Mac)
* **Supported:** BlueStacks, LDPlayer, MuMu Player (12 / X), NoxPlayer, MEmu Play, Android Studio AVD, Genymotion.
* **Plug & Play:** Automatically probes standard emulator ports (`5555`, `5554`, `7555`, `16384`, `62001`, `21503`). Just start your emulator with ADB debugging enabled, and the bot connects automatically.
* *Note:* Emulators run in their own desktop window, so screen mirroring (`scrcpy`) is not required.

### 2. Physical Android Phones
* Connect your Android phone via USB (or wireless ADB) with **USB Debugging** enabled.
* **Zero-Latency Mirroring:** Use `dokkan-eza-link --scrcpy` (or the `scrcpy` console command) to open a real-time mirroring window of your phone on your computer screen.

### 3. Autonomous Tool Detection (`ToolLocator`)
* The bot automatically detects `adb` and `scrcpy` binaries on your system across **Windows** (WinGet, Scoop, Chocolatey, Program Files, Downloads) and **macOS** (Homebrew Apple Silicon M1–M4 & Intel, Android Studio SDK, `/Applications`). No manual PATH configuration is required.

---

## 🚀 Quick Start

### Option A: Standalone Executable (Recommended, No Python Required)
Download the pre-compiled package for your operating system from the [**Releases**](https://github.com/) page:
- **Windows:** Download `dokkan-eza-link-windows-x64.zip`, extract, and double-click `Launch-Dokkan-EZALink.bat` (or `dokkan-eza-link.exe`).
- **macOS:** Download `dokkan-eza-link-macos.zip`, extract, and double-click `Launch-Dokkan-EZALink.command` (opens Terminal automatically).
- **Linux:** Download `dokkan-eza-link-linux-x64.zip`, extract, and double-click `Launch-Dokkan-EZALink.sh`.

### Option B: Running from Python Source
1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-repo/Dokkan-EZALink-Farmer.git
   cd Dokkan-EZALink-Farmer
   ```

2. **Create a virtual environment & install dependencies:**
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Verify your environment:**
   ```bash
   python main.py --doctor
   ```

---

## ⚡ Command Line Usage

You can start tasks directly from your terminal:

```bash
# Verify environment (scrcpy, adb, OS, connected phones/emulators)
python main.py --doctor

# Set interface to Italian and run doctor check
python main.py --lang it --doctor

# Start automated EZA climbing up to Lv. 999 (Zeni farming)
python main.py --eza

# Start Link Level farming on Chamber of Spirit and Time (runs until stamina empty)
python main.py --link

# Farm 10 runs of Chamber of Spirit and Time with Boost active
python main.py --link 10 --boost

# Open real-time scrcpy screen mirroring (for physical phones)
python main.py --scrcpy
```

*(If using the standalone binary, replace `python main.py` with `.\dokkan-eza-link.exe` on Windows or `./dokkan-eza-link` on macOS/Linux).*

---

## ⌨️ Interactive CLI Console

Running `python main.py` (or double-clicking `Launch-Dokkan-EZALink.*`) opens the interactive console:

```text
dokkan-farmer> help
dokkan-farmer> devices          # List connected devices / emulators
dokkan-farmer> connect          # Auto-connects to first available device
dokkan-farmer> eza              # Interactive EZA selector or auto-climb
dokkan-farmer> link             # Start Chamber of Spirit and Time farming
dokkan-farmer> status           # Show task progress, completed runs, and Zeni stats
dokkan-farmer> pause / resume   # Pause or resume automation
dokkan-farmer> stop             # Stop running automation safely
dokkan-farmer> scrcpy           # Launch phone mirroring window
dokkan-farmer> discord setup    # Launch interactive Discord bot setup wizard
```

---

## 🤖 Remote Control via Discord

The bot includes an optional Discord bot interface with real-time alerts, live screenshots, and Slash Command support:

### Quick Setup Wizard (No manual file editing needed)
Run the setup wizard directly from the console:
```text
dokkan-farmer> discord setup
```
Or launch Discord mode directly from the terminal:
```bash
python main.py --discord
# or with standalone executable:
.\dokkan-eza-link.exe --discord
```
If no token is configured, the bot will prompt you to paste your **Bot Token** and **Channel ID** and save it directly to [`config/settings.yaml`](config/settings.yaml).

> 📖 **Step-by-Step Setup Guides:**  
> * 🇮🇹 [**Guida Configurazione Bot Discord (Italiano)**](docs/DISCORD_SETUP.it.md)  
> * 🇬🇧 [**Discord Bot Setup Guide (English)**](docs/DISCORD_SETUP.md)

### Available Slash Commands on Discord:
* `/status`: Displays bot state, completed runs, Hercule statues, and estimated Zeni.
* `/screenshot`: Sends a real-time screenshot of the game to your Discord channel.
* `/eza [target_level]`: Starts continuous EZA climbing (default: 999).
* `/link [runs]`: Starts Link Level farming on Chamber of Spirit and Time.
* `/stop`: Aborts the running task remotely.
* `/pause` / `/resume`: Pauses or resumes farming.
* `/scrcpy [start/stop]`: Controls phone mirroring window on your computer.

---

## 🛠️ Building Standalone Binaries

To compile your own standalone executables locally:
```bash
python scripts/build_dist.py
```
Pre-compiled builds are also generated automatically on **GitHub Releases** via GitHub Actions for Windows, macOS, and Linux.

---

## 📄 Documentation

* 🇬🇧 [**English Commands Guide**](docs/COMMANDS.md) | 🇮🇹 [**Guida Comandi in Italiano**](docs/COMMANDS.it.md)
* 🇬🇧 [**Discord Setup Guide**](docs/DISCORD_SETUP.md) | 🇮🇹 [**Guida Configurazione Discord**](docs/DISCORD_SETUP.it.md)

---

## ⚠️ Disclaimer

This project is a free, open-source automation tool created for educational and personal use. *Dragon Ball Z: Dokkan Battle* is a registered trademark of Bandai Namco Entertainment Inc. and Akatsuki Inc.
