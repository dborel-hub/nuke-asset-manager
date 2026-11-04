"""
AssetLibrary - Main controller for asset management
Coordinates database, scanner, and thumbnail generation
"""

import os
import threading
import time
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime

from .asset_item import AssetItem
from .asset_scanner import AssetScanner, scan_for_missing_assets
from .thumbnail_generator import ThumbnailGenerator
from ..database import DatabaseManager, AssetModel, FolderModel
from ..config import ConfigManager
from ..log import log


class AssetLibrary:
    """
    Main asset library management class
    
    Responsibilities:
    - Coordinate asset scanning
    - Manage database operations
    - Handle thumbnail generation
    - Provide search and filter API
    - Maintain in-memory cache of assets
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize asset library
        
        Args:
            db_path: Path to database file (uses default if None)
        """
        self.db = DatabaseManager(db_path)
        self.scanner = AssetScanner()
        self.thumbnail_gen = ThumbnailGenerator()
        self.config = ConfigManager()
        
        # In-memory cache
        self._asset_cache: Dict[int, AssetItem] = {}
        self._cache_loaded = False
        
        # Callbacks
        self._scan_progress_callback = None
        self._scan_complete_callback = None
        
        # Background thumbnail generation
        self._bg_stop_event = threading.Event()
        self._processed_assets = set()   # (legacy, still cleared by scans)
        self._thumb_lock = threading.Lock()
        self._thumb_running = False
        self._thumb_dirty = False
        self._thumb_force = False
        self._thumb_failed = set()       # asset ids with no possible thumbnail
        self.thumb_total = 0             # progress of the current run (for the UI)
        self.thumb_done = 0
    
    # ==================== FOLDER MANAGEMENT ====================
    
    def add_folder(self, folder_path: str, name: str = None, 
                   recursive: bool = True, auto_scan: bool = True) -> int:
        """
        Add a folder to watch list
        
        Args:
            folder_path: Path to folder
            name: Display name (uses folder name if None)
            recursive: Scan subdirectories
            auto_scan: Automatically scan on startup
        
        Returns:
            Folder ID
        """
        if not os.path.exists(folder_path):
            raise ValueError(f"Folder not found: {folder_path}")
        
        folder_path = os.path.abspath(folder_path)
        
        if name is None:
            name = os.path.basename(folder_path)
        
        folder = FolderModel(
            path=folder_path,
            name=name,
            recursive=recursive,
            auto_scan=auto_scan,
            is_active=True,
        )
        
        folder_id = self.db.add_folder(folder)
        
        return folder_id
    
    def remove_folder(self, folder_id: int, delete_assets: bool = False):
        """
        Remove a folder from watch list
        
        Args:
            folder_id: Folder ID
            delete_assets: If True, also delete all assets from this folder
        """
        self.db.delete_folder(folder_id, delete_assets)
        
        # Clear cache
        if delete_assets:
            self._clear_cache()
    
    # Fields the user edits (or that a rescan can't know) - never overwritten
    _KEEP_ON_RESCAN = ('id', 'tags', 'notes', 'rating', 'added_time', 'thumbnail_path')

    def _update_rescanned(self, existing, asset):
        """
        Refresh file metadata of an asset already in the library.
        (Used to send the whole dict - the tag list made SQLite raise, the
        rescan was thrown away, and notes/rating/tags would have been wiped.)
        """
        data = asset.to_dict()
        for key in self._KEEP_ON_RESCAN:
            data.pop(key, None)
        self.db.update_asset(existing.id, data)
        asset.id = existing.id
        asset.notes = existing.notes or ""
        asset.rating = existing.rating or 0
        asset.thumbnail_path = existing.thumbnail_path
        if getattr(existing, 'tags', None):
            asset.tags = list(existing.tags)

    def get_folders(self) -> List[FolderModel]:
        """Get all watched folders"""
        return self.db.get_all_folders()
    
    def update_folder(self, folder_id: int, **updates):
        """Update folder settings"""
        self.db.update_folder(folder_id, updates)
    
    # ==================== ASSET SCANNING ====================
    
    def scan_folder(self, folder_id: int, 
                   progress_callback: Optional[Callable] = None,
                   complete_callback: Optional[Callable] = None):
        """
        Scan a watched folder for assets
        
        Args:
            folder_id: Folder ID to scan
            progress_callback: Called with (current, total, filepath)
            complete_callback: Called when scan completes
        """
        folder = self.db.get_folder(folder_id)
        if not folder:
            raise ValueError(f"Folder ID {folder_id} not found")
        
        # Set up callbacks
        def on_complete(assets: List[AssetItem]):
            """Called from scanner thread - keep this lightweight"""
            try:
                # Add assets to database
                added_count = 0
                updated_count = 0
                
                for asset in assets:
                    asset.folder_id = folder_id
                    
                    # Check if asset already exists
                    existing = self.db.get_asset_by_path(asset.filepath)
                    if existing:
                        self._update_rescanned(existing, asset)
                        updated_count += 1
                    else:
                        # Add new asset
                        asset_id = self.db.add_asset(AssetModel.from_dict(asset.to_dict()))
                        asset.id = asset_id
                        added_count += 1
                    
                    # Add to cache
                    self._asset_cache[asset.id] = asset
                
                # Update folder scan timestamp
                self.db.update_folder(folder_id, {
                    'last_scanned': datetime.now().timestamp(),
                    'asset_count': len(assets)
                })
                
                log.debug(f"Scan complete: {added_count} new, {updated_count} updated")
                
                # Notify background processor of new assets
                self._processed_assets.clear()
                
            except Exception as e:
                log.warning(f"Error in scan completion: {e}")
                import traceback
                traceback.print_exc()
            
            # Call user callback - keep this simple
            if complete_callback:
                try:
                    complete_callback(assets)
                except Exception as e:
                    log.warning(f"Error calling user callback: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Start scan
        self.scanner.scan_directory_async(
            folder.path,
            folder.recursive,
            progress_callback,
            on_complete
        )
    
    def scan_all_folders(self, 
                        progress_callback: Optional[Callable] = None,
                        complete_callback: Optional[Callable] = None):
        """Scan all active watched folders"""
        folders = [f for f in self.get_folders() if f.is_active]
        
        if not folders:
            if complete_callback:
                complete_callback([])
            return
        
        # Scan each folder sequentially
        # TODO: Could be parallelized with a thread pool
        for folder in folders:
            self.scan_folder(folder.id, progress_callback)
        
        if complete_callback:
            complete_callback(self.get_all_assets())
    
    def add_files(self, filepaths: List[str], folder_id: int = None) -> List[AssetItem]:
        """
        Add specific files to library
        
        Args:
            filepaths: List of file paths
            folder_id: Optional folder ID to associate with
        
        Returns:
            List of added AssetItem objects
        """
        assets = self.scanner.scan_files(filepaths)
        
        for asset in assets:
            asset.folder_id = folder_id
            
            # Check if exists
            existing = self.db.get_asset_by_path(asset.filepath)
            if existing:
                self._update_rescanned(existing, asset)
            else:
                asset_id = self.db.add_asset(AssetModel.from_dict(asset.to_dict()))
                asset.id = asset_id
            
            # Cache and thumbnail
            self._asset_cache[asset.id] = asset
            self._generate_thumbnail_async(asset)
        
        # Notify background processor of new assets
        self._processed_assets.clear()
        
        return assets
    
    # ==================== ASSET RETRIEVAL ====================
    
    def get_asset(self, asset_id: int) -> Optional[AssetItem]:
        """Get asset by ID"""
        # Check cache first
        if asset_id in self._asset_cache:
            return self._asset_cache[asset_id]
        
        # Load from database
        asset_model = self.db.get_asset(asset_id)
        if asset_model:
            asset = AssetItem.from_dict(asset_model.to_dict())
            self._asset_cache[asset_id] = asset
            return asset
        
        return None
    
    def get_all_assets(self, limit: int = None) -> List[AssetItem]:
        """Get all assets"""
        log.debug(f"[get_all_assets] Fetching assets from database (limit={limit})...")
        asset_models = self.db.get_all_assets(limit)
        log.debug(f"[get_all_assets] Database returned {len(asset_models)} models")
        
        assets = []
        for model in asset_models:
            asset_id = model.to_dict()['id']
            
            # Check cache
            if asset_id in self._asset_cache:
                assets.append(self._asset_cache[asset_id])
            else:
                asset = AssetItem.from_dict(model.to_dict())
                self._asset_cache[asset_id] = asset
                assets.append(asset)
        
        log.debug(f"[get_all_assets] Returning {len(assets)} assets")
        return assets
    
    # ==================== THUMBNAIL GENERATION ====================
    # One run at a time, 3 thumbnails in parallel (ffmpeg / QImage are
    # separate work per file). A new request while running just marks the
    # run "dirty" so it goes over the list again when it finishes.

    THUMB_WORKERS = 3

    def generate_all_thumbnails(self, force=False, on_done=None):
        """Generate missing thumbnails in the background (non-blocking)."""
        with self._thumb_lock:
            if self._thumb_running:
                self._thumb_dirty = True
                self._thumb_force = self._thumb_force or force
                return
            self._thumb_running = True
            self._thumb_dirty = False
            self._thumb_force = force
            self._bg_stop_event.clear()

        def run():
            from concurrent.futures import ThreadPoolExecutor
            while True:
                force_now = self._thumb_force
                assets = [a for a in self.get_all_assets()
                          if self.thumbnail_gen.can_have_thumbnail(a.filepath)
                          and (force_now or a.id not in self._thumb_failed)
                          and (force_now or not (a.thumbnail_path and os.path.exists(a.thumbnail_path)))]
                if assets:
                    log.debug("Generating %d thumbnails...", len(assets))
                    self.thumb_total = len(assets)
                    self.thumb_done = 0
                    with ThreadPoolExecutor(max_workers=self.THUMB_WORKERS) as pool:
                        for _ in pool.map(lambda a: self._safe_thumbnail(a, force_now), assets):
                            self.thumb_done += 1
                with self._thumb_lock:
                    if not self._thumb_dirty or self._bg_stop_event.is_set():
                        self._thumb_running = False
                        self.thumb_total = self.thumb_done = 0
                        break
                    self._thumb_dirty = False
            if on_done:
                on_done()

        threading.Thread(target=run, daemon=True).start()

    def _safe_thumbnail(self, asset, force):
        if self._bg_stop_event.is_set():
            return None
        try:
            path = self.get_thumbnail(asset, force=force)
            if not path:
                self._thumb_failed.add(asset.id)
            return path
        except Exception as e:
            log.warning("Thumbnail error for %s: %s", asset.filename, e)
            self._thumb_failed.add(asset.id)
            return None

    def stop_background_processing(self):
        """Stop thumbnail generation (called when the window closes)."""
        self._bg_stop_event.set()

    def search_assets(self, 
                     query: str = "",
                     category: str = None,
                     folder_id: int = None,
                     tags: List[str] = None,
                     extension: str = None,
                     rating_min: int = 0,
                     limit: int = None) -> List[AssetItem]:
        """
        Search assets with filters
        
        Args:
            query: Search term
            category: Filter by category
            folder_id: Filter by folder
            tags: Filter by tags
            extension: Filter by extension
            rating_min: Minimum rating
            limit: Max results
        
        Returns:
            List of matching AssetItem objects
        """
        asset_models = self.db.search_assets(
            query=query,
            category=category,
            folder_id=folder_id,
            tags=tags,
            extension=extension,
            rating_min=rating_min,
            limit=limit
        )
        
        assets = []
        for model in asset_models:
            asset_dict = model.to_dict()
            asset_id = asset_dict['id']
            
            # Check cache
            if asset_id in self._asset_cache:
                assets.append(self._asset_cache[asset_id])
            else:
                asset = AssetItem.from_dict(asset_dict)
                self._asset_cache[asset_id] = asset
                assets.append(asset)
        
        return assets
    
    # ==================== ASSET UPDATES ====================
    
    def update_asset(self, asset_id: int, **updates):
        """Update asset metadata"""
        # Update database
        self.db.update_asset(asset_id, updates)
        
        # Update cache
        if asset_id in self._asset_cache:
            asset = self._asset_cache[asset_id]
            for key, value in updates.items():
                if hasattr(asset, key):
                    setattr(asset, key, value)
    
    def delete_asset(self, asset_id: int):
        """Delete an asset from library"""
        self.db.delete_asset(asset_id)
        
        # Remove from cache
        if asset_id in self._asset_cache:
            del self._asset_cache[asset_id]
    
    def add_tag_to_asset(self, asset_id: int, tag: str):
        """Add a tag to an asset"""
        self.db.add_tag_to_asset(asset_id, tag)
        
        # Update cache
        if asset_id in self._asset_cache:
            self._asset_cache[asset_id].add_tag(tag)
    
    def remove_tag_from_asset(self, asset_id: int, tag: str):
        """Remove a tag from an asset"""
        self.db.remove_tag_from_asset(asset_id, tag)
        
        # Update cache
        if asset_id in self._asset_cache:
            self._asset_cache[asset_id].remove_tag(tag)
    
    # ==================== THUMBNAILS ====================

    @staticmethod
    def _thumbnail_source(asset):
        """
        (file to read, video seek in seconds).
        Sequences and clips use the middle frame: FX elements usually start
        on an empty / black frame.
        """
        if asset.is_sequence and asset.sequence_path and asset.first_frame is not None \
                and asset.last_frame is not None:
            middle = (asset.first_frame + asset.last_frame) // 2
            try:
                candidate = asset.sequence_path % middle
                if os.path.exists(candidate):
                    return candidate, None
            except (TypeError, ValueError):
                pass
            return asset.filepath, None
        seek = None
        if asset.duration:
            seek = float(asset.duration) * 0.5
        return asset.filepath, seek

    def get_thumbnail(self, asset: AssetItem, force: bool = False) -> Optional[str]:
        """Thumbnail path for an asset, generating it if needed."""
        if not force and asset.thumbnail_path and os.path.exists(asset.thumbnail_path):
            return asset.thumbnail_path

        source, seek = self._thumbnail_source(asset)
        thumb_path = self.thumbnail_gen.generate_thumbnail(
            asset.filepath, force=force, source_path=source, seek_seconds=seek)

        if thumb_path:
            asset.thumbnail_path = thumb_path
            if asset.id:
                self.db.update_asset(asset.id, {'thumbnail_path': thumb_path})
        return thumb_path

    def _generate_thumbnail_async(self, asset: AssetItem):
        """Kept for compatibility: queue a normal background run."""
        self.generate_all_thumbnails()

    def regenerate_all_thumbnails(self):
        """Rebuild every thumbnail in the background."""
        self._thumb_failed.clear()
        self.generate_all_thumbnails(force=True)

    # ==================== MAINTENANCE ====================
    
    def verify_assets(self) -> List[AssetItem]:
        """
        Verify all assets still exist on disk
        
        Returns:
            List of missing assets
        """
        assets = self.get_all_assets()
        missing = scan_for_missing_assets(assets)
        
        # Update database
        for asset in missing:
            if asset.id:
                self.db.update_asset(asset.id, {
                    'is_missing': True,
                    'last_verified': datetime.now().timestamp()
                })
        
        return missing
    
    def remove_missing_assets(self):
        """Remove all assets marked as missing"""
        assets = self.get_all_assets()
        
        for asset in assets:
            if asset.is_missing and asset.id:
                self.delete_asset(asset.id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get library statistics"""
        return self.db.get_statistics()
    
    def _clear_cache(self):
        """Clear in-memory cache"""
        self._asset_cache.clear()
        self._cache_loaded = False
    
    # ==================== TAGS ====================
    
    def get_all_tags(self):
        """Get all tags"""
        return self.db.get_all_tags()
    
    def create_tag(self, name: str, color: str = "#888888"):
        """Create a new tag"""
        from ..database.models import TagModel
        tag = TagModel(name=name, color=color)
        return self.db.add_tag(tag)
