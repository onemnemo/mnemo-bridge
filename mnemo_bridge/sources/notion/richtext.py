"""
Notion ``rich_text`` -> Mnemo ``InlineSpan[]``.

An inline equation becomes an ``EquationSpan`` (an atom occupying one caret
position) rather than text, and keeps its bold or italic marks.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .colors import ColorMap
from ...mnemo import EquationSpan, InlineSpan, TextSpan, TextStyle, normalize_spans, plain


def _style(annotations: dict[str, Any], colors: ColorMap, link: str | None) -> TextStyle:
    foreground, background = colors.resolve(annotations.get("color"))
    return TextStyle(
        bold=bool(annotations.get("bold")),
        italic=bool(annotations.get("italic")),
        underline=bool(annotations.get("underline")),
        strikethrough=bool(annotations.get("strikethrough")),
        code=bool(annotations.get("code")),
        # A Notion highlight is a background colour; a token keeps the hue,
        # which Mnemo's single `highlight` boolean would lose.
        highlight=False,
        background_color=background,
        foreground_color=foreground,
        link_url=link or None,
        suppress_auto_link=False,
        subscript=False,
        superscript=False,
    )


def _mention_text(item: dict[str, Any]) -> str:
    """A mention's label. The fallbacks cover kinds where Notion sends an empty plain_text."""
    text = item.get("plain_text") or ""
    if text:
        return text
    mention = item.get("mention") or {}
    kind = mention.get("type")
    if kind == "date":
        date = mention.get("date") or {}
        start, end = date.get("start"), date.get("end")
        return f"{start} to {end}" if end else str(start or "")
    if kind == "user":
        return (mention.get("user") or {}).get("name") or "someone"
    if kind in {"page", "database"}:
        return (mention.get(kind) or {}).get("id") or ""
    if kind == "link_preview":
        return (mention.get("link_preview") or {}).get("url") or ""
    return ""


def convert_rich_text(
    rich_text: Sequence[dict[str, Any]] | None,
    colors: ColorMap,
    *,
    force_style: TextStyle | None = None,
) -> list[InlineSpan]:
    """
    Converts one Notion rich-text array into Mnemo spans.

    ``force_style`` is a block-level colour, applied to every run that has no
    colour of its own.
    """
    spans: list[InlineSpan] = []
    for item in rich_text or ():
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        annotations = item.get("annotations") or {}
        link = item.get("href")
        style = _style(annotations, colors, link)
        if force_style is not None:
            style = _merge(force_style, style)

        if kind == "equation":
            latex = (item.get("equation") or {}).get("expression") or ""
            if latex:
                spans.append(EquationSpan(latex=latex, style=style))
            continue

        if kind == "mention":
            text = _mention_text(item)
            if text:
                spans.append(TextSpan(text=text, style=style))
            continue

        # Unknown types fall back to `plain_text`, which every rich-text object has.
        text = (item.get("text") or {}).get("content")
        if text is None:
            text = item.get("plain_text") or ""
        if text:
            spans.append(TextSpan(text=text, style=style))

    return normalize_spans(spans)


def _merge(block_style: TextStyle, run_style: TextStyle) -> TextStyle:
    """A run's own colour wins; the block's colour fills in where the run has none."""
    from dataclasses import replace

    return replace(
        run_style,
        foreground_color=run_style.foreground_color or block_style.foreground_color,
        background_color=run_style.background_color or block_style.background_color,
    )


def block_color_style(color: str | None, colors: ColorMap) -> TextStyle | None:
    """The ``force_style`` for a Notion block colour, or None when it is default."""
    foreground, background = colors.resolve(color)
    if foreground is None and background is None:
        return None
    return TextStyle(foreground_color=foreground, background_color=background)


def rich_text_to_plain(rich_text: Iterable[dict[str, Any]] | None) -> str:
    """The bare text of a rich-text array. Non-object entries are skipped, not raised on."""
    if isinstance(rich_text, dict):
        rich_text = [rich_text]
    return "".join(
        item.get("plain_text") or ""
        for item in (rich_text or ())
        if isinstance(item, dict)
    )


def linked(text: str, url: str, colors: ColorMap) -> list[InlineSpan]:
    """One span of link text, for blocks Mnemo cannot model."""
    return [TextSpan(text=text or url, style=TextStyle(link_url=url))] if url else [plain(text)]
