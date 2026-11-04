"""
Configuration settings for Asset Manager
"""

import os
import json
from .log import log

# Application metadata
APP_NAME = "Asset Manager"
APP_VERSION = "1.0.0"
AUTHOR = "Daniel Marinho Borel"
CONTACT = "danielmborel@gmail.com"

# Where updates come from (updater.py / install.pyw read these two lines)
GITHUB_REPO = "dborel-hub/nuke-asset-manager"
GITHUB_BRANCH = "main"

# Paths
NUKE_DIR = os.path.expanduser("~/.nuke")
# Everything lives in .nuke/Asset Manager/
#   code at the root, ffmpeg in bin/, database + thumbnails in data/
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(APP_ROOT, "data")
OLD_CONFIG_DIR = os.path.join(NUKE_DIR, "asset_manager")  # pre-rename location
DATABASE_PATH = os.path.join(CONFIG_DIR, "asset_library.db")
THUMBNAIL_CACHE_DIR = os.path.join(CONFIG_DIR, "thumbnails")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Thumbnail settings
THUMBNAIL_SIZE = (384, 384)
THUMBNAIL_QUALITY = 85

# Asset categories
ASSET_CATEGORIES = {
    "Footage": [".mov", ".mp4", ".avi", ".mxf", ".r3d"],
    "EXR": [".exr"],
    "Plates": [".dpx", ".cin", ".tif", ".tiff"],
    "Images": [".png", ".jpg", ".jpeg"],
    "HDRI": [".hdr", ".hdri", ".exr"],
    "Geometry": [".obj", ".fbx", ".abc", ".usd", ".usda", ".usdc"],
    "LUTs": [".cube", ".3dl", ".csp", ".lut"],
    "References": [".psd"],
    "Nuke": [".nk", ".nknc"],
}

# Never shown / scanned (read-me files, documents, junk that ships with packs)
EXCLUDED_EXTENSIONS = (
    ".pdf", ".txt", ".md", ".rtf", ".doc", ".docx", ".html", ".htm",
    ".url", ".nfo", ".ini", ".db", ".log", ".xml", ".json",
)

# Supported file extensions (flattened from categories)
SUPPORTED_EXTENSIONS = []
for exts in ASSET_CATEGORIES.values():
    SUPPORTED_EXTENSIONS.extend(exts)
SUPPORTED_EXTENSIONS = [e for e in set(SUPPORTED_EXTENSIONS) if e not in EXCLUDED_EXTENSIONS]

# Image sequence patterns
SEQUENCE_PATTERNS = [
    r"(.+?)[\._](\d{3,})\.(\w+)$",  # name.####.ext or name_####.ext
    r"(.+?)[\._](%\d+d)\.(\w+)$",   # name.%04d.ext
]

# Node types for drag & drop
NODE_TYPE_MAPPING = {
    "Footage": "Read",
    "EXR": "Read",
    "Plates": "Read",
    "HDRI": "Read",
    "Geometry": "ReadGeo2",
    "LUTs": "Vectorfield",
    "Nuke": "Read",  # Will be handled specially to merge scripts
}

# Performance settings
MAX_CONCURRENT_SCANS = 4
THUMBNAIL_CACHE_SIZE = 1000  # Max thumbnails to keep in memory
LAZY_LOAD_THRESHOLD = 100  # Load thumbnails in batches

# UI Settings
GRID_ITEM_SIZE = 180
LIST_ITEM_HEIGHT = 60


class ConfigManager:
    """Manages user configuration and preferences"""
    
    def __init__(self):
        self.config_path = CONFIG_FILE
        self.config = self._load_config()
    
    def _load_config(self):
        """Load configuration from JSON file"""
        default_config = {
            "last_opened_folders": [],
            "view_mode": "grid",  # grid or list
            "sort_by": "name",  # name, date, type, size
            "show_hidden_files": False,
            "auto_scan_on_startup": False,
            "thumbnail_quality": THUMBNAIL_QUALITY,
            "theme": "dark",
        }
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                log.warning(f"Error loading config: {e}")
        
        return default_config
    
    def save_config(self):
        """Save configuration to JSON file"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            log.warning(f"Error saving config: {e}")
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set configuration value"""
        self.config[key] = value
        self.save_config()


# Initialize directories on import
def _migrate_old_data():
    """
    One-time copy of the library from the old location
    (.nuke/asset_manager) into Asset Manager/data. The old folder is left
    untouched - delete it by hand once everything works.
    Thumbnail paths stored in the database still point to the old folder;
    the library re-points them automatically when a thumbnail is missing.
    """
    import shutil
    old_db = os.path.join(OLD_CONFIG_DIR, "asset_library.db")
    if os.path.exists(DATABASE_PATH) or not os.path.exists(old_db):
        return
    try:
        shutil.copytree(OLD_CONFIG_DIR, CONFIG_DIR, dirs_exist_ok=True)
        log.warning("Library migrated from %s" % OLD_CONFIG_DIR)
    except Exception as e:
        log.warning("Could not migrate old library: %s" % e)


def init_directories():
    """Create necessary directories if they don't exist"""
    _migrate_old_data()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_CACHE_DIR, exist_ok=True)

init_directories()
