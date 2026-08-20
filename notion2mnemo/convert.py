"""
Notion blocks -> Mnemo blocks.

Notion puts colour on the block and Mnemo only on the run, so a block colour is
pushed into every span (``block_color_style``). Mnemo has no collapsible block, so
a toggle becomes a Text block with its contents as children. Blocks with no Mnemo
equivalent become a link rather than being dropped. Children come from the
injected ``children_of``, so conversion runs offline in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from . import mnemo
from .assets import AssetStore
from .colors import ColorMap
from .convert_layout import LayoutHandlers
from .convert_links import LinkHandlers
from .mnemo import Block, InlineSpan, TextSpan, TextStyle, plain
from .richtext import block_color_style, convert_rich_text, rich_text_to_plain

#: Notion code language -> Mnemo token. A language missing from Mnemo's picker
#: (`mnemo-web/src/notes/editor/code/languages.ts`) is passed through unchanged,
#: since Mnemo shows an unknown token verbatim.
CODE_LANGUAGES: dict[str, str] = {
    "plain text": "text",
    "c++": "cpp",
    "c#": "csharp",
    "objective-c": "objectivec",
    "shell": "bash",
    "docker": "bash",
    "makefile": "bash",
    "markup": "html",
    "vb.net": "text",
    "visual basic": "text",
    "f#": "text",
    "webassembly": "text",
    "java/c/c++/c#": "java",
    "sass": "css",
    "scss": "css",
    "less": "css",
    "protobuf": "text",
    "mermaid": "text",
}

#: Generated views that Mnemo renders its own way, so they get no placeholder.
SILENTLY_DROPPED = frozenset({"table_of_contents", "breadcrumb", "template"})

_DEFAULT_CALLOUT_EMOJI = "\N{ELECTRIC LIGHT BULB}"
_WARN_CALLOUT_EMOJI = "\N{WARNING SIGN}\N{VARIATION SELECTOR-16}"


@dataclass
class ConversionStats:
    blocks_in: int = 0
    blocks_out: int = 0
    images: int = 0
    equations: int = 0
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, kind: str) -> None:
        self.dropped[kind] = self.dropped.get(kind, 0) + 1



class BlockConverter(LayoutHandlers, LinkHandlers):
    """
    Converts one Notion page's block tree.

    :param children_of: returns a Notion block's children, given its id.
    :param note_id_for_page: the Mnemo note id a Notion page id was converted to,
        or None when that page is outside the export. Sub-page and page-link
        blocks become Page blocks when it resolves, and a link when it does not.
    """

    def __init__(
        self,
        *,
        colors: ColorMap,
        assets: AssetStore,
        children_of: Callable[[str], list[dict[str, Any]]],
        note_id_for_page: Callable[[str], str | None],
        warnings: list[str] | None = None,
        stats: ConversionStats | None = None,
        max_depth: int = 24,
    ) -> None:
        self.colors = colors
        self.assets = assets
        self.children_of = children_of
        self.note_id_for_page = note_id_for_page
        self.warnings = warnings if warnings is not None else []
        self.stats = stats or ConversionStats()
        self.max_depth = max_depth

    def convert_blocks(self, blocks: Sequence[dict[str, Any]], depth: int = 0) -> list[Block]:
        out: list[Block] = []
        for notion_block in blocks:
            out.extend(self.convert_block(notion_block, depth))
        return out

    def convert_children_of(self, block_id: str, depth: int) -> list[Block]:
        if depth >= self.max_depth:
            # Notion nests deeper than any layout can show; stop before a recursion error.
            self.warnings.append(f"stopped at nesting depth {self.max_depth} in block {block_id}")
            return []
        return self.convert_blocks(self._children(block_id), depth + 1)

    def _children(self, block_id: str) -> list[dict[str, Any]]:
        """A block's children, or none with a warning when they can't be read."""
        try:
            return self.children_of(block_id)
        except Exception as exc:
            self.warnings.append(f"could not read the contents of block {block_id}; they were skipped: {exc}")
            return []

    def convert_block(self, notion: dict[str, Any], depth: int = 0) -> list[Block]:
        kind = notion.get("type") or ""
        self.stats.blocks_in += 1
        handler = getattr(self, f"_{kind}", None)
        if handler is None:
            if kind in SILENTLY_DROPPED:
                self.stats.drop(kind)
                return []
            self.stats.drop(kind)
            self.warnings.append(f"unsupported Notion block type '{kind}' was skipped")
            return []
        blocks = handler(notion, notion.get(kind) or {}, depth)
        self.stats.blocks_out += len(blocks)
        return blocks

    def _spans(self, data: dict[str, Any], key: str = "rich_text", *, block_background: bool = True) -> list[InlineSpan]:
        force_style = block_color_style(data.get("color"), self.colors)
        if force_style is not None and not block_background:
            force_style = (
                TextStyle(foreground_color=force_style.foreground_color)
                if force_style.foreground_color
                else None
            )
        spans = convert_rich_text(data.get(key), self.colors, force_style=force_style)
        self.stats.equations += sum(1 for span in spans if not isinstance(span, TextSpan))
        return spans

    def _kids(self, notion: dict[str, Any], depth: int) -> list[Block]:
        if not notion.get("has_children"):
            return []
        block_id = notion.get("id") or ""
        return self.convert_children_of(block_id, depth) if block_id else []

    def _simple(
        self, notion: dict[str, Any], data: dict[str, Any], depth: int, block_type: str, payload=None
    ) -> list[Block]:
        return [
            Block(
                type=block_type,
                spans=self._spans(data),
                payload=payload or mnemo.empty_payload(),
                children=self._kids(notion, depth),
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _paragraph(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.TEXT)

    def _heading_1(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.HEADING1)

    def _heading_2(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.HEADING2)

    def _heading_3(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.HEADING3)

    def _bulleted_list_item(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.BULLET_LIST)

    def _numbered_list_item(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.NUMBERED_LIST)

    def _to_do(self, notion, data, depth):
        return self._simple(
            notion, data, depth, mnemo.CHECKLIST, mnemo.checklist_payload(bool(data.get("checked")))
        )

    def _quote(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.QUOTE)

    def _toggle(self, notion, data, depth):
        return self._simple(notion, data, depth, mnemo.TEXT)

    def _divider(self, notion, data, depth):
        return [Block(type=mnemo.DIVIDER, id=mnemo.stable_id("block", notion.get("id") or ""))]

    def _callout(self, notion, data, depth):
        icon = data.get("icon") or {}
        warn = ColorMap.is_warn(data.get("color"))
        emoji = icon.get("emoji") if icon.get("type") == "emoji" else None
        if not emoji:
            emoji = _WARN_CALLOUT_EMOJI if warn else _DEFAULT_CALLOUT_EMOJI
        return [
            Block(
                type=mnemo.CALLOUT,
                # The tone already carries the callout's background; pushing it
                # into the spans would highlight every word.
                spans=self._spans(data, block_background=False),
                payload=mnemo.callout_payload(emoji, "warn" if warn else "note"),
                children=self._kids(notion, depth),
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _code(self, notion, data, depth):
        source = rich_text_to_plain(data.get("rich_text"))
        language = str(data.get("language") or "").lower()
        caption = rich_text_to_plain(data.get("caption"))
        return [
            Block(
                type=mnemo.CODE,
                # Mnemo's reader backfills the payload source from the spans or the
                # reverse; writing both matches a block typed in the app.
                spans=[plain(source)],
                payload=mnemo.code_payload(
                    CODE_LANGUAGES.get(language, language or "text"), source, caption=caption
                ),
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _equation(self, notion, data, depth):
        latex = str(data.get("expression") or "")
        self.stats.equations += 1
        return [
            Block(
                type=mnemo.EQUATION,
                # Mnemo's reader blanks an equation block's spans; it renders from the payload.
                spans=[plain("")],
                payload=mnemo.equation_payload(latex),
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _synced_block(self, notion, data, depth):
        # Originals and copies both return the synced content from the children
        # endpoint, and every copy returns the same child ids, so copies are
        # re-keyed to keep block ids unique on a page.
        blocks = self._kids(notion, depth)
        if data.get("synced_from"):
            _rekey(blocks, notion.get("id") or "")
        return blocks

    def _child_database(self, notion, data, depth):
        # The rows become notes in a folder of their own (see `walker.py`).
        title = str(data.get("title") or "Database")
        return [
            Block(
                type=mnemo.TEXT,
                spans=[TextSpan(text=title, style=TextStyle(bold=True, italic=True))],
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _unsupported(self, notion, data, depth):
        self.stats.drop("unsupported")
        self.warnings.append(
            "a block Notion itself reports as unsupported by its API was skipped "
            "(usually a database view, button, or AI block)"
        )
        return []


def _rekey(blocks: list[Block], salt: str) -> None:
    """Gives a synced copy's blocks ids of their own, derived from the copy's id."""
    for block in blocks:
        block.id = mnemo.stable_id("synced", salt, block.id)
        _rekey(block.children, salt)
