#!/usr/bin/env python3
"""Memory system launcher."""
import sys
import os
from pathlib import Path

# Add memory lib to path
MEMORY_LIB = Path.home() / "dev" / "ideas" / "huh" / "memory" / "lib"
sys.path.insert(0, str(MEMORY_LIB))

from cli import main

if __name__ == "__main__":
    main()
