"""
Self-update over Velopack, reading release feeds published on the GitHub release.

``boot`` must run first in the packaged process: Velopack re-runs the executable
with hook arguments during install, update and uninstall and expects it to exit
before anything slow or visible happens.

``Updater`` is best-effort. No network, no feed, a portable copy or a source
checkout all report "no update" quietly.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

REPO_URL = "https://github.com/torstfugl/mnemo2notion"

#: Pre-releases are skipped unless this is on; only a beta build should enable it.
PRERELEASE = False

log = logging.getLogger(__name__)


def boot() -> None:
    """Hand control to Velopack's install and update hooks, then carry on."""
    try:
        from velopack import App
    except ImportError:
        return
    try:
        App().run()
    except Exception:  # never let the updater stop the app from starting
        log.exception("velopack startup hook failed")


class Updater:
    """Check, download and apply. One instance per window."""

    def __init__(self, repo_url: str = REPO_URL, prerelease: bool = PRERELEASE) -> None:
        self._repo_url = repo_url
        self._prerelease = prerelease
        self._manager: Any = None
        self._pending: Any = None  # the UpdateInfo we last found

    def _get_manager(self) -> Any:
        """The manager, or None when this is not an installed Velopack app."""
        if self._manager is not None:
            return self._manager
        try:
            from velopack import GithubSource, UpdateManager
        except ImportError:
            return None
        try:
            source = GithubSource(self._repo_url, None, self._prerelease)
            self._manager = UpdateManager(source)
        except Exception:
            log.info("not an installed Velopack app; updates disabled", exc_info=True)
            return None
        return self._manager

    def check(self) -> dict[str, str] | None:
        """The newer release waiting for us, or None if there isn't one."""
        manager = self._get_manager()
        if manager is None:
            return None
        try:
            info = manager.check_for_updates()
        except Exception:
            log.info("update check failed", exc_info=True)
            return None
        if info is None:
            return None
        self._pending = info
        release = info.TargetFullRelease
        return {
            "version": release.Version,
            # Fetched from the network: the page must render this as text, not HTML.
            "notes": (release.NotesMarkdown or "").strip(),
            "url": f"{self._repo_url}/releases/tag/v{release.Version}",
        }

    def download(self, progress: Callable[[int], None] | None = None) -> None:
        """Fetch the pending update. Raises if it cannot be downloaded."""
        manager = self._get_manager()
        if manager is None or self._pending is None:
            raise RuntimeError("there is no update to download")
        manager.download_updates(self._pending, progress)

    def apply_and_restart(self) -> None:
        """Swap in the downloaded version and relaunch. Does not return."""
        manager = self._get_manager()
        if manager is None or self._pending is None:
            raise RuntimeError("there is no update to apply")
        manager.apply_updates_and_restart(self._pending)

    def installed_version(self) -> str | None:
        """The version Velopack thinks is running, if it manages this copy."""
        manager = self._get_manager()
        if manager is None:
            return None
        try:
            return manager.get_current_version()
        except Exception:
            return None
