"""
Notion image files -> Mnemo managed assets.

Mnemo stores an image as ``{32 hex}{ext}`` in its ``note-assets`` directory and a
note refers to it by that bare filename. Ids come from a content hash, so the
same picture on many pages is stored once and a second run gives the same
package. Mnemo's lookup feeds an extensionless id to a filesystem glob, so ids
must be hex only. Unsupported formats are converted to PNG when Pillow is
installed, and otherwise become a link.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
from dataclasses import dataclass, field
from typing import Callable

#: Extensions Mnemo's image store accepts, from `ManagedAssetStore.ImageExtensions`.
ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

#: `ManagedAssetStore.MaxFileBytes`. Package import does not check it, but a
#: larger asset could not be re-uploaded from the app.
MAX_FILE_BYTES = 20 * 1024 * 1024

_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
}

#: Magic-byte prefixes, checked before the content type because Notion's file host
#: often answers ``application/octet-stream``.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def _sniff(data: bytes) -> str | None:
    for prefix, extension in _SIGNATURES:
        if data.startswith(prefix):
            return extension
    # WEBP is RIFF-framed: "RIFF" then four size bytes then "WEBP".
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _extension_from_url(url: str) -> str | None:
    path = url.split("?", 1)[0].split("#", 1)[0]
    dot = path.rfind(".")
    if dot < 0:
        return None
    extension = path[dot:].lower()
    return extension if extension in ALLOWED_EXTENSIONS else None


def _to_png(data: bytes) -> bytes | None:
    """Re-encodes an unsupported image as PNG, when Pillow is available."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            buffer = io.BytesIO()
            image.convert("RGBA" if image.mode in ("P", "LA", "RGBA") else "RGB").save(
                buffer, format="PNG"
            )
            return buffer.getvalue()
    except Exception:  # a file Pillow cannot read is not an image we can carry
        return None


@dataclass
class AssetStore:
    """The images a package will carry, keyed by asset id. ``downloader`` is injected so tests need no network."""

    downloader: Callable[[str], tuple[bytes, str]]
    files: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Notion URL -> asset id, so one image used on many pages is fetched once.
    _by_url: dict[str, str] = field(default_factory=dict)

    def add(self, url: str, *, label: str = "") -> str | None:
        """Downloads an image and returns its asset id, or None (with a warning) if it cannot be carried."""
        if not url:
            return None
        if url in self._by_url:
            return self._by_url[url]

        where = f" ({label})" if label else ""
        try:
            data, content_type = self.downloader(url)
        except Exception as exc:
            self.warnings.append(f"could not download image{where}: {exc}")
            return None

        if not data:
            self.warnings.append(f"empty image{where}")
            return None

        extension = (
            _sniff(data)
            or _CONTENT_TYPE_EXTENSIONS.get(content_type.split(";", 1)[0].strip().lower())
            or _extension_from_url(url)
        )

        if extension is None:
            converted = _to_png(data)
            if converted is None:
                guessed = mimetypes.guess_extension(content_type.split(";", 1)[0]) or "unknown"
                self.warnings.append(
                    f"image{where} is a format Mnemo cannot store ({guessed}); "
                    "linked instead. Install Pillow to convert it automatically."
                )
                return None
            data, extension = converted, ".png"

        if len(data) > MAX_FILE_BYTES:
            self.warnings.append(
                f"image{where} is {len(data) // (1024 * 1024)} MB, over Mnemo's 20 MB "
                "asset limit; linked instead."
            )
            return None

        asset_id = hashlib.sha256(data).hexdigest()[:32] + extension
        self.files.setdefault(asset_id, data)
        self._by_url[url] = asset_id
        return asset_id


def file_url(node: dict) -> str:
    """The URL out of a Notion file object. Uploaded files (``file``) have signed, expiring URLs."""
    kind = node.get("type")
    if kind and isinstance(node.get(kind), dict):
        url = node[kind].get("url")
        if url:
            return str(url)
    for key in ("file", "external", "file_upload"):
        value = node.get(key)
        if isinstance(value, dict) and value.get("url"):
            return str(value["url"])
    return ""
