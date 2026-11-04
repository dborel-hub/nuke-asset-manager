"""
ThumbnailGenerator - creates and caches thumbnails for assets.

No third-party Python packages: images are read with Qt's QImage (ships with
every Nuke), production formats and video go through ffmpeg in bin/.
Everything here is safe to run from worker threads (QImage, not QPixmap).

Files with nothing to show (3D, LUTs, Nuke scripts) get no thumbnail -
the grid paints the file extension instead.
"""

import os
import sys
import shutil
import hashlib
import subprocess
from typing import Optional

try:
    from PySide2 import QtGui, QtCore
except ImportError:
    from PySide6 import QtGui, QtCore

from ..config import THUMBNAIL_CACHE_DIR, THUMBNAIL_SIZE, THUMBNAIL_QUALITY
from ..log import log

NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

QT_IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.tga')
FFMPEG_STILL_EXT = ('.exr', '.dpx', '.cin', '.tif', '.tiff', '.tga', '.psd', '.hdr')
VIDEO_EXT = ('.mov', '.mp4', '.avi', '.mxf', '.mkv', '.webm', '.m4v')

BACKGROUND = QtGui.QColor(30, 33, 38)   # behind transparent images


def find_tool(name):
    """bin/<name>.exe next to the plugin, else the system PATH."""
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local = os.path.join(plugin_dir, 'bin', name + ('.exe' if sys.platform == 'win32' else ''))
    if os.path.exists(local):
        return local
    return shutil.which(name)


class ThumbnailGenerator:

    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or THUMBNAIL_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        self.thumbnail_size = THUMBNAIL_SIZE
        self._ffmpeg_path = None

    # ------------------------------------------------------------ paths
    def _get_ffmpeg_path(self) -> Optional[str]:
        if not self._ffmpeg_path:
            self._ffmpeg_path = find_tool('ffmpeg')
        return self._ffmpeg_path

    def has_ffmpeg(self) -> bool:
        return bool(self._get_ffmpeg_path())

    def get_thumbnail_path(self, asset_path: str) -> str:
        path_hash = hashlib.md5(asset_path.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{path_hash}.jpg")

    def get_video_preview_path(self, asset_path: str, bucket: int, total_buckets: int) -> str:
        path_hash = hashlib.md5(asset_path.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{path_hash}_pv_{total_buckets}_{bucket}.jpg")

    def has_cached_thumbnail(self, asset_path: str) -> bool:
        return os.path.exists(self.get_thumbnail_path(asset_path))

    @staticmethod
    def can_have_thumbnail(path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        return ext in QT_IMAGE_EXT or ext in FFMPEG_STILL_EXT or ext in VIDEO_EXT

    # ------------------------------------------------------------ main entry
    def generate_thumbnail(self, asset_path: str, force: bool = False,
                           source_path: str = None, seek_seconds: float = None) -> Optional[str]:
        """
        asset_path:   identifies the asset (cache key)
        source_path:  file to read (e.g. the middle frame of a sequence)
        seek_seconds: where to grab a video frame (default: 0.5 s)
        Returns the thumbnail path, or None if this file type has none / failed.
        """
        thumb_path = self.get_thumbnail_path(asset_path)
        if not force and os.path.exists(thumb_path):
            return thumb_path

        src = source_path or asset_path
        ext = os.path.splitext(src)[1].lower()
        try:
            if ext in QT_IMAGE_EXT and self._from_qimage(src, thumb_path):
                return thumb_path
            if ext in FFMPEG_STILL_EXT and self._from_ffmpeg(src, thumb_path, still=True):
                return thumb_path
            if ext in VIDEO_EXT and self._from_ffmpeg(src, thumb_path, still=False,
                                                      seek=seek_seconds):
                return thumb_path
        except Exception as e:
            log.warning("Thumbnail failed for %s: %s", src, e)
        return None

    # ------------------------------------------------------------ Qt images
    def _from_qimage(self, src, thumb_path) -> bool:
        reader = QtGui.QImageReader(src)
        reader.setAutoTransform(True)
        size = reader.size()
        w, h = self.thumbnail_size
        if size.isValid() and (size.width() > w * 2 or size.height() > h * 2):
            # decode at reduced size: much faster for big textures
            reader.setScaledSize(size.scaled(w * 2, h * 2, QtCore.Qt.KeepAspectRatio))
        img = reader.read()
        if img.isNull():
            log.debug("Qt could not read %s: %s", src, reader.errorString())
            return False
        img = img.scaled(w, h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        if img.hasAlphaChannel():
            flat = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
            flat.fill(BACKGROUND)
            p = QtGui.QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        return img.save(thumb_path, 'JPG', THUMBNAIL_QUALITY)

    # ------------------------------------------------------------ ffmpeg
    def _from_ffmpeg(self, src, thumb_path, still, seek=None) -> bool:
        ffmpeg = self._get_ffmpeg_path()
        if not ffmpeg:
            return False
        w, h = self.thumbnail_size
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error']
        if still:
            if src.lower().endswith('.exr'):
                cmd += ['-apply_trc', 'iec61966_2_1']   # linear -> sRGB, not dark
            cmd += ['-i', src]
        else:
            cmd += ['-ss', f"{max(0.0, seek if seek is not None else 0.5):.3f}", '-i', src]
        cmd += ['-frames:v', '1',
                '-vf', f'scale={w}:{h}:force_original_aspect_ratio=decrease',
                '-q:v', '3', '-y', thumb_path]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg timed out on %s", src)
            return False
        if r.returncode == 0 and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return True
        if not still and seek:
            # clip shorter than the seek point: retry at the start
            return self._from_ffmpeg(src, thumb_path, still=False, seek=0.0)
        log.debug("ffmpeg could not read %s: %s", src,
                  r.stderr.decode('utf-8', 'replace').strip()[:200])
        return False

    # ------------------------------------------------------------ hover scrub
    def _strip_marker(self, asset_path, total_buckets):
        path_hash = hashlib.md5(asset_path.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{path_hash}_pv_{total_buckets}.done")

    def has_video_preview_strip(self, asset_path, total_buckets) -> bool:
        return os.path.exists(self._strip_marker(asset_path, total_buckets))

    def generate_video_preview_strip(self, asset_path: str, duration: float,
                                     size: tuple, total_buckets: int) -> bool:
        """
        All hover-scrub frames of a clip in ONE ffmpeg run (the clip is
        decoded once), written as <hash>_pv_<total>_<n>.jpg, n = 0..total-1.
        """
        if self.has_video_preview_strip(asset_path, total_buckets):
            return True
        ffmpeg = self._get_ffmpeg_path()
        if not ffmpeg or not duration or duration <= 0:
            return False
        width, height = size
        path_hash = hashlib.md5(asset_path.encode()).hexdigest()
        pattern = os.path.join(self.cache_dir, f"{path_hash}_pv_{total_buckets}_%d.jpg")
        rate = total_buckets / float(duration)
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', asset_path,
               '-vf', f"fps={rate:.6f},scale={width}:{height}:force_original_aspect_ratio=decrease",
               '-frames:v', str(total_buckets), '-start_number', '0', '-q:v', '4',
               '-y', pattern]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, creationflags=NO_WINDOW)
        except Exception as e:
            log.debug("Preview strip failed for %s: %s", asset_path, e)
            return False
        ok = os.path.exists(self.get_video_preview_path(asset_path, 0, total_buckets))
        if ok:
            open(self._strip_marker(asset_path, total_buckets), 'w').close()
        return ok

    def generate_video_preview_frame(self, asset_path: str, time_seconds: float,
                                     size: tuple, bucket: int, total_buckets: int) -> Optional[str]:
        ffmpeg = self._get_ffmpeg_path()
        if not ffmpeg:
            return None
        output_path = self.get_video_preview_path(asset_path, bucket, total_buckets)
        if os.path.exists(output_path):
            return output_path
        width, height = size
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error',
               '-ss', f"{max(0.0, float(time_seconds)):.3f}", '-i', asset_path,
               '-frames:v', '1',
               '-vf', f"scale={width}:{height}:force_original_aspect_ratio=decrease",
               '-y', output_path]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW)
        except Exception:
            return None
        return output_path if os.path.exists(output_path) else None

    # ------------------------------------------------------------ cache
    def clear_cache(self):
        for name in os.listdir(self.cache_dir):
            try:
                os.unlink(os.path.join(self.cache_dir, name))
            except OSError as e:
                log.warning("Could not delete %s: %s", name, e)

    def get_cache_size(self) -> int:
        return sum(os.path.getsize(os.path.join(self.cache_dir, n))
                   for n in os.listdir(self.cache_dir)
                   if os.path.isfile(os.path.join(self.cache_dir, n)))
