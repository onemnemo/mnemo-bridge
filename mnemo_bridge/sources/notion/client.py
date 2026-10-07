"""
Notion API client with throttling and a disk cache of responses.

Notion allows about three requests per second and answers a burst with 429, so
the client sleeps for ``Retry-After``. Cached block JSON can hold signed file
URLs that expire after an hour, so image bytes are never read from a cached URL
(see ``assets.py``) and expired entries count as misses.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

import requests

from .transport import API_ROOT, _expired_file_urls, _never_connected, _retry_after
from .write import NotionWriteMixin

#: Covers every page and single-source database. Multi-source databases need
#: 2025-09-03 or later.
DEFAULT_VERSION = "2022-06-28"

#: The version at which databases split into databases-plus-data-sources.
DATA_SOURCE_VERSION = "2025-09-03"


class NotionError(RuntimeError):
    """An API call that failed. ``status`` is the HTTP status, when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NotionClient(NotionWriteMixin):
    def __init__(
        self,
        token: str,
        *,
        version: str = DEFAULT_VERSION,
        cache_dir: Path | None = None,
        requests_per_second: float = 2.5,
        max_retries: int = 5,
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.version = version
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._max_retries = max_retries
        self._timeout = timeout
        self._last_call = 0.0
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": version,
                "Content-Type": "application/json",
            }
        )
        self.request_count = 0
        self.cache_hits = 0

    def _cache_path(self, method: str, path: str, body: dict[str, Any] | None) -> Path | None:
        if not self.cache_dir:
            return None
        key = json.dumps([self.version, method, path, body], sort_keys=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{digest}.json"

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _read_cache(self, cache_path: Path | None) -> dict[str, Any] | None:
        if cache_path is None or not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Half-written entry from an interrupted run.
            return None
        if _expired_file_urls(data, time.time()):
            return None
        return data

    def _write_cache(self, cache_path: Path, data: dict[str, Any]) -> None:
        # Renamed into place so an interrupted write never leaves a truncated entry.
        temp = cache_path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(temp, cache_path)
        except OSError:
            temp.unlink(missing_ok=True)

    def _send(self, method: str, url: str, *, idempotent: bool, label: str, **kwargs: Any) -> requests.Response:
        """
        One HTTP call with throttling and retries, returning a 2xx response.

        Writes are not retried after a timeout or a 5xx, because Notion may
        already have applied them and a retry would duplicate pages or blocks.
        They retry only on a 429 or a connection that was never made.
        """
        last_error = ""
        for attempt in range(self._max_retries):
            self._throttle()
            self.request_count += 1
            try:
                response = self._session.request(method, url, timeout=self._timeout, **kwargs)
            except requests.exceptions.ConnectTimeout as exc:
                last_error = f"could not connect: {exc}"
            except requests.ConnectionError as exc:
                if not idempotent and not _never_connected(exc):
                    raise NotionError(
                        f"{label} lost its connection, and Notion may or may not have applied it: {exc}"
                    ) from exc
                last_error = f"could not connect: {exc}"
            except requests.RequestException as exc:
                if not idempotent:
                    raise NotionError(
                        f"{label} got no answer, and Notion may or may not have applied it: {exc}"
                    ) from exc
                last_error = str(exc)
            else:
                if response.status_code == 429:
                    last_error = "429 rate limited"
                    time.sleep(min(_retry_after(response), 60))
                    continue
                if response.status_code >= 500:
                    if not idempotent:
                        raise NotionError(
                            f"{label} failed: {response.status_code} {response.text[:300]}",
                            response.status_code,
                        )
                    last_error = f"{response.status_code} {response.text[:200]}"
                elif response.status_code >= 400:
                    raise NotionError(
                        f"{label} failed: {response.status_code} {response.text[:400]}",
                        response.status_code,
                    )
                else:
                    return response
            if attempt + 1 < self._max_retries:
                time.sleep(min(2**attempt, 30))
        raise NotionError(f"{label} failed after {self._max_retries} attempts: {last_error}")

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        idempotent: bool | None = None,
    ) -> dict[str, Any]:
        """
        One API call. ``idempotent`` defaults to true for GET, DELETE, and the
        POST endpoints that only search or query.
        """
        cache_path = self._cache_path(method, path, body)
        cached = self._read_cache(cache_path)
        if cached is not None:
            self.cache_hits += 1
            return cached

        if idempotent is None:
            idempotent = method in {"GET", "DELETE"} or path == "/search" or path.endswith("/query")
        response = self._send(
            method, f"{API_ROOT}{path}", idempotent=idempotent, label=f"{method} {path}", json=body
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise NotionError(f"{method} {path} answered with something that isn't JSON") from exc
        if cache_path is not None:
            self._write_cache(cache_path, data)
        return data

    def _paginate(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            if method == "GET":
                suffix = "?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
                data = self.request("GET", path + suffix)
            else:
                payload = dict(body or {})
                payload["page_size"] = 100
                if cursor:
                    payload["start_cursor"] = cursor
                data = self.request(method, path, payload)

            yield from data.get("results", [])
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")
            if not cursor:
                return

    def search_pages(self, query: str = "") -> list[dict[str, Any]]:
        """Every page the integration can see. Databases are fetched separately."""
        body: dict[str, Any] = {"filter": {"property": "object", "value": "page"}}
        if query:
            body["query"] = query
        return list(self._paginate("POST", "/search", body))

    def search_databases(self, query: str = "") -> list[dict[str, Any]]:
        """
        Every database the integration can see.

        From 2025-09-03 on, search returns data sources (each naming its
        database as ``parent``) instead of databases, so they are folded back
        into one entry per database.
        """
        if self.version < DATA_SOURCE_VERSION:
            body: dict[str, Any] = {"filter": {"property": "object", "value": "database"}}
            if query:
                body["query"] = query
            return list(self._paginate("POST", "/search", body))

        body = {"filter": {"property": "object", "value": "data_source"}}
        if query:
            body["query"] = query
        databases: dict[str, dict[str, Any]] = {}
        for source in self._paginate("POST", "/search", body):
            parent = source.get("parent") or {}
            database_id = parent.get("database_id") if parent.get("type") == "database_id" else None
            if not database_id or database_id in databases:
                continue
            try:
                databases[database_id] = self.get_database(database_id)
            except NotionError:
                # The database itself is not readable; the source carries a title.
                databases[database_id] = dict(source, id=database_id, object="database")
        return list(databases.values())

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def get_database(self, database_id: str) -> dict[str, Any]:
        return self.request("GET", f"/databases/{database_id}")

    def get_block(self, block_id: str) -> dict[str, Any]:
        return self.request("GET", f"/blocks/{block_id}")

    def block_children(self, block_id: str) -> list[dict[str, Any]]:
        return list(self._paginate("GET", f"/blocks/{block_id}/children"))

    def block_children_fresh(self, block_id: str) -> list[dict[str, Any]]:
        """
        Children read past the cache, for blocks this run just created.

        The cache is keyed by request, so after a write it would return the
        state from before it.
        """
        cache_dir, self.cache_dir = self.cache_dir, None
        try:
            return list(self._paginate("GET", f"/blocks/{block_id}/children"))
        finally:
            self.cache_dir = cache_dir

    def query_database(self, database_id: str) -> list[dict[str, Any]]:
        """
        Every row of a database. From 2025-09-03 a database is a container of
        data sources and the query moved to ``/data_sources/{id}/query``.
        """
        if self.version >= DATA_SOURCE_VERSION:
            database = self.get_database(database_id)
            sources = database.get("data_sources") or []
            if sources:
                rows: list[dict[str, Any]] = []
                for source in sources:
                    source_id = source.get("id")
                    if source_id:
                        rows.extend(self._paginate("POST", f"/data_sources/{source_id}/query", {}))
                return rows
        return list(self._paginate("POST", f"/databases/{database_id}/query", {}))

    def download(self, url: str) -> tuple[bytes, str]:
        """
        Fetches a file, returning its bytes and the server's content type.

        Not cached or throttled: these are S3 URLs, outside the API rate limit,
        and the signature expires within the hour.

        The session's auth headers are stripped because S3 rejects a bearer
        token it did not issue; ``None`` removes a session header for one call.
        """
        response = self._session.get(
            url,
            timeout=self._timeout,
            headers={"Authorization": None, "Notion-Version": None, "Content-Type": None},
        )
        response.raise_for_status()
        return response.content, response.headers.get("Content-Type", "")
