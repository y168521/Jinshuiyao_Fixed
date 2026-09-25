# -*- coding: utf-8 -*-
"""FFmpeg 操作：视频转音频、格式转换、元数据、裁剪拼接、信息获取"""
import os
import json
import time
import logging
import subprocess
import tempfile

from ._core import FFMPEG_PATH, FORMATS, _run_ffmpeg

logger = logging.getLogger(__name__)


def _run_with_progress(cmd, progress_callback, start_time):
    """执行带进度回调的 FFmpeg 命令，返回 (success, output_path, elapsed, error_msg)。

    video_to_audio 与 convert_audio 共享此进度追踪循环。
    """
    try:
        process = _run_ffmpeg(cmd)
        duration = 0
        while True:
            line = process.stderr.readline().decode("utf-8", errors="replace").strip()
            if not line and process.poll() is not None:
                break
            if "Duration:" in line and duration == 0:
                try:
                    dur_str = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = dur_str.split(":")
                    duration = int(h) * 3600 + int(m) * 60 + float(s)
                except Exception as _e:
                    logger.debug("parse duration failed: %s", _e)
            if "time=" in line and duration > 0 and progress_callback:
                try:
                    time_str = line.split("time=")[1].split(" ")[0].strip()
                    h, m, s = time_str.split(":")
                    current = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(95, int((current / duration) * 90) + 10)
                    progress_callback(pct, f"转换中 {pct}%")
                except Exception as _e:
                    logger.debug("parse time failed: %s", _e)
        process.wait()
        elapsed = time.time() - start_time
        return process.returncode == 0, elapsed, None
    except Exception as e:
        return False, time.time() - start_time, str(e)


def video_to_audio(video_path, output_dir, format_name, progress_callback=None):
    """视频转音频"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}
    fmt = FORMATS.get(format_name)
    if not fmt:
        return {"success": False, "error": f"不支持的格式: {format_name}"}

    basename = os.path.splitext(os.path.basename(video_path))[0]
    output_path = os.path.join(output_dir, basename + fmt["ext"])
    counter = 1
    while os.path.exists(output_path):
        output_path = os.path.join(output_dir, f"{basename}_{counter}{fmt['ext']}")
        counter += 1

    start_time = time.time()
    cmd = [FFMPEG_PATH, "-i", video_path, "-vn", "-c:a", fmt["codec"],
           *fmt["args"], "-y", output_path]

    ok, elapsed, err = _run_with_progress(cmd, progress_callback, start_time)
    if ok and os.path.exists(output_path):
        if progress_callback:
            progress_callback(100, "完成")
        return {"success": True, "output": output_path, "time": elapsed,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024)}
    if err:
        return {"success": False, "error": err, "time": elapsed}
    return {"success": False, "error": "转换失败", "time": elapsed}


def convert_audio(input_path, output_dir, format_name, progress_callback=None):
    """音频格式互转（音频→音频）"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}
    fmt = FORMATS.get(format_name)
    if not fmt:
        return {"success": False, "error": f"不支持的格式: {format_name}"}

    basename = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, basename + fmt["ext"])
    counter = 1
    while os.path.exists(output_path):
        output_path = os.path.join(output_dir, f"{basename}_{counter}{fmt['ext']}")
        counter += 1

    start_time = time.time()
    cmd = [FFMPEG_PATH, "-i", input_path, "-c:a", fmt["codec"],
           *fmt["args"], "-y", output_path]

    ok, elapsed, err = _run_with_progress(cmd, progress_callback, start_time)
    if ok and os.path.exists(output_path):
        if progress_callback:
            progress_callback(100, "完成")
        return {"success": True, "output": output_path, "time": elapsed,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024)}
    if err:
        return {"success": False, "error": err, "time": elapsed}
    return {"success": False, "error": "转换失败", "time": elapsed}


def read_metadata(filepath):
    """读取音频文件的元数据"""
    try:
        from mutagen import File
        f = File(filepath, easy=True)
        if f is None:
            return {}
        info = {
            "title": f.get("title", "") or "",
            "artist": f.get("artist", "") or "",
            "album": f.get("album", "") or "",
            "year": f.get("date", "") or "",
            "genre": f.get("genre", "") or "",
            "track": f.get("tracknumber", "") or "",
            "comment": f.get("comment", "") or "",
        }
        for k in list(info.keys()):
            if isinstance(info[k], list):
                info[k] = info[k][0] if info[k] else ""
        return info
    except Exception as e:
        return {"error": str(e)}


def write_metadata(filepath, title=None, artist=None, album=None,
                   year=None, genre=None, track=None, comment=None):
    """写入音频文件的元数据"""
    try:
        from mutagen import File
        f = File(filepath, easy=True)
        if f is None:
            return {"success": False, "error": "无法读取文件"}
        if title is not None:
            f["title"] = title
        if artist is not None:
            f["artist"] = artist
        if album is not None:
            f["album"] = album
        if year is not None:
            f["date"] = str(year)
        if genre is not None:
            f["genre"] = genre
        if track is not None:
            f["tracknumber"] = str(track)
        if comment is not None:
            f["comment"] = comment
        f.save()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def trim_audio(input_path, output_dir, start_sec, end_sec, output_format=None):
    """裁剪音频片段"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}

    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
    else:
        ext = os.path.splitext(input_path)[1] or ".mp3"

    basename = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{basename}_clip_{start_sec}s-{end_sec}s{ext}")

    duration = end_sec - start_sec
    cmd = [FFMPEG_PATH, "-i", input_path, "-ss", str(start_sec),
           "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "320k",
           "-y", output_path]

    start_time = time.time()
    try:
        process = _run_ffmpeg(cmd)
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            return {"success": True, "output": output_path, "time": elapsed,
                    "size_mb": os.path.getsize(output_path) / (1024 * 1024),
                    "duration_sec": duration}
        return {"success": False, "error": "裁剪失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e)}


def concat_audio(file_list, output_dir, output_name="merged", output_format=None):
    """拼接多个音频文件"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}
    if len(file_list) < 2:
        return {"success": False, "error": "至少需要2个文件"}

    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
        codec = fmt["codec"] if fmt else "libmp3lame"
        args = fmt.get("args", []) if fmt else ["-b:a", "320k"]
    else:
        ext, codec, args = ".mp3", "libmp3lame", ["-b:a", "320k"]

    tmp_list = os.path.join(tempfile.gettempdir(), "concat_list.txt")
    try:
        with open(tmp_list, "w", encoding="utf-8") as f:
            for fp in file_list:
                f.write(f"file '{fp.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")

        output_path = os.path.join(output_dir, f"{output_name}{ext}")
        cmd = [FFMPEG_PATH, "-f", "concat", "-safe", "0", "-i", tmp_list,
               "-c:a", codec, *args, "-y", output_path]

        start_time = time.time()
        process = _run_ffmpeg(cmd)
        process.wait()
        elapsed = time.time() - start_time

        if process.returncode == 0 and os.path.exists(output_path):
            return {"success": True, "output": output_path, "time": elapsed,
                    "size_mb": os.path.getsize(output_path) / (1024 * 1024)}
        return {"success": False, "error": "拼接失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(tmp_list):
            try:
                os.remove(tmp_list)
            except Exception as _e:
                logger.debug("remove tmp list failed: %s", _e)


def get_audio_info(filepath):
    """获取音频/视频文件的详细信息"""
    info = {"path": filepath, "filename": os.path.basename(filepath),
            "size_mb": 0, "duration": 0, "has_audio": False}
    try:
        info["size_mb"] = os.path.getsize(filepath) / (1024 * 1024)
    except Exception as _e:
        logger.debug("getsize failed: %s", _e)

    ffprobe = FFMPEG_PATH.replace("ffmpeg", "ffprobe") if FFMPEG_PATH else "ffprobe"
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", filepath],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if "format" in data:
                if "duration" in data["format"]:
                    info["duration"] = float(data["format"]["duration"])
                if "bit_rate" in data["format"]:
                    info["bitrate"] = int(data["format"]["bit_rate"]) / 1000
            for s in data.get("streams", []):
                if s.get("codec_type") == "audio":
                    info["has_audio"] = True
                    info["sample_rate"] = s.get("sample_rate", "?")
                    info["channels"] = s.get("channels", "?")
                    info["audio_codec"] = s.get("codec_name", "?")
    except Exception as _e:
        logger.debug("ffprobe info failed: %s", _e)
    return info


def format_duration(seconds):
    if seconds <= 0:
        return "未知"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
