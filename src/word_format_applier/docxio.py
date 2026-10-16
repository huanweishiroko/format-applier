"""Thin python-docx layer + text fingerprinting.

Everything that touches ``python-docx`` lives here so the rest of the package
stays importable (and testable) even when the dependency is missing, and so the
"text must not change" contract has exactly one implementation.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - exercised implicitly by the test suite
    import docx  # noqa: F401
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor, Twips

    HAVE_DOCX = True
except Exception:  # pragma: no cover
    HAVE_DOCX = False
    Document = None  # type: ignore
    WD_ALIGN_PARAGRAPH = None  # type: ignore
    WD_LINE_SPACING = None  # type: ignore
    WD_ORIENT = None  # type: ignore
    qn = None  # type: ignore
    Cm = Pt = RGBColor = Twips = None  # type: ignore


class DocxError(RuntimeError):
    pass


def require_docx() -> None:
    if not HAVE_DOCX:
        raise DocxError(
            "python-docx is required for reading/writing .docx files "
            "(pip install python-docx)"
        )


def open_document(path: str):
    require_docx()
    try:
        return Document(path)
    except Exception as exc:  # pragma: no cover - depends on broken input
        raise DocxError("cannot open docx %s: %s" % (path, exc)) from exc


# --------------------------------------------------------------------------- #
# Text extraction / fingerprinting
# --------------------------------------------------------------------------- #

_PARA_TAGS = ("w:p", "w:tbl")


def iter_block_paragraphs(container) -> Iterable[Any]:
    """Yield every paragraph of a container, including nested table cells.

    ``container`` is a ``Document``, ``_Cell`` or ``Table``; the walk is
    recursive so nested tables are covered too.
    """
    if container is None:
        return
    paragraphs = getattr(container, "paragraphs", None)
    if paragraphs is not None:
        for paragraph in paragraphs:
            yield paragraph
    tables = getattr(container, "tables", None)
    if tables is not None:
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from iter_block_paragraphs(cell)


def iter_all_paragraphs(document) -> List[Any]:
    seen = set()
    out = []
    for paragraph in iter_block_paragraphs(document):
        marker = id(paragraph._p)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(paragraph)
    return out


def paragraph_text(paragraph) -> str:
    try:
        return paragraph.text or ""
    except Exception:  # pragma: no cover
        return ""


def paragraph_is_centered(paragraph) -> bool:
    """True when the paragraph (or its style) is centre aligned.

    Direct formatting wins; a paragraph without direct alignment inherits the
    style's, which is how Word's own Title style is centred.
    """
    if not HAVE_DOCX:  # pragma: no cover - defensive
        return False
    try:
        alignment = paragraph.alignment
        if alignment is None:
            alignment = paragraph.style.paragraph_format.alignment
        return alignment == WD_ALIGN_PARAGRAPH.CENTER
    except Exception:  # pragma: no cover - defensive
        return False


def document_text(document) -> str:
    """Canonical text projection used for the "text unchanged" fingerprint.

    Paragraph text joined by ``\\n``; tables are flattened cell by cell in
    document order. Formatting-only edits must leave this byte-identical.
    """
    lines: List[str] = []
    for paragraph in iter_block_paragraphs(document):
        lines.append(paragraph_text(paragraph))
    return "\n".join(lines)


def text_fingerprint(document) -> Dict[str, Any]:
    text = document_text(document)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "chars": len(text),
        "paragraphs": len(iter_all_paragraphs(document)),
    }


def file_sha256(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text_file(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def docx_available(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Namespaces / low level helpers
# --------------------------------------------------------------------------- #

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def qname(tag: str) -> str:
    return W + tag


def find_child(element, tag: str):
    if element is None:
        return None
    return element.find(qname(tag))


def get_or_add(parent, tag: str):
    child = find_child(parent, tag)
    if child is None:
        child = parent.makeelement(qname(tag), {})
        parent.append(child)
    return child


def element_run_properties(run):
    rpr = run._element.find(qn("w:rPr")) if HAVE_DOCX else None
    if rpr is None:
        rpr = get_or_add(run._element, "rPr")
    return rpr


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #

_ILLEGAL_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def save_document(document, path: str) -> None:
    buffer = io.BytesIO()
    document.save(buffer)
    payload = buffer.getvalue()
    with open(path, "wb") as handle:
        handle.write(payload)


def scrub_illegal_xml(text: str) -> str:
    return _ILLEGAL_XML.sub("", text)


# --------------------------------------------------------------------------- #
# Alignment / spacing enums (kept behind helpers so callers stay docx-free)
# --------------------------------------------------------------------------- #

ALIGN_TO_DOCX = {}
ALIGN_NAMES = {
    "left": "LEFT",
    "center": "CENTER",
    "right": "RIGHT",
    "justify": "JUSTIFY",
    "distribute": "DISTRIBUTE",
}

if HAVE_DOCX:
    ALIGN_TO_DOCX = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "distribute": getattr(WD_ALIGN_PARAGRAPH, "DISTRIBUTE", WD_ALIGN_PARAGRAPH.JUSTIFY),
    }

LINE_RULE_TO_DOCX = {}
if HAVE_DOCX:
    LINE_RULE_TO_DOCX = {
        "multiple": WD_LINE_SPACING.MULTIPLE,
        "exactly": WD_LINE_SPACING.EXACTLY,
        "atleast": WD_LINE_SPACING.AT_LEAST,
        "at_least": WD_LINE_SPACING.AT_LEAST,
        "single": WD_LINE_SPACING.SINGLE,
    }
