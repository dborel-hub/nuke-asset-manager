"""
Node Creation - Create Nuke nodes from assets (Nuke Indie safe)

Nuke Indie caps Python at ~10 node objects per session. Every
nuke.nodes.X(), nuke.createNode(), nuke.selectedNodes(), nuke.toNode()
etc. returns a Python node object and burns that budget.

This module NEVER creates a Python node object. Everything goes through
nuke.tcl(), which returns plain strings (tested: 12 Reads via TCL, no limit
error). Functions return node NAMES (str), not node objects.
"""

import os

try:
    from ..utils import get_video_metadata
except ImportError:
    from utils import get_video_metadata
from ..log import log


VIDEO_EXTENSIONS = ('.mov', '.mp4', '.avi', '.mkv', '.mxf', '.m4v',
                    '.webm', '.flv', '.wmv', '.r3d')

GRID_COLUMNS = 4
GRID_DX = 120
GRID_DY = 150


# ------------------------------------------------------------------
# TCL helpers (strings only - zero node budget)
# ------------------------------------------------------------------

def _q(value):
    """Quote a value as a TCL word (double quotes, special chars escaped)."""
    s = str(value)
    for ch in ('\\', '"', '[', ']', '$', '{', '}'):
        s = s.replace(ch, '\\' + ch)
    return '"%s"' % s


def _tcl(cmd):
    import nuke
    return nuke.tcl(cmd)


def _exists(name):
    try:
        return _tcl('exists %s' % _q(name)) == '1'
    except Exception:
        return False


def _unique_name(node_class):
    """Next free default-style name (Read1, Read2...) without touching nodes."""
    i = 1
    while _exists('%s%d' % (node_class, i)):
        i += 1
    return '%s%d' % (node_class, i)


def _set_knob(node_name, knob, value):
    """Set one knob via TCL. Fails silently if the knob doesn't exist."""
    try:
        _tcl('knob %s %s' % (_q('%s.%s' % (node_name, knob)), _q(value)))
        return True
    except Exception as e:
        log.debug('[node_creation] knob %s.%s not set: %s' % (node_name, knob, e))
        return False


def _anchor_position():
    """
    Position of the selected node (via TCL), or None.
    Replaces nuke.selectedNodes() / activeViewer().node(), which burned budget.
    """
    try:
        name = _tcl('selected_node')
    except Exception:
        return None  # nothing selected
    if not name:
        return None
    try:
        x = int(float(_tcl('value %s' % _q(name + '.xpos'))))
        y = int(float(_tcl('value %s' % _q(name + '.ypos'))))
        return x, y
    except Exception:
        return None


def _normalize_path_for_nuke(path):
    return path.replace('\\', '/') if path else path


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def create_node_from_asset(asset, xpos=None, ypos=None):
    """
    Create the right node for an asset. Returns the node NAME (str) or None.
    If xpos/ypos are None, places it under the selected node (if any).
    """
    node_class = _get_node_type(asset)
    if not node_class:
        raise ValueError('Unsupported asset type: %s' % asset.category)

    if xpos is None or ypos is None:
        anchor = _anchor_position()
        if anchor:
            xpos, ypos = anchor[0], anchor[1] + 100

    name = _unique_name(node_class)

    # 1) Create the node with only name (+ position). Minimal = can't fail on
    #    an unknown knob.
    parts = [node_class, 'name', _q(name)]
    if xpos is not None and ypos is not None:
        parts += ['xpos', str(int(xpos)), 'ypos', str(int(ypos))]
    _tcl(' '.join(parts))

    # 2) Fill knobs one by one (each failure is isolated)
    if node_class == 'Read':
        _fill_read(name, asset)
    elif node_class == 'ReadGeo2':
        _set_knob(name, 'file', _normalize_path_for_nuke(asset.filepath))
        if asset.extension.lower() == '.abc' and asset.first_frame and asset.last_frame:
            _set_knob(name, 'range_first', asset.first_frame)
            _set_knob(name, 'range_last', asset.last_frame)
    elif node_class == 'Vectorfield':
        _set_knob(name, 'vfield_file', _normalize_path_for_nuke(asset.filepath))

    return name


def create_nodes_from_assets(assets, arrange=True):
    """
    Create nodes for several assets inside one undo step.
    Returns a list of node NAMES.
    """
    import nuke

    names = []
    base = _anchor_position()
    base_x, base_y = (base[0], base[1] + 100) if base else (None, None)

    nuke.Undo.begin('Asset Manager: import')
    try:
        for i, asset in enumerate(assets):
            x = y = None
            if arrange and base_x is not None:
                x = base_x + (i % GRID_COLUMNS) * GRID_DX
                y = base_y + (i // GRID_COLUMNS) * GRID_DY
            try:
                names.append(create_node_from_asset(asset, x, y))
            except Exception as e:
                log.warning('[node_creation] Error creating node for %s: %s' % (asset.filename, e))
    finally:
        nuke.Undo.end()

    return names


# ------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------

def _get_node_type(asset):
    category_to_node = {
        'Footage': 'Read',
        'EXR': 'Read',
        'Plates': 'Read',
        'HDRI': 'Read',
        'Geometry': 'ReadGeo2',
        'LUTs': 'Vectorfield',
        'References': 'Read',
    }
    ext = asset.extension.lower()
    if ext in ('.abc', '.obj', '.fbx', '.usd', '.usda', '.usdc'):
        return 'ReadGeo2'
    if ext in ('.cube', '.3dl', '.csp'):
        return 'Vectorfield'
    if ext in ('.nk', '.nknc', '.nkind'):
        return None
    return category_to_node.get(asset.category, 'Read')


def _resolve_frame_range(asset):
    """Frame range from asset metadata, with ffprobe fallback for videos."""
    first, last = asset.first_frame, asset.last_frame
    if first is not None and last is not None and last > first:
        return first, last

    if asset.extension.lower() not in VIDEO_EXTENSIONS:
        return None, None

    try:
        try:
            from ..utils import get_video_frame_count_fallback
        except ImportError:
            from utils import get_video_frame_count_fallback

        meta = get_video_metadata(asset.filepath)
        if meta:
            first, last = meta.get('first_frame'), meta.get('last_frame')
        if first is None or last is None or last <= first:
            count = get_video_frame_count_fallback(asset.filepath)
            if count and count > 1:
                first, last = 1, count
    except Exception as e:
        log.warning('[node_creation] ffprobe fallback failed: %s' % e)
        return None, None

    if first is not None and last is not None and last > first:
        asset.first_frame, asset.last_frame = first, last
        asset.frame_count = last - first + 1
        return first, last
    return None, None


def _fill_read(name, asset):
    _set_knob(name, 'file', _normalize_path_for_nuke(asset.get_display_path()))

    first, last = _resolve_frame_range(asset)
    if first is not None:
        for knob, val in (('first', first), ('last', last),
                          ('origfirst', first), ('origlast', last)):
            _set_knob(name, knob, int(val))

    # Colorspace and premultiplied are left to Nuke on purpose: its file
    # rules / OCIO config know better than a guess from the file name.


def get_nuke_root_path():
    """Current script folder, via TCL (nuke.root() would burn budget)."""
    try:
        script_path = _tcl('value root.name')
        if script_path:
            return os.path.dirname(script_path)
    except Exception:
        pass
    return None


def make_path_relative_to_script(filepath):
    root_path = get_nuke_root_path()
    if root_path and os.path.exists(root_path):
        try:
            return os.path.relpath(filepath, root_path)
        except ValueError:
            return filepath
    return filepath
