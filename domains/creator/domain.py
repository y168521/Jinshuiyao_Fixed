# -*- coding: utf-8 -*-
"""创作者工具箱子系统 - 金水谣内核适配层

提供六大创作者工具的统一入口：
  AI文案生成 / 语音转文字 / 智能配音 / OCR识别 / 音频提取 / 去水印

所有工具采用延迟加载，缺失依赖时优雅降级不报错。
"""
import os
import logging
from datetime import datetime
from domains.base import DomainBase

logger = logging.getLogger(__name__)


class CreatorDomain(DomainBase):
    """创作者工具箱子系统

    集成AI文案、语音转文字、TTS配音、OCR、音频提取、去水印六大工具。
    完全遵循 DomainBase 契约，可由内核统一调度。
    """
    DOMAIN_ID = "creator"
    DESCRIPTION = "创作者工具箱（AI文案/语音转文字/TTS配音/OCR/音频提取/去水印）"

    # 7种工具模式
    MODES = {
        'ai_copy': 'AI智能文案',
        'stt': '语音转文字',
        'tts': '智能配音',
        'ocr': '图片转文字',
        'audio_extract': '音频提取',
        'watermark': '去水印',
        'batch': '批量处理',
    }

    def __init__(self, config=None):
        """初始化创作者工具箱子系统

        Args:
            config: 子系统配置字典
        """
        super().__init__(config)
        self.output_dir = self.config.get(
            "output_dir", os.path.join("金水谣数据", "creator_output")
        )
        self._copywriter = None
        self._stt = None
        self._tts = None
        self._ocr = None
        self._audio_extractor = None
        self._watermark_remover = None
        self._ai_service = None
        self._tool_status = {}  # 各工具可用状态
        self._last_run = None
        self._review_count = 0
        self._temp_files = []  # 临时文件列表，用于teardown清理
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def setup(self):
        """检测各工具依赖是否可用（缺依赖不报错只降级）

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 检测AI服务
            try:
                from core.ai_service import get_ai_service
                self._ai_service = get_ai_service()
                self._tool_status['ai_service'] = (
                    self._ai_service.is_available if self._ai_service else False
                )
                logger.info("AI服务状态: %s", self._tool_status['ai_service'])
            except ImportError:
                self._tool_status['ai_service'] = False

            # 检测各工具依赖（仅检测，不实例化）
            self._tool_status['edge_tts'] = self._check_import('edge_tts')
            self._tool_status['speech_recognition'] = self._check_import('speech_recognition')
            self._tool_status['pytesseract'] = self._check_import('pytesseract')
            self._tool_status['PIL'] = self._check_import('PIL')
            self._tool_status['moviepy'] = self._check_import('moviepy.editor')
            self._tool_status['cv2'] = self._check_import('cv2')

            # 初始化各工具实例
            self._copywriter = None  # 按需延迟加载
            self._stt = None
            self._tts = None
            self._ocr = None
            self._audio_extractor = None
            self._watermark_remover = None

            self._initialized = True
            available = sum(1 for v in self._tool_status.values() if v)
            logger.info(
                "创作者工具箱初始化完成 (%d/%d 依赖可用)",
                available, len(self._tool_status)
            )
            return True
        except Exception as e:
            logger.error("创作者工具箱初始化失败: %s", e)
            return False

    def teardown(self):
        """清理临时文件

        Returns:
            bool: 关闭是否成功
        """
        try:
            # 清理临时文件
            for f in self._temp_files:
                try:
                    if os.path.isfile(f):
                        os.unlink(f)
                        logger.debug("已清理临时文件: %s", f)
                except OSError:
                    pass
            self._temp_files = []
            self._initialized = False
            logger.info("创作者工具箱已关闭")
            return True
        except Exception as e:
            logger.error("创作者工具箱关闭失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 核心流程
    # ------------------------------------------------------------------

    def fetch(self, **kwargs):
        """从知识库/输出目录获取已有素材

        Returns:
            dict: {"success": bool, "data": [...], "message": str}
        """
        try:
            materials = []

            # 扫描输出目录中的文件
            if os.path.isdir(self.output_dir):
                for f in sorted(os.listdir(self.output_dir)):
                    fpath = os.path.join(self.output_dir, f)
                    if os.path.isfile(fpath):
                        size = os.path.getsize(fpath)
                        materials.append({
                            'name': f,
                            'path': fpath,
                            'size_bytes': size,
                            'type': self._guess_type(f),
                        })

            self._last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return {
                "success": True,
                "data": materials,
                "message": f"获取 {len(materials)} 个素材文件",
                "output_dir": self.output_dir,
            }
        except Exception as e:
            logger.error("获取素材失败: %s", e)
            return {"success": False, "data": [], "message": str(e)}

    def analyze(self, data, **kwargs):
        """分析素材（图片/音频/视频）

        Args:
            data: fetch() 返回的数据或文件路径
            **kwargs: 分析参数

        Returns:
            dict: 分析结果
        """
        if not data:
            return {
                "status": "no_data",
                "analysis": [],
                "message": "无数据可分析",
            }

        results = []
        items = data if isinstance(data, list) else [data]

        for item in items:
            if isinstance(item, dict) and 'path' in item:
                path = item['path']
                ftype = item.get('type', self._guess_type(path))
            elif isinstance(item, str):
                path = item
                ftype = self._guess_type(path)
            else:
                continue

            analysis = {
                'path': path,
                'type': ftype,
                'name': os.path.basename(path),
            }

            # 根据类型分析
            if ftype in ('image', 'png', 'jpg'):
                ocr_result = self.recognize_image(path)
                analysis['ocr'] = ocr_result
                analysis['has_text'] = bool(ocr_result.get('text'))

            elif ftype in ('audio', 'mp3', 'wav'):
                stt_result = self.transcribe_audio(path)
                analysis['stt'] = stt_result
                analysis['has_transcript'] = bool(stt_result.get('text'))

            elif ftype in ('video', 'mp4', 'avi'):
                extract_result = self.extract_audio(path)
                analysis['audio_extract'] = extract_result

            results.append(analysis)

        return {
            "status": "ok" if results else "no_result",
            "analysis": results,
            "total": len(results),
            "message": f"分析了 {len(results)} 个文件",
        }

    def generate(self, params=None, **kwargs):
        """生成内容（文案/配音/OCR结果）

        Args:
            params: 生成参数，支持多种模式
            **kwargs: 额外参数

        Returns:
            dict: 生成结果
        """
        if not params:
            return {
                "predictions": [],
                "summary": "无生成参数",
                "status": "no_params",
                "domain_id": self.DOMAIN_ID,
            }

        mode = params.get('mode', 'ai_copy')
        predictions = []

        if mode == 'ai_copy':
            topic = params.get('topic', '')
            style = params.get('style', 'xiaohongshu')
            result = self.write_copy(topic, style)
            predictions.append(result)

        elif mode == 'stt':
            audio_path = params.get('audio_path', '')
            result = self.transcribe_audio(audio_path)
            predictions.append(result)

        elif mode == 'tts':
            text = params.get('text', '')
            output_path = params.get('output_path', '')
            voice = params.get('voice', 'zh_female_1')
            result = self.text_to_speech(text, output_path, voice)
            predictions.append(result)

        elif mode == 'ocr':
            image_path = params.get('image_path', '')
            result = self.recognize_image(image_path)
            predictions.append(result)

        elif mode == 'audio_extract':
            video_path = params.get('video_path', '')
            result = self.extract_audio(video_path)
            predictions.append(result)

        elif mode == 'watermark':
            image_path = params.get('image_path', '')
            result = self.remove_watermark(image_path)
            predictions.append(result)

        elif mode == 'batch':
            # 批量文案生成
            topic = params.get('topic', '')
            styles = params.get('styles', None)
            results = self._get_copywriter().generate_batch(topic, styles)
            predictions.extend(results)

        self._last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "predictions": predictions,
            "summary": f"模式[{mode}] 生成 {len(predictions)} 条结果",
            "status": "ok" if predictions else "empty",
            "domain_id": self.DOMAIN_ID,
        }

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘生成效果

        Args:
            predictions: 生成记录列表
            actual: 实际效果数据（可选）

        Returns:
            dict: 复盘结果
        """
        self._review_count += 1
        try:
            if not predictions:
                return {
                    "reviews": 0,
                    "hits": 0,
                    "updated": True,
                    "metrics": {},
                    "status": "ok",
                    "review_count": self._review_count,
                }

            total = len(predictions)
            # 统计各模式数量
            mode_counts = {}
            for p in predictions:
                mode = p.get('mode', p.get('style', 'unknown'))
                mode_counts[mode] = mode_counts.get(mode, 0) + 1

            # 简单质量评估
            quality_scores = []
            for p in predictions:
                if p.get('mode') == 'template':
                    quality_scores.append(0.5)
                elif p.get('mode') == 'ai':
                    quality_scores.append(0.85)
                elif p.get('mode') in ('edge_tts', 'tesseract', 'google_stt'):
                    quality_scores.append(0.9)
                elif p.get('mode') == 'degraded':
                    quality_scores.append(0.2)
                else:
                    quality_scores.append(0.6)

            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

            return {
                "reviews": total,
                "hits": int(total * avg_quality),
                "updated": True,
                "metrics": {
                    "total_generated": total,
                    "mode_distribution": mode_counts,
                    "avg_quality_score": round(avg_quality, 2),
                    "review_count": self._review_count,
                },
                "status": "ok",
                "review_count": self._review_count,
            }
        except Exception as e:
            logger.error("创作者工具箱复盘失败: %s", e)
            return {
                "reviews": 0,
                "hits": 0,
                "updated": False,
                "error": str(e),
            }

    def status(self):
        """返回各工具可用状态

        Returns:
            dict: 健康状态信息
        """
        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "description": self.DESCRIPTION,
            "tools": {
                "ai_copy": "可用(AI)" if self._tool_status.get('ai_service') else "可用(模板)",
                "stt": "可用" if self._tool_status.get('speech_recognition') else "降级",
                "tts": "可用" if self._tool_status.get('edge_tts') else "降级",
                "ocr": "可用" if (self._tool_status.get('pytesseract') and self._tool_status.get('PIL')) else "降级",
                "audio_extract": "可用" if (self._tool_status.get('moviepy') or self._check_ffmpeg()) else "降级",
                "watermark": "可用" if self._tool_status.get('cv2') else "降级",
            },
            "dependencies": dict(self._tool_status),
            "output_dir": self.output_dir,
            "last_run": self._last_run,
            "review_count": self._review_count,
            "modes": self.MODES,
            "errors": [],
        }

    # ------------------------------------------------------------------
    # 额外方法 - 各工具快捷入口
    # ------------------------------------------------------------------

    def write_copy(self, topic, style='xiaohongshu'):
        """AI文案生成

        Args:
            topic: 文案主题
            style: 文案风格

        Returns:
            dict: 生成结果
        """
        writer = self._get_copywriter()
        return writer.generate(topic, style=style)

    def transcribe_audio(self, audio_path):
        """语音转文字

        Args:
            audio_path: 音频文件路径

        Returns:
            dict: 转写结果
        """
        stt = self._get_stt()
        return stt.transcribe(audio_path)

    def text_to_speech(self, text, output_path=None, voice='zh_female_1'):
        """智能配音

        Args:
            text: 要合成的文本
            output_path: 输出路径，None自动生成
            voice: 语音ID

        Returns:
            dict: 合成结果
        """
        if not output_path:
            output_path = os.path.join(
                self.output_dir,
                f'tts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.mp3'
            )
        tts = self._get_tts()
        return tts.synthesize(text, output_path, voice=voice)

    def recognize_image(self, image_path):
        """OCR识别

        Args:
            image_path: 图片文件路径

        Returns:
            dict: 识别结果
        """
        ocr = self._get_ocr()
        return ocr.recognize(image_path)

    def extract_audio(self, video_path):
        """从视频提取音频

        Args:
            video_path: 视频文件路径

        Returns:
            dict: 提取结果
        """
        extractor = self._get_audio_extractor()
        return extractor.extract(video_path, output_dir=self.output_dir)

    def remove_watermark(self, image_path):
        """去水印

        Args:
            image_path: 图片文件路径

        Returns:
            dict: 处理结果
        """
        remover = self._get_watermark_remover()
        return remover.remove(image_path, output_dir=self.output_dir)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_copywriter(self):
        """延迟加载AI文案生成器"""
        if self._copywriter is None:
            from domains.creator.ai_copywriter import AICopywriter
            self._copywriter = AICopywriter()
        return self._copywriter

    def _get_stt(self):
        """延迟加载语音转文字"""
        if self._stt is None:
            from domains.creator.speech_to_text import SpeechToText
            self._stt = SpeechToText()
        return self._stt

    def _get_tts(self):
        """延迟加载TTS引擎"""
        if self._tts is None:
            from domains.creator.tts_engine import TTSEngine
            self._tts = TTSEngine()
        return self._tts

    def _get_ocr(self):
        """延迟加载OCR引擎"""
        if self._ocr is None:
            from domains.creator.ocr_engine import OCREngine
            self._ocr = OCREngine()
        return self._ocr

    def _get_audio_extractor(self):
        """延迟加载音频提取器"""
        if self._audio_extractor is None:
            from domains.creator.audio_extractor import AudioExtractor
            self._audio_extractor = AudioExtractor()
        return self._audio_extractor

    def _get_watermark_remover(self):
        """延迟加载去水印器"""
        if self._watermark_remover is None:
            from domains.creator.watermark_remover import WatermarkRemover
            self._watermark_remover = WatermarkRemover()
        return self._watermark_remover

    @staticmethod
    def _check_import(module_name):
        """检查模块是否可导入"""
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_ffmpeg():
        """检查 ffmpeg 是否可用"""
        import shutil
        return shutil.which('ffmpeg') is not None

    @staticmethod
    def _guess_type(filename):
        """根据文件名猜测类型"""
        ext = os.path.splitext(filename)[1].lower()
        type_map = {
            '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio',
            '.aac': 'audio', '.ogg': 'audio', '.m4a': 'audio',
            '.mp4': 'video', '.avi': 'video', '.mkv': 'video',
            '.mov': 'video', '.flv': 'video', '.wmv': 'video',
            '.png': 'image', '.jpg': 'image', '.jpeg': 'image',
            '.bmp': 'image', '.webp': 'image', '.gif': 'image',
            '.txt': 'text', '.json': 'text',
        }
        return type_map.get(ext, 'unknown')