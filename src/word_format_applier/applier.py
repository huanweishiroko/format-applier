"""Apply a rule set to a target .docx.

Guarantees:

* **text is formatting-stable** - the paragraph text fingerprint is taken once
  after the optional cleanup pass and once after formatting; a mismatch fails the
  run and, unless the output was already written, no file is produced. Without a
  ``cleanup`` block the two fingerprints are the original document's, so the
  historical "text never changes" contract still holds exactly;
* **cleanup is opt-in** - text is only ever rewritten when the rule set declares
  it (see :mod:`word_format_applier.cleanup`), and every rewrite is summarised in
  the report;
* structure is preserved - the document object is edited in place and saved, so
  images, tables, hyperlinks, headers and styles survive untouched;
* the original target file is never overwritten (the output path is distinct);
* verification happens *inside* the plugin: the caller only ever reads a short
  JSON summary plus ``report.json``.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from . import docxio, llm_fallback, parser, presets as presets_mod, report as report_mod
from . import schema as ruleschema

#: cap on stored per-item detail, keeps report.json readable
MAX_DETAIL = 200
#: cap on the cleanup before/after samples kept in the report
MAX_CLEANUP_SAMPLES = 20
#: clip length for those samples: the report must never carry whole paragraphs
SAMPLE_CHARS = 60

#: XML that makes an apparently-empty paragraph meaningful; never remove those.
PROTECTED_PARAGRAPH_TAGS = (
    "w:drawing", "w:pict", "w:object", "w:br", "w:fldChar", "w:instrText",
    "w:hyperlink", "w:sectPr", "w:footnoteReference", "w:endnoteReference",
    "w:commentReference", "w:bookmarkStart", "w:bookmarkEnd",
)

TEXT_LEVEL = {
    "font_ascii", "font_eastasia", "font_hansi", "font_cs",
    "size_pt", "bold", "italic", "underline", "strike",
    "color", "all_caps", "character_spacing_pt", "vertical_align",
}


class FormatError(RuntimeError):
    pass


def _clip(text: str) -> str:
    value = (text or "").replace("\n", " ").strip()
    return value if len(value) <= SAMPLE_CHARS else value[:SAMPLE_CHARS] + "…"


def _element_text(element) -> str:
    """Visible text of a raw ``w:p`` element; used for the blank-all sweep.

    ``python-docx`` paragraph proxies are only needed for the entries the sweep
    walks; sibling paragraphs are inspected straight from the XML.
    """
    return "".join(node.text or "" for node in element.iter(docxio.qn("w:t")))


def _in_table(paragraph) -> bool:
    node = paragraph._p
    while node is not None:
        tag = getattr(node, "tag", "")
        if tag.endswith("}tbl"):
            return True
        node = node.getparent()
    return False


def _paragraph_index_map(paragraphs: List[Any]) -> Dict[int, int]:
    return {id(paragraph._p): index for index, paragraph in enumerate(paragraphs)}


def _role_of(paragraph, index: int, roles_seen: Dict[str, int]) -> Tuple[str, str]:
    style_name, style_id, outline = _style_ident(paragraph)
    in_table = _in_table(paragraph)
    return ruleschema.infer_role(style_name=style_name, style_id=style_id,
                                 outline_level=outline, in_table=in_table,
                                 paragraph_text=docxio.paragraph_text(paragraph))


def _style_ident(paragraph) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    from .textparse import _paragraph_style_ident

    return _paragraph_style_ident(paragraph)


def _run_font_spec(run) -> Dict[str, Any]:
    from .textparse import _run_char_spec

    return _run_char_spec(run)


def _current_effective(run, paragraph, default_font: Dict[str, Any],
                       role_spec: Dict[str, Any]) -> Dict[str, Any]:
    return _run_font_spec(run)


class Applier:
    """Applies one rule set to one document."""

    def __init__(self, document, rules: Dict[str, Any], *,
                 apply_page: bool = True,
                 heading_heuristic: bool = True,
                 explicit_heading_styles: bool = True,
                 logger=None) -> None:
        self.document = document
        self.rules = rules or {}
        self.styles = self.rules.get("styles") or {}
        self.page_rules = self.rules.get("page") or {}
        self.default_font = self.rules.get("default_font") or {}
        self.cleanup_rules = self.rules.get("cleanup") or {}
        self.structure_rules = self.rules.get("structure") or {}
        self.apply_page = apply_page
        self.heading_heuristic = heading_heuristic
        self.explicit_heading_styles = explicit_heading_styles
        self.log = logger or (lambda message: None)

        self.paragraphs: List[Any] = []
        self.role_by_paragraph: Dict[int, str] = {}
        self.reason_by_paragraph: Dict[int, str] = {}
        self.role_counts: Dict[str, int] = {}
        self.applied_rules: List[Dict[str, Any]] = []
        self.skipped_rules: List[Dict[str, Any]] = []
        self.conflicts: List[Dict[str, Any]] = []
        self.unresolved: List[Dict[str, Any]] = []
        self.replaced_direct: List[Dict[str, Any]] = []
        self.role_sample: List[Dict[str, Any]] = []
        self.cleanup_hints: Dict[int, str] = {}

        self.paragraphs_changed = 0
        self.paragraphs_skipped = 0
        self.runs_changed = 0
        self.properties_applied = 0
        self.sections_updated = 0

    # ------------------------------------------------------------------ #
    # text cleanup (opt-in, runs before any formatting)
    # ------------------------------------------------------------------ #

    def apply_cleanup(self) -> Dict[str, Any]:
        """Strip markdown residue / junk symbols when the rule set asks for it.

        Returns a report-ready summary. A rule set without a ``cleanup`` block
        makes this a no-op, which is what keeps every other preset byte-exact.
        """
        result: Dict[str, Any] = {"enabled": False, "applied": False}
        if not ruleschema.cleanup_enabled(self.rules):
            return result

        from . import cleanup as cleanup_mod

        cleaner = cleanup_mod.TextCleaner(
            self.cleanup_rules, preserve_numbering=self._numbering_preserved())
        result.update(cleaner.describe())
        result["enabled"] = True

        entries: List[Dict[str, Any]] = []
        for index, paragraph in enumerate(docxio.iter_all_paragraphs(self.document)):
            before = docxio.paragraph_text(paragraph)
            after, info = cleaner.clean(before)
            entries.append({"paragraph": paragraph, "index": index,
                            "before": before, "after": after, "info": info})

        # a "===" / "---" underline promotes the paragraph directly above it
        for position in range(1, len(entries)):
            entry = entries[position]
            level = entry["info"].get("setext")
            if not level:
                continue
            previous = entries[position - 1]
            if previous["after"].strip() and not previous["info"].get("fence"):
                previous["info"]["heading"] = level
            entry["after"] = ""
            entry["info"]["blank"] = True

        # a paragraph that only carried markdown syntax ("===", "```", "---",
        # "| --- |") is dropped outright rather than left as an empty paragraph
        for entry in entries:
            if entry["info"].get("marker") and self._paragraph_is_removable(entry["paragraph"]):
                entry["drop"] = True

        changed = 0
        samples: List[Dict[str, Any]] = []
        for entry in entries:
            paragraph = entry["paragraph"]
            if entry.get("drop"):
                continue
            before, after = entry["before"], entry["after"]
            if after != before and self._write_paragraph_text(paragraph, after):
                changed += 1
                if len(samples) < MAX_CLEANUP_SAMPLES:
                    samples.append({"paragraph": entry["index"],
                                    "before": _clip(before), "after": _clip(after)})
            heading = entry["info"].get("heading")
            if heading:
                entry["role_hint"] = "heading%d" % min(6, max(1, int(heading)))

        removed_markers = self._drop_entries(entries)

        removed_blanks = 0
        if cleaner.config.get("blank_lines"):
            removed_blanks = self._collapse_blank_run(entries)
        # "删除空段落" goes one step further: no separator paragraph survives at all
        removed_all_blanks = 0
        if cleaner.config.get("blank_all"):
            removed_all_blanks = self._drop_all_blank(entries)
        if removed_blanks or removed_all_blanks:
            self._drop_entries(entries)

        # The surviving paragraphs, in document order, become the list the role
        # mapper works on. Rebuilding it here (instead of asking the document
        # again) keeps the index -> role-hint mapping valid: lxml hands out fresh
        # proxy objects for the same node once the previous ones are collected, so
        # identity-keyed maps silently miss.
        survivors = [entry for entry in entries if not entry.get("drop")]
        self.paragraphs = [entry["paragraph"] for entry in survivors]
        self.cleanup_hints = {
            index: entry["role_hint"]
            for index, entry in enumerate(survivors)
            if entry.get("role_hint")
        }

        removed = removed_markers + removed_blanks + removed_all_blanks
        result.update({
            "applied": bool(changed or removed),
            "paragraphs_scanned": len(entries),
            "paragraphs_changed": changed,
            "paragraphs_removed": removed,
            "paragraphs_removed_markers": removed_markers,
            "paragraphs_removed_blank": removed_blanks,
            "paragraphs_removed_blank_all": removed_all_blanks,
            "heading_hints": len(self.cleanup_hints),
            "samples": samples,
            "unresolved": [item for item in self.unresolved if item.get("scope") == "cleanup"],
        })
        return result

    def _drop_entries(self, entries: List[Dict[str, Any]]) -> int:
        """Detach every entry flagged with ``drop`` from the document."""
        removed = 0
        for entry in entries:
            if not entry.get("drop") or entry.get("detached"):
                continue
            element = entry["paragraph"]._p
            parent = element.getparent()
            if parent is None:
                continue
            parent.remove(element)
            entry["detached"] = True
            removed += 1
        return removed

    def _write_paragraph_text(self, paragraph, text: str) -> bool:
        """Replace a paragraph's visible text, keeping its first run's formatting.

        Word splits one sentence across many runs; once the text changes there is
        no faithful run-by-run mapping, so the cleaned text lands in the first run
        and the remaining runs are dropped. ``w:rPr`` of that first run survives,
        and role formatting is applied right afterwards anyway.
        """
        runs = paragraph.runs
        if not runs:
            return False
        try:
            runs[0].text = text
            for run in runs[1:]:
                element = run._element
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)
        except Exception as exc:  # pragma: no cover - defensive
            self.unresolved.append({"scope": "cleanup",
                                    "reason": "cannot rewrite paragraph: %s" % exc})
            return False
        return True

    def _paragraph_is_removable(self, paragraph, *, allow_last: bool = False) -> bool:
        element = paragraph._p
        for tag in PROTECTED_PARAGRAPH_TAGS:
            for _ in element.iter(docxio.qn(tag)):
                return False
        parent = element.getparent()
        if parent is None:
            return False
        parent_tag = getattr(parent, "tag", "")
        if not (parent_tag.endswith("}body") or parent_tag.endswith("}tc")):
            return False
        siblings = [child for child in parent
                    if getattr(child, "tag", "") == docxio.qn("w:p")]
        # keep at least one paragraph per cell/body
        if len(siblings) <= 1:
            return False
        # a *trailing* empty paragraph is only droppable for 删除空段落, and only in
        # the body: a table cell must always keep its last paragraph
        if siblings[-1] is element and not (allow_last and parent_tag.endswith("}body")):
            return False
        return True

    def _collapse_blank_run(self, entries: List[Dict[str, Any]]) -> int:
        """Flag every blank paragraph that follows another blank one for removal."""
        removed = 0
        previous_blank = False
        for entry in entries:
            if entry.get("drop"):
                continue
            paragraph = entry["paragraph"]
            blank = not docxio.paragraph_text(paragraph).strip()
            if blank and previous_blank and self._paragraph_is_removable(paragraph):
                entry["drop"] = True
                removed += 1
                continue
            previous_blank = blank
        return removed

    def _drop_all_blank(self, entries: List[Dict[str, Any]]) -> int:
        """Flag *every* blank paragraph for removal (the 删除空段落 category).

        Unlike :meth:`_collapse_blank_run` this leaves no separator paragraph
        behind, so "两个段落之间不要空行" really holds. A container that would be
        left without any paragraph keeps its first blank one.
        """
        removed = 0
        for entry in entries:
            if entry.get("drop"):
                continue
            paragraph = entry["paragraph"]
            if docxio.paragraph_text(paragraph).strip():
                continue
            element = paragraph._p
            parent = element.getparent()
            if parent is None:
                continue
            siblings = [child for child in parent
                        if getattr(child, "tag", "") == docxio.qn("w:p")]
            if len(siblings) <= 1:
                continue
            if all(not _element_text(child).strip() for child in siblings) \
                    and siblings[0] is element:
                # every paragraph of this body/cell is blank: keep this one
                continue
            if self._paragraph_is_removable(paragraph, allow_last=True):
                entry["drop"] = True
                removed += 1
        return removed

    # ------------------------------------------------------------------ #
    # structural preprocessing (opt-in, runs after cleanup, before role binding)
    # ------------------------------------------------------------------ #

    def _numbering_preserved(self) -> bool:
        """True when 结构预处理 reads document numbering.

        The markdown cleanup would otherwise delete "1. " as list syntax, leaving
        the structural pass nothing to read.
        """
        return bool((self.structure_rules or {}).get("numbering"))

    def apply_structure(self) -> Dict[str, Any]:
        """Give 整段加粗 / 编号正则 / 首段标题 paragraphs a real Word style.

        This runs before role binding on purpose: once the paragraph carries
        "Heading 2" (or "Title"), the ordinary role mapper resolves ``heading2``
        (or ``title``) and the preset's 标题2 / 标题 fonts are applied by the normal
        path. Nothing is written to the text, so the byte-identical guarantee is
        untouched.
        """
        result: Dict[str, Any] = {"enabled": False, "applied": False}
        if not ruleschema.structure_enabled(self.rules):
            return result

        from . import structure as structure_mod

        if not self.paragraphs:
            # no cleanup pass ran: role binding will read the whole document, so
            # the structural pass must plan on exactly the same paragraph list
            self.paragraphs = docxio.iter_all_paragraphs(self.document)

        assignments, meta = structure_mod.detect_levels(self.paragraphs, self.structure_rules)
        result.update(structure_mod.describe(self.structure_rules))
        result["enabled"] = True
        result.update(meta)

        mapped = 0
        by_level: Dict[str, int] = {}
        title_mapped = 0
        samples: List[Dict[str, Any]] = []
        index_map = _paragraph_index_map(self.paragraphs)
        for item in assignments:
            paragraph = item["paragraph"]
            level = item.get("level")
            style_name = item.get("style") or "Heading %d" % int(level)
            target_role = ruleschema.role_from_style_name(style_name)
            if target_role and ruleschema.role_from_style_name(_style_ident(paragraph)[0] or "") == target_role:
                continue
            try:
                paragraph.style = self.document.styles[style_name]
            except Exception as exc:
                self.unresolved.append({
                    "scope": "structure", "style": style_name, "level": level,
                    "reason": "style unavailable: %s" % exc,
                    "text_head": item.get("text_head", "")})
                continue
            mapped += 1
            if level:
                by_level[str(level)] = by_level.get(str(level), 0) + 1
            else:
                title_mapped += 1
            if len(samples) < MAX_CLEANUP_SAMPLES:
                samples.append({"paragraph": index_map.get(id(paragraph._p), -1),
                                "style": style_name, "level": level,
                                "reason": item["reason"],
                                "text_head": item.get("text_head", "")})

        result.update({
            "applied": bool(mapped),
            "mapped": mapped,
            "headings_mapped": mapped - title_mapped,
            "title_mapped": title_mapped,
            "by_level": by_level,
            "samples": samples,
            "unresolved": [entry for entry in self.unresolved if entry.get("scope") == "structure"],
        })
        return result

    # ------------------------------------------------------------------ #
    # planning
    # ------------------------------------------------------------------ #

    def build_role_map(self) -> Dict[int, str]:
        if not self.paragraphs:
            self.paragraphs = docxio.iter_all_paragraphs(self.document)
        text_sizes: List[float] = []
        for paragraph in self.paragraphs:
            for run in paragraph.runs:
                if (run.text or "").strip() and run.font.size is not None:
                    text_sizes.append(round(float(run.font.size.pt), 2))
                    break
        body_size = None
        if text_sizes:
            counts: Dict[float, int] = {}
            for size in text_sizes:
                counts[size] = counts.get(size, 0) + 1
            body_size = max(counts.items(), key=lambda item: (item[1], item[0]))[0]

        style_default_size = (self.default_font or {}).get("size_pt") or (self.styles.get("normal") or {}).get("size_pt")

        for index, paragraph in enumerate(self.paragraphs):
            style_name, style_id, outline = _style_ident(paragraph)
            in_table = _in_table(paragraph)
            text = docxio.paragraph_text(paragraph).strip()
            role, reason = ruleschema.infer_role(
                style_name=style_name, style_id=style_id, outline_level=outline,
                in_table=in_table, paragraph_text=text)
            # A markdown "# heading" outranks the text-shape heuristic but never an
            # explicit Word heading style, which has already resolved above.
            hint = self.cleanup_hints.get(index)
            if hint and not role.startswith("heading"):
                role, reason = hint, "cleanup:%s" % hint
            # A paragraph whose style resolves to "normal" carries no heading signal,
            # so the text-shape heuristic must still get its chance: without the
            # style_name clause the heuristic was unreachable for every document
            # whose body style is Word's built-in Normal.
            if (self.heading_heuristic and role == "normal" and text
                    and not in_table
                    and (reason in ("heuristic:short_line", "default")
                         or reason.startswith("style_name:"))):
                guess = self._heading_guess(paragraph, text, body_size, style_default_size)
                if guess:
                    role, reason = guess
            if role not in self.styles and role != "normal":
                base = "normal" if "normal" in self.styles else None
                if base is None:
                    self.unresolved.append({
                        "paragraph": index, "role": role,
                        "reason": "no rule for role and no normal fallback",
                        "text_head": text[:20]})
                    role, reason = "normal", "fallback:normal"
            self.role_by_paragraph[index] = role
            self.reason_by_paragraph[index] = reason
            self.role_counts[role] = self.role_counts.get(role, 0) + 1
            if len(self.role_sample) < 30:
                self.role_sample.append({"i": index, "role": role, "reason": reason,
                                         "style": style_name, "head": text[:20]})
        return self.role_by_paragraph

    def _heading_guess(self, paragraph, text: str, body_size: Optional[float],
                       style_default_size: Optional[float]) -> Optional[Tuple[str, str]]:
        if len(text) > 60 or text.endswith(("。", ".", "！", "!", "？", "?", "；", ";")):
            return None
        if len(text.split()) > 14:
            return None
        run = None
        for candidate in paragraph.runs:
            if (candidate.text or "").strip():
                run = candidate
                break
        bold = False
        size = None
        if run is not None:
            bold = bool(run.font.bold)
            if run.font.size is not None:
                size = round(float(run.font.size.pt), 2)
        normal_spec = self.styles.get("normal") or {}
        base_size = body_size or style_default_size or normal_spec.get("size_pt")
        bold_rule = normal_spec.get("bold")
        if bold and bold_rule is not True:
            return "heading1", "heuristic:bold_short_line"
        if size and base_size and size > base_size + 0.4:
            return "heading1", "heuristic:larger_font"
        if text.endswith(("：", ":")) and len(text) <= 30:
            return "heading3", "heuristic:label_line"
        return None

    # ------------------------------------------------------------------ #
    # application
    # ------------------------------------------------------------------ #

    def apply(self) -> Dict[str, Any]:
        self.build_role_map()
        for index, paragraph in enumerate(self.paragraphs):
            self._apply_paragraph(index, paragraph)
        if self.apply_page and self.page_rules:
            self._apply_page()
        return self.stats()


    def _spec_for(self, role: str) -> Dict[str, Any]:
        normal = self.styles.get("normal") or {}
        role_spec = self.styles.get(role) or {}
        if role == "normal":
            return dict(role_spec)
        base = {k: v for k, v in normal.items() if k in TEXT_LEVEL}
        spec = ruleschema.merge_specs(base, role_spec)
        if role.startswith("heading") or role in ("title", "caption"):
            if "first_line_indent_chars" not in role_spec and "first_line_indent_pt" not in role_spec:
                spec["first_line_indent_chars"] = 0.0
                spec.pop("first_line_indent_pt", None)
        return {k: v for k, v in spec.items() if v is not None}

    def _apply_paragraph(self, index: int, paragraph) -> None:
        role = self.role_by_paragraph.get(index, "normal")
        spec = self._spec_for(role)
        text = docxio.paragraph_text(paragraph)
        if not spec:
            self.paragraphs_skipped += 1
            self._skip(index, role, "*", "no attributes for role")
            return
        changed_props: List[str] = []

        # ---- explicit heading style beats heuristics and direct formatting ----
        if (role.startswith("heading") and self.explicit_heading_styles
                and role in ("heading1", "heading2", "heading3", "heading4", "heading5", "heading6")):
            level = int(role[len("heading"):])
            style_name, style_id, outline = _style_ident(paragraph)
            if ruleschema.role_from_style_name(style_name or "") != role:
                prior = self._collect_direct(paragraph)
                try:
                    paragraph.style = self.document.styles["Heading %d" % level]
                    changed_props.append("style=Heading %d" % level)
                    self.replaced_direct.append({
                        "paragraph": index, "role": role,
                        "style_applied": "Heading %d" % level,
                        "replaced_direct_formatting": prior,
                    })
                except Exception as exc:
                    self.unresolved.append({"paragraph": index, "role": role,
                                            "reason": "heading style unavailable: %s" % exc})

        # ---- paragraph level attributes ----
        para_props = self._apply_paragraph_format(paragraph, spec)
        changed_props.extend(para_props)

        # ---- run level attributes ----
        runs_touched = 0
        run_props: List[str] = []
        if not text.strip():
            # keep empty paragraphs empty, but still normalise their run fonts
            for run in paragraph.runs:
                added = self._apply_run(run, spec)
                if added:
                    run_props.extend(added)
        else:
            for run in paragraph.runs:
                added = self._apply_run(run, spec)
                if added:
                    run_props.extend(added)
                    self.runs_changed += 1
                runs_touched += 1
        changed_props.extend(run_props)

        if not paragraph.runs and self._has_text_attrs(spec):
            self.unresolved.append({"paragraph": index, "role": role,
                                    "reason": "paragraph has no runs (text may be in a field)",
                                    "text_head": text[:20].strip()})

        if changed_props:
            self.paragraphs_changed += 1
            self.properties_applied += len(changed_props)
            if len(self.applied_rules) < MAX_DETAIL:
                self.applied_rules.append({
                    "paragraph": index, "role": role,
                    "changes": sorted(set(changed_props)),
                })
            if len(self.applied_rules) >= MAX_DETAIL and len(self.applied_rules) == MAX_DETAIL:
                self.applied_rules.append({"note": "applied_rules truncated"})
        else:
            self.paragraphs_skipped += 1
            self._skip(index, role, "*", "already matches the rule", text_head=text[:20].strip())

    def _has_text_attrs(self, spec: Dict[str, Any]) -> bool:
        return any(key in spec for key in ruleschema.TEXT_ATTRS)

    def _skip(self, index: int, role: str, prop: str, reason: str, text_head: str = "") -> None:
        if len(self.skipped_rules) >= MAX_DETAIL:
            return
        self.skipped_rules.append({"paragraph": index, "role": role, "attribute": prop,
                                   "reason": reason, "text_head": text_head})

    def _collect_direct(self, paragraph) -> Dict[str, Any]:
        direct: Dict[str, Any] = {}
        for run in paragraph.runs:
            direct.update(_run_font_spec(run))
        for key, value in _para_spec(paragraph).items():
            direct.setdefault(key, value)
        return direct

    # ------------------------------------------------------------------ #

    def _apply_paragraph_format(self, paragraph, spec: Dict[str, Any]) -> List[str]:
        from docx.shared import Pt, Twips

        changed: List[str] = []
        fmt = paragraph.paragraph_format

        if "align" in spec:
            target = docxio.ALIGN_TO_DOCX.get(spec["align"])
            if target is None:
                self.unresolved.append({"attribute": "align", "value": spec["align"],
                                        "reason": "unsupported alignment"})
            elif fmt.alignment != target:
                fmt.alignment = target
                changed.append("align=%s" % spec["align"])

        rule = spec.get("line_spacing_rule", "multiple")
        if "line_spacing" in spec:
            value = spec["line_spacing"]
            if rule == "exactly":
                target = Pt(value)
                if fmt.line_spacing != target or fmt.line_spacing_rule != docxio.LINE_RULE_TO_DOCX["exactly"]:
                    fmt.line_spacing = target
                    changed.append("line_spacing=%spt(exact)" % value)
            else:
                target = float(value)
                if fmt.line_spacing != target:
                    fmt.line_spacing = target
                    changed.append("line_spacing=%sx" % value)

        for key, attr, label in (("space_before_pt", "space_before", "space_before"),
                                 ("space_after_pt", "space_after", "space_after")):
            if key in spec:
                target = Pt(spec[key])
                if getattr(fmt, attr) != target:
                    setattr(fmt, attr, target)
                    changed.append("%s=%spt" % (label, spec[key]))

        if "first_line_indent_chars" in spec:
            target = Pt(spec["first_line_indent_chars"] * ruleschema.CHARS_TO_PT)
            if fmt.first_line_indent != target:
                fmt.first_line_indent = target
                changed.append("first_line_indent=%s字" % spec["first_line_indent_chars"])
        elif "first_line_indent_pt" in spec:
            target = Pt(spec["first_line_indent_pt"])
            if fmt.first_line_indent != target:
                fmt.first_line_indent = target
                changed.append("first_line_indent=%spt" % spec["first_line_indent_pt"])

        if "left_indent_chars" in spec:
            target = Pt(spec["left_indent_chars"] * ruleschema.CHARS_TO_PT)
            if fmt.left_indent != target:
                fmt.left_indent = target
                changed.append("left_indent=%s字" % spec["left_indent_chars"])
        elif "left_indent_pt" in spec:
            target = Pt(spec["left_indent_pt"])
            if fmt.left_indent != target:
                fmt.left_indent = target
                changed.append("left_indent=%spt" % spec["left_indent_pt"])

        if "right_indent_pt" in spec:
            target = Pt(spec["right_indent_pt"])
            if fmt.right_indent != target:
                fmt.right_indent = target
                changed.append("right_indent=%spt" % spec["right_indent_pt"])

        for key, attr in (("keep_with_next", "keep_with_next"),
                          ("page_break_before", "page_break_before"),
                          ("widow_control", "widow_control")):
            if key in spec:
                try:
                    if getattr(fmt, attr) != spec[key]:
                        setattr(fmt, attr, spec[key])
                        changed.append("%s=%s" % (key, spec[key]))
                except Exception:
                    self.unresolved.append({"attribute": key, "reason": "unsupported by python-docx"})

        return changed

    def _apply_run(self, run, spec: Dict[str, Any]) -> List[str]:
        from docx.shared import Pt, RGBColor
        from docx.oxml.ns import qn

        changed: List[str] = []
        font = run.font
        has_eastasia = False
        for key in ("font_ascii", "font_hansi", "font_cs"):
            if key in spec:
                if font.name != spec[key]:
                    font.name = spec[key]
                    changed.append("%s=%s" % (key, spec[key]))
                has_eastasia = True
        if has_eastasia:
            rpr = docxio.element_run_properties(run)
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = rpr.makeelement(qn("w:rFonts"), {})
                rpr.insert(0, rfonts)
            for xml_key, spec_key in (("w:ascii", "font_ascii"), ("w:hAnsi", "font_hansi")):
                value = spec.get(spec_key) or spec.get("font_ascii")
                if value and rfonts.get(qn(xml_key)) != value:
                    rfonts.set(qn(xml_key), value)
        if "font_eastasia" in spec:
            rpr = docxio.element_run_properties(run)
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = rpr.makeelement(qn("w:rFonts"), {})
                rpr.insert(0, rfonts)
            if rfonts.get(qn("w:eastAsia")) != spec["font_eastasia"]:
                rfonts.set(qn("w:eastAsia"), spec["font_eastasia"])
                changed.append("font_eastasia=%s" % spec["font_eastasia"])

        if "size_pt" in spec:
            target = Pt(spec["size_pt"])
            if font.size != target:
                font.size = target
                changed.append("size=%spt" % spec["size_pt"])

        for key, attr in (("bold", "bold"), ("italic", "italic"),
                          ("underline", "underline"), ("strike", "strike"),
                          ("all_caps", "all_caps")):
            if key in spec and getattr(font, attr) != spec[key]:
                setattr(font, attr, spec[key])
                changed.append("%s=%s" % (key, spec[key]))

        if "color" in spec:
            try:
                if spec["color"] == "auto":
                    target = None
                else:
                    target = RGBColor.from_string(spec["color"])
                current = None
                try:
                    current = font.color.rgb if font.color is not None else None
                except Exception:
                    current = None
                if (target is None and current is not None) or (target is not None and current != target):
                    if target is None:
                        font.color.rgb = None
                    else:
                        font.color.rgb = target
                    changed.append("color=%s" % spec["color"])
            except Exception as exc:
                self.unresolved.append({"attribute": "color", "value": spec["color"],
                                        "reason": str(exc)})

        if "vertical_align" in spec:
            try:
                from docx.enum.text import WD_ALIGN_VERTICAL

                mapping = {"superscript": WD_ALIGN_VERTICAL.SUPERSCRIPT,
                           "subscript": WD_ALIGN_VERTICAL.SUBSCRIPT}
                target = mapping.get(spec["vertical_align"])
                if target is not None and font.superscript != (target == WD_ALIGN_VERTICAL.SUPERSCRIPT) \
                        or font.subscript != (target == WD_ALIGN_VERTICAL.SUBSCRIPT):
                    font.superscript = target == WD_ALIGN_VERTICAL.SUPERSCRIPT
                    font.subscript = target == WD_ALIGN_VERTICAL.SUBSCRIPT
                    changed.append("vertical_align=%s" % spec["vertical_align"])
            except Exception:
                self.unresolved.append({"attribute": "vertical_align",
                                        "reason": "unsupported by python-docx"})

        if "character_spacing_pt" in spec:
            rpr = docxio.element_run_properties(run)
            spacing = rpr.find(qn("w:spacing"))
            twips = str(int(round(spec["character_spacing_pt"] * ruleschema.PT_TO_TWIPS)))
            if spacing is None:
                spacing = rpr.makeelement(qn("w:spacing"), {})
                rpr.append(spacing)
            if spacing.get(qn("w:val")) != twips:
                spacing.set(qn("w:val"), twips)
                changed.append("character_spacing=%spt" % spec["character_spacing_pt"])

        return changed

    def _apply_page(self) -> None:
        from docx.shared import Cm

        spec = self.page_rules
        for index, section in enumerate(self.document.sections):
            touched = False
            try:
                if "margin_top_cm" in spec:
                    section.top_margin = Cm(spec["margin_top_cm"])
                    touched = True
                if "margin_bottom_cm" in spec:
                    section.bottom_margin = Cm(spec["margin_bottom_cm"])
                    touched = True
                if "margin_left_cm" in spec:
                    section.left_margin = Cm(spec["margin_left_cm"])
                    touched = True
                if "margin_right_cm" in spec:
                    section.right_margin = Cm(spec["margin_right_cm"])
                    touched = True
                if "orientation" in spec:
                    from docx.enum.section import WD_ORIENT

                    target = (WD_ORIENT.LANDSCAPE if spec["orientation"] == "landscape"
                              else WD_ORIENT.PORTRAIT)
                    if section.orientation != target:
                        section.orientation = target
                        touched = True
            except Exception as exc:
                self.unresolved.append({"scope": "section", "index": index, "reason": str(exc)})
            if touched:
                self.sections_updated += 1
        if self.sections_updated:
            self.applied_rules.append({
                "scope": "page",
                "sections": self.sections_updated,
                "changes": sorted(self.page_rules.keys()),
            })

    # ------------------------------------------------------------------ #

    def stats(self) -> Dict[str, Any]:
        return {
            "paragraphs_total": len(self.paragraphs),
            "paragraphs_changed": self.paragraphs_changed,
            "paragraphs_skipped": self.paragraphs_skipped,
            "runs_changed": self.runs_changed,
            "properties_applied": self.properties_applied,
            "sections_updated": self.sections_updated,
            "role_counts": self.role_counts,
            "applied_rules": self.applied_rules,
            "skipped_rules": self.skipped_rules,
            "conflicts": self.conflicts,
            "unresolved": self.unresolved,
            "replaced_direct_formatting": self.replaced_direct[:MAX_DETAIL],
            "role_sample": self.role_sample,
        }


def _para_spec(paragraph) -> Dict[str, Any]:
    from .textparse import _paragraph_para_spec

    return _paragraph_para_spec(paragraph)


# --------------------------------------------------------------------------- #
# top level API
# --------------------------------------------------------------------------- #

def apply_format(target_docx: str,
                 format_source: str,
                 output_docx: Optional[str] = None,
                 *,
                 dry_run: bool = False,
                 report_path: Optional[str] = None,
                 markdown_report_path: Optional[str] = None,
                 presets_dir: Optional[str] = None,
                 cwd: Optional[str] = None,
                 use_cache: bool = True,
                 llm_fallback_enabled: bool = False,
                 llm_budget: Optional[llm_fallback.LLMBudget] = None,
                 llm_config: Optional[Dict[str, Any]] = None,
                 inline_text: Optional[str] = None,
                 apply_page: bool = True,
                 heading_heuristic: bool = True,
                 logger=None) -> Dict[str, Any]:
    """Apply ``format_source`` formatting to ``target_docx``; return a short summary.

    The full detail lands in ``report.json``.
    """
    log = logger or (lambda message: None)
    started = time.time()
    target_docx = os.path.abspath(target_docx)
    if not os.path.isfile(target_docx):
        raise FormatError("target docx not found: %s" % target_docx)
    docxio.require_docx()

    output_docx = presets_mod.default_output_path(target_docx, output_docx)
    if os.path.abspath(output_docx) == target_docx:
        raise FormatError("output path must differ from the target (the original is never overwritten)")
    if report_path is None:
        base, _ = os.path.splitext(output_docx)
        report_path = base + ".report.json"
    report_path = os.path.abspath(report_path)

    document = docxio.open_document(target_docx)
    text_before = docxio.text_fingerprint(document)

    # target-side context for the (optional) LLM fallback: small aggregates only
    llm_context: Optional[Dict[str, Any]] = None
    if llm_fallback_enabled:
        try:
            llm_context = {
                "target_style_stats": llm_fallback.style_stats(document),
                "paragraph_metadata_sample": llm_fallback.paragraph_metadata_sample(document),
            }
        except Exception:
            llm_context = None

    early_warnings: List[str] = []
    try:
        parsed = parser.parse_format_source(
            format_source,
            cwd=cwd or os.getcwd(),
            use_cache=use_cache,
            presets_dir=presets_dir,
            llm_enabled=llm_fallback_enabled,
            llm_budget=llm_budget,
            llm_context=llm_context,
            llm_config=llm_config,
            raw_text=inline_text,
            logger=log,
        )
    except parser.FormatError as exc:
        # one local retry in lenient mode; never a second guess, never an LLM call
        log("initial parse failed (%s); retrying once in lenient mode" % exc)
        parsed = parser.parse_format_source(
            format_source, cwd=cwd or os.getcwd(), use_cache=use_cache, presets_dir=presets_dir,
            llm_enabled=llm_fallback_enabled, llm_budget=llm_budget, llm_context=llm_context,
            llm_config=llm_config, raw_text=inline_text, strict=False, logger=log)
        early_warnings.append("the requirement text could not be parsed: %s" % exc)
    rules = parsed["rules"]
    source_meta = parsed["source"]
    if source_meta.get("kind") in ("text", "preset_text") and not (rules.get("styles") or rules.get("page")):
        early_warnings.append(
            "no formatting rule could be parsed from the requirement text; "
            "the document was written through unchanged")
    log("rules: %d" % ruleschema.ruleset_rule_count(rules))

    applier = Applier(document, rules, apply_page=apply_page,
                      heading_heuristic=heading_heuristic, logger=log)

    # Text cleanup is the only step allowed to change the text, and only when the
    # rule set declares it. The fingerprint taken right afterwards becomes the
    # baseline the formatting pass must preserve byte-for-byte.
    cleanup_info = applier.apply_cleanup()
    text_baseline = docxio.text_fingerprint(document)
    if cleanup_info.get("applied"):
        log("cleanup: %d paragraph(s) rewritten, %d removed"
            % (cleanup_info.get("paragraphs_changed", 0),
               cleanup_info.get("paragraphs_removed", 0)))

    # Structural preprocessing runs next - still before role binding, and again
    # without touching a single character: it only assigns Word heading styles.
    structure_info = applier.apply_structure()
    if structure_info.get("applied"):
        log("structure: %d paragraph(s) mapped to Word heading styles (%d title)"
            % (structure_info.get("mapped", 0), structure_info.get("title_mapped", 0)))

    stats = applier.apply()

    text_after = docxio.text_fingerprint(document)
    text_unchanged = text_baseline["sha256"] == text_after["sha256"]
    warnings: List[str] = list(early_warnings)
    errors: List[str] = []
    if not text_unchanged:
        errors.append("text changed during formatting: %s -> %s"
                      % (text_baseline["sha256"][:12], text_after["sha256"][:12]))
    # a cleanup pass that found nothing is not a warning: report.json already
    # carries cleanup.applied == false, and warning on every clean document is noise
    if cleanup_info.get("unresolved"):
        warnings.append("cleanup could not rewrite %d paragraph(s)"
                        % len(cleanup_info["unresolved"]))
    if (rules.get("extras") or {}).get("parse", {}).get("cleanup_unrecognised"):
        warnings.append("unrecognised cleanup keyword(s): %s"
                        % ", ".join(rules["extras"]["parse"]["cleanup_unrecognised"]))
    if (rules.get("extras") or {}).get("parse", {}).get("structure_unrecognised"):
        warnings.append("unrecognised structure keyword(s): %s"
                        % ", ".join(rules["extras"]["parse"]["structure_unrecognised"]))
    if structure_info.get("bold_disabled"):
        warnings.append("整段加粗 signal ignored: %s" % structure_info["bold_disabled"])
    if (rules.get("extras") or {}).get("parse", {}).get("llm_unresolved"):
        warnings.append("llm reported unresolved items")
    if stats["unresolved"]:
        warnings.append("%d attribute(s) could not be applied" % len(stats["unresolved"]))
    if any(entry.get("replaced_direct_formatting") for entry in stats["replaced_direct_formatting"]):
        warnings.append("%d paragraph(s) had direct formatting replaced by a heading style"
                        % len(stats["replaced_direct_formatting"]))

    written_output = None
    partial = False
    if not dry_run and text_unchanged:
        try:
            docxio.save_document(document, output_docx)
            written_output = output_docx
        except Exception as exc:
            errors.append("failed to write output: %s" % exc)
            partial = True
    elif dry_run:
        written_output = None

    timings = {
        "total_ms": int((time.time() - started) * 1000),
    }
    report = report_mod.build_report(
        ok=bool(text_unchanged and not errors),
        target_docx=target_docx,
        output_docx=written_output or (None if dry_run else output_docx),
        report_json=report_path,
        dry_run=dry_run,
        source_info=source_meta,
        rules=rules,
        stats=stats,
        text_before=text_before,
        text_after=text_after,
        text_baseline=text_baseline,
        cleanup=cleanup_info,
        structure=structure_info,
        warnings=warnings,
        errors=errors,
        llm={
            "calls": parsed["llm"].get("calls", 0),
            "used": bool(parsed["llm"].get("used")),
            "reason": parsed["llm"].get("reason"),
            "cache_hit": bool(parsed["llm"].get("cache_hit")),
            "budget": (llm_budget or llm_fallback.LLMBudget()).snapshot(),
        },
        timings=timings,
        partial=partial,
    )
    report_mod.write_reports(report, report_path, markdown_report_path)
    return report_mod.short_summary(report)
