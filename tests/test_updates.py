"""
The updater's failure behaviour. A copy that cannot update itself (source
checkout, portable unzip, no network) must report "no update" rather than raise,
because the check runs at startup. Nothing here touches the network.
"""

from __future__ import annotations

import unittest
from unittest import mock

from mnemo_bridge.updates import Updater, boot


class _Boom:
    """Stands in for a velopack the way it behaves when nothing is installed."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Could not auto-locate app manifest")


class UpdaterWithoutVelopack(unittest.TestCase):
    """velopack is an optional dependency; absence is not an error."""

    def setUp(self):
        # Simulate `import velopack` failing, wherever it is attempted.
        patcher = mock.patch.dict("sys.modules", {"velopack": None})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_check_returns_none(self):
        self.assertIsNone(Updater().check())

    def test_installed_version_returns_none(self):
        self.assertIsNone(Updater().installed_version())

    def test_boot_is_silent(self):
        boot()  # must not raise

    def test_download_refuses_rather_than_pretending(self):
        # Only reachable if the page asks out of order, so raising is fine.
        with self.assertRaises(RuntimeError):
            Updater().download()

    def test_apply_refuses_rather_than_pretending(self):
        with self.assertRaises(RuntimeError):
            Updater().apply_and_restart()


class UpdaterWhenNotInstalled(unittest.TestCase):
    """velopack is present, but this copy was never installed by it."""

    def test_check_returns_none_when_manager_cannot_be_built(self):
        fake = mock.MagicMock()
        fake.UpdateManager = _Boom
        fake.GithubSource = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            self.assertIsNone(Updater().check())

    def test_check_returns_none_when_the_feed_cannot_be_read(self):
        manager = mock.MagicMock()
        manager.check_for_updates.side_effect = OSError("no network")
        fake = mock.MagicMock()
        fake.UpdateManager = mock.MagicMock(return_value=manager)
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            self.assertIsNone(Updater().check())

    def test_boot_survives_a_failing_hook(self):
        fake = mock.MagicMock()
        fake.App = _Boom
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            # assertLogs also keeps the expected traceback out of test output.
            with self.assertLogs("mnemo_bridge.updates", level="ERROR") as caught:
                boot()  # must not raise
        self.assertIn("velopack startup hook failed", caught.output[0])


class UpdaterWhenAnUpdateExists(unittest.TestCase):
    def _velopack(self, version="1.2.0", notes="Fixed a thing."):
        release = mock.MagicMock()
        release.Version = version
        release.NotesMarkdown = notes
        info = mock.MagicMock()
        info.TargetFullRelease = release

        manager = mock.MagicMock()
        manager.check_for_updates.return_value = info
        manager.get_current_version.return_value = "1.1.0"

        fake = mock.MagicMock()
        fake.UpdateManager = mock.MagicMock(return_value=manager)
        return fake, manager, info

    def test_check_reports_version_and_notes(self):
        fake, _manager, _info = self._velopack()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            found = Updater().check()
        self.assertEqual(found, {
            "version": "1.2.0",
            "notes": "Fixed a thing.",
            "url": "https://github.com/onemnemo/mnemo-bridge/releases/tag/v1.2.0",
        })

    def test_missing_notes_become_an_empty_string(self):
        fake, _manager, _info = self._velopack(notes=None)
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            found = Updater().check()
        self.assertEqual(found["notes"], "")

    def test_download_passes_the_found_release_through(self):
        fake, manager, info = self._velopack()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            updater = Updater()
            updater.check()
            updater.download()
        manager.download_updates.assert_called_once_with(info, None)

    def test_apply_uses_the_release_that_was_downloaded(self):
        fake, manager, info = self._velopack()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            updater = Updater()
            updater.check()
            updater.apply_and_restart()
        manager.apply_updates_and_restart.assert_called_once_with(info)

    def test_the_manager_is_built_once_and_reused(self):
        fake, _manager, _info = self._velopack()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            updater = Updater()
            updater.check()
            updater.check()
        self.assertEqual(fake.UpdateManager.call_count, 1)


if __name__ == "__main__":
    unittest.main()
