# -*- coding: utf-8 -*-
"""图片转文字（OCR）模块

优先使用 pytesseract（本地OCR）。
不可用时优雅降级。
"""
import logging
import os
import base64
import tempfile

logger = logging.getLogger(__name__)


class OCREngine:
    """OCR文字识别引擎

    优先使用 pytesseract + PIL 进行本地OCR识别。
    不可用时返回降级提示。
    """

    def __init__(self):
        self._tesseract_available = None  # 延迟检测

    def _check_available(self):
        """检查 pytesseract 是否可用"""
        if self._tesseract_available is None:
            try:
                import pytesseract
                from PIL import Image
                self._tesseract_available = True
                logger.info("pytesseract + PIL 已加载")
            except ImportError:
                logger.info("pytesseract 或 PIL 未安装，OCR将使用降级模式")
                self._tesseract_available = False
        return self._tesseract_available

    def recognize(self, image_path, lang='chi_sim+eng'):
        """识别图片文字

        Args:
            image_path: 图片文件路径
            lang: 识别语言，默认中英混合

        Returns:
            dict: {
                'text': '识别出的文字',
                'blocks': [{'text': '...', 'bbox': [x1,y1,x2,y2]}],
                'confidence': 0.9,
                'lang': 'chi_sim+eng',
            }
        """
        if not self._check_available():
            return self._degraded_result(image_path, lang)

        if not os.path.isfile(image_path):
            return {
                'text': '',
                'blocks': [],
                'confidence': 0,
                'lang': lang,
                'error': f'文件不存在: {image_path}',
                'mode': 'error',
            }

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)

            # 使用 pytesseract 识别
            data = pytesseract.image_to_data(
                img, lang=lang, output_type=pytesseract.Output.DICT
            )

            # 提取文字和位置信息
            text_parts = []
            blocks = []
            confidences = []

            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i].strip()
                if text:
                    conf = int(data['conf'][i])
                    if conf > 0:
                        text_parts.append(text)
                        blocks.append({
                            'text': text,
                            'bbox': [
                                data['left'][i],
                                data['top'][i],
                                data['left'][i] + data['width'][i],
                                data['top'][i] + data['height'][i],
                            ],
                            'confidence': conf / 100.0,
                        })
                        confidences.append(conf)

            full_text = '\n'.join(text_parts)
            avg_conf = sum(confidences) / len(confidences) / 100.0 if confidences else 0

            return {
                'text': full_text,
                'blocks': blocks,
                'confidence': round(avg_conf, 2),
                'lang': lang,
                'mode': 'tesseract',
            }
        except Exception as e:
            logger.warning("OCR识别失败: %s", e)
            return self._degraded_result(image_path, lang, error=str(e))

    def recognize_base64(self, base64_data, lang='chi_sim+eng'):
        """从base64数据识别

        Args:
            base64_data: base64编码的图片数据
            lang: 识别语言

        Returns:
            dict: 识别结果
        """
        try:
            # 解码base64
            img_bytes = base64.b64decode(base64_data)

            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            result = self.recognize(tmp_path, lang=lang)

            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            return result
        except Exception as e:
            logger.error("base64 OCR失败: %s", e)
            return {
                'text': '',
                'blocks': [],
                'confidence': 0,
                'lang': lang,
                'error': f'base64解码或识别失败: {e}',
                'mode': 'error',
            }

    def _degraded_result(self, image_path, lang, error=None):
        """降级模式返回结果"""
        msg = 'OCR功能需要安装 pytesseract 和 Pillow 库'
        if error:
            msg = f'识别失败: {error}'

        return {
            'text': '',
            'blocks': [],
            'confidence': 0,
            'lang': lang,
            'error': msg,
            'mode': 'degraded',
        }