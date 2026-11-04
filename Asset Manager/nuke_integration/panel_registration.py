"""
Panel Registration - open the Asset Manager window inside Nuke

Nuke Indie safe:
- Opening the window touches no nodes.
- Drag & drop onto the Node Graph goes through Nuke's official drop hook
  (nukescripts.addDropDataCallback), which hands us plain text. Nodes are
  then created via TCL (see node_creation.py) - zero Python node objects.
  The old version installed an event filter on Nuke's main window that
  hijacked EVERY file drop (even from Explorer) and created nodes in Python.
"""

import json

try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    from PySide6 import QtWidgets, QtCore
from ..log import log

# Marker that identifies a drag coming from the Asset Manager.
# draggable_list_widget.py puts "<marker> <json>" (one line) in the drag's text.
DRAG_MARKER = 'ASSET_MANAGER_DROP_V1'

_window = None
_drop_callback_installed = False


# ------------------------------------------------------------------
# Window
# ------------------------------------------------------------------

class AssetManagerWindow(QtWidgets.QMainWindow):
    """Main window: remembers size/position and panel layout on close."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setWindowTitle("Asset Manager")

    def closeEvent(self, event):
        panel = self.centralWidget()
        try:
            cfg = panel.library.config
            cfg.config['window_geometry'] = bytes(self.saveGeometry().toBase64()).decode('ascii')
            panel.save_state()   # also writes the config file
        except Exception as e:
            log.warning("Could not save window state: %s", e)
        super().closeEvent(event)


def show_asset_manager():
    """Show the Asset Manager window (creates it on first call)."""
    global _window

    _install_drop_callback()

    if _window is not None:
        try:
            _window.show()
            _window.raise_()
            _window.activateWindow()
            return _window
        except RuntimeError:
            _window = None  # Qt object was destroyed

    from ..ui import AssetManagerPanel
    from .nuke_utils import get_nuke_main_window

    nuke_main = get_nuke_main_window()

    # Parent to Nuke's main window so it stays in front of Nuke,
    # Qt.Window keeps it a separate, movable window.
    window = AssetManagerWindow(nuke_main)
    panel = AssetManagerPanel()
    window.setCentralWidget(panel)

    saved = panel.library.config.get('window_geometry')
    restored = False
    if saved:
        try:
            restored = window.restoreGeometry(QtCore.QByteArray.fromBase64(saved.encode('ascii')))
        except Exception:
            restored = False
    if not restored:
        window.resize(1400, 800)
        if nuke_main is not None:
            geo = nuke_main.geometry()
            window.move(geo.x() + (geo.width() - 1400) // 2,
                        geo.y() + (geo.height() - 800) // 2)

    window.show()
    _window = window
    return window


# ------------------------------------------------------------------
# Drag & drop onto the Node Graph
# ------------------------------------------------------------------

class _DroppedAsset(object):
    """
    Lightweight stand-in for AssetItem built from drag data.
    (Building a real AssetItem would re-scan the file / run ffprobe.)
    Has exactly what node_creation.py reads.
    """

    def __init__(self, info):
        self.filepath = info.get('filepath', '')
        self.filename = info.get('filename', '')
        self.category = info.get('category', 'Footage')
        self.extension = (info.get('extension') or '').lower()
        self.first_frame = info.get('first_frame')
        self.last_frame = info.get('last_frame')
        self.frame_count = None
        self.color_space = info.get('color_space')
        self._display_path = info.get('display_path') or self.filepath

    def get_display_path(self):
        return self._display_path


def _on_drop(mime_type, text):
    """
    Called by Nuke for drops on the Node Graph.
    Return True = handled (Nuke does nothing else), None = not ours.
    """
    if not text or DRAG_MARKER not in text:
        return None

    # Everything after the marker, from the first "[" (the JSON list).
    # Tolerant of extra whitespace / line breaks Nuke may add.
    rest = text.split(DRAG_MARKER, 1)[1]
    start = rest.find('[')
    try:
        payload = json.loads(rest[start:].strip()) if start >= 0 else None
    except Exception as e:
        payload = None
        log.warning('Could not read drop data: %s' % e)
    if not payload:
        log.debug('Drop data received (mime=%s): %r' % (mime_type, text[:300]))
        return True  # it was ours, don't let Nuke paste the raw text

    from .node_creation import create_nodes_from_assets
    assets = [_DroppedAsset(info) for info in payload]
    names = create_nodes_from_assets(assets)
    log.debug('Dropped %d asset(s): %s' % (len(names), ', '.join(names)))
    return True


def _install_drop_callback():
    """Register the drop hook once per Nuke session."""
    global _drop_callback_installed
    if _drop_callback_installed:
        return
    try:
        import nukescripts
        nukescripts.addDropDataCallback(_on_drop)
        _drop_callback_installed = True
    except Exception as e:
        log.warning('Drag & drop to Node Graph unavailable: %s' % e)
