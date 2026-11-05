"""
menu_block - the Asset Manager entry in ~/.nuke/menu.py

Single source of truth for that block, used by BOTH:
  - install.pyw (adds / replaces / removes it)
  - the plugin itself: when the window opens, an outdated block left by an
    older version is replaced automatically, so menu changes arrive with a
    normal update - no need to run the installer again.

The block lives between unique START / END markers; only that part of
menu.py is ever touched. Before a change, menu.py is copied to ONE backup
file (menu.py.asset_manager_backup, overwritten each time) - no pile of
timestamped copies.

Standard library only (runs inside Nuke and in install.pyw).
"""

import os
import re
import glob
import shutil

BLOCK_START = "# ---- Asset Manager: START (added by install.pyw) ----"
BLOCK_END = "# ---- Asset Manager: END ----"

MENU_BLOCK = BLOCK_START + '''
# Asset Manager by Daniel Marinho Borel - loaded only when a menu item is used.
def _asset_manager_load():
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
    return sys.modules['asset_manager']

def _asset_manager_open():
    _asset_manager_load()
    from asset_manager.nuke_integration import show_asset_manager
    show_asset_manager()

try:
    import nuke
    _dmb_tools = nuke.menu('Nuke').addMenu('DMB Tools')
    _dmb_tools.addCommand('Asset Manager', _asset_manager_open)
    nuke.menu('Nodes').addCommand('DMB Tools/Asset Manager', _asset_manager_open)
except Exception as _e:
    print('[Asset Manager] menu entry failed: %s' % _e)
''' + BLOCK_END + "\n"

BACKUP_SUFFIX = ".asset_manager_backup"   # one backup file, overwritten
OWNER_SIGNS = ("_asset_manager_load", "_asset_manager_open")  # prove a marked block is ours (any version)

BLOCK_RE = re.compile(r"\n*" + re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)

# Blocks pasted by hand before the installer existed - replaced automatically
LEGACY_BLOCK_RES = [
    re.compile(r"\n*# =+\n# Asset Manager - \.nuke/Asset Manager/.*?"
               r"nuke\.menu\('Nodes'\)\.addCommand\('DMB/Asset Manager', _dmb_open_asset_manager\)\n?", re.S),
    re.compile(r"\n*# ---- Asset Manager ----\n.*?# ---- /Asset Manager ----\n?", re.S),
]
LEGACY_SIGNS = ("_dmb_open_asset_manager",)                         # hand-made, unknown format
OLD_VERSION_SIGNS = ("from nuke_integration import add_to_nuke_menu",)  # very first prototype


def default_menu_py():
    return os.path.join(os.path.expanduser("~"), ".nuke", "menu.py")


# ---------------------------------------------------------------- file helpers
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


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def backup(path, log=None):
    """Copy menu.py to a single backup file (overwritten each time)."""
    if not os.path.exists(path):
        return None
    target = path + BACKUP_SUFFIX
    shutil.copy2(path, target)
    if log:
        log("Backup: %s" % target)
    cleanup_old_backups(path, log)
    return target


def cleanup_old_backups(path, log=None):
    """
    Older versions saved menu.py.backup_<date>_<time> on every change and
    never removed them. Keep only the newest of those, delete the rest.
    """
    old = sorted(glob.glob(glob.escape(path) + ".backup_*"), key=os.path.getmtime)
    removed = 0
    for f in old[:-1]:
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    if removed and log:
        log("Removed %d old menu.py backup file(s)" % removed)
    return removed


# ---------------------------------------------------------------- state
def state(text):
    """
    'current'  block present and identical to MENU_BLOCK
    'outdated' block from an older version (safe to replace)
    'legacy'   hand-pasted block in a known format (safe to replace)
    'manual'   hand-made loader in an unknown format (leave alone)
    'foreign'  our markers, but the block belongs to another plugin (leave alone)
    'old'      loader of the very first prototype
    None       no Asset Manager entry
    """
    if BLOCK_START in text:
        m = BLOCK_RE.search(text)
        if m and MENU_BLOCK.strip() in m.group(0):
            return "current"
        if m and not any(sig in m.group(0) for sig in OWNER_SIGNS):
            return "foreign"      # another plugin copied our markers - never touch it
        return "outdated"
    if any(r.search(text) for r in LEGACY_BLOCK_RES):
        return "legacy"
    if any(s in text for s in LEGACY_SIGNS):
        return "manual"
    if any(s in text for s in OLD_VERSION_SIGNS):
        return "old"
    return None


def file_state(menu_py=None):
    return state(read_text(menu_py or default_menu_py()))


# ---------------------------------------------------------------- changes
def ensure(menu_py=None, log=None, allow_add=True):
    """
    Make menu.py hold exactly one current block.
      allow_add=True  (installer): also add it when missing
      allow_add=False (plugin):    only replace an outdated / legacy block
    Returns the state that was fixed ('outdated', 'legacy', None, 'old'),
    or False when nothing was changed.
    """
    menu_py = menu_py or default_menu_py()
    log = log or (lambda msg: None)
    cleanup_old_backups(menu_py, log)      # clear the pile left by older versions
    text = read_text(menu_py) if os.path.exists(menu_py) else ""
    st = state(text)

    if st == "current":
        log("menu.py: DMB Tools entry already there - not changed")
        return False
    if st == "manual":
        log("menu.py: a hand-made Asset Manager loader exists - not changed (edit by hand)")
        return False
    if st == "foreign":
        log("menu.py: the 'Asset Manager' markers hold another plugin's code - not changed. "
            "Give that plugin its own START/END markers.")
        return False
    if not allow_add and st not in ("outdated", "legacy"):
        return False

    os.makedirs(os.path.dirname(menu_py), exist_ok=True)
    backup(menu_py, log)
    if st == "outdated":
        text = BLOCK_RE.sub("\n", text)
        log("menu.py: older Asset Manager entry removed")
    elif st == "legacy":
        for r in LEGACY_BLOCK_RES:
            text = r.sub("\n", text)
        log("menu.py: hand-made Asset Manager block replaced")

    text = text.rstrip("\n")
    text = (text + "\n\n\n" if text else "") + MENU_BLOCK
    write_text(menu_py, text)

    # read back: if it isn't "current" now, stop here instead of retrying
    # (and backing up) on every Nuke session
    if state(read_text(menu_py)) != "current":
        log("menu.py: entry written but not recognised afterwards - stopped (check menu.py by hand)")
        return False
    log("menu.py: entry added  ->  DMB Tools > Asset Manager")
    if st == "old":
        log("NOTE: menu.py still has the OLD loader block - delete it by hand")
    return st


def remove(menu_py=None, log=None):
    menu_py = menu_py or default_menu_py()
    log = log or (lambda msg: None)
    text = read_text(menu_py)
    if BLOCK_START not in text:
        log("No installer block in menu.py")
        return False
    backup(menu_py, log)
    write_text(menu_py, BLOCK_RE.sub("\n", text).rstrip("\n") + "\n")
    log("menu.py: Asset Manager entry removed")
    return True
