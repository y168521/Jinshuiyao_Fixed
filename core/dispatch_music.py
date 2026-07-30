# -*- coding: utf-8 -*-
"""音乐领域调度器

从 core/ai_agent.py 拆出，负责音乐库浏览/音频分析/旋律生成等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)

from core.agent_formatters import (
    format_music_result as _fmt_music,
    format_music_analysis as _fmt_music_analysis,
)


def dispatch_music(agent, action: str, target: str) -> str:
    """调度音乐子系统"""
    domain = agent._get_domain("music")
    if not domain or not agent._initialized.get("music"):
        return "音乐子系统未就绪，请稍后再试。"

    try:
        if action == "list":
            # 获取音乐文件列表
            result = domain.fetch()
            if result.get("success"):
                files = result.get("data", [])
                if not files:
                    return "【音乐库】\n当前音乐目录为空。\n可以将音频文件放入 '金水谣数据/music/' 目录。"
                lines = [f"【音乐库】共 {len(files)} 个文件\n"]
                for f in files[:20]:  # 最多显示20个
                    lines.append(f"  {f['name']}  ({f.get('size_mb', 0):.2f}MB)")
                if len(files) > 20:
                    lines.append(f"\n  ... 还有 {len(files) - 20} 个文件")
                lines.append(f"\n音频: {result.get('audio_count', 0)} 个 | 视频: {result.get('video_count', 0)} 个")
                return "\n".join(lines)
            return f"获取音乐列表失败：{result.get('message', '未知错误')}"

        elif action == "analyze":
            # 分析所有音乐文件
            fetch_result = domain.fetch()
            if not fetch_result.get("success") or not fetch_result.get("data"):
                return "没有找到可分析的音频文件。"
            files = [f["path"] for f in fetch_result["data"] if f.get("is_audio")][:5]
            if not files:
                return "没有找到可分析的音频文件（支持MP3/WAV/FLAC等格式）。"
            analysis = domain.analyze(files)
            if analysis.get("success"):
                return _fmt_music_analysis(analysis)
            return f"音频分析失败：{analysis.get('error', '未知错误')}"

        elif action == "generate_melody":
            # 生成音乐旋律
            result = domain.generate(params={"mode": "melody", "style": "pentatonic", "duration": 8})
            if result.get("status") == "ok":
                return _fmt_music(result)
            return f"音乐生成失败：{result.get('summary', '未知错误')}"

        elif action == "convert":
            return ("【格式转换】\n"
                    "请提供要转换的音频文件路径和目标格式。\n"
                    "支持格式: MP3(320kbps), WAV(无损), FLAC(无损), AAC, OGG\n"
                    "示例: 将 'D:\\music\\song.wav' 转为 MP3 格式")

        elif action == "normalize":
            return ("【音量标准化】\n"
                    "支持 EBU R128 音量标准化（默认 -14 LUFS）。\n"
                    "请提供音频文件路径以进行标准化处理。")

        elif action == "optimize":
            return ("【智能优化】\n"
                    "自动检测音频问题并一键修复：\n"
                    "  - 采样率 → 44100Hz\n"
                    "  - 声道 → 立体声\n"
                    "  - 码率 → 320kbps\n"
                    "  - 音量 → -14LUFS\n"
                    "请提供音频文件路径以进行优化。")

        else:
            # 默认：生成一段旋律
            result = domain.generate(params={"mode": "melody"})
            if result.get("status") == "ok":
                return _fmt_music(result)
            return "音乐子系统操作失败"
    except Exception as e:
        logger.error("[agent] 音乐调度异常: %s", e)
        return f"音乐系统异常：{e}"
