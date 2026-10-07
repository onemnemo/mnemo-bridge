"""The saved Notion integration key: the system keychain when there is one, else the config file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".mnemo-bridge"
CONFIG_PATH = CONFIG_DIR / "config.json"

KEYRING_SERVICE = "mnemo-bridge"
KEYRING_USER = "notion-token"


def _load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if os.name == "posix":
        try:
            CONFIG_PATH.chmod(0o600)
        except OSError:
            pass


def _keyring() -> Any:
    """The keyring module, or None where there is no usable keychain."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring):
        return None
    return keyring


def _load_token() -> str:
    config = _load_config()
    store = _keyring()
    if store is None:
        return config.get("token") or ""
    try:
        token = store.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return config.get("token") or ""
    if token:
        return token
    legacy = config.get("token") or ""
    if legacy:
        # Older versions saved the key in the plain file: move it to the keychain.
        _store_token(legacy)
    return legacy


def _store_token(token: str | None) -> None:
    config = _load_config()
    store = _keyring()
    if store is not None:
        try:
            if token:
                store.set_password(KEYRING_SERVICE, KEYRING_USER, token)
            else:
                try:
                    store.delete_password(KEYRING_SERVICE, KEYRING_USER)
                except Exception:
                    pass
            if "token" in config:
                config.pop("token")
                _save_config(config)
            return
        except Exception:
            pass  # a locked or broken keychain: fall back to the file
    if token:
        config["token"] = token
    else:
        config.pop("token", None)
    _save_config(config)
