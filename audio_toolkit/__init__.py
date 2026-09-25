# -*- coding: utf-8 -*-
"""
音频工具箱 V2.0 - 智能音频处理套件（按职责拆分为子包）

子模块:
  - _core: FFmpeg 路径检测 + 格式常量 + 进程管理
  - ffmpeg_ops: 视频转音频 / 格式转换 / 元数据 / 裁剪拼接 / 信息获取
  - processing: 音量标准化 / 质量分析 / 智能优化
  - gui: tkinter 图形界面

用法:
    import audio_toolkit
    audio_toolkit.run_gui()
    result = audio_toolkit.normalize_loudness("input.mp3")
"""
from ._core import FFMPEG_PATH, FORMATS, VIDEO_EXTS, AUDIO_EXTS, _run_ffmpeg
from .ffmpeg_ops import (
    video_to_audio, convert_audio, read_metadata, write_metadata,
    trim_audio, concat_audio, get_audio_info, format_duration,
)
from .processing import normalize_loudness, analyze_audio, smart_optimize
from .gui import run_gui

__all__ = [
    "FFMPEG_PATH", "FORMATS", "VIDEO_EXTS", "AUDIO_EXTS",
    "video_to_audio", "convert_audio", "read_metadata", "write_metadata",
    "trim_audio", "concat_audio", "get_audio_info", "format_duration",
    "normalize_loudness", "analyze_audio", "smart_optimize", "run_gui",
]

if __name__ == "__main__":
    run_gui()
