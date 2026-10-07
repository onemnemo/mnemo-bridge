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
from ..package import read_package
from ..updates import Updater
from .explain import _explain
from .notion import NotionBridge
from .shared import Cancelled, documents_dir
from .settings import _load_token, _store_token

#: Both engines announce per-item progress as "[3/12] Some title".
_COUNTED = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")


def _which(program: str) -> str | None:
    import shutil

    return shutil.which(program)


class Api(NotionBridge):
    """The bridge the page calls. One instance per window. Each source adds its methods through a mixin."""

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
            raise Cancelled()
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
            "notionToken": token,
            "rememberNotionToken": bool(token),
            "defaultOutput": str(documents_dir() / "notion-export.mnemo"),
            "canOpenFolder": sys.platform in {"win32", "darwin"} or bool(_which("xdg-open")),
            # The page draws the window controls: left on a Mac, right elsewhere.
            "platform": {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux"),
        }

    def notion_remember_token(self, token: str, remember: bool) -> None:
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

    def pick_output_path(self, suggested: str = "") -> str | None:
        import webview

        start = Path(suggested).parent if suggested else documents_dir()
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

    def _start(self, target: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not self._busy.acquire(blocking=False):
            return {"error": _explain("A conversion is already running.")}
        self._cancel.clear()
        threading.Thread(target=target, args=(params,), daemon=True).start()
        return {"started": True}

