# Privacy Policy

**Effective Date:** September 2026  
**Project:** Dokkan-EZALink-Farmer (`Dokkan-EZALink-Farmer`)  
**Maintainer:** SolaneHub  

---

## 1. Overview
This Privacy Policy outlines how the **Dokkan-EZALink-Farmer** automation companion application ("the Software") interacts with your system, connected Android devices, and Discord. We are committed to complete privacy and transparency.

## 2. Zero Data Collection & Storage
- **No Personal Data Collected**: The Software does **not** collect, store, transmit, or harvest any personal information, credentials, Dokkan Battle account transfer codes, passwords, or personal files.
- **No External Telemetry or Tracking**: The Software does not include third-party tracking scripts, analytics libraries, or telemetry beacons.
- **100% Local Execution**: All computer vision detection, ADB communication, template matching, and game automation occur strictly within your local computer's memory and disk.

## 3. Communication with ADB & Android Devices
The Software communicates exclusively with your locally connected Android device or local emulator instances via standard Android Debug Bridge (ADB) loopback sockets (`127.0.0.1:5555`, etc.) or USB debug tunnels.
- Screen capture buffers (`screencap`) are processed in volatile memory for UI state detection and immediately discarded.
- No screenshots or game assets are uploaded to any external server.

## 4. Communication with Discord (Optional)
If you enable the optional Discord Bot integration:
- Only in-game status updates (completed run counts, current state, and diagnostic screencap commands issued by authorized users) are transmitted to your configured Discord channel via the Discord Gateway API.
- No unauthorized messages, friend lists, or server data are accessed or stored.

## 5. GitHub Releases & Update Checks
If update checks are requested, the Software queries the public GitHub REST API (`https://api.github.com/repos/SolaneHub/Dokkan-EZALink-Farmer/releases/latest`) solely to compare the local version string against the latest published release tag. No user identifiers or machine fingerprints are transmitted.

## 6. Contact & Questions
For any questions regarding this policy or the software's privacy architecture, please open an issue or inquiry on the official repository:  
[GitHub Repository - SolaneHub/Dokkan-EZALink-Farmer](https://github.com/SolaneHub/Dokkan-EZALink-Farmer)
