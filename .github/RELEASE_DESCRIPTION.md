# ⚡ Dokkan-EZALink-Farmer v1.0.0

A high-performance terminal automation and remote control tool for **Dragon Ball Z Dokkan Battle**. Exclusively specialized in the two most tedious and time-consuming endgame tasks: **continuous Extreme Z-Battle climbing (EZA up to Level 999)** and **automated Link Level farming in the Chamber of Spirit and Time**.

---

## 🌟 Key Features

### ⚔️ Extreme Z-Battle (EZA) Auto-Climber (Lv. 999 & Infinite Zeni)
- **Continuous Automated Climb:** Automatically navigates through EZA events, detects the current stage level, and climbs continuously up to Level 999.
- **Unlimited Zeni Grinding:** Consistent farming of Platinum Hercule Statues (~1,500,000 Zeni per victory past Level 30).
- **Comprehensive Screen Handling:** Intelligent handling of victory, defeat, friend supporters, network reconnects, and loading screens.

### 🔮 Link Level Grinder (Chamber of Spirit and Time)
- **Automated Link Farming:** Executes continuous runs of the dedicated *"1. Saiyan Training"* stage on SUPER difficulty.
- **Smart Team Cycling (Auto-Swap):** When a character reaches Level 10 across all links, the bot detects it, opens the character selection menu, automatically applies the *"Released"* and *"Level Up Possible"* filters, and swaps in a fresh character to level up.
- **Boost & Stamina Management:** Optional Boost charge consumption and automated stamina depletion detection.

### 🤖 Remote Control via Integrated Discord Bot
- **1-Minute Setup Wizard:** Configure your Bot Token and Channel ID effortlessly from the interactive console with `discord setup` or `--discord`.
- **Remote Slash Commands:** Control and monitor the bot from any authorized Discord channel using `/status`, `/screenshot`, `/eza`, `/link`, `/stop`, `/pause`, `/resume`, and `/scrcpy`.
- **Live Screen Capture:** Requests real-time high-resolution screenshots of the phone display directly in Discord chat.

### 🖥️ Interactive CLI Console & System Diagnostics
- **Rich Terminal Interface:** Real-time colored logs, structured data tables, and live farming progress metrics.
- **Diagnostic Suite (`--doctor`):** Immediate verification of ADB binaries, Scrcpy installation, and connected Android devices (USB / Wi-Fi).
- **Zero-Latency Screen Mirroring:** Stream real-time gameplay directly to your desktop via Scrcpy using the `scrcpy` command.

### 🌐 Multi-Language Support (EN / IT)
- Fully bilingual console interface and documentation (English and Italian), switchable on the fly with `lang en` / `lang it` or the `--lang` flag.

### 📦 Standalone Zero-Dependency Executables
- Pre-compiled standalone distributions for **Windows (x64)**, **macOS (Apple Silicon & Intel)**, and **Linux (x64)**.
- No need to install Python, OpenCV, or external dependencies.
- 1-click desktop launchers: `Launch-Dokkan-EZALink.bat` (Windows), `Launch-Dokkan-EZALink.command` (macOS), or `Launch-Dokkan-EZALink.sh` (Linux).

---

## 📥 Quick Start

1. Download the zip archive corresponding to your operating system from the **Assets** below:
   - **Windows:** `dokkan-eza-link-windows-x64.zip`
   - **macOS:** `dokkan-eza-link-macos.zip`
   - **Linux:** `dokkan-eza-link-linux-x64.zip`
2. Extract the archive onto your computer.
3. Connect your Android smartphone with USB Debugging enabled (or start your Android emulator).
4. Double-click the launcher for your OS:
   - On Windows: `Launch-Dokkan-EZALink.bat` (or `dokkan-eza-link.exe`)
   - On macOS: `Launch-Dokkan-EZALink.command`
   - On Linux: `Launch-Dokkan-EZALink.sh`
5. To configure Discord: type `discord setup` inside the interactive console or launch with `--discord`.

---

**Full Changelog**: https://github.com/SolaneHub/Dokkan-EZALink-Farmer/commits/v1.0.0
