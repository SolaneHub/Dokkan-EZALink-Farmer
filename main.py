import sys
from pathlib import Path

# Add src to sys.path for direct execution from repository root
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dokkan_eza_link_farmer.__main__ import main

if __name__ == "__main__":
    main()
