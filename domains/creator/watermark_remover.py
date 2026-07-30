# -*- coding: utf-8 -*-
"""去水印模块

使用 OpenCV 进行基础水印检测和移除。
不可用时优雅降级。
"""
import logging
import os

logger = logging.getLogger(__name__)


class WatermarkRemover:
    """水印检测与移除引擎

    使用 OpenCV 进行图像处理：
    - 检测：通过透明度通道和边缘检测定位水印
    - 移除：使用图像修复（inpaint）技术
    """

    def __init__(self):
        self._cv2_available = None
        self._numpy_available = None

    def _check_available(self):
        """检查 OpenCV 是否可用"""
        if self._cv2_available is None:
            try:
                import cv2
                import numpy as np
                self._cv2_available = True
                self._numpy_available = True
                logger.info("OpenCV + NumPy 已加载")
            except ImportError as e:
                logger.info("OpenCV 或 NumPy 未安装: %s", e)
                self._cv2_available = False
                self._numpy_available = False
        return self._cv2_available

    def detect(self, image_path):
        """检测水印位置

        Args:
            image_path: 图片文件路径

        Returns:
            dict: {
                'detected': True,
                'regions': [{'x': 10, 'y': 10, 'w': 100, 'h': 30}],
                'method': 'alpha_channel',
            }
        """
        if not self._check_available():
            return {
                'detected': False,
                'regions': [],
                'method': 'none',
                'error': '需要安装 opencv-python 和 numpy',
                'mode': 'degraded',
            }

        if not os.path.isfile(image_path):
            return {
                'detected': False,
                'regions': [],
                'method': 'none',
                'error': f'文件不存在: {image_path}',
                'mode': 'error',
            }

        try:
            import cv2
            import numpy as np

            img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)

            if img is None:
                return {
                    'detected': False,
                    'regions': [],
                    'method': 'none',
                    'error': '无法读取图片',
                    'mode': 'error',
                }

            regions = []
            method = 'none'

            # 方法1：通过透明度通道检测水印（PNG）
            if len(img.shape) == 3 and img.shape[2] == 4:
                alpha = img[:, :, 3]
                # 查找半透明区域（水印通常是半透明的）
                _, thresh = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for cnt in contours:
                    x, y, w, h = cv2.boundingRect(cnt)
                    # 过滤太小的区域（噪点）
                    if w > 20 and h > 10:
                        regions.append({'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)})
                method = 'alpha_channel'

            # 方法2：如果没有透明通道或没找到，尝试边缘检测
            if not regions:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
                # 检测右下角区域（常见水印位置）
                h_img, w_img = gray.shape[:2]
                roi = gray[max(0, h_img - 100):h_img, max(0, w_img - 300):w_img]

                # 使用Canny边缘检测
                edges = cv2.Canny(roi, 50, 150)
                if edges.sum() > 0:
                    # 有边缘活动，可能存在水印
                    regions.append({
                        'x': max(0, w_img - 300),
                        'y': max(0, h_img - 100),
                        'w': 300,
                        'h': 100,
                    })
                    method = 'edge_detection'

            return {
                'detected': len(regions) > 0,
                'regions': regions,
                'method': method,
                'mode': 'opencv',
            }
        except Exception as e:
            logger.warning("水印检测失败: %s", e)
            return {
                'detected': False,
                'regions': [],
                'method': 'none',
                'error': str(e),
                'mode': 'error',
            }

    def remove(self, image_path, output_dir=None):
        """去除图片水印

        Args:
            image_path: 图片文件路径
            output_dir: 输出目录，None表示同目录

        Returns:
            dict: {
                'image_path': '输出文件路径',
                'method': 'inpaint',
                'watermark_detected': True,
            }
        """
        if not self._check_available():
            return {
                'image_path': '',
                'method': 'none',
                'watermark_detected': False,
                'error': '需要安装 opencv-python 和 numpy',
                'mode': 'degraded',
            }

        if not os.path.isfile(image_path):
            return {
                'image_path': '',
                'method': 'none',
                'watermark_detected': False,
                'error': f'文件不存在: {image_path}',
                'mode': 'error',
            }

        try:
            import cv2
            import numpy as np

            # 先检测水印
            detection = self.detect(image_path)

            # 确定输出路径
            if output_dir is None:
                output_dir = os.path.dirname(image_path) or '.'
            os.makedirs(output_dir, exist_ok=True)

            base_name = os.path.splitext(os.path.basename(image_path))[0]
            output_path = os.path.join(output_dir, f'{base_name}_no_watermark.png')

            img = cv2.imread(image_path)
            if img is None:
                return {
                    'image_path': '',
                    'method': 'none',
                    'watermark_detected': False,
                    'error': '无法读取图片',
                    'mode': 'error',
                }

            if detection.get('detected') and detection.get('regions'):
                # 创建水印掩码
                mask = np.zeros(img.shape[:2], dtype=np.uint8)
                for region in detection['regions']:
                    x, y, w, h = region['x'], region['y'], region['w'], region['h']
                    mask[y:y+h, x:x+w] = 255

                # 使用 OpenCV 修复算法
                result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
                cv2.imwrite(output_path, result)

                return {
                    'image_path': output_path,
                    'method': 'inpaint',
                    'watermark_detected': True,
                    'regions_removed': len(detection['regions']),
                    'mode': 'opencv',
                }
            else:
                # 没有检测到水印，直接复制
                cv2.imwrite(output_path, img)
                return {
                    'image_path': output_path,
                    'method': 'none',
                    'watermark_detected': False,
                    'mode': 'opencv',
                }

        except Exception as e:
            logger.warning("水印移除失败: %s", e)
            return {
                'image_path': '',
                'method': 'none',
                'watermark_detected': False,
                'error': str(e),
                'mode': 'error',
            }