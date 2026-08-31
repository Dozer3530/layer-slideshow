"""Layer Slideshow QGIS plugin.

Cycles layer-group visibility one group at a time on a timer, with play/pause
and loop. Works on QGIS 3.x (PyQt5) and QGIS 4.x (PyQt6).
"""

import os

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QDoubleSpinBox,
    QLabel, QCheckBox,
)
from qgis.PyQt.QtGui import QIcon, QAction
from qgis.core import QgsProject, QgsLayerTree

# Enum compatibility: PyQt6 scopes enums (Qt.ItemDataRole.UserRole), PyQt5 does not
# (Qt.UserRole). Resolve once here so the rest of the file is version-agnostic.
USER_ROLE = getattr(Qt, "UserRole", None)
if USER_ROLE is None:
    USER_ROLE = Qt.ItemDataRole.UserRole
    CHECKED = Qt.CheckState.Checked
    UNCHECKED = Qt.CheckState.Unchecked
    FLAG_CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
    FLAG_ENABLED = Qt.ItemFlag.ItemIsEnabled
    DOCK_RIGHT = Qt.DockWidgetArea.RightDockWidgetArea
else:
    CHECKED = Qt.Checked
    UNCHECKED = Qt.Unchecked
    FLAG_CHECKABLE = Qt.ItemIsUserCheckable
    FLAG_ENABLED = Qt.ItemIsEnabled
    DOCK_RIGHT = Qt.RightDockWidgetArea

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.png")


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

    def unload(self):
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


class SlideshowDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("Layer Slideshow")
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

        self._build_ui()
        self.refresh_layers()
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
        # A newly loaded project gets a fresh default selection.
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
        self.refresh_layers()
        self.status.setText("Idle")

    def teardown(self):
        """Stop playback and drop project connections (plugin unload)."""
        self.stop()
        self._disconnect_project()

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
        layout.addWidget(self.list)

        refresh_btn = QPushButton("Refresh group list")
        refresh_btn.clicked.connect(self.refresh_layers)
        layout.addWidget(refresh_btn)

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
        layout.addWidget(self.loop)

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
        self.resize(320, 480)

    def _sync_buttons(self, playing):
        """Keep full and mini play/pause buttons in the same enabled state."""
        self.play_btn.setEnabled(not playing)
        self.pause_btn.setEnabled(playing)
        self.mini_play_btn.setEnabled(not playing)
        self.mini_pause_btn.setEnabled(playing)

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
                keep = True                       # first populate: everything on
            elif name in prev_checked:
                keep = True                       # user had it on
            elif name not in prev_known:
                keep = True                       # brand new group joins the show
            else:
                keep = False                      # user turned it off; respect that
            item.setCheckState(CHECKED if keep else UNCHECKED)
            self.list.addItem(item)

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

    def play(self):
        names = self.checked_group_names()
        if not names:
            self.status.setText("No groups checked.")
            return
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
