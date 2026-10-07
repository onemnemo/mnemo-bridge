"""Media, link and page-reference handlers for BlockConverter."""

from __future__ import annotations

from typing import Any

from ... import mnemo
from .assets import file_url
from ...mnemo import Block, InlineSpan, TextSpan, TextStyle, plain
from .richtext import convert_rich_text, rich_text_to_plain


class LinkHandlers:
    """Mixin: needs `colors`, `assets`, `stats`, `warnings` and `note_id_for_page`."""

    def _link_block(self, text: str, url: str, notion_id: str, prefix: str = "") -> list[Block]:
        """The fallback for a Notion block Mnemo has no shape for: keep the link."""
        label = f"{prefix}{text or url}"
        spans: list[InlineSpan] = (
            [TextSpan(text=label, style=TextStyle(link_url=url))] if url else [plain(label)]
        )
        return [Block(type=mnemo.TEXT, spans=spans, id=mnemo.stable_id("block", notion_id))]

    def _image(self, notion, data, depth):
        url = file_url(data)
        caption_spans = convert_rich_text(data.get("caption"), self.colors)
        caption = rich_text_to_plain(data.get("caption"))
        asset_id = self.assets.add(url, label=caption or url)
        if asset_id is None:
            return self._link_block(caption or "image", url, notion.get("id") or "", prefix="")
        self.stats.images += 1
        return [
            Block(
                type=mnemo.IMAGE,
                # Mnemo treats the caption line as authoritative and rewrites
                # `alt` from it on every save.
                spans=caption_spans or [plain("")],
                payload=mnemo.image_payload(asset_id, alt=caption),
                id=mnemo.stable_id("block", notion.get("id") or ""),
            )
        ]

    def _video(self, notion, data, depth):
        return self._media(notion, data, "video")

    def _audio(self, notion, data, depth):
        return self._media(notion, data, "audio")

    def _pdf(self, notion, data, depth):
        return self._media(notion, data, "PDF")

    def _file(self, notion, data, depth):
        return self._media(notion, data, "file")

    def _media(self, notion: dict[str, Any], data: dict[str, Any], noun: str) -> list[Block]:
        url = file_url(data)
        label = rich_text_to_plain(data.get("caption")) or data.get("name") or f"{noun}"
        if not url:
            self.warnings.append(f"{noun} block had no URL and was skipped")
            self.stats.drop(noun)
            return []
        if url.startswith("https://prod-files-secure") or "amazonaws.com" in url:
            # Uploaded files get signed URLs that expire within the hour.
            self.warnings.append(
                f"{noun} '{label}' is a Notion-hosted upload; its link expires. "
                "Download it from Notion and attach it manually."
            )
        return self._link_block(label, url, notion.get("id") or "")

    def _bookmark(self, notion, data, depth):
        url = str(data.get("url") or "")
        label = rich_text_to_plain(data.get("caption")) or url
        return self._link_block(label, url, notion.get("id") or "")

    def _embed(self, notion, data, depth):
        url = str(data.get("url") or "")
        label = rich_text_to_plain(data.get("caption")) or url
        return self._link_block(label, url, notion.get("id") or "")

    def _link_preview(self, notion, data, depth):
        url = str(data.get("url") or "")
        return self._link_block(url, url, notion.get("id") or "")

    def _child_page(self, notion, data, depth):
        page_id = notion.get("id") or ""
        note_id = self.note_id_for_page(page_id)
        if note_id:
            return [
                Block(
                    type=mnemo.PAGE,
                    spans=[plain("")],
                    payload=mnemo.page_payload(note_id),
                    id=mnemo.stable_id("block", page_id),
                )
            ]
        title = str(data.get("title") or "Untitled")
        self.warnings.append(f"sub-page '{title}' is outside the export; kept as a heading")
        return [
            Block(
                type=mnemo.HEADING3,
                spans=[plain(title)],
                id=mnemo.stable_id("block", page_id),
            )
        ]

    def _link_to_page(self, notion, data, depth):
        target = data.get("page_id") or data.get("database_id") or ""
        note_id = self.note_id_for_page(str(target)) if target else None
        if note_id:
            return [
                Block(
                    type=mnemo.PAGE,
                    spans=[plain("")],
                    payload=mnemo.page_payload(note_id),
                    id=mnemo.stable_id("block", notion.get("id") or ""),
                )
            ]
        url = f"https://www.notion.so/{str(target).replace('-', '')}" if target else ""
        return self._link_block("Linked page", url, notion.get("id") or "")
