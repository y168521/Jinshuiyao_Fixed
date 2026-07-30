# -*- coding: utf-8 -*-
"""音频提取模块

从视频中提取音频，支持本地文件和URL。
使用 moviepy 或 ffmpeg 进行提取。
"""
import logging
import os
import tempfile
import subprocess
import shutil

logger = logging.getLogger(__name__)


class AudioExtractor:
    """音频提取引擎

    优先使用 moviepy，不可用则尝试 ffmpeg 命令行。
    全部不可用时优雅降级。
    """

    def __init__(self):
        self._moviepy_available = None
        self._ffmpeg_available = None

    def _check_moviepy(self):
        """检查 moviepy 是否可用"""
        if self._moviepy_available is None:
            try:
                from moviepy.editor import VideoFileClip
                self._moviepy_available = True
                logger.info("moviepy 已加载")
            except ImportError:
                logger.info("moviepy 未安装")
                self._moviepy_available = False
        return self._moviepy_available

    def _check_ffmpeg(self):
        """检查 ffmpeg 是否可用"""
        if self._ffmpeg_available is None:
            self._ffmpeg_available = shutil.which('ffmpeg') is not None
            if self._ffmpeg_available:
                logger.info("ffmpeg 命令可用")
            else:
                logger.info("ffmpeg 未安装")
        return self._ffmpeg_available

    def extract(self, video_path, output_dir=None, format='mp3'):
        """从视频提取音频

        Args:
            video_path: 视频文件路径
            output_dir: 输出目录，None表示视频同目录
            format: 输出格式，默认mp3

        Returns:
            dict: {
                'audio_path': '输出文件路径',
                'duration': 180,
                'format': 'mp3',
                'size_bytes': 3000000,
            }
        """
        if not os.path.isfile(video_path):
            return {
                'audio_path': '',
                'duration': 0,
                'format': format,
                'size_bytes': 0,
                'error': f'文件不存在: {video_path}',
                'mode': 'error',
            }

        # 确定输出路径
        if output_dir is None:
            output_dir = os.path.dirname(video_path) or '.'
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        output_path = os.path.join(output_dir, f'{base_name}.{format}')

        # 优先使用 moviepy
        if self._check_moviepy():
            try:
                return self._extract_with_moviepy(video_path, output_path, format)
            except Exception as e:
                logger.warning("moviepy提取失败，尝试ffmpeg: %s", e)

        # 降级使用 ffmpeg
        if self._check_ffmpeg():
            try:
                return self._extract_with_ffmpeg(video_path, output_path, format)
            except Exception as e:
                logger.warning("ffmpeg提取失败: %s", e)

        # 全部不可用
        return {
            'audio_path': '',
            'duration': 0,
            'format': format,
            'size_bytes': 0,
            'error': '需要安装 moviepy 或 ffmpeg',
            'mode': 'degraded',
        }

    def extract_from_url(self, video_url, output_dir=None, format='mp3'):
        """从URL下载并提取音频

        Args:
            video_url: 视频URL
            output_dir: 输出目录
            format: 输出格式

        Returns:
            dict: 提取结果
        """
        try:
            import urllib.request

            # 下载视频到临时文件
            suffix = '.mp4'
            for ext in ['.mp4', '.avi', '.mkv', '.mov', '.flv']:
                if ext in video_url.lower():
                    suffix = ext
                    break

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name

            urllib.request.urlretrieve(video_url, tmp_path)

            result = self.extract(tmp_path, output_dir=output_dir, format=format)

            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            result['source_url'] = video_url
            return result
        except Exception as e:
            logger.error("从URL提取音频失败: %s", e)
            return {
                'audio_path': '',
                'duration': 0,
                'format': format,
                'size_bytes': 0,
                'error': f'下载或提取失败: {e}',
                'mode': 'error',
            }

    def _extract_with_moviepy(self, video_path, output_path, format):
        """使用 moviepy 提取音频"""
        from moviepy.editor import VideoFileClip

        with VideoFileClip(video_path) as video:
            duration = video.duration
            video.audio.write_audiofile(output_path, verbose=False, logger=None)

        size_bytes = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

        return {
            'audio_path': output_path,
            'duration': round(duration, 1),
            'format': format,
            'size_bytes': size_bytes,
            'mode': 'moviepy',
        }

    def _extract_with_ffmpeg(self, video_path, output_path, format):
        """使用 ffmpeg 提取音频"""
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vn',  # 不要视频
            '-acodec', 'libmp3lame' if format == 'mp3' else 'aac',
            '-ab', '192k',
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg返回错误: {result.stderr[:200]}")

        # 获取时长
        duration = self._get_duration_ffprobe(video_path)
        size_bytes = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

        return {
            'audio_path': output_path,
            'duration': duration,
            'format': format,
            'size_bytes': size_bytes,
            'mode': 'ffmpeg',
        }

    def _get_duration_ffprobe(self, video_path):
        """使用 ffprobe 获取视频时长"""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return round(float(result.stdout.strip()), 1)
        except Exception:
            pass
        return 0