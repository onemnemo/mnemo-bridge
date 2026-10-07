"""
Mnemo's note model, written to match ``BlockJsonConverter`` in Mnemo.Core.

The C# reader throws on an unknown ``payload.kind``, so payloads are only built
through the constructors below. Styles omit the same default fields Mnemo does,
so an imported note saves without a diff.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

TEXT = "Text"
HEADING1 = "Heading1"
HEADING2 = "Heading2"
HEADING3 = "Heading3"
HEADING4 = "Heading4"
BULLET_LIST = "BulletList"
NUMBERED_LIST = "NumberedList"
CHECKLIST = "Checklist"
QUOTE = "Quote"
CODE = "Code"
DIVIDER = "Divider"
IMAGE = "Image"
COLUMN_GROUP = "ColumnGroup"
TWO_COLUMN = "TwoColumn"
EQUATION = "Equation"
PAGE = "Page"
CALLOUT = "Callout"
TABLE = "Table"
TABLE_ROW = "TableRow"
TABLE_CELL = "TableCell"

#: The C# ``BlockType`` enum in declaration order. A type sent as a number is
#: read by its ordinal, so the order is part of the format.
ALL_BLOCK_TYPES: tuple[str, ...] = (
    TEXT, HEADING1, HEADING2, HEADING3, HEADING4,
    BULLET_LIST, NUMBERED_LIST, CHECKLIST, QUOTE,
    CODE, DIVIDER, IMAGE, COLUMN_GROUP, TWO_COLUMN,
    # "Sketch" is a retired block type that still holds its ordinal.
    EQUATION, PAGE, "Sketch", CALLOUT,
    TABLE, TABLE_ROW, TABLE_CELL,
)

#: Gives every Notion id the same Mnemo id on each run, so re-importing with the
#: Overwrite policy updates notes instead of duplicating them.
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "\x1f".join(parts)))


@dataclass(frozen=True)
class TextStyle:
    """
    The C# ``TextStyle``. Colours are design tokens such as ``"swatch5"``, never
    hex values, because Mnemo resolves them against the active theme.
    """

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    code: bool = False
    highlight: bool = False
    background_color: str | None = None
    foreground_color: str | None = None
    link_url: str | None = None
    suppress_auto_link: bool = False
    subscript: bool = False
    superscript: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "strikethrough": self.strikethrough,
            "code": self.code,
            "highlight": self.highlight,
        }
        if self.background_color is not None:
            out["backgroundColor"] = self.background_color
        if self.foreground_color is not None:
            out["foregroundColor"] = self.foreground_color
        if self.link_url is not None:
            out["linkUrl"] = self.link_url
        out["suppressAutoLink"] = self.suppress_auto_link
        if self.subscript:
            out["subscript"] = True
        if self.superscript:
            out["superscript"] = True
        return out


DEFAULT_STYLE = TextStyle()


@dataclass(frozen=True)
class TextSpan:
    text: str
    style: TextStyle = DEFAULT_STYLE

    def to_json(self) -> dict[str, Any]:
        return {"kind": "text", "text": self.text, "style": self.style.to_json()}

    @property
    def display_text(self) -> str:
        return self.text


@dataclass(frozen=True)
class EquationSpan:
    """Inline LaTeX. It takes one caret position in Mnemo, whatever its length."""

    latex: str
    style: TextStyle = DEFAULT_STYLE

    def to_json(self) -> dict[str, Any]:
        return {"kind": "equation", "latex": self.latex, "style": self.style.to_json()}

    @property
    def display_text(self) -> str:
        return self.latex


InlineSpan = TextSpan | EquationSpan


def plain(text: str = "") -> TextSpan:
    return TextSpan(text=text, style=DEFAULT_STYLE)


#: The one blank span a block needs when its content lives in the payload.
BLANK_SPANS: tuple[InlineSpan, ...] = (plain(""),)

#: Caret placeholders from Mnemo's old editor. Mnemo refuses to save them.
_SENTINELS = str.maketrans({"￼": None, "￹": None, "￺": None, "￻": None})


def normalize_spans(spans: Sequence[InlineSpan]) -> list[InlineSpan]:
    """
    Drops empty text spans and merges neighbours with the same style, as Mnemo
    does on load, so opening an imported note doesn't change it.
    """
    out: list[InlineSpan] = []
    for span in spans:
        if isinstance(span, TextSpan):
            text = span.text.translate(_SENTINELS)
            if not text:
                continue
            span = replace(span, text=text)
            if out and isinstance(out[-1], TextSpan) and out[-1].style == span.style:
                out[-1] = replace(out[-1], text=out[-1].text + text)
                continue
        out.append(span)
    return out or [plain("")]


def spans_text(spans: Iterable[InlineSpan]) -> str:
    """The visible text of a run, with equations as their LaTeX source."""
    return "".join(span.display_text for span in spans)


def empty_payload() -> dict[str, Any]:
    return {"kind": "empty"}


def equation_payload(latex: str) -> dict[str, Any]:
    return {"kind": "equation", "latex": latex}


def image_payload(path: str, alt: str = "", width: float = 0, align: str = "left") -> dict[str, Any]:
    return {"kind": "image", "path": path, "alt": alt, "width": width, "align": align}


def code_payload(
    language: str,
    source: str,
    wrap: bool = False,
    numbers: bool = False,
    caption: str = "",
) -> dict[str, Any]:
    return {
        "kind": "code",
        "language": language,
        "source": source,
        "wrap": wrap,
        "numbers": numbers,
        "caption": caption,
    }


def checklist_payload(checked: bool) -> dict[str, Any]:
    return {"kind": "checklist", "checked": checked}


def two_column_payload(split_ratio: float = 0.5) -> dict[str, Any]:
    return {"kind": "twoColumn", "splitRatio": split_ratio}


def page_payload(reference_note_id: str) -> dict[str, Any]:
    return {"kind": "page", "referenceNoteId": reference_note_id}


def callout_payload(emoji: str, tone: str = "note") -> dict[str, Any]:
    return {"kind": "callout", "emoji": emoji, "tone": tone}


def table_payload(
    column_widths: Sequence[float],
    header_rows: Sequence[bool],
    header_columns: Sequence[bool],
    full_width: bool = False,
) -> dict[str, Any]:
    return {
        "kind": "table",
        "columnWidths": list(column_widths),
        "headerRows": list(header_rows),
        "headerColumns": list(header_columns),
        "fullWidth": full_width,
    }


def table_cell_payload(fill: str = "") -> dict[str, Any]:
    return {"kind": "tableCell", "fill": fill}


@dataclass
class Block:
    """
    One node of a note's content tree. There is no ``sid``: Mnemo mints those
    itself, and an empty one marks the block as new.
    """

    type: str
    spans: list[InlineSpan] = field(default_factory=lambda: [plain("")])
    payload: dict[str, Any] = field(default_factory=empty_payload)
    children: list["Block"] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    meta: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "spans": [span.to_json() for span in normalize_spans(self.spans)],
            "payload": dict(self.payload),
            "meta": dict(self.meta),
            "order": self.order,
        }
        # Mnemo never writes an empty children array, so neither do we.
        if self.children:
            out["children"] = [
                _with_order(child, index).to_json() for index, child in enumerate(self.children)
            ]
        return out

    def walk(self) -> Iterable["Block"]:
        yield self
        for child in self.children:
            yield from child.walk()


def _with_order(block: Block, order: int) -> Block:
    block.order = order
    return block


def _iso(value: datetime) -> str:
    """UTC with milliseconds, the shape System.Text.Json reads as a DateTime."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class Note:
    note_id: str
    title: str
    blocks: list[Block] = field(default_factory=list)
    folder_id: str | None = None
    folder_path: str = ""
    parent_note_id: str | None = None
    order: int = 0
    emoji: str | None = None
    cover: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_favorite: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "noteId": self.note_id,
            # Mnemo mints sids on first save. One made up here could collide.
            "sid": "",
            "ver": 0,
            "title": self.title,
            "folderId": self.folder_id,
            "parentNoteId": self.parent_note_id,
            "order": self.order,
            "folderPath": self.folder_path,
            "content": self.plain_text(),
            "blocks": [
                _with_order(block, index).to_json() for index, block in enumerate(self.blocks)
            ],
            "createdAt": _iso(self.created_at),
            "modifiedAt": _iso(self.modified_at),
            "isFavorite": self.is_favorite,
            "emoji": self.emoji,
            "cover": self.cover,
            "tags": list(self.tags),
        }

    def plain_text(self) -> str:
        """The note as plain text, for the ``content`` field older exports read."""
        lines: list[str] = []
        for block in self.blocks:
            _flatten(block, lines)
        return "\n".join(lines).strip()


def _flatten(block: Block, into: list[str]) -> None:
    kind = block.payload.get("kind")
    if kind == "equation":
        into.append(block.payload.get("latex", ""))
    elif kind == "code":
        into.append(block.payload.get("source", ""))
    else:
        into.append(spans_text(block.spans))
    for child in block.children:
        _flatten(child, into)


@dataclass
class Folder:
    folder_id: str
    name: str
    parent_id: str | None = None
    order: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "folderId": self.folder_id,
            "name": self.name,
            "parentId": self.parent_id,
            "order": self.order,
        }
