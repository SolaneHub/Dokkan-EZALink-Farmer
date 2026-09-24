#!/usr/bin/env python3
"""
Extracts release notes for a specific version tag from CHANGELOG.md
and formats them for GitHub Releases.
"""

import argparse
import re
from pathlib import Path

DEFAULT_TEMPLATE = """# ⚡ Dokkan-EZALink-Farmer {tag}

{content}

---

### 📥 Downloads & Assets
Download the package for your operating system from the **Assets** section below:
- **Windows:** `dokkan-eza-link-windows.zip`
- **macOS:** `dokkan-eza-link-macos.zip`
- **Linux (x64):** `dokkan-eza-link-linux-x64.zip`
- **Checksums:** `SHA256SUMS.txt`
{verification_block}
---

📖 **Full Changelog**: See [CHANGELOG.md](https://github.com/SolaneHub/Dokkan-EZALink-Farmer/blob/main/CHANGELOG.md) for complete version history.
"""

FALLBACK_TEMPLATE = """# ⚡ Dokkan-EZALink-Farmer {tag}

Release {tag}. For a detailed list of all historical changes and updates, please refer to the complete changelog.

---

### 📥 Downloads & Assets
Download the package for your operating system from the **Assets** section below:
- **Windows:** `dokkan-eza-link-windows.zip`
- **macOS:** `dokkan-eza-link-macos.zip`
- **Linux (x64):** `dokkan-eza-link-linux-x64.zip`
- **Checksums:** `SHA256SUMS.txt`
{verification_block}
---

📖 **Full Changelog**: See [CHANGELOG.md](https://github.com/SolaneHub/Dokkan-EZALink-Farmer/blob/main/CHANGELOG.md).
"""


def format_verification_block(checksums_path: Path | None) -> str:
    """Builds cryptographic checksums and build provenance verification block."""
    if not checksums_path or not checksums_path.is_file():
        return ""

    checksums_content = checksums_path.read_text(encoding="utf-8").strip()
    return f"""
---

### 🔒 Cryptographic Checksums (SHA-256)
Integrity hashes for package verification:
```text
{checksums_content}
```

#### Verification Commands:
- **Linux:** `sha256sum -c SHA256SUMS.txt`
- **macOS:** `shasum -a 256 -c SHA256SUMS.txt`
- **Windows (PowerShell):** `Get-FileHash dokkan-eza-link-windows.zip -Algorithm SHA256`

---

### 🛡️ Supply Chain Security & Build Provenance
All build artifacts include cryptographic build provenance attested by GitHub Actions with **Sigstore**.
Verify artifact provenance with the GitHub CLI:
```bash
gh attestation verify <asset-filename> --owner SolaneHub
```"""


def extract_notes(changelog_path: Path, tag: str, checksums_path: Path | None = None) -> str:
    """Extracts notes for the given tag from CHANGELOG.md."""
    verification_block = format_verification_block(checksums_path)

    if not changelog_path.exists():
        return FALLBACK_TEMPLATE.format(tag=tag, verification_block=verification_block)

    text = changelog_path.read_text(encoding="utf-8")

    # Clean version string (e.g. 'v1.0.1' -> ['v1.0.1', '1.0.1'])
    v_clean = tag.strip().lstrip("v")
    possible_versions = [tag.strip(), v_clean, f"v{v_clean}"]

    # Pattern matching: ## [v1.0.1] or ## [1.0.1] or ## v1.0.1 or ## 1.0.1
    # followed by anything until next ## [ or ## v or EOF
    header_pattern = re.compile(
        r"^##\s+\[?(" + "|".join(map(re.escape, possible_versions)) + r")\]?.*$", re.MULTILINE | re.IGNORECASE
    )
    match = header_pattern.search(text)

    if not match:
        return FALLBACK_TEMPLATE.format(tag=tag, verification_block=verification_block)

    start_pos = match.end()

    # Find the start of the next release heading (e.g. ## [ or ## v)
    next_header_pattern = re.compile(r"^##\s+\[?[vV]?\d+\.\d+", re.MULTILINE)
    next_match = next_header_pattern.search(text, pos=start_pos)

    content = text[start_pos : next_match.start()].strip() if next_match else text[start_pos:].strip()

    # Strip any trailing '---' divider
    content = re.sub(r"(\r?\n\s*---\s*)+$", "", content).strip()

    if not content:
        return FALLBACK_TEMPLATE.format(tag=tag, verification_block=verification_block)

    return DEFAULT_TEMPLATE.format(tag=tag, content=content, verification_block=verification_block)


def main():
    parser = argparse.ArgumentParser(description="Extract release notes from CHANGELOG.md for a given tag.")
    parser.add_argument("tag", help="Release tag (e.g., v1.0.1)")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Path to CHANGELOG.md (default: CHANGELOG.md)")
    parser.add_argument(
        "--output", "-o", default="release_notes.md", help="Output file path (default: release_notes.md)"
    )
    parser.add_argument(
        "--checksums", default=None, help="Path to SHA256SUMS.txt to include in release notes (optional)"
    )

    args = parser.parse_args()

    changelog_path = Path(args.changelog)
    checksums_path = Path(args.checksums) if args.checksums else None
    notes = extract_notes(changelog_path, args.tag, checksums_path=checksums_path)

    out_path = Path(args.output)
    out_path.write_text(notes, encoding="utf-8")
    print(f"Extracted release notes for {args.tag} -> {out_path} ({len(notes)} bytes)")


if __name__ == "__main__":
    main()
