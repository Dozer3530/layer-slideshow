"""Headless regression tests for SlideshowDock.

Runs against the real QGIS API on either binding:

    & "C:\\Program Files\\QGIS 4.0.1\\bin\\python-qgis.bat" ^
        -m unittest layer_slideshow.test.test_slideshow -v

Each test covers a bug that shipped in 1.0.0 and was fixed in 1.2.0.
"""

import os
import unittest

from qgis.core import QgsApplication, QgsProject

QGIS_APP = QgsApplication([], False)
QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
QGIS_APP.initQgis()

from layer_slideshow.slideshow import SlideshowDock, CHECKED, UNCHECKED  # noqa: E402


class _StubCanvas:
    def refresh(self):
        pass


class _StubIface:
    def mapCanvas(self):
        return _StubCanvas()


class SlideshowDockTest(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.root = self.project.layerTreeRoot()
        for name in ("Alpha", "Bravo", "Charlie"):
            self.root.addGroup(name)
        self.dock = SlideshowDock(_StubIface())

    def tearDown(self):
        self.dock.teardown()
        self.dock.deleteLater()

    def _set_all(self, state):
        for i in range(self.dock.list.count()):
            self.dock.list.item(i).setCheckState(state)

    def _listed(self):
        return [self.dock.list.item(i).text() for i in range(self.dock.list.count())]

    # ---------- ordering ----------
    def test_playback_order_is_bottom_to_top(self):
        """Groups added Alpha, Bravo, Charlie play back Charlie first."""
        self.assertEqual(self.dock.checked_group_names(),
                         ["Charlie", "Bravo", "Alpha"])

    def test_new_groups_default_to_checked(self):
        self.root.addGroup("Delta")
        self.assertIn("Delta", self.dock.checked_group_names())

    # ---------- bug 1 ----------
    def test_unchecking_every_group_survives_refresh(self):
        self._set_all(UNCHECKED)
        self.dock.refresh_layers()
        self.assertEqual(self.dock.checked_group_names(), [])

    def test_partial_uncheck_survives_refresh(self):
        self.dock.list.item(1).setCheckState(UNCHECKED)
        expected = self.dock.checked_group_names()
        self.dock.refresh_layers()
        self.assertEqual(self.dock.checked_group_names(), expected)

    # ---------- bug 2 ----------
    def test_play_restarts_after_finishing(self):
        self.dock.loop.setChecked(False)
        self.dock.play()
        for _ in range(3):
            self.dock.advance()
        self.assertEqual(self.dock.status.text(), "Finished")
        self.dock.play()
        self.assertEqual(self.dock.status.text(), "Showing 1/3: Charlie")

    def test_loop_wraps_instead_of_finishing(self):
        self.dock.loop.setChecked(True)
        self.dock.play()
        for _ in range(3):
            self.dock.advance()
        self.assertEqual(self.dock.status.text(), "Showing 1/3: Charlie")

    # ---------- bug 3 ----------
    def test_stop_leaves_buttons_consistent(self):
        self.dock.play()
        self.dock.stop()
        self.assertTrue(self.dock.play_btn.isEnabled())
        self.assertFalse(self.dock.pause_btn.isEnabled())
        self.assertTrue(self.dock.mini_play_btn.isEnabled())
        self.assertFalse(self.dock.mini_pause_btn.isEnabled())

    def test_close_then_reopen_can_play_again(self):
        """closeEvent() calls stop(); Play must not be left greyed out."""
        self.dock.play()
        self.dock.close()
        self.assertTrue(self.dock.play_btn.isEnabled())

    # ---------- bug 4 ----------
    def test_group_added_refreshes_list(self):
        self.root.addGroup("Delta")
        self.assertIn("Delta", self._listed())

    def test_group_removed_refreshes_list(self):
        self.root.removeChildNode(self.root.findGroup("Bravo"))
        self.assertNotIn("Bravo", self._listed())

    # ---------- bug 5 ----------
    def test_rename_does_not_orphan_the_group(self):
        self.dock.play()
        self.root.findGroup("Alpha").setName("Alpha RENAMED")
        self.assertIn("Alpha RENAMED", self._listed())
        self.assertNotIn("Alpha", self._listed())
        orphans = [n for n in self.dock.checked_group_names()
                   if self.root.findGroup(n) is None]
        self.assertEqual(orphans, [])

    def test_playhead_stays_consistent_across_rebuild(self):
        self.dock.play()
        self.root.findGroup("Alpha").setName("Alpha RENAMED")
        names = self.dock.checked_group_names()
        self.assertTrue(0 <= self.dock.index < len(names))
        self.assertEqual(names[self.dock.index], self.dock.current_name)

    # ---------- misc ----------
    def test_play_with_nothing_checked_reports_and_does_not_start(self):
        self._set_all(UNCHECKED)
        self.dock.play()
        self.assertEqual(self.dock.status.text(), "No groups checked.")
        self.assertFalse(self.dock.running)

    def test_only_the_current_group_is_visible(self):
        self.dock.play()
        current = self.dock.current_name
        for name in self.dock.checked_group_names():
            node = self.root.findGroup(name)
            self.assertEqual(node.isVisible(), name == current, name)

    def test_groups_outside_the_slideshow_are_untouched(self):
        """An unchecked group keeps whatever visibility it had (e.g. a basemap)."""
        self.dock.list.item(2).setCheckState(UNCHECKED)   # Alpha
        basemap = self.root.findGroup("Alpha")
        basemap.setItemVisibilityChecked(True)
        self.dock.play()
        self.dock.advance()
        self.assertTrue(basemap.isVisible())

    def test_duplicate_group_names_are_reported(self):
        self.root.addGroup("Charlie")
        self.assertIn("duplicate", self.dock.status.text().lower())


if __name__ == "__main__":
    unittest.main()
