"""
Database Manager for Asset Manager
Handles all SQLite database operations with proper connection management
"""

import sqlite3
import json
import os
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from ..config import DATABASE_PATH
from .models import AssetModel, FolderModel, TagModel
from ..log import log


class DatabaseManager:
    """
    Manages SQLite database for asset library
    
    Features:
    - Thread-safe operations
    - Automatic schema migration
    - Efficient querying with indexes
    - Transaction support
    """
    
    def __init__(self, db_path=None):
        """
        Initialize database manager
        
        Args:
            db_path: Path to SQLite database file (uses default if None)
        """
        self.db_path = db_path or DATABASE_PATH
        self._ensure_database_exists()
        self._create_indexes()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _ensure_database_exists(self):
        """Create database and tables if they don't exist"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Assets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER,
                    file_type TEXT,
                    extension TEXT,
                    modified_time REAL,
                    created_time REAL,
                    category TEXT,
                    folder_id INTEGER,
                    is_sequence BOOLEAN,
                    first_frame INTEGER,
                    last_frame INTEGER,
                    frame_count INTEGER,
                    missing_frames TEXT,
                    sequence_path TEXT,
                    resolution_width INTEGER,
                    resolution_height INTEGER,
                    color_space TEXT,
                    bit_depth INTEGER,
                    fps REAL,
                    duration REAL,
                    version INTEGER,
                    tags TEXT DEFAULT '[]',
                    notes TEXT,
                    rating INTEGER DEFAULT 0,
                    thumbnail_path TEXT,
                    is_missing BOOLEAN DEFAULT 0,
                    last_verified REAL,
                    added_time REAL,
                    FOREIGN KEY (folder_id) REFERENCES folders (id)
                )
            """)
            
            # Folders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    recursive BOOLEAN DEFAULT 1,
                    auto_scan BOOLEAN DEFAULT 1,
                    last_scanned REAL,
                    asset_count INTEGER DEFAULT 0,
                    added_time REAL
                )
            """)
            
            # Tags table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#888888',
                    asset_count INTEGER DEFAULT 0,
                    created_time REAL
                )
            """)
            
            # Asset-Tag junction table (many-to-many)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS asset_tags (
                    asset_id INTEGER,
                    tag_id INTEGER,
                    PRIMARY KEY (asset_id, tag_id),
                    FOREIGN KEY (asset_id) REFERENCES assets (id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
                )
            """)
            
            # Migration: Add tags column if it doesn't exist
            cursor.execute("PRAGMA table_info(assets)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'tags' not in columns:
                cursor.execute("ALTER TABLE assets ADD COLUMN tags TEXT DEFAULT '[]'")
                log.debug("Added 'tags' column to assets table")
            
            conn.commit()
    
    def _create_indexes(self):
        """Create indexes for faster queries"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Index on frequently searched columns
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_filename ON assets(filename)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_category ON assets(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_extension ON assets(extension)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_folder_id ON assets(folder_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_is_sequence ON assets(is_sequence)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_rating ON assets(rating)")
            
            conn.commit()
    
    # ==================== ASSET OPERATIONS ====================
    
    def add_asset(self, asset: AssetModel) -> int:
        """
        Add a new asset to the database
        
        Args:
            asset: AssetModel instance
        
        Returns:
            Asset ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            asset_dict = asset.to_dict()
            asset_dict.pop('id', None)  # Remove id, will be auto-generated
            
            columns = ', '.join(asset_dict.keys())
            placeholders = ', '.join(['?' for _ in asset_dict])
            
            cursor.execute(
                f"INSERT INTO assets ({columns}) VALUES ({placeholders})",
                list(asset_dict.values())
            )
            
            return cursor.lastrowid
    
    def update_asset(self, asset_id: int, updates: Dict[str, Any]) -> bool:
        """
        Update an existing asset
        
        Args:
            asset_id: Asset ID
            updates: Dictionary of fields to update
        
        Returns:
            True if successful
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values()) + [asset_id]
            
            cursor.execute(
                f"UPDATE assets SET {set_clause} WHERE id = ?",
                values
            )
            
            return cursor.rowcount > 0
    
    def get_asset(self, asset_id: int) -> Optional[AssetModel]:
        """Get asset by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE id = ?", (asset_id,))
            row = cursor.fetchone()
            
            if row:
                return AssetModel.from_dict(dict(row))
            return None
    
    def get_asset_by_path(self, filepath: str) -> Optional[AssetModel]:
        """Get asset by filepath"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE filepath = ?", (filepath,))
            row = cursor.fetchone()
            
            if row:
                return AssetModel.from_dict(dict(row))
            return None
    
    def delete_asset(self, asset_id: int) -> bool:
        """Delete an asset"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            return cursor.rowcount > 0
    
    def search_assets(self, 
                     query: str = "", 
                     category: str = None,
                     folder_id: int = None,
                     tags: List[str] = None,
                     extension: str = None,
                     rating_min: int = 0,
                     limit: int = None,
                     offset: int = 0) -> List[AssetModel]:
        """
        Search assets with filters
        
        Args:
            query: Search term for filename
            category: Filter by category
            folder_id: Filter by folder
            tags: Filter by tags (must have all tags)
            extension: Filter by file extension
            rating_min: Minimum rating
            limit: Maximum results
            offset: Result offset for pagination
        
        Returns:
            List of AssetModel instances
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            sql = "SELECT DISTINCT a.* FROM assets a"
            conditions = []
            params = []
            
            # Join with tags if needed
            if tags:
                sql += " INNER JOIN asset_tags at ON a.id = at.asset_id"
                sql += " INNER JOIN tags t ON at.tag_id = t.id"
            
            # Build WHERE clause
            if query:
                conditions.append("(a.filename LIKE ? OR a.notes LIKE ?)")
                search_term = f"%{query}%"
                params.extend([search_term, search_term])
            
            if category:
                conditions.append("a.category = ?")
                params.append(category)
            
            if folder_id is not None:
                conditions.append("a.folder_id = ?")
                params.append(folder_id)
            
            if extension:
                conditions.append("a.extension = ?")
                params.append(extension)
            
            if rating_min > 0:
                conditions.append("a.rating >= ?")
                params.append(rating_min)
            
            if tags:
                conditions.append("t.name IN ({})".format(','.join(['?' for _ in tags])))
                params.extend(tags)
            
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            
            # Add pagination
            if limit:
                sql += f" LIMIT {limit} OFFSET {offset}"
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            return [AssetModel.from_dict(dict(row)) for row in rows]
    
    def get_all_assets(self, limit: int = None) -> List[AssetModel]:
        """Get all assets"""
        return self.search_assets(limit=limit)
    
    # ==================== FOLDER OPERATIONS ====================
    
    def add_folder(self, folder: FolderModel) -> int:
        """Add a watched folder"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            folder_dict = folder.to_dict()
            folder_dict.pop('id', None)
            
            columns = ', '.join(folder_dict.keys())
            placeholders = ', '.join(['?' for _ in folder_dict])
            
            cursor.execute(
                f"INSERT INTO folders ({columns}) VALUES ({placeholders})",
                list(folder_dict.values())
            )
            
            return cursor.lastrowid
    
    def get_folder(self, folder_id: int) -> Optional[FolderModel]:
        """Get folder by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM folders WHERE id = ?", (folder_id,))
            row = cursor.fetchone()
            
            if row:
                return FolderModel.from_dict(dict(row))
            return None
    
    def get_all_folders(self) -> List[FolderModel]:
        """Get all watched folders"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM folders ORDER BY name")
            rows = cursor.fetchall()
            
            return [FolderModel.from_dict(dict(row)) for row in rows]
    
    def update_folder(self, folder_id: int, updates: Dict[str, Any]) -> bool:
        """Update folder settings"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values()) + [folder_id]
            
            cursor.execute(
                f"UPDATE folders SET {set_clause} WHERE id = ?",
                values
            )
            
            return cursor.rowcount > 0
    
    def delete_folder(self, folder_id: int, delete_assets: bool = False) -> bool:
        """
        Delete a folder
        
        Args:
            folder_id: Folder ID
            delete_assets: If True, also delete all assets in this folder
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if delete_assets:
                cursor.execute("DELETE FROM assets WHERE folder_id = ?", (folder_id,))
            else:
                # Just unlink assets from folder
                cursor.execute("UPDATE assets SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
            
            cursor.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
            return cursor.rowcount > 0
    
    # ==================== TAG OPERATIONS ====================
    
    def add_tag(self, tag: TagModel) -> int:
        """Add a new tag"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            tag_dict = tag.to_dict()
            tag_dict.pop('id', None)
            
            columns = ', '.join(tag_dict.keys())
            placeholders = ', '.join(['?' for _ in tag_dict])
            
            cursor.execute(
                f"INSERT INTO tags ({columns}) VALUES ({placeholders})",
                list(tag_dict.values())
            )
            
            return cursor.lastrowid
    
    def get_tag_by_name(self, name: str) -> Optional[TagModel]:
        """Get tag by name"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tags WHERE name = ?", (name,))
            row = cursor.fetchone()
            
            if row:
                return TagModel.from_dict(dict(row))
            return None
    
    def get_all_tags(self) -> List[TagModel]:
        """Get all tags"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tags ORDER BY name")
            rows = cursor.fetchall()
            
            return [TagModel.from_dict(dict(row)) for row in rows]
    
    def add_tag_to_asset(self, asset_id: int, tag_name: str) -> bool:
        """Add a tag to an asset"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get or create tag
            tag = self.get_tag_by_name(tag_name)
            if not tag:
                tag_model = TagModel(name=tag_name)
                tag_id = self.add_tag(tag_model)
            else:
                tag_id = tag.id
            
            # Add relationship
            try:
                cursor.execute(
                    "INSERT INTO asset_tags (asset_id, tag_id) VALUES (?, ?)",
                    (asset_id, tag_id)
                )
                return True
            except sqlite3.IntegrityError:
                # Tag already exists on asset
                return False
    
    def remove_tag_from_asset(self, asset_id: int, tag_name: str) -> bool:
        """Remove a tag from an asset"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM asset_tags 
                WHERE asset_id = ? AND tag_id = (
                    SELECT id FROM tags WHERE name = ?
                )
            """, (asset_id, tag_name))
            
            return cursor.rowcount > 0
    
    def get_asset_tags(self, asset_id: int) -> List[str]:
        """Get all tags for an asset"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT t.name FROM tags t
                INNER JOIN asset_tags at ON t.id = at.tag_id
                WHERE at.asset_id = ?
            """, (asset_id,))
            
            return [row['name'] for row in cursor.fetchall()]
    
    # ==================== STATISTICS ====================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get library statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Total assets
            cursor.execute("SELECT COUNT(*) as count FROM assets")
            total_assets = cursor.fetchone()['count']
            
            # Total size
            cursor.execute("SELECT SUM(file_size) as total FROM assets")
            total_size = cursor.fetchone()['total'] or 0
            
            # Assets by category
            cursor.execute("""
                SELECT category, COUNT(*) as count 
                FROM assets 
                GROUP BY category
            """)
            by_category = {row['category']: row['count'] for row in cursor.fetchall()}
            
            # Missing assets
            cursor.execute("SELECT COUNT(*) as count FROM assets WHERE is_missing = 1")
            missing_assets = cursor.fetchone()['count']
            
            # Sequences
            cursor.execute("SELECT COUNT(*) as count FROM assets WHERE is_sequence = 1")
            sequences = cursor.fetchone()['count']
            
            return {
                'total_assets': total_assets,
                'total_size': total_size,
                'by_category': by_category,
                'missing_assets': missing_assets,
                'sequences': sequences,
            }
    
    def vacuum(self):
        """Optimize database"""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
