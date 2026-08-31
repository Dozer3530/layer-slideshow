"""PyQt5 / PyQt6 enum compatibility.

PyQt6 scopes enums that PyQt5 left flat (``Qt.UserRole`` became
``Qt.ItemDataRole.UserRole``). Resolve every name the plugin needs once, here,
so the rest of the package is binding-agnostic.
"""

from qgis.PyQt.QtCore import Qt

# PyQt5 exposes the flat name; PyQt6 does not. One probe decides the branch.
_FLAT = getattr(Qt, "UserRole", None) is not None

if _FLAT:
    USER_ROLE = Qt.UserRole
    CHECKED = Qt.Checked
    UNCHECKED = Qt.Unchecked
    FLAG_CHECKABLE = Qt.ItemIsUserCheckable
    FLAG_ENABLED = Qt.ItemIsEnabled
    DOCK_RIGHT = Qt.RightDockWidgetArea
    DOCK_LEFT = Qt.LeftDockWidgetArea
    ALIGN_LEFT = Qt.AlignLeft
    ALIGN_TOP = Qt.AlignTop
    ALIGN_VCENTER = Qt.AlignVCenter
else:
    USER_ROLE = Qt.ItemDataRole.UserRole
    CHECKED = Qt.CheckState.Checked
    UNCHECKED = Qt.CheckState.Unchecked
    FLAG_CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
    FLAG_ENABLED = Qt.ItemFlag.ItemIsEnabled
    DOCK_RIGHT = Qt.DockWidgetArea.RightDockWidgetArea
    DOCK_LEFT = Qt.DockWidgetArea.LeftDockWidgetArea
    ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft
    ALIGN_TOP = Qt.AlignmentFlag.AlignTop
    ALIGN_VCENTER = Qt.AlignmentFlag.AlignVCenter

ALIGN_LEFT_VCENTER = ALIGN_LEFT | ALIGN_VCENTER
