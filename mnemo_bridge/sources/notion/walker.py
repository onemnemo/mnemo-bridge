"""
Walks a Notion workspace and produces Mnemo notes and folders.

A sub-page becomes a sub-note (``ParentNoteId`` plus a ``Page`` block), keeping
its nesting and in-page position. A database becomes a folder of notes.
Discovery goes through ``/search`` when no ids are given, so the whole hierarchy
is known before conversion and a ``child_page`` block can point at a real id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ... import mnemo
from .assets import AssetStore
from .colors import ColorMap
from .convert import BlockConverter, ConversionStats
from .ids import UNTITLED, _dashed, database_title, normalize_id, page_title
from ...mnemo import Block, Folder, Note
from .client import NotionClient
from .properties import property_table, tags

__all__ = [
    "UNTITLED",
    "WalkOptions",
    "WalkResult",
    "Walker",
    "database_title",
    "normalize_id",
    "page_title",
]


@dataclass
class WalkOptions:
    #: Empty places notes at the root of the notes tree.
    root_folder: str = "Notion"
    #: "table" or "none"; tags are extracted either way.
    database_properties: str = "table"
    include_databases: bool = True
    #: Off by default: covers are the bulkiest part of a typical export.
    covers: bool = False
    limit: int | None = None


@dataclass
class WalkResult:
    notes: list[Note] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: ConversionStats = field(default_factory=ConversionStats)
    skipped: int = 0


def _parse_time(*values: str | None) -> datetime:
    """The first of ``values`` that parses; the clock is a last resort because it makes exports differ."""
    for value in values:
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _icon_emoji(node: dict[str, Any]) -> str | None:
    icon = node.get("icon") or {}
    return icon.get("emoji") if icon.get("type") == "emoji" else None


class Walker:
    def __init__(
        self,
        client: NotionClient,
        colors: ColorMap,
        assets: AssetStore,
        options: WalkOptions,
        *,
        progress: Callable[[str], None] = lambda _message: None,
    ) -> None:
        self.client = client
        self.colors = colors
        self.assets = assets
        self.options = options
        self.progress = progress
        self.result = WalkResult()

        self._pages: dict[str, dict[str, Any]] = {}
        self._databases: dict[str, dict[str, Any]] = {}
        #: Pages this run writes; narrower than `_pages` under --limit.
        self._included: set[str] = set()
        self._folder_ids: dict[str, str] = {}
        self._folder_paths: dict[str, str] = {}
        self._root_folder_id: str | None = None

    def discover(self, page_ids: Iterable[str] = (), database_ids: Iterable[str] = ()) -> None:
        page_ids = [normalize_id(i) for i in page_ids]
        database_ids = [normalize_id(i) for i in database_ids]

        if not page_ids and not database_ids:
            self.progress("Searching the workspace...")
            for page in self.client.search_pages():
                self._pages[page["id"]] = page
            if self.options.include_databases:
                for database in self.client.search_databases():
                    self._databases[database["id"]] = database
        else:
            for page_id in page_ids:
                self._collect_page_tree(page_id)
            for database_id in database_ids:
                self._collect_database(database_id)

        self._pages = {k: v for k, v in self._pages.items() if not _is_trashed(v)}
        self._databases = {k: v for k, v in self._databases.items() if not _is_trashed(v)}
        self.progress(
            f"Found {len(self._pages)} page(s) and {len(self._databases)} database(s)."
        )

    def _collect_page_tree(self, page_id: str, depth: int = 0) -> None:
        """With explicit ids a page names only itself, so descendants are found by walking its blocks."""
        if page_id in self._pages:
            return
        if depth > 32:
            self.result.warnings.append(
                f"pages nested more than 32 deep below the chosen ones were not included (at {page_id})"
            )
            return
        try:
            page = self.client.get_page(page_id)
        except Exception as exc:
            self.result.warnings.append(f"could not read page {page_id}: {exc}")
            return
        self._pages[page_id] = page
        for block in self._iter_blocks(page_id):
            kind = block.get("type")
            if kind == "child_page":
                self._collect_page_tree(block["id"], depth + 1)
            elif kind == "child_database" and self.options.include_databases:
                self._collect_database(block["id"], depth + 1)

    def _iter_blocks(self, block_id: str) -> Iterable[dict[str, Any]]:
        """Every descendant block, flattened."""
        try:
            children = self.client.block_children(block_id)
        except Exception as exc:
            self.result.warnings.append(f"could not read children of {block_id}: {exc}")
            return
        for child in children:
            yield child
            # A child page owns its subtree.
            if child.get("has_children") and child.get("type") != "child_page":
                yield from self._iter_blocks(child["id"])

    def _collect_database(self, database_id: str, depth: int = 0) -> None:
        if database_id in self._databases:
            return
        try:
            database = self.client.get_database(database_id)
        except Exception as exc:
            self.result.warnings.append(f"could not read database {database_id}: {exc}")
            return
        self._databases[database_id] = database
        try:
            rows = self.client.query_database(database_id)
        except Exception as exc:
            self.result.warnings.append(f"could not query database {database_id}: {exc}")
            return
        for row in rows:
            if row.get("id") and row["id"] not in self._pages:
                self._collect_page_tree(row["id"], depth + 1)

    def convert(self) -> WalkResult:
        self._build_folders()

        pages = list(self._pages.values())
        if self.options.limit is not None:
            pages = pages[: self.options.limit]

        # A `Page` block reads its title from the referenced note, so only
        # pages that get written may be linked to.
        self._included = {page["id"] for page in pages}

        for index, page in enumerate(pages, start=1):
            title = page_title(page)
            self.progress(f"[{index}/{len(pages)}] {title}")
            try:
                self.result.notes.append(self._convert_page(page, index - 1))
            except Exception as exc:
                self.result.skipped += 1
                self.result.warnings.append(f"failed to convert page '{title}': {exc}")

        self.result.warnings.extend(self.assets.warnings)
        return self.result

    def _build_folders(self) -> None:
        if self.options.root_folder:
            self._root_folder_id = mnemo.stable_id("folder", "root", self.options.root_folder)
            self.result.folders.append(
                Folder(folder_id=self._root_folder_id, name=self.options.root_folder, order=0)
            )
            self._folder_paths[self._root_folder_id] = self.options.root_folder

        # A database nested inside a page is placed beside it: folders hold notes.
        for order, (database_id, database) in enumerate(sorted(self._databases.items())):
            folder_id = mnemo.stable_id("folder", database_id)
            parent_id = self._root_folder_id
            name = database_title(database)
            self._folder_ids[database_id] = folder_id
            self.result.folders.append(
                Folder(folder_id=folder_id, name=name, parent_id=parent_id, order=order + 1)
            )
            parent_path = self._folder_paths.get(parent_id or "", "")
            self._folder_paths[folder_id] = f"{parent_path} / {name}" if parent_path else name

    def _note_id_for_page(self, notion_page_id: str) -> str | None:
        normalized = normalize_id(notion_page_id)
        for candidate in (notion_page_id, normalized, _dashed(normalized)):
            if candidate in self._included:
                return mnemo.stable_id("note", candidate)
        return None

    def _convert_page(self, page: dict[str, Any], order: int) -> Note:
        page_id = page["id"]
        parent = page.get("parent") or {}
        parent_kind = parent.get("type")

        folder_id = self._root_folder_id
        parent_note_id: str | None = None

        if parent_kind in {"database_id", "data_source_id"}:
            database_id = parent.get("database_id") or parent.get("data_source_id") or ""
            folder_id = self._folder_ids.get(database_id, self._root_folder_id)
        elif parent_kind in {"page_id", "block_id"}:
            # A page inside a toggle, column or callout names that block as parent.
            if parent_kind == "page_id":
                parent_page_id = parent.get("page_id") or ""
            else:
                parent_page_id = self._owning_page(parent.get("block_id") or "") or ""
            parent_note_id = self._note_id_for_page(parent_page_id) if parent_page_id else None
            # A sub-note shares its parent's folder; nesting is by ParentNoteId.
            parent_page = self._pages.get(parent_page_id)
            if parent_page is not None:
                folder_id = self._folder_for_page(parent_page)

        converter = BlockConverter(
            colors=self.colors,
            assets=self.assets,
            children_of=self.client.block_children,
            note_id_for_page=self._note_id_for_page,
            warnings=self.result.warnings,
            stats=self.result.stats,
        )

        blocks: list[Block] = []
        if parent_kind in {"database_id", "data_source_id"} and self.options.database_properties == "table":
            table = property_table(page, self.colors)
            if table is not None:
                blocks.append(table)
        blocks.extend(converter.convert_blocks(self.client.block_children(page_id)))
        if not blocks:
            # An empty page still needs one editable block, with a stable id.
            blocks = [Block(type=mnemo.TEXT, id=mnemo.stable_id("empty", page_id))]

        cover = None
        if self.options.covers:
            cover_url = _cover_url(page)
            if cover_url:
                asset_id = self.assets.add(cover_url, label=f"cover of {page_title(page)}")
                if asset_id:
                    cover = f"asset:{asset_id}"

        return Note(
            note_id=mnemo.stable_id("note", page_id),
            title=page_title(page),
            blocks=blocks,
            folder_id=folder_id,
            folder_path=self._folder_paths.get(folder_id or "", ""),
            parent_note_id=parent_note_id,
            order=order,
            emoji=_icon_emoji(page),
            cover=cover,
            tags=tags(page),
            created_at=_parse_time(page.get("created_time"), page.get("last_edited_time")),
            modified_at=_parse_time(page.get("last_edited_time"), page.get("created_time")),
        )

    def _owning_page(self, block_id: str) -> str | None:
        """The page a block sits on, found by following block parents upward."""
        for _ in range(32):
            if not block_id:
                return None
            try:
                block = self.client.get_block(block_id)
            except Exception:
                return None
            parent = block.get("parent") or {}
            if parent.get("type") == "page_id":
                return parent.get("page_id")
            if parent.get("type") != "block_id":
                return None
            block_id = parent.get("block_id") or ""
        return None

    def _folder_for_page(self, page: dict[str, Any]) -> str | None:
        parent = page.get("parent") or {}
        if parent.get("type") in {"database_id", "data_source_id"}:
            database_id = parent.get("database_id") or parent.get("data_source_id") or ""
            return self._folder_ids.get(database_id, self._root_folder_id)
        if parent.get("type") == "page_id":
            grandparent = self._pages.get(parent.get("page_id") or "")
            if grandparent is not None and grandparent is not page:
                return self._folder_for_page(grandparent)
        return self._root_folder_id


def _cover_url(page: dict[str, Any]) -> str:
    cover = page.get("cover") or {}
    kind = cover.get("type")
    if kind and isinstance(cover.get(kind), dict):
        return str(cover[kind].get("url") or "")
    return ""


def _is_trashed(node: dict[str, Any]) -> bool:
    return bool(node.get("in_trash") or node.get("archived"))
