"""
Asset Manager for Nuke - installer / updater
by Daniel Marinho Borel  (danielmborel@gmail.com)

Double-click this file (needs Python 3 from python.org - tkinter comes with it).

  Install / Update     copies the "Asset Manager" folder next to this file
                       into ~/.nuke/Asset Manager
  Update from GitHub   downloads ONLY the files that changed on GitHub
                       (inside Nuke, the plugin also checks GitHub by itself
                       the first time its window opens each session)
  Download ffmpeg      gets ffmpeg / ffprobe / ffplay into Asset Manager/bin
  Uninstall            removes the plugin and its menu entry

Always kept: your library (data/) and ffmpeg (bin/).
menu.py: the "DMB Tools" entry is added once (backup first); an older
Asset Manager block is replaced. Nothing else in .nuke is touched.
(The block is defined in "Asset Manager/menu_block.py".)
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
import importlib.util
import urllib.request

APP_NAME = "Asset Manager"
AUTHOR = "Daniel Marinho Borel"
CONTACT = "danielmborel@gmail.com"

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

# ---------------------------------------------------------------- menu.py block
# The block itself lives in "Asset Manager/menu_block.py" (single source of
# truth, also used by the plugin to fix an outdated block by itself).

OK, WARN, MISSING, INFO = "ok", "warn", "missing", "info"


# ======================================================================
# Helpers
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
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', read_text(os.path.join(folder, "config.py")), re.M)
    return m.group(1) if m else None


def load_updater():
    """updater.py from the package next to this file, else the installed one."""
    for root in (SOURCE, DEST):
        path = os.path.join(root, "updater.py")
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("am_updater", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError("updater.py not found - extract the whole ZIP")


def find_ff(tool):
    for folder in (os.path.join(DEST, "bin"), os.path.join(SOURCE, "bin")):
        p = os.path.join(folder, tool + FF_EXE)
        if os.path.exists(p):
            return p
    return shutil.which(tool)


def load_menu_block():
    """menu_block.py from the package next to this file, else the installed one."""
    for root in (SOURCE, DEST):
        path = os.path.join(root, "menu_block.py")
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("am_menu_block", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def menu_state():
    """'current' / 'outdated' / 'legacy' / 'manual' / 'old' / None  (see menu_block.state)"""
    mb = load_menu_block()
    return mb.state(read_text(MENU_PY)) if mb else None


# ======================================================================
# Checks
# ======================================================================

def run_checks():
    """List of (status, title, detail)."""
    rows = []
    v = sys.version_info
    rows.append((OK if v >= (3, 6) else MISSING, "Python",
                 f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 6) else " - needs 3.6+")))

    if os.path.exists(os.path.join(SOURCE, "__init__.py")):
        rows.append((OK, "Package", f"version {version_of(SOURCE) or '?'} next to this installer"))
    else:
        rows.append((WARN, "Package", f'no "{APP_NAME}" folder here - use "Update from GitHub" '
                                      'or extract the whole ZIP'))

    rows.append((OK if os.path.isdir(NUKE_DIR) else INFO, ".nuke folder",
                 NUKE_DIR if os.path.isdir(NUKE_DIR) else f"{NUKE_DIR} (will be created)"))

    if IS_WINDOWS:
        nukes = sorted(glob.glob(r"C:\Program Files\Nuke*"))
        rows.append((OK if nukes else INFO, "Nuke",
                     ", ".join(os.path.basename(n) for n in nukes) if nukes
                     else "not found in C:\\Program Files (fine if installed elsewhere)"))

    if os.path.exists(os.path.join(DEST, "__init__.py")):
        detail = f"version {version_of(DEST) or '?'} installed"
        if os.path.isdir(os.path.join(DEST, "data")):
            detail += " (library in data/ is kept on update)"
        rows.append((OK, "Installed", detail))
    else:
        rows.append((INFO, "Installed", "not installed yet"))

    missing_ff = [t for t in FF_TOOLS if not find_ff(t)]
    if not missing_ff:
        rows.append((OK, "ffmpeg", "ffmpeg, ffprobe, ffplay found"))
    else:
        rows.append((WARN, "ffmpeg", "missing: " + ", ".join(missing_ff) +
                     " - video/EXR thumbnails need it (use 'Download ffmpeg')"))

    state = menu_state()
    detail = {
        "current": (OK, "DMB Tools > Asset Manager entry is there"),
        "outdated": (INFO, "older Asset Manager entry - will be updated"),
        "legacy": (INFO, "hand-made Asset Manager block - will be replaced by the DMB Tools entry"),
        "manual": (WARN, "hand-made Asset Manager loader found - left as is (edit menu.py by hand)"),
        "foreign": (WARN, "another plugin uses the 'Asset Manager' markers - left as is "
                          "(give that plugin its own START/END markers)"),
        "old": (WARN, "OLD Asset Manager loader found - remove it by hand; new entry will be added"),
        None: (INFO, "entry will be added" + ("" if os.path.exists(MENU_PY) else " (menu.py will be created)")),
    }[state]
    rows.append((detail[0], "menu.py", detail[1]))

    old = os.path.join(NUKE_DIR, "nuke_asset_manager")
    if os.path.isdir(old):
        rows.append((WARN, "Old version", f"{old} still exists - can be deleted"))
    return rows


# ======================================================================
# Actions
# ======================================================================

def install_files(log):
    if not os.path.exists(os.path.join(SOURCE, "__init__.py")):
        raise RuntimeError(f'"{APP_NAME}" folder not found next to install.pyw')
    os.makedirs(DEST, exist_ok=True)
    for name in os.listdir(DEST):                  # old code out, keep data + bin
        if name in KEEP_ON_UPDATE:
            continue
        path = os.path.join(DEST, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(SOURCE):
        if name in SKIP_ON_COPY:
            continue
        src, dst = os.path.join(SOURCE, name), os.path.join(DEST, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    log(f"Plugin {version_of(DEST) or ''} copied to {DEST}")
    ensure_ffmpeg_from_system(log)


def ensure_ffmpeg_from_system(log):
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
    """Make menu.py contain exactly one, current Asset Manager block."""
    mb = load_menu_block()
    if mb is None:
        raise RuntimeError("menu_block.py not found - extract the whole ZIP")
    return bool(mb.ensure(MENU_PY, log, allow_add=True))


def remove_menu_entry(log):
    mb = load_menu_block()
    if mb is None:
        log("menu_block.py not found - menu.py not changed")
        return False
    return mb.remove(MENU_PY, log)


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
        log("Plugin removed" + (" (library kept in data/)" if os.path.isdir(DEST) else ""))


def update_from_github(log, progress):
    """Download only the files that differ from GitHub (also works as a fresh install)."""
    upd = load_updater()
    repo, branch = upd.repo_settings(SOURCE, DEST)
    log(f"Checking github.com/{repo} ({branch}) ...")
    plan = upd.check(DEST, repo, branch)
    log(f"Installed: {plan['local_version'] or 'none'}   GitHub: {plan['remote_version'] or '?'}")
    if not plan["update_available"]:
        log("Already up to date - nothing to download")
    else:
        log(f"{len(plan['changed'])} file(s) to download, {len(plan['removed'])} to remove")
        for rel in plan["changed"]:
            log("  + " + rel)
        for rel in plan["removed"]:
            log("  - " + rel)
        upd.apply(DEST, plan, progress=lambda d, t, p: progress(d, t))
        log("Files updated")
    ensure_ffmpeg_from_system(log)
    add_menu_entry(log)
    return plan


def remote_version():
    upd = load_updater()
    repo, branch = upd.repo_settings(SOURCE, DEST)
    return upd.remote_version(repo, branch), repo


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
        got = []
        with zipfile.ZipFile(tmp.name) as z:
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
    root.geometry("800x640")
    root.minsize(680, 520)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL,
                    lightcolor=ACCENT, darkcolor=ACCENT)

    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=18, pady=(16, 0))
    tk.Label(head, text="Asset Manager for Nuke", bg=BG, fg=FG,
             font=("Segoe UI", 15, "bold")).pack(side="left")
    tk.Label(head, text=f"{AUTHOR}  \u00b7  {CONTACT}", bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(side="right", pady=(6, 0))
    tk.Label(root, text=f"Installs into {DEST}", bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(anchor="w", padx=18)

    checks_frame = tk.Frame(root, bg=PANEL)
    checks_frame.pack(fill="x", padx=18, pady=12)

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=18)

    def make_button(text, cmd, primary=False):
        return tk.Button(btns, text=text, command=cmd, relief="flat", cursor="hand2",
                         bg=ACCENT if primary else PANEL, fg="#0b1a1f" if primary else FG,
                         activebackground="#56c4e3" if primary else "#262b33",
                         activeforeground="#0b1a1f" if primary else FG,
                         font=("Segoe UI", 10, "bold" if primary else "normal"),
                         padx=14, pady=6, bd=0, highlightthickness=0)

    install_btn = make_button("Install / Update", lambda: start(do_install), primary=True)
    github_btn = make_button("Update from GitHub", lambda: start(do_github))
    ff_btn = make_button("Download ffmpeg", lambda: start(do_download))
    uninstall_btn = make_button("Uninstall", lambda: confirm_uninstall())
    close_btn = make_button("Close", root.destroy)
    install_btn.pack(side="left")
    github_btn.pack(side="left", padx=8)
    ff_btn.pack(side="left")
    close_btn.pack(side="right")
    uninstall_btn.pack(side="right", padx=8)

    bar = ttk.Progressbar(root, mode="determinate", style="TProgressbar")
    bar.pack(fill="x", padx=18, pady=(12, 0))

    log_box = tk.Text(root, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                      font=("Consolas", 9), height=10, wrap="word", bd=0, padx=8, pady=6)
    log_box.pack(fill="both", expand=True, padx=18, pady=12)

    events = queue.Queue()
    state = {"busy": False, "remote": None}

    def log(msg):
        events.put(("log", msg))

    def progress(done, total):
        events.put(("progress", (done, total)))

    def refresh_checks():
        for w in checks_frame.winfo_children():
            w.destroy()
        rows = run_checks()
        remote = state["remote"]
        if remote:
            installed = version_of(DEST)
            newer = installed and remote[0] and _vt(remote[0]) > _vt(installed)
            rows.insert(5, (WARN if newer else OK, "GitHub",
                            f"version {remote[0] or '?'} on github.com/{remote[1]}"
                            + ("  - newer, use 'Update from GitHub'" if newer else "")))
        for status, title, detail in rows:
            row = tk.Frame(checks_frame, bg=PANEL)
            row.pack(fill="x", padx=10, pady=3)
            tk.Label(row, text=ICONS[status], width=2, bg=PANEL, fg=COLORS[status],
                     font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Label(row, text=title, width=12, anchor="w", bg=PANEL, fg=FG,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            tk.Label(row, text=detail, anchor="w", justify="left", bg=PANEL, fg=DIM,
                     font=("Segoe UI", 9), wraplength=540).pack(side="left", fill="x", expand=True)
        ff_missing = any(t[1] == "ffmpeg" and t[0] != OK for t in rows)
        package_ok = os.path.exists(os.path.join(SOURCE, "__init__.py"))
        idle = not state["busy"]
        install_btn.configure(state="normal" if package_ok and idle else "disabled")
        github_btn.configure(state="normal" if idle else "disabled")
        ff_btn.configure(state="normal" if ff_missing and IS_WINDOWS and idle else "disabled")

    def _vt(v):
        return tuple(int(x) for x in re.findall(r"\d+", v or "0"))

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
                elif kind == "remote":
                    state["remote"] = payload
                    refresh_checks()
                elif kind == "done":
                    state["busy"] = False
                    bar.configure(mode="determinate", value=0)
                    refresh_checks()
                    if payload:
                        messagebox.showinfo("Asset Manager", payload)
        except queue.Empty:
            pass
        root.after(80, pump)

    def start(job):
        if state["busy"]:
            return
        state["busy"] = True
        for b in (install_btn, github_btn, ff_btn):
            b.configure(state="disabled")

        def runner():
            message = None
            try:
                message = job()
            except Exception as e:
                log(f"ERROR: {e}")
            events.put(("done", message))

        threading.Thread(target=runner, daemon=True).start()

    def do_install():
        log("---- Install / Update (from this folder) ----")
        install_files(log)
        add_menu_entry(log)
        missing = [t for t in FF_TOOLS if not find_ff(t)]
        if missing:
            log("ffmpeg still missing: " + ", ".join(missing) + " - click 'Download ffmpeg'")
        log("Done. Restart Nuke, then open:  DMB Tools > Asset Manager")
        return "Installed.\n\nRestart Nuke and open  DMB Tools > Asset Manager."

    def do_github():
        log("---- Update from GitHub ----")
        plan = update_from_github(log, progress)
        if plan["update_available"]:
            log("Done. Restart Nuke to load the new version.")
            return f"Updated to {plan['remote_version'] or 'the latest version'}.\n\nRestart Nuke."
        return None

    def do_download():
        log("---- Download ffmpeg ----")
        download_ffmpeg(log, progress)

    def confirm_uninstall():
        if state["busy"]:
            return
        answer = messagebox.askyesnocancel(
            "Uninstall Asset Manager",
            "Remove the plugin and its menu entry?\n\n"
            "Yes = keep your library (data folder)\nNo = remove everything\nCancel = do nothing")
        if answer is None:
            return

        def job():
            log("---- Uninstall ----")
            uninstall(log, keep_library=answer)
            return "Uninstalled. Restart Nuke."
        start(job)

    def fetch_remote():
        try:
            events.put(("remote", remote_version()))
        except Exception as e:
            log(f"GitHub not reachable right now ({e})")

    refresh_checks()
    log("Checked this machine - see the list above.")
    threading.Thread(target=fetch_remote, daemon=True).start()
    pump()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
