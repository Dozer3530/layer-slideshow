"""Live legend panel for the slideshow.

Shows the symbology of whichever group is currently on screen, refreshed on
each step. A dock widget rather than a canvas overlay: QgsMapCanvasItem
subclasses need hand-painted rendering that behaves differently under Qt6,
while a dock is plain widget code that works unmodified on both bindings.

Sized for a walk-up public audience -- large group heading, large swatches.
"""

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QFont, QPixmap
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame,
)
from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsSymbolLayerUtils

from .compat import ALIGN_LEFT, ALIGN_TOP, ALIGN_LEFT_VCENTER

SWATCH_PX = 28
HEADING_PT = 16
ENTRY_PT = 11


def _color_pixmap(color, size=SWATCH_PX):
    """Flat swatch for renderers that report colours rather than symbols."""
    pix = QPixmap(size, size)
    pix.fill(QColor(color))
    return pix


def _vector_entries(layer, size):
    renderer = layer.renderer()
    if renderer is None:
        return [(layer.name(), None)]

    try:
        items = renderer.legendSymbolItems()
    except Exception:
        items = []

    entries = []
    for item in items:
        symbol = item.symbol()
        pix = None
        if symbol is not None:
            try:
                pix = QgsSymbolLayerUtils.symbolPreviewPixmap(
                    symbol, QSize(size, size))
            except Exception:
                pix = None
        # A single-symbol renderer reports one item with an empty label; the
        # layer name is the useful caption there.
        label = item.label() or ""
        if not label and len(items) == 1:
            label = layer.name()
        entries.append((label, pix))

    return entries or [(layer.name(), None)]


def _raster_entries(layer, size):
    try:
        items = layer.legendSymbologyItems()
    except Exception:
        items = []
    entries = [(label, _color_pixmap(color, size)) for label, color in items]
    return entries or [(layer.name(), None)]


def group_legend_entries(group_node, size=SWATCH_PX):
    """Flatten a layer-tree group into ``[(label, QPixmap|None), ...]``.

    Only layers whose own checkbox is ticked are included -- an unchecked layer
    inside a visible group does not render, so it should not appear in the
    legend either.
    """
    entries = []
    if group_node is None:
        return entries

    for layer_node in group_node.findLayers():
        if not layer_node.itemVisibilityChecked():
            continue
        layer = layer_node.layer()
        if layer is None:                      # still loading, or broken path
            continue
        if isinstance(layer, QgsVectorLayer):
            entries.extend(_vector_entries(layer, size))
        elif isinstance(layer, QgsRasterLayer):
            entries.extend(_raster_entries(layer, size))
        else:
            entries.append((layer.name(), None))
    return entries


class SlideshowLegendDock(QDockWidget):
    """Dock showing the active group's name and symbology."""

    def __init__(self, parent=None):
        super().__init__("Slideshow Legend", parent)
        self.setObjectName("SlideshowLegendDock")

        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setAlignment(ALIGN_TOP)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body)
        self.setWidget(scroll)

        # What the panel is currently showing (None while a placeholder is up).
        self.current_title = None
        self.show_placeholder("Slideshow not running")

    # ---------- content ----------
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def show_placeholder(self, text):
        self._clear()
        self.current_title = None
        label = QLabel(text)
        label.setWordWrap(True)
        self._layout.addWidget(label)

    def show_group(self, group_node, title=None):
        """Rebuild the panel for one group."""
        self._clear()
        # `is not None`, never truthiness: SIP maps __len__ to the child count,
        # so an empty layer-tree group is falsy despite being a valid node.
        if title:
            self.current_title = title
        elif group_node is not None:
            self.current_title = group_node.name()
        else:
            self.current_title = ""

        heading = QLabel(self.current_title)
        font = QFont()
        font.setPointSize(HEADING_PT)
        font.setBold(True)
        heading.setFont(font)
        heading.setWordWrap(True)
        self._layout.addWidget(heading)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine if hasattr(QFrame, "Shape")
                           else QFrame.HLine)
        self._layout.addWidget(rule)

        entries = group_legend_entries(group_node)
        if not entries:
            self._layout.addWidget(QLabel("(no visible layers)"))
            return

        for label, pixmap in entries:
            self._layout.addWidget(self._entry_row(label, pixmap))

    def _entry_row(self, label, pixmap):
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 2, 0, 2)

        swatch = QLabel()
        swatch.setFixedSize(SWATCH_PX, SWATCH_PX)
        if pixmap is not None:
            swatch.setPixmap(pixmap)
        box.addWidget(swatch)

        text = QLabel(label)
        text.setWordWrap(True)
        font = QFont()
        font.setPointSize(ENTRY_PT)
        text.setFont(font)
        box.addWidget(text, 1, ALIGN_LEFT_VCENTER)

        box.setAlignment(ALIGN_LEFT)
        return row
