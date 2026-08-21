"""Where the GUI keeps the integration key, without touching the real keychain."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from notion2mnemo.gui import settings


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


class TokenStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config_dir = Path(self.tmp.name)
        self.config_path = config_dir / "config.json"
        patches = [
            mock.patch.object(settings, "CONFIG_DIR", config_dir),
            mock.patch.object(settings, "CONFIG_PATH", self.config_path),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}

    def test_keychain_holds_the_key_and_the_file_does_not(self):
        keyring = FakeKeyring()
        with mock.patch.object(settings, "_keyring", lambda: keyring):
            settings._store_token("ntn_secret")
            self.assertEqual(settings._load_token(), "ntn_secret")
        self.assertNotIn("token", self.config())

    def test_a_key_from_an_older_version_moves_into_the_keychain(self):
        self.config_path.write_text(json.dumps({"token": "ntn_old"}), encoding="utf-8")
        keyring = FakeKeyring()
        with mock.patch.object(settings, "_keyring", lambda: keyring):
            self.assertEqual(settings._load_token(), "ntn_old")
        self.assertEqual(list(keyring.store.values()), ["ntn_old"])
        self.assertNotIn("token", self.config())

    def test_without_a_keychain_the_file_is_used(self):
        with mock.patch.object(settings, "_keyring", lambda: None):
            settings._store_token("ntn_file")
            self.assertEqual(settings._load_token(), "ntn_file")
            settings._store_token(None)
            self.assertEqual(settings._load_token(), "")


if __name__ == "__main__":
    unittest.main()
