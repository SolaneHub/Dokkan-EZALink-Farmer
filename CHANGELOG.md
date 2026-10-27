# Changelog

## [v2.0.0] - 2026-10-28

### Added
- **AI Tactical Engine Overhaul (i.solver, i.synergy)**: Realistic multi-slot combat damage simulation taking pre-attack vs post-attack defense into account. Cards suffering lethal unmitigated damage (>700k against 2.5M-3.5M boss Super Attacks) are strictly disqualified from Slot 1.
- **Post-10th Anniversary Mechanics & Tactical Dictionary (i.passive_parser, i.dokkandb_parser, i.card_heuristics)**:
  - Full passive skill deconstruction extracting unconditional vs timed guard, pre-attack-only damage reduction, on-hit damage reduction, and Ki-dependent defensive thresholds.
  - Evaluation of active skills, standbys, domain fields, and transformation timelines.
  - Offline dataset and extraction tools (data/dokkan_cards_post_10th_anniversary.json, data/dokkan_tactical_dictionary.json, data/cards_tactical_matrix.json, data/damage_simulation_benchmarks.json).
- **Tactical Rich Briefing & Terminal UI (ui.formatters, ui.briefing, ui.cli)**:
  - Enhanced Rich tables detailing rotation assignments (Slot 1 Tank vs Slot 2 DPS vs Floater).
  - Clear visual warnings for lethal floater vulnerabilities and pre-attack-only damage reduction dependencies.
  - Fully updated English and Italian localization bundles (locales/en.yaml, locales/it.yaml).
- **Unified Quality Gate CLI (scripts/quality_gate.py)**:
  - Standardized developer toolchain executing 
uff (lint & format), pyright (strict static typing), and pytest across dual-granularity tiers (--fast sub-20s, --full comprehensive pre-release matrix).
  - PyInstaller configuration (uild_exe.py) updated with hidden imports for all new AI tactical modules.

## [v1.9.0] - 2026-10-25

### Added
- **On-Hit Defense & Pre-Attack Mitigation Engine (`ai.synergy`, `ai.syncer`)**: Native detection of passive mechanics activating upon hit. Disqualifies glass cannons from Slot 1, routing them to Slot 2/3 where Super Attacks safely raise DEF before impact.
- **AI Domain Model Decoupling (`ai.boss_models`, `ai.card_models`)**: Decomposed monolithic 1850-line `models.py` into dedicated high-cohesion modules while maintaining full backwards compatibility via facade re-exports.
- **Isolated Stage Farm Integration Harness (`tests/test_stage_farm_integration.py`)**: Extracted slow synthetic ADB loop verification into dual-granularity slow tier, keeping unit test suite strictly under 3 seconds.
- **Declarative Headless CLI Task Orchestration (`__main__`, `ui.cli`)**: Seamless execution of automated tasks (`--eza`, `--link`, `--stage`, `--scan-box`, `--challenge`) with non-blocking lifecycle monitoring.

### Changed
- **Unified Canonical Test Runner (`scripts/test_runner.py`)**: Consolidated test execution into a single entry-point supporting both rapid developer feedback (`fast`) and full pre-release test matrix verification (`full`), eliminating redundant runner scripts (`fast_test.py`, `run_fast.py`).
- **DokkanDB Boss Category & Class Enrichment**: Enemy data parser now populates boss category names and Super/Extreme typing for exact conditional passive evaluations.
- **PyInstaller Modular Subsystem Bundling**: Configured standalone distribution script with complete AI subpackage hidden imports.

## [v1.8.0] - 2026-10-25

### Added
- **Bespoke DokkanDB Offline Fuzzer (`tools/fuzz_dokkandb_offline.py`)**: Lightweight, self-contained fault-injection testing engine validating network drop resilience, malformed JSON structures, and defensive parsing without heavy external frameworks.
- **ScanSessionContext Decoupling (`automation.scanner.session_context`)**: Encapsulated scan state, catalog cache, and screen positions into an immutable session context, completely isolating card registration from task instances.
- **Modular UI Component Architecture (`ui.panels`, `ui.briefing`, `ui.wizards`)**: Decomposed monolithic terminal CLI into dedicated presentation panels and interactive wizards, shrinking `TerminalCLI` to under 500 lines.
- **Modular AI Subsystems (`ai.synergy`, `ai.llm_advisor`, `ai.formatters`)**: Isolated rotation synergy heuristics, tactical LLM advisor prompting, and team presentation logic into dedicated single-responsibility packages.
- **Continuous Memory & Latency Vision Benchmarks (`tests/test_vision_performance.py`)**: Added a 200-cycle ADB screencap and template matching regression benchmark verifying sub-10ms ROI execution and zero unbounded heap growth.
- **Unified Canonical Test Runner (`scripts/test_runner.py`)**: Consolidated test execution into a single entry-point supporting both rapid developer feedback (`fast`) and full pre-release test matrix verification (`full`), eliminating redundant runner scripts (`fast_test.py`, `run_fast.py`).

### Changed
- **Thread-Safe Screencap Buffer Allocation**: Synchronized frame buffer reuse in `ADBClient` with thread lock protection.
- **Leader Parsing Defensiveness**: Hardened `parse_leader_spec` in `ai.syncer` against non-string headers and malformed category schemas.
- **Dual-Granularity Test Suite Marking**: Explicitly designated all heavy integration tests with `@pytest.mark.slow`, preserving strict sub-3s targets for fast feedback runs.

## [v1.7.0] - 2026-10-25
### Added
- **In-Memory Virtual Clock Test Harness (`tests/harness/fake_clock.py`)**: Intercepts `time.sleep`, `time.time`, and `time.monotonic` in integration tests, executing long asynchronous farm loops instantly without real-time CPU idle delays.
- **Generative Solver Fuzzing Tooling (`tools/fuzz_team_solver.py` & `tests/test_solver_fuzz.py`)**: Procedural fuzzing engine stressing `DokkanConstraintSolver` across randomized candidate pools and mission criteria to guarantee mathematical invariants (zero crashes, 6 distinct cards, full constraint satisfaction).
- **Canonical Telemetry Data Models & Serialization (`ai.models`)**: Centralized `FailureReport` dataclass and added full dictionary serialization (`to_dict` / `from_dict`) on `TeamRecommendation`.
- **End-to-End Black-Box TeamBuilder Verification (`tests/test_team_builder_blackbox.py`)**: Validates complete box-to-recommendation pipeline in isolation from internal scoring heuristics.

### Changed
- **Strict Rainbow (5-Typing) Solver Filtering**: Constraint solver now preemptively verifies that leader candidates cover all 5 elemental types when evaluating rainbow missions, immediately rejecting incomplete candidate pools.
- **Solver Degradation Contract**: Enforced explicit `ValueError` raising when candidate pools cannot satisfy hard mission constraints under a chosen leader.

### Removed
- **Legacy Grid Scanner & Obsolete Matching (`legacy_grid.py`)**: Dropped legacy grid mode, preloaded thumbnail matching, and coordinate shifting in favor of streamlined detail swipe scanning (`scan_detail_screen`).
- **Deprecated AI Backward-Compatibility Shims**: Purged top-level alias shims (`ai/telemetry.py`, `ai/endgame_runner.py`, `ai/endgame/endgame_runner.py`) in favor of canonical `dokkan_eza_link_farmer.ai.endgame`.

## [v1.6.0] - 2026-10-25
### Added
- **Full-Stage Multi-Phase Survivability Heuristics**: Constraint solver now evaluates elemental matchups across all constituent phases and battles, preventing teams that fold in Phase 1 before building defensive stacks.
- **Chronological Phase-by-Phase AI Tactical Guidance**: Restructured local LLM system prompt into clear battle horizons (Turn 1 Opening Barrage, Mid-Phase Stacking & Transformations, Final Phase Boss Finisher).
- **Stage-Wide Survival Mandate**: TeamBuilder payload explicitly instructs the tactical advisor to reject glass cannons lacking early survivability.
- **Cross-Phase Transformation Horizons**: Fine-tuned turn thresholds aligning transforming forms (min_turn <= 3 vs min_turn >= 4) with appropriate battle phases.

## [v1.5.0] - 2026-10-24

### Added
- **Multi-Enemy & Rainbow Boss Phase Architecture**: Native recognition of multi-target battles, rainbow phases (all 5 typings), and cumulative actions-per-turn calculation.
- **Tactical AoE & Debuff Heuristics**: Constraint solver weighting prioritizing AoE units (+25.0) and ATK debuffers (+15.0) in stages lacking status immunities.
- **Official DokkanDB Category Leader Integration**: Live parsing of category leader boost percentages (up to 220%) to enrich candidate viability.
- **Complementary Friend Leader & Rotation Consistency**: Intelligent friend selection algorithm guaranteeing core 200% titular units remain in primary rotations.
- **Rich Terminal Stage Briefing**: Auto-expanding tables for multi-enemy stage mechanics and distinct Friend Leader badge labeling.

### Changed
- **Boss Phase Typing Semantics**: Replaced placeholder typing with descriptive labels ('Rainbow (5 Enemies: All 5 Types)' or 'Multi-Type (N Enemies)').

## [v1.4.0] - 2026-10-24

### Added
- **AI Endgame Subsystem Isolation (`ai.endgame`)**: Decomposed monolithic endgame runner and combat telemetry into a self-contained subpackage with thread-safe lazy exports (`__getattr__`) and zero-import decoupling for core bot engines.
- **In-Memory DokkanDB Test Harness (`tests/harness/fake_dokkandb.py`)**: Authoritative, in-memory client and HTTP requests interceptor simulating DokkanDB catalogs, events, and stages with zero network latency.
- **Dual-Granularity Test Runner (`scripts/test_runner.py`)**: Cross-platform CLI runner enforcing sub-3s feedback loops for fast tests (`pytest -m fast`) and comprehensive matrices for pre-release verification (`pytest`).
- **Black-Box Synthetic Integration Tests**: Multi-stage regression suites for EZA climb loops (`EZAFarmTask`) and Link Leveling deck rebuilds (`LinkLevelFarmTask`) powered by synthetic screen generators.
- **Diagnostic Crop Dumps (`save_diagnostic_crops`)**: Automatic persistence of raw screen, banner, and level crops during scanner low-confidence OCR conditions (< 0.85).

### Changed
- **Scanner Schema Contract Hardening**: Enforced normalized `title`, `rainbow`, `leader_skill`, and `categories` defaults across all serialized card dictionaries.
- **CI/CD Optimization**: Streamlined PR/push CI on fast tests (< 3s) while gating release builds behind the complete multi-OS test matrix.

## [v1.3.0] - 2026-10-24

### Added
- **Multi-Battle Stage Architecture**: Native ingestion of sugoroku type 301 events and complete boss phase combat telemetry (HP, ATK, DEF, actions per turn).
- **Curated Tier-1 Support Catalog**: Priority ranking for Whis (40% DR), Ghost Usher, Icarus, and permanent support memories matching team categories.
- **Nuanced Tactical Solver**: Stacking reset awareness across separate battles (-20.0 penalty / +15.0 Turn-1 shield bonus), defensive expiration rules for long fights, and -60.0 glass cannon penalty against Cancels Dodge bosses.
- **Local AI Unification**: Consolidated on local Qwen 3.5 4B with 8K context and zero-latency inference (thinking tokens disabled).
- **7-Unit Dynamic Rotations & Stage Intel CLI**: Rich terminal tables showing stage structure, stacking warnings, and role-badged rotations.

---

All notable changes to **Dokkan-EZALink-Farmer** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.2.0] - 2026-10-24

### Added
- **Synthetic Box Scanner Test Harness (`tests/harness/`)**: Fully simulated in-memory ADB and synthetic card rendering frames for reproducible offline testing without physical devices.
- **Selective Memory Telemetry Freezing**: Disabled observation frame accumulation in long-running farming tasks (EZA 999, link leveling) by default, with `--debug-telemetry` CLI flag for on-demand debugging.
- **Live Box Scanner Diagnostic Tool (`scripts/self_improve_scanner.py`)**: Real-time diagnostic script for ADB box scans with automated debug crop dumps.

### Changed
- **Decomposed Box Scanner Architecture**: Monolithic `box_scanner.py` modularized into domain subpackages (`banner_extractor`, `detail_evaluator`, `catalog_matcher`, `box_storage`, `card_registry`, `filter_manager`, `swipe_controller`), maintaining complete backwards compatibility via `__all__`.
- **Vision Prior Vertical ROI Optimization**: Accelerated template matching on tall aspect ratios (>=1600px) with deterministic vertical search windows and C-contiguous zero-overhead OpenCV processing.
- **ADB Screencap Preallocated Frame Buffer**: Reused contiguous byte buffers across screenshot captures, eliminating GC overhead in fast polling loops.
- **Discord Bot Decoupling**: Lazy-loaded Discord dependencies and wrapped notification callbacks to prevent event loop teardown exceptions from interrupting automation.

---

## [v1.1.1] - 2026-10-19

### Added
- **Manual Stage Auto-Clear until Stamina Depleted (`StageFarmTask`)**:
  - Automatically loops through a manually selected stage in Dokkan Battle until stamina is completely exhausted.
  - Seamless state detection across `STAGE_SELECT`, `FRIEND_SELECT`, `TEAM_CONFIRM`, `MAP_SCREEN`, `BATTLE_SCREEN`, and `RESULTS_SCREEN`.
  - Integrates fast-replay via 'Attempt Again' (Ripeti) and automatically confirms the stamina consumption modal dialog.
  - Terminates cleanly upon encountering `GameState.STAMINA_EMPTY` (Restore STA popup), dismissing the modal without consuming Dragon Stones or Meat.
  - Supports optional maximum runs target (e.g. `stage 10`) and Boost energy toggle (`--boost` / `--no-boost`).
  - Added interactive CLI command `stage` / `farm` (`stage`, `farm`, `repeat`, `clear`).
  - Added standalone CLI flags `--stage [N]` and `--farm [N]`.
  - Added Discord slash command `/stage [runs] [boost]`.
  - Full bilingual localization (English & Italian) and unit test coverage (`tests/test_stage_farm.py`).

---

## [v1.1.0] - 2026-10-02

### Added
- **Autonomous Character Box Scanner (`BoxScannerTask`)**:
  - **On-Device RapidOCR Title Recognition**: Automatically reads card epithets/subnames (e.g. *[Warrior Beyond the Limits]*) directly from character icon thumbnails with zero cloud latency.
  - **Calibrated Physical Row Pitch & Dynamic Micro-Alignment**: Exact `253.0px` row spacing combined with visual anchor matching eliminates pixel drift, guaranteeing zero missed or duplicate cards across hundreds of swipe cycles.
  - **Multi-Anchor Shift Tracking**: Top-row and mid-row anchor persistence to flawlessly stitch rows across swipe boundaries.
  - **Rainbow Star & Copy Tracking**: Chromatic HSV/RGB color analysis reliably detects 100% Hidden Potential rainbow stars and tracks multiple character copies.
  - **Skin & Special Effect Tolerance**: Custom crop isolation and title masking to cleanly recognize cards with animated backgrounds, corner effects (blue, red, pink, rainbow), and Survival Passive frames.
  - **DokkanDB Metadata & Partner Enrichment**: Fetches card IDs, typing, leader skills, passives, categories, link skills, and top linking partner synergies with HTTP 429 exponential backoff retry into `config/box.json`.
  - **CLI Command `--scan-box`**: New command (`--scan-box [N]` or `scan-box` in interactive console) to scan and enrich character boxes autonomously.
- **AI Strategy, Rotation Optimizer & Team Builder Engine (`dokkan_eza_link_farmer.ai`)**:
  - **Multi-Provider LLM Integration**: Support for DeepSeek (R1/V3) and Qwen (2.5) with `<think>` tag extraction and robust fallback to heuristic algorithmic solvers.
  - **Slot 1 Tank Detection & Rotation Optimizer**: Evaluates guard, damage reduction, DEF stacking, dodge, and Ki links to generate optimal main rotations (Slots 1 & 2) and floaters (Slot 3).
  - **Mission Solver & Bundler**: Automatically parses event mission constraints (e.g. Category restrictions, Rainbow typing, itemless clears) and compiles teams from the player's scanned `config/box.json`.
  - **Challenge Task (`ChallengeTask`)**: Automates mission team synthesis and deployment for endgame challenge events.
- **Unified Testing & Quality Assurance**:
  - Unified test suite in `tests/test_box_scanner.py` (7 comprehensive tests) and `tests/test_ai.py` (11 tests).
  - Formal `rapidocr-onnxruntime>=1.3.0` dependency added to `pyproject.toml`.

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
