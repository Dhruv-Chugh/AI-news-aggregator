"""CLI entry point for AI News Aggregator."""

import sys
from pathlib import Path

# Ensure app package is importable
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from app.scrapers.runner import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
