# Changelog

All notable changes to **Dokkan-EZALink-Farmer** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.0.5] - 2026-09-30

### Added
- **Multi-Stage Link Leveling with Interactive Dropdown**: Added interactive dropdown selection (via `questionary.select` in CLI and choice options in Discord) for Link Level farming locations:
  - *Area 39 Stage 3*: Great stamina-friendly option (also drops green gems) | 5 fights (`area_39_3`).
  - *Area 35 Stage 1*: Good stamina-friendly option (also drops blue gems) | 4 fights (`area_35_1`).
  - *Chamber of Spirit and Time*: Daily event (`spirit_and_time`).
- **Cumulative Card Rarity Flags (`--ur` & `--lr`)**: Added support for combinable CLI and Discord rarity flags (`--ur`, `--lr`, `--ur --lr`, defaulting to both UR+LR when omitted) to target unmaxed cards.
- **Native "Attempt Again" Fast-Looping**: Extracted and integrated high-fidelity `button_attempt_again.png` template (red button at left coordinates `~304, 2045`). Updated `find_attempt_again_button` and `dismiss_results_and_popups` to click "Attempt Again" and confirm the stamina consumption modal (`Please Confirm`), restarting stages directly on `TEAM_CONFIRM` without returning to menus.
- **Area 39 & Area 35 Unique Badge/Title Templates**: Generated high-contrast templates for Area 39 (`badge_area_39.png`, `stage_area39_3.png`) and Area 35 (`badge_area_35.png`, `stage_area35_1.png`), eliminating visual octagon collisions between Quest areas.

### Changed
- **Single-Setup Filter Optimization**: In `rebuild_team_from_box`, box filters (*Released*, *UR/LR*, and *Level Up Possible*) are now configured and verified **only on the very first run (Run 1)**. From Run 2 onwards, the bot skips the filter menu entirely and immediately clears and populates cards from the already-filtered box.
- **Quest Story Navigation Engine**: Added dynamic multi-scroll handling for Area 35 (2-swipe stage list scroll to reveal Stage 1) and carousel-vs-list discrimination for Chapter 6.

### Fixed
- **Infinite "Advancing stage selection..." Loop**: Adjusted `find_chapter_6` matching threshold from `0.95` to `0.82` (matching rendered font at `0.88`), preventing the bot from falling into `UNKNOWN` fallback tap loops.
- **Clear Screen Button Geometry**: Corrected `find_attempt_again_button` geometry assumption (Dokkan places "Attempt Again" on the left `~0.28 * W` and "OK" on the right `~0.72 * W`).

---

## [v1.0.4] - 2026-09-28

### Added
- **Dragon Ball Z Dokkan Battle AAA Panoramic Hero Banner**: High-resolution 16:9 visual header featuring Ultra Instinct Goku, Shenron, and holographic HUD telemetry for Link Skill Farming and EZA Lv. 999 (`docs/github/official_banner.png`).
- **Comprehensive Contextual Documentation**: Overhauled `README.md` with complete Dokkan Battle context: Rich terminal dashboard, zero-latency Scrcpy screen mirroring, Discord slash command bot control, detailed automation matrix, and antivirus transparency analysis.
- **Single-Instance Mutex & Process Environment Isolation**: Integrated `SingleInstanceMutex` and runtime environment sanitization in `core/system_tools.py` and `core/updater.py` to prevent multi-instance ADB socket collisions and eliminate PyInstaller `_MEIPASS` variable leakage in child subprocesses.
- **Community Health & Security Infrastructure**: Added GitHub Issue forms (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `config.yml`), `PRIVACY.md` (guaranteeing 100% local execution and zero telemetry), `TERMS.md` (disclaimer of non-affiliation with Bandai Namco/Akatsuki), and `SECURITY.md`.
- **Standalone Distribution Builder**: Introduced clean standalone build pipeline `build_exe.py` targeting `Launch-Dokkan-EZALink.exe` with bundled internal assets.

### Changed
- **Modular Packaging Refactor (`src/dokkan_eza_link_farmer/`)**: Migrated flat legacy project structure to standard PEP 517/518/621/660 `src/` layout under the package name `dokkan_eza_link_farmer` with Hatchling backend.
- **Root Asset Consolidation**: Relocated all template images, localization catalogs (`en.yaml`, `it.yaml`), and configuration files into `src/dokkan_eza_link_farmer/assets/`, eliminating legacy root duplicates.
- **Streamlined Entrypoint**: Refactored `main.py` into a lightweight, robust 10-line runner delegating execution directly to `dokkan_eza_link_farmer.__main__:main`.
- **Strict Quality Toolchain**: Enforced strict Ruff linting rules (`E`, `W`, `F`, `I`, `B`, `UP`, `SIM`, `ARG`) with `line-length = 100` and Pyright standard mode with 0 errors and 0 warnings.
- **License Clarification**: Updated `LICENSE` to MIT License with explicit author attribution requirement (SolaneHub).

### Fixed
- **Circular Import Elimination**: Implemented PEP 562 dynamic lazy-loading in `core/__init__.py` and reordered `GameState` enum definitions to resolve circular imports between vision and bot engine modules.
- **Asset Filtering in `.gitignore`**: Corrected asset whitelist patterns to track template PNG images inside `src/dokkan_eza_link_farmer/assets/`.
- **DokkanDB Live Event Rotation Test**: Updated test assertion in `tests/test_link_leveling.py` to gracefully handle server-side event rotation and expiration dates.

---

## [v1.0.3] - 2026-09-25

### Added
- **Modern Package Management with `uv`**: Full project modernization introducing universal lockfile `uv.lock` and Python version pinning via `.python-version` (`3.11`).
- **PEP 735 Dependency Groups**: Standardized developer tooling (`pytest`, `ruff`, `pyright`, `pyinstaller`) under `[dependency-groups]`.
- **Automated CI Workflow**: Introduced `.github/workflows/ci.yml` running format checks, linter, type checks, and pytest on push and pull requests.
- **CI/CD Supply Chain Security & Attestation**: Release workflow now generates cryptographic `SHA256SUMS.txt`, signs build artifacts with Sigstore provenance (`actions/attest-build-provenance`), performs automated VirusTotal antivirus scans (`crazy-max/ghaction-virustotal`), and embeds verification commands directly into GitHub release notes.
- **VS Code Terminal Auto-Activation**: Configured `.vscode/settings.json` to automatically activate the project virtual environment with custom prompt prefix `(dokkan-eza-link-farmer)`.

### Changed
- **Build Backend Migration to `hatchling`**: Replaced legacy `setuptools` with `hatchling` (PEP 517/518/621/660) in `pyproject.toml`, eliminating obsolete `*.egg-info` generation.
- **Pre-Build Quality Gate**: Enforced strict pre-build validation in release pipeline ensuring builds fail if formatting, linting, or type checking is not clean.
- **Cleaned `.gitignore`**: Removed legacy virtualenv patterns, unused tool caches, and obsolete packaging artifacts while keeping essential configuration files tracked.
- **CLI Commands Documentation**: Updated `README.md` to feature direct execution via `uv run dokkan-farmer`.

### Fixed
- **Linter & Formatting Conformance**: Configured `ruff` with rules `E`, `W`, `F`, `I`, `UP`, `B`, `SIM`, and `ARG`, addressing unused arguments and simplifying conditional blocks across tasks and engine modules.

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
