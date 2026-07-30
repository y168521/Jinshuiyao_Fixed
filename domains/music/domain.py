# -*- coding: utf-8 -*-
"""音乐子系统 - 金水谣内核适配层

将 audio_toolkit.py 音频工具箱封装为 DomainBase 标准接口。
核心功能：音频信息提取、格式转换、音量标准化、智能优化、简单旋律生成。

所有实际音频处理复用 audio_toolkit 模块，本模块仅做接口适配和域封装。
"""
import os
import sys
import math
import random
import struct
import wave
import logging
from datetime import datetime

from domains.base import DomainBase

logger = logging.getLogger(__name__)

# 支持的音频格式
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".opus"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".m4v",
              ".3gp", ".ts", ".mts", ".m2ts", ".vob", ".mpg", ".mpeg", ".rmvb",
              ".rm", ".asf", ".f4v"}

# 输出格式映射
FORMAT_MAP = {
    "mp3": "MP3 (320kbps)",
    "wav": "WAV (无损)",
    "flac": "FLAC (无损)",
    "m4a": "AAC (256kbps)",
    "aac": "AAC (256kbps)",
    "ogg": "OGG (320kbps)",
}


class MusicDomain(DomainBase):
    """音乐/音频子系统

    封装 audio_toolkit 音频工具箱为金水谣标准域子系统。
    提供音频扫描、特征分析、格式转换、音量标准化、智能优化、简单旋律生成等功能。
    """
    DOMAIN_ID = "music"
    DESCRIPTION = "音乐/音频处理（格式转换/音量标准化/智能优化/旋律生成）"

    def __init__(self, config=None):
        super().__init__(config)
        self.data_dir = self.config.get("data_dir", os.path.join("金水谣数据", "music"))
        self._toolkit = None          # audio_toolkit 模块引用
        self._ffmpeg_available = False
        self._ffmpeg_path = None
        self._stats = {
            "total_processed": 0,
            "conversions": 0,
            "normalizations": 0,
            "optimizations": 0,
            "generations": 0,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def setup(self):
        """初始化音频子系统

        检测 ffmpeg 可用性，加载 audio_toolkit 模块，确保数据目录存在。
        """
        try:
            # 确保数据目录存在
            os.makedirs(self.data_dir, exist_ok=True)

            # 尝试导入 audio_toolkit
            try:
                import audio_toolkit
                self._toolkit = audio_toolkit
                self._ffmpeg_path = audio_toolkit.FFMPEG_PATH
                self._ffmpeg_available = audio_toolkit.FFMPEG_PATH is not None
            except ImportError:
                # 降级模式：不依赖 audio_toolkit，仅使用内置功能
                logger.warning("audio_toolkit 模块未找到，音乐子系统以降级模式运行")
                self._toolkit = None
                self._ffmpeg_available = self._detect_ffmpeg()

            self._initialized = True
            ffmpeg_status = "已就绪" if self._ffmpeg_available else "未检测到"
            logger.info("音乐子系统初始化完成 (FFmpeg: %s)", ffmpeg_status)
            return True
        except Exception as e:
            logger.error("音乐子系统初始化失败: %s", e)
            return False

    def teardown(self):
        """清理资源"""
        try:
            self._initialized = False
            self._toolkit = None
            logger.info("音乐子系统已关闭")
            return True
        except Exception as e:
            logger.error("音乐子系统关闭失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 核心流程
    # ------------------------------------------------------------------

    def fetch(self, **kwargs):
        """扫描音乐目录，获取音频文件列表

        Args:
            directory: 自定义目录，默认使用 data_dir
            extensions: 文件扩展名过滤

        Returns:
            dict: {"success": bool, "data": [file_info...], "message": str}
        """
        try:
            directory = kwargs.get("directory", self.data_dir)
            exts_filter = kwargs.get("extensions")

            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                return {"success": True, "data": [], "message": f"目录已创建: {directory}"}

            files = []
            for root, dirs, filenames in os.walk(directory):
                for fname in sorted(filenames):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                        if exts_filter and ext not in exts_filter:
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            size = os.path.getsize(fpath)
                        except OSError:
                            size = 0
                        files.append({
                            "name": fname,
                            "path": fpath,
                            "ext": ext,
                            "size_bytes": size,
                            "size_mb": round(size / (1024 * 1024), 2),
                            "is_audio": ext in AUDIO_EXTS,
                            "is_video": ext in VIDEO_EXTS,
                        })

            return {
                "success": True,
                "data": files,
                "message": f"扫描完成，发现 {len(files)} 个音频/视频文件",
                "directory": directory,
                "total": len(files),
                "audio_count": sum(1 for f in files if f["is_audio"]),
                "video_count": sum(1 for f in files if f["is_video"]),
            }
        except Exception as e:
            logger.error("音乐文件扫描失败: %s", e)
            return {"success": False, "data": [], "message": str(e)}

    def analyze(self, data, **kwargs):
        """分析音频文件特征

        对单个或多个音频文件进行详细分析，包括时长、采样率、声道、码率、质量评分等。

        Args:
            data: 文件路径或文件列表
            **kwargs: 额外参数

        Returns:
            dict: 分析结果
        """
        try:
            # 统一处理为文件列表
            if isinstance(data, str):
                file_list = [data]
            elif isinstance(data, list):
                file_list = data
            else:
                return {"success": False, "error": "不支持的数据类型"}

            results = []
            for fpath in file_list:
                if isinstance(fpath, dict):
                    fpath = fpath.get("path", "")
                if not fpath or not os.path.exists(fpath):
                    continue

                info = self._analyze_single(fpath)
                results.append(info)

            return {
                "success": True,
                "results": results,
                "count": len(results),
                "total_duration": sum(r.get("duration", 0) for r in results),
                "total_size_mb": round(sum(r.get("size_mb", 0) for r in results), 2),
                "avg_score": round(sum(r.get("score", 0) for r in results) / len(results), 1) if results else 0,
            }
        except Exception as e:
            logger.error("音频分析失败: %s", e)
            return {"success": False, "error": str(e), "results": []}

    def generate(self, params=None, **kwargs):
        """生成音乐/音频内容

        支持两种模式：
        1. 格式转换：传入文件路径和目标格式
        2. 旋律生成：纯Python生成简单WAV旋律（无需ffmpeg）

        Args:
            params: 生成参数
                - mode: "convert" | "normalize" | "optimize" | "melody"
                - input: 输入文件路径（convert/normalize/optimize模式）
                - format: 输出格式（convert模式）
                - output_dir: 输出目录
                - melody_name: 旋律名称（melody模式）
                - duration: 时长秒数（melody模式，默认8秒）
                - key: 调式（melody模式，默认C大调）
                - style: 风格（melody模式：random/pentatonic/classical）
            **kwargs: 额外参数

        Returns:
            dict: {"predictions": [...], "summary": str, "status": str}
        """
        params = params or {}
        mode = params.get("mode", kwargs.get("mode", "melody"))
        output_dir = params.get("output_dir", kwargs.get("output_dir", self.data_dir))

        try:
            os.makedirs(output_dir, exist_ok=True)

            if mode == "convert":
                return self._generate_convert(params, output_dir)
            elif mode == "normalize":
                return self._generate_normalize(params, output_dir)
            elif mode == "optimize":
                return self._generate_optimize(params, output_dir)
            elif mode == "melody":
                return self._generate_melody(params, output_dir)
            else:
                return {
                    "predictions": [],
                    "summary": f"未知生成模式: {mode}，支持: convert/normalize/optimize/melody",
                    "status": "error",
                    "domain_id": self.DOMAIN_ID,
                }
        except Exception as e:
            logger.error("音乐生成失败: %s", e)
            return {
                "predictions": [],
                "summary": f"生成失败: {e}",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘统计

        统计音频处理历史记录，返回处理数量、成功率等。

        Returns:
            dict: {"reviews": int, "hits": int, "updated": bool}
        """
        try:
            total = self._stats["total_processed"]
            # 简单计算"成功率"：所有处理操作都视为有效处理
            hits = total  # 在音乐域，所有成功处理的都算"命中"
            return {
                "reviews": total,
                "hits": hits,
                "updated": True,
                "stats": dict(self._stats),
                "status": "ok",
            }
        except Exception as e:
            logger.error("音乐复盘失败: %s", e)
            return {"reviews": 0, "hits": 0, "updated": False, "error": str(e)}

    def status(self):
        """子系统健康状态

        Returns:
            dict: {"ready": bool, "engines": [...], "last_run": str, "errors": [...]}
        """
        # 统计文件数量
        file_count = 0
        if os.path.exists(self.data_dir):
            try:
                for fname in os.listdir(self.data_dir):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in AUDIO_EXTS:
                        file_count += 1
            except OSError:
                pass

        engines = []
        if self._ffmpeg_available:
            engines = [
                "format_converter",   # 格式转换
                "loudness_normalizer",  # 音量标准化
                "smart_optimizer",    # 智能优化
                "audio_analyzer",     # 音频分析
                "metadata_editor",    # 元数据编辑
                "trimmer",            # 裁剪拼接
            ]
        engines.append("melody_generator")  # 纯Python旋律生成器（始终可用）

        errors = []
        if not self._ffmpeg_available:
            errors.append("FFmpeg 未检测到，部分功能（格式转换/标准化/优化）不可用")

        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "ffmpeg_available": self._ffmpeg_available,
            "ffmpeg_path": self._ffmpeg_path,
            "engines": engines,
            "supported_formats": list(AUDIO_EXTS),
            "music_file_count": file_count,
            "data_dir": self.data_dir,
            "stats": dict(self._stats),
            "last_run": None,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # 内部方法 - 音频分析
    # ------------------------------------------------------------------

    def _analyze_single(self, filepath):
        """分析单个音频文件"""
        info = {
            "file": os.path.basename(filepath),
            "path": filepath,
            "ext": os.path.splitext(filepath)[1].lower(),
            "size_mb": 0,
            "duration": 0,
            "sample_rate": 0,
            "channels": 0,
            "bitrate": 0,
            "codec": "",
            "score": 0,
            "issues": [],
        }

        try:
            info["size_mb"] = round(os.path.getsize(filepath) / (1024 * 1024), 2)
        except OSError:
            pass

        # 优先使用 audio_toolkit 的分析功能
        if self._toolkit and self._ffmpeg_available:
            try:
                report = self._toolkit.analyze_audio(filepath)
                info.update({
                    "sample_rate": report.get("sample_rate", 0),
                    "channels": report.get("channels", 0),
                    "bitrate": report.get("bitrate", 0),
                    "duration": report.get("duration", 0),
                    "codec": report.get("codec", ""),
                    "score": report.get("score", 0),
                    "issues": report.get("issues", []),
                })
                return info
            except Exception:
                pass

        # 降级：WAV 文件可以直接读取基本信息
        if info["ext"] == ".wav":
            try:
                with wave.open(filepath, "rb") as wf:
                    info["sample_rate"] = wf.getframerate()
                    info["channels"] = wf.getnchannels()
                    frames = wf.getnframes()
                    info["duration"] = frames / float(wf.getframerate()) if wf.getframerate() > 0 else 0
                    info["codec"] = "pcm"
                    # 简单评分
                    score = 100
                    if info["sample_rate"] < 44100:
                        score -= 20
                    if info["channels"] < 2:
                        score -= 15
                    info["score"] = max(0, score)
            except Exception:
                pass

        return info

    # ------------------------------------------------------------------
    # 内部方法 - 格式转换
    # ------------------------------------------------------------------

    def _generate_convert(self, params, output_dir):
        """格式转换生成"""
        if not self._ffmpeg_available or not self._toolkit:
            return {
                "predictions": [],
                "summary": "FFmpeg 不可用，无法进行格式转换",
                "status": "ffmpeg_unavailable",
                "domain_id": self.DOMAIN_ID,
            }

        input_path = params.get("input", params.get("file", ""))
        target_format = params.get("format", params.get("target_format", "MP3 (320kbps)"))

        if not input_path or not os.path.exists(input_path):
            return {
                "predictions": [],
                "summary": "输入文件不存在",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

        # 格式名称映射
        if target_format.lower() in FORMAT_MAP:
            target_format = FORMAT_MAP[target_format.lower()]

        ext = os.path.splitext(input_path)[1].lower()
        is_video = ext in VIDEO_EXTS

        if is_video:
            result = self._toolkit.video_to_audio(input_path, output_dir, target_format)
        else:
            result = self._toolkit.convert_audio(input_path, output_dir, target_format)

        if result.get("success"):
            self._stats["conversions"] += 1
            self._stats["total_processed"] += 1
            output_file = result.get("output", "")
            return {
                "predictions": [{
                    "type": "convert",
                    "input": input_path,
                    "output": output_file,
                    "format": target_format,
                    "size_mb": result.get("size_mb", 0),
                    "time_sec": round(result.get("time", 0), 2),
                }],
                "summary": f"转换完成: {os.path.basename(output_file)} ({result.get('size_mb', 0):.2f}MB)",
                "status": "ok",
                "domain_id": self.DOMAIN_ID,
            }
        else:
            return {
                "predictions": [],
                "summary": f"转换失败: {result.get('error', '未知错误')}",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

    def _generate_normalize(self, params, output_dir):
        """音量标准化生成"""
        if not self._ffmpeg_available or not self._toolkit:
            return {
                "predictions": [],
                "summary": "FFmpeg 不可用，无法进行音量标准化",
                "status": "ffmpeg_unavailable",
                "domain_id": self.DOMAIN_ID,
            }

        input_path = params.get("input", params.get("file", ""))
        target_lufs = params.get("lufs", params.get("target_lufs", -14.0))

        if not input_path or not os.path.exists(input_path):
            return {
                "predictions": [],
                "summary": "输入文件不存在",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

        result = self._toolkit.normalize_loudness(input_path, output_dir, target_lufs)

        if result.get("success"):
            self._stats["normalizations"] += 1
            self._stats["total_processed"] += 1
            output_file = result.get("output", "")
            return {
                "predictions": [{
                    "type": "normalize",
                    "input": input_path,
                    "output": output_file,
                    "target_lufs": target_lufs,
                    "original_lufs": result.get("original_lufs", "?"),
                    "mode": result.get("mode", "single_pass"),
                    "size_mb": result.get("size_mb", 0),
                    "time_sec": round(result.get("time", 0), 2),
                }],
                "summary": f"音量标准化完成: {os.path.basename(output_file)} ({result.get('mode', '?')})",
                "status": "ok",
                "domain_id": self.DOMAIN_ID,
            }
        else:
            return {
                "predictions": [],
                "summary": f"标准化失败: {result.get('error', '未知错误')}",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

    def _generate_optimize(self, params, output_dir):
        """智能优化生成"""
        if not self._ffmpeg_available or not self._toolkit:
            return {
                "predictions": [],
                "summary": "FFmpeg 不可用，无法进行智能优化",
                "status": "ffmpeg_unavailable",
                "domain_id": self.DOMAIN_ID,
            }

        input_path = params.get("input", params.get("file", ""))
        output_format = params.get("output_format", params.get("format"))

        if not input_path or not os.path.exists(input_path):
            return {
                "predictions": [],
                "summary": "输入文件不存在",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

        result = self._toolkit.smart_optimize(input_path, output_dir, output_format)

        if result.get("success"):
            self._stats["optimizations"] += 1
            self._stats["total_processed"] += 1
            output_file = result.get("output", "")
            issues_fixed = result.get("issues_fixed", [])
            return {
                "predictions": [{
                    "type": "optimize",
                    "input": input_path,
                    "output": output_file,
                    "issues_fixed": issues_fixed,
                    "size_mb": result.get("size_mb", 0),
                    "time_sec": round(result.get("time", 0), 2),
                }],
                "summary": f"智能优化完成: {os.path.basename(output_file)}，修复了 {len(issues_fixed)} 个问题",
                "status": "ok",
                "domain_id": self.DOMAIN_ID,
            }
        else:
            return {
                "predictions": [],
                "summary": f"优化失败: {result.get('error', '未知错误')}",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

    # ------------------------------------------------------------------
    # 内部方法 - 简单旋律生成（纯Python，无需ffmpeg）
    # ------------------------------------------------------------------

    def _generate_melody(self, params, output_dir):
        """生成简单旋律（纯Python WAV生成）

        无需ffmpeg，使用Python标准库 wave 生成WAV格式旋律。
        支持多种风格：随机、五声音阶、古典进行等。
        """
        melody_name = params.get("melody_name", params.get("name", f"melody_{int(datetime.now().timestamp())}"))
        duration = float(params.get("duration", 8))
        style = params.get("style", "pentatonic")  # random, pentatonic, classical
        bpm = int(params.get("bpm", 120))
        sample_rate = 44100

        try:
            # 生成音符序列
            notes = self._compose_melody(duration, bpm, style)

            # 生成WAV文件
            output_path = os.path.join(output_dir, f"{melody_name}.wav")
            self._render_wav(notes, output_path, sample_rate)

            self._stats["generations"] += 1
            self._stats["total_processed"] += 1

            size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)

            return {
                "predictions": [{
                    "type": "melody",
                    "name": melody_name,
                    "output": output_path,
                    "style": style,
                    "bpm": bpm,
                    "duration_sec": duration,
                    "note_count": len(notes),
                    "size_mb": size_mb,
                    "format": "WAV (无损)",
                }],
                "summary": f"旋律生成完成: {melody_name}.wav ({style}风格, {len(notes)}个音符, {duration:.0f}秒)",
                "status": "ok",
                "domain_id": self.DOMAIN_ID,
            }
        except Exception as e:
            logger.error("旋律生成失败: %s", e)
            return {
                "predictions": [],
                "summary": f"旋律生成失败: {e}",
                "status": "error",
                "domain_id": self.DOMAIN_ID,
            }

    def _compose_melody(self, total_duration, bpm, style):
        """作曲：生成音符序列

        Returns:
            list of (freq_hz, start_sec, duration_sec, volume)
        """
        beat_duration = 60.0 / bpm  # 一拍的秒数
        notes = []

        # 音阶定义
        # C大调五声音阶: C D E G A (频率Hz)
        pentatonic_c = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25]
        # C大调音阶
        major_c = [261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25]
        # 古典和弦进行 I-V-vi-IV (C G Am F)
        classical_progression = [
            [261.63, 329.63, 392.00],   # C大三和弦
            [392.00, 493.88, 587.33],   # G大三和弦
            [440.00, 523.25, 659.25],   # A小三和弦 (Am)
            [349.23, 440.00, 523.25],   # F大三和弦
        ]

        current_time = 0.0
        note_duration = beat_duration * 0.5  # 八分音符

        if style == "pentatonic":
            # 五声音阶随机旋律
            scale = pentatonic_c
            while current_time < total_duration:
                freq = random.choice(scale)
                # 偶尔加入长音
                dur = note_duration * random.choice([1, 1, 1, 2, 2, 4])
                if current_time + dur > total_duration:
                    dur = total_duration - current_time
                vol = 0.3 + random.random() * 0.3
                notes.append((freq, current_time, dur, vol))
                current_time += dur

        elif style == "classical":
            # 古典和弦分解（I-V-vi-IV进行）
            chord_dur = beat_duration * 4  # 每小节4拍
            chord_index = 0
            while current_time < total_duration:
                chord = classical_progression[chord_index % len(classical_progression)]
                # 分解和弦：每个音符依次出现
                for i, freq in enumerate(chord):
                    nd = note_duration
                    if current_time + nd > total_duration:
                        nd = total_duration - current_time
                    if nd <= 0:
                        break
                    notes.append((freq, current_time, nd * 0.9, 0.35))
                    current_time += note_duration
                # 加一个根音长音作为低音
                if current_time + note_duration <= total_duration:
                    bass_freq = chord[0] / 2
                    notes.append((bass_freq, current_time - 3 * note_duration,
                                  3 * note_duration, 0.2))
                chord_index += 1

        else:  # random
            # 完全随机旋律
            scale = major_c
            while current_time < total_duration:
                freq = random.choice(scale)
                dur = note_duration * random.choice([0.5, 1, 1, 2, 3])
                if current_time + dur > total_duration:
                    dur = total_duration - current_time
                vol = 0.25 + random.random() * 0.35
                notes.append((freq, current_time, dur, vol))
                current_time += dur

        return notes

    def _render_wav(self, notes, output_path, sample_rate=44100):
        """将音符序列渲染为WAV文件

        使用正弦波 + ADSR包络生成简单音色。
        """
        if not notes:
            # 空文件，生成1秒静音
            n_samples = sample_rate
            frames = [0] * n_samples
        else:
            total_duration = max(n[1] + n[2] for n in notes)
            n_samples = int(total_duration * sample_rate)
            frames = [0.0] * n_samples

            for freq, start, dur, volume in notes:
                start_sample = int(start * sample_rate)
                dur_samples = int(dur * sample_rate)
                end_sample = min(start_sample + dur_samples, n_samples)

                # ADSR 包络
                attack = int(dur_samples * 0.05)
                release = int(dur_samples * 0.15)
                sustain = dur_samples - attack - release

                for i in range(start_sample, end_sample):
                    offset = i - start_sample
                    # 计算包络
                    if offset < attack:
                        env = offset / max(attack, 1)
                    elif offset < attack + sustain:
                        env = 1.0
                    else:
                        rel_offset = offset - attack - sustain
                        env = max(0, 1.0 - rel_offset / max(release, 1))

                    # 正弦波 + 少量泛音
                    t = (i - start_sample) / sample_rate
                    sample = (
                        volume * env * (
                            0.6 * math.sin(2 * math.pi * freq * t) +
                            0.25 * math.sin(2 * math.pi * freq * 2 * t) +
                            0.1 * math.sin(2 * math.pi * freq * 3 * t) +
                            0.05 * math.sin(2 * math.pi * freq * 4 * t)
                        )
                    )
                    frames[i] += sample

            # 归一化（防止削波）
            max_val = max(abs(s) for s in frames) if frames else 1.0
            if max_val > 0.8:
                scale = 0.8 / max_val
                frames = [s * scale for s in frames]

        # 写入WAV文件
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            # 转换为16位整数
            int_frames = [int(max(-1.0, min(1.0, s)) * 32767) for s in frames]
            wf.writeframes(struct.pack("<" + "h" * len(int_frames), *int_frames))

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _detect_ffmpeg(self):
        """检测系统中是否有ffmpeg"""
        import subprocess
        try:
            from config.path_resolver import get_ffmpeg_candidates
            candidates = get_ffmpeg_candidates()
        except ImportError:
            candidates = ["ffmpeg"]  # minimal fallback
        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "-version"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                if result.returncode == 0:
                    self._ffmpeg_path = candidate
                    return True
            except Exception:
                continue
        return False

    def convert_format(self, input_path, output_dir, format_name="MP3 (320kbps)"):
        """便捷方法：格式转换"""
        return self.generate(params={
            "mode": "convert",
            "input": input_path,
            "format": format_name,
            "output_dir": output_dir,
        })

    def normalize_audio(self, input_path, output_dir=None, target_lufs=-14.0):
        """便捷方法：音量标准化"""
        return self.generate(params={
            "mode": "normalize",
            "input": input_path,
            "lufs": target_lufs,
            "output_dir": output_dir or os.path.dirname(input_path),
        })

    def optimize_audio(self, input_path, output_dir=None, output_format=None):
        """便捷方法：智能优化"""
        return self.generate(params={
            "mode": "optimize",
            "input": input_path,
            "output_format": output_format,
            "output_dir": output_dir or os.path.dirname(input_path),
        })

    def generate_melody(self, name=None, duration=8, style="pentatonic", bpm=120):
        """便捷方法：生成旋律"""
        return self.generate(params={
            "mode": "melody",
            "melody_name": name or f"melody_{int(datetime.now().timestamp())}",
            "duration": duration,
            "style": style,
            "bpm": bpm,
        })
