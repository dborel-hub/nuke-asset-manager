"""
Asset Grid - thumbnails in grid or list view.

- Cards are painted by AssetCardDelegate (16:9 thumbnail box, readable name
  even when selected, accent border on selection, red name when missing).
- Thumbnail images are decoded in worker threads (ThumbLoader) and handed
  to the UI thread through a Qt signal, so big libraries don't freeze it.
- Card size is adjustable (set_card_width), Enter creates nodes.
"""

import os
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt, Signal, QSize
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt, Signal, QSize

from .. import theme
from .draggable_list_widget import DraggableAssetListWidget


ROLE_ASSET = Qt.UserRole
ROLE_PIXMAP = Qt.UserRole + 1
ROLE_LOADING = Qt.UserRole + 2      # hover preview being prepared -> spinner

VIDEO_EXTENSIONS = ('.mov', '.mp4', '.avi', '.mxf', '.mkv', '.webm', '.m4v')

CARD_W_DEFAULT = 200
CARD_W_MIN = 120
CARD_W_MAX = 360
CARD_GAP = 14
TEXT_H = 46            # name + meta under the thumbnail
ROW_H = 46             # list mode
ROW_THUMB_W = 64


def thumb_height(card_w):
    return int(round(card_w * 9 / 16.0))


# ------------------------------------------------------------------
# Text helpers (also used by the info bar)
# ------------------------------------------------------------------

def frame_range_text(asset):
    first, last = asset.first_frame, asset.last_frame
    if first is not None and last is not None and last > first:
        return f"{first}-{last}"
    return ""


def asset_meta_text(asset):
    """Short line under the card name: 'MOV · 1-70'."""
    parts = [(asset.extension or '').lstrip('.').upper()]
    fr = frame_range_text(asset)
    if fr:
        parts.append(fr)
    return "  ·  ".join(p for p in parts if p)


def asset_info_text(asset):
    """Full one-line info for the bottom bar."""
    parts = []
    if asset.is_missing:
        parts.append("FILE NOT FOUND")
    if asset.resolution_width and asset.resolution_height:
        parts.append(f"{asset.resolution_width}x{asset.resolution_height}")
    fr = frame_range_text(asset)
    if fr:
        count = asset.last_frame - asset.first_frame + 1
        parts.append(f"{fr}  ({count} f)")
    if asset.fps:
        parts.append(f"{float(asset.fps):.3g} fps")
    try:
        parts.append(asset.get_size_str())
    except Exception:
        pass
    return "   ·   ".join(parts)


def asset_exists(asset):
    """Cheap existence check (first frame for sequences)."""
    if os.path.exists(asset.filepath):
        return True
    if asset.is_sequence and asset.sequence_path and asset.first_frame is not None:
        try:
            return os.path.exists(asset.sequence_path % asset.first_frame)
        except (TypeError, ValueError):
            return False
    return False


# ------------------------------------------------------------------
# Background workers -> UI thread via signals
# ------------------------------------------------------------------

class ThumbLoader(QtCore.QObject):
    """
    Decodes thumbnail files into QImages in worker threads.
    request(key, producer): producer() runs in the worker and returns a file
    path (lets hover previews run ffmpeg first). Result arrives in `loaded`.
    """
    loaded = Signal(str, QtGui.QImage)

    def __init__(self, parent=None, workers=2):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._pending = set()
        self._lock = threading.Lock()
        self.max_size = QSize(CARD_W_MAX * 2, thumb_height(CARD_W_MAX) * 2)

    def request(self, key, producer=None):
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
        self._pool.submit(self._work, key, producer or (lambda: key))

    def _work(self, key, producer):
        try:
            path = producer()
            img = QtGui.QImage()
            if path and os.path.exists(path):
                reader = QtGui.QImageReader(path)
                size = reader.size()
                if size.isValid() and (size.width() > self.max_size.width()
                                       or size.height() > self.max_size.height()):
                    reader.setScaledSize(size.scaled(self.max_size, Qt.KeepAspectRatio))
                img = reader.read()
            self.loaded.emit(key, img)
        except Exception:
            self.loaded.emit(key, QtGui.QImage())
        finally:
            with self._lock:
                self._pending.discard(key)

    def shutdown(self):
        self._pool.shutdown(wait=False)


class PreviewWorker(QtCore.QObject):
    """
    Builds hover-scrub frame strips (one ffmpeg run per clip) on its OWN
    thread, separate from thumbnail loading - so the clip under the mouse
    never waits behind the whole library. Most recent request first; only
    the last few requests are kept.
    """
    ready = Signal(str)      # asset file path

    MAX_QUEUE = 3

    def __init__(self, generator, buckets, parent=None):
        super().__init__(parent)
        self.gen = generator
        self.buckets = buckets
        self._queue = deque()
        self._cond = threading.Condition()
        self._busy = None
        threading.Thread(target=self._run, daemon=True).start()

    def request(self, asset_path, duration, size):
        with self._cond:
            if asset_path == self._busy:
                return
            self._queue = deque(j for j in self._queue if j[0] != asset_path)
            self._queue.append((asset_path, duration, size))
            while len(self._queue) > self.MAX_QUEUE:
                self._queue.popleft()          # drop the oldest
            self._cond.notify()

    def _run(self):
        while True:
            with self._cond:
                while not self._queue:
                    self._cond.wait()
                job = self._queue.pop()        # newest first
                self._busy = job[0]
            try:
                self.gen.generate_video_preview_strip(job[0], job[1], job[2], self.buckets)
            except Exception:
                pass
            finally:
                with self._cond:
                    self._busy = None
            self.ready.emit(job[0])


class MissingChecker(QtCore.QObject):
    """Checks in a thread which assets no longer exist on disk."""
    checked = Signal(int, object)   # generation, {asset_id: is_missing}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0

    def check(self, assets):
        self.generation += 1
        gen = self.generation
        items = list(assets)

        def run():
            result = {}
            for a in items:
                if gen != self.generation:
                    return          # a newer check started
                result[id(a)] = not asset_exists(a)
            self.checked.emit(gen, result)

        threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------
# Delegate
# ------------------------------------------------------------------

class AssetCardDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = 'grid'
        self.card_w = CARD_W_DEFAULT
        self.spin_phase = 0

    @property
    def thumb_h(self):
        return thumb_height(self.card_w)

    def sizeHint(self, option, index):
        if self.mode == 'grid':
            return QSize(self.card_w, self.thumb_h + TEXT_H)
        return QSize(0, ROW_H)

    def paint(self, painter, option, index):
        asset = index.data(ROLE_ASSET)
        if asset is None:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        pixmap = index.data(ROLE_PIXMAP)
        if self.mode == 'grid':
            thumb = self._paint_card(painter, option.rect, asset, pixmap, selected, hovered)
        else:
            thumb = self._paint_row(painter, option.rect, asset, pixmap, selected, hovered)
        if index.data(ROLE_LOADING):
            self._paint_spinner(painter, thumb)
        painter.restore()

    def _paint_spinner(self, p, box):
        """Small rotating arc in the thumbnail's top-right corner."""
        r = 9 if box.height() > 40 else 6
        c = QtCore.QPointF(box.right() - r - 7, box.top() + r + 7)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 150))
        p.drawEllipse(c, r + 4, r + 4)
        pen = QtGui.QPen(QtGui.QColor(theme.ACCENT), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        rect = QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.drawArc(rect, int(-self.spin_phase * 16), 100 * 16)
        p.restore()

    def _paint_card(self, p, rect, asset, pixmap, selected, hovered):
        th = self.thumb_h
        thumb = QtCore.QRectF(rect.x(), rect.y(), rect.width(), th)
        self._paint_thumb(p, thumb, asset, pixmap, radius=6)
        if selected or hovered:
            pen = QtGui.QPen(QtGui.QColor(theme.ACCENT if selected else theme.TEXT_FAINT),
                             2 if selected else 1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(thumb.adjusted(1, 1, -1, -1), 6, 6)
        name_rect = QtCore.QRect(rect.x() + 2, rect.y() + th + 6, rect.width() - 4, 18)
        meta_rect = QtCore.QRect(rect.x() + 2, name_rect.bottom() + 1, rect.width() - 4, 16)
        self._paint_text(p, name_rect, meta_rect, asset, selected)
        return thumb

    def _paint_row(self, p, rect, asset, pixmap, selected, hovered):
        if selected or hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(63, 183, 217, 36) if selected else QtGui.QColor(theme.BG_FIELD))
            p.drawRoundedRect(QtCore.QRectF(rect).adjusted(4, 1, -4, -1), 6, 6)
        thumb = QtCore.QRectF(rect.x() + 10, rect.y() + 5, ROW_THUMB_W, ROW_H - 10)
        self._paint_thumb(p, thumb, asset, pixmap, radius=4)
        x = int(thumb.right()) + 12
        meta = asset_info_text(asset)
        fm = QtGui.QFontMetrics(p.font())
        meta_w = min(fm.horizontalAdvance(meta) + 12, rect.width() // 2)
        name_rect = QtCore.QRect(x, rect.y(), rect.right() - x - meta_w - 10, rect.height())
        color = theme.DANGER if asset.is_missing else (theme.ACCENT if selected else theme.TEXT)
        self._draw_elided(p, name_rect, asset.get_display_name(), color,
                          Qt.AlignVCenter | Qt.AlignLeft, bold=True)
        meta_rect = QtCore.QRect(rect.right() - meta_w - 10, rect.y(), meta_w, rect.height())
        self._draw_elided(p, meta_rect, meta,
                          theme.DANGER if asset.is_missing else theme.TEXT_DIM,
                          Qt.AlignVCenter | Qt.AlignRight)
        return thumb

    def _paint_thumb(self, p, box, asset, pixmap, radius):
        path = QtGui.QPainterPath()
        path.addRoundedRect(box, radius, radius)
        p.fillPath(path, QtGui.QColor("#0c0e11"))
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.size()
            scaled.scale(int(box.width()), int(box.height()), Qt.KeepAspectRatio)
            target = QtCore.QRectF(box.x() + (box.width() - scaled.width()) / 2.0,
                                   box.y() + (box.height() - scaled.height()) / 2.0,
                                   scaled.width(), scaled.height())
            p.save()
            p.setClipPath(path)
            if asset.is_missing:
                p.setOpacity(0.35)
            p.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            p.restore()
        else:
            ext = (asset.extension or '').lstrip('.').upper() or "FILE"
            p.setPen(QtGui.QColor(theme.TEXT_FAINT))
            f = QtGui.QFont(p.font())
            f.setBold(True)
            p.save()
            p.setFont(f)
            p.drawText(box, Qt.AlignCenter, ext)
            p.restore()

    def _paint_text(self, p, name_rect, meta_rect, asset, selected):
        color = theme.DANGER if asset.is_missing else (theme.ACCENT if selected else theme.TEXT)
        self._draw_elided(p, name_rect, asset.get_display_name(), color, Qt.AlignLeft | Qt.AlignVCenter)
        meta = "file not found" if asset.is_missing else asset_meta_text(asset)
        f = p.font()
        small = QtGui.QFont(f)
        small.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(small)
        self._draw_elided(p, meta_rect, meta,
                          theme.DANGER if asset.is_missing else theme.TEXT_DIM,
                          Qt.AlignLeft | Qt.AlignVCenter)
        p.setFont(f)

    @staticmethod
    def _draw_elided(p, rect, text, color, align, bold=False):
        f = p.font()
        if bold:
            bf = QtGui.QFont(f)
            bf.setBold(True)
            p.setFont(bf)
        fm = QtGui.QFontMetrics(p.font())
        p.setPen(QtGui.QColor(color))
        p.drawText(rect, align, fm.elidedText(text or "", Qt.ElideMiddle, rect.width()))
        p.setFont(f)


# ------------------------------------------------------------------
# Grid widget
# ------------------------------------------------------------------

class AssetGridWidget(QtWidgets.QWidget):

    asset_selected = Signal(object)            # AssetItem or None
    asset_double_clicked = Signal(object)      # AssetItem
    create_nodes_requested = Signal(list)      # [AssetItem]

    def __init__(self, asset_library=None, parent=None):
        super().__init__(parent)
        self.asset_library = asset_library
        self._assets = []
        self._view_mode = 'grid'
        self._pixmap_cache = {}     # file path -> QPixmap
        self._waiting = {}          # file path -> [QListWidgetItem]

        self._hover_buckets = 20
        self._hover_last_key = None
        self._hover_item = None

        self.loader = ThumbLoader(self)
        self.loader.loaded.connect(self._on_image_loaded)
        self.missing_checker = MissingChecker(self)
        self.missing_checker.checked.connect(self._on_missing_checked)
        self.preview_worker = None
        if asset_library is not None:
            self.preview_worker = PreviewWorker(asset_library.thumbnail_gen, self._hover_buckets, self)
            self.preview_worker.ready.connect(self._on_preview_ready)
        self._hover_cache = {}            # frame path -> QPixmap (small, bounded)
        self._hover_pos = None
        self._loading_items = []          # QListWidgetItems aren't hashable in PySide6

        self._spin_timer = QtCore.QTimer(self)
        self._spin_timer.setInterval(60)
        self._spin_timer.timeout.connect(self._advance_spinner)

        self._setup_ui()

        # pick up thumbnails finished by the background generator
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.timeout.connect(self._request_missing_thumbnails)
        self._refresh_timer.start(1500)

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list_widget = DraggableAssetListWidget()
        self.list_widget.setObjectName("assetList")
        self.delegate = AssetCardDelegate(self.list_widget)
        self.list_widget.setItemDelegate(self.delegate)
        self.list_widget.setMouseTracking(True)
        self.list_widget.viewport().setMouseTracking(True)
        self.list_widget.viewport().setAttribute(Qt.WA_Hover, True)
        self.list_widget.viewport().installEventFilter(self)
        self.list_widget.installEventFilter(self)
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list_widget.verticalScrollBar().setSingleStep(24)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)
        self._apply_view_mode()

    # ---------------------------------------------------------- view
    def set_view_mode(self, mode):
        self._view_mode = mode
        self._apply_view_mode()

    def view_mode(self):
        return self._view_mode

    def set_card_width(self, width):
        self.delegate.card_w = max(CARD_W_MIN, min(CARD_W_MAX, int(width)))
        if self._view_mode == 'grid':
            self._apply_view_mode()

    def card_width(self):
        return self.delegate.card_w

    def _apply_view_mode(self):
        lw = self.list_widget
        self.delegate.mode = self._view_mode
        if self._view_mode == 'grid':
            lw.setViewMode(QtWidgets.QListView.IconMode)
            lw.setFlow(QtWidgets.QListView.LeftToRight)
            lw.setWrapping(True)
            lw.setResizeMode(QtWidgets.QListView.Adjust)
            lw.setMovement(QtWidgets.QListView.Static)
            lw.setUniformItemSizes(True)
            lw.setGridSize(QSize(self.delegate.card_w + CARD_GAP,
                                 self.delegate.thumb_h + TEXT_H + CARD_GAP))
            lw.setSpacing(0)
            lw.setViewportMargins(10, 10, 4, 0)
        else:
            lw.setViewMode(QtWidgets.QListView.ListMode)
            lw.setFlow(QtWidgets.QListView.TopToBottom)
            lw.setWrapping(False)
            lw.setGridSize(QSize())
            lw.setSpacing(0)
            lw.setUniformItemSizes(True)
            lw.setViewportMargins(4, 6, 4, 0)
        # setViewMode()/setMovement(Static) silently turn dragging OFF in Qt -
        # switch it back on after every layout change, or drag to the Node
        # Graph stops working.
        lw.setDragEnabled(True)
        lw.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        lw.setDefaultDropAction(Qt.CopyAction)
        lw.doItemsLayout()
        lw.viewport().update()

    # ---------------------------------------------------------- data
    def set_assets(self, assets):
        self._assets = assets
        self._waiting = {}
        self._hover_item = None
        self._loading_items = []
        self._spin_timer.stop()
        lw = self.list_widget
        lw.setUpdatesEnabled(False)
        lw.clear()
        for asset in assets:
            item = QtWidgets.QListWidgetItem()
            item.setData(ROLE_ASSET, asset)
            item.setToolTip(asset.get_display_path())
            lw.addItem(item)
            self._attach_thumbnail(item, asset.thumbnail_path)
        lw.setUpdatesEnabled(True)
        self.asset_selected.emit(None)
        self.missing_checker.check(assets)

    def _attach_thumbnail(self, item, path):
        """Use the cached pixmap, or ask the loader for it."""
        if not path:
            return
        pix = self._pixmap_cache.get(path)
        if pix is not None:
            item.setData(ROLE_PIXMAP, pix)
            return
        if not os.path.exists(path):
            return
        self._waiting.setdefault(path, []).append(item)
        self.loader.request(path)

    def _on_image_loaded(self, path, image):
        items = self._waiting.pop(path, [])
        if image.isNull():
            return
        pix = QtGui.QPixmap.fromImage(image)
        is_hover_frame = '_pv_' in os.path.basename(path)
        if is_hover_frame:
            # only if the mouse is still on that card
            items = [i for i in items if i is self._hover_item]
        else:
            self._pixmap_cache[path] = pix
        for item in items:
            try:
                item.setData(ROLE_PIXMAP, pix)
            except RuntimeError:
                pass   # item deleted by a refresh

    def _request_missing_thumbnails(self):
        """Thumbnails created by the background generator since the last look."""
        lw = self.list_widget
        gen = self.asset_library.thumbnail_gen if self.asset_library else None
        for i in range(lw.count()):
            item = lw.item(i)
            if item.data(ROLE_PIXMAP) is not None:
                continue
            asset = item.data(ROLE_ASSET)
            path = asset.thumbnail_path if asset else None
            if (not path or not os.path.exists(path)) and gen and asset:
                candidate = gen.get_thumbnail_path(asset.filepath)
                if os.path.exists(candidate):
                    asset.thumbnail_path = path = candidate
            if path and path not in self._waiting:
                self._attach_thumbnail(item, path)

    def _on_missing_checked(self, generation, result):
        if generation != self.missing_checker.generation:
            return
        changed = False
        for asset in self._assets:
            missing = result.get(id(asset))
            if missing is not None and missing != asset.is_missing:
                asset.is_missing = missing
                changed = True
        if changed:
            self.list_widget.viewport().update()
            self._on_selection_changed()

    def get_selected_assets(self):
        return [i.data(ROLE_ASSET) for i in self.list_widget.selectedItems() if i.data(ROLE_ASSET)]

    def missing_count(self):
        return sum(1 for a in self._assets if a.is_missing)

    # ---------------------------------------------------------- signals
    def _on_selection_changed(self):
        selected = self.get_selected_assets()
        self.asset_selected.emit(selected[-1] if selected else None)

    def _on_item_double_clicked(self, item):
        asset = item.data(ROLE_ASSET)
        if asset:
            self.asset_double_clicked.emit(asset)

    def _create_selected(self):
        selected = self.get_selected_assets()
        if len(selected) == 1:
            self.asset_double_clicked.emit(selected[0])
        elif selected:
            self.create_nodes_requested.emit(selected)

    # ---------------------------------------------------------- context menu
    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        asset = item.data(ROLE_ASSET)
        selected = self.get_selected_assets()
        if asset not in selected:
            selected = [asset]
        menu = QtWidgets.QMenu(self)
        if len(selected) > 1:
            menu.addAction(f"Create {len(selected)} Nodes",
                           lambda: self.create_nodes_requested.emit(selected))
        else:
            menu.addAction("Create Node", lambda: self.asset_double_clicked.emit(asset))
        menu.addSeparator()
        menu.addAction("Reveal in Explorer", lambda: self._reveal_in_explorer(asset))
        menu.addAction("Copy Path", lambda: QtWidgets.QApplication.clipboard().setText(asset.get_display_path()))
        menu.addSeparator()
        menu.addAction("Regenerate Thumbnail", lambda: self._regenerate_thumbnail(asset, item))
        menu.exec_(self.list_widget.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal_in_explorer(asset):
        import subprocess
        target = asset.filepath
        if not os.path.exists(target):
            target = os.path.dirname(target)
        if os.name == 'nt':
            if os.path.isfile(target):
                subprocess.Popen(['explorer', '/select,', os.path.normpath(target)])
            else:
                subprocess.Popen(['explorer', os.path.normpath(target)])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(target)])

    def _regenerate_thumbnail(self, asset, item):
        if not self.asset_library:
            return
        lib = self.asset_library

        def produce():
            return lib.get_thumbnail(asset, force=True)

        path = lib.thumbnail_gen.get_thumbnail_path(asset.filepath)
        self._pixmap_cache.pop(path, None)
        self._waiting.setdefault(path, []).append(item)
        self.loader.request(path, produce)

    # ---------------------------------------------------------- keys + hover scrub
    def eventFilter(self, obj, event):
        if obj is self.list_widget and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._create_selected()
                return True
        if obj is self.list_widget.viewport():
            if event.type() == QtCore.QEvent.MouseMove:
                self._hover_scrub(event.pos())
            elif event.type() == QtCore.QEvent.Leave:
                self._restore_hover_item()
        return super().eventFilter(obj, event)

    def _restore_hover_item(self):
        """Put the normal thumbnail back after scrubbing a video."""
        item, self._hover_item = self._hover_item, None
        self._hover_last_key = None
        self._hover_pos = None
        if item is None:
            return
        self._set_loading(item, False)
        try:
            asset = item.data(ROLE_ASSET)
            pix = self._pixmap_cache.get(asset.thumbnail_path) if asset else None
            if pix is not None:
                item.setData(ROLE_PIXMAP, pix)
        except RuntimeError:
            pass

    # spinner -------------------------------------------------------
    def _set_loading(self, item, on):
        try:
            item.setData(ROLE_LOADING, bool(on))
        except RuntimeError:
            return
        if on:
            if not any(i is item for i in self._loading_items):
                self._loading_items.append(item)
            if not self._spin_timer.isActive():
                self._spin_timer.start()
        else:
            self._loading_items = [i for i in self._loading_items if i is not item]
            if not self._loading_items:
                self._spin_timer.stop()

    def _advance_spinner(self):
        self.delegate.spin_phase = (self.delegate.spin_phase + 24) % 360
        vp = self.list_widget.viewport()
        for item in list(self._loading_items):
            try:
                vp.update(self.list_widget.visualItemRect(item))
            except RuntimeError:
                self._set_loading(item, False)

    # scrub ---------------------------------------------------------
    @staticmethod
    def _clip_duration(asset):
        duration = asset.duration
        if not duration and asset.fps and asset.frame_count:
            duration = float(asset.frame_count) / float(asset.fps)
        return duration

    def _hover_scrub(self, pos):
        if not self.asset_library:
            return
        item = self.list_widget.itemAt(pos)
        if item is not self._hover_item:
            self._restore_hover_item()
        if not item:
            return
        asset = item.data(ROLE_ASSET)
        if not asset or asset.is_missing or (asset.extension or '').lower() not in VIDEO_EXTENSIONS:
            return
        duration = self._clip_duration(asset)
        if not duration or duration <= 0:
            return
        rect = self.list_widget.visualItemRect(item)
        if rect.width() <= 0:
            return
        self._hover_item = item
        self._hover_pos = pos
        ratio = max(0.0, min(1.0, (pos.x() - rect.x()) / float(rect.width())))
        bucket = int(ratio * (self._hover_buckets - 1))
        key = (asset.id, bucket)
        if key == self._hover_last_key:
            return

        gen = self.asset_library.thumbnail_gen
        if not gen.has_video_preview_strip(asset.filepath, self._hover_buckets):
            # frames not ready: spinner + ask the preview worker (once)
            self._set_loading(item, True)
            card_w = self.delegate.card_w
            self.preview_worker.request(asset.filepath, duration,
                                        (card_w * 2, thumb_height(card_w) * 2))
            return

        self._hover_last_key = key
        pix = self._hover_frame(asset, bucket)
        if pix is not None:
            item.setData(ROLE_PIXMAP, pix)

    def _hover_frame(self, asset, bucket):
        """Small cached jpg -> QPixmap. Falls back to the nearest earlier frame."""
        gen = self.asset_library.thumbnail_gen
        for b in range(bucket, -1, -1):
            path = gen.get_video_preview_path(asset.filepath, b, self._hover_buckets)
            pix = self._hover_cache.get(path)
            if pix is None and os.path.exists(path):
                pix = QtGui.QPixmap(path)
                if pix.isNull():
                    continue
                if len(self._hover_cache) > 600:
                    self._hover_cache.clear()
                self._hover_cache[path] = pix
            if pix is not None:
                return pix
        return None

    def _on_preview_ready(self, asset_path):
        for item in list(self._loading_items):
            try:
                a = item.data(ROLE_ASSET)
            except RuntimeError:
                self._set_loading(item, False)
                continue
            if a is not None and a.filepath == asset_path:
                self._set_loading(item, False)
        # mouse still on that clip -> show the frame under the cursor now
        if self._hover_item is not None and self._hover_pos is not None:
            try:
                a = self._hover_item.data(ROLE_ASSET)
            except RuntimeError:
                return
            if a is not None and a.filepath == asset_path:
                self._hover_last_key = None
                self._hover_scrub(self._hover_pos)

    def closeEvent(self, event):
        self.loader.shutdown()
        super().closeEvent(event)
