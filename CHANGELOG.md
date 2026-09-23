# Changelog

All notable changes to **Dokkan-EZALink-Farmer** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.0.2] - 2026-09-23

### Added
- **1-Click Launchers**: Standardized desktop launchers across all platforms named `Launch-Dokkan-EZALink` (`Launch-Dokkan-EZALink.bat` on Windows, `Launch-Dokkan-EZALink.command` on macOS, and `Launch-Dokkan-EZALink.sh` on Linux).
- **macOS Gatekeeper Auto-Unquarantine**: `Launch-Dokkan-EZALink.command` now automatically strips the `com.apple.quarantine` attribute when downloaded via browser, preventing `dlopen` library load security errors.
- **Discord Setup Wizard Strings**: Added complete bilingual localization catalogs (English and Italian) for the interactive Discord setup wizard and link leveling status messages.

### Changed
- **Windows Standalone Distribution**: Standardized distribution packaging with complete zero-dependency PyInstaller standalone runtime and desktop launcher.
- **Release Naming**: GitHub release titles now display the clean version tag directly (e.g., `v1.0.2`), preventing version number truncation in repository release lists and sidebar.

### Fixed
- **Type Annotations & Diagnostics**: Full codebase type safety pass with zero errors on `pyright` and `ruff`, improving reliability across ADB client, DokkanDB client, game state, and CLI interfaces.

---

## [v1.0.1] - 2026-09-22

### Fixed
- **Localization**: Added missing Italian and English translation strings for post-stage advancement (`tasks.stage.post_stage_advance`) and screencap errors (`tasks.stage.screencap_error`).
- **Log output**: Cleaned up repetitive raw fallback log messages during end-of-stage reward/rank-up sequences in Link Level Farm.

---

## [v1.0.0] - 2026-09-21

### Added
- **Extreme Z-Battle (EZA) Auto-Climber**:
  - Continuous automated climbing of EZA events up to Level 999.
  - Infinite Zeni grinding via Platinum Hercule Statues past Level 30.
  - Intelligent handling of defeat, victory, friend supporters, and network popups.
- **Link Level Grinder (Chamber of Spirit and Time)**:
  - Automated continuous farming of the *"1. Saiyan Training"* event.
  - Smart Team Cycling (**Auto-Swap**): Automatically replaces units that have maxed all links (Lv. 10) by applying in-game box filters (*Released* & *Level Up Possible*).
  - Boost charge activation support and stamina refill modes.
- **Integrated Discord Bot**:
  - Remote monitoring and slash command control (`/status`, `/screenshot`, `/eza`, `/link`, `/stop`, `/pause`, `/resume`, `/scrcpy`).
  - Real-time high-resolution phone display screen captures sent directly to Discord chat.
- **CLI & Diagnostic Suite**:
  - Interactive colored terminal dashboard.
  - Built-in `--doctor` environment diagnostics (ADB, Scrcpy, connected devices).
  - Zero-latency desktop screen mirroring with Scrcpy.
- **Bilingual Localization**:
  - Full English and Italian support switchable via `--lang` or live `lang` command.
- **Cross-Platform Standalone Builds**:
  - Automated standalone distributions for Windows (x64), macOS (Apple Silicon/Intel), and Linux (x64) via GitHub Actions.
