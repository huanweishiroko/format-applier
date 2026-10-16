"""Preset discovery, ``format_source`` resolution and the parse cache.

Layout (fixed, no code change needed when new presets arrive)::

    presets/
      <name>.docx | <name>.txt | <name>.md
      .cache/            # generated: parsed rules + apply-cache, keyed by file hash

``format_source`` accepts three spellings:

* a path                     -> ``./samples/我的格式.docx``
* a preset name              -> ``格式要求1``
* an explicit preset         -> ``preset:格式要求1``

Resolution order: existing path first, then the preset table; on a preset name
collision ``.docx`` wins over ``.txt`` over ``.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from . import docxio
from . import schema as ruleschema

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PRESETS_DIR = os.path.join(PLUGIN_ROOT, "presets")
CACHE_DIRNAME = ".cache"

PRESET_EXTENSIONS = (".docx", ".txt", ".md")
#: lower index wins when two presets share a name.
EXTENSION_PRIORITY = {".docx": 0, ".txt": 1, ".md": 2}

PRESET_PREFIX = "preset:"


class PresetError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #

def presets_dir(presets_dir_arg: Optional[str] = None) -> str:
    return os.path.abspath(presets_dir_arg or os.environ.get("WORD_FORMAT_PRESETS_DIR")
                           or DEFAULT_PRESETS_DIR)


def cache_dir(presets_dir_arg: Optional[str] = None) -> str:
    return os.path.join(presets_dir(presets_dir_arg), CACHE_DIRNAME)


def ensure_cache_dir(presets_dir_arg: Optional[str] = None) -> str:
    path = cache_dir(presets_dir_arg)
    os.makedirs(path, exist_ok=True)
    return path


def list_preset_entries(presets_dir_arg: Optional[str] = None) -> List[Dict[str, Any]]:
    """Scan ``presets/`` (never any other plugin directory)."""
    folder = presets_dir(presets_dir_arg)
    entries: List[Dict[str, Any]] = []
    if not os.path.isdir(folder):
        return entries
    for filename in sorted(os.listdir(folder)):
        if filename.startswith("."):
            continue
        full = os.path.join(folder, filename)
        if not os.path.isfile(full):
            continue
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in PRESET_EXTENSIONS:
            continue
        entries.append({
            "name": stem,
            "filename": filename,
            "path": full,
            "ext": ext.lower(),
            "size": os.path.getsize(full),
        })
    entries.sort(key=lambda item: (item["name"], EXTENSION_PRIORITY.get(item["ext"], 9)))
    return entries


def list_presets(presets_dir_arg: Optional[str] = None) -> List[str]:
    """Preset names, deduplicated (the winning file is the one used)."""
    names: List[str] = []
    for entry in list_preset_entries(presets_dir_arg):
        if entry["name"] not in names:
            names.append(entry["name"])
    return names


def preset_table(presets_dir_arg: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    table: Dict[str, Dict[str, Any]] = {}
    for entry in list_preset_entries(presets_dir_arg):
        table.setdefault(entry["name"], entry)
    return table


def resolve_preset(name: str, presets_dir_arg: Optional[str] = None) -> Dict[str, Any]:
    """Exact preset name -> entry. Never guesses, never walks the disk."""
    clean = (name or "").strip()
    if clean.lower().startswith(PRESET_PREFIX):
        clean = clean[len(PRESET_PREFIX):].strip()
    if not clean:
        raise PresetError("empty preset name")
    directory = presets_dir(presets_dir_arg)
    candidates = [
        os.path.join(directory, clean + ext) for ext in PRESET_EXTENSIONS
    ]
    for candidate in sorted(candidates, key=lambda p: EXTENSION_PRIORITY.get(os.path.splitext(p)[1].lower(), 9)):
        if os.path.isfile(candidate):
            return {
                "name": clean,
                "path": candidate,
                "filename": os.path.basename(candidate),
                "ext": os.path.splitext(candidate)[1].lower(),
            }
    available = list_presets(presets_dir_arg if presets_dir_arg is not None else None)
    listing = ", ".join(available) if available else "(none found in %s)" % directory
    raise PresetError(
        "preset %r not found in %s; available presets: %s" % (clean, directory, listing)
    )


# --------------------------------------------------------------------------- #
# format_source resolution
# --------------------------------------------------------------------------- #

def resolve_format_source(format_source: str,
                          *,
                          cwd: Optional[str] = None,
                          presets_dir_arg: Optional[str] = None,
                          source_kind_hint: Optional[str] = None) -> Dict[str, Any]:
    """Classify ``format_source``; returns ``{kind, path|text, ...}``.

    ``kind`` is one of ``docx``, ``text``, ``preset_docx``, ``preset_text``.
    """
    raw = format_source if isinstance(format_source, str) else str(format_source or "")
    text = raw.strip()
    if not text:
        raise PresetError("format_source is empty")

    explicit_preset = text.lower().startswith(PRESET_PREFIX)
    candidate = text[len(PRESET_PREFIX):].strip() if explicit_preset else text

    looks_like_file = (not explicit_preset) and _looks_like_path(candidate)
    if looks_like_file:
        resolved = candidate if os.path.isabs(candidate) else os.path.join(cwd or os.getcwd(), candidate)
        resolved = os.path.abspath(resolved)
        if os.path.isfile(resolved):
            ext = os.path.splitext(resolved)[1].lower()
            kind = "docx" if ext == ".docx" else "text"
            return {"kind": kind, "path": resolved, "used_preset": None,
                    "resolved_by": "path", "explicit_preset": False}
        if not explicit_preset and _path_is_specific(candidate):
            raise PresetError("format file not found: %s" % resolved)

    entry = resolve_preset(candidate, presets_dir_arg)
    kind = "preset_docx" if entry["ext"] == ".docx" else "preset_text"
    return {
        "kind": kind,
        "path": entry["path"],
        "used_preset": entry["name"],
        "preset_file": entry["path"],
        "resolved_by": "preset",
        "explicit_preset": explicit_preset,
    }


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    ext = os.path.splitext(value)[1].lower()
    if ext in (".docx", ".txt", ".md", ".text", ".markdown"):
        return True
    return any(sep in value for sep in ("/", "\\")) or value.startswith(".")


def _path_is_specific(value: str) -> bool:
    """A path with a directory part or a known extension is a path, not a name."""
    ext = os.path.splitext(value)[1].lower()
    return ext in (".docx", ".txt", ".md", ".text", ".markdown") or any(
        sep in value for sep in ("/", "\\"))


def default_output_path(target_docx: str, output_docx: Optional[str], *, suffix: str = "_formatted") -> str:
    if output_docx:
        return os.path.abspath(output_docx)
    base, ext = os.path.splitext(os.path.abspath(target_docx))
    return "%s%s%s" % (base, suffix, ext or ".docx")


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #

def _cache_key(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:32]


def cache_read(namespace: str, key: str, presets_dir_arg: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = os.path.join(cache_dir(presets_dir_arg), "%s-%s.json" % (namespace, key))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def cache_write(namespace: str, key: str, payload: Dict[str, Any],
                presets_dir_arg: Optional[str] = None) -> Optional[str]:
    try:
        folder = ensure_cache_dir(presets_dir_arg)
    except OSError:
        return None
    path = os.path.join(folder, "%s-%s.json" % (namespace, key))
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError:
        return None
    return path


def parse_cache_key(path: str) -> str:
    # The ruleset version participates in the key: a parser change that alters the
    # produced ruleset must not keep serving results cached by an older parser.
    return _cache_key("rules", docxio.file_sha256(path), os.path.basename(path),
                      "v%d" % ruleschema.RULESET_VERSION)


def apply_cache_key(target_docx: str, source_fingerprint: str, rules_digest: str) -> str:
    return _cache_key("apply", docxio.file_sha256(target_docx), source_fingerprint, rules_digest)


def rules_digest(rules: Dict[str, Any]) -> str:
    payload = json.dumps(rules or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def file_info(path: str) -> Dict[str, Any]:
    return {
        "path": os.path.abspath(path),
        "sha256": docxio.file_sha256(path),
        "size": os.path.getsize(path),
        "filename": os.path.basename(path),
    }
