"""Layer Slideshow QGIS plugin.

Cycles layer visibility one layer at a time on a timer, with play/pause and loop.
Works on QGIS 3.x (PyQt5) and QGIS 4.x (PyQt6).
"""

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


class LayerSlideshowPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction("Layer Slideshow", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("Layer Slideshow", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.dock is not None:
            self.dock.stop()
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

        self._build_ui()
        self.refresh_layers()

        # Keep the layer list in sync with the project.
        self.project.layersAdded.connect(self.refresh_layers)
        self.project.layersRemoved.connect(self.refresh_layers)

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
        self.minimize_btn = QPushButton("Minimize \u25be")
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

        self.expand_btn = QPushButton("\u25b4")
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
        """Rebuild the checkbox list from group order, preserving prior checks."""
        prev_checked = set(self.checked_group_names())
        self.list.clear()
        root = self.project.layerTreeRoot()
        for child in reversed(root.children()):
            if not QgsLayerTree.isGroup(child):
                continue
            name = child.name()
            item = QListWidgetItem(name)
            item.setData(USER_ROLE, name)
            item.setFlags(FLAG_CHECKABLE | FLAG_ENABLED)
            keep = name in prev_checked if prev_checked else True
            item.setCheckState(CHECKED if keep else UNCHECKED)
            self.list.addItem(item)

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
        self.running = True
        self._sync_buttons(True)
        if self.index < 0:
            self.index = -1  # advance() will move to first
        self.timer.start(int(self.interval.value() * 1000))
        self.advance()  # show first frame immediately

    def pause(self):
        self.running = False
        self.timer.stop()
        self._sync_buttons(False)
        self.status.setText("Paused")

    def stop(self):
        self.timer.stop()
        self.running = False

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
                self.pause()
                self.status.setText("Finished")
                return

        current = names[self.index]
        self._apply_visibility(names, current)
        self.status.setText("Showing {}/{}: {}".format(self.index + 1, len(names), current))

    def _apply_visibility(self, slideshow_names, visible_name):
        """Show only visible_name among the slideshow groups; leave others untouched."""
        root = self.project.layerTreeRoot()
        for name in slideshow_names:
            node = root.findGroup(name)
            if node is not None:
                node.setItemVisibilityChecked(name == visible_name)
        self.iface.mapCanvas().refresh()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
