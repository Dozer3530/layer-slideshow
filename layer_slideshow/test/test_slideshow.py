"""Headless regression tests for the Layer Slideshow dock.

Runs against the real QGIS API on either binding:

    & "C:\\Program Files\\QGIS 4.0.1\\bin\\python-qgis.bat" ^
        -m unittest layer_slideshow.test.test_slideshow -v

SlideshowDockTest covers the bugs that shipped in 1.0.0 and were fixed in 1.2.0;
the remaining classes cover the 1.3.0 features.
"""

import os
import unittest

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

QGIS_APP = QgsApplication([], False)
QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
QGIS_APP.initQgis()

from qgis.PyQt.QtWidgets import QWidget  # noqa: E402

from layer_slideshow import classFactory  # noqa: E402
from layer_slideshow.slideshow import (  # noqa: E402
    LayerSlideshowPlugin, SlideshowDock, SCOPE, CHECKED, UNCHECKED,
)
from layer_slideshow.legend import group_legend_entries  # noqa: E402


class _StubCanvas:
    def refresh(self):
        pass


class _StubIface:
    """Just enough of QgisInterface for the dock to run headless."""

    def __init__(self):
        self.canvas = _StubCanvas()
        self.docks = []

    def mapCanvas(self):
        return self.canvas

    def addDockWidget(self, area, dock):
        self.docks.append(dock)

    def removeDockWidget(self, dock):
        if dock in self.docks:
            self.docks.remove(dock)


class _DockCase(unittest.TestCase):
    """Fresh project with three groups and a dock, torn down after each test."""

    GROUPS = ("Alpha", "Bravo", "Charlie")

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.root = self.project.layerTreeRoot()
        for name in self.GROUPS:
            self.root.addGroup(name)
        self.iface = _StubIface()
        self.dock = SlideshowDock(self.iface)
        self._extra_docks = []

    def tearDown(self):
        for dock in self._extra_docks:
            dock.teardown()
            dock.deleteLater()
        self.dock.teardown()
        self.dock.deleteLater()

    def new_dock(self):
        """A second dock that reads its state back out of the project."""
        dock = SlideshowDock(_StubIface())
        self._extra_docks.append(dock)
        return dock

    def add_layer(self, group_name, layer_name):
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:integer", layer_name, "memory")
        self.assertTrue(layer.isValid(), layer_name)
        self.project.addMapLayer(layer, False)
        self.root.findGroup(group_name).addLayer(layer)
        return layer

    def set_all(self, state):
        for i in range(self.dock.list.count()):
            self.dock.list.item(i).setCheckState(state)

    def listed(self):
        return [self.dock.list.item(i).text()
                for i in range(self.dock.list.count())]


class SlideshowDockTest(_DockCase):
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
        self.set_all(UNCHECKED)
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
        self.assertIn("Delta", self.listed())

    def test_group_removed_refreshes_list(self):
        self.root.removeChildNode(self.root.findGroup("Bravo"))
        self.assertNotIn("Bravo", self.listed())

    # ---------- bug 5 ----------
    def test_rename_does_not_orphan_the_group(self):
        self.dock.play()
        self.root.findGroup("Alpha").setName("Alpha RENAMED")
        self.assertIn("Alpha RENAMED", self.listed())
        self.assertNotIn("Alpha", self.listed())
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
        self.set_all(UNCHECKED)
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


class SettingsPersistenceTest(_DockCase):
    def test_fractional_interval_does_not_raise(self):
        """writeEntry exposes no double overload; a float here used to abort QGIS.

        The exception surfaced inside a Qt slot, where PyQt6 calls abort()
        rather than propagating -- so this is a crash regression, not a
        cosmetic one.
        """
        self.dock.interval.setValue(0.7)
        ms, ok = self.project.readNumEntry(SCOPE, "/IntervalMs", 0)
        self.assertTrue(ok)
        self.assertEqual(ms, 700)

    def test_interval_round_trips_through_the_project(self):
        self.dock.interval.setValue(7.5)
        self.assertAlmostEqual(self.new_dock().interval.value(), 7.5, places=3)

    def test_loop_round_trips(self):
        self.dock.loop.setChecked(False)
        self.assertFalse(self.new_dock().loop.isChecked())

    def test_autostart_round_trips(self):
        self.dock.autostart.setChecked(True)
        self.assertTrue(self.new_dock().autostart.isChecked())
        self.assertTrue(self.project.readBoolEntry(SCOPE, "/AutoStart", False)[0])

    def test_group_selection_round_trips(self):
        self.dock.list.item(1).setCheckState(UNCHECKED)     # Bravo off
        expected = self.dock.checked_group_names()
        self.assertEqual(self.new_dock().checked_group_names(), expected)

    def test_saved_empty_selection_is_not_resurrected(self):
        """An all-off selection must survive a reload, same as a refresh."""
        self.set_all(UNCHECKED)
        self.assertEqual(self.new_dock().checked_group_names(), [])

    def test_defaults_when_project_has_no_entries(self):
        fresh = self.new_dock()
        self.assertAlmostEqual(fresh.interval.value(), 3.0, places=3)
        self.assertTrue(fresh.loop.isChecked())
        self.assertFalse(fresh.autostart.isChecked())


class VisibilityRestoreTest(_DockCase):
    def _set_visibility(self, mapping):
        for name, visible in mapping.items():
            self.root.findGroup(name).setItemVisibilityChecked(visible)

    def test_restore_button_enabled_only_once_snapshot_exists(self):
        self.assertFalse(self.dock.restore_btn.isEnabled())
        self.dock.play()
        self.assertTrue(self.dock.restore_btn.isEnabled())

    def test_restores_pre_show_visibility(self):
        original = {"Alpha": True, "Bravo": False, "Charlie": True}
        self._set_visibility(original)
        self.dock.play()
        self.dock.advance()
        self.assertTrue(self.dock.restore_visibility())
        for name, visible in original.items():
            self.assertEqual(
                self.root.findGroup(name).itemVisibilityChecked(), visible, name)

    def test_teardown_hands_the_project_back(self):
        original = {"Alpha": False, "Bravo": True, "Charlie": False}
        self._set_visibility(original)
        self.dock.play()
        self.dock.teardown()
        for name, visible in original.items():
            self.assertEqual(
                self.root.findGroup(name).itemVisibilityChecked(), visible, name)

    def test_restore_without_a_snapshot_is_a_no_op(self):
        self.assertFalse(self.dock.restore_visibility())

    def test_snapshot_is_taken_once_not_per_play(self):
        """Pausing mid-show and playing again must not re-baseline."""
        self._set_visibility({"Alpha": True, "Bravo": True, "Charlie": True})
        self.dock.play()
        self.dock.pause()
        self.dock.play()          # snapshot must still be the pre-show state
        self.dock.restore_visibility()
        for name in self.GROUPS:
            self.assertTrue(
                self.root.findGroup(name).itemVisibilityChecked(), name)


class LegendTest(_DockCase):
    def test_entries_for_a_vector_layer_use_the_layer_name(self):
        self.add_layer("Alpha", "Soil Sensors")
        labels = [label for label, _ in
                  group_legend_entries(self.root.findGroup("Alpha"))]
        self.assertIn("Soil Sensors", labels)

    def test_entries_carry_a_symbol_swatch(self):
        self.add_layer("Alpha", "Soil Sensors")
        entries = group_legend_entries(self.root.findGroup("Alpha"))
        self.assertTrue(any(pix is not None and not pix.isNull()
                            for _, pix in entries))

    def test_empty_group_has_no_entries(self):
        self.assertEqual(group_legend_entries(self.root.findGroup("Bravo")), [])

    def test_unchecked_layer_is_excluded(self):
        layer = self.add_layer("Alpha", "Hidden")
        group = self.root.findGroup("Alpha")
        group.findLayer(layer.id()).setItemVisibilityChecked(False)
        self.assertEqual(group_legend_entries(group), [])

    def test_missing_group_yields_no_entries(self):
        self.assertEqual(group_legend_entries(None), [])

    def test_toggling_creates_and_destroys_the_dock(self):
        self.dock.show_legend.setChecked(True)
        self.assertIsNotNone(self.dock.legend_dock)
        self.assertIn(self.dock.legend_dock, self.iface.docks)
        legend = self.dock.legend_dock
        self.dock.show_legend.setChecked(False)
        self.assertIsNone(self.dock.legend_dock)
        self.assertNotIn(legend, self.iface.docks)

    def test_legend_follows_the_active_group(self):
        self.add_layer("Charlie", "Yield")
        self.dock.show_legend.setChecked(True)
        self.dock.play()                                  # Charlie is first
        self.assertEqual(self.dock.legend_dock.current_title, "Charlie")
        self.dock.advance()                               # Bravo next
        self.assertEqual(self.dock.legend_dock.current_title, "Bravo")

    def test_legend_preference_round_trips(self):
        self.dock.show_legend.setChecked(True)
        self.assertTrue(self.project.readBoolEntry(SCOPE, "/ShowLegend", False)[0])

    def test_legend_is_removed_on_teardown(self):
        self.dock.show_legend.setChecked(True)
        self.dock.teardown()
        self.assertIsNone(self.dock.legend_dock)
        self.assertEqual(self.iface.docks, [])


class _StubPluginIface(_StubIface):
    """Adds the menu/toolbar surface that LayerSlideshowPlugin.initGui() needs."""

    def __init__(self):
        super().__init__()
        self.window = QWidget()
        self.menu_actions = []
        self.toolbar_actions = []

    def mainWindow(self):
        return self.window

    def addPluginToMenu(self, menu, action):
        self.menu_actions.append(action)

    def removePluginMenu(self, menu, action):
        self.menu_actions.remove(action)

    def addToolBarIcon(self, action):
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar_actions.remove(action)


class PluginShellTest(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.root = self.project.layerTreeRoot()
        self.root.addGroup("Alpha")
        self.iface = _StubPluginIface()
        self.plugin = LayerSlideshowPlugin(self.iface)

    def tearDown(self):
        self.plugin.unload()

    def test_class_factory_returns_the_plugin(self):
        self.assertIsInstance(classFactory(self.iface), LayerSlideshowPlugin)

    def test_initgui_registers_menu_and_toolbar_with_an_icon(self):
        self.plugin.initGui()
        self.assertEqual(len(self.iface.menu_actions), 1)
        self.assertEqual(len(self.iface.toolbar_actions), 1)
        self.assertFalse(self.iface.toolbar_actions[0].icon().isNull(),
                         "toolbar action should carry icon.png")

    def test_unload_deregisters_everything(self):
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.unload()
        self.assertEqual(self.iface.menu_actions, [])
        self.assertEqual(self.iface.toolbar_actions, [])
        self.assertIsNone(self.plugin.dock)

    def test_run_reuses_the_same_dock(self):
        self.plugin.initGui()
        self.plugin.run()
        first = self.plugin.dock
        self.plugin.run()
        self.assertIs(self.plugin.dock, first)
        self.assertEqual(len(self.iface.docks), 1)

    def test_autostart_off_does_not_create_a_dock(self):
        self.plugin.initGui()
        self.plugin._maybe_autostart()
        self.assertIsNone(self.plugin.dock)

    def test_autostart_on_creates_the_dock(self):
        """A project saved with auto-start must open its own panel."""
        self.project.writeEntry(SCOPE, "/AutoStart", True)
        self.plugin.initGui()
        self.plugin._maybe_autostart()
        self.assertIsNotNone(self.plugin.dock)

    def test_unload_restores_visibility(self):
        self.plugin.initGui()
        self.plugin.run()
        self.root.findGroup("Alpha").setItemVisibilityChecked(False)
        self.plugin.dock.play()
        self.plugin.unload()
        self.assertFalse(self.root.findGroup("Alpha").itemVisibilityChecked())


if __name__ == "__main__":
    unittest.main()
