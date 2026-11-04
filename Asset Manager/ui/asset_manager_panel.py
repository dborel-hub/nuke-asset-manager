"""
Asset Manager main panel

 ┌──────────────────────────────────────────────────────┐
 │ Asset Manager      [ search...........]   ▦ ☰  23  ⋯ │  top bar
 ├────────────┬─────────────────────────────────────────┤
 │ + Add      │                                         │
 │ LIBRARY    │              thumbnail grid             │
 │ FOLDERS    │                                         │
 │ TYPES      │                                         │
 ├────────────┴─────────────────────────────────────────┤
 │ name.mov   2048x1556 · 1-70 (70 f) · 24 fps · 36 MB  │  info bar
 └──────────────────────────────────────────────────────┘
"""

import os

try:
    from PySide2 import QtWidgets, QtCore
    from PySide2.QtCore import Qt, Signal
except ImportError:
    from PySide6 import QtWidgets, QtCore
    from PySide6.QtCore import Qt, Signal

from . import theme
from .widgets.sidebar_widget import SidebarWidget
from .widgets.asset_grid_widget import (AssetGridWidget, asset_info_text, asset_exists,
                                        CARD_W_MIN, CARD_W_MAX, CARD_W_DEFAULT)

from ..core import AssetLibrary
from ..config import ASSET_CATEGORIES, EXCLUDED_EXTENSIONS


class AssetManagerPanel(QtWidgets.QWidget):

    # Scanner callbacks run in a worker thread; these signals hand the
    # results to the UI thread (touching widgets from a thread froze Nuke).
    scan_progress = Signal(int, int, str)
    scan_completed = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("amRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(theme.stylesheet())
        self.setMinimumSize(900, 560)

        self.library = AssetLibrary()
        self.current_folder_id = None
        self.current_subdir = None
        self.current_category = None
        self._scan_queue = []
        self._scan_dialog = None

        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._reload_assets)

        self._setup_ui()
        self.scan_progress.connect(self._on_scan_progress)
        self.scan_completed.connect(self._on_scan_completed)

        self._restore_state()
        self._reload_all()
        self.library.generate_all_thumbnails()
        if not self.library.thumbnail_gen.has_ffmpeg():
            self._set_status("ffmpeg not found: video/EXR thumbnails off "
                             "(put ffmpeg.exe + ffprobe.exe in Asset Manager/bin)", 0)

    # ================================================================ UI
    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = SidebarWidget()
        self.sidebar.setMinimumWidth(180)
        self.grid = AssetGridWidget(self.library)

        root.addWidget(self._build_top_bar())

        body = self.body = QtWidgets.QSplitter(Qt.Horizontal)
        body.setHandleWidth(1)
        body.setStyleSheet(f"QSplitter::handle {{ background: {theme.BORDER}; }}")
        body.addWidget(self.sidebar)
        body.addWidget(self.grid)
        body.setStretchFactor(1, 1)
        body.setSizes([230, 1100])
        body.setCollapsible(0, False)
        root.addWidget(body, 1)

        root.addWidget(self._build_info_bar())

        # sidebar
        self.sidebar.add_folder_requested.connect(self._on_add_folder)
        self.sidebar.add_files_requested.connect(self._on_add_files)
        self.sidebar.scope_changed.connect(self._on_scope_changed)
        self.sidebar.scan_folder_requested.connect(self._queue_scan)
        self.sidebar.remove_folder_requested.connect(self._on_remove_folder)
        # grid
        self.grid.asset_selected.connect(self._on_asset_selected)
        self.grid.asset_double_clicked.connect(self._create_node)
        self.grid.create_nodes_requested.connect(self._create_nodes)

    def _build_top_bar(self):
        bar = QtWidgets.QWidget()
        bar.setObjectName("amTopBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(8)

        title = QtWidgets.QLabel("Asset Manager")
        title.setObjectName("amTitle")
        lay.addWidget(title)
        lay.addSpacing(18)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search assets...   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(420)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        lay.addWidget(self.search, 1)
        lay.addStretch()

        self.size_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.size_slider.setObjectName("amSizeSlider")
        self.size_slider.setRange(CARD_W_MIN, CARD_W_MAX)
        self.size_slider.setValue(CARD_W_DEFAULT)
        self.size_slider.setFixedWidth(100)
        self.size_slider.setToolTip("Thumbnail size")
        self.size_slider.valueChanged.connect(self.grid.set_card_width)
        lay.addWidget(self.size_slider)
        lay.addSpacing(6)

        self.grid_btn = self._tool_button("▦", "Grid view", checkable=True)
        self.list_btn = self._tool_button("☰", "List view", checkable=True)
        group = QtWidgets.QButtonGroup(bar)
        group.setExclusive(True)
        group.addButton(self.grid_btn)
        group.addButton(self.list_btn)
        self.grid_btn.setChecked(True)
        self.grid_btn.clicked.connect(lambda: self._set_view_mode('grid'))
        self.list_btn.clicked.connect(lambda: self._set_view_mode('list'))
        lay.addWidget(self.grid_btn)
        lay.addWidget(self.list_btn)

        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("amDim")
        self.count_label.setMinimumWidth(70)
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.count_label)

        self.more_btn = self._tool_button("⋯", "More")
        self.more_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.more_btn)
        menu.addAction("Refresh", self._reload_all)
        menu.addAction("Rescan All Folders", self._rescan_all)
        menu.addAction("Regenerate Thumbnails", self._regenerate_thumbnails)
        menu.addSeparator()
        menu.addAction("Remove Missing Files from Library", self._remove_missing)
        menu.addSeparator()
        menu.addAction("Check for Updates...", self._open_updates)
        self.more_btn.setMenu(menu)
        lay.addWidget(self.more_btn)
        return bar

    @staticmethod
    def _tool_button(text, tip, checkable=False):
        b = QtWidgets.QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        b.setFixedSize(30, 28)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _build_info_bar(self):
        bar = QtWidgets.QWidget()
        bar.setObjectName("amInfoBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setFixedHeight(32)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(16)
        self.info_name = QtWidgets.QLabel("")
        self.info_name.setObjectName("amInfoName")
        self.info_meta = QtWidgets.QLabel("")
        self.info_meta.setObjectName("amInfoMeta")
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("amDim")

        # background work indicator (thumbnail generation)
        self.work_label = QtWidgets.QLabel("")
        self.work_label.setObjectName("amDim")
        self.work_bar = QtWidgets.QProgressBar()
        self.work_bar.setObjectName("amWorkBar")
        self.work_bar.setTextVisible(False)
        self.work_bar.setFixedSize(120, 4)
        self.work_label.hide()
        self.work_bar.hide()

        lay.addWidget(self.info_name)
        lay.addWidget(self.info_meta)
        lay.addStretch()
        lay.addWidget(self.status)
        lay.addWidget(self.work_label)
        lay.addWidget(self.work_bar)

        self._work_timer = QtCore.QTimer(self)
        self._work_timer.setInterval(400)
        self._work_timer.timeout.connect(self._update_work_indicator)
        self._work_timer.start()
        return bar

    def _update_work_indicator(self):
        lib = self.library
        total, done = lib.thumb_total, lib.thumb_done
        if lib._thumb_running and total:
            self.work_label.setText(f"Thumbnails {done} / {total}")
            self.work_bar.setRange(0, total)
            self.work_bar.setValue(done)
            self.work_label.show()
            self.work_bar.show()
        elif self.work_bar.isVisible():
            self.work_label.hide()
            self.work_bar.hide()

    def _set_status(self, text, timeout_ms=4000):
        self.status.setText(text)
        if timeout_ms:
            QtCore.QTimer.singleShot(timeout_ms, lambda: self.status.text() == text and self.status.setText(""))

    def _set_view_mode(self, mode):
        self.grid.set_view_mode(mode)
        self.size_slider.setEnabled(mode == 'grid')
        (self.grid_btn if mode == 'grid' else self.list_btn).setChecked(True)

    # ================================================================ state
    # Saved in Asset Manager/data/config.json
    def _restore_state(self):
        cfg = self.library.config
        self.size_slider.setValue(int(cfg.get('card_width', CARD_W_DEFAULT)))
        self._set_view_mode(cfg.get('view_mode', 'grid') if cfg.get('view_mode') in ('grid', 'list') else 'grid')
        sizes = cfg.get('splitter_sizes')
        if isinstance(sizes, list) and len(sizes) == 2:
            self.body.setSizes([int(x) for x in sizes])
        self.sidebar._expanded = {(int(fid), sub) for fid, sub in cfg.get('expanded_folders', [])
                                  if fid is not None}

    def save_state(self):
        cfg = self.library.config
        cfg.config['card_width'] = self.grid.card_width()
        cfg.config['view_mode'] = self.grid.view_mode()
        cfg.config['splitter_sizes'] = self.body.sizes()
        cfg.config['expanded_folders'] = [[fid, sub] for fid, sub in self.sidebar._expanded
                                          if fid is not None]
        cfg.save_config()

    # ================================================================ updates
    def _open_updates(self):
        from .update_dialog import show_update_dialog
        show_update_dialog(self.window())

    def _remove_missing(self):
        missing = [a for a in self.library.search_assets() if not asset_exists(a)]
        if not missing:
            self._message("Remove Missing Files", "No missing files in the library.\n"
                          "(Files are marked red when they no longer exist on disk.)")
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Remove Missing Files",
            f"Remove {len(missing)} missing file(s) from the library?\n(Nothing is deleted from disk.)")
        if answer == QtWidgets.QMessageBox.Yes:
            for a in missing:
                if a.id:
                    self.library.delete_asset(a.id)
            self._reload_all()
            self._set_status(f"Removed {len(missing)} missing files")

    # ================================================================ data
    @staticmethod
    def _visible(assets):
        """Hide file types that don't belong in a VFX library (pdf, txt...)."""
        return [a for a in assets if (a.extension or '').lower() not in EXCLUDED_EXTENSIONS]

    def _reload_all(self):
        """Folders, counts and the current asset view."""
        folders = self.library.get_folders()
        everything = self._visible(self.library.search_assets())
        self.sidebar.set_folders(folders, everything)
        self.sidebar.set_total_count(len(everything))
        counts = {c: 0 for c in ASSET_CATEGORIES}
        for a in everything:
            counts[a.category] = counts.get(a.category, 0) + 1
        self.sidebar.set_type_counts(counts)

        self._reload_assets()

    def _reload_assets(self):
        assets = self._visible(self.library.search_assets(
            query=self.search.text().strip(),
            folder_id=self.current_folder_id,
            category=self.current_category,
        ))
        if self.current_subdir:
            prefix = os.path.normcase(os.path.normpath(self.current_subdir)) + os.sep
            assets = [a for a in assets
                      if os.path.normcase(os.path.normpath(a.filepath)).startswith(prefix)]
        assets.sort(key=lambda a: a.get_display_name().lower())
        self.grid.set_assets(assets)
        self.count_label.setText(f"{len(assets)} asset{'s' if len(assets) != 1 else ''}")

    # ================================================================ handlers
    def _on_scope_changed(self, folder_id, subdir, category):
        self.current_folder_id = folder_id
        self.current_subdir = subdir
        self.current_category = category
        self._reload_assets()

    def _on_asset_selected(self, asset):
        if asset is None:
            count = len(self.grid.get_selected_assets())
            self.info_name.setText(f"{count} selected" if count > 1 else "")
            self.info_meta.setText("")
            return
        selected = self.grid.get_selected_assets()
        if len(selected) > 1:
            self.info_name.setText(f"{len(selected)} selected")
            self.info_meta.setText("")
        else:
            self.info_name.setText(asset.get_display_name())
            self.info_meta.setText(asset_info_text(asset))

    def _create_node(self, asset):
        from ..nuke_integration import create_node_from_asset
        try:
            name = create_node_from_asset(asset)
            self._set_status(f"Created {name}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._message("Could not create node", str(e), QtWidgets.QMessageBox.Warning)

    def _create_nodes(self, assets):
        from ..nuke_integration import create_nodes_from_assets
        names = create_nodes_from_assets(assets)
        self._set_status(f"Created {len(names)} nodes")

    def _on_add_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Add Folder to Library")
        if not path:
            return
        try:
            folder_id = self.library.add_folder(path)
        except Exception as e:
            self._message("Could not add folder", str(e), QtWidgets.QMessageBox.Warning)
            return
        self._reload_all()
        self._queue_scan(folder_id)

    def _on_add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Files to Library")
        if not paths:
            return
        try:
            added = self.library.add_files(paths, self.current_folder_id)
            self._reload_all()
            self.library.generate_all_thumbnails()
            self._set_status(f"Added {len(added)} files")
        except Exception as e:
            self._message("Could not add files", str(e), QtWidgets.QMessageBox.Warning)

    def _on_remove_folder(self, folder_id):
        answer = QtWidgets.QMessageBox.question(
            self, "Remove Folder",
            "Remove this folder and its assets from the library?\n(Files on disk are not touched.)")
        if answer == QtWidgets.QMessageBox.Yes:
            self.library.remove_folder(folder_id, delete_assets=True)
            self._reload_all()

    def _rescan_all(self):
        for folder in self.library.get_folders():
            self._queue_scan(folder.id)

    def _regenerate_thumbnails(self):
        self.library.regenerate_all_thumbnails()   # progress shows in the info bar

    # ================================================================ scanning
    # One scan at a time (the scanner refuses a second one), queued.
    def _queue_scan(self, folder_id):
        if folder_id not in self._scan_queue:
            self._scan_queue.append(folder_id)
        if self._scan_dialog is None:
            self._start_next_scan()

    def _start_next_scan(self):
        while self._scan_queue:
            folder_id = self._scan_queue.pop(0)
            folder = self.library.db.get_folder(folder_id)
            if folder:
                break
        else:
            return

        dlg = QtWidgets.QProgressDialog("Looking for files...", "Cancel", 0, 0, self)
        dlg.setWindowTitle(f"Scanning {folder.name}")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setMinimumWidth(460)
        dlg.canceled.connect(self.library.scanner.cancel_scan)
        dlg.show()
        self._scan_dialog = dlg

        # Called from the scanner thread -> only emit signals here
        def on_progress(current, total, filepath):
            self.scan_progress.emit(current, total, filepath)

        def on_complete(assets):
            self.scan_completed.emit(assets, folder_id)

        self.library.scan_folder(folder_id, on_progress, on_complete)

    def _on_scan_progress(self, current, total, filepath):
        dlg = self._scan_dialog
        if dlg is None:
            return
        dlg.setMaximum(max(1, total))
        dlg.setValue(min(current, total))
        name = os.path.basename(filepath)
        dlg.setLabelText(f"{current} / {total}\n{name}")

    def _on_scan_completed(self, assets, folder_id):
        if self._scan_dialog is not None:
            self._scan_dialog.reset()
            self._scan_dialog.deleteLater()
            self._scan_dialog = None
        self._reload_all()
        self.library.generate_all_thumbnails()
        self._set_status(f"Scan complete: {len(self._visible(assets))} assets")
        if self._scan_queue:
            QtCore.QTimer.singleShot(0, self._start_next_scan)

    # ================================================================ misc
    def _message(self, title, text, icon=QtWidgets.QMessageBox.Information):
        box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok, self)
        box.exec_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.window():
            self.window().close()
            return
        if event.key() == Qt.Key_F and event.modifiers() & Qt.ControlModifier:
            self.search.setFocus()
            self.search.selectAll()
            return
        super().keyPressEvent(event)

    def get_library(self):
        return self.library

    def refresh(self):
        self._reload_all()

    def closeEvent(self, event):
        self.library.stop_background_processing()
        super().closeEvent(event)
