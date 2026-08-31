<div align="center"><img src="assets/layer-slideshow-icon.svg" alt="Layer Slideshow" width="180"></div>

# Layer Slideshow

Cycles layer-group visibility on a timer, one group shown at a time, with play/pause and loop — for unattended kiosk and exhibit displays in QGIS.

Built for an Olds College Smart Farm booth at the Calgary Stampede: the map runs unattended in a loop for a walk-up public audience.

AI assistance was used to make this plugin possible.

## Install

Grab the latest `layer-slideshow-vX.Y.Z.zip` from the [Releases](https://github.com/Dozer3530/layer-slideshow/releases) page, then in QGIS:

**Plugins → Manage and Install Plugins → Install from ZIP** → select the file → **Install Plugin**.

Compatible with QGIS 3.x and QGIS 4.x (Qt5 and Qt6).

## What it does

1. Every top-level node in the layer tree that is a **group** becomes a slideshow candidate — a checkbox list lets you pick which groups are in the rotation. Anything that isn't in the rotation (a basemap, a reference layer) keeps whatever visibility it already has.
2. Playback order is bottom-to-top through the layer tree, so the group order you'd drag in the Layers panel is the slideshow order.
3. On each tick, the plugin shows exactly one of the checked groups and hides the rest of the checked groups — it never adds or removes layers, only toggles the group's visibility checkbox.
4. An interval spinner (0.1–3600 seconds, default 3.0) controls the timer; changing it mid-run applies on the next tick.
5. **Loop** is on by default so the slideshow repeats indefinitely; uncheck it to stop after the last group.
6. **Minimize** collapses the dock to a small floating Play/Pause bar for kiosk use — **Expand** brings back the full panel.

Groups are matched by name, so group names need to be unique. Nested/sub-groups aren't part of the rotation — the plugin only looks at the top level of the layer tree.

## Usage

1. Organize your project so each thing you want to show (a layer plus its labels/annotations) lives together in its own top-level group.
2. Open **Layer Slideshow** from the toolbar or Plugins menu.
3. Check the groups you want in the rotation, set the interval, and hit **Play**.
4. For a kiosk/unattended display, click **Minimize** to shrink the dock down to a small floating play/pause bar, then leave the map running.

## Project layout

```
layer-slideshow/
  assets/                   # logo
  layer_slideshow/          # QGIS plugin folder (name fixed for plugin identity)
    __init__.py             # classFactory entry point
    metadata.txt
    icon.png
    LICENSE
    slideshow.py            # plugin shell + dock widget (UI, timer, visibility logic)
  build_zip.ps1              # builds the release zip
  README.md / LICENSE / .gitignore
```

The QGIS plugin folder stays named `layer_slideshow/` because QGIS identifies installed plugins by folder name on disk. Renaming it would orphan existing installs.

## QGIS 3 / QGIS 4 compatibility

QGIS 4 moved from PyQt5 to PyQt6, which scopes enums that PyQt5 left flat (`Qt.UserRole` → `Qt.ItemDataRole.UserRole`, `Qt.Checked` → `Qt.CheckState.Checked`, etc.) and moved `QAction` from `QtWidgets` to `QtGui`. `slideshow.py` resolves the right enum names once at import time and imports `QAction` via `qgis.PyQt.QtGui` (QGIS's own compatibility shim), so the same file runs unmodified on both bindings.

## Build a release zip

```powershell
.\build_zip.ps1
```

Reads the version from `metadata.txt` and writes `layer-slideshow-vX.Y.Z.zip` (gitignored — attach it to a GitHub Release instead of committing it).

## License

MIT — see [LICENSE](LICENSE).

## Author

Zachary Komarnisky — Digital Agriculture program, Olds College of Agriculture & Technology.
