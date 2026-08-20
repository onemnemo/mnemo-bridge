"""Notion id normalisation and page or database titles."""

from __future__ import annotations

from typing import Any

from .richtext import rich_text_to_plain

UNTITLED = "Untitled"


def page_title(page: dict[str, Any]) -> str:
    """
    A page's title. A database row keeps it in whichever property has type
    ``title`` (the name is the user's choice); a plain page uses ``title``.
    """
    properties = page.get("properties") or {}
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            text = rich_text_to_plain(prop.get("title"))
            if text.strip():
                return text.strip()
    title = properties.get("title")
    if isinstance(title, dict):
        text = rich_text_to_plain(title.get("title"))
        if text.strip():
            return text.strip()
    return UNTITLED


def database_title(database: dict[str, Any]) -> str:
    text = rich_text_to_plain(database.get("title")).strip()
    return text or UNTITLED


def normalize_id(value: str) -> str:
    """Accepts a bare id, a dashed id, or any Notion URL and returns the dashed id."""
    original = (value or "").strip()
    # Drop a block anchor (#...) and query string, then keep the last segment.
    text = original.split("#", 1)[0].split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    compact = text.replace("-", "")
    if len(compact) == 32 and _is_hex(compact):
        return _dashed(compact)
    # A slug: "My-Page-<32 hex>".
    tail = text.rsplit("-", 1)[-1]
    if len(tail) == 32 and _is_hex(tail):
        return _dashed(tail)
    return original


def _is_hex(text: str) -> bool:
    return all(c in "0123456789abcdefABCDEF" for c in text)


def _dashed(hex32: str) -> str:
    if len(hex32) != 32:
        return hex32
    return f"{hex32[:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:]}"
