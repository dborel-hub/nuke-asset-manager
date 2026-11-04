"""
Sidebar - "+ Add" button and LIBRARY / FOLDERS / TYPES navigation.

FOLDERS is a tree: each library folder is a root you can open/close, with
its subfolders underneath (only subfolders that actually contain assets).
Clicking a subfolder shows everything inside it, including deeper levels.

Scope (All / folder / subfolder) and type are combined:
e.g. "Blood Splashes / Pack 2" + "Footage".
Click a selected type again to clear the type filter.
"""

import os
import subprocess

try:
    from PySide2 import QtWidgets, QtCore
    from PySide2.QtCore import Qt, Signal
except ImportError:
    from PySide6 import QtWidgets, QtCore
    from PySide6.QtCore import Qt, Signal


ROLE_DATA = Qt.UserRole
ROW_HEIGHT = 28
ARROW_OPEN = "▾"    # ▾
ARROW_CLOSED = "▸"  # ▸
INDENT = " "         # em space per level (native indentation is off:
                          # Qt painted a stray highlight in the indent area)


def norm(path):
    return os.path.normcase(os.path.normpath(path))


# ------------------------------------------------------------------
# Small building blocks
# ------------------------------------------------------------------

class _NavList(QtWidgets.QListWidget):
    """Flat list that grows to fit its items (no inner scrollbar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("amNavList")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.setTextElideMode(Qt.ElideMiddle)

    def add(self, text, data, count=None):
        item = QtWidgets.QListWidgetItem(text if count is None else f"{text}    {count}")
        item.setData(ROLE_DATA, data)
        item.setSizeHint(QtCore.QSize(0, ROW_HEIGHT))
        self.addItem(item)
        return item

    def fit(self):
        self.setFixedHeight(max(1, self.count()) * (ROW_HEIGHT + 2) + 4)


class _FolderTree(QtWidgets.QTreeWidget):
    """
    Folder tree with a text arrow (▸/▾) instead of the native branch
    decoration (which is nearly invisible on a dark background).
    Click the arrow to open/close; click the name to select.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("amNavTree")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setExpandsOnDoubleClick(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setUniformRowHeights(True)
        self.itemExpanded.connect(self._on_toggled)
        self.itemCollapsed.connect(self._on_toggled)

    def make_item(self, parent, name, count, data, has_children):
        item = QtWidgets.QTreeWidgetItem(parent)
        item.setData(0, ROLE_DATA, data)
        item.setData(0, ROLE_DATA + 1, (name, count, has_children))
        item.setSizeHint(0, QtCore.QSize(0, ROW_HEIGHT))
        self._refresh_text(item)
        return item

    @staticmethod
    def _depth(item):
        depth, parent = 0, item.parent()
        while parent is not None:
            depth, parent = depth + 1, parent.parent()
        return depth

    def _refresh_text(self, item):
        name, count, has_children = item.data(0, ROLE_DATA + 1)
        arrow = (ARROW_OPEN if item.isExpanded() else ARROW_CLOSED) if has_children else " "
        item.setText(0, f"{INDENT * self._depth(item)}{arrow}  {name}    {count}")

    def _on_toggled(self, item):
        self._refresh_text(item)
        self.fit()

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            item = self.itemFromIndex(index)
            rect = self.visualRect(index)
            fm = self.fontMetrics()
            indent = INDENT * self._depth(item)
            indent_px = fm.horizontalAdvance(indent) if hasattr(fm, 'horizontalAdvance') else fm.width(indent)
            arrow_x = rect.x() + 12 + indent_px          # item margin + padding
            on_arrow = arrow_x - 6 <= event.pos().x() <= arrow_x + 16
            if on_arrow and item.childCount():
                item.setExpanded(not item.isExpanded())
                return
        super().mousePressEvent(event)

    def fit(self):
        rows = 0
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            parent = item.parent()
            visible = True
            while parent is not None:
                if not parent.isExpanded():
                    visible = False
                    break
                parent = parent.parent()
            if visible:
                rows += 1
            it += 1
        self.setFixedHeight(max(1, rows) * (ROW_HEIGHT + 2) + 4)


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------

class SidebarWidget(QtWidgets.QWidget):

    add_folder_requested = Signal()
    add_files_requested = Signal()
    scope_changed = Signal(object, object, object)   # folder_id, subdir, category
    scan_folder_requested = Signal(int)
    remove_folder_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("amSidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._folder_id = None
        self._subdir = None
        self._category = None
        self._folders = {}
        self._expanded = set()   # (folder_id, subdir) kept open across refreshes
        self._setup_ui()

    # ---------------------------------------------------------- UI
    def _setup_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        add_row = QtWidgets.QHBoxLayout()
        add_row.setContentsMargins(10, 10, 10, 4)
        self.add_button = QtWidgets.QPushButton("+  Add")
        self.add_button.setObjectName("amAddButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        menu = QtWidgets.QMenu(self.add_button)
        menu.addAction("Add Folder...", self.add_folder_requested.emit)
        menu.addAction("Add Files...", self.add_files_requested.emit)
        self.add_button.setMenu(menu)
        add_row.addWidget(self.add_button)
        outer.addLayout(add_row)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        content = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(0)

        lay.addWidget(self._section("LIBRARY"))
        self.library_list = _NavList()
        self._all_item = self.library_list.add("All Assets", None)
        self.library_list.fit()
        lay.addWidget(self.library_list)

        lay.addWidget(self._section("FOLDERS"))
        self.folder_tree = _FolderTree()
        self.folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._folder_menu)
        self.folder_tree.itemExpanded.connect(lambda i: self._expanded.add(self._key(i)))
        self.folder_tree.itemCollapsed.connect(lambda i: self._expanded.discard(self._key(i)))
        lay.addWidget(self.folder_tree)

        lay.addWidget(self._section("TYPES"))
        self.type_list = _NavList()
        lay.addWidget(self.type_list)

        lay.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.library_list.itemClicked.connect(self._on_library_clicked)
        self.folder_tree.itemClicked.connect(self._on_folder_clicked)
        self.type_list.itemClicked.connect(self._on_type_clicked)
        self.library_list.setCurrentItem(self._all_item)

    @staticmethod
    def _section(text):
        label = QtWidgets.QLabel(text)
        label.setObjectName("amSection")
        return label

    @staticmethod
    def _key(item):
        data = item.data(0, ROLE_DATA) or {}
        return (data.get('folder_id'), data.get('subdir'))

    # ---------------------------------------------------------- data
    def set_total_count(self, count):
        self._all_item.setText(f"All Assets    {count}")

    def set_folders(self, folders, assets):
        """
        folders: FolderModel list. assets: all visible AssetItems
        (used to build the subfolder tree and the counts).
        """
        self._folders = {f.id: f for f in folders}
        by_folder = {}
        for a in assets:
            by_folder.setdefault(a.folder_id, []).append(a)

        tree = self.folder_tree
        tree.setUpdatesEnabled(False)
        tree.clear()
        selected_item = None

        for folder in sorted(folders, key=lambda f: f.name.lower()):
            root_path = norm(folder.path)
            folder_assets = by_folder.get(folder.id, [])

            # nested dict: {name: {'count': n, 'children': {...}}}
            nodes = {}
            for a in folder_assets:
                rel = os.path.relpath(norm(os.path.dirname(a.filepath)), root_path)
                if rel == '.' or rel.startswith('..'):
                    continue
                level = nodes
                for part in rel.split(os.sep):
                    node = level.setdefault(part, {'count': 0, 'children': {}})
                    node['count'] += 1
                    level = node['children']

            root_data = {'folder_id': folder.id, 'subdir': None}
            root_item = tree.make_item(tree, folder.name, len(folder_assets), root_data, bool(nodes))
            root_item.setToolTip(0, folder.path)
            if self._folder_id == folder.id and self._subdir is None:
                selected_item = root_item
            found = self._add_children(root_item, folder.id, folder.path, nodes)
            selected_item = selected_item or found

        # restore open/closed state (default: closed)
        it = QtWidgets.QTreeWidgetItemIterator(tree)
        while it.value():
            item = it.value()
            if self._key(item) in self._expanded:
                item.setExpanded(True)
            it += 1

        tree.setUpdatesEnabled(True)
        if selected_item is not None:
            tree.setCurrentItem(selected_item)
        elif self._folder_id is not None:
            self._select_all()   # selected folder no longer exists
        tree.fit()

    def _add_children(self, parent_item, folder_id, parent_path, nodes):
        selected = None
        for name in sorted(nodes, key=str.lower):
            node = nodes[name]
            path = os.path.join(parent_path, name)
            data = {'folder_id': folder_id, 'subdir': path}
            item = self.folder_tree.make_item(parent_item, name, node['count'], data, bool(node['children']))
            item.setToolTip(0, path)
            if self._folder_id == folder_id and self._subdir and norm(self._subdir) == norm(path):
                selected = item
            selected = self._add_children(item, folder_id, path, node['children']) or selected
        return selected

    def set_type_counts(self, counts):
        """counts: {category: n}. Only categories with assets are shown."""
        self.type_list.clear()
        for category, n in counts.items():
            if n <= 0:
                continue
            item = self.type_list.add(category, category, n)
            if self._category == category:
                self.type_list.setCurrentItem(item)
        self.type_list.fit()

    # ---------------------------------------------------------- clicks
    def _select_all(self):
        self._folder_id = None
        self._subdir = None
        self.folder_tree.clearSelection()
        self.library_list.setCurrentItem(self._all_item)

    def _on_library_clicked(self, item):
        self._select_all()
        self._emit()

    def _on_folder_clicked(self, item, _column=0):
        data = item.data(0, ROLE_DATA) or {}
        self._folder_id = data.get('folder_id')
        self._subdir = data.get('subdir')
        self.library_list.clearSelection()
        self._emit()

    def _on_type_clicked(self, item):
        category = item.data(ROLE_DATA)
        if self._category == category:      # click again = clear
            self._category = None
            self.type_list.clearSelection()
            self.type_list.setCurrentRow(-1)
        else:
            self._category = category
        self._emit()

    def _emit(self):
        self.scope_changed.emit(self._folder_id, self._subdir, self._category)

    # ---------------------------------------------------------- folder menu
    def _folder_menu(self, pos):
        item = self.folder_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, ROLE_DATA) or {}
        folder_id = data.get('folder_id')
        folder = self._folders.get(folder_id)
        path = data.get('subdir') or (folder.path if folder else None)

        menu = QtWidgets.QMenu(self)
        if item.childCount():
            menu.addAction("Expand All", lambda: self._set_expanded_recursive(item, True))
            menu.addAction("Collapse All", lambda: self._set_expanded_recursive(item, False))
            menu.addSeparator()
        if path:
            menu.addAction("Reveal in Explorer", lambda: self._reveal(path))
        menu.addAction("Rescan", lambda: self.scan_folder_requested.emit(folder_id))
        if data.get('subdir') is None:
            menu.addSeparator()
            menu.addAction("Remove from Library", lambda: self.remove_folder_requested.emit(folder_id))
        menu.exec_(self.folder_tree.viewport().mapToGlobal(pos))

    def _set_expanded_recursive(self, item, expanded):
        item.setExpanded(expanded)
        for i in range(item.childCount()):
            self._set_expanded_recursive(item.child(i), expanded)

    @staticmethod
    def _reveal(path):
        if os.name == 'nt':
            subprocess.Popen(['explorer', os.path.normpath(path)])
        else:
            subprocess.Popen(['xdg-open', path])
