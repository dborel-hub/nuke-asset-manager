"""
Asset Manager for Nuke - installer

Double-click this file (needs Python 3 from python.org - tkinter comes with it).

What it does:
  1. Checks what this machine has / is missing
  2. Copies the "Asset Manager" folder into  ~/.nuke/Asset Manager
     (on update, your library in data/ and ffmpeg in bin/ are kept)
  3. Gets ffmpeg / ffprobe / ffplay into Asset Manager/bin if needed
     (copies them from the system PATH, or downloads them on request)
  4. Adds the menu entry to ~/.nuke/menu.py - only if it isn't there yet,
     with a backup of menu.py first

Nothing else in your .nuke folder is touched.
"""

import os
import re
import sys
import glob
import queue
import shutil
import zipfile
import tempfile
import threading
import datetime
import urllib.request

APP_NAME = "Asset Manager"
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, APP_NAME)
NUKE_DIR = os.path.join(os.path.expanduser("~"), ".nuke")
DEST = os.path.join(NUKE_DIR, APP_NAME)
MENU_PY = os.path.join(NUKE_DIR, "menu.py")

KEEP_ON_UPDATE = ("data", "bin")          # never deleted / overwritten
SKIP_ON_COPY = ("data", "bin", "__pycache__")

IS_WINDOWS = sys.platform == "win32"
FF_TOOLS = ("ffmpeg", "ffprobe", "ffplay")
FF_EXE = ".exe" if IS_WINDOWS else ""
FF_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

BLOCK_START = "# ---- Asset Manager: START (added by install.pyw) ----"
BLOCK_END = "# ---- Asset Manager: END ----"
MENU_BLOCK = BLOCK_START + '''
# Loads ~/.nuke/Asset Manager only when you click the menu item.
def _asset_manager_open():
    import os, sys, importlib.util
    if 'asset_manager' not in sys.modules:
        root = os.path.join(os.path.expanduser('~'), '.nuke', 'Asset Manager')
        spec = importlib.util.spec_from_file_location(
            'asset_manager', os.path.join(root, '__init__.py'),
            submodule_search_locations=[root])
        module = importlib.util.module_from_spec(spec)
        sys.modules['asset_manager'] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            del sys.modules['asset_manager']
            raise
    from asset_manager.nuke_integration import show_asset_manager
    show_asset_manager()

try:
    import nuke
    nuke.menu('Nuke').addCommand('DMB/Asset Manager', _asset_manager_open)
    nuke.menu('Nodes').addCommand('DMB/Asset Manager', _asset_manager_open)
except Exception as _e:
    print('[Asset Manager] menu entry failed: %s' % _e)
''' + BLOCK_END + "\n"

# A block written by hand before this installer existed (same loader)
LEGACY_MENU_SIGNS = ("_dmb_open_asset_manager", "_asset_manager_open")
# The very first version (folder "nuke_asset_manager"), loaded differently
OLD_VERSION_SIGNS = ("from nuke_integration import add_to_nuke_menu",)

OK, WARN, MISSING, INFO = "ok", "warn", "missing", "info"


# ======================================================================
# Checks (pure functions - no GUI)
# ======================================================================

def read_text(path):
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def version_of(folder):
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', read_text(os.path.join(folder, "config.py")))
    return m.group(1) if m else None


def find_ff(tool):
    """Path of an ffmpeg tool: installed bin, package bin, or system PATH."""
    for folder in (os.path.join(DEST, "bin"), os.path.join(SOURCE, "bin")):
        p = os.path.join(folder, tool + FF_EXE)
        if os.path.exists(p):
            return p
    return shutil.which(tool)


def menu_state():
    """'block' (installer block), 'legacy' (hand-made loader), 'old' (first version), or None."""
    text = read_text(MENU_PY)
    if BLOCK_START in text:
        return "block"
    if any(s in text for s in LEGACY_MENU_SIGNS):
        return "legacy"
    if any(s in text for s in OLD_VERSION_SIGNS):
        return "old"
    return None


def run_checks():
    """List of (status, title, detail)."""
    rows = []
    v = sys.version_info
    rows.append((OK if v >= (3, 6) else MISSING, "Python",
                 f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 6) else " - needs 3.6+")))

    if os.path.exists(os.path.join(SOURCE, "__init__.py")):
        rows.append((OK, "Plugin files", f"version {version_of(SOURCE) or '?'} next to this installer"))
    else:
        rows.append((MISSING, "Plugin files",
                     f'"{APP_NAME}" folder not found next to install.pyw - extract the whole ZIP first'))

    rows.append((OK if os.path.isdir(NUKE_DIR) else INFO, ".nuke folder",
                 NUKE_DIR if os.path.isdir(NUKE_DIR) else f"{NUKE_DIR} (will be created)"))

    if IS_WINDOWS:
        nukes = sorted(glob.glob(r"C:\Program Files\Nuke*"))
        rows.append((OK if nukes else INFO, "Nuke",
                     ", ".join(os.path.basename(n) for n in nukes) if nukes
                     else "not found in C:\\Program Files (fine if installed elsewhere)"))

    if os.path.exists(os.path.join(DEST, "__init__.py")):
        installed, new = version_of(DEST), version_of(SOURCE)
        detail = f"version {installed or '?'} installed"
        if installed and new and installed != new:
            detail += f" -> will update to {new}"
        if os.path.isdir(os.path.join(DEST, "data")):
            detail += " (your library in data/ is kept)"
        rows.append((OK, "Current install", detail))
    else:
        rows.append((INFO, "Current install", "not installed yet"))

    missing_ff = [t for t in FF_TOOLS if not find_ff(t)]
    if not missing_ff:
        rows.append((OK, "ffmpeg", "ffmpeg, ffprobe, ffplay found"))
    else:
        rows.append((WARN, "ffmpeg", "missing: " + ", ".join(missing_ff) +
                     " - video/EXR thumbnails need it (use 'Download ffmpeg')"))

    state = menu_state()
    if state == "block":
        rows.append((OK, "menu.py", "Asset Manager entry already there"))
    elif state == "legacy":
        rows.append((OK, "menu.py", "Asset Manager loader already there (added by hand) - left as is"))
    elif state == "old":
        rows.append((WARN, "menu.py", "has the OLD Asset Manager loader - remove that block by hand; "
                     "the new entry will be added"))
    else:
        rows.append((INFO, "menu.py", "entry will be added" + ("" if os.path.exists(MENU_PY)
                                                             else " (menu.py will be created)")))

    old = os.path.join(NUKE_DIR, "nuke_asset_manager")
    if os.path.isdir(old):
        rows.append((WARN, "Old version", f"{old} still exists - can be deleted after testing"))
    return rows


# ======================================================================
# Actions (pure functions - log through a callback)
# ======================================================================

def install_files(log):
    if not os.path.exists(os.path.join(SOURCE, "__init__.py")):
        raise RuntimeError(f'"{APP_NAME}" folder not found next to install.pyw')
    os.makedirs(DEST, exist_ok=True)

    # remove old code (files deleted between versions must go), keep data + bin
    for name in os.listdir(DEST):
        if name in KEEP_ON_UPDATE:
            continue
        path = os.path.join(DEST, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    for name in os.listdir(SOURCE):
        if name in SKIP_ON_COPY:
            continue
        src, dst = os.path.join(SOURCE, name), os.path.join(DEST, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    log(f"Plugin copied to {DEST}")

    # ffmpeg: bundled with the package, or already on the system PATH
    bin_dir = os.path.join(DEST, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    for tool in FF_TOOLS:
        target = os.path.join(bin_dir, tool + FF_EXE)
        if os.path.exists(target):
            continue
        for candidate in (os.path.join(SOURCE, "bin", tool + FF_EXE), shutil.which(tool)):
            if candidate and os.path.exists(candidate):
                shutil.copy2(candidate, target)
                log(f"{tool} copied from {candidate}")
                break


def add_menu_entry(log):
    """Append the menu block once. Backs up menu.py before changing it."""
    state = menu_state()
    if state in ("block", "legacy"):
        log("menu.py already has the Asset Manager entry - not changed")
        return False
    os.makedirs(NUKE_DIR, exist_ok=True)
    text = read_text(MENU_PY) if os.path.exists(MENU_PY) else ""
    if os.path.exists(MENU_PY):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = MENU_PY + f".backup_{stamp}"
        shutil.copy2(MENU_PY, backup)
        log(f"Backup: {backup}")
    sep = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
    with open(MENU_PY, "a", encoding="utf-8") as fh:
        fh.write(sep + "\n" + MENU_BLOCK)
    log("Menu entry added to menu.py  (DMB > Asset Manager)")
    if state == "old":
        log("NOTE: menu.py still has the OLD loader block - delete it by hand")
    return True


def remove_menu_entry(log):
    text = read_text(MENU_PY)
    if BLOCK_START not in text:
        log("No installer block in menu.py (a hand-made one, if any, is left alone)")
        return False
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(MENU_PY, MENU_PY + f".backup_{stamp}")
    pattern = re.compile(r"\n*" + re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
    with open(MENU_PY, "w", encoding="utf-8") as fh:
        fh.write(pattern.sub("\n", text).rstrip("\n") + "\n")
    log("Menu entry removed from menu.py (backup saved)")
    return True


def uninstall(log, keep_library=True):
    remove_menu_entry(log)
    if os.path.isdir(DEST):
        for name in os.listdir(DEST):
            if keep_library and name == "data":
                continue
            path = os.path.join(DEST, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        if not os.listdir(DEST):
            os.rmdir(DEST)
        log("Plugin removed" + (" (library kept in data/)" if keep_library and os.path.isdir(DEST) else ""))


def download_ffmpeg(log, progress):
    """Windows: download the gyan.dev 'essentials' build, extract the 3 exes into bin/."""
    if not IS_WINDOWS:
        raise RuntimeError("Automatic download is Windows only - install ffmpeg with your package manager")
    bin_dir = os.path.join(DEST, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    log(f"Downloading {FF_URL} ...")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    try:
        req = urllib.request.Request(FF_URL, headers={"User-Agent": "AssetManager-Installer"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp.name, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress(done, total)
        log("Extracting...")
        with zipfile.ZipFile(tmp.name) as z:
            got = []
            for member in z.namelist():
                base = os.path.basename(member).lower()
                if "/bin/" in member.replace("\\", "/") and base in [t + ".exe" for t in FF_TOOLS]:
                    with z.open(member) as src, open(os.path.join(bin_dir, base), "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    got.append(base)
        if not got:
            raise RuntimeError("ffmpeg executables not found inside the download")
        log("ffmpeg ready: " + ", ".join(sorted(got)))
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


# ======================================================================
# GUI (tkinter - ships with Python, no pip install needed)
# ======================================================================

def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox

    BG, PANEL, FG, DIM, ACCENT = "#14161a", "#1b1f25", "#d7dce2", "#8a93a0", "#3fb7d9"
    COLORS = {OK: "#5fd38d", WARN: "#e5c07b", MISSING: "#e06c75", INFO: DIM}
    ICONS = {OK: "\u2713", WARN: "!", MISSING: "\u2717", INFO: "\u2022"}

    root = tk.Tk()
    root.title("Asset Manager - Installer")
    root.configure(bg=BG)
    root.geometry("760x600")
    root.minsize(640, 480)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL,
                    lightcolor=ACCENT, darkcolor=ACCENT)

    tk.Label(root, text="Asset Manager for Nuke", bg=BG, fg=FG,
             font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 0))
    tk.Label(root, text=f"Installs into {DEST}", bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(anchor="w", padx=18)

    checks_frame = tk.Frame(root, bg=PANEL)
    checks_frame.pack(fill="x", padx=18, pady=12)

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=18)

    def make_button(text, cmd, primary=False):
        b = tk.Button(btns, text=text, command=cmd, relief="flat", cursor="hand2",
                      bg=ACCENT if primary else PANEL, fg="#0b1a1f" if primary else FG,
                      activebackground="#56c4e3" if primary else "#262b33",
                      activeforeground="#0b1a1f" if primary else FG,
                      font=("Segoe UI", 10, "bold" if primary else "normal"), padx=14, pady=6, bd=0,
                      highlightthickness=0)
        return b

    install_btn = make_button("Install / Update", lambda: start(do_install), primary=True)
    ff_btn = make_button("Download ffmpeg", lambda: start(do_download))
    uninstall_btn = make_button("Uninstall", lambda: confirm_uninstall())
    close_btn = make_button("Close", root.destroy)
    install_btn.pack(side="left")
    ff_btn.pack(side="left", padx=8)
    close_btn.pack(side="right")
    uninstall_btn.pack(side="right", padx=8)

    bar = ttk.Progressbar(root, mode="determinate", style="TProgressbar")
    bar.pack(fill="x", padx=18, pady=(12, 0))

    log_box = tk.Text(root, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                      font=("Consolas", 9), height=10, wrap="word", bd=0, padx=8, pady=6)
    log_box.pack(fill="both", expand=True, padx=18, pady=12)

    events = queue.Queue()
    busy = {"on": False}

    def log(msg):
        events.put(("log", msg))

    def progress(done, total):
        events.put(("progress", (done, total)))

    def refresh_checks():
        for w in checks_frame.winfo_children():
            w.destroy()
        rows = run_checks()
        for status, title, detail in rows:
            row = tk.Frame(checks_frame, bg=PANEL)
            row.pack(fill="x", padx=10, pady=3)
            tk.Label(row, text=ICONS[status], width=2, bg=PANEL, fg=COLORS[status],
                     font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Label(row, text=title, width=15, anchor="w", bg=PANEL, fg=FG,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(row, text=detail, anchor="w", justify="left", bg=PANEL, fg=DIM,
                     font=("Segoe UI", 9), wraplength=480).pack(side="left", fill="x", expand=True)
        ff_missing = any(t[1] == "ffmpeg" and t[0] != OK for t in rows)
        plugin_ok = any(t[1] == "Plugin files" and t[0] == OK for t in rows)
        install_btn.configure(state="normal" if plugin_ok and not busy["on"] else "disabled")
        ff_btn.configure(state="normal" if ff_missing and IS_WINDOWS and not busy["on"] else "disabled")

    def pump():
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "log":
                    log_box.insert("end", payload + "\n")
                    log_box.see("end")
                elif kind == "progress":
                    done, total = payload
                    if total:
                        bar.configure(mode="determinate", maximum=total, value=done)
                    else:
                        bar.configure(mode="indeterminate")
                        bar.step(5)
                elif kind == "done":
                    busy["on"] = False
                    bar.configure(mode="determinate", value=0)
                    refresh_checks()
                    if payload:
                        messagebox.showinfo("Asset Manager", payload)
        except queue.Empty:
            pass
        root.after(80, pump)

    def start(job):
        if busy["on"]:
            return
        busy["on"] = True
        install_btn.configure(state="disabled")
        ff_btn.configure(state="disabled")

        def runner():
            message = None
            try:
                message = job()
            except Exception as e:
                log(f"ERROR: {e}")
            events.put(("done", message))

        threading.Thread(target=runner, daemon=True).start()

    def do_install():
        log("---- Install / Update ----")
        install_files(log)
        add_menu_entry(log)
        missing = [t for t in FF_TOOLS if not find_ff(t)]
        if missing:
            log("ffmpeg still missing: " + ", ".join(missing) + " - click 'Download ffmpeg' "
                "(or copy the .exe files into Asset Manager\\bin)")
        log("Done. Restart Nuke, then open:  DMB > Asset Manager")
        return "Installed.\n\nRestart Nuke and open  DMB > Asset Manager."

    def do_download():
        log("---- Download ffmpeg ----")
        download_ffmpeg(log, progress)
        return None

    def confirm_uninstall():
        if busy["on"]:
            return
        answer = messagebox.askyesnocancel(
            "Uninstall Asset Manager",
            "Remove the plugin and its menu entry?\n\n"
            "Yes = keep your library (data folder)\nNo = remove everything\nCancel = do nothing")
        if answer is None:
            return
        start(lambda: (log("---- Uninstall ----"), uninstall(log, keep_library=answer),
                       "Uninstalled. Restart Nuke.")[-1])

    refresh_checks()
    log("Checked this machine - see the list above.")
    if not os.path.exists(os.path.join(SOURCE, "__init__.py")):
        log(f'"{APP_NAME}" folder missing next to install.pyw: extract the whole ZIP first.')
    pump()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
