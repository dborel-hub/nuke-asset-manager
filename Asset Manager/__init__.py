"""
Asset Manager for Nuke
Browse your footage, plates, images and elements and drop them into the
Node Graph. Works on Nuke Indie: nodes are created through TCL, so it never
hits Indie's Python node limit.

Daniel Marinho Borel - danielmborel@gmail.com
https://github.com/dborel-hub/nuke-asset-manager
"""

__version__ = "1.0.0"
__author__ = "Daniel Marinho Borel"

# Main module imports
from .core import AssetScanner, AssetLibrary, AssetItem
from .database import DatabaseManager

# UI import is optional (requires PySide2/PySide6)
try:
    from .ui import AssetManagerPanel
    __all__ = [
        'AssetScanner',
        'AssetLibrary',
        'AssetItem',
        'DatabaseManager',
        'AssetManagerPanel'
    ]
except ImportError as e:
    # PySide2/PySide6 not available
    __all__ = [
        'AssetScanner',
        'AssetLibrary',
        'AssetItem',
        'DatabaseManager'
    ]
