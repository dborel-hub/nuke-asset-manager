"""
Database models for asset management
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class AssetModel:
    """Data model for an asset"""
    
    # Primary fields
    id: Optional[int] = None
    filepath: str = ""
    filename: str = ""
    file_hash: str = ""
    
    # File metadata
    file_size: int = 0
    file_type: str = ""
    extension: str = ""
    modified_time: float = 0.0
    created_time: float = 0.0
    
    # Asset classification
    category: str = "Unknown"
    folder_id: Optional[int] = None
    
    # Sequence information
    is_sequence: bool = False
    first_frame: Optional[int] = None
    last_frame: Optional[int] = None
    frame_count: int = 1
    missing_frames: str = "[]"  # JSON string of missing frames
    sequence_path: Optional[str] = None
    
    # Media information
    resolution_width: Optional[int] = None
    resolution_height: Optional[int] = None
    color_space: Optional[str] = None
    bit_depth: Optional[int] = None
    fps: Optional[float] = None
    duration: Optional[float] = None
    
    # Versioning
    version: Optional[int] = None
    
    # User metadata
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    rating: int = 0  # 0-5 stars
    
    # Thumbnail
    thumbnail_path: Optional[str] = None
    
    # Status
    is_missing: bool = False
    last_verified: Optional[float] = None
    
    # Timestamps
    added_time: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self):
        """Convert to dictionary for database storage"""
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
            'missing_frames': self.missing_frames,
            'sequence_path': self.sequence_path,
            'resolution_width': self.resolution_width,
            'resolution_height': self.resolution_height,
            'color_space': self.color_space,
            'bit_depth': self.bit_depth,
            'fps': self.fps,
            'duration': self.duration,
            'version': self.version,
            'notes': self.notes,
            'rating': self.rating,
            'thumbnail_path': self.thumbnail_path,
            'is_missing': self.is_missing,
            'last_verified': self.last_verified,
            'added_time': self.added_time,
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create AssetModel from dictionary"""
        import json
        
        # Make a copy to avoid modifying original
        data_copy = dict(data)
        
        # Convert JSON strings back to Python objects
        if 'tags' in data_copy and isinstance(data_copy['tags'], str):
            try:
                data_copy['tags'] = json.loads(data_copy['tags'])
            except (json.JSONDecodeError, TypeError):
                data_copy['tags'] = []
        
        if 'missing_frames' in data_copy and isinstance(data_copy['missing_frames'], str):
            try:
                # Try to parse as JSON array first
                parsed = json.loads(data_copy['missing_frames'])
                data_copy['missing_frames'] = json.dumps(parsed)
            except (json.JSONDecodeError, TypeError):
                data_copy['missing_frames'] = "[]"
        
        return cls(**data_copy)


@dataclass
class FolderModel:
    """Data model for a watched folder"""
    
    id: Optional[int] = None
    path: str = ""
    name: str = ""
    is_active: bool = True
    recursive: bool = True
    auto_scan: bool = True
    last_scanned: Optional[float] = None
    asset_count: int = 0
    added_time: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self):
        """Convert to dictionary for database storage"""
        return {
            'id': self.id,
            'path': self.path,
            'name': self.name,
            'is_active': self.is_active,
            'recursive': self.recursive,
            'auto_scan': self.auto_scan,
            'last_scanned': self.last_scanned,
            'asset_count': self.asset_count,
            'added_time': self.added_time,
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create FolderModel from dictionary"""
        return cls(**data)


@dataclass
class TagModel:
    """Data model for a tag"""
    
    id: Optional[int] = None
    name: str = ""
    color: str = "#888888"  # Hex color for UI
    asset_count: int = 0
    created_time: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self):
        """Convert to dictionary for database storage"""
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'asset_count': self.asset_count,
            'created_time': self.created_time,
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create TagModel from dictionary"""
        return cls(**data)
