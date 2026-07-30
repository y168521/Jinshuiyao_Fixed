# -*- coding: utf-8 -*-
"""
音频工具箱 V2.0 - 智能音频处理套件
功能模块:
  1. 视频转音频 (320kbps MP3 / 无损 WAV/FLAC / AAC / OGG)
  2. 音频格式互转 (任意格式间转换)
  3. 元数据编辑 (ID3标签读写)
  4. 音量标准化 (EBU R128 -14LUFS)
  5. 音频裁剪拼接
  6. 智能音频优化 (自动检测+一键修复)
"""

import os
import sys
import subprocess
import threading
import time
import json
import shutil
import tempfile
import math

# ============================================================
# FFmpeg 配置
# ============================================================
try:
    from config.path_resolver import get_ffmpeg_candidates
    _FFMPEG_CANDIDATES = get_ffmpeg_candidates()
except ImportError:
    _FFMPEG_CANDIDATES = ["ffmpeg"]  # minimal fallback

FFMPEG_PATH = None
for candidate in _FFMPEG_CANDIDATES:
    try:
        result = subprocess.run([candidate, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            FFMPEG_PATH = candidate
            break
    except Exception:
        continue

# ============================================================
# 支持的格式
# ============================================================
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
    """执行FFmpeg命令，返回(subprocess, stderr_lines_generator)

    Args:
        cmd: FFmpeg 命令列表
        timeout: 超时秒数（默认300秒），超时将强制终止进程
    """
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

    def _timeout_kill():
        """超时后强制终止 FFmpeg 进程"""
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    watchdog = threading.Thread(target=_timeout_kill, daemon=True)
    watchdog.start()
    return process


# ============================================================
# 模块1: 视频转音频
# ============================================================
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
                except Exception:
                    pass
            if "time=" in line and duration > 0 and progress_callback:
                try:
                    time_str = line.split("time=")[1].split(" ")[0].strip()
                    h, m, s = time_str.split(":")
                    current = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(95, int((current / duration) * 90) + 10)
                    progress_callback(pct, f"转换中 {pct}%")
                except Exception:
                    pass
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            if progress_callback:
                progress_callback(100, "完成")
            return {"success": True, "output": output_path, "time": elapsed,
                    "size_mb": os.path.getsize(output_path) / (1024 * 1024)}
        else:
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            return {"success": False, "error": stderr[-500:], "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}


# ============================================================
# 模块2: 音频格式互转
# ============================================================
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
                except Exception:
                    pass
            if "time=" in line and duration > 0 and progress_callback:
                try:
                    time_str = line.split("time=")[1].split(" ")[0].strip()
                    h, m, s = time_str.split(":")
                    current = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(95, int((current / duration) * 90) + 10)
                    progress_callback(pct, f"转换中 {pct}%")
                except Exception:
                    pass
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            if progress_callback:
                progress_callback(100, "完成")
            return {"success": True, "output": output_path, "time": elapsed,
                    "size_mb": os.path.getsize(output_path) / (1024 * 1024)}
        else:
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            return {"success": False, "error": stderr[-500:], "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}


# ============================================================
# 模块3: 元数据编辑 (ID3标签)
# ============================================================
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
        # mutagen easy模式返回列表，取第一个元素
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


# ============================================================
# 模块4: 音量标准化 (EBU R128 -14LUFS)
# ============================================================
def normalize_loudness(input_path, output_dir=None, target_lufs=-14.0,
                        output_format=None, progress_callback=None):
    """
    EBU R128 音量标准化。
    两遍编码: 第一遍分析，第二遍应用。
    """
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}

    if output_dir is None:
        output_dir = os.path.dirname(input_path)

    # 输出路径
    basename = os.path.splitext(os.path.basename(input_path))[0]
    ext = os.path.splitext(input_path)[1]
    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
    output_path = os.path.join(output_dir, basename + "_normalized" + ext)

    start_time = time.time()

    if progress_callback:
        progress_callback(5, "分析音量...")

    # 第一遍: 分析
    tmp_nul = os.path.join(tempfile.gettempdir(), "loudnorm_null.mp4")
    try:
        analyze_cmd = [
            FFMPEG_PATH, "-i", input_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
            "-f", "mp4", "-y", tmp_nul
        ]
        p = subprocess.Popen(analyze_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        _, stderr = p.communicate()
    except Exception:
        # 如果mp4容器不行，用null
        try:
            analyze_cmd = [
                FFMPEG_PATH, "-i", input_path,
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
                "-f", "null", "-"
            ]
            p = subprocess.Popen(analyze_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            _, stderr = p.communicate()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # 解析分析结果
    measured = {}
    try:
        # loudnorm的JSON输出在stderr的最后几行
        lines = stderr.decode("utf-8", errors="replace").strip().split("\n")
        json_lines = [l for l in lines if l.strip().startswith("{") or l.strip().startswith('"')]
        for line in lines:
            if '"input_i"' in line or '"input_lra"' in line or '"input_tp"' in line or '"target_offset"' in line:
                json_start = line.find("{")
                if json_start >= 0:
                    json_str = line[json_start:]
                    # 找到完整的JSON
                    brace_count = 0
                    end = 0
                    for i, c in enumerate(json_str):
                        if c == "{":
                            brace_count += 1
                        elif c == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end = i + 1
                                break
                    if end > 0:
                        measured = json.loads(json_str[:end])
                        break
    except Exception:
        pass

    if not measured:
        # 没有解析到数据，使用单遍标准化
        if progress_callback:
            progress_callback(50, "单遍标准化...")
        try:
            norm_cmd = [
                FFMPEG_PATH, "-i", input_path,
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-b:a", "320k", "-y", output_path
            ]
            process = _run_ffmpeg(norm_cmd)
            process.wait()
            elapsed = time.time() - start_time
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    progress_callback(100, "完成")
                return {"success": True, "output": output_path, "time": elapsed,
                        "size_mb": os.path.getsize(output_path) / (1024 * 1024),
                        "mode": "single_pass"}
            else:
                return {"success": False, "error": "标准化失败", "time": elapsed}
        except Exception as e:
            return {"success": False, "error": str(e)}

    if progress_callback:
        progress_callback(40, "应用标准化...")

    # 提取测量值
    input_i = measured.get("input_i", target_lufs)
    input_lra = measured.get("input_lra", 11)
    input_tp = measured.get("input_tp", -1.5)
    target_offset = measured.get("target_offset", 0)
    input_lra = max(input_lra, 0.1)

    # 第二遍: 应用精确标准化
    try:
        norm_cmd = [
            FFMPEG_PATH, "-i", input_path,
            "-af", (f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:"
                    f"measured_I={input_i}:measured_LRA={input_lra}:"
                    f"measured_TP={input_tp}:measured_thresh=-70:"
                    f"offset={target_offset}:linear=true"),
            "-c:a", "libmp3lame", "-b:a", "320k", "-y", output_path
        ]
        process = _run_ffmpeg(norm_cmd)
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            if progress_callback:
                progress_callback(100, "完成")
            return {
                "success": True, "output": output_path, "time": elapsed,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024),
                "mode": "dual_pass",
                "original_lufs": input_i,
                "target_lufs": target_lufs,
            }
        else:
            return {"success": False, "error": "第二遍标准化失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}
    finally:
        if os.path.exists(tmp_nul):
            try:
                os.remove(tmp_nul)
            except Exception:
                pass


# ============================================================
# 模块5: 音频裁剪拼接
# ============================================================
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
        else:
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
        ext = ".mp3"
        codec = "libmp3lame"
        args = ["-b:a", "320k"]

    # 创建concat文件列表
    tmp_list = os.path.join(tempfile.gettempdir(), "concat_list.txt")
    try:
        with open(tmp_list, "w", encoding="utf-8") as f:
            for fp in file_list:
                fp = fp.replace("'", "'\\''")
                f.write(f"file '{fp}'\n")

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
        else:
            return {"success": False, "error": "拼接失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(tmp_list):
            try:
                os.remove(tmp_list)
            except Exception:
                pass


# ============================================================
# 模块6: 智能音频优化
# ============================================================
def analyze_audio(filepath):
    """全面分析音频质量，返回诊断报告"""
    report = {"file": os.path.basename(filepath), "issues": [], "score": 100}

    # 获取音频信息
    ffprobe = FFMPEG_PATH.replace("ffmpeg", "ffprobe")
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", filepath],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            for s in data.get("streams", []):
                if s.get("codec_type") == "audio":
                    sr = int(s.get("sample_rate", 0))
                    ch = s.get("channels", 0)
                    br = int(s.get("bit_rate", 0)) / 1000
                    duration = float(s.get("duration", 0))

                    report["sample_rate"] = sr
                    report["channels"] = ch
                    report["bitrate"] = br
                    report["duration"] = duration
                    report["codec"] = s.get("codec_name", "")

                    # 检查采样率
                    if sr < 44100:
                        report["issues"].append({"type": "sample_rate",
                                                  "msg": f"采样率{sr}Hz偏低，建议>=44100Hz",
                                                  "fix": "resample", "value": 44100, "score": -20})
                    elif sr > 48000:
                        report["issues"].append({"type": "sample_rate",
                                                  "msg": f"采样率{sr}Hz过高，建议44100Hz",
                                                  "fix": "resample", "value": 44100, "score": -5})

                    # 检查声道
                    if ch < 2:
                        report["issues"].append({"type": "channels",
                                                  "msg": f"{ch}声道，建议双声道(stereo)",
                                                  "fix": "stereo", "value": 2, "score": -15})

                    # 检查码率
                    if s.get("codec_name") == "mp3" and br < 256:
                        report["issues"].append({"type": "bitrate",
                                                  "msg": f"MP3码率{br:.0f}kbps偏低，建议>=320kbps",
                                                  "fix": "bitrate", "value": 320, "score": -15})

                    # 检查时长
                    if duration < 30:
                        report["issues"].append({"type": "duration",
                                                  "msg": f"时长{duration:.0f}秒，可能过短",
                                                  "fix": "none", "score": -5})

            # 文件大小
            fmt = data.get("format", {})
            size_mb = int(fmt.get("size", 0)) / (1024 * 1024)
            report["size_mb"] = size_mb
    except Exception:
        report["issues"].append({"type": "info_error", "msg": "无法读取音频信息", "fix": "none", "score": -30})

    # 计算总分
    for issue in report["issues"]:
        report["score"] += issue.get("score", 0)
    report["score"] = max(0, report["score"])

    return report


def smart_optimize(input_path, output_dir=None, output_format=None, progress_callback=None):
    """
    智能一键优化: 自动检测问题并修复。
    优化项: 采样率->44100Hz, 声道->立体声, 码率->320kbps, 音量->-14LUFS
    """
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}

    if output_dir is None:
        output_dir = os.path.dirname(input_path)

    report = analyze_audio(input_path)

    # 构建优化滤镜链
    filters = []
    issues_fixed = []

    # 采样率
    sr = report.get("sample_rate", 44100)
    if sr != 44100:
        filters.append(f"aresample=44100")
        issues_fixed.append(f"采样率 {sr}Hz -> 44100Hz")

    # 声道
    ch = report.get("channels", 2)
    if ch < 2:
        filters.append("aformat=channel_layouts=stereo")
        issues_fixed.append(f"声道 单声道 -> 立体声")

    # 码率+音量标准化
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if filters:
        filter_chain = ",".join(filters) + "," + loudnorm
    else:
        filter_chain = loudnorm

    # 输出格式
    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
        codec = fmt["codec"] if fmt else "libmp3lame"
        args = fmt.get("args", []) if fmt else ["-b:a", "320k"]
    else:
        ext = os.path.splitext(input_path)[1] or ".mp3"
        if ext in [".wav", ".flac"]:
            codec = ext.replace(".", "")
            args = []
        elif ext == ".ogg":
            codec = "libvorbis"
            args = ["-b:a", "320k", "-ar", "44100", "-ac", "2"]
        else:
            codec = "libmp3lame"
            args = ["-b:a", "320k"]

    basename = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{basename}_optimized{ext}")

    if progress_callback:
        progress_callback(10, "正在优化...")

    cmd = [FFMPEG_PATH, "-i", input_path, "-af", filter_chain,
           "-c:a", codec, *args, "-ar", "44100", "-y", output_path]

    start_time = time.time()
    try:
        process = _run_ffmpeg(cmd)
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            if progress_callback:
                progress_callback(100, "优化完成")
            # 写入元数据（保留原有标签）
            old_meta = read_metadata(input_path)
            if not old_meta.get("error"):
                write_metadata(output_path, **old_meta)

            return {
                "success": True, "output": output_path, "time": elapsed,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024),
                "issues_fixed": issues_fixed or ["音量标准化到-14LUFS"],
                "original_report": report,
            }
        else:
            return {"success": False, "error": "优化处理失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}


# ============================================================
# 音频信息获取
# ============================================================
def get_audio_info(filepath):
    """获取音频/视频文件的详细信息"""
    info = {"path": filepath, "filename": os.path.basename(filepath),
            "size_mb": 0, "duration": 0, "has_audio": False}
    try:
        info["size_mb"] = os.path.getsize(filepath) / (1024 * 1024)
    except Exception:
        pass

    ffprobe = FFMPEG_PATH.replace("ffmpeg", "ffprobe")
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
    except Exception:
        pass

    return info


def format_duration(seconds):
    if seconds <= 0:
        return "未知"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


# ============================================================
# GUI
# ============================================================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title("音频工具箱 V2.0")
    root.geometry("800x680")
    root.minsize(720, 600)
    root.configure(bg="#1a1a2e")

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Dark.TFrame", background="#1a1a2e")
    style.configure("Dark.TLabel", background="#1a1a2e", foreground="#e0e0e0",
                    font=("Microsoft YaHei UI", 10))
    style.configure("Title.TLabel", background="#1a1a2e", foreground="#00d4aa",
                    font=("Microsoft YaHei UI", 16, "bold"))
    style.configure("Status.TLabel", background="#1a1a2e", foreground="#7a8499",
                    font=("Microsoft YaHei UI", 9))
    style.configure("Dark.TButton", font=("Microsoft YaHei UI", 10))
    style.configure("Convert.TButton", font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("Dark.TLabelframe", background="#1a1a2e", foreground="#00d4aa")
    style.configure("Dark.TLabelframe.Label", background="#1a1a2e", foreground="#00d4aa",
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Dark.TNotebook", background="#1a1a2e")
    style.configure("Dark.TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=[12, 4])

    # 变量
    file_list = []
    output_dir_var = tk.StringVar(value="")
    format_var = tk.StringVar(value="MP3 (320kbps)")
    status_var = tk.StringVar(value="就绪 - 选择功能模块开始")
    progress_var = tk.DoubleVar(value=0)
    is_processing = False

    # 标题
    title_frame = ttk.Frame(root, style="Dark.TFrame")
    title_frame.pack(fill="x", padx=20, pady=(15, 5))
    ttk.Label(title_frame, text="音频工具箱 V2.0", style="Title.TLabel").pack(side="left")
    ffmpeg_status = "FFmpeg: " + ("已就绪" if FFMPEG_PATH else "未找到!")
    tk.Label(title_frame, text=ffmpeg_status, bg="#1a1a2e",
             fg="#00d4aa" if FFMPEG_PATH else "#ff6b6b",
             font=("Microsoft YaHei UI", 9)).pack(side="right")

    # Notebook (Tab切换)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=20, pady=10)

    # ============ Tab 1: 视频转音频 / 格式互转 ============
    tab_convert = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab_convert, text=" 转换 ")

    # 模式选择
    mode_frame = ttk.Frame(tab_convert, style="Dark.TFrame")
    mode_frame.pack(fill="x", padx=10, pady=(5, 0))
    mode_var = tk.StringVar(value="video")
    ttk.Radiobutton(mode_frame, text="视频转音频", variable=mode_var, value="video",
                     style="Dark.TLabel").pack(side="left", padx=10)
    ttk.Radiobutton(mode_frame, text="音频格式互转", variable=mode_var, value="audio",
                     style="Dark.TLabel").pack(side="left", padx=10)

    # 文件列表
    list_frame = ttk.LabelFrame(tab_convert, text=" 文件列表 ",
                                  style="Dark.TLabelframe")
    list_frame.pack(fill="both", expand=True, padx=10, pady=5)

    btn_frame = ttk.Frame(list_frame, style="Dark.TFrame")
    btn_frame.pack(fill="x", padx=10, pady=5)
    ttk.Button(btn_frame, text="添加文件",
                command=lambda: add_files()).pack(side="left", padx=2)
    ttk.Button(btn_frame, text="添加文件夹",
                command=lambda: add_folder()).pack(side="left", padx=2)
    ttk.Button(btn_frame, text="清空",
                command=lambda: clear_list()).pack(side="left", padx=2)
    file_count_label = ttk.Label(btn_frame, text="0 个文件", style="Status.TLabel")
    file_count_label.pack(side="right", padx=5)

    columns = ("filename", "size", "duration", "status")
    tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
    tree.heading("filename", text="文件名")
    tree.heading("size", text="大小")
    tree.heading("duration", text="时长")
    tree.heading("status", text="状态")
    tree.column("filename", width=350, minwidth=200)
    tree.column("size", width=80, minwidth=60, anchor="center")
    tree.column("duration", width=80, minwidth=60, anchor="center")
    tree.column("status", width=180, minwidth=120, anchor="center")
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=5)
    tree.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 5))

    # 设置
    settings_frame = ttk.Frame(tab_convert, style="Dark.TFrame")
    settings_frame.pack(fill="x", padx=10, pady=5)
    ttk.Label(settings_frame, text="输出目录:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Entry(settings_frame, textvariable=output_dir_var, width=35).pack(side="left", padx=2)
    ttk.Button(settings_frame, text="浏览",
                command=lambda: output_dir_var.set(
                    filedialog.askdirectory() or output_dir_var.get())).pack(side="left", padx=2)
    ttk.Label(settings_frame, text="格式:", style="Dark.TLabel").pack(side="left", padx=(20, 5))
    ttk.Combobox(settings_frame, textvariable=format_var, values=list(FORMATS.keys()),
                  state="readonly", width=16).pack(side="left", padx=2)

    # ============ Tab 2: 元数据编辑 ============
    tab_meta = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab_meta, text=" 元数据 ")

    meta_file_frame = ttk.Frame(tab_meta, style="Dark.TFrame")
    meta_file_frame.pack(fill="x", padx=15, pady=(10, 5))
    ttk.Label(meta_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    meta_path_var = tk.StringVar(value="")
    meta_entry = ttk.Entry(meta_file_frame, textvariable=meta_path_var, width=50)
    meta_entry.pack(side="left", padx=2, fill="x", expand=True)
    ttk.Button(meta_file_frame, text="浏览",
                command=lambda: browse_meta_file()).pack(side="left", padx=2)
    ttk.Button(meta_file_frame, text="读取",
                command=lambda: load_metadata()).pack(side="left", padx=2)

    # 元数据字段
    fields_frame = ttk.LabelFrame(tab_meta, text=" 标签信息 ",
                                     style="Dark.TLabelframe")
    fields_frame.pack(fill="x", padx=15, pady=5)

    meta_vars = {}
    field_defs = [
        ("title", "歌名"), ("artist", "歌手"), ("album", "专辑"),
        ("year", "年份"), ("genre", "流派"), ("track", "曲号"),
        ("comment", "备注"),
    ]
    for i, (key, label) in enumerate(field_defs):
        row = ttk.Frame(fields_frame, style="Dark.TFrame")
        row.pack(fill="x", padx=10, pady=3)
        ttk.Label(row, text=f"{label}:", width=8, style="Dark.TLabel").pack(side="left")
        var = tk.StringVar()
        meta_vars[key] = var
        ttk.Entry(row, textvariable=var, width=40).pack(side="left", padx=5, fill="x", expand=True)

    ttk.Button(fields_frame, text="保存标签",
                command=lambda: save_metadata()).pack(pady=8)

    # ============ Tab 3: 音量标准化 ============
    tab_loud = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab_loud, text=" 标准化 ")

    loud_desc = ttk.Label(tab_loud,
                           text="EBU R128 音量标准化\n将音频音量统一到 -14 LUFS（音乐平台推荐响度）",
                           style="Dark.TLabel", justify="center")
    loud_desc.pack(pady=(15, 10))

    loud_file_frame = ttk.Frame(tab_loud, style="Dark.TFrame")
    loud_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(loud_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    loud_path_var = tk.StringVar(value="")
    ttk.Entry(loud_file_frame, textvariable=loud_path_var, width=50).pack(side="left", padx=2,
               fill="x", expand=True)
    ttk.Button(loud_file_frame, text="浏览",
                command=lambda: loud_path_var.set(
                    filedialog.askopenfilename(
                        filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")]) or "")).pack(side="left", padx=2)

    loud_btn_frame = ttk.Frame(tab_loud, style="Dark.TFrame")
    loud_btn_frame.pack(fill="x", padx=15, pady=10)
    ttk.Button(loud_btn_frame, text="开始标准化",
                command=lambda: do_normalize()).pack(pady=5)

    # ============ Tab 4: 裁剪拼接 ============
    tab_trim = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab_trim, text=" 裁剪拼接 ")

    trim_desc = ttk.Label(tab_trim,
                          text="裁剪: 选择单个文件，设定起止时间\n拼接: 选择多个文件，按顺序合并",
                          style="Dark.TLabel", justify="center")
    trim_desc.pack(pady=(15, 10))

    trim_file_frame = ttk.Frame(tab_trim, style="Dark.TFrame")
    trim_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(trim_file_frame, text="文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Button(trim_file_frame, text="添加音频",
                command=lambda: add_trim_files()).pack(side="left", padx=2)
    trim_count_label = ttk.Label(trim_file_frame, text="", style="Status.TLabel")
    trim_count_label.pack(side="left", padx=5)

    trim_list_frame = ttk.Frame(tab_trim, style="Dark.TFrame")
    trim_list_frame.pack(fill="both", expand=True, padx=15, pady=5)

    trim_columns = ("filename", "duration")
    trim_tree = ttk.Treeview(trim_list_frame, columns=trim_columns, show="headings", height=6)
    trim_tree.heading("filename", text="文件名")
    trim_tree.heading("duration", text="时长")
    trim_tree.column("filename", width=400, minwidth=200)
    trim_tree.column("duration", width=100, minwidth=80, anchor="center")
    trim_tree.pack(fill="both", expand=True)

    trim_params = ttk.Frame(tab_trim, style="Dark.TFrame")
    trim_params.pack(fill="x", padx=15, pady=5)
    ttk.Label(trim_params, text="开始(秒):", style="Dark.TLabel").pack(side="left")
    start_sec_var = tk.StringVar(value="0")
    ttk.Entry(trim_params, textvariable=start_sec_var, width=8).pack(side="left", padx=5)
    ttk.Label(trim_params, text="结束(秒):", style="Dark.TLabel").pack(side="left", padx=(15, 0))
    end_sec_var = tk.StringVar(value="")
    ttk.Entry(trim_params, textvariable=end_sec_var, width=8).pack(side="left", padx=5)

    trim_btn_frame = ttk.Frame(tab_trim, style="Dark.TFrame")
    trim_btn_frame.pack(fill="x", padx=15, pady=5)
    ttk.Button(trim_btn_frame, text="裁剪",
                command=lambda: do_trim()).pack(side="left", padx=5)
    ttk.Button(trim_btn_frame, text="拼接全部",
                command=lambda: do_concat()).pack(side="left", padx=5)

    trim_files = []

    # ============ Tab 5: 智能优化 ============
    tab_smart = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab_smart, text=" 智能优化 ")

    smart_desc = ttk.Label(tab_smart,
                            text="智能检测音频问题并一键修复\n\n自动处理: 采样率→44100Hz | 声道→立体声\n"
                                 "码率→320kbps | 音量→-14LUFS | 保留元数据",
                            style="Dark.TLabel", justify="center")
    smart_desc.pack(pady=(15, 10))

    smart_file_frame = ttk.Frame(tab_smart, style="Dark.TFrame")
    smart_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(smart_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    smart_path_var = tk.StringVar(value="")
    ttk.Entry(smart_file_frame, textvariable=smart_path_var, width=50).pack(side="left", padx=2,
              fill="x", expand=True)
    ttk.Button(smart_file_frame, text="浏览",
                command=lambda: smart_path_var.set(
                    filedialog.askopenfilename(
                        filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma"), ("所有文件", "*.*")]) or "")).pack(side="left", padx=2)

    # 诊断报告区域
    smart_report = tk.Text(tab_smart, height=10, bg="#131a2a", fg="#e0e0e0",
                             font=("Microsoft YaHei UI", 10), wrap="word",
                             insertbackground="#e0e0e0", selectbackground="#00d4aa")
    smart_report.pack(fill="both", expand=True, padx=15, pady=5)

    smart_btn_frame = ttk.Frame(tab_smart, style="Dark.TFrame")
    smart_btn_frame.pack(fill="x", padx=15, pady=5)
    ttk.Button(smart_btn_frame, text="检测问题",
                command=lambda: do_analyze()).pack(side="left", padx=5)
    ttk.Button(smart_btn_frame, text="一键优化",
                command=lambda: do_smart_optimize()).pack(side="left", padx=5)

    # ============ 底部状态栏 ============
    bottom_frame = ttk.Frame(root, style="Dark.TFrame")
    bottom_frame.pack(fill="x", padx=20, pady=(5, 15))

    progress_bar = ttk.Progressbar(bottom_frame, variable=progress_var, maximum=100)
    progress_bar.pack(fill="x")
    status_label = ttk.Label(bottom_frame, textvariable=status_var, style="Status.TLabel")
    status_label.pack(fill="x", pady=(2, 0))

    # ---- 方法 ----
    def add_files():
        mode = mode_var.get()
        if mode == "video":
            exts = [("视频文件", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm")]
        else:
            exts = [("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma")]
        paths = filedialog.askopenfilenames(title="选择文件", filetypes=exts + [("所有文件", "*.*")])
        for p in paths:
            iid = tree.insert("", "end", values=(os.path.basename(p), "...", "...", "等待中"))
            file_list.append({"path": p, "iid": iid})
        update_count()

    def add_folder():
        dir_path = filedialog.askdirectory(title="选择文件夹")
        if dir_path:
            count = 0
            for f in sorted(os.listdir(dir_path)):
                full = os.path.join(dir_path, f)
                if os.path.isfile(full):
                    ext = os.path.splitext(f)[1].lower()
                    if mode_var.get() == "video" and ext in VIDEO_EXTS:
                        iid = tree.insert("", "end", values=(f, "...", "...", "等待中"))
                        file_list.append({"path": full, "iid": iid})
                        count += 1
                    elif mode_var.get() == "audio" and ext in AUDIO_EXTS:
                        iid = tree.insert("", "end", values=(f, "...", "...", "等待中"))
                        file_list.append({"path": full, "iid": iid})
                        count += 1
            update_count()

    def clear_list():
        tree.delete(*tree.get_children())
        file_list.clear()
        update_count()

    def update_count():
        file_count_label.config(text=f"{len(file_list)} 个文件")

    def browse_meta_file():
        p = filedialog.askopenfilename(
            filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")])
        if p:
            meta_path_var.set(p)

    def load_metadata():
        p = meta_path_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        meta = read_metadata(p)
        if meta.get("error"):
            messagebox.showerror("错误", meta["error"])
            return
        for key, var in meta_vars.items():
            var.set(meta.get(key, ""))
        status_var.set(f"已读取标签: {os.path.basename(p)}")

    def save_metadata():
        p = meta_path_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        kwargs = {}
        for key, var in meta_vars.items():
            val = var.get().strip()
            if val:
                kwargs[key] = val
        result = write_metadata(p, **kwargs)
        if result["success"]:
            messagebox.showinfo("成功", "标签已保存")
            status_var.set("标签保存成功")
        else:
            messagebox.showerror("失败", result.get("error", "未知错误"))

    def do_normalize():
        p = loud_path_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        out = output_dir_var.get() or os.path.dirname(p)
        status_var.set("正在进行音量标准化...")
        progress_var.set(10)

        def worker():
            result = normalize_loudness(p, out, progress_callback=prog_cb)
            root.after(0, lambda: finish(result))
            root.after(0, lambda: convert_btn.config(state="normal"))

        def prog_cb(pct, msg):
            root.after(0, lambda: progress_var.set(pct))
            root.after(0, lambda: status_var.set(msg))

        def finish(result):
            if result["success"]:
                out_name = os.path.basename(result["output"])
                status_var.set(f"标准化完成 -> {out_name} ({result.get('mode', '?')})")
                messagebox.showinfo("完成",
                                    f"音量标准化完成!\n原始: {result.get('original_lufs', '?')} LUFS\n"
                                    f"目标: {result.get('target_lufs', -14)} LUFS\n"
                                    f"输出: {out_name}")
            else:
                status_var.set("标准化失败")
                messagebox.showerror("失败", result.get("error", "未知错误"))

        convert_btn.config(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    def add_trim_files():
        paths = filedialog.askopenfilenames(
            title="选择音频文件",
            filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")])
        for p in paths:
            info = get_audio_info(p)
            dur = format_duration(info.get("duration", 0))
            trim_tree.insert("", "end", values=(os.path.basename(p), dur))
            trim_files.append(p)
        trim_count_label.config(text=f"{len(trim_files)} 个文件")

    def do_trim():
        if len(trim_files) == 0:
            messagebox.showwarning("提示", "请先添加文件")
            return
        p = trim_files[0]
        try:
            start = float(start_sec_var.get())
        except ValueError:
            start = 0
        try:
            end = float(end_sec_var.get())
        except ValueError:
            messagebox.showwarning("提示", "请输入结束时间(秒)")
            return
        if end <= start:
            messagebox.showwarning("提示", "结束时间必须大于开始时间")
            return

        out = output_dir_var.get() or os.path.dirname(p)
        status_var.set(f"裁剪中 {start}s - {end}s...")
        result = trim_audio(p, out, start, end)
        if result["success"]:
            status_var.set(f"裁剪完成 -> {os.path.basename(result['output'])}")
            messagebox.showinfo("完成", f"裁剪完成! 时长: {result['duration_sec']:.0f}秒")
        else:
            messagebox.showerror("失败", result.get("error", ""))

    def do_concat():
        if len(trim_files) < 2:
            messagebox.showwarning("提示", "拼接至少需要2个文件")
            return
        out = output_dir_var.get() or os.path.dirname(trim_files[0])
        status_var.set("拼接中...")
        result = concat_audio(trim_files, out)
        if result["success"]:
            status_var.set(f"拼接完成 -> {os.path.basename(result['output'])}")
            messagebox.showinfo("完成", f"拼接完成! {len(trim_files)}个文件已合并")
        else:
            messagebox.showerror("失败", result.get("error", ""))

    def do_analyze():
        p = smart_path_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        report = analyze_audio(p)
        smart_report.delete("1.0", "end")
        smart_report.insert("end",
                            f"文件: {report['filename']}\n"
                            f"大小: {report.get('size_mb', 0):.2f} MB\n"
                            f"时长: {format_duration(report.get('duration', 0))}\n"
                            f"编码: {report.get('codec', '?')} | 采样率: {report.get('sample_rate', '?')}Hz | "
                            f"声道: {report.get('channels', '?')} | 码率: {report.get('bitrate', 0):.0f}kbps\n"
                            f"\n质量评分: {report['score']}/100\n"
                            f"{'=' * 40}\n")
        if report["issues"]:
            for i, issue in enumerate(report["issues"]):
                icon = "[!]" if issue.get("score", 0) <= -15 else "[~]"
                smart_report.insert("end",
                                    f"{icon} {issue['msg']} (扣{abs(issue.get('score', 0))}分)\n")
        else:
            smart_report.insert("end", "[OK] 音频质量良好，无需优化\n")

        status_var.set(f"检测完成 - 评分: {report['score']}/100")

    def do_smart_optimize():
        p = smart_path_var.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("提示", "请先选择音频文件")
            return
        out = output_dir_var.get() or os.path.dirname(p)
        status_var.set("智能优化中...")
        progress_var.set(10)

        def worker():
            result = smart_optimize(p, out, progress_callback=prog_cb)
            root.after(0, lambda: finish(result))

        def prog_cb(pct, msg):
            root.after(0, lambda: progress_var.set(pct))
            root.after(0, lambda: status_var.set(msg))

        def finish(result):
            if result["success"]:
                out_name = os.path.basename(result["output"])
                fixes = "\n".join(f"  - {f}" for f in result.get("issues_fixed", []))
                smart_report.delete("1.0", "end")
                smart_report.insert("end",
                                    f"[OK] 优化完成!\n输出: {out_name}\n"
                                    f"处理时长: {result['time']:.1f}s\n"
                                    f"修复项目:\n{fixes}\n")
                status_var.set(f"优化完成 -> {out_name}")
                messagebox.showinfo("完成",
                                    f"智能优化完成!\n输出: {out_name}\n\n"
                                    f"修复了 {len(result.get('issues_fixed', []))} 个问题")
            else:
                status_var.set("优化失败")
                messagebox.showerror("失败", result.get("error", ""))

        threading.Thread(target=worker, daemon=True).start()

    # 转换功能(共享)
    convert_btn = ttk.Button(bottom_frame, text="开始处理", style="Convert.TButton")
    convert_btn.pack(side="left")

    def start_convert():
        nonlocal is_processing
        if is_processing or not file_list:
            messagebox.showwarning("提示", "请先添加文件")
            return
        if not output_dir_var.get():
            output_dir_var.set(os.path.dirname(file_list[0]["path"]))
        is_processing = True
        convert_btn.config(state="disabled")

        def worker():
            nonlocal is_processing
            total = len(file_list)
            fmt = format_var.get()
            mode = mode_var.get()

            for idx, item in enumerate(file_list):
                p = item["path"]
                iid = item["iid"]

                root.after(0, lambda iid=iid, idx=idx, total=total:
                           tree.item(iid, values=(tree.item(iid)["values"][0],
                                                     tree.item(iid)["values"][1],
                                                     tree.item(iid)["values"][2],
                                                     f"处理中 ({idx+1}/{total})")))
                root.after(0, lambda idx=idx, total=total:
                           status_var.set(f"处理 {idx+1}/{total}: {os.path.basename(p)}"))

                def prog_cb(pct, msg):
                    overall = (idx + pct / 100) / total * 100
                    root.after(0, lambda o=overall: progress_var.set(o))

                if mode == "video":
                    result = video_to_audio(p, output_dir_var.get(), fmt, prog_cb)
                else:
                    result = convert_audio(p, output_dir_var.get(), fmt, prog_cb)

                if result["success"]:
                    out_name = os.path.basename(result["output"])
                    if len(out_name) > 25:
                        out_name = out_name[:15] + "..." + out_name[-5:]
                    st = f"完成 -> {out_name} ({result.get('size_mb', 0):.1f}MB)"
                    root.after(0, lambda iid=iid, s=st: tree.item(iid, values=(
                        tree.item(iid)["values"][0], tree.item(iid)["values"][1],
                        tree.item(iid)["values"][2], s)))
                else:
                    err = result.get("error", "")[:50]
                    root.after(0, lambda iid=iid, e=err: tree.item(iid, values=(
                        tree.item(iid)["values"][0], tree.item(iid)["values"][1],
                        tree.item(iid)["values"][2], f"失败: {e}")))

                progress_var.set((idx + 1) / total * 100)

            root.after(0, lambda: status_var.set("全部处理完成!"))
            root.after(0, lambda: progress_var.set(100))
            is_processing = False
            root.after(0, lambda: convert_btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    convert_btn.config(command=lambda: start_convert())

    # 拖放
    try:
        root.drop_target_register("DND_Files")
        root.dnd_bind("<<Drop>>", lambda e: handle_drop(e.data))
    except Exception:
        pass

    def handle_drop(data):
        if isinstance(data, str):
            data = [data]
        for f in data:
            f = f.strip('{}').strip('"')
            if os.path.isfile(f):
                ext = os.path.splitext(f)[1].lower()
                if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                    iid = tree.insert("", "end", values=(os.path.basename(f), "...", "...", "等待中"))
                    file_list.append({"path": f, "iid": iid})
                    update_count()

    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI模式
        import argparse
        parser = argparse.ArgumentParser(description="音频工具箱 V2.0")
        sub = parser.add_subparsers(dest="cmd")

        # 视频转音频
        p1 = sub.add_parser("v2a", help="视频转音频")
        p1.add_argument("input", help="输入视频文件")
        p1.add_argument("-o", "--output", default=None)
        p1.add_argument("-f", "--format", default="MP3 (320kbps)", choices=list(FORMATS.keys()))

        # 格式互转
        p2 = sub.add_parser("convert", help="音频格式互转")
        p2.add_argument("input", help="输入音频文件")
        p2.add_argument("-o", "--output", default=None)
        p2.add_argument("-f", "--format", default="MP3 (320kbps)", choices=list(FORMATS.keys()))

        # 标准化
        p3 = sub.add_parser("normalize", help="音量标准化")
        p3.add_argument("input", help="输入音频文件")
        p3.add_argument("-o", "--output", default=None)
        p3.add_argument("-l", "--lufs", type=float, default=-14.0)

        # 优化
        p4 = sub.add_parser("optimize", help="智能优化")
        p4.add_argument("input", help="输入音频文件")
        p4.add_argument("-o", "--output", default=None)

        # 元数据
        p5 = sub.add_parser("meta", help="读取元数据")
        p5.add_argument("input", help="输入文件")

        args = parser.parse_args()
        if args.cmd == "v2a":
            r = video_to_audio(args.input, args.output or os.path.dirname(args.input), args.format)
            print(f"{'成功' if r['success'] else '失败'}: {r.get('output', r.get('error', ''))}")
        elif args.cmd == "convert":
            r = convert_audio(args.input, args.output or os.path.dirname(args.input), args.format)
            print(f"{'成功' if r['success'] else '失败'}: {r.get('output', r.get('error', ''))}")
        elif args.cmd == "normalize":
            r = normalize_loudness(args.input, args.output or os.path.dirname(args.input), args.lufs)
            print(f"{'成功' if r['success'] else '失败'}: {r.get('output', r.get('error', ''))}")
        elif args.cmd == "optimize":
            r = smart_optimize(args.input, args.output or os.path.dirname(args.input))
            print(f"{'成功' if r['success'] else '失败'}: {r.get('output', r.get('error', ''))}")
            if r["success"]:
                for f in r.get("issues_fixed", []):
                    print(f"  - {f}")
        elif args.cmd == "meta":
            m = read_metadata(args.input)
            for k, v in m.items():
                print(f"  {k}: {v}")
        else:
            print("请指定子命令: v2a, convert, normalize, optimize, meta")
    else:
        run_gui()
