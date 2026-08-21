"""Rich-text layer of the Mnemo -> Notion mapping: spans, colours, Notion length caps."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

#: Notion counts in UTF-16 units, so an emoji costs two.
MAX_TEXT_LENGTH = 2000
#: Notion's cap on an equation expression.
MAX_EQUATION_LENGTH = 1000
#: Notion's cap on the number of rich-text objects in one array.
MAX_RICH_TEXT_ITEMS = 100

#: Inverse of `colors.TEXT_COLORS`, extended to tokens the forward direction
#: never produces. Tokens the forward direction merged (pink and red both
#: become swatch5) map to the nearest Notion colour.
FOREGROUND_TO_NOTION: dict[str, str] = {
    "swatch1": "gray",    # stone
    "swatch2": "purple",  # violet
    "swatch3": "blue",
    "swatch4": "purple",
    "swatch5": "red",
    "swatch6": "green",
    "swatch7": "yellow",  # goldenrod
    "swatch8": "orange",
    "swatch9": "blue",
    "swatch10": "green",  # teal
}

BACKGROUND_TO_NOTION: dict[str, str] = {
    "swatch1": "gray_background",
    "swatch2": "purple_background",
    "swatch3": "blue_background",
    "swatch4": "purple_background",
    "swatch5": "red_background",    # blush sits nearer Notion's red tint than its pink
    "swatch6": "green_background",
    "swatch7": "yellow_background",
    "swatch8": "orange_background",
    "swatch9": "blue_background",
    "swatch10": "green_background",
}


@dataclass
class ReverseContext:
    """
    State for one note's conversion.

    ``resolve_image`` maps a Mnemo image reference (asset id or remote URL) to a
    Notion file object, or None. The caller owns it because uploads need a
    network. ``warnings`` collects everything that degraded.
    """

    resolve_image: Callable[[str], dict[str, Any] | None]
    warnings: list[str] = field(default_factory=list)


def _annotations(style: dict[str, Any]) -> dict[str, Any]:
    """
    A Mnemo ``TextStyle`` as Notion annotations.

    Notion holds one colour per run, either text or background. A span with
    both keeps the background. A bare ``highlight`` flag becomes yellow.
    """
    color = "default"
    fg = style.get("foregroundColor")
    bg = style.get("backgroundColor")
    if fg and fg in FOREGROUND_TO_NOTION:
        color = FOREGROUND_TO_NOTION[fg]
    if bg and bg in BACKGROUND_TO_NOTION:
        color = BACKGROUND_TO_NOTION[bg]
    elif style.get("highlight"):
        color = "yellow_background"

    return {
        "bold": bool(style.get("bold")),
        "italic": bool(style.get("italic")),
        "strikethrough": bool(style.get("strikethrough")),
        "underline": bool(style.get("underline")),
        "code": bool(style.get("code")),
        "color": color,
    }


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _joins_previous(char: str) -> bool:
    """A character that belongs to the one before it, so must not start a chunk."""
    code = ord(char)
    return (
        unicodedata.combining(char) != 0
        or code == 0x200D  # zero-width joiner
        or 0xFE00 <= code <= 0xFE0F  # variation selectors
        or 0x1F3FB <= code <= 0x1F3FF  # skin tones
        or 0xE0020 <= code <= 0xE007F  # tag sequences (flags)
    )


def _chunks(text: str, size: int) -> list[str]:
    """
    ``text`` cut into pieces of at most ``size`` UTF-16 units, without splitting
    a multi-code-point emoji (family, flag, skin tone) across pieces.
    """
    if not text:
        return [""]
    out: list[str] = []
    start = 0
    while start < len(text):
        end, units = start, 0
        while end < len(text):
            cost = 2 if ord(text[end]) > 0xFFFF else 1
            if units + cost > size:
                break
            units += cost
            end += 1
        if end < len(text):
            cut = end
            while cut > start + 1 and (_joins_previous(text[cut]) or text[cut - 1] == "\u200d"):
                cut -= 1
            # Joiners longer than the whole chunk: cut anyway.
            if cut > start + 1 or not _joins_previous(text[cut]):
                end = cut
        out.append(text[start:end])
        start = end
    return out


def _same_run(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a.get("type") == "text"
        and b.get("type") == "text"
        and a.get("annotations") == b.get("annotations")
        and (a["text"].get("link") or None) == (b["text"].get("link") or None)
    )


def _merge_runs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adjacent runs with identical styling joined, up to the length cap."""
    out: list[dict[str, Any]] = []
    for item in items:
        if out and _same_run(out[-1], item):
            joined = out[-1]["text"]["content"] + item["text"]["content"]
            if _utf16_len(joined) <= MAX_TEXT_LENGTH:
                out[-1] = dict(out[-1], text=dict(out[-1]["text"], content=joined))
                continue
        out.append(item)
    return out


def _rich_text_pages(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rich text split into arrays Notion accepts: at most 100 items each."""
    items = _merge_runs(items)
    if len(items) <= MAX_RICH_TEXT_ITEMS:
        return [items]
    return [items[i : i + MAX_RICH_TEXT_ITEMS] for i in range(0, len(items), MAX_RICH_TEXT_ITEMS)]


def _capped(items: list[dict[str, Any]], ctx: "ReverseContext", where: str) -> list[dict[str, Any]]:
    """Rich text for a slot that cannot spill into another block (a cell, a caption)."""
    items = _merge_runs(items)
    if len(items) > MAX_RICH_TEXT_ITEMS:
        ctx.warnings.append(
            f"{where} has more differently formatted pieces than Notion allows; "
            "the formatting of the last ones was dropped"
        )
        tail = "".join(_plain_of(item) for item in items[MAX_RICH_TEXT_ITEMS - 1 :])
        items = items[: MAX_RICH_TEXT_ITEMS - 1]
        pieces = _chunks(tail, MAX_TEXT_LENGTH)
        if len(pieces) > 1:
            ctx.warnings.append(f"{where} is longer than Notion allows; the end was cut")
        items.append({"type": "text", "text": {"content": pieces[0]}})
    return items


def _plain_of(item: dict[str, Any]) -> str:
    if item.get("type") == "equation":
        return item["equation"].get("expression") or ""
    return item.get("text", {}).get("content") or ""


def span_to_rich_text(span: dict[str, Any], ctx: ReverseContext) -> list[dict[str, Any]]:
    """One Mnemo span as one or more Notion rich-text objects."""
    style = span.get("style") or {}
    annotations = _annotations(style)
    kind = (span.get("kind") or "text").lower()

    if kind == "equation":
        latex = span.get("latex") or ""
        if not latex:
            return []
        if len(latex) > MAX_EQUATION_LENGTH:
            ctx.warnings.append(
                f"an inline equation of {len(latex)} characters exceeds Notion's "
                f"{MAX_EQUATION_LENGTH}-character limit; kept as code text"
            )
            code_annotations = dict(annotations, code=True)
            return [
                {"type": "text", "text": {"content": chunk}, "annotations": code_annotations}
                for chunk in _chunks(latex, MAX_TEXT_LENGTH)
            ]
        return [{"type": "equation", "equation": {"expression": latex}, "annotations": annotations}]

    if kind == "fraction":
        numerator = span.get("numerator", 0)
        denominator = span.get("denominator", 1)
        return [
            {
                "type": "equation",
                "equation": {"expression": f"\\frac{{{numerator}}}{{{denominator}}}"},
                "annotations": annotations,
            }
        ]

    text = span.get("text") or ""
    if not text:
        return []
    link = style.get("linkUrl")
    out = []
    for chunk in _chunks(text, MAX_TEXT_LENGTH):
        item: dict[str, Any] = {"type": "text", "text": {"content": chunk}, "annotations": annotations}
        if link:
            item["text"]["link"] = {"url": link}
        out.append(item)
    return out


def spans_to_rich_text(spans: list[dict[str, Any]] | None, ctx: ReverseContext) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for span in spans or []:
        out.extend(span_to_rich_text(span, ctx))
    return out


def spans_plain_text(spans: list[dict[str, Any]] | None) -> str:
    parts = []
    for span in spans or []:
        if span.get("kind") == "equation":
            parts.append(span.get("latex") or "")
        else:
            parts.append(span.get("text") or "")
    return "".join(parts)
