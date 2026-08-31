<div align="center"><img src="assets/layer-slideshow-icon.svg" alt="Layer Slideshow" width="180"></div>

# Layer Slideshow

Cycles layer-group visibility on a timer, one group shown at a time, with play/pause and loop — for unattended kiosk and display use in QGIS.

AI assistance was used to make this plugin possible.

## Install

Grab the latest `layer-slideshow-vX.Y.Z.zip` from the [Releases](https://github.com/Dozer3530/layer-slideshow/releases) page, then in QGIS:

**Plugins → Manage and Install Plugins → Install from ZIP** → select the file → **Install Plugin**.

Compatible with QGIS 3.22+ and QGIS 4.x (Qt5 and Qt6). Verified against QGIS 3.44.12 (Qt 5.15) and QGIS 4.0.1 (Qt 6.8).

## What it does

1. Every top-level node in the layer tree that is a **group** becomes a slideshow candidate — a checkbox list lets you pick which groups are in the rotation. Anything that isn't in the rotation (a basemap, a reference layer) keeps whatever visibility it already has.
2. Playback order is bottom-to-top through the layer tree, so the group order you'd drag in the Layers panel is the slideshow order.
3. On each tick, the plugin shows exactly one of the checked groups and hides the rest of the checked groups — it never adds or removes layers, only toggles the group's visibility checkbox.
4. An interval spinner (0.1–3600 seconds, default 3.0) controls the timer; changing it mid-run applies on the next tick.
5. **Loop** is on by default so the slideshow repeats indefinitely; uncheck it to stop after the last group.
6. **Minimize** collapses the dock to a small floating Play/Pause bar for kiosk use — **Expand** brings back the full panel.

Groups are matched by name, so group names need to be unique (the plugin warns if two clash). Nested/sub-groups aren't part of the rotation — the plugin only looks at the top level of the layer tree.

## Kiosk mode

Everything needed for an unattended display is saved **into the project**, so the display machine only has to open the `.qgz`:

- **Start automatically when this project opens** — tick it, save the project, and the show runs on open with no interaction. Playback begins a moment after load so layers finish rendering first.
- **Show legend panel** — an optional dock showing the active group's name and symbology, refreshed on every step. Sized large so it stays readable at a distance. It's a dock rather than a canvas overlay, so it can be floated over the map, docked, or left off entirely.
- **Restore visibility** — puts group visibility back exactly as it was before the show started. The plugin also does this automatically when it's unloaded, so it never leaves your project rearranged.

Interval, loop, group selection, auto-start and the legend preference all persist with the project.

## Usage

1. Organize your project so each thing you want to show (a layer plus its labels/annotations) lives together in its own top-level group.
2. Open **Layer Slideshow** from the toolbar or Plugins menu.
3. Check the groups you want in the rotation, set the interval, and hit **Play**.
4. For a kiosk/unattended display, tick **Start automatically when this project opens** and **Show legend panel**, click **Minimize** to shrink the dock to a floating play/pause bar, then save the project.

## Project layout

```
layer-slideshow/
  assets/                   # logo
  layer_slideshow/          # QGIS plugin folder (name fixed for plugin identity)
    __init__.py             # classFactory entry point
    metadata.txt
    icon.png
    LICENSE
    compat.py               # PyQt5/PyQt6 enum resolution, in one place
    slideshow.py            # plugin shell + dock widget (UI, timer, visibility, persistence)
    legend.py               # live legend panel: group symbology -> swatches
    test/                   # headless regression tests against the real QGIS API
  build_zip.ps1              # builds the release zip
  README.md / LICENSE / .gitignore
```

The QGIS plugin folder stays named `layer_slideshow/` because QGIS identifies installed plugins by folder name on disk. Renaming it would orphan existing installs.

## QGIS 3 / QGIS 4 compatibility

QGIS 4 moved from PyQt5 to PyQt6, which scopes enums that PyQt5 left flat (`Qt.UserRole` → `Qt.ItemDataRole.UserRole`, `Qt.Checked` → `Qt.CheckState.Checked`, etc.) and moved `QAction` from `QtWidgets` to `QtGui`. `slideshow.py` resolves the right enum names once at import time and imports `QAction` via `qgis.PyQt.QtGui` (QGIS's own compatibility shim), so the same file runs unmodified on both bindings.

The minimum is 3.22 rather than 3.0 because that `QAction` back-patch lives in QGIS's own `qgis/PyQt/QtGui.py` shim and is not present in early 3.x releases — without it the import fails outright.

Two further Qt6-era traps the tests pin down:

- **An exception inside a Qt slot aborts the process under PyQt6** rather than propagating. `QgsProject.writeEntry()` exposes no `double` overload to Python, so persisting a fractional interval raised `TypeError` from a `valueChanged` handler and took QGIS down with it. The interval is stored as integer milliseconds, and the settings read/write paths log instead of raising.
- **An empty layer-tree group is falsy.** SIP maps `__len__` to the child count, so `if group_node:` is `False` for a valid but empty group. Node checks use `is not None` throughout.

## Development

The tests exercise the real QGIS layer tree, so they run under a QGIS Python:

```powershell
& "C:\Program Files\QGIS 4.0.1\bin\python-qgis.bat" -m unittest layer_slideshow.test.test_slideshow -v
```

Swap in `python-qgis-ltr.bat` from a QGIS 3.x install to check the Qt5 path.

## Build a release zip

```powershell
.\build_zip.ps1
```

Reads the version from `metadata.txt` and writes `layer-slideshow-vX.Y.Z.zip` (gitignored — attach it to a GitHub Release instead of committing it).

## License

MIT — see [LICENSE](LICENSE).

## Author

Zachary Komarnisky — Digital Agriculture program, Olds College of Agriculture & Technology.
