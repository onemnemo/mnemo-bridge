"""
Writes a ``.mnemo`` package into Notion as real pages (content mapping is in ``reverse.py``).

Notion limits: 100 blocks per append, 1000 per request, two nesting levels.
Deeper children are appended to the created parent's id. Tables and column
lists cannot be created empty, so they carry their first rows or blocks inline.
Pages always land at the bottom of their parent, so sub-notes are created in
stream order when their ``Page`` block comes up. Upload ids expire after an
hour, so images are uploaded when attached.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .assets import ALLOWED_EXTENSIONS, MAX_FILE_BYTES
from .notion import NotionClient, NotionError
from .package import read_package
from .push_layout import (
    _PLACEHOLDER,
    TAKES_CHILDREN,
    _asset_index,
    _embeddable,
    _flatten_columns,
    _parents_first,
    _with_children_placed,
)
from .reverse import NotionNode, ReverseContext, note_to_nodes

#: Children per append request.
MAX_BATCH = 100
#: Blocks per request, nested ones included.
MAX_REQUEST_BLOCKS = 1000
#: Notion refuses bodies over 500 KB.
MAX_REQUEST_BYTES = 400_000

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass
class PushOptions:
    #: Off means image blocks degrade to placeholder text.
    upload_images: bool = True
    #: Stops after this many notes (trial run).
    limit: int | None = None


@dataclass
class PushResult:
    pages_created: int = 0
    blocks_written: int = 0
    images_uploaded: int = 0
    warnings: list[str] = field(default_factory=list)
    #: Mnemo note id -> created Notion page id.
    page_ids: dict[str, str] = field(default_factory=dict)


class NotionWriter:
    def __init__(
        self,
        client: NotionClient,
        *,
        options: PushOptions | None = None,
        progress: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self.client = client
        self.options = options or PushOptions()
        self.progress = progress
        self.result = PushResult()
        self._package_path = ""
        self._asset_entries: dict[str, zipfile.ZipInfo] = {}
        self._notes_by_id: dict[str, dict[str, Any]] = {}
        self._created: set[str] = set()
        self._notes_written = 0

    def push_package(self, package_path: str, parent_page_id: str) -> PushResult:
        _manifest, notes, folders, _asset_ids = read_package(package_path)
        self._package_path = package_path
        self._asset_entries = _asset_index(package_path)
        self._notes_by_id = {n["noteId"]: n for n in notes if n.get("noteId")}

        # Parents first, so a sub-folder listed before its parent still lands inside it.
        folder_pages: dict[str, str] = {}
        ordered = sorted(folders, key=lambda f: (f.get("order", 0), f.get("name", "")))
        for folder in _parents_first(ordered, "folderId", "parentId"):
            parent = folder_pages.get(folder.get("parentId") or "", parent_page_id)
            name = folder.get("name") or "Folder"
            try:
                page = self.client.create_page(parent, name)
            except NotionError as exc:
                # Its notes go where the folder would have.
                self.result.warnings.append(f"could not create folder page '{name}': {exc}")
                folder_pages[folder.get("folderId") or ""] = parent
                continue
            folder_pages[folder.get("folderId") or ""] = page["id"]
            self.result.pages_created += 1
            self.progress(f"Created folder page '{name}'")

        # Sub-notes are created from their parent's Page blocks instead.
        top_level = [n for n in notes if not n.get("parentNoteId")]
        sub_notes = [n for n in notes if n.get("parentNoteId")]

        for index, note in enumerate(top_level, start=1):
            target = folder_pages.get(note.get("folderId") or "", parent_page_id)
            self.progress(f"[{index}/{len(top_level)}] {note.get('title') or 'Untitled'}")
            self._write_note(note, target)

        # Sub-notes nobody referenced still get a page. Parents first so chains nest.
        for note in _parents_first(sub_notes, "noteId", "parentNoteId"):
            if (note.get("noteId") or "") in self._created:
                continue
            title = note.get("title") or "Untitled"
            parent_notion = self.result.page_ids.get(note.get("parentNoteId") or "")
            if parent_notion:
                target = parent_notion
                why = "it was not embedded in its parent's content, so it was added at the end of the parent page"
            else:
                target = folder_pages.get(note.get("folderId") or "", parent_page_id)
                why = "its parent note was not written, so it was placed in its folder instead"
            if self._write_note(note, target):
                self.result.warnings.append(f"sub-note '{title}': {why}")

        return self.result

    def _write_note(self, note: dict[str, Any], parent_page_id: str) -> str | None:
        note_id = note.get("noteId") or ""
        if note_id in self._created:
            return self.result.page_ids.get(note_id)
        if self.options.limit is not None and self._notes_written >= self.options.limit:
            return None
        self._created.add(note_id)
        self._notes_written += 1

        title = note.get("title") or "Untitled"
        emoji = note.get("emoji") or None
        try:
            page = self.client.create_page(parent_page_id, title, icon_emoji=emoji)
        except NotionError as exc:
            if emoji and exc.status == 400:
                # Notion accepts only emoji it has artwork for.
                try:
                    page = self.client.create_page(parent_page_id, title)
                except NotionError as retry_exc:
                    self.result.warnings.append(f"could not create page '{title}': {retry_exc}")
                    return None
                self.result.warnings.append(f"'{title}': Notion refused the icon {emoji}; created without it")
            else:
                self.result.warnings.append(f"could not create page '{title}': {exc}")
                return None

        page_id = page["id"]
        self.result.page_ids[note_id] = page_id
        self.result.pages_created += 1

        ctx = ReverseContext(resolve_image=self._resolve_image)
        nodes = note_to_nodes(note, ctx)
        self.result.warnings.extend(f"'{title}': {w}" for w in ctx.warnings)

        try:
            self._write_nodes(page_id, nodes, page_id)
        except NotionError as exc:
            self.result.warnings.append(f"page '{title}' was only partially written: {exc}")
        return page_id

    def _write_nodes(self, parent_id: str, nodes: Iterable[NotionNode], page_id: str) -> None:
        """
        Appends a node stream to one parent, in order.

        ``page_id`` is where a sub-page goes when ``parent_id`` is a block. A
        ``note_ref`` flushes first so the sub-page lands at the right position.
        """
        batch: list[dict[str, Any]] = []
        # (index into batch, node with children to append after creation)
        deferred: list[tuple[int, NotionNode]] = []
        blocks = 0
        weight = 0

        def flush() -> None:
            nonlocal batch, deferred, blocks, weight
            if not batch:
                return
            results = self._append(parent_id, batch)
            for index, node in deferred:
                created = results[index] if index < len(results) else None
                if created is not None:
                    self._append_deferred(created["id"], node, page_id)
            batch, deferred, blocks, weight = [], [], 0, 0

        for node in _with_children_placed(nodes):
            if node.note_ref is not None:
                flush()
                self._create_referenced_note(node.note_ref, page_id, nested=parent_id != page_id)
                continue
            if node.block is None:
                # Block-less structural node: splice its children in.
                flush()
                self._write_nodes(parent_id, node.children, page_id)
                continue

            serialized, has_deferred, count = self._serialize(node)
            size = len(json.dumps(serialized))
            if batch and (
                len(batch) >= MAX_BATCH
                or blocks + count > MAX_REQUEST_BLOCKS
                or weight + size > MAX_REQUEST_BYTES
            ):
                flush()
            batch.append(serialized)
            blocks += count
            weight += size
            if has_deferred:
                deferred.append((len(batch) - 1, node))
        flush()

    def _append(self, parent_id: str, batch: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        """
        Appends a batch, returning each block's created form (None if refused).

        A 400 means nothing was written, so retrying block by block is safe.
        """
        try:
            results = self.client.append_children(parent_id, batch)
        except NotionError as exc:
            if exc.status != 400:
                raise
            if len(batch) == 1:
                return [self._append_single(parent_id, batch[0], exc)]
            return [self._append_single(parent_id, block) for block in batch]
        self.result.blocks_written += len(batch)
        return list(results)

    def _append_single(
        self, parent_id: str, block: dict[str, Any], error: NotionError | None = None
    ) -> dict[str, Any] | None:
        if error is None:
            try:
                results = self.client.append_children(parent_id, [block])
                self.result.blocks_written += 1
                return results[0] if results else None
            except NotionError as exc:
                if exc.status != 400:
                    raise
                error = exc

        kind = block.get("type") or "block"
        icon = (block.get(kind) or {}).get("icon") if kind == "callout" else None
        if icon:
            plain = dict(block, callout={k: v for k, v in block["callout"].items() if k != "icon"})
            try:
                results = self.client.append_children(parent_id, [plain])
            except NotionError as exc:
                if exc.status != 400:
                    raise
                error = exc
            else:
                self.result.blocks_written += 1
                self.result.warnings.append("Notion refused a callout's icon; the callout was kept without it")
                return results[0] if results else None

        self.result.warnings.append(
            f"Notion refused a {kind.replace('_', ' ')} block, so it and anything inside it "
            f"were skipped: {error}"
        )
        return None

    def _create_referenced_note(self, note_ref: str, page_id: str, *, nested: bool) -> None:
        note = self._notes_by_id.get(note_ref)
        if note is None:
            self.result.warnings.append(
                "a page block references a note that is not in the package; skipped"
            )
            return
        if (note.get("noteId") or "") in self._created:
            self.result.warnings.append(
                f"note '{note.get('title')}' is embedded more than once; only the first became a page"
            )
            return
        if nested:
            self.result.warnings.append(
                f"sub-page '{note.get('title') or 'Untitled'}' sat inside a column or list; Notion "
                "only allows pages directly on a page, so it follows that block instead"
            )
        # Child of the page being written, not of the note's folder.
        self._write_note(note, page_id)

    def _serialize(self, node: NotionNode) -> tuple[dict[str, Any], bool, int]:
        """
        One node as a request-ready dict, whether anything is left for a
        follow-up append, and how many blocks the dict holds.

        Plain children always defer. Tables and column lists carry the least
        they need to be valid.
        """
        block = dict(node.block or {})
        if not node.inline_children:
            return block, bool(node.children), 1

        kind = block.get("type")
        if kind == "table":
            rows = node.children[:MAX_BATCH]
            block["table"] = dict(block["table"])
            block["table"]["children"] = [dict(row.block or {}) for row in rows]
            return block, len(node.children) > MAX_BATCH, 1 + len(rows)

        if kind == "column_list":
            columns = []
            any_deferred = False
            for column_node in node.children:
                kids = column_node.children
                first = kids[0] if kids else None
                if first is not None and _embeddable(first):
                    embedded = dict(first.block or {})
                    any_deferred = any_deferred or len(kids) > 1 or bool(first.children)
                else:
                    embedded = dict(_PLACEHOLDER)
                    any_deferred = any_deferred or bool(kids)
                column_block = dict(column_node.block or {})
                column_block["column"] = dict(column_block.get("column") or {})
                column_block["column"]["children"] = [embedded]
                columns.append(column_block)
            block["column_list"] = {"children": columns}
            return block, any_deferred, 1 + 2 * len(columns)

        # Unknown structural kind: defer its children.
        return block, bool(node.children), 1

    def _append_deferred(self, created_id: str, node: NotionNode, page_id: str) -> None:
        """Writes what a batch item could not carry, now that it has an id."""
        if not node.inline_children:
            self._write_nodes(created_id, node.children, page_id)
            return

        kind = (node.block or {}).get("type")
        if kind == "table":
            rows = [dict(row.block or {}) for row in node.children[MAX_BATCH:]]
            for start in range(0, len(rows), MAX_BATCH):
                self._append(created_id, rows[start : start + MAX_BATCH])
            return

        if kind == "column_list":
            # Fresh read: a cached listing would not include the just-created columns.
            columns = self.client.block_children_fresh(created_id)
            for column_node, created_column in zip(node.children, columns):
                self._fill_column(created_column["id"], column_node.children, page_id)

    def _fill_column(self, column_id: str, kids: list[NotionNode], page_id: str) -> None:
        first = kids[0] if kids else None
        placeholder_id: str | None = None
        if first is not None and _embeddable(first):
            rest = kids[1:]
            if first.children:
                if (first.block or {}).get("type") in TAKES_CHILDREN:
                    created = self.client.block_children_fresh(column_id)
                    if created:
                        self._write_nodes(created[0]["id"], first.children, page_id)
                else:
                    rest = first.children + rest
        else:
            rest = kids
            if rest:
                created = self.client.block_children_fresh(column_id)
                placeholder_id = created[0]["id"] if created else None

        if not rest:
            return
        # Notion cannot nest columns, so a nested split's contents are laid out in sequence.
        self._write_nodes(column_id, _flatten_columns(rest), page_id)
        if placeholder_id:
            try:
                self.client.delete_block(placeholder_id)
            except NotionError:
                pass  # a leftover empty line is harmless

    def _resolve_image(self, path: str) -> dict[str, Any] | None:
        if path.startswith(("http://", "https://")):
            return {"type": "external", "external": {"url": path}}
        if not self.options.upload_images:
            return None
        entry = self._asset_entries.get(path)
        if entry is None:
            return None
        extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if extension not in ALLOWED_EXTENSIONS:
            return None
        if entry.file_size > MAX_FILE_BYTES:
            self.result.warnings.append(
                f"image '{path}' is larger than Notion's {MAX_FILE_BYTES // (1024 * 1024)} MB upload limit"
            )
            return None
        # Read per image so a large package need not fit in memory.
        with zipfile.ZipFile(self._package_path) as archive:
            data = archive.read(entry)
        try:
            upload_id = self.client.upload_file(
                path.rsplit("/", 1)[-1], _CONTENT_TYPES.get(extension, "application/octet-stream"), data
            )
        except NotionError as exc:
            self.result.warnings.append(f"image upload failed: {exc}")
            return None
        self.result.images_uploaded += 1
        return {"type": "file_upload", "file_upload": {"id": upload_id}}
