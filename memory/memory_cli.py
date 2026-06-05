#!/usr/bin/env python3
"""Memory system launcher."""
import sys
from pathlib import Path

# Resolve lib relative to THIS file so the launcher works wherever the repo lives
# (the old hardcoded absolute path only worked on the original author's machine).
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from cli import main

if __name__ == "__main__":
    main()
