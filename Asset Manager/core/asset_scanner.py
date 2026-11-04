"""
AssetScanner - Scans directories for assets
Handles multi-threaded scanning with progress reporting
"""

import os
import threading
from typing import List, Callable, Optional
from queue import Queue

from .asset_item import AssetItem
from ..config import SUPPORTED_EXTENSIONS, MAX_CONCURRENT_SCANS
from ..utils import detect_sequence
from ..log import log


class AssetScanner:
    """
    Scans directories for supported assets
    
    Features:
    - Recursive directory scanning
    - Multi-threaded for performance
    - Progress callbacks
    - Sequence detection and grouping
    - Cancellable operations
    """
    
    def __init__(self):
        self.is_scanning = False
        self.cancel_requested = False
        self._scan_thread = None
        self._progress_callback = None
        self._complete_callback = None
        self._scanned_sequences = set()  # Track processed sequences
    
    def scan_directory(self, 
                      directory: str, 
                      recursive: bool = True,
                      progress_callback: Optional[Callable] = None,
                      complete_callback: Optional[Callable] = None) -> List[AssetItem]:
        """
        Scan a directory for assets
        
        Args:
            directory: Path to directory to scan
            recursive: If True, scan subdirectories
            progress_callback: Called with (current, total, filepath)
            complete_callback: Called when scan completes with list of assets
        
        Returns:
            List of AssetItem objects
        """
        if not os.path.exists(directory):
            log.warning(f"Directory not found: {directory}")
            return []
        
        self.is_scanning = True
        self.cancel_requested = False
        self._progress_callback = progress_callback
        self._complete_callback = complete_callback
        self._scanned_sequences = set()
        
        assets = []
        
        try:
            # First pass: collect all files
            all_files = []
            for root, dirs, files in os.walk(directory):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    
                    # Check extension
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        all_files.append(filepath)
                
                if not recursive:
                    break  # Don't descend into subdirectories
            
            total_files = len(all_files)
            
            # Second pass: process files
            for i, filepath in enumerate(all_files):
                if self.cancel_requested:
                    break
                
                # Report progress
                if self._progress_callback:
                    self._progress_callback(i + 1, total_files, filepath)
                
                # Check if this file is part of an already-processed sequence
                seq_info = detect_sequence(filepath)
                if seq_info:
                    base_name, frame_num, ext, pattern, padding = seq_info
                    sequence_key = (os.path.dirname(filepath), pattern)
                    
                    if sequence_key in self._scanned_sequences:
                        continue  # Skip, already processed
                    
                    # Mark this sequence as processed
                    self._scanned_sequences.add(sequence_key)
                
                # Create asset item
                try:
                    asset = AssetItem(filepath)
                    assets.append(asset)
                except Exception as e:
                    log.warning(f"Error processing {filepath}: {e}")
            
            # Call completion callback
            if self._complete_callback:
                self._complete_callback(assets)
        
        finally:
            self.is_scanning = False
            self._scanned_sequences.clear()
        
        return assets
    
    def scan_directory_async(self,
                            directory: str,
                            recursive: bool = True,
                            progress_callback: Optional[Callable] = None,
                            complete_callback: Optional[Callable] = None):
        """
        Scan directory in a background thread
        
        Args:
            directory: Path to directory to scan
            recursive: If True, scan subdirectories
            progress_callback: Called with (current, total, filepath)
            complete_callback: Called when scan completes with list of assets
        """
        if self.is_scanning:
            log.debug("Scan already in progress")
            return
        
        def scan_worker():
            self.scan_directory(
                directory,
                recursive,
                progress_callback,
                complete_callback
            )
        
        self._scan_thread = threading.Thread(target=scan_worker, daemon=True)
        self._scan_thread.start()
    
    def scan_multiple_directories(self,
                                  directories: List[str],
                                  recursive: bool = True,
                                  progress_callback: Optional[Callable] = None,
                                  complete_callback: Optional[Callable] = None) -> List[AssetItem]:
        """
        Scan multiple directories
        
        Args:
            directories: List of directory paths
            recursive: If True, scan subdirectories
            progress_callback: Called with (current, total, filepath)
            complete_callback: Called when all scans complete
        
        Returns:
            Combined list of AssetItem objects
        """
        all_assets = []
        
        for i, directory in enumerate(directories):
            if self.cancel_requested:
                break
            
            assets = self.scan_directory(directory, recursive)
            all_assets.extend(assets)
        
        if self._complete_callback:
            self._complete_callback(all_assets)
        
        return all_assets
    
    def scan_files(self, filepaths: List[str]) -> List[AssetItem]:
        """
        Scan specific files (not directories)
        
        Args:
            filepaths: List of file paths
        
        Returns:
            List of AssetItem objects
        """
        assets = []
        processed_sequences = set()
        
        for filepath in filepaths:
            if not os.path.exists(filepath):
                continue
            
            # Check if part of already-processed sequence
            seq_info = detect_sequence(filepath)
            if seq_info:
                base_name, frame_num, ext, pattern, padding = seq_info
                sequence_key = (os.path.dirname(filepath), pattern)
                
                if sequence_key in processed_sequences:
                    continue
                processed_sequences.add(sequence_key)
            
            try:
                asset = AssetItem(filepath)
                assets.append(asset)
            except Exception as e:
                log.warning(f"Error processing {filepath}: {e}")
        
        return assets
    
    def cancel_scan(self):
        """Request cancellation of current scan"""
        self.cancel_requested = True
    
    def is_busy(self) -> bool:
        """Check if scanner is currently scanning"""
        return self.is_scanning
    
    def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for current scan to complete"""
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_thread.join(timeout)


def scan_for_missing_assets(assets: List[AssetItem]) -> List[AssetItem]:
    """
    Check a list of assets and return those that are missing
    
    Args:
        assets: List of AssetItem objects
    
    Returns:
        List of missing assets
    """
    missing = []
    
    for asset in assets:
        if not asset.verify_exists():
            missing.append(asset)
    
    return missing
