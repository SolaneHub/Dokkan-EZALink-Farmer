# Changelog

All notable changes to **Dokkan-EZALink-Farmer** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
