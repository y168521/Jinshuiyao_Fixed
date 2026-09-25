# -*- coding: utf-8 -*-
"""音频高级处理：音量标准化、质量分析、智能优化"""
import os
import sys
import json
import time
import logging
import subprocess
import tempfile

from ._core import FFMPEG_PATH, FORMATS, _run_ffmpeg
from .ffmpeg_ops import read_metadata, write_metadata

logger = logging.getLogger(__name__)


def _make_output_path(input_path, output_dir, suffix, output_format=None):
    """构建输出文件路径"""
    if output_dir is None:
        output_dir = os.path.dirname(input_path)
    basename = os.path.splitext(os.path.basename(input_path))[0]
    ext = os.path.splitext(input_path)[1]
    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
    return os.path.join(output_dir, basename + suffix + ext)


def _apply_dual_pass_normalize(input_path, output_path, measured, target_lufs,
                               progress_callback, start_time):
    """第二遍：应用测量值进行线性标准化"""
    input_i = measured.get("input_i", target_lufs)
    input_lra = max(measured.get("input_lra", 11), 0.1)
    input_tp = measured.get("input_tp", -1.5)
    target_offset = measured.get("target_offset", 0)
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
                "mode": "dual_pass", "original_lufs": input_i,
                "target_lufs": target_lufs,
            }
        return {"success": False, "error": "第二遍标准化失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}


def normalize_loudness(input_path, output_dir=None, target_lufs=-14.0,
                        output_format=None, progress_callback=None):
    """EBU R128 音量标准化（两遍编码）"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}

    output_path = _make_output_path(input_path, output_dir, "_normalized", output_format)
    start_time = time.time()
    if progress_callback:
        progress_callback(5, "分析音量...")

    measured = _analyze_loudness(input_path, target_lufs)
    if not measured:
        return _single_pass_normalize(input_path, output_path, target_lufs,
                                      progress_callback, start_time)

    if progress_callback:
        progress_callback(40, "应用标准化...")
    return _apply_dual_pass_normalize(input_path, output_path, measured,
                                      target_lufs, progress_callback, start_time)


def _analyze_loudness(input_path, target_lufs):
    """第一遍：分析音量，返回测量值 dict 或空 dict"""
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
        try:
            analyze_cmd = [
                FFMPEG_PATH, "-i", input_path,
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
                "-f", "null", "-"
            ]
            p = subprocess.Popen(analyze_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            _, stderr = p.communicate()
        except Exception:
            return {}
    finally:
        if os.path.exists(tmp_nul):
            try:
                os.remove(tmp_nul)
            except Exception as _e:
                logger.debug("remove tmp_nul failed: %s", _e)

    return _parse_loudnorm_json(stderr)


def _parse_loudnorm_json(stderr):
    """从 loudnorm 输出的 stderr 中解析 JSON 测量值"""
    try:
        lines = stderr.decode("utf-8", errors="replace").strip().split("\n")
        for line in lines:
            if '"input_i"' in line:
                json_start = line.find("{")
                if json_start >= 0:
                    json_str = line[json_start:]
                    brace_count, end = 0, 0
                    for i, c in enumerate(json_str):
                        if c == "{":
                            brace_count += 1
                        elif c == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end = i + 1
                                break
                    if end > 0:
                        return json.loads(json_str[:end])
    except Exception as _e:
        logger.debug("parse loudnorm json failed: %s", _e)
    return {}


def _single_pass_normalize(input_path, output_path, target_lufs, progress_callback, start_time):
    """单遍标准化（解析失败时的降级）"""
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
        return {"success": False, "error": "标准化失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _check_audio_issues(report, sr, ch, br, duration, codec):
    """根据音频参数检测质量问题，追加到 report['issues']"""
    if sr < 44100:
        report["issues"].append({"type": "sample_rate",
            "msg": f"采样率{sr}Hz偏低，建议>=44100Hz",
            "fix": "resample", "value": 44100, "score": -20})
    elif sr > 48000:
        report["issues"].append({"type": "sample_rate",
            "msg": f"采样率{sr}Hz过高，建议44100Hz",
            "fix": "resample", "value": 44100, "score": -5})
    if ch < 2:
        report["issues"].append({"type": "channels",
            "msg": f"{ch}声道，建议双声道(stereo)",
            "fix": "stereo", "value": 2, "score": -15})
    if codec == "mp3" and br < 256:
        report["issues"].append({"type": "bitrate",
            "msg": f"MP3码率{br:.0f}kbps偏低，建议>=320kbps",
            "fix": "bitrate", "value": 320, "score": -15})
    if duration < 30:
        report["issues"].append({"type": "duration",
            "msg": f"时长{duration:.0f}秒，可能过短",
            "fix": "none", "score": -5})


def _select_codec(input_path, output_format):
    """根据输出格式和输入扩展名选择编码器及参数，返回 (ext, codec, args)"""
    if output_format:
        fmt = FORMATS.get(output_format)
        ext = fmt["ext"] if fmt else ".mp3"
        codec = fmt["codec"] if fmt else "libmp3lame"
        args = fmt.get("args", []) if fmt else ["-b:a", "320k"]
        return ext, codec, args
    ext = os.path.splitext(input_path)[1] or ".mp3"
    if ext in (".wav", ".flac"):
        return ext, ext.replace(".", ""), []
    if ext == ".ogg":
        return ext, "libvorbis", ["-b:a", "320k", "-ar", "44100", "-ac", "2"]
    return ext, "libmp3lame", ["-b:a", "320k"]


def analyze_audio(filepath):
    """全面分析音频质量，返回诊断报告"""
    report = {"file": os.path.basename(filepath), "issues": [], "score": 100}

    ffprobe = FFMPEG_PATH.replace("ffmpeg", "ffprobe") if FFMPEG_PATH else "ffprobe"
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
                    report.update({"sample_rate": sr, "channels": ch,
                                   "bitrate": br, "duration": duration,
                                   "codec": s.get("codec_name", "")})
                    _check_audio_issues(report, sr, ch, br, duration,
                                        s.get("codec_name"))
            fmt = data.get("format", {})
            report["size_mb"] = int(fmt.get("size", 0)) / (1024 * 1024)
    except Exception:
        report["issues"].append({"type": "info_error", "msg": "无法读取音频信息",
                                  "fix": "none", "score": -30})

    for issue in report["issues"]:
        report["score"] += issue.get("score", 0)
    report["score"] = max(0, report["score"])
    return report


def smart_optimize(input_path, output_dir=None, output_format=None, progress_callback=None):
    """智能一键优化：自动检测问题并修复"""
    if FFMPEG_PATH is None:
        return {"success": False, "error": "未找到FFmpeg"}

    report = analyze_audio(input_path)
    filters, issues_fixed = _build_optimize_filters(report)
    ext, codec, args = _select_codec(input_path, output_format)
    output_path = _make_output_path(input_path, output_dir, "_optimized")
    output_path = os.path.splitext(output_path)[0] + ext

    if progress_callback:
        progress_callback(10, "正在优化...")

    cmd = [FFMPEG_PATH, "-i", input_path, "-af", filters,
           "-c:a", codec, *args, "-ar", "44100", "-y", output_path]

    start_time = time.time()
    try:
        process = _run_ffmpeg(cmd)
        process.wait()
        elapsed = time.time() - start_time
        if process.returncode == 0 and os.path.exists(output_path):
            if progress_callback:
                progress_callback(100, "优化完成")
            old_meta = read_metadata(input_path)
            if not old_meta.get("error"):
                write_metadata(output_path, **old_meta)
            return {
                "success": True, "output": output_path, "time": elapsed,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024),
                "issues_fixed": issues_fixed or ["音量标准化到-14LUFS"],
                "original_report": report,
            }
        return {"success": False, "error": "优化处理失败", "time": elapsed}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}


def _build_optimize_filters(report):
    """根据分析报告构建优化滤镜链"""
    filters = []
    issues_fixed = []
    sr = report.get("sample_rate", 44100)
    if sr != 44100:
        filters.append("aresample=44100")
        issues_fixed.append(f"采样率 {sr}Hz -> 44100Hz")
    ch = report.get("channels", 2)
    if ch < 2:
        filters.append("aformat=channel_layouts=stereo")
        issues_fixed.append("声道 单声道 -> 立体声")
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    filter_chain = ",".join(filters) + "," + loudnorm if filters else loudnorm
    return filter_chain, issues_fixed
