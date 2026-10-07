"""
Mnemo blocks -> Notion blocks. Pure functions: dicts in, dicts out, warnings
appended to the context.

Notion nests at most two levels per write request, so this emits one node per
Mnemo block with its children kept separate. Kinds whose children must ride
along inline (table rows, columns) are marked; push.py owns the batching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .reverse_text import (
    BACKGROUND_TO_NOTION,
    FOREGROUND_TO_NOTION,
    MAX_EQUATION_LENGTH,
    MAX_RICH_TEXT_ITEMS,
    MAX_TEXT_LENGTH,
    ReverseContext,
    _capped,
    _chunks,
    _rich_text_pages,
    span_to_rich_text,
    spans_plain_text,
    spans_to_rich_text,
)

__all__ = [
    "BACKGROUND_TO_NOTION",
    "FOREGROUND_TO_NOTION",
    "MAX_TEXT_LENGTH",
    "NotionNode",
    "ReverseContext",
    "block_to_notion",
    "note_to_nodes",
    "span_to_rich_text",
]

#: Mnemo code language token -> Notion code block language. Only the spellings
#: that differ; everything else passes through and Notion falls back to plain
#: text for a name it does not know.
CODE_LANGUAGES_TO_NOTION: dict[str, str] = {
    "text": "plain text",
    "cpp": "c++",
    "csharp": "c#",
    "objectivec": "objective-c",
    "bash": "shell",
    "html": "html",
    "matlab": "matlab",
    "powershell": "powershell",
    "verilog": "verilog",
    "vhdl": "vhdl",
    "toml": "toml",  # not in Notion's list; passes through as-is and degrades gracefully
}

#: Callout tone -> Notion callout colour. Mnemo has exactly two tones.
CALLOUT_TONE_COLORS = {"note": "gray_background", "warn": "red_background"}



@dataclass
class NotionNode:
    """
    One Notion block plus its children, kept apart for the writer.

    ``inline_children`` marks kinds whose children must go in the same request:
    Notion rejects an empty table or column list. ``note_ref`` marks a Mnemo
    ``Page`` block, which produces no block; the writer creates a child page.
    """

    block: dict[str, Any] | None
    children: list["NotionNode"] = field(default_factory=list)
    inline_children: bool = False
    note_ref: str | None = None
    #: Overflow past Notion's 100-item rich-text cap, written right after this block.
    continuation: list["NotionNode"] = field(default_factory=list)



def block_to_notion(block: dict[str, Any], ctx: ReverseContext) -> NotionNode | None:
    """One Mnemo block as a NotionNode, or None when it has nothing to write."""
    block_type = block.get("type") or "Text"
    payload = block.get("payload") or {}
    handler = _HANDLERS.get(block_type, _paragraph)
    node = handler(block, payload, ctx)
    if node is None or node.inline_children:
        # The handler already consumed the children; converting again would duplicate them.
        return node
    for child in block.get("children") or []:
        child_node = block_to_notion(child, ctx)
        if child_node is not None:
            node.children.append(child_node)
    if node.continuation:
        # A block-less node splices the overflow in as siblings after this block and its children.
        continuation, node.continuation = node.continuation, []
        return NotionNode(block=None, children=[node, *continuation])
    return node


def _rich_body(kind: str, block: dict[str, Any], ctx: ReverseContext, **extra: Any) -> NotionNode:
    pages = _rich_text_pages(spans_to_rich_text(block.get("spans"), ctx))
    body = {"rich_text": pages[0], **extra}
    node = NotionNode(block={"object": "block", "type": kind, kind: body})
    # Overflow continues as plain paragraphs: a repeated bullet or heading would change the structure.
    node.continuation = [
        NotionNode(block={"object": "block", "type": "paragraph", "paragraph": {"rich_text": page}})
        for page in pages[1:]
    ]
    return node


def _code_nodes(text: str, language: str, caption: list[dict[str, Any]] | None = None) -> NotionNode:
    """A code block, split when the source passes 100 runs of 2000 characters. The caption goes on the last."""
    chunks = _chunks(text, MAX_TEXT_LENGTH)
    groups = [chunks[i : i + MAX_RICH_TEXT_ITEMS] for i in range(0, len(chunks), MAX_RICH_TEXT_ITEMS)]
    nodes = []
    for index, group in enumerate(groups):
        body: dict[str, Any] = {
            "rich_text": [{"type": "text", "text": {"content": chunk}} for chunk in group],
            "language": language,
        }
        if caption and index == len(groups) - 1:
            body["caption"] = caption
        nodes.append(NotionNode(block={"object": "block", "type": "code", "code": body}))
    node = nodes[0]
    node.continuation = nodes[1:]
    return node


def _paragraph(block, payload, ctx):
    return _rich_body("paragraph", block, ctx)


def _heading(level: int):
    def handler(block, payload, ctx):
        # Notion has three heading levels; Mnemo's fourth becomes the third.
        kind = f"heading_{min(level, 3)}"
        return _rich_body(kind, block, ctx)

    return handler


def _bullet(block, payload, ctx):
    return _rich_body("bulleted_list_item", block, ctx)


def _numbered(block, payload, ctx):
    return _rich_body("numbered_list_item", block, ctx)


def _checklist(block, payload, ctx):
    return _rich_body("to_do", block, ctx, checked=bool(payload.get("checked")))


def _quote(block, payload, ctx):
    return _rich_body("quote", block, ctx)


def _divider(block, payload, ctx):
    return NotionNode(block={"object": "block", "type": "divider", "divider": {}})


def _callout(block, payload, ctx):
    tone = payload.get("tone") or "note"
    node = _rich_body(
        "callout",
        block,
        ctx,
        color=CALLOUT_TONE_COLORS.get(tone, "gray_background"),
    )
    emoji = payload.get("emoji") or ""
    if emoji:
        node.block["callout"]["icon"] = {"type": "emoji", "emoji": emoji}
    return node


def _code(block, payload, ctx):
    source = payload.get("source") or spans_plain_text(block.get("spans"))
    language = CODE_LANGUAGES_TO_NOTION.get(payload.get("language") or "", payload.get("language") or "plain text")
    caption = payload.get("caption") or ""
    caption_rich = None
    if caption:
        caption_rich = [
            {"type": "text", "text": {"content": chunk}} for chunk in _chunks(caption, MAX_TEXT_LENGTH)
        ]
        caption_rich = _capped(caption_rich, ctx, "a code block's caption")
    return _code_nodes(source, language, caption_rich)


def _equation(block, payload, ctx):
    latex = payload.get("latex") or ""
    if len(latex) > MAX_EQUATION_LENGTH:
        ctx.warnings.append(
            f"a block equation of {len(latex)} characters exceeds Notion's limit; kept as a code block"
        )
        return _code_nodes(latex, "latex")
    return NotionNode(block={"object": "block", "type": "equation", "equation": {"expression": latex}})


def _image(block, payload, ctx):
    path = payload.get("path") or ""
    file_object = ctx.resolve_image(path) if path else None
    if file_object is None:
        caption = spans_plain_text(block.get("spans")) or path or "image"
        ctx.warnings.append(f"image '{path}' could not be carried to Notion; kept as text")
        pieces = [
            {"type": "text", "text": {"content": chunk}}
            for chunk in _chunks(f"[image: {caption}]", MAX_TEXT_LENGTH)
        ]
        return NotionNode(
            block={
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _capped(pieces, ctx, "an image's caption")},
            }
        )
    body = dict(file_object)
    caption_rich = spans_to_rich_text(block.get("spans"), ctx)
    if caption_rich and spans_plain_text(block.get("spans")).strip():
        body["caption"] = _capped(caption_rich, ctx, "an image's caption")
    return NotionNode(block={"object": "block", "type": "image", "image": body})


def _table(block, payload, ctx):
    rows = []
    width = 0
    for row in block.get("children") or []:
        if row.get("type") != "TableRow":
            continue
        cells = [
            _capped(spans_to_rich_text(cell.get("spans"), ctx), ctx, "a table cell")
            for cell in row.get("children") or []
            if cell.get("type") == "TableCell"
        ]
        width = max(width, len(cells))
        rows.append(cells)
    if not rows or width == 0:
        return None

    # Notion requires every row to have the same number of cells.
    for cells in rows:
        while len(cells) < width:
            cells.append([])

    header_rows = payload.get("headerRows") or []
    header_columns = payload.get("headerColumns") or []
    if any(header_rows[1:]) or any(header_columns[1:]):
        # Notion can only mark the first row and column as headers.
        ctx.warnings.append(
            "a table marks a non-first row or column as a header, which Notion cannot represent"
        )

    row_nodes = [
        NotionNode(
            block={
                "object": "block",
                "type": "table_row",
                "table_row": {"cells": cells},
            }
        )
        for cells in rows
    ]
    table_block = {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": bool(header_rows[0] if header_rows else False),
            "has_row_header": bool(header_columns[0] if header_columns else False),
        },
    }
    return NotionNode(block=table_block, children=row_nodes, inline_children=True)


def _two_column(block, payload, ctx):
    groups = [child for child in block.get("children") or [] if child.get("type") == "ColumnGroup"]
    if len(groups) < 2:
        # Malformed split: emit the contents in order. inline_children stops
        # block_to_notion from converting the column groups again.
        node = NotionNode(block=None, inline_children=True)
        for group in groups:
            for child in group.get("children") or []:
                child_node = block_to_notion(child, ctx)
                if child_node is not None:
                    node.children.append(child_node)
        return node

    ratio = payload.get("splitRatio")
    ratios = [ratio, 1 - ratio] if isinstance(ratio, (int, float)) and 0 < ratio < 1 else [None, None]

    if len(groups) > 2:
        # Mnemo allows exactly two columns; extras are merged into the second.
        ctx.warnings.append("a two-column block had more than two columns; the extras joined the second")
        groups = [groups[0], {"children": [c for g in groups[1:] for c in g.get("children") or []]}]

    column_nodes = []
    for group, width_ratio in zip(groups, ratios):
        children = []
        for child in group.get("children") or []:
            child_node = block_to_notion(child, ctx)
            if child_node is not None:
                children.append(child_node)
        if not children:
            # Notion rejects an empty column.
            children = [
                NotionNode(block={"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}})
            ]
        column: dict[str, Any] = {"object": "block", "type": "column", "column": {}}
        if width_ratio is not None:
            column["column"]["width_ratio"] = round(float(width_ratio), 4)
        column_nodes.append(NotionNode(block=column, children=children, inline_children=True))

    return NotionNode(
        block={"object": "block", "type": "column_list", "column_list": {}},
        children=column_nodes,
        inline_children=True,
    )


def _page(block, payload, ctx):
    reference = payload.get("referenceNoteId") or ""
    if not reference:
        return None
    return NotionNode(block=None, note_ref=reference)


_HANDLERS: dict[str, Callable[[dict, dict, ReverseContext], NotionNode | None]] = {
    "Text": _paragraph,
    "Heading1": _heading(1),
    "Heading2": _heading(2),
    "Heading3": _heading(3),
    "Heading4": _heading(4),
    "BulletList": _bullet,
    "NumberedList": _numbered,
    "Checklist": _checklist,
    "Quote": _quote,
    "Code": _code,
    "Divider": _divider,
    "Image": _image,
    "Equation": _equation,
    "Callout": _callout,
    "Table": _table,
    "TwoColumn": _two_column,
    "Page": _page,
    # A stray cell, row or column group outside its container becomes a paragraph.
    "TableRow": _paragraph,
    "TableCell": _paragraph,
    "ColumnGroup": _paragraph,
}


def note_to_nodes(note: dict[str, Any], ctx: ReverseContext) -> list[NotionNode]:
    """A whole note's blocks as an ordered list of NotionNodes."""
    nodes = []
    for block in note.get("blocks") or []:
        node = block_to_notion(block, ctx)
        if node is not None:
            nodes.append(node)
    return nodes
