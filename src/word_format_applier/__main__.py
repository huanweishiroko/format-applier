"""``python -m word_format_applier`` entry point."""

from __future__ import annotations

import os
import sys

# Allow running straight from a checkout (``python -m word_format_applier`` with
# PYTHONPATH=src, or ``python src/word_format_applier``).
if __package__ in (None, ""):  # pragma: no cover - direct script execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
