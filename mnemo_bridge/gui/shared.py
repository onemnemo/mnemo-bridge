"""Pieces every source's bridge shares."""

from __future__ import annotations

from pathlib import Path


class Cancelled(BaseException):
    """Raised inside the progress callback to unwind a run the user stopped.

    BaseException so the engine's broad ``except Exception`` guards cannot swallow it.
    """


def documents_dir() -> Path:
    candidate = Path.home() / "Documents"
    return candidate if candidate.is_dir() else Path.home()
