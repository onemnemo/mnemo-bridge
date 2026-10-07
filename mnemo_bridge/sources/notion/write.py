"""Write endpoints (Mnemo -> Notion), mixed into ``NotionClient``."""

from __future__ import annotations

from typing import Any

from .transport import API_ROOT


class NotionWriteMixin:
    """
    Needs ``request``, ``_send`` and ``cache_dir`` from ``NotionClient``.

    Writes bypass the cache: replaying a cached "created page" would make a
    re-run skip the write.
    """

    cache_dir: Any

    def _request_uncached(
        self, method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        cache_dir, self.cache_dir = self.cache_dir, None
        try:
            return self.request(method, path, body, **kwargs)  # type: ignore[attr-defined]
        finally:
            self.cache_dir = cache_dir

    def create_page(
        self,
        parent_page_id: str,
        title: str,
        *,
        icon_emoji: str | None = None,
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {
                "title": {"title": [{"type": "text", "text": {"content": title[:2000]}}]}
            },
        }
        if icon_emoji:
            body["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if children:
            body["children"] = children
        return self._request_uncached("POST", "/pages", body)

    def delete_block(self, block_id: str) -> None:
        """Moves a block to the trash."""
        self._request_uncached("DELETE", f"/blocks/{block_id}")

    def append_children(self, block_id: str, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Appends up to 100 blocks and returns the created blocks, in order."""
        data = self._request_uncached("PATCH", f"/blocks/{block_id}/children", {"children": children})
        return data.get("results", [])

    def upload_file(self, filename: str, content_type: str, data: bytes) -> str:
        """
        Uploads one file through Notion's File Upload API and returns the upload id.

        The id must be attached to a block within an hour or Notion archives it.
        """
        created = self._request_uncached(
            "POST",
            "/file_uploads",
            {"filename": filename, "content_type": content_type},
            # A duplicate upload object is never attached and expires after an hour.
            idempotent=True,
        )
        upload_id = created["id"]

        self._send(  # type: ignore[attr-defined]
            "POST",
            f"{API_ROOT}/file_uploads/{upload_id}/send",
            idempotent=False,
            label=f"uploading '{filename}'",
            files={"file": (filename, data, content_type)},
            # requests must set the multipart boundary itself; the session-level
            # application/json would corrupt the body.
            headers={"Content-Type": None},
        )
        return upload_id
