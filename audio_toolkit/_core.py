# -*- coding: utf-8 -*-
"""音频工具箱核心配置：FFmpeg 路径检测 + 格式常量 + 进程管理"""
import os
import sys
import subprocess
import threading

try:
    from config.path_resolver import get_ffmpeg_candidates
    _FFMPEG_CANDIDATES = get_ffmpeg_candidates()
except ImportError:
    _FFMPEG_CANDIDATES = ["ffmpeg"]

FFMPEG_PATH = None
for candidate in _FFMPEG_CANDIDATES:
    try:
        result = subprocess.run([candidate, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            FFMPEG_PATH = candidate
            break
    except Exception:
        continue

FORMATS = {
    "MP3 (320kbps)": {
        "ext": ".mp3", "codec": "libmp3lame", "args": ["-b:a", "320k"],
        "desc": "MP3 高品质 320kbps",
    },
    "WAV (无损)": {
        "ext": ".wav", "codec": "pcm_s16le", "args": ["-ar", "44100", "-ac", "2"],
        "desc": "WAV 无损 PCM 44.1kHz",
    },
    "FLAC (无损)": {
        "ext": ".flac", "codec": "flac", "args": ["-compression_level", "5"],
        "desc": "FLAC 无损压缩",
    },
    "AAC (256kbps)": {
        "ext": ".m4a", "codec": "aac", "args": ["-b:a", "256k", "-ar", "44100"],
        "desc": "AAC 高品质 256kbps",
    },
    "OGG (320kbps)": {
        "ext": ".ogg", "codec": "libvorbis",
        "args": ["-b:a", "320k", "-ar", "44100", "-ac", "2"],
        "desc": "OGG Vorbis 320kbps",
    },
}

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".m4v",
              ".3gp", ".ts", ".mts", ".m2ts", ".vob", ".mpg", ".mpeg", ".rmvb",
              ".rm", ".asf", ".f4v"}

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}


def _run_ffmpeg(cmd, timeout=300):
    """执行FFmpeg命令，返回 subprocess 对象（带超时看门狗）"""
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

    def _timeout_kill():
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    threading.Thread(target=_timeout_kill, daemon=True).start()
    return process
