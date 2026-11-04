"""
Utility functions for Asset Manager
"""

import os
import re
import hashlib
import json
import subprocess
import shutil
from datetime import datetime
from .log import log

# Hide the console window that every ffprobe/ffmpeg call opens on Windows
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def get_file_hash(filepath):
    """Generate MD5 hash of file path for unique identification"""
    return hashlib.md5(filepath.encode()).hexdigest()


def format_file_size(size_bytes):
    """Convert bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_timestamp(timestamp):
    """Convert timestamp to readable date string"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


_SEQUENCE_RE = re.compile(r"^(.+?)([._])(\d{3,})\.(\w+)$")


def detect_sequence(filepath):
    """
    Detect a frame number at the end of a file name.
    Returns (base_name, frame_number, extension, frame_pattern, padding) or None

    The separator before the frame number is KEPT (the old version always
    used "." - "fire_0001.png" became "fire.%04d.png", a path that doesn't
    exist, so the Read node pointed at nothing):
        render.0001.exr   -> render.%04d.exr
        fire_0001.png     -> fire_%04d.png
        shot_010_1001.exr -> shot_010_%04d.exr
    """
    match = _SEQUENCE_RE.match(os.path.basename(filepath))
    if not match:
        return None
    base_name, sep, digits, extension = match.groups()
    padding = len(digits)
    frame_pattern = f"{base_name}{sep}%0{padding}d.{extension}"
    return (base_name, int(digits), extension, frame_pattern, padding)


def find_sequence_range(directory, base_pattern, padding=None):
    """
    Frames in `directory` whose name matches `base_pattern` (e.g. fire_%04d.png).
    Returns (first_frame, last_frame, missing_frames, frame_count)
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return None, None, [], 0

    frames = []
    for name in names:
        info = detect_sequence(name)
        if info and info[3] == base_pattern:
            frames.append(info[1])

    if not frames:
        return None, None, [], 0

    frames.sort()
    first_frame, last_frame = frames[0], frames[-1]
    missing = sorted(set(range(first_frame, last_frame + 1)) - set(frames))
    return first_frame, last_frame, missing, len(frames)


def get_sequence_info(filepath):
    """
    Complete information about an image sequence.
    A file is only a sequence if at least 2 frames exist - a single image
    with a number in its name (IMG_4521.JPG, brick_2048.jpg) stays a
    normal file with its real name.
    """
    single = {
        "is_sequence": False,
        "first_frame": None,
        "last_frame": None,
        "frame_count": 1,
        "missing_frames": [],
        "sequence_path": filepath,
    }

    seq_detect = detect_sequence(filepath)
    if not seq_detect:
        return single

    base_name, frame_num, extension, frame_pattern, padding = seq_detect
    directory = os.path.dirname(filepath)
    first_frame, last_frame, missing_frames, found = find_sequence_range(directory, frame_pattern)

    if found < 2:
        return single

    return {
        "is_sequence": True,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "frame_count": found,
        "missing_frames": missing_frames,
        "sequence_path": os.path.join(directory, frame_pattern),
        "padding": padding,
    }


def detect_version(filepath):
    """
    Detect version number in filepath
    Returns version number or None
    
    Examples:
        shot_010_v002.exr -> 2
        render_v12.mov -> 12
        plate.v001.dpx -> 1
    """
    patterns = [
        r"[vV](\d{3,})",  # v001, V002
        r"[vV](\d{2})",   # v12, V01
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filepath)
        if match:
            return int(match.group(1))
    
    return None


def get_color_space_from_exr(filepath):
    """
    Try to detect color space from EXR metadata
    This is a placeholder - actual implementation would use OpenEXR library
    """
    # TODO: Implement with OpenEXR when available in Nuke
    # For now, return common defaults based on naming
    filename = os.path.basename(filepath).lower()
    
    if 'linear' in filename or 'lin' in filename:
        return 'linear'
    elif 'srgb' in filename or 'sRGB' in filename:
        return 'sRGB'
    elif 'log' in filename or 'cineon' in filename:
        return 'Cineon'
    elif 'raw' in filename:
        return 'raw'
    else:
        return 'linear'  # Default for EXR


def sanitize_filename(filename):
    """Remove or replace invalid characters from filename"""
    # Replace invalid characters with underscore
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename


def get_relative_path(filepath, base_path):
    """Get relative path from base_path to filepath"""
    try:
        return os.path.relpath(filepath, base_path)
    except ValueError:
        # Different drives on Windows
        return filepath


def is_file_accessible(filepath):
    """Check if file exists and is accessible"""
    return os.path.exists(filepath) and os.access(filepath, os.R_OK)


def get_video_metadata(filepath):
    """
    Extract video metadata using ffprobe and ffmpeg as fallback
    Tries multiple methods to get accurate duration and frame count
    
    Args:
        filepath: Path to video file
    
    Returns:
        dict with keys:
            - duration: float (seconds)
            - fps: float (frames per second)
            - width: int
            - height: int
            - first_frame: int (1)
            - last_frame: int (calculated from duration * fps)
            - codec: str
            - total_frames: int (from nb_frames if available)
    """
    log.debug(f"\n[get_video_metadata] ===== START VIDEO ANALYSIS =====")
    log.debug(f"[get_video_metadata] File: {filepath}")
    log.debug(f"[get_video_metadata] File size: {os.path.getsize(filepath)} bytes")
    log.debug(f"[get_video_metadata] File exists: {os.path.exists(filepath)}")
    log.debug(f"[get_video_metadata] File readable: {os.access(filepath, os.R_OK)}")
    
    # Check if ffprobe is available
    ffprobe_cmd = shutil.which("ffprobe")
    ffmpeg_cmd = shutil.which("ffmpeg")
    
    if not ffprobe_cmd:
        # Try local bin directory (in .nuke/Asset Manager/bin/)
        module_dir = os.path.dirname(os.path.abspath(__file__))
        bin_path = os.path.join(module_dir, 'bin', 'ffprobe.exe')
        log.debug(f"[get_video_metadata] Checking for ffprobe at: {bin_path}")
        if os.path.exists(bin_path):
            ffprobe_cmd = bin_path
            log.debug(f"[get_video_metadata] ✓ Found local ffprobe: {ffprobe_cmd}")
        else:
            log.warning(f"[get_video_metadata] ✗ ffprobe not found at {bin_path}")
    else:
        log.debug(f"[get_video_metadata] ✓ Using system ffprobe: {ffprobe_cmd}")
    
    if not ffmpeg_cmd:
        # Try local bin directory
        module_dir = os.path.dirname(os.path.abspath(__file__))
        bin_path = os.path.join(module_dir, 'bin', 'ffmpeg.exe')
        if os.path.exists(bin_path):
            ffmpeg_cmd = bin_path
            log.debug(f"[get_video_metadata] ✓ Found local ffmpeg: {ffmpeg_cmd}")
        else:
            log.debug(f"[get_video_metadata] Note: ffmpeg not found at {bin_path}")
    else:
        log.debug(f"[get_video_metadata] ✓ Using system ffmpeg: {ffmpeg_cmd}")
    
    # Fallback if no fftools available
    if not ffprobe_cmd and not ffmpeg_cmd:
        log.warning(f"[get_video_metadata] ✗ Neither ffprobe nor ffmpeg found!")
        log.debug(f"[get_video_metadata] ===== END VIDEO ANALYSIS (FAILED - no fftools) =====\n")
        return None
    
    try:
        metadata = {}
        
        # FIRST ATTEMPT: ffprobe with JSON output
        if ffprobe_cmd:
            log.debug(f"[get_video_metadata] >> Attempt 1: ffprobe with JSON...")
            try:
                cmd = [
                    ffprobe_cmd,
                    '-v', 'error',
                    '-print_format', 'json',
                    '-show_format',
                    '-show_streams',
                    filepath
                ]
                
                log.debug(f"[get_video_metadata] Command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
                log.debug(f"[get_video_metadata] Return code: {result.returncode}")
                
                if result.returncode == 0 and result.stdout:
                    log.debug(f"[get_video_metadata] ✓ ffprobe returned data")
                    data = json.loads(result.stdout)
                    
                    # Find video stream
                    video_stream = None
                    for stream in data.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            video_stream = stream
                            break
                    
                    if video_stream:
                        log.debug(f"[get_video_metadata] ✓ Found video stream")
                        
                        # Duration
                        duration = None
                        if 'duration' in video_stream and video_stream['duration']:
                            duration = float(video_stream['duration'])
                        elif 'duration' in data.get('format', {}):
                            duration = float(data['format']['duration'])
                        
                        # FPS
                        fps = None
                        fps_str = video_stream.get('r_frame_rate', '')
                        if '/' in fps_str:
                            num, den = fps_str.split('/')
                            fps = float(num) / float(den)
                        elif fps_str:
                            try:
                                fps = float(fps_str)
                            except:
                                pass
                        
                        # Resolution
                        width = video_stream.get('width')
                        height = video_stream.get('height')
                        codec = video_stream.get('codec_name')
                        
                        # Frame count
                        nb_frames = None
                        if 'nb_frames' in video_stream and video_stream['nb_frames']:
                            try:
                                nb_frames = int(video_stream['nb_frames'])
                            except:
                                pass
                        
                        log.debug(f"[get_video_metadata] Duration: {duration}s, FPS: {fps}, NB_Frames: {nb_frames}, Resolution: {width}x{height}")
                        
                        metadata['duration'] = duration
                        metadata['fps'] = fps
                        metadata['width'] = width
                        metadata['height'] = height
                        metadata['codec'] = codec
                        if nb_frames:
                            metadata['total_frames'] = nb_frames
                    else:
                        log.warning(f"[get_video_metadata] ✗ No video stream found")
                else:
                    log.warning(f"[get_video_metadata] ✗ ffprobe failed (return code: {result.returncode})")
                    if result.stderr:
                        log.warning(f"[get_video_metadata] Error: {result.stderr[:200]}")
            
            except Exception as e:
                log.warning(f"[get_video_metadata] ✗ Attempt 1 exception: {e}")
        
        # SECOND ATTEMPT: ffmpeg -i (text output parsing)
        if ffmpeg_cmd and not metadata.get('fps'):
            log.debug(f"[get_video_metadata] >> Attempt 2: ffmpeg -i (text parsing)...")
            try:
                cmd = [ffmpeg_cmd, '-i', filepath]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
                output = result.stderr  # ffmpeg outputs to stderr
                log.debug(f"[get_video_metadata] ffmpeg output length: {len(output)} chars")
                
                # Parse "Duration: HH:MM:SS.ms"
                duration_match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', output)
                if duration_match:
                    hours = int(duration_match.group(1))
                    minutes = int(duration_match.group(2))
                    seconds = float(duration_match.group(3))
                    duration = hours * 3600 + minutes * 60 + seconds
                    metadata['duration'] = duration
                    log.debug(f"[get_video_metadata] ✓ Duration from ffmpeg: {duration}s")
                
                # Parse "Video: codec ... X fps"
                fps_match = re.search(r'(\d+\.?\d*)\s*fps', output)
                if fps_match:
                    fps = float(fps_match.group(1))
                    metadata['fps'] = fps
                    log.debug(f"[get_video_metadata] ✓ FPS from ffmpeg: {fps}")
                
                # Parse resolution "WIDTHxHEIGHT"
                res_match = re.search(r'(\d{3,4})x(\d{3,4})', output)
                if res_match:
                    metadata['width'] = int(res_match.group(1))
                    metadata['height'] = int(res_match.group(2))
                    log.debug(f"[get_video_metadata] ✓ Resolution from ffmpeg: {metadata['width']}x{metadata['height']}")
                
                # Parse codec
                codec_match = re.search(r'Video: ([^\s,]+)', output)
                if codec_match:
                    metadata['codec'] = codec_match.group(1)
                    log.debug(f"[get_video_metadata] ✓ Codec from ffmpeg: {metadata['codec']}")
            
            except Exception as e:
                log.warning(f"[get_video_metadata] ✗ Attempt 2 exception: {e}")
        
        # THIRD ATTEMPT: Frame counting with ffprobe (decodes the whole file -
        # slow on big clips). Only when duration*fps can't give the range.
        if ffprobe_cmd and not metadata.get('total_frames') and not (metadata.get('duration') and metadata.get('fps')):
            log.debug(f"[get_video_metadata] >> Attempt 3: ffprobe frame counting...")
            try:
                cmd = [
                    ffprobe_cmd,
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-count_frames',
                    '-show_entries', 'stream=nb_read_frames',
                    '-print_format', 'json',
                    filepath
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    if data.get('streams') and len(data['streams']) > 0:
                        nb_read = data['streams'][0].get('nb_read_frames')
                        if nb_read:
                            try:
                                metadata['total_frames'] = int(nb_read)
                                log.debug(f"[get_video_metadata] ✓ Total frames from frame count: {metadata['total_frames']}")
                            except:
                                pass
            except Exception as e:
                log.warning(f"[get_video_metadata] ✗ Attempt 3 exception: {e}")
        
        # Calculate frame range
        log.debug(f"[get_video_metadata] >> Calculating frame range...")
        log.debug(f"[get_video_metadata] Available metadata: duration={metadata.get('duration')}, fps={metadata.get('fps')}, total_frames={metadata.get('total_frames')}")
        
        metadata['first_frame'] = 1
        metadata['last_frame'] = 1
        
        # Priority 1: Use nb_frames/total_frames
        if metadata.get('total_frames') and metadata['total_frames'] > 1:
            metadata['last_frame'] = metadata['total_frames']
            log.debug(f"[get_video_metadata] ✓ Frame range from total_frames: 1-{metadata['last_frame']}")
        
        # Priority 2: Calculate from duration * fps
        elif metadata.get('duration') and metadata.get('fps') and metadata['duration'] > 0 and metadata['fps'] > 0:
            calculated_frames = int(round(metadata['duration'] * metadata['fps']))
            if calculated_frames > 1:
                metadata['last_frame'] = calculated_frames
                log.debug(f"[get_video_metadata] ✓ Frame range from duration*fps: 1-{metadata['last_frame']}")
            else:
                log.debug(f"[get_video_metadata] ⚠ Calculated frames too small: {calculated_frames}")
        
        else:
            log.warning(f"[get_video_metadata] ✗ Could not calculate frame range")
        
        log.debug(f"[get_video_metadata] ===== FINAL RESULT =====")
        log.debug(f"[get_video_metadata] Duration: {metadata.get('duration')}s")
        log.debug(f"[get_video_metadata] FPS: {metadata.get('fps')}")
        log.debug(f"[get_video_metadata] Frame Range: {metadata['first_frame']}-{metadata['last_frame']}")
        log.debug(f"[get_video_metadata] Resolution: {metadata.get('width')}x{metadata.get('height')}")
        log.debug(f"[get_video_metadata] ===== END VIDEO ANALYSIS (SUCCESS) =====\n")
        
        return metadata
        
    except subprocess.TimeoutExpired:
        log.warning(f"[get_video_metadata] ✗ Command timed out")
        log.debug(f"[get_video_metadata] ===== END VIDEO ANALYSIS (TIMEOUT) =====\n")
        return None
        
    except Exception as e:
        log.warning(f"[get_video_metadata] ✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        log.debug(f"[get_video_metadata] ===== END VIDEO ANALYSIS (EXCEPTION) =====\n")
        return None


def get_video_frame_count_fallback(filepath):
    """
    Get frame count from video file using multiple fallback methods
    This is called when normal frame detection fails
    
    Returns:
        int (number of frames) or None
    """
    log.debug(f"\n[get_video_frame_count_fallback] ===== FRAME COUNT DETECTION =====")
    log.debug(f"[get_video_frame_count_fallback] File: {filepath}")
    
    ffprobe_cmd = shutil.which("ffprobe")
    if not ffprobe_cmd:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        bin_path = os.path.join(module_dir, 'bin', 'ffprobe.exe')
        if os.path.exists(bin_path):
            ffprobe_cmd = bin_path
        else:
            log.warning(f"[get_video_frame_count_fallback] ✗ ffprobe not available")
            log.debug(f"[get_video_frame_count_fallback] ===== END =====\n")
            return None
    
    # Method 1: Use ffprobe with frame counting
    log.debug(f"[get_video_frame_count_fallback] Method 1: ffprobe with -count_frames...")
    try:
        cmd = [
            ffprobe_cmd,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-count_frames',
            '-show_entries', 'stream=nb_read_frames',
            '-print_format', 'json',
            filepath
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('streams') and len(data['streams']) > 0:
                nb_frames = data['streams'][0].get('nb_read_frames')
                if nb_frames:
                    try:
                        frame_count = int(nb_frames)
                        log.debug(f"[get_video_frame_count_fallback] ✓ Method 1 SUCCESS: {frame_count} frames")
                        log.debug(f"[get_video_frame_count_fallback] ===== END =====\n")
                        return frame_count
                    except:
                        pass
    except Exception as e:
        log.warning(f"[get_video_frame_count_fallback] Method 1 failed: {e}")
    
    # Method 2: Get duration and fps, calculate frames
    log.debug(f"[get_video_frame_count_fallback] Method 2: Calculate from duration*fps...")
    try:
        cmd = [
            ffprobe_cmd,
            '-v', 'error',
            '-show_entries', 'format=duration,stream=r_frame_rate',
            '-select_streams', 'v:0',
            '-print_format', 'json',
            filepath
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            
            duration = None
            if data.get('format') and data['format'].get('duration'):
                duration = float(data['format']['duration'])
            
            fps = None
            if data.get('streams') and len(data['streams']) > 0:
                fps_str = data['streams'][0].get('r_frame_rate', '')
                if '/' in fps_str:
                    num, den = fps_str.split('/')
                    fps = float(num) / float(den)
                else:
                    try:
                        fps = float(fps_str)
                    except:
                        pass
            
            if duration and fps and fps > 0:
                frame_count = int(round(duration * fps))
                log.debug(f"[get_video_frame_count_fallback] ✓ Method 2 SUCCESS: calculated {frame_count} frames (duration={duration}s, fps={fps})")
                log.debug(f"[get_video_frame_count_fallback] ===== END =====\n")
                return frame_count
            else:
                log.debug(f"[get_video_frame_count_fallback] Method 2: duration={duration}, fps={fps}")
    except Exception as e:
        log.warning(f"[get_video_frame_count_fallback] Method 2 failed: {e}")
    
    # Method 3: Try quicktime atoms (for .mov files)
    log.debug(f"[get_video_frame_count_fallback] Method 3: QuickTime atoms (MOV files)...")
    try:
        if filepath.lower().endswith('.mov'):
            # Try to read MOV header directly
            cmd = [
                ffprobe_cmd,
                '-v', 'error',
                '-show_entries', 'stream=nb_frames',
                '-select_streams', 'v:0',
                '-print_format', 'json',
                filepath
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get('streams') and len(data['streams']) > 0:
                    nb_frames = data['streams'][0].get('nb_frames')
                    if nb_frames:
                        try:
                            frame_count = int(nb_frames)
                            log.debug(f"[get_video_frame_count_fallback] ✓ Method 3 SUCCESS: {frame_count} frames from MOV atoms")
                            log.debug(f"[get_video_frame_count_fallback] ===== END =====\n")
                            return frame_count
                        except:
                            pass
    except Exception as e:
        log.warning(f"[get_video_frame_count_fallback] Method 3 failed: {e}")
    
    log.warning(f"[get_video_frame_count_fallback] ✗ All methods failed to detect frame count")
    log.debug(f"[get_video_frame_count_fallback] ===== END =====\n")
    return None


def get_nuke_main_window():
    """
    Get Nuke's main window QWidget
    
    Returns:
        QMainWindow or None
    """
    try:
        from PySide2 import QtWidgets
    except ImportError:
        try:
            from PySide6 import QtWidgets
        except ImportError:
            return None
    
    app = QtWidgets.QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if widget.objectName() == 'NukeMainWindow' or 'Nuke' in widget.windowTitle():
                return widget
    
    return None
