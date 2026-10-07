"""Database row properties: the property table, and tags from label-like properties."""

from __future__ import annotations

from typing import Any

from ... import mnemo
from .colors import ColorMap
from ...mnemo import Block, TextSpan, TextStyle, plain
from .richtext import convert_rich_text


def property_table(page: dict[str, Any], colors: ColorMap) -> Block | None:
    """A database row's properties as a two-column table, or None when none are set."""
    page_id = page.get("id") or ""
    rows: list[Block] = []
    for name, prop in sorted((page.get("properties") or {}).items()):
        if not isinstance(prop, dict) or prop.get("type") == "title":
            continue
        value_spans = property_spans(prop, colors)
        if not value_spans:
            continue
        # Keyed by name, not index, so adding a property keeps the other ids.
        rows.append(
            Block(
                type=mnemo.TABLE_ROW,
                id=mnemo.stable_id("prop-row", page_id, name),
                children=[
                    Block(
                        type=mnemo.TABLE_CELL,
                        spans=[TextSpan(text=name, style=TextStyle(bold=True))],
                        payload=mnemo.table_cell_payload(),
                        id=mnemo.stable_id("prop-key", page_id, name),
                    ),
                    Block(
                        type=mnemo.TABLE_CELL,
                        spans=value_spans,
                        payload=mnemo.table_cell_payload(),
                        id=mnemo.stable_id("prop-value", page_id, name),
                    ),
                ],
            )
        )
    if not rows:
        return None
    return Block(
        type=mnemo.TABLE,
        payload=mnemo.table_payload([], [False] * len(rows), [True, False]),
        children=rows,
        id=mnemo.stable_id("prop-table", page_id),
    )


def property_spans(prop: dict[str, Any], colors: ColorMap) -> list:
    """One property's value as Mnemo spans, or an empty list when unset."""
    kind = prop.get("type")
    value = prop.get(kind)

    if kind == "rich_text":
        return convert_rich_text(value, colors) if value else []
    if kind in {"number"}:
        return [plain(str(value))] if value is not None else []
    if kind in {"select", "status"}:
        return [plain(str((value or {}).get("name") or ""))] if value else []
    if kind == "multi_select":
        names = [str(item.get("name") or "") for item in (value or [])]
        return [plain(", ".join(n for n in names if n))] if names else []
    if kind == "date":
        if not value:
            return []
        start, end = value.get("start"), value.get("end")
        return [plain(f"{start} to {end}" if end else str(start or ""))]
    if kind == "checkbox":
        return [plain("✓" if value else "✗")]
    if kind in {"url", "email", "phone_number"}:
        if not value:
            return []
        href = str(value)
        if kind == "email":
            href = f"mailto:{value}"
        elif kind == "phone_number":
            href = f"tel:{value}"
        return [TextSpan(text=str(value), style=TextStyle(link_url=href))]
    if kind in {"people", "created_by", "last_edited_by"}:
        people = value if isinstance(value, list) else [value]
        names = [str((p or {}).get("name") or "") for p in people if p]
        return [plain(", ".join(n for n in names if n))] if any(names) else []
    if kind == "files":
        names = [str(item.get("name") or "") for item in (value or [])]
        return [plain(", ".join(n for n in names if n))] if names else []
    if kind in {"created_time", "last_edited_time"}:
        return [plain(str(value))] if value else []
    if kind == "formula":
        inner = (value or {}).get((value or {}).get("type") or "", None)
        return [plain(str(inner))] if inner not in (None, "") else []
    if kind == "rollup":
        rollup_type = (value or {}).get("type")
        inner = (value or {}).get(rollup_type or "")
        if isinstance(inner, list):
            return [plain(f"{len(inner)} item(s)")] if inner else []
        return [plain(str(inner))] if inner not in (None, "") else []
    if kind == "relation":
        return [plain(f"{len(value)} linked page(s)")] if value else []
    if kind == "unique_id":
        prefix = (value or {}).get("prefix") or ""
        number = (value or {}).get("number")
        return [plain(f"{prefix}-{number}" if prefix else str(number))] if number is not None else []
    if kind == "verification":
        state = (value or {}).get("state")
        return [plain(str(state))] if state else []
    if value in (None, "", [], {}):
        return []
    return [plain(str(value))]


def tags(page: dict[str, Any]) -> list[str]:
    """Select, multi-select and status values become Mnemo tags."""
    tags: list[str] = []
    for prop in (page.get("properties") or {}).values():
        if not isinstance(prop, dict):
            continue
        kind = prop.get("type")
        if kind in {"select", "status"}:
            name = (prop.get(kind) or {}).get("name")
            if name:
                tags.append(str(name))
        elif kind == "multi_select":
            tags.extend(str(item.get("name")) for item in (prop.get(kind) or []) if item.get("name"))
    # Sorted so a re-export does not reorder tags.
    return sorted(dict.fromkeys(tags))
