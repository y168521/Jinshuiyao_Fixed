# -*- coding: utf-8 -*-
"""创作者工具箱子系统调度器

从 core/ai_agent.py 拆出，负责AI文案/语音转文字/TTS配音/OCR/音频提取/去水印等功能的调度。
"""

import logging

logger = logging.getLogger(__name__)


def dispatch_creator(agent, action: str, target: str) -> str:
    """调度创作者工具箱子系统"""
    domain = agent._get_domain("creator")
    if not domain or not agent._initialized.get("creator"):
        return "创作者工具箱未就绪，请稍后再试。"

    try:
        if action == "ai_copy":
            return (
                "【AI智能文案】\n"
                "支持6种文案风格：\n"
                "  - 小红书种草文 / 抖音带货文 / 朋友圈文案\n"
                "  - 公众号文章 / 产品描述 / 视频脚本\n\n"
                "请告诉我主题，例如：\n"
                "  '帮我写一篇关于护肤的小红书文案'\n"
                "  '生成一个咖啡产品的抖音带货文'\n"
                "  '写一段旅游视频脚本'"
            )

        elif action == "stt":
            return (
                "【语音转文字】\n"
                "支持将音频文件转录为文字。\n\n"
                "请提供音频文件路径，支持 WAV 格式。\n"
                "需要安装 speech_recognition 库。"
            )

        elif action == "tts":
            st = domain.status()
            tts_status = st.get('tools', {}).get('tts', '未知')
            return (
                f"【智能配音（TTS）】\n"
                f"状态: {tts_status}\n\n"
                "支持多种中英文语音：\n"
                "  - 中文女声1(晓晓) / 中文女声2(小艺)\n"
                "  - 中文男声1(云希) / 中文男声2(云健)\n"
                "  - 英文女声 / 英文男声\n\n"
                "请提供要配音的文字，例如：\n"
                "  '帮我朗读：今天天气真好'"
            )

        elif action == "ocr":
            return (
                "【图片转文字（OCR）】\n"
                "支持识别图片中的文字（中英混合）。\n\n"
                "请提供图片文件路径。\n"
                "需要安装 pytesseract 和 Pillow 库。"
            )

        elif action == "audio_extract":
            return (
                "【音频提取】\n"
                "从视频中提取音频，支持 MP4/AVI/MKV 等格式。\n\n"
                "请提供视频文件路径。\n"
                "输出格式默认为 MP3。"
            )

        elif action == "watermark":
            return (
                "【去水印】\n"
                "检测并移除图片中的水印。\n\n"
                "请提供图片文件路径。\n"
                "需要安装 opencv-python 和 numpy 库。"
            )

        else:
            st = domain.status()
            tools = st.get('tools', {})
            lines = ["【创作者工具箱】\n"]
            for mode, status in tools.items():
                mode_name = domain.MODES.get(mode, mode)
                lines.append(f"  {mode_name}: {status}")
            lines.append(f"\n输出目录: {st.get('output_dir', '未知')}")
            return "\n".join(lines)
    except Exception as e:
        logger.error("[agent] 创作者工具箱调度异常: %s", e)
        return f"创作者工具箱异常：{e}"
