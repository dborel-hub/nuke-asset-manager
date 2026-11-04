"""
Nuke Integration Module
Opens the window and creates nodes (via TCL - Nuke Indie safe)
"""

from .panel_registration import show_asset_manager
from .nuke_utils import get_nuke_main_window, get_nuke_version, is_nuke_indie
from .node_creation import create_node_from_asset, create_nodes_from_assets

__all__ = [
    'show_asset_manager',
    'get_nuke_main_window',
    'get_nuke_version',
    'is_nuke_indie',
    'create_node_from_asset',
    'create_nodes_from_assets',
]


def check_for_updates():
    """Menu entry: DMB Tools > Check for Updates..."""
    from ..ui.update_dialog import show_update_dialog
    return show_update_dialog()


__all__.append('check_for_updates')
