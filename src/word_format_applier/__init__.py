"""word_format_applier - apply Word formatting rules to a .docx without touching text.

Public entry points::

    from word_format_applier import apply_format, list_presets, parse_format_source

The package never calls an LLM unless the caller opts in through
``llm_fallback_enabled=True`` *and* the deterministic text parser fails.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "apply_format",
    "parse_format_source",
    "list_presets",
    "resolve_preset",
    "Applier",
    "FormatError",
]


def __getattr__(name):  # lazy re-exports keep `import word_format_applier` cheap
    if name in ("apply_format", "FormatError"):
        from . import applier

        return getattr(applier, name)
    if name in ("parse_format_source",):
        from . import parser

        return getattr(parser, name)
    if name in ("list_presets", "resolve_preset", "PresetError"):
        from . import presets

        return getattr(presets, name)
    if name == "Applier":
        from .applier import Applier

        return Applier
    raise AttributeError(name)
