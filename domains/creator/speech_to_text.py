# -*- coding: utf-8 -*-
"""语音转文字模块

支持本地识别（speech_recognition）+ 降级模式。
使用免费的 Google Speech Recognition API。
"""
import logging
import os

logger = logging.getLogger(__name__)


class SpeechToText:
    """语音转文字引擎

    优先使用 speech_recognition 库进行本地识别。
    不可用时优雅降级，返回提示信息。
    """

    def __init__(self):
        self._recognizer = None  # 延迟加载 speech_recognition

    def _get_recognizer(self):
        """延迟加载 speech_recognition"""
        if self._recognizer is None:
            try:
                import speech_recognition as sr
                self._recognizer = sr.Recognizer()
                logger.info("speech_recognition 已加载")
            except ImportError:
                logger.info("speech_recognition 未安装，语音转文字将使用降级模式")
                self._recognizer = False  # 标记为不可用
        return self._recognizer if self._recognizer else None

    def transcribe(self, audio_path, language='zh-CN'):
        """转录音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言代码，默认中文

        Returns:
            dict: {
                'text': '转写文本',
                'language': 'zh-CN',
                'duration': 120.5,
                'segments': [{'start': 0, 'end': 10, 'text': '第一段'}],
                'confidence': 0.85,
            }
        """
        recognizer = self._get_recognizer()
        if recognizer is None:
            return self._degraded_result(audio_path, language)

        try:
            import speech_recognition as sr

            with sr.AudioFile(audio_path) as source:
                audio_data = recognizer.record(source)

            # 使用 Google 免费语音识别
            text = recognizer.recognize_google(audio_data, language=language)

            # 获取音频时长
            duration = self._get_audio_duration(audio_path)

            # 简单分段（按句号分）
            segments = self._split_segments(text)

            return {
                'text': text,
                'language': language,
                'duration': duration,
                'segments': segments,
                'confidence': 0.8,  # Google API 不返回置信度时使用默认值
                'mode': 'google_stt',
            }
        except Exception as e:
            logger.warning("语音转写失败: %s", e)
            return self._degraded_result(audio_path, language, error=str(e))

    def transcribe_from_url(self, audio_url, language='zh-CN'):
        """从URL转录

        Args:
            audio_url: 音频文件URL
            language: 语言代码

        Returns:
            dict: 转写结果
        """
        # 尝试下载后转录
        try:
            import tempfile
            import urllib.request

            # 下载到临时文件
            suffix = os.path.splitext(audio_url)[1] or '.wav'
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            urllib.request.urlretrieve(audio_url, tmp_path)
            result = self.transcribe(tmp_path, language=language)

            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            result['source_url'] = audio_url
            return result
        except Exception as e:
            logger.error("从URL转录失败: %s", e)
            return {
                'text': '',
                'language': language,
                'duration': 0,
                'segments': [],
                'confidence': 0,
                'error': f'下载或转录失败: {e}',
                'mode': 'error',
            }

    def _get_audio_duration(self, audio_path):
        """获取音频时长（秒）"""
        try:
            import wave
            with wave.open(audio_path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return round(frames / float(rate), 1) if rate > 0 else 0
        except Exception:
            pass

        try:
            # 尝试用文件大小粗略估算
            size = os.path.getsize(audio_path)
            return round(size / 16000, 1)  # 假设16kHz单声道
        except OSError:
            return 0

    def _split_segments(self, text):
        """简单文本分段"""
        if not text:
            return []

        segments = []
        # 按标点分段
        import re
        parts = re.split(r'[。！？\n]', text)
        pos = 0
        for part in parts:
            part = part.strip()
            if part:
                start = pos
                end = pos + len(part)
                segments.append({
                    'start': start,
                    'end': end,
                    'text': part,
                })
                pos = end + 1
        return segments

    def _degraded_result(self, audio_path, language, error=None):
        """降级模式返回结果"""
        duration = self._get_audio_duration(audio_path) if os.path.isfile(audio_path) else 0
        msg = '语音转文字功能需要安装 speech_recognition 库'
        if error:
            msg = f'转写失败: {error}'

        return {
            'text': '',
            'language': language,
            'duration': duration,
            'segments': [],
            'confidence': 0,
            'error': msg,
            'mode': 'degraded',
        }