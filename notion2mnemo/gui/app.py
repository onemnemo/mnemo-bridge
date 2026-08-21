"""The desktop app: a native web view whose page talks to the Api bridge in api.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .api import Api

APP_NAME = "Notion ↔ Mnemo Converter"


def _icon_path() -> Path | None:
    """The PNG icon, for window managers that take it from the running app."""
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2]  # type: ignore[attr-defined]
    path = base / "assets" / "icon.png"
    return path if path.exists() else None


def _web_dir() -> Path:
    # PyInstaller unpacks data files under sys._MEIPASS.
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "notion2mnemo" / "gui" / "web"  # type: ignore[attr-defined]
    return Path(__file__).parent / "web"


def _start_options() -> dict[str, Any]:
    # Windows and macOS take the icon from the executable and the app bundle;
    # only the Linux backends read it from here.
    icon = _icon_path()
    return {"icon": str(icon)} if icon is not None and sys.platform.startswith("linux") else {}


def run_gui() -> int:
    import webview

    # Boots the web view, bridge and page without showing a window, checks the
    # page initialised, and exits. Used by CI and packaging.
    smoke = os.environ.get("NOTION2MNEMO_SMOKE") == "1"

    api = Api()
    window = webview.create_window(
        APP_NAME,
        url=str(_web_dir() / "index.html"),
        js_api=api,
        width=900,
        height=700,
        min_size=(820, 620),
        # The page draws the title bar. easy_drag is off so only the
        # .pywebview-drag-region strip moves the window.
        frameless=True,
        easy_drag=False,
        background_color="#FFFFFF",
        hidden=smoke,
    )
    api._window = window
    events = getattr(window, "events", None)
    if events is not None:
        if hasattr(events, "maximized"):
            events.maximized += api._on_maximized
        if hasattr(events, "restored"):
            events.restored += api._on_restored

    if smoke:
        def probe(w) -> None:
            import time

            time.sleep(3)  # let the page load and call get_state
            ready = w.evaluate_js("typeof state === 'object' && typeof appDone === 'function'")
            print(f"SMOKE ready={ready}", flush=True)
            w.destroy()

        webview.start(probe, window, **_start_options())
    else:
        webview.start(**_start_options())
    return 0
