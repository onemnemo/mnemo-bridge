"""
Writes a ``.mnemo`` package, as defined by ``MnemoPackageService`` in ``Mnemo.Infrastructure``.

Layout: ``manifest.json``, ``payloads/notes/notes.db`` (SQLite, each row an id
plus a JSON object) and ``payloads/notes/assets/note-assets/{32 hex}{ext}``.

``manifest.entries[].path`` must be ``payloads/{payloadType}``: import selects
a payload's files by that prefix and otherwise reports "missing notes.db". Assets
sit under the payload root, so a note refers to an image by its bare id.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .mnemo import Folder, Note

PAYLOAD_TYPE = "notes"
PAYLOAD_ROOT = f"payloads/{PAYLOAD_TYPE}"
ASSET_PREFIX = "assets/note-assets/"

#: Guard against a crafted package that inflates to gigabytes when read.
MAX_DB_BYTES = 512 * 1024 * 1024

#: Fixed so unchanged input produces byte-identical packages.
_ZIP_TIMESTAMP = (2000, 1, 1, 0, 0, 0)


def build_notes_db(notes: Sequence[Note], folders: Sequence[Folder]) -> bytes:
    """The ``notes.db`` payload bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "notes.db"
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS Notes (
                    NoteId TEXT PRIMARY KEY,
                    Json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS Folders (
                    FolderId TEXT PRIMARY KEY,
                    Json TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT OR REPLACE INTO Notes (NoteId, Json) VALUES (?, ?)",
                [
                    (note.note_id, json.dumps(note.to_json(), ensure_ascii=False))
                    for note in notes
                ],
            )
            connection.executemany(
                "INSERT OR REPLACE INTO Folders (FolderId, Json) VALUES (?, ?)",
                [
                    (folder.folder_id, json.dumps(folder.to_json(), ensure_ascii=False))
                    for folder in folders
                ],
            )
            connection.commit()
        finally:
            connection.close()
        return path.read_bytes()


def build_manifest(
    note_count: int, app_version: str, created_at: datetime | None = None
) -> dict:
    stamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "format": "mnemo-package",
        "version": 1,
        "createdAtUtc": stamp.isoformat().replace("+00:00", "Z"),
        "createdByAppVersion": app_version,
        "packageKind": PAYLOAD_TYPE,
        "entries": [
            {
                "payloadType": PAYLOAD_TYPE,
                "itemCount": note_count,
                "schemaVersion": 1,
                "path": PAYLOAD_ROOT,
                "capabilities": [],
            }
        ],
        "assets": [],
    }


def write_package(
    output_path: str | Path,
    notes: Sequence[Note],
    folders: Sequence[Folder],
    assets: dict[str, bytes],
    *,
    app_version: str,
    created_at: datetime | None = None,
) -> Path:
    """Writes the package and returns its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(len(notes), app_version, created_at)
    db_bytes = build_notes_db(notes, folders)

    # A zip that fails halfway still closes into a valid archive, so write
    # beside the target and rename once complete.
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            _write(archive, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
            _write(archive, f"{PAYLOAD_ROOT}/notes.db", db_bytes)
            for asset_id in sorted(assets):
                _write(archive, f"{PAYLOAD_ROOT}/{ASSET_PREFIX}{asset_id}", assets[asset_id])
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return path


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def read_package(path: str | Path) -> tuple[dict, list[dict], list[dict], list[str]]:
    """Reads a package back: ``(manifest, notes, folders, asset_ids)``."""
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        db_name = f"{PAYLOAD_ROOT}/notes.db"
        if archive.getinfo(db_name).file_size > MAX_DB_BYTES:
            raise ValueError("notes.db is larger than any real notes package")
        db_bytes = archive.read(db_name)
        assets = [
            name[len(f"{PAYLOAD_ROOT}/{ASSET_PREFIX}") :]
            for name in archive.namelist()
            if name.startswith(f"{PAYLOAD_ROOT}/{ASSET_PREFIX}")
        ]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "notes.db"
        db_path.write_bytes(db_bytes)
        connection = sqlite3.connect(db_path)
        try:
            notes = [json.loads(row[0]) for row in connection.execute("SELECT Json FROM Notes")]
            folders = [json.loads(row[0]) for row in connection.execute("SELECT Json FROM Folders")]
        finally:
            connection.close()

    return manifest, notes, folders, sorted(assets)
