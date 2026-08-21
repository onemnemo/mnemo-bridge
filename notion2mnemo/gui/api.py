"""The bridge the page calls. Conversions run on a worker thread and push progress into the page."""

from __future__ import annotations

import json
import re
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from .. import __version__
from ..assets import AssetStore
from ..colors import ColorMap
from ..notion import DEFAULT_VERSION, NotionClient, NotionError
from ..package import read_package, write_package
from ..push import NotionWriter, PushOptions
from ..updates import Updater
from ..walker import WalkOptions, Walker, database_title, normalize_id, page_title
from .explain import _explain, _explain_api_error, _explain_unexpected
from .settings import _load_token, _store_token

#: Both engines announce per-item progress as "[3/12] Some title".
_COUNTED = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")


class _Cancelled(BaseException):
    """Raised inside the progress callback to unwind a run the user stopped.

    BaseException so the engine's broad ``except Exception`` guards cannot swallow it.
    """


def _which(program: str) -> str | None:
    import shutil

    return shutil.which(program)


def _result_title(item: dict[str, Any]) -> str:
    if item.get("object") == "database":
        return database_title(item)
    return page_title(item)


def _result_icon(item: dict[str, Any]) -> str:
    icon = item.get("icon") or {}
    return icon.get("emoji") or "" if icon.get("type") == "emoji" else ""


def _documents_dir() -> Path:
    candidate = Path.home() / "Documents"
    return candidate if candidate.is_dir() else Path.home()


class Api:
    """The bridge the page calls. One instance per window."""

    def __init__(self) -> None:
        self._window = None  # set by run_gui once the window exists
        self._busy = threading.Lock()
        self._cancel = threading.Event()
        self._maximized = False
        self._updater = Updater()

    def _push_js(self, function: str, payload: Any) -> None:
        if self._window is not None:
            self._window.evaluate_js(f"{function}({json.dumps(payload)})")

    def _progress(self, message: str) -> None:
        """Parse engine progress for the page. Also the stop point: raises when cancelled."""
        if self._cancel.is_set():
            raise _Cancelled()
        match = _COUNTED.match(message)
        if match:
            index, total, label = match.groups()
            payload = {
                "text": message,
                "index": int(index),
                "total": int(total),
                "label": label,
            }
        else:
            payload = {"text": message, "index": None, "total": None, "label": None}
        self._push_js("appProgress", payload)

    def _client(self, token: str, *, interactive: bool = False) -> NotionClient:
        # No disk cache: a conversion should reflect what Notion holds right now.
        if interactive:
            # Short timeout and few retries so being offline shows up within seconds.
            return NotionClient(
                token, version=DEFAULT_VERSION, cache_dir=None, timeout=20.0, max_retries=2
            )
        return NotionClient(token, version=DEFAULT_VERSION, cache_dir=None)

    def window_minimize(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def window_toggle_maximize(self) -> None:
        if self._window is None:
            return
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        # The window events wired in run_gui keep this correct when the user
        # maximizes another way (Win+Up, snapping to the top edge).
        self._maximized = not self._maximized

    def _on_maximized(self) -> None:
        self._maximized = True

    def _on_restored(self) -> None:
        self._maximized = False

    def window_close(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def get_state(self) -> dict[str, Any]:
        token = _load_token()
        return {
            "version": __version__,
            "token": token,
            "rememberToken": bool(token),
            "defaultOutput": str(_documents_dir() / "notion-export.mnemo"),
            "canOpenFolder": sys.platform in {"win32", "darwin"} or bool(_which("xdg-open")),
            # The page draws the window controls: left on a Mac, right elsewhere.
            "platform": {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux"),
        }

    def remember_token(self, token: str, remember: bool) -> None:
        _store_token(token if remember and token else None)

    def open_url(self, url: str) -> None:
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def check_for_update(self) -> None:
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _check_for_update(self) -> None:
        found = self._updater.check()
        if found:
            self._push_js("appUpdate", found)

    def download_update(self) -> None:
        threading.Thread(target=self._download_update, daemon=True).start()

    def _download_update(self) -> None:
        try:
            self._updater.download(lambda pct: self._push_js("appUpdateProgress", pct))
        except Exception as exc:
            self._push_js("appUpdateFailed", str(exc)[:200])
            return
        self._push_js("appUpdateReady", True)

    def install_update(self) -> None:
        """Swap in the new version and relaunch. The process ends here."""
        try:
            self._updater.apply_and_restart()
        except Exception as exc:
            self._push_js("appUpdateFailed", str(exc)[:200])

    def list_content(self, token: str) -> dict[str, Any]:
        """Everything the integration can see, for the page picker."""
        if not token.strip():
            return {"error": _explain("Paste your integration key first.")}
        client = self._client(token.strip(), interactive=True)
        try:
            pages = client.search_pages()
            databases = client.search_databases()
        except NotionError as exc:
            return {"error": _explain_api_error(exc)}
        except Exception as exc:  # the page awaits this call, so always return something
            return {"error": _explain_unexpected(exc)}

        items = []
        for page in pages:
            if page.get("in_trash") or page.get("archived"):
                continue
            parent_type = (page.get("parent") or {}).get("type") or ""
            items.append(
                {
                    "id": page["id"],
                    "kind": "page",
                    "title": _result_title(page),
                    "emoji": _result_icon(page),
                    # Nested items come along with their parent, so the page can
                    # default to selecting only top-level ones.
                    "nested": parent_type in {"page_id", "database_id", "data_source_id", "block_id"},
                }
            )
        for database in databases:
            if database.get("in_trash") or database.get("archived"):
                continue
            items.append(
                {
                    "id": database["id"],
                    "kind": "database",
                    "title": _result_title(database),
                    "emoji": _result_icon(database),
                    "nested": (database.get("parent") or {}).get("type") == "page_id",
                }
            )
        if not items:
            return {
                "error": _explain(
                    "This key works, but no pages are shared with it yet.",
                    checks=[
                        "In Notion, open a page you want to move and choose "
                        "**⋯ → Connections** → your integration.",
                        "Pages inside the ones you share come along automatically, "
                        "so sharing the top-level ones is enough.",
                    ],
                )
            }
        return {"items": items}

    def pick_output_path(self, suggested: str = "") -> str | None:
        import webview

        start = Path(suggested).parent if suggested else _documents_dir()
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(start),
            save_filename=Path(suggested).name or "notion-export.mnemo",
            file_types=("Mnemo package (*.mnemo)",),
        )
        return result if isinstance(result, str) else (result[0] if result else None)

    def pick_package(self) -> dict[str, Any] | None:
        import webview

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Mnemo package (*.mnemo)",)
        )
        path = result[0] if result else None
        if not path:
            return None
        return self.inspect_package(path)

    def inspect_package(self, path: str) -> dict[str, Any]:
        try:
            _manifest, notes, folders, assets = read_package(path)
        except Exception as exc:
            return {
                "error": _explain(
                    "That file isn't a Mnemo package.",
                    checks=[
                        "Export one from Mnemo with **Notes → Export → Mnemo package**.",
                        f"The file was read as far as: {exc}",
                    ],
                )
            }
        return {
            "path": path,
            "notes": [
                {
                    "title": note.get("title") or "Untitled",
                    "emoji": note.get("emoji") or "",
                    "blocks": len(note.get("blocks") or []),
                    "sub": bool(note.get("parentNoteId")),
                }
                for note in notes
            ],
            "folders": len(folders),
            "images": len(assets),
        }

    def open_containing_folder(self, path: str) -> None:
        import subprocess

        target = Path(path)
        if not target.exists():
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            elif _which("xdg-open"):
                # No portable way to highlight one file on Linux; open its folder.
                subprocess.Popen(["xdg-open", str(target.parent)])
        except OSError:
            pass

    def cancel_run(self) -> None:
        """Stop the running conversion at the next page boundary, where nothing is half-written."""
        self._cancel.set()

    def start_pull(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._start(self._run_pull, params)

    def start_push(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._start(self._run_push, params)

    def _start(self, target: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self._busy.acquire(blocking=False):
            return {"error": _explain("A conversion is already running.")}
        self._cancel.clear()
        threading.Thread(target=target, args=(params,), daemon=True).start()
        return {"started": True}

    def _run_pull(self, params: dict[str, Any]) -> None:
        try:
            token = (params.get("token") or "").strip()
            output = params.get("output") or str(_documents_dir() / "notion-export.mnemo")
            client = self._client(token)
            assets = AssetStore(downloader=client.download)
            options = WalkOptions(
                root_folder=params.get("folder") if params.get("folder") is not None else "Notion",
                database_properties="table" if params.get("dbProperties", True) else "none",
                covers=bool(params.get("covers")),
                limit=int(params["limit"]) if params.get("limit") else None,
            )
            walker = Walker(client, ColorMap(), assets, options, progress=self._progress)
            walker.discover(
                page_ids=params.get("pageIds") or (),
                database_ids=params.get("databaseIds") or (),
            )
            result = walker.convert()
            if not result.notes:
                self._push_js(
                    "appDone",
                    {
                        "error": _explain(
                            "Nothing came across.",
                            checks=[
                                "The pages you picked may no longer be shared with the "
                                "integration. In Notion: **⋯ → Connections**.",
                            ],
                        )
                    },
                )
                return

            self._progress("Writing the package…")
            path = write_package(
                output, result.notes, result.folders, assets.files,
                app_version=f"notion2mnemo {__version__}",
            )
            size_mb = path.stat().st_size / (1024 * 1024)
            self._push_js(
                "appDone",
                {
                    "path": str(path),
                    "folder": options.root_folder or "",
                    "notes": len(result.notes),
                    "folders": len(result.folders),
                    "images": len(assets.files),
                    "sizeMb": round(size_mb, 1),
                    "warnings": result.warnings,
                },
            )
        except _Cancelled:
            self._push_js("appDone", {"cancelled": True})
        except NotionError as exc:
            self._push_js("appDone", {"error": _explain_api_error(exc)})
        except Exception as exc:
            self._push_js("appDone", {"error": _explain_unexpected(exc)})
        finally:
            self._busy.release()

    def _run_push(self, params: dict[str, Any]) -> None:
        writer: NotionWriter | None = None
        try:
            token = (params.get("token") or "").strip()
            package = params.get("package") or ""
            parent = normalize_id(params.get("parent") or "")
            client = self._client(token)
            writer = NotionWriter(
                client,
                options=PushOptions(upload_images=bool(params.get("uploadImages", True))),
                progress=self._progress,
            )
            result = writer.push_package(package, parent)
            self._push_js(
                "appDone",
                {
                    "pages": result.pages_created,
                    "blocks": result.blocks_written,
                    "images": result.images_uploaded,
                    "warnings": result.warnings,
                },
            )
        except _Cancelled:
            # A stopped push has already written to Notion; the page tells the user.
            created = writer.result.pages_created if writer is not None else 0
            self._push_js("appDone", {"cancelled": True, "pagesCreated": created})
        except NotionError as exc:
            self._push_js("appDone", {"error": _explain_api_error(exc)})
        except Exception as exc:
            self._push_js("appDone", {"error": _explain_unexpected(exc)})
        finally:
            self._busy.release()
