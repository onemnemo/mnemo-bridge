"""The Notion part of the bridge: list what the integration can see, then pull or push on a worker thread."""

from __future__ import annotations

from typing import Any

from .. import __version__
from ..package import write_package
from ..sources.notion.assets import AssetStore
from ..sources.notion.client import DEFAULT_VERSION, NotionClient, NotionError
from ..sources.notion.colors import ColorMap
from ..sources.notion.push import NotionWriter, PushOptions
from ..sources.notion.walker import WalkOptions, Walker, database_title, normalize_id, page_title
from .explain import _explain, _explain_api_error, _explain_unexpected
from .shared import Cancelled, documents_dir


def _result_title(item: dict[str, Any]) -> str:
    if item.get("object") == "database":
        return database_title(item)
    return page_title(item)


def _result_icon(item: dict[str, Any]) -> str:
    icon = item.get("icon") or {}
    return icon.get("emoji") or "" if icon.get("type") == "emoji" else ""


class NotionBridge:
    """Mixed into ``Api``, which supplies ``_start``, ``_progress``, ``_push_js`` and ``_busy``."""

    def _notion_client(self, token: str, *, interactive: bool = False) -> NotionClient:
        # No disk cache: a conversion should reflect what Notion holds right now.
        if interactive:
            # Short timeout and few retries so being offline shows up within seconds.
            return NotionClient(
                token, version=DEFAULT_VERSION, cache_dir=None, timeout=20.0, max_retries=2
            )
        return NotionClient(token, version=DEFAULT_VERSION, cache_dir=None)

    def notion_list_content(self, token: str) -> dict[str, Any]:
        """Everything the integration can see, for the page picker."""
        if not token.strip():
            return {"error": _explain("Paste your integration key first.")}
        client = self._notion_client(token.strip(), interactive=True)
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

    def notion_start_pull(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._start(self._notion_pull, params)

    def notion_start_push(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._start(self._notion_push, params)

    def _notion_pull(self, params: dict[str, Any]) -> None:
        try:
            token = (params.get("token") or "").strip()
            output = params.get("output") or str(documents_dir() / "notion-export.mnemo")
            client = self._notion_client(token)
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
                app_version=f"mnemo-bridge {__version__}",
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
        except Cancelled:
            self._push_js("appDone", {"cancelled": True})
        except NotionError as exc:
            self._push_js("appDone", {"error": _explain_api_error(exc)})
        except Exception as exc:
            self._push_js("appDone", {"error": _explain_unexpected(exc)})
        finally:
            self._busy.release()

    def _notion_push(self, params: dict[str, Any]) -> None:
        writer: NotionWriter | None = None
        try:
            token = (params.get("token") or "").strip()
            package = params.get("package") or ""
            parent = normalize_id(params.get("parent") or "")
            client = self._notion_client(token)
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
        except Cancelled:
            # A stopped push has already written to Notion; the page tells the user.
            created = writer.result.pages_created if writer is not None else 0
            self._push_js("appDone", {"cancelled": True, "pagesCreated": created})
        except NotionError as exc:
            self._push_js("appDone", {"error": _explain_api_error(exc)})
        except Exception as exc:
            self._push_js("appDone", {"error": _explain_unexpected(exc)})
        finally:
            self._busy.release()
