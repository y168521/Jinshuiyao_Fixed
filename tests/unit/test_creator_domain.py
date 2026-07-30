# -*- coding: utf-8 -*-
"""创作者工具箱子系统 - 单元测试

测试所有模块，全部使用mock，不依赖外部工具。
总计 42 个测试。
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

# 确保项目根目录在 sys.path
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


# ==================================================================
# CreatorDomain 测试
# ==================================================================

class TestCreatorDomain(unittest.TestCase):
    """CreatorDomain 核心测试（7个）"""

    def setUp(self):
        """创建CreatorDomain实例"""
        from domains.creator.domain import CreatorDomain
        # 使用临时目录
        self.tmp_dir = tempfile.mkdtemp()
        self.domain = CreatorDomain(config={"output_dir": self.tmp_dir})

    def tearDown(self):
        """清理临时目录"""
        import shutil
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_domain_id_and_description(self):
        """测试DOMAIN_ID和DESCRIPTION"""
        self.assertEqual(self.domain.DOMAIN_ID, "creator")
        self.assertIn("创作者", self.domain.DESCRIPTION)

    def test_modes_has_seven_entries(self):
        """测试MODES包含7种工具模式"""
        self.assertEqual(len(self.domain.MODES), 7)
        self.assertIn('ai_copy', self.domain.MODES)
        self.assertIn('batch', self.domain.MODES)

    def test_setup_returns_true(self):
        """测试setup()返回True"""
        result = self.domain.setup()
        self.assertTrue(result)
        self.assertTrue(self.domain._initialized)

    def test_teardown_returns_true(self):
        """测试teardown()返回True"""
        self.domain.setup()
        result = self.domain.teardown()
        self.assertTrue(result)
        self.assertFalse(self.domain._initialized)

    def test_generate_no_params(self):
        """测试generate()无参数时返回no_params"""
        self.domain.setup()
        result = self.domain.generate()
        self.assertEqual(result.get('status'), 'no_params')
        self.assertEqual(result.get('domain_id'), 'creator')

    def test_generate_ai_copy_mode(self):
        """测试generate() ai_copy模式"""
        self.domain.setup()
        result = self.domain.generate({'mode': 'ai_copy', 'topic': '测试主题'})
        self.assertEqual(result.get('status'), 'ok')
        self.assertTrue(len(result.get('predictions', [])) > 0)

    def test_status_returns_dict(self):
        """测试status()返回包含必要字段的字典"""
        self.domain.setup()
        status = self.domain.status()
        self.assertIn('ready', status)
        self.assertIn('tools', status)
        self.assertIn('modes', status)
        self.assertEqual(status['domain_id'], 'creator')


class TestCreatorDomainFetch(unittest.TestCase):
    """CreatorDomain fetch测试（3个）"""

    def setUp(self):
        from domains.creator.domain import CreatorDomain
        import shutil
        self.tmp_dir = tempfile.mkdtemp()
        os.rmdir(self.tmp_dir)  # 确保目录不存在，隔离且避免上次运行残留污染
        self.domain = CreatorDomain(config={"output_dir": self.tmp_dir})

    def tearDown(self):
        import shutil
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_fetch_empty_dir(self):
        """测试fetch()空目录返回空列表"""
        self.domain.setup()
        result = self.domain.fetch()
        self.assertTrue(result['success'])
        self.assertEqual(result['data'], [])

    def test_fetch_with_files(self):
        """测试fetch()有文件时返回文件列表"""
        os.makedirs(self.tmp_dir, exist_ok=True)
        # 创建测试文件
        test_file = os.path.join(self.tmp_dir, 'test.txt')
        with open(test_file, 'w') as f:
            f.write('test')
        self.domain.setup()
        result = self.domain.fetch()
        self.assertTrue(result['success'])
        self.assertTrue(len(result['data']) > 0)

    def test_fetch_nonexistent_dir(self):
        """测试fetch()目录不存在时也能工作"""
        self.domain.setup()
        result = self.domain.fetch()
        self.assertTrue(result['success'])


class TestCreatorDomainReview(unittest.TestCase):
    """CreatorDomain review测试（3个）"""

    def setUp(self):
        from domains.creator.domain import CreatorDomain
        self.tmp_dir = tempfile.mkdtemp()
        self.domain = CreatorDomain(config={"output_dir": self.tmp_dir})

    def tearDown(self):
        import shutil
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_review_none_predictions(self):
        """测试review()无预测记录"""
        self.domain.setup()
        result = self.domain.review()
        self.assertEqual(result['reviews'], 0)
        self.assertTrue(result['updated'])

    def test_review_with_predictions(self):
        """测试review()有预测记录时返回统计"""
        self.domain.setup()
        preds = [
            {'mode': 'template', 'style': 'xiaohongshu'},
            {'mode': 'ai', 'style': 'douyin'},
        ]
        result = self.domain.review(predictions=preds)
        self.assertEqual(result['reviews'], 2)
        self.assertIn('metrics', result)
        self.assertIn('mode_distribution', result['metrics'])

    def test_review_increments_count(self):
        """测试review()会增加复盘计数"""
        self.domain.setup()
        self.domain.review()
        self.domain.review()
        self.assertEqual(self.domain._review_count, 2)


# ==================================================================
# AICopywriter 测试
# ==================================================================

class TestAICopywriter(unittest.TestCase):
    """AI文案生成测试（7个）"""

    def setUp(self):
        from domains.creator.ai_copywriter import AICopywriter
        self.writer = AICopywriter()

    def test_styles_list(self):
        """测试STYLES包含6种风格"""
        self.assertEqual(len(self.writer.STYLES), 6)
        self.assertIn('xiaohongshu', self.writer.STYLES)
        self.assertIn('script', self.writer.STYLES)

    def test_generate_template_mode(self):
        """测试AI不可用时使用模板降级"""
        # 强制AI不可用
        self.writer._ai = False
        result = self.writer.generate('护肤好物', style='xiaohongshu')
        self.assertIn('title', result)
        self.assertIn('content', result)
        self.assertIn('tags', result)
        self.assertEqual(result['mode'], 'template')
        self.assertEqual(result['style'], 'xiaohongshu')
        self.assertIn('护肤好物', result['title'])

    def test_generate_invalid_style_fallback(self):
        """测试无效风格回退到默认"""
        self.writer._ai = False
        result = self.writer.generate('测试', style='invalid_style')
        self.assertEqual(result['style'], 'xiaohongshu')

    def test_generate_douyin_style(self):
        """测试抖音风格生成"""
        self.writer._ai = False
        result = self.writer.generate('咖啡机', style='douyin')
        self.assertEqual(result['style'], 'douyin')
        self.assertIn('咖啡机', result['content'])

    def test_generate_with_tone(self):
        """测试语气参数"""
        self.writer._ai = False
        result = self.writer.generate('书籍', style='wechat', tone='温馨')
        self.assertIn('书籍', result['title'])

    def test_generate_batch(self):
        """测试批量生成"""
        results = self.writer.generate_batch('美食', count=3)
        self.assertEqual(len(results), 3)
        for i, r in enumerate(results):
            self.assertEqual(r['batch_index'], i + 1)

    def test_generate_batch_custom_styles(self):
        """测试批量生成指定风格"""
        results = self.writer.generate_batch(
            '旅行', styles=['xiaohongshu', 'douyin']
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['style'], 'xiaohongshu')
        self.assertEqual(results[1]['style'], 'douyin')

    def test_generate_article_style(self):
        """测试公众号文章风格"""
        self.writer._ai = False
        result = self.writer.generate('科技趋势', style='article')
        self.assertIn('引言', result['content'])
        self.assertIn('总结', result['content'])


# ==================================================================
# SpeechToText 测试
# ==================================================================

class TestSpeechToText(unittest.TestCase):
    """语音转文字测试（5个）"""

    def setUp(self):
        from domains.creator.speech_to_text import SpeechToText
        self.stt = SpeechToText()

    def test_transcribe_degraded_mode(self):
        """测试无speech_recognition时降级"""
        result = self.stt.transcribe('/nonexistent/file.wav')
        self.assertEqual(result['mode'], 'degraded')
        self.assertEqual(result['text'], '')

    def test_transcribe_nonexistent_file(self):
        """测试文件不存在时返回错误提示"""
        result = self.stt.transcribe('/nonexistent/file.wav')
        self.assertIn('error', result)

    def test_split_segments(self):
        """测试文本分段"""
        segments = self.stt._split_segments('第一段。第二段！第三段？')
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]['text'], '第一段')

    def test_split_segments_empty(self):
        """测试空文本分段"""
        segments = self.stt._split_segments('')
        self.assertEqual(segments, [])

    def test_degraded_result_structure(self):
        """测试降级结果结构"""
        result = self.stt._degraded_result('/fake/path.wav', 'zh-CN')
        self.assertIn('text', result)
        self.assertIn('language', result)
        self.assertIn('duration', result)
        self.assertIn('segments', result)
        self.assertIn('confidence', result)
        self.assertEqual(result['language'], 'zh-CN')


# ==================================================================
# TTSEngine 测试
# ==================================================================

class TestTTSEngine(unittest.TestCase):
    """TTS引擎测试（6个）"""

    def setUp(self):
        from domains.creator.tts_engine import TTSEngine
        self.tts = TTSEngine()

    def test_voices_dict(self):
        """测试VOICES包含6种语音"""
        self.assertEqual(len(self.tts.VOICES), 6)
        self.assertIn('zh_female_1', self.tts.VOICES)
        self.assertIn('en_male', self.tts.VOICES)

    def test_synthesize_degraded_mode(self):
        """测试无edge-tts时降级"""
        result = self.tts.synthesize('测试文本', '/fake/output.mp3')
        self.assertEqual(result['mode'], 'degraded')
        self.assertEqual(result['size_bytes'], 0)

    def test_estimate_duration(self):
        """测试时长估算"""
        duration = self.tts._estimate_duration('你好世界', 1.0)
        self.assertGreater(duration, 0)
        # 4个字 / 4字每秒 = 1秒
        self.assertAlmostEqual(duration, 1.0, places=1)

    def test_estimate_duration_with_speed(self):
        """测试倍速时长估算"""
        duration_normal = self.tts._estimate_duration('你好', 1.0)
        duration_fast = self.tts._estimate_duration('你好', 2.0)
        self.assertLess(duration_fast, duration_normal)

    def test_list_voices_degraded(self):
        """测试无edge-tts时列出内置语音"""
        voices = self.tts.list_voices()
        self.assertEqual(len(voices), 6)
        for v in voices:
            self.assertFalse(v['available'])

    def test_voice_mapping(self):
        """测试语音映射"""
        self.assertEqual(
            self.tts.VOICES['zh_female_1'],
            'zh-CN-XiaoxiaoNeural'
        )
        self.assertEqual(
            self.tts.VOICES['en_female'],
            'en-US-JennyNeural'
        )


# ==================================================================
# OCREngine 测试
# ==================================================================

class TestOCREngine(unittest.TestCase):
    """OCR引擎测试（5个）"""

    def setUp(self):
        from domains.creator.ocr_engine import OCREngine
        self.ocr = OCREngine()

    def test_recognize_degraded_mode(self):
        """测试无pytesseract时降级"""
        with patch.object(self.ocr, '_check_available', return_value=False):
            result = self.ocr.recognize('/fake/image.png')
            self.assertEqual(result['mode'], 'degraded')
            self.assertEqual(result['text'], '')

    def test_recognize_base64_invalid(self):
        """测试无效base64数据"""
        result = self.ocr.recognize_base64('not-valid-base64!!!')
        self.assertEqual(result['mode'], 'error')
        self.assertIn('error', result)

    def test_degraded_result_structure(self):
        """测试降级结果结构"""
        result = self.ocr._degraded_result('/fake/img.png', 'chi_sim+eng')
        self.assertIn('text', result)
        self.assertIn('blocks', result)
        self.assertIn('confidence', result)
        self.assertEqual(result['lang'], 'chi_sim+eng')

    def test_recognize_nonexistent_file(self):
        """测试文件不存在时返回错误（库可用但文件不存在）"""
        with patch.object(self.ocr, '_check_available', return_value=True):
            result = self.ocr.recognize('/nonexistent/image.png')
            self.assertEqual(result['mode'], 'error')
            self.assertIn('error', result)

    def test_recognize_base64_empty(self):
        """测试空base64数据"""
        import base64
        # 有效但不是图片的base64
        data = base64.b64encode(b'not an image').decode()
        result = self.ocr.recognize_base64(data)
        # 会写入临时文件但OCR失败
        self.assertIn('mode', result)


# ==================================================================
# AudioExtractor 测试
# ==================================================================

class TestAudioExtractor(unittest.TestCase):
    """音频提取测试（5个）"""

    def setUp(self):
        from domains.creator.audio_extractor import AudioExtractor
        self.extractor = AudioExtractor()

    def test_extract_nonexistent_file(self):
        """测试文件不存在时返回错误"""
        result = self.extractor.extract('/nonexistent/video.mp4')
        self.assertEqual(result['mode'], 'error')
        self.assertIn('error', result)

    def test_extract_degraded_mode(self):
        """测试无moviepy和ffmpeg时降级"""
        # 创建一个假视频文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(b'fake video data')
            tmp_path = tmp.name
        try:
            # mock掉ffmpeg检查
            with patch.object(self.extractor, '_check_ffmpeg', return_value=False):
                with patch.object(self.extractor, '_check_moviepy', return_value=False):
                    result = self.extractor.extract(tmp_path)
                    self.assertEqual(result['mode'], 'degraded')
                    self.assertIn('error', result)
        finally:
            os.unlink(tmp_path)

    def test_extract_format_parameter(self):
        """测试format参数传递"""
        result = self.extractor.extract('/nonexistent/video.mp4', format='wav')
        self.assertEqual(result['format'], 'wav')

    def test_extract_output_dir_creation(self):
        """测试输出目录自动创建"""
        import tempfile
        tmp_video = os.path.join(tempfile.gettempdir(), 'fake_test_video.mp4')
        with open(tmp_video, 'wb') as f:
            f.write(b'fake')
        try:
            out_dir = os.path.join(tempfile.gettempdir(), 'test_creator_extract_out')
            with patch.object(self.extractor, '_check_ffmpeg', return_value=False):
                with patch.object(self.extractor, '_check_moviepy', return_value=False):
                    result = self.extractor.extract(tmp_video, output_dir=out_dir)
            self.assertIn('error', result)
        finally:
            if os.path.exists(tmp_video):
                os.unlink(tmp_video)
            if os.path.isdir(out_dir):
                os.rmdir(out_dir)

    def test_extract_from_url_error(self):
        """测试从无效URL提取"""
        result = self.extractor.extract_from_url('not-a-valid-url')
        self.assertEqual(result['mode'], 'error')


# ==================================================================
# WatermarkRemover 测试
# ==================================================================

class TestWatermarkRemover(unittest.TestCase):
    """去水印测试（6个）"""

    def setUp(self):
        from domains.creator.watermark_remover import WatermarkRemover
        self.remover = WatermarkRemover()

    def test_detect_degraded_mode(self):
        """测试无OpenCV时降级"""
        with patch.object(self.remover, '_check_available', return_value=False):
            result = self.remover.detect('/fake/image.png')
            self.assertEqual(result['mode'], 'degraded')
            self.assertFalse(result['detected'])

    def test_remove_degraded_mode(self):
        """测试无OpenCV时降级"""
        with patch.object(self.remover, '_check_available', return_value=False):
            result = self.remover.remove('/fake/image.png')
            self.assertEqual(result['mode'], 'degraded')
            self.assertFalse(result['watermark_detected'])

    def test_detect_nonexistent_file(self):
        """测试文件不存在（库可用但文件不存在）"""
        with patch.object(self.remover, '_check_available', return_value=True):
            result = self.remover.detect('/nonexistent/image.png')
            self.assertEqual(result['mode'], 'error')
            self.assertIn('error', result)

    def test_remove_nonexistent_file(self):
        """测试文件不存在（库可用但文件不存在）"""
        with patch.object(self.remover, '_check_available', return_value=True):
            result = self.remover.remove('/nonexistent/image.png')
            self.assertEqual(result['mode'], 'error')
            self.assertIn('error', result)

    def test_detect_result_structure(self):
        """测试检测结果结构"""
        result = self.remover.detect('/fake/image.png')
        self.assertIn('detected', result)
        self.assertIn('regions', result)
        self.assertIn('method', result)

    def test_remove_result_structure(self):
        """测试去水印结果结构"""
        result = self.remover.remove('/fake/image.png')
        self.assertIn('image_path', result)
        self.assertIn('method', result)
        self.assertIn('watermark_detected', result)


# ==================================================================
# DomainBase 兼容性测试
# ==================================================================

class TestCreatorDomainBaseCompat(unittest.TestCase):
    """验证CreatorDomain完整实现DomainBase接口"""

    def setUp(self):
        from domains.creator.domain import CreatorDomain
        from domains.base import DomainBase
        self.tmp_dir = os.path.join(_SCRIPT_DIR, '金水谣数据', 'test_compat')
        self.domain = CreatorDomain(config={"output_dir": self.tmp_dir})

    def tearDown(self):
        import shutil
        if os.path.isdir(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_inherits_domain_base(self):
        """测试继承DomainBase"""
        from domains.base import DomainBase
        self.assertIsInstance(self.domain, DomainBase)

    def test_implements_setup(self):
        """测试实现了setup方法"""
        self.assertTrue(callable(self.domain.setup))

    def test_implements_teardown(self):
        """测试实现了teardown方法"""
        self.assertTrue(callable(self.domain.teardown))

    def test_implements_fetch(self):
        """测试实现了fetch方法"""
        self.assertTrue(callable(self.domain.fetch))

    def test_implements_analyze(self):
        """测试实现了analyze方法"""
        self.assertTrue(callable(self.domain.analyze))

    def test_implements_generate(self):
        """测试实现了generate方法"""
        self.assertTrue(callable(self.domain.generate))

    def test_implements_review(self):
        """测试实现了review方法"""
        self.assertTrue(callable(self.domain.review))

    def test_implements_status(self):
        """测试实现了status方法"""
        self.assertTrue(callable(self.domain.status))

    def test_repr(self):
        """测试__repr__方法"""
        r = repr(self.domain)
        self.assertIn('creator', r)

    def test_full_lifecycle(self):
        """测试完整生命周期：setup -> fetch -> analyze -> generate -> review -> teardown"""
        self.domain.setup()
        self.assertTrue(self.domain._initialized)

        fetch_result = self.domain.fetch()
        self.assertTrue(fetch_result['success'])

        analyze_result = self.domain.analyze([])
        self.assertIn('status', analyze_result)

        gen_result = self.domain.generate({'mode': 'ai_copy', 'topic': '测试'})
        self.assertIn('predictions', gen_result)

        review_result = self.domain.review()
        self.assertTrue(review_result['updated'])

        teardown_result = self.domain.teardown()
        self.assertTrue(teardown_result)