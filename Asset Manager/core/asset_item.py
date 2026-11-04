"""
AssetItem class - represents a single asset in memory
"""

import os
from typing import Optional, List, Dict, Any
from ..utils import (
    get_file_hash, 
    format_file_size,
    get_sequence_info,
    detect_version,
    get_color_space_from_exr,
    is_file_accessible,
    get_video_metadata
)
from ..config import ASSET_CATEGORIES
from ..log import log


class AssetItem:
    """
    Represents a single asset with all its metadata
    
    This is the in-memory representation of an asset, used by the UI.
    It can be converted to/from AssetModel for database operations.
    """
    
    def __init__(self, filepath: str, scan: bool = True):
        """
        Initialize an AssetItem from a file path
        
        Args:
            filepath: Absolute path to the asset file
            scan: Read metadata from disk (sequence range, ffprobe...).
                  False when the data comes from the database (from_dict) -
                  rescanning every asset on load froze the UI.
        """
        self.filepath = os.path.abspath(filepath)
        self.filename = os.path.basename(filepath)
        self.file_hash = get_file_hash(filepath)
        
        # Initialize default values
        self.id = None
        self.file_size = 0
        self.file_type = ""
        self.extension = ""
        self.modified_time = 0.0
        self.created_time = 0.0
        self.category = "Unknown"
        self.folder_id = None
        
        # Sequence information
        self.is_sequence = False
        self.first_frame = None
        self.last_frame = None
        self.frame_count = 1
        self.missing_frames = []
        self.sequence_path = None
        
        # Media information
        self.resolution_width = None
        self.resolution_height = None
        self.color_space = None
        self.bit_depth = None
        self.fps = None
        self.duration = None
        
        # Versioning
        self.version = None
        
        # User metadata
        self.tags = []
        self.notes = ""
        self.rating = 0
        
        # Thumbnail
        self.thumbnail_path = None
        self._thumbnail_loaded = False
        
        # Status
        self.last_verified = None
        self.added_time = None
        
        if not scan:
            self.is_missing = False
            self.extension = os.path.splitext(self.filepath)[1].lower()
            return
        
        self.is_missing = not is_file_accessible(filepath)
        
        # Scan file metadata
        if not self.is_missing:
            self._scan_file_metadata()
    
    def _scan_file_metadata(self):
        """Scan basic file metadata"""
        try:
            stat = os.stat(self.filepath)
            self.file_size = stat.st_size
            self.modified_time = stat.st_mtime
            self.created_time = stat.st_ctime
        except Exception as e:
            log.warning(f"Error scanning file metadata: {e}")
            self.is_missing = True
        
        # Get extension and categorize
        self.extension = os.path.splitext(self.filepath)[1].lower()
        self.category = self._detect_category()
        
        # Detect version
        self.version = detect_version(self.filepath)
        
        # Check if it's a sequence
        seq_info = get_sequence_info(self.filepath)
        if seq_info['is_sequence']:
            self.is_sequence = True
            self.first_frame = seq_info['first_frame']
            self.last_frame = seq_info['last_frame']
            self.frame_count = seq_info['frame_count']
            self.missing_frames = seq_info['missing_frames']
            self.sequence_path = seq_info['sequence_path']
        
        # Colorspace is NOT guessed from the file name any more (it used to
        # set "linear"/"Cineon" on the Read and fight the OCIO config).
        
        # Extract video metadata for video files
        video_extensions = ['.mov', '.mp4', '.avi', '.mkv', '.mxf', '.m4v', '.webm', '.flv', '.wmv', '.r3d']
        if self.extension in video_extensions:
            log.debug(f"\n[AssetItem] ===== SCANNING VIDEO: {self.filename} =====")
            log.debug(f"[AssetItem] Extension: {self.extension}")
            
            video_meta = get_video_metadata(self.filepath)
            
            if video_meta:
                log.debug(f"[AssetItem] ✓ Video metadata retrieved successfully")
                log.debug(f"[AssetItem]   - Duration: {video_meta.get('duration')}s")
                log.debug(f"[AssetItem]   - FPS: {video_meta.get('fps')}")
                log.debug(f"[AssetItem]   - Resolution: {video_meta.get('width')}x{video_meta.get('height')}")
                log.debug(f"[AssetItem]   - Codec: {video_meta.get('codec')}")
                
                # Store video metadata
                self.duration = video_meta.get('duration')
                self.fps = video_meta.get('fps')
                self.resolution_width = video_meta.get('width')
                self.resolution_height = video_meta.get('height')
                
                # Set frame range from video metadata
                first = video_meta.get('first_frame')
                last = video_meta.get('last_frame')
                
                log.debug(f"[AssetItem] Extracted frame range: first={first}, last={last}")
                
                if first is not None and last is not None and last > first:
                    self.first_frame = first
                    self.last_frame = last
                    self.frame_count = last - first + 1
                    log.debug(f"[AssetItem] ✓ Frame range SET: {self.first_frame}-{self.last_frame} ({self.frame_count} frames)")
                else:
                    # If ffprobe failed, mark as video but leave frame range unset
                    # This allows fallback frame detection later
                    log.debug(f"[AssetItem] ⚠ Frame range is invalid (first={first}, last={last})")
                    log.debug(f"[AssetItem]   Trying fallback: will attempt frame detection on demand")
                    self.first_frame = 1
                    self.last_frame = None  # Mark as invalid for later fallback
                    self.frame_count = 1
            else:
                log.warning(f"[AssetItem] ✗ Failed to retrieve video metadata")
                log.debug(f"[AssetItem]   Will attempt frame detection on demand during Nuke node creation")
                self.first_frame = 1
                self.last_frame = None  # Mark as invalid for later fallback
                self.frame_count = 1
            
            log.debug(f"[AssetItem] ===== END SCANNING VIDEO =====\n")
    
    def _detect_category(self) -> str:
        """Detect asset category based on file extension"""
        for category, extensions in ASSET_CATEGORIES.items():
            if self.extension in extensions:
                return category
        return "Unknown"
    
    def get_display_name(self) -> str:
        """Get display name for UI (shows sequence notation if applicable)"""
        if self.is_sequence and self.sequence_path:
            return os.path.basename(self.sequence_path)
        return self.filename
    
    def get_display_path(self) -> str:
        """Get display path for UI (shows sequence notation if applicable)"""
        path = self.sequence_path if (self.is_sequence and self.sequence_path) else self.filepath
        # Normalize path for cross-platform compatibility (Nuke requires forward slashes)
        return path.replace('\\', '/') if path else path
    
    def get_frame_range_str(self) -> str:
        """Get frame range as string (e.g., '1-100')"""
        if not self.is_sequence:
            return "N/A"
        return f"{self.first_frame}-{self.last_frame}"
    
    def get_resolution_str(self) -> str:
        """Get resolution as string (e.g., '1920x1080')"""
        if self.resolution_width and self.resolution_height:
            return f"{self.resolution_width}x{self.resolution_height}"
        return "Unknown"
    
    def get_size_str(self) -> str:
        """Get file size as human-readable string"""
        return format_file_size(self.file_size)
    
    def verify_exists(self) -> bool:
        """Verify if the asset file still exists"""
        exists = is_file_accessible(self.filepath)
        self.is_missing = not exists
        return exists
    
    def add_tag(self, tag: str):
        """Add a tag to this asset"""
        if tag not in self.tags:
            self.tags.append(tag)
    
    def remove_tag(self, tag: str):
        """Remove a tag from this asset"""
        if tag in self.tags:
            self.tags.remove(tag)
    
    def has_tag(self, tag: str) -> bool:
        """Check if asset has a specific tag"""
        return tag in self.tags
    
    def matches_search(self, query: str) -> bool:
        """
        Check if asset matches a search query
        
        Searches in:
        - Filename
        - Extension
        - Category
        - Tags
        - Notes
        """
        query = query.lower()
        
        search_fields = [
            self.filename.lower(),
            self.extension.lower(),
            self.category.lower(),
            self.notes.lower(),
        ] + [tag.lower() for tag in self.tags]
        
        return any(query in field for field in search_fields)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        import json
        return {
            'id': self.id,
            'filepath': self.filepath,
            'filename': self.filename,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'file_type': self.file_type,
            'extension': self.extension,
            'modified_time': self.modified_time,
            'created_time': self.created_time,
            'category': self.category,
            'folder_id': self.folder_id,
            'is_sequence': self.is_sequence,
            'first_frame': self.first_frame,
            'last_frame': self.last_frame,
            'frame_count': self.frame_count,
            'missing_frames': json.dumps(self.missing_frames) if isinstance(self.missing_frames, list) else self.missing_frames,
            'sequence_path': self.sequence_path,
            'resolution_width': self.resolution_width,
            'resolution_height': self.resolution_height,
            'color_space': self.color_space,
            'bit_depth': self.bit_depth,
            'fps': self.fps,
            'duration': self.duration,
            'version': self.version,
            'tags': self.tags,  # Tags will be converted by AssetModel.to_dict()
            'notes': self.notes,
            'rating': self.rating,
            'thumbnail_path': self.thumbnail_path,
            'is_missing': self.is_missing,
            'last_verified': self.last_verified,
            'added_time': self.added_time,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AssetItem':
        """Create AssetItem from dictionary"""
        asset = cls(data['filepath'], scan=False)
        
        # Update with stored data
        for key, value in data.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        
        return asset
    
    def __repr__(self):
        return f"<AssetItem: {self.filename} ({self.category})>"
    
    def __str__(self):
        return self.get_display_name()
