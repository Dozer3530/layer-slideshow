"""Layer Slideshow QGIS plugin.

Cycles layer-group visibility one group at a time on a timer, with play/pause
and loop. Works on QGIS 3.22+ (PyQt5) and QGIS 4.x (PyQt6).

Slideshow settings live in the project, not in QgsSettings: a kiosk .qgz then
carries its own show definition, so the booth machine only has to open the file.
"""

import os

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QDoubleSpinBox,
    QLabel, QCheckBox,
)
from qgis.PyQt.QtGui import QIcon, QAction
from qgis.core import QgsProject, QgsLayerTree, QgsMessageLog, Qgis

from .compat import (  # noqa: F401  (re-exported for callers and tests)
    USER_ROLE, CHECKED, UNCHECKED, FLAG_CHECKABLE, FLAG_ENABLED,
    DOCK_RIGHT, DOCK_LEFT,
)
from .legend import SlideshowLegendDock

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.png")

# QgsProject entry scope for persisted settings.
SCOPE = "LayerSlideshow"
# Let layers finish loading and the first render settle before auto-starting.
AUTOSTART_DELAY_MS = 1500


class LayerSlideshowPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction(QIcon(ICON_PATH), "Layer Slideshow",
                              self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("Layer Slideshow", self.action)
        self.iface.addToolBarIcon(self.action)
        # Watched at plugin level, not dock level: auto-start has to be able to
        # create the dock for a project opened before anyone clicked the button.
        QgsProject.instance().readProject.connect(self._maybe_autostart)

    def unload(self):
        try:
            QgsProject.instance().readProject.disconnect(self._maybe_autostart)
        except (TypeError, RuntimeError):
            pass
        if self.dock is not None:
            self.dock.teardown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginMenu("Layer Slideshow", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        if self.dock is None:
            self.dock = SlideshowDock(self.iface)
            self.iface.addDockWidget(DOCK_RIGHT, self.dock)
        self.dock.show()
        self.dock.raise_()

    def _maybe_autostart(self, *args):
        if not QgsProject.instance().readBoolEntry(SCOPE, "/AutoStart", False)[0]:
            return
        self.run()
        QTimer.singleShot(AUTOSTART_DELAY_MS, self.dock.play)


class SlideshowDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("Layer Slideshow")
        self.setObjectName("LayerSlideshowDock")
        self.iface = iface
        self.project = QgsProject.instance()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.index = -1
        self.running = False
        # Name of the group currently on screen, so playback can survive a list
        # rebuild (groups added/renamed mid-show).
        self.current_name = None
        # True once the show has run off the end with looping off, so Play knows
        # to restart rather than immediately re-finish.
        self._finished = False
        # Distinguishes "first ever populate, default everything on" from
        # "the user has since made a selection" (which may legitimately be empty).
        self._initialized = False
        # Group visibility as it was before the show first started, so the
        # project can be handed back unmodified.
        self._visibility_snapshot = None
        # Suppress persistence while we are the ones changing the widgets.
        self._loading = False
        self.legend_dock = None

        self._build_ui()
        self.refresh_layers()
        self._load_settings()
        self._connect_project()

    # ---------- Project signals ----------
    def _connect_project(self):
        """Watch the layer tree for group changes, not just layer changes.

        Groups are layer-tree nodes, so layersAdded/layersRemoved never fire for
        them -- adding, removing or renaming a group needs the tree's own signals.
        """
        root = self.project.layerTreeRoot()
        root.addedChildren.connect(self.refresh_layers)
        root.removedChildren.connect(self.refresh_layers)
        root.nameChanged.connect(self.refresh_layers)
        self.project.readProject.connect(self._project_reloaded)
        self.project.cleared.connect(self._project_reloaded)

    def _disconnect_project(self):
        root = self.project.layerTreeRoot()
        for signal, slot in (
            (root.addedChildren, self.refresh_layers),
            (root.removedChildren, self.refresh_layers),
            (root.nameChanged, self.refresh_layers),
            (self.project.readProject, self._project_reloaded),
            (self.project.cleared, self._project_reloaded),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _project_reloaded(self, *args):
        self.stop()
        self.index = -1
        self.current_name = None
        self._finished = False
        self._initialized = False
        # The snapshot belonged to the old project; it means nothing here.
        self._visibility_snapshot = None
        self.refresh_layers()
        self._load_settings()
        self.status.setText("Idle")
        if self.legend_dock is not None:
            self.legend_dock.show_placeholder("Slideshow not running")

    def teardown(self):
        """Stop playback, hand the project back, drop connections (unload)."""
        self.stop()
        self.restore_visibility()
        self._disconnect_project()
        self._destroy_legend()

    # ---------- Persistence ----------
    def _load_settings(self):
        """Read the show definition back out of the project."""
        self._loading = True
        try:
            ms, ok = self.project.readNumEntry(SCOPE, "/IntervalMs", 3000)
            self.interval.setValue((ms / 1000.0) if ok and ms > 0 else 3.0)

            loop, ok = self.project.readBoolEntry(SCOPE, "/Loop", True)
            self.loop.setChecked(loop if ok else True)

            autostart, ok = self.project.readBoolEntry(SCOPE, "/AutoStart", False)
            self.autostart.setChecked(autostart if ok else False)

            # `ok` alone, not `ok and groups`: readListEntry reports False for a
            # key that was never written and True for one saved as empty, so a
            # deliberately empty selection must not fall through to "check all".
            groups, ok = self.project.readListEntry(SCOPE, "/Groups")
            if ok:
                wanted = set(groups)
                for i in range(self.list.count()):
                    item = self.list.item(i)
                    item.setCheckState(
                        CHECKED if item.data(USER_ROLE) in wanted else UNCHECKED)
                self._initialized = True

            show_legend, ok = self.project.readBoolEntry(SCOPE, "/ShowLegend", False)
            self.show_legend.setChecked(show_legend if ok else False)
        except Exception as exc:                        # pragma: no cover
            QgsMessageLog.logMessage(
                "Could not read slideshow settings: {}".format(exc),
                "Layer Slideshow", Qgis.Warning)
        finally:
            self._loading = False

    def _persist(self, *args):
        """Write the show definition into the project.

        Runs from Qt signal handlers, where PyQt6 aborts the process on an
        unhandled exception rather than propagating it -- so this must never
        raise. Note the interval is stored as integer milliseconds: writeEntry
        exposes no double overload to Python.
        """
        if self._loading:
            return
        try:
            self.project.writeEntry(
                SCOPE, "/IntervalMs", int(round(self.interval.value() * 1000)))
            self.project.writeEntry(SCOPE, "/Loop", self.loop.isChecked())
            self.project.writeEntry(SCOPE, "/AutoStart", self.autostart.isChecked())
            self.project.writeEntry(
                SCOPE, "/ShowLegend", self.show_legend.isChecked())
            self.project.writeEntry(SCOPE, "/Groups", self.checked_group_names())
        except Exception as exc:                        # pragma: no cover
            QgsMessageLog.logMessage(
                "Could not save slideshow settings: {}".format(exc),
                "Layer Slideshow", Qgis.Warning)

    # ---------- UI ----------
    def _build_ui(self):
        # Container holds both the full panel and the mini bar; only one shows.
        self.container = QWidget()
        outer = QVBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)

        self.full_panel = self._build_full_panel()
        self.mini_panel = self._build_mini_panel()
        self.mini_panel.setVisible(False)

        outer.addWidget(self.full_panel)
        outer.addWidget(self.mini_panel)
        self.setWidget(self.container)

    def _build_full_panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # Minimize control at the top.
        top_row = QHBoxLayout()
        top_row.addStretch()
        self.minimize_btn = QPushButton("Minimize ▾")
        self.minimize_btn.setToolTip("Collapse to a floating play/pause bar")
        self.minimize_btn.clicked.connect(self.minimize)
        top_row.addWidget(self.minimize_btn)
        layout.addLayout(top_row)

        layout.addWidget(QLabel("Groups in slideshow (checked, bottom-to-top order):"))

        self.list = QListWidget()
        self.list.itemChanged.connect(self._persist)
        layout.addWidget(self.list)

        list_btns = QHBoxLayout()
        refresh_btn = QPushButton("Refresh group list")
        refresh_btn.clicked.connect(self.refresh_layers)
        list_btns.addWidget(refresh_btn)
        self.restore_btn = QPushButton("Restore visibility")
        self.restore_btn.setToolTip(
            "Put group visibility back the way it was before the slideshow started")
        self.restore_btn.clicked.connect(self._restore_clicked)
        self.restore_btn.setEnabled(False)
        list_btns.addWidget(self.restore_btn)
        layout.addLayout(list_btns)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval (s):"))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 3600.0)
        self.interval.setDecimals(1)
        self.interval.setSingleStep(0.5)
        self.interval.setValue(3.0)
        self.interval.valueChanged.connect(self._interval_changed)
        interval_row.addWidget(self.interval)
        layout.addLayout(interval_row)

        self.loop = QCheckBox("Loop")
        self.loop.setChecked(True)
        self.loop.toggled.connect(self._persist)
        layout.addWidget(self.loop)

        self.autostart = QCheckBox("Start automatically when this project opens")
        self.autostart.setToolTip(
            "Save the project with this ticked and the show runs unattended on open")
        self.autostart.toggled.connect(self._persist)
        layout.addWidget(self.autostart)

        self.show_legend = QCheckBox("Show legend panel")
        self.show_legend.setToolTip(
            "Display the active group's symbology in its own dock")
        self.show_legend.toggled.connect(self._legend_toggled)
        layout.addWidget(self.show_legend)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause)
        self.pause_btn.setEnabled(False)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.pause_btn)
        layout.addLayout(btn_row)

        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addStretch()
        return w

    def _build_mini_panel(self):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(4, 4, 4, 4)

        self.mini_play_btn = QPushButton("Play")
        self.mini_play_btn.clicked.connect(self.play)
        self.mini_pause_btn = QPushButton("Pause")
        self.mini_pause_btn.clicked.connect(self.pause)
        self.mini_pause_btn.setEnabled(False)
        row.addWidget(self.mini_play_btn)
        row.addWidget(self.mini_pause_btn)

        self.expand_btn = QPushButton("▴")
        self.expand_btn.setToolTip("Expand to full panel")
        self.expand_btn.setFixedWidth(32)
        self.expand_btn.clicked.connect(self.expand)
        row.addWidget(self.expand_btn)
        return w

    # ---------- Minimize / expand ----------
    def minimize(self):
        self.full_panel.setVisible(False)
        self.mini_panel.setVisible(True)
        self.setFloating(True)
        self.resize(220, 48)

    def expand(self):
        self.mini_panel.setVisible(False)
        self.full_panel.setVisible(True)
        self.resize(320, 520)

    def _sync_buttons(self, playing):
        """Keep full and mini play/pause buttons in the same enabled state."""
        self.play_btn.setEnabled(not playing)
        self.pause_btn.setEnabled(playing)
        self.mini_play_btn.setEnabled(not playing)
        self.mini_pause_btn.setEnabled(playing)

    # ---------- Legend ----------
    def _legend_toggled(self, checked):
        if checked:
            self._ensure_legend()
            self._update_legend()
        else:
            self._destroy_legend()
        self._persist()

    def _ensure_legend(self):
        if self.legend_dock is None:
            self.legend_dock = SlideshowLegendDock()
            self.iface.addDockWidget(DOCK_LEFT, self.legend_dock)
        self.legend_dock.show()

    def _destroy_legend(self):
        if self.legend_dock is None:
            return
        self.iface.removeDockWidget(self.legend_dock)
        self.legend_dock.deleteLater()
        self.legend_dock = None

    def _update_legend(self):
        if self.legend_dock is None:
            return
        if self.current_name is None:
            self.legend_dock.show_placeholder("Slideshow not running")
            return
        node = self.project.layerTreeRoot().findGroup(self.current_name)
        if node is None:
            self.legend_dock.show_placeholder(
                "Group \"{}\" not found".format(self.current_name))
        else:
            self.legend_dock.show_group(node)

    # ---------- Visibility snapshot ----------
    def _snapshot_visibility(self):
        """Remember every top-level group's visibility before the show starts."""
        if self._visibility_snapshot is not None:
            return
        root = self.project.layerTreeRoot()
        self._visibility_snapshot = {
            child.name(): child.itemVisibilityChecked()
            for child in root.children() if QgsLayerTree.isGroup(child)
        }
        self.restore_btn.setEnabled(True)

    def restore_visibility(self):
        """Put group visibility back as it was before the show started."""
        if not self._visibility_snapshot:
            self._visibility_snapshot = None
            return False
        root = self.project.layerTreeRoot()
        for name, visible in self._visibility_snapshot.items():
            node = root.findGroup(name)
            if node is not None:
                node.setItemVisibilityChecked(visible)
        self._visibility_snapshot = None
        self.restore_btn.setEnabled(False)
        self.iface.mapCanvas().refresh()
        return True

    def _restore_clicked(self):
        self.stop()
        self.index = -1
        self.current_name = None
        self._finished = False
        if self.restore_visibility():
            self.status.setText("Visibility restored")
        self._update_legend()

    # ---------- Layer list ----------
    def refresh_layers(self, *args):
        """Rebuild the checkbox list from group order, preserving prior checks.

        A group the user explicitly unchecked stays unchecked -- including when
        they unchecked every one. Groups that are new since the last rebuild
        (added, or renamed into existence) join the show by default.
        """
        if self._initialized:
            prev_checked = set(self.checked_group_names())
            prev_known = {self.list.item(i).data(USER_ROLE)
                          for i in range(self.list.count())}
        else:
            prev_checked = None
            prev_known = set()

        was_loading, self._loading = self._loading, True
        try:
            self.list.clear()
            root = self.project.layerTreeRoot()
            names = []
            for child in reversed(root.children()):
                if not QgsLayerTree.isGroup(child):
                    continue
                name = child.name()
                names.append(name)
                item = QListWidgetItem(name)
                item.setData(USER_ROLE, name)
                item.setFlags(FLAG_CHECKABLE | FLAG_ENABLED)
                if prev_checked is None:
                    keep = True                   # first populate: everything on
                elif name in prev_checked:
                    keep = True                   # user had it on
                elif name not in prev_known:
                    keep = True                   # brand new group joins the show
                else:
                    keep = False                  # user turned it off; respect that
                item.setCheckState(CHECKED if keep else UNCHECKED)
                self.list.addItem(item)
        finally:
            self._loading = was_loading

        self._initialized = True
        self._resync_index()
        self._warn_duplicates(names)

    def _resync_index(self):
        """Keep the playhead on the same group after the list is rebuilt."""
        names = self.checked_group_names()
        if not names:
            self.index = -1
            self.current_name = None
            return
        if self.current_name in names:
            self.index = names.index(self.current_name)
            return
        # The playing group vanished under us (renamed or unchecked). Hold the
        # slot and adopt whatever now occupies it, so current_name never goes stale.
        if self.index >= len(names):
            self.index = len(names) - 1
        if 0 <= self.index:
            self.current_name = names[self.index]

    def _warn_duplicates(self, names):
        """Group lookup is by name, so duplicates are ambiguous -- say so."""
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes and not self.running:
            self.status.setText(
                "Warning: duplicate group names ({}). Rename them so each is unique."
                .format(", ".join(dupes)))

    def checked_group_names(self):
        names = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == CHECKED:
                names.append(item.data(USER_ROLE))
        return names

    # ---------- Playback ----------
    def _interval_changed(self, val):
        if self.running:
            self.timer.setInterval(int(val * 1000))
        self._persist()

    def play(self):
        names = self.checked_group_names()
        if not names:
            self.status.setText("No groups checked.")
            return
        self._snapshot_visibility()
        # A finished non-looping run restarts from the top instead of instantly
        # re-finishing on the first tick.
        if self._finished or self.index < 0:
            self.index = -1
            self._finished = False
        self.running = True
        self._sync_buttons(True)
        self.timer.start(int(self.interval.value() * 1000))
        self.advance()  # show first frame immediately

    def pause(self):
        self.running = False
        self.timer.stop()
        self._sync_buttons(False)
        self.status.setText("Paused")

    def stop(self):
        """Halt playback without touching the status text (close / unload path)."""
        self.timer.stop()
        self.running = False
        self._sync_buttons(False)

    def advance(self):
        names = self.checked_group_names()
        if not names:
            self.pause()
            self.status.setText("No groups checked.")
            return

        self.index += 1
        if self.index >= len(names):
            if self.loop.isChecked():
                self.index = 0
            else:
                self.index = len(names) - 1
                self._finished = True
                self.pause()
                self.status.setText("Finished")
                return

        current = names[self.index]
        self.current_name = current
        found = self._apply_visibility(names, current)
        if found:
            self.status.setText(
                "Showing {}/{}: {}".format(self.index + 1, len(names), current))
        else:
            self.status.setText(
                "Group \"{}\" no longer exists (renamed or deleted) — "
                "click Refresh group list.".format(current))
        self._update_legend()

    def _apply_visibility(self, slideshow_names, visible_name):
        """Show only visible_name among the slideshow groups; leave others untouched.

        Returns whether the target group was actually found in the tree.
        """
        root = self.project.layerTreeRoot()
        found = False
        for name in slideshow_names:
            node = root.findGroup(name)
            if node is None:
                continue
            if name == visible_name:
                found = True
            node.setItemVisibilityChecked(name == visible_name)
        self.iface.mapCanvas().refresh()
        return found

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
