"""
Update dialog - checks GitHub and downloads only the files that changed.
Opened from  DMB Tools > Check for Updates...  or the "Update" button
in the Asset Manager window.
"""

import threading

try:
    from PySide2 import QtWidgets, QtCore
    from PySide2.QtCore import Qt, Signal
except ImportError:
    from PySide6 import QtWidgets, QtCore
    from PySide6.QtCore import Qt, Signal

from . import theme
from .. import updater
from ..config import APP_ROOT, APP_VERSION

_dialog = None


class _Worker(QtCore.QObject):
    """Runs network work in a thread, reports back through signals."""
    checked = Signal(object)          # plan dict
    progress = Signal(int, int, str)  # done, total, path
    finished = Signal(int)            # files written
    failed = Signal(str)

    def check(self):
        def run():
            try:
                self.checked.emit(updater.check(APP_ROOT))
            except Exception as e:
                self.failed.emit(str(e))
        threading.Thread(target=run, daemon=True).start()

    def apply(self, plan):
        def run():
            try:
                n = updater.apply(APP_ROOT, plan,
                                  progress=lambda d, t, p: self.progress.emit(d, t, p))
                self.finished.emit(n)
            except Exception as e:
                self.failed.emit(str(e))
        threading.Thread(target=run, daemon=True).start()


class UpdateDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asset Manager - Updates")
        self.setObjectName("amRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(theme.stylesheet())
        self.setMinimumSize(520, 380)
        self._plan = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QtWidgets.QLabel("Asset Manager updates")
        title.setObjectName("amTitle")
        lay.addWidget(title)

        self.versions = QtWidgets.QLabel(f"Installed: {APP_VERSION}")
        self.versions.setObjectName("amDim")
        lay.addWidget(self.versions)

        self.message = QtWidgets.QLabel("Checking GitHub...")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.message.setMinimumHeight(self.message.fontMetrics().lineSpacing() * 3)
        self.message.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
        lay.addWidget(self.message)

        self.files = QtWidgets.QListWidget()
        self.files.setObjectName("amNavList")
        self.files.setStyleSheet(f"QListWidget {{ background: {theme.BG_FIELD}; border-radius: 6px; }}")
        lay.addWidget(self.files, 1)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setObjectName("amWorkBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setRange(0, 0)           # busy until the check returns
        lay.addWidget(self.bar)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.update_btn = QtWidgets.QPushButton("Update now")
        self.update_btn.setObjectName("amAddButton")
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._start_update)
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.update_btn)
        buttons.addWidget(self.close_btn)
        lay.addLayout(buttons)

        self.worker = _Worker(self)
        self.worker.checked.connect(self._on_checked)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

    def start_check(self):
        self._plan = None
        self.files.clear()
        self.bar.setRange(0, 0)
        self.bar.show()
        self.update_btn.setEnabled(False)
        self.message.setText("Checking GitHub...")
        self.worker.check()

    # ------------------------------------------------------------ results
    def _on_checked(self, plan):
        self._plan = plan
        self.bar.hide()
        remote_v = plan.get("remote_version") or "?"
        self.versions.setText(f"Installed: {plan.get('local_version') or APP_VERSION}    "
                              f"·    GitHub: {remote_v}    ·    {plan['repo']}")
        changed, removed = plan["changed"], plan["removed"]
        if not plan["update_available"]:
            self.message.setText("You have the latest version.")
            return
        parts = []
        if changed:
            parts.append(f"{len(changed)} file(s) to download")
        if removed:
            parts.append(f"{len(removed)} old file(s) to remove")
        self.message.setText("Update available: " + ", ".join(parts) +
                             ".\nYour library (data) and ffmpeg (bin) are not touched.")
        for rel in changed:
            self.files.addItem("↓  " + rel)
        for rel in removed:
            self.files.addItem("✕  " + rel)
        self.update_btn.setEnabled(True)

    def _start_update(self):
        if not self._plan:
            return
        self.update_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        total = max(1, len(self._plan["changed"]))
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.show()
        self.message.setText("Downloading...")
        self.worker.apply(self._plan)

    def _on_progress(self, done, total, path):
        self.bar.setValue(done)
        self.message.setText(f"Downloading {done} / {total}\n{path}")

    def _on_finished(self, count):
        self.bar.hide()
        self.close_btn.setEnabled(True)
        self.files.clear()
        new_v = (self._plan or {}).get("remote_version") or ""
        self.message.setText(f"Updated{(' to ' + new_v) if new_v else ''} ({count} file(s)).\n"
                             "Restart Nuke to load the new version.")

    def _on_failed(self, error):
        self.bar.hide()
        self.close_btn.setEnabled(True)
        self.update_btn.setEnabled(bool(self._plan and self._plan.get("update_available")))
        self.message.setText(f"Could not update: {error}")


def show_update_dialog(parent=None):
    """Open (or raise) the update dialog and start a check."""
    global _dialog
    if parent is None:
        try:
            from ..nuke_integration.nuke_utils import get_nuke_main_window
            parent = get_nuke_main_window()
        except Exception:
            parent = None
    if _dialog is None:
        _dialog = UpdateDialog(parent)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    _dialog.start_check()
    return _dialog


# ------------------------------------------------------------------
# Quiet background check (used by the main window)
# ------------------------------------------------------------------

class UpdateNotifier(QtCore.QObject):
    """Emits `available(version)` when GitHub has a newer APP_VERSION."""
    available = Signal(str)

    def check(self):
        def run():
            try:
                repo, branch = updater.repo_settings(APP_ROOT)
                remote = updater.remote_version(repo, branch)
                if remote and updater.version_tuple(remote) > updater.version_tuple(APP_VERSION):
                    self.available.emit(remote)
            except Exception:
                pass   # offline etc. - stay quiet
        threading.Thread(target=run, daemon=True).start()
