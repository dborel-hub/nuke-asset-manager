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
