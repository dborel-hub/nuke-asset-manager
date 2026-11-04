"""
List widget whose drag carries assets to Nuke's Node Graph.

The drag holds ONE line of plain text: "<marker> <json>". Nuke's drop hook
(panel_registration._on_drop) reads it and creates the nodes via TCL.
No file URLs on purpose: those would make Nuke's own drop handler create an
extra Read node as well.
"""

import json

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt, QMimeData
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt, QMimeData

ROLE_ASSET = Qt.UserRole
ROLE_PIXMAP = Qt.UserRole + 1


class DraggableAssetListWidget(QtWidgets.QListWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        assets = [i.data(ROLE_ASSET) for i in items if i.data(ROLE_ASSET)]
        if not assets:
            return

        payload = [{
            'filepath': a.filepath,
            'display_path': a.get_display_path(),
            'color_space': a.color_space,
            'filename': a.filename,
            'category': a.category,
            'first_frame': a.first_frame,
            'last_frame': a.last_frame,
            'is_sequence': a.is_sequence,
            'extension': a.extension,
        } for a in assets]

        from ...nuke_integration.panel_registration import DRAG_MARKER
        mime = QMimeData()
        mime.setText(DRAG_MARKER + ' ' + json.dumps(payload))

        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(items, len(assets)))
        drag.exec_(supportedActions)

    @staticmethod
    def _drag_pixmap(items, count):
        """Small thumbnail with a count badge when dragging several assets."""
        w, h = 112, 63
        pix = QtGui.QPixmap(w, h)
        pix.fill(Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(0, 0, w, h), 5, 5)
        p.fillPath(path, QtGui.QColor(12, 14, 17, 230))

        thumb = items[0].data(ROLE_PIXMAP) if items else None
        if thumb is not None and not thumb.isNull():
            p.setClipPath(path)
            scaled = thumb.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
            p.setClipping(False)

        if count > 1:
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(63, 183, 217))
            p.drawEllipse(QtCore.QRectF(w - 26, 4, 22, 22))
            p.setPen(QtGui.QColor(10, 20, 24))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(QtCore.QRectF(w - 26, 4, 22, 22), Qt.AlignCenter, str(count))
        p.end()
        return pix
