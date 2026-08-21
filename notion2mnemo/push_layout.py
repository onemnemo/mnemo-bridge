"""Pure helpers for the Notion writer: node stream layout and package asset lookup."""

from __future__ import annotations

import zipfile
from typing import Any, Iterable, Iterator

from .package import ASSET_PREFIX, PAYLOAD_ROOT
from .reverse import NotionNode

#: Block types Notion lets carry children. Children of any other type are
#: written as siblings right after it, losing the indent but not the content.
TAKES_CHILDREN = frozenset(
    {
        "paragraph",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "quote",
        "callout",
        "synced_block",
        "column",
    }
)

_PLACEHOLDER = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}


def _embeddable(node: NotionNode) -> bool:
    """Whether a node can ride inside a new column as its one inline block."""
    return node.block is not None and node.note_ref is None and not node.inline_children


def _with_children_placed(nodes: Iterable[NotionNode]) -> Iterator[NotionNode]:
    """
    The stream, with children moved out from under blocks that cannot hold
    them. They follow their block instead, so nothing is lost.
    """
    for node in nodes:
        kind = (node.block or {}).get("type")
        if node.block is not None and not node.inline_children and node.children and kind not in TAKES_CHILDREN:
            yield NotionNode(block=node.block)
            yield from _with_children_placed(node.children)
        else:
            yield node


def _flatten_columns(nodes: Iterable[NotionNode]) -> list[NotionNode]:
    out: list[NotionNode] = []
    for node in nodes:
        if (node.block or {}).get("type") == "column_list":
            for column in node.children:
                out.extend(_flatten_columns(column.children))
        else:
            out.append(node)
    return out


def _parents_first(items: list[dict[str, Any]], id_key: str, parent_key: str) -> list[dict[str, Any]]:
    """
    ``items`` reordered so each comes after its parent, keeping the given order
    otherwise. An item whose parent is missing, or part of a cycle, keeps its
    place among the roots.
    """
    by_id = {item.get(id_key): item for item in items if item.get(id_key)}
    out: list[dict[str, Any]] = []
    placed: set[int] = set()

    def place(item: dict[str, Any], seen: set[int]) -> None:
        if id(item) in placed or id(item) in seen:
            return
        seen.add(id(item))
        parent = by_id.get(item.get(parent_key))
        if parent is not None:
            place(parent, seen)
        placed.add(id(item))
        out.append(item)

    for item in items:
        place(item, set())
    return out


def _asset_index(package_path: str) -> dict[str, zipfile.ZipInfo]:
    """The package's bundled images, keyed by asset id, without reading them."""
    prefix = f"{PAYLOAD_ROOT}/{ASSET_PREFIX}"
    with zipfile.ZipFile(package_path) as archive:
        return {
            info.filename[len(prefix) :]: info
            for info in archive.infolist()
            if info.filename.startswith(prefix) and not info.is_dir()
        }
