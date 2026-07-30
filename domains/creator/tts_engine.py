# -*- coding: utf-8 -*-
"""智能配音（TTS）模块

优先使用 edge-tts（微软免费TTS，音质好，无需API key）。
不可用时优雅降级。
"""
import logging
import os
import asyncio

logger = logging.getLogger(__name__)


class TTSEngine:
    """智能配音引擎

    使用微软 edge-tts 进行高质量语音合成。
    支持多种中英文语音，可调节语速。
    """

    VOICES = {
        'zh_female_1': 'zh-CN-XiaoxiaoNeural',
        'zh_female_2': 'zh-CN-XiaoyiNeural',
        'zh_male_1': 'zh-CN-YunxiNeural',
        'zh_male_2': 'zh-CN-YunjianNeural',
        'en_female': 'en-US-JennyNeural',
        'en_male': 'en-US-GuyNeural',
    }

    def __init__(self):
        self._edge_tts = None  # 延迟加载 edge-tts

    def _check_available(self):
        """检查 edge-tts 是否可用"""
        if self._edge_tts is None:
            try:
                import edge_tts
                self._edge_tts = edge_tts
                logger.info("edge-tts 已加载")
            except ImportError:
                logger.info("edge-tts 未安装，TTS将使用降级模式")
                self._edge_tts = False
        return self._edge_tts is not False

    def synthesize(self, text, output_path, voice='zh_female_1', speed=1.0):
        """合成语音

        Args:
            text: 要合成的文本
            output_path: 输出音频文件路径
            voice: 语音ID，默认中文女声1
            speed: 语速，1.0为正常，0.5为半速，2.0为倍速

        Returns:
            dict: {
                'audio_path': '输出文件路径',
                'duration': 30,
                'size_bytes': 500000,
                'voice': 'zh-CN-XiaoxiaoNeural',
                'speed': 1.0,
            }
        """
        voice_id = self.VOICES.get(voice, voice)

        if not self._check_available():
            return self._degraded_synthesize(text, output_path, voice_id, speed)

        try:
            # edge-tts 是异步库，需要在事件循环中运行
            rate_str = f'+{int((speed - 1) * 100)}%' if speed >= 1 else f'{int((speed - 1) * 100)}%'

            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 运行异步合成
            loop = asyncio.new_event_loop()
            try:
                communicate = self._edge_tts.Communicate(text, voice_id, rate=rate_str)
                loop.run_until_complete(communicate.save(output_path))
            finally:
                loop.close()

            # 获取文件信息
            size_bytes = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

            return {
                'audio_path': output_path,
                'duration': self._estimate_duration(text, speed),
                'size_bytes': size_bytes,
                'voice': voice_id,
                'speed': speed,
                'mode': 'edge_tts',
            }
        except Exception as e:
            logger.warning("TTS合成失败: %s", e)
            return self._degraded_synthesize(text, output_path, voice_id, speed, error=str(e))

    def list_voices(self):
        """列出可用语音

        Returns:
            list: [{'id': 'zh-CN-XiaoxiaoNeural', 'name': '晓晓', 'lang': 'zh-CN'}, ...]
        """
        if not self._check_available():
            # 返回内置列表
            return [
                {'id': v, 'name': k, 'lang': v.split('-')[0:2], 'available': False}
                for k, v in self.VOICES.items()
            ]

        try:
            loop = asyncio.new_event_loop()
            try:
                voices = loop.run_until_complete(self._edge_tts.list_voices())
            finally:
                loop.close()

            result = []
            for v in voices:
                result.append({
                    'id': v.get('ShortName', ''),
                    'name': v.get('FriendlyName', ''),
                    'lang': v.get('Locale', ''),
                    'gender': v.get('Gender', ''),
                    'available': True,
                })
            return result
        except Exception as e:
            logger.warning("获取语音列表失败: %s", e)
            return [
                {'id': v, 'name': k, 'lang': v.split('-')[0:2], 'available': False}
                for k, v in self.VOICES.items()
            ]

    def _estimate_duration(self, text, speed=1.0):
        """估算语音时长（秒）"""
        # 中文平均语速约 4 字/秒
        char_count = len(text)
        base_duration = char_count / 4.0
        return round(base_duration / max(speed, 0.1), 1)

    def _degraded_synthesize(self, text, output_path, voice_id, speed, error=None):
        """降级模式返回结果"""
        msg = 'TTS功能需要安装 edge-tts 库 (pip install edge-tts)'
        if error:
            msg = f'合成失败: {error}'

        return {
            'audio_path': output_path,
            'duration': 0,
            'size_bytes': 0,
            'voice': voice_id,
            'speed': speed,
            'error': msg,
            'mode': 'degraded',
        }