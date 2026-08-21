"""Failure explanations for the GUI: what to do, with the raw error kept as detail."""

from __future__ import annotations

import traceback
from typing import Any

from ..notion import NotionError


def _explain(title: str, *, detail: str = "", checks: list[str] | None = None) -> dict[str, Any]:
    return {"title": title, "checks": checks or [], "detail": detail or title}


def _explain_api_error(exc: NotionError) -> dict[str, Any]:
    text = str(exc)
    if "401" in text:
        return _explain(
            "Notion didn't accept that key.",
            detail=text,
            checks=[
                "The key starts with **ntn_** and is copied whole. It's easy to miss "
                "the last few characters.",
                "The integration still exists in Notion. If you deleted and remade it, "
                "the old key stops working.",
            ],
        )
    if "404" in text:
        return _explain(
            "Notion couldn't find that page.",
            detail=text,
            checks=[
                "The page exists, but the integration isn't connected to it. Open it in "
                "Notion and choose **⋯ → Connections** → your integration.",
            ],
        )
    if "403" in text:
        return _explain(
            "The integration isn't allowed to do that.",
            detail=text,
            checks=[
                "In Notion, open your integration's settings and make sure it may "
                "**read** content and **insert** content (to create pages).",
            ],
        )
    if "429" in text:
        return _explain(
            "Notion asked us to slow down.",
            detail=text,
            checks=["Give it a minute and try again. Nothing was lost."],
        )
    return _explain("Notion returned an error.", detail=text, checks=[text[:300]])


def _explain_unexpected(exc: Exception) -> dict[str, Any]:
    return _explain(
        "Something went wrong on this side.",
        detail="".join(traceback.format_exception(exc)),
        checks=[f"{type(exc).__name__}: {exc}"],
    )
