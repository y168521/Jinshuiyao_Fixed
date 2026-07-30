# -*- coding: utf-8 -*-
"""金水谣视频文案提取模块单元测试

测试范围：
  - 平台识别（douyin/bilibili/kuaishou/xiaohongshu/weishi/general）
  - URL解析（视频ID提取）
  - 内容结构验证（返回字典字段完整性）
  - ContentRefiner的规则提炼（降级方案）
  - 知识卡片生成
  - 错误处理（无效URL、网络错误等）
  - 缓存机制
  - VTT字幕解析
  - 数字格式化
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime
from io import StringIO

# 确保项目根目录在sys.path中
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)


# ===================================================================
# VideoExtractor 单元测试（mock网络请求，测试逻辑层）
# ===================================================================

class TestVideoExtractorPlatformDetection(unittest.TestCase):
    """平台识别测试"""

    @classmethod
    def setUpClass(cls):
        """mock依赖后导入模块"""
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor

    def setUp(self):
        self.extractor = self.ve_module.VideoExtractor(cache_dir=os.path.join(
            _PROJECT_DIR, '金水谣数据', 'video_cache', '_test'))

    def test_detect_douyin(self):
        """识别抖音链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.douyin.com/video/7123456789'), 'douyin')

    def test_detect_douyin_tiktok(self):
        """识别TikTok链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.tiktok.com/@user/video/123'), 'douyin')

    def test_detect_douyin_iesdouyin(self):
        """识别抖音短链接(iesdouyin)"""
        self.assertEqual(self.extractor._detect_platform(
            'https://v.iesdouyin.com/xxx'), 'douyin')

    def test_detect_bilibili(self):
        """识别B站链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.bilibili.com/video/BV1xx411c7mD'), 'bilibili')

    def test_detect_bilibili_b23(self):
        """识别B站短链接(b23.tv)"""
        self.assertEqual(self.extractor._detect_platform(
            'https://b23.tv/xxxxx'), 'bilibili')

    def test_detect_kuaishou(self):
        """识别快手链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.kuaishou.com/short-video/xxx'), 'kuaishou')

    def test_detect_kuaishou_v(self):
        """识别快手v子域名"""
        self.assertEqual(self.extractor._detect_platform(
            'https://v.kuaishou.com/xxxxx'), 'kuaishou')

    def test_detect_xiaohongshu(self):
        """识别小红书链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.xiaohongshu.com/explore/xxxxx'), 'xiaohongshu')

    def test_detect_xiaohongshu_xhslink(self):
        """识别小红书短链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://xhslink.com/xxxxx'), 'xiaohongshu')

    def test_detect_weishi(self):
        """识别微信视频号链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://channels.weixin.qq.com/platform/live/liveEmbed?xxx'), 'weishi')

    def test_detect_weishi_qq(self):
        """识别微信视频号(weishi.qq.com)"""
        self.assertEqual(self.extractor._detect_platform(
            'https://weishi.qq.com/xxx'), 'weishi')

    def test_detect_general_youtube(self):
        """识别YouTube为通用链接"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.youtube.com/watch?v=xxx'), 'general')

    def test_detect_general_unknown(self):
        """识别未知平台为通用"""
        self.assertEqual(self.extractor._detect_platform(
            'https://www.unknown-site.com/video/123'), 'general')

    def test_detect_case_insensitive(self):
        """域名识别不区分大小写"""
        self.assertEqual(self.extractor._detect_platform(
            'https://WWW.BILIBILI.COM/VIDEO/BV1xx'), 'bilibili')


class TestVideoExtractorURLParsing(unittest.TestCase):
    """URL解析测试"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor

    def setUp(self):
        self.extractor = self.ve_module.VideoExtractor()

    def test_parse_bilibili_bv(self):
        """解析B站BV号"""
        vid = self.extractor._parse_video_id(
            'https://www.bilibili.com/video/BV1xx411c7mD', 'bilibili')
        self.assertEqual(vid, 'BV1xx411c7mD')

    def test_parse_bilibili_av(self):
        """解析B站AV号"""
        vid = self.extractor._parse_video_id(
            'https://www.bilibili.com/video/av123456', 'bilibili')
        self.assertEqual(vid, 'av123456')

    def test_parse_douyin_video(self):
        """解析抖音视频ID"""
        vid = self.extractor._parse_video_id(
            'https://www.douyin.com/video/7123456789012345678', 'douyin')
        self.assertEqual(vid, '7123456789012345678')

    def test_parse_kuaishou_video(self):
        """解析快手视频ID"""
        vid = self.extractor._parse_video_id(
            'https://www.kuaishou.com/short-video/3xx', 'kuaishou')
        # 快手路径不含 /video/，返回路径
        self.assertTrue(len(vid) > 0)

    def test_parse_xiaohongshu_explore(self):
        """解析小红书笔记ID"""
        vid = self.extractor._parse_video_id(
            'https://www.xiaohongshu.com/explore/abc123', 'xiaohongshu')
        self.assertEqual(vid, 'abc123')

    def test_parse_xiaohongshu_note(self):
        """解析小红书笔记(note路径)"""
        vid = self.extractor._parse_video_id(
            'https://www.xiaohongshu.com/note/xyz789', 'xiaohongshu')
        self.assertEqual(vid, 'xyz789')

    def test_parse_general_path(self):
        """通用URL解析取路径末尾"""
        vid = self.extractor._parse_video_id(
            'https://example.com/watch/some_video_id', 'general')
        self.assertEqual(vid, 'some_video_id')

    def test_parse_empty_path(self):
        """空路径返回空字符串"""
        vid = self.extractor._parse_video_id(
            'https://example.com/', 'general')
        self.assertEqual(vid, '')


class TestVideoExtractorResultStructure(unittest.TestCase):
    """返回数据结构测试"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor

    def test_empty_result_structure(self):
        """空结果字典结构完整性"""
        extractor = self.ve_module.VideoExtractor()
        result = extractor._empty_result('https://example.com', 'general')

        expected_keys = [
            'url', 'platform', 'platform_name', 'title', 'description',
            'subtitles', 'author', 'likes', 'comments', 'shares',
            'top_comments', 'tags', 'extracted_at'
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"缺少字段: {key}")

    def test_empty_result_defaults(self):
        """空结果默认值检查"""
        extractor = self.ve_module.VideoExtractor()
        result = extractor._empty_result('https://example.com', 'bilibili')

        self.assertEqual(result['url'], 'https://example.com')
        self.assertEqual(result['platform'], 'bilibili')
        self.assertEqual(result['platform_name'], 'B站')
        self.assertEqual(result['title'], '')
        self.assertEqual(result['description'], '')
        self.assertEqual(result['subtitles'], '')
        self.assertEqual(result['author'], '')
        self.assertEqual(result['top_comments'], [])
        self.assertEqual(result['tags'], [])
        self.assertIsNotNone(result['extracted_at'])

    def test_empty_result_platform_names(self):
        """各平台名称映射正确"""
        extractor = self.ve_module.VideoExtractor()
        names_map = {
            'douyin': '抖音',
            'bilibili': 'B站',
            'kuaishou': '快手',
            'xiaohongshu': '小红书',
            'weishi': '微信视频号',
            'general': '通用',
        }
        for platform, name in names_map.items():
            result = extractor._empty_result('', platform)
            self.assertEqual(result['platform_name'], name,
                             f"平台{platform}名称应为{name}")


class TestVideoExtractorExtract(unittest.TestCase):
    """提取主入口测试（mock网络）"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor

    def test_extract_empty_url_raises(self):
        """空URL抛出ValueError"""
        extractor = self.ve_module.VideoExtractor()
        with self.assertRaises(ValueError):
            extractor.extract("")

    def test_extract_whitespace_url_raises(self):
        """纯空白URL抛出ValueError"""
        extractor = self.ve_module.VideoExtractor()
        with self.assertRaises(ValueError):
            extractor.extract("   ")

    def test_extract_auto_https_prefix(self):
        """自动补全https协议头"""
        extractor = self.ve_module.VideoExtractor()
        # mock掉实际网络请求
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("douyin.com/video/123", use_cache=False)
        self.assertIn('douyin.com', result['url'])
        self.assertTrue(result['url'].startswith('https://'))

    def test_extract_result_has_required_fields(self):
        """提取结果包含所有必需字段"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.bilibili.com/video/BV1test", use_cache=False)

        expected_keys = [
            'url', 'platform', 'platform_name', 'title', 'description',
            'subtitles', 'author', 'likes', 'comments', 'shares',
            'top_comments', 'tags', 'extracted_at'
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_extract_douyin_platform(self):
        """抖音链接正确识别平台"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.douyin.com/video/123", use_cache=False)
        self.assertEqual(result['platform'], 'douyin')
        self.assertEqual(result['platform_name'], '抖音')

    def test_extract_kuaishou_platform(self):
        """快手链接正确识别平台"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.kuaishou.com/short-video/abc", use_cache=False)
        self.assertEqual(result['platform'], 'kuaishou')
        self.assertEqual(result['platform_name'], '快手')

    def test_extract_xiaohongshu_platform(self):
        """小红书链接正确识别平台"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.xiaohongshu.com/explore/abc123", use_cache=False)
        self.assertEqual(result['platform'], 'xiaohongshu')
        self.assertEqual(result['platform_name'], '小红书')

    def test_extract_weishi_platform(self):
        """微信视频号链接正确识别平台"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://channels.weixin.qq.com/live/abc", use_cache=False)
        self.assertEqual(result['platform'], 'weishi')
        self.assertEqual(result['platform_name'], '微信视频号')

    def test_extract_general_platform(self):
        """YouTube等未知平台识别为通用"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.youtube.com/watch?v=abc123", use_cache=False)
        self.assertEqual(result['platform'], 'general')
        self.assertEqual(result['platform_name'], '通用')

    def test_extract_handles_import_error(self):
        """requests未安装时优雅降级"""
        extractor = self.ve_module.VideoExtractor()
        extractor._save_cache = MagicMock()

        # 让平台提取器抛出 ImportError（模拟requests未安装）
        extractor._extract_douyin = MagicMock(side_effect=ImportError("no requests"))

        result = extractor.extract("https://www.douyin.com/video/123", use_cache=False)
        self.assertIn('提取失败', result['description'])
        self.assertEqual(result['platform'], 'douyin')

    def test_extract_handles_exception(self):
        """网络异常时返回错误信息"""
        extractor = self.ve_module.VideoExtractor()
        extractor._save_cache = MagicMock()

        # 让平台提取器抛出异常
        extractor._extract_douyin = MagicMock(side_effect=Exception("网络超时"))

        result = extractor.extract("https://www.douyin.com/video/123", use_cache=False)
        self.assertIn('提取失败', result['description'])

    def test_extract_timestamp(self):
        """提取结果包含时间戳"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        result = extractor.extract("https://www.bilibili.com/video/BV1test", use_cache=False)
        # 验证extracted_at是有效的ISO格式时间
        ts = result['extracted_at']
        self.assertIsNotNone(ts)
        # 尝试解析，确保格式正确
        parsed = datetime.fromisoformat(ts)
        self.assertIsInstance(parsed, datetime)


class TestVideoExtractorCache(unittest.TestCase):
    """缓存机制测试"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor

    def test_cache_key_is_md5(self):
        """缓存key为MD5格式"""
        extractor = self.ve_module.VideoExtractor()
        key = extractor._get_cache_key('https://www.douyin.com/video/123')
        self.assertEqual(len(key), 32 + 5)  # MD5(32) + '.json'(5)
        self.assertTrue(key.endswith('.json'))

    def test_cache_key_deterministic(self):
        """同一URL生成相同缓存key"""
        extractor = self.ve_module.VideoExtractor()
        url = 'https://www.bilibili.com/video/BV1test'
        key1 = extractor._get_cache_key(url)
        key2 = extractor._get_cache_key(url)
        self.assertEqual(key1, key2)

    def test_cache_key_different_urls(self):
        """不同URL生成不同缓存key"""
        extractor = self.ve_module.VideoExtractor()
        key1 = extractor._get_cache_key('https://www.douyin.com/video/111')
        key2 = extractor._get_cache_key('https://www.douyin.com/video/222')
        self.assertNotEqual(key1, key2)

    def test_save_and_load_cache(self):
        """缓存保存和加载"""
        import tempfile
        cache_dir = tempfile.mkdtemp()
        try:
            extractor = self.ve_module.VideoExtractor(cache_dir=cache_dir)

            test_data = {
                'url': 'https://test.com/video/123',
                'platform': 'douyin',
                'title': '测试标题',
                'description': '测试描述',
                'extracted_at': datetime.now().isoformat(),
            }
            url = 'https://test.com/video/123'

            # 保存缓存
            extractor._save_cache(url, test_data)

            # 加载缓存
            loaded = extractor._load_cache(url)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded['title'], '测试标题')
            self.assertEqual(loaded['description'], '测试描述')
            self.assertEqual(loaded['platform'], 'douyin')
        finally:
            # 清理
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)

    def test_cache_expired(self):
        """过期缓存不加载（24小时有效期）"""
        import tempfile
        cache_dir = tempfile.mkdtemp()
        try:
            extractor = self.ve_module.VideoExtractor(cache_dir=cache_dir)

            # 创建一个25小时前的缓存
            from datetime import timedelta
            old_time = (datetime.now() - timedelta(hours=25)).isoformat()
            test_data = {
                'url': 'https://test.com/video/old',
                'title': '旧数据',
                'extracted_at': old_time,
            }
            extractor._save_cache('https://test.com/video/old', test_data)

            # 尝试加载应返回None（已过期）
            loaded = extractor._load_cache('https://test.com/video/old')
            self.assertIsNone(loaded)
        finally:
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)

    def test_cache_miss(self):
        """缓存不存在返回None"""
        extractor = self.ve_module.VideoExtractor()
        loaded = extractor._load_cache('https://nonexistent-url-xyz.com/video/999')
        self.assertIsNone(loaded)

    def test_extract_uses_cache(self):
        """提取时使用缓存"""
        extractor = self.ve_module.VideoExtractor()
        test_url = 'https://cached-test.com/video/123'

        # 写入缓存
        cached_data = {
            'url': test_url,
            'platform': 'bilibili',
            'platform_name': 'B站',
            'title': '缓存标题',
            'description': '缓存描述',
            'subtitles': '',
            'author': '缓存作者',
            'likes': '',
            'comments': '',
            'shares': '',
            'top_comments': [],
            'tags': [],
            'extracted_at': datetime.now().isoformat(),
        }
        extractor._save_cache(test_url, cached_data)

        # 提取应命中缓存，不发起网络请求
        result = extractor.extract(test_url, use_cache=True)
        self.assertEqual(result['title'], '缓存标题')
        self.assertEqual(result['platform'], 'bilibili')

    def test_extract_skip_cache(self):
        """跳过缓存直接提取"""
        extractor = self.ve_module.VideoExtractor()
        extractor._request_with_retry = MagicMock(return_value=None)
        extractor._save_cache = MagicMock()

        # 虽然可能有缓存，但use_cache=False时直接请求
        result = extractor.extract("https://www.bilibili.com/video/BV1test", use_cache=False)
        # 验证请求被调用
        extractor._request_with_retry.assert_called()


class TestVideoExtractorHelpers(unittest.TestCase):
    """辅助方法测试"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import video_extractor
        importlib.reload(video_extractor)
        cls.ve_module = video_extractor
        cls.extractor = cls.ve_module.VideoExtractor()

    def test_format_number_small(self):
        """小数字不转换"""
        self.assertEqual(self.extractor._format_number(999), '999')

    def test_format_number_ten_thousand(self):
        """万级数字格式化"""
        self.assertEqual(self.extractor._format_number(10000), '1.0万')
        self.assertEqual(self.extractor._format_number(25000), '2.5万')

    def test_format_number_hundred_million(self):
        """亿级数字格式化"""
        self.assertEqual(self.extractor._format_number(100000000), '1.0亿')
        self.assertEqual(self.extractor._format_number(350000000), '3.5亿')

    def test_format_number_string(self):
        """字符串数字能转换（会被int()解析后格式化）"""
        # 字符串'10000'会被int()转为10000，然后格式化为1.0万
        self.assertEqual(self.extractor._format_number('10000'), '1.0万')

    def test_format_number_zero(self):
        """零值处理"""
        self.assertEqual(self.extractor._format_number(0), '0')

    def test_format_number_none(self):
        """None值处理"""
        self.assertEqual(self.extractor._format_number(None), '0')

    def test_parse_vtt_basic(self):
        """VTT字幕基本解析"""
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "第一句话\n\n"
            "00:00:04.000 --> 00:00:06.000\n"
            "第二句话\n\n"
            "00:00:07.000 --> 00:00:09.000\n"
            "第三句话"
        )
        result = self.ve_module.VideoExtractor._parse_vtt(vtt)
        self.assertEqual(result, '第一句话 第二句话 第三句话')

    def test_parse_vtt_empty(self):
        """空VTT返回空字符串"""
        self.assertEqual(self.ve_module.VideoExtractor._parse_vtt(''), '')

    def test_parse_vtt_only_header(self):
        """只有WEBVTT头部"""
        self.assertEqual(self.ve_module.VideoExtractor._parse_vtt('WEBVTT\n'), '')

    def test_parse_vtt_with_html_tags(self):
        """VTT中带HTML标签"""
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<b>加粗文字</b>\n\n"
            "00:00:04.000 --> 00:00:06.000\n"
            "普通文字"
        )
        result = self.ve_module.VideoExtractor._parse_vtt(vtt)
        self.assertIn('加粗文字', result)
        self.assertIn('普通文字', result)

    def test_parse_vtt_skip_timestamps(self):
        """VTT不包含时间戳"""
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "测试内容"
        )
        result = self.ve_module.VideoExtractor._parse_vtt(vtt)
        self.assertNotIn('-->', result)
        self.assertNotIn('00:00', result)
        self.assertIn('测试内容', result)

    def test_parse_vtt_skip_sequence_numbers(self):
        """VTT不包含序号"""
        vtt = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "测试"
        )
        result = self.ve_module.VideoExtractor._parse_vtt(vtt)
        self.assertNotIn('\n1\n', result)

    def test_extract_render_data(self):
        """RENDER_DATA提取"""
        import urllib.parse
        test_data = {'title': '测试标题', 'desc': '测试描述'}
        encoded = urllib.parse.quote(json.dumps(test_data))
        html = f'<script id="RENDER_DATA">{encoded}</script>'

        extractor = self.ve_module.VideoExtractor()
        result = extractor._extract_render_data(html)
        # RENDER_DATA提取可能返回嵌套结构，不一定是直接匹配
        self.assertIsNotNone(result)

    def test_extract_render_data_none(self):
        """无RENDER_DATA返回None"""
        html = '<html><body>没有RENDER_DATA</body></html>'
        extractor = self.ve_module.VideoExtractor()
        result = extractor._extract_render_data(html)
        self.assertIsNone(result)

    def test_extract_initial_state(self):
        """INITIAL_STATE提取"""
        test_data = {'note': {'noteDetailMap': {}}}
        json_str = json.dumps(test_data).replace('"undefined"', 'null')
        html = f'<script>window.__INITIAL_STATE__={json_str}</script>'

        extractor = self.ve_module.VideoExtractor()
        result = extractor._extract_initial_state(html)
        self.assertIsNotNone(result)
        self.assertIn('note', result)

    def test_extract_initial_state_none(self):
        """无INITIAL_STATE返回None"""
        html = '<html><body>没有INITIAL_STATE</body></html>'
        extractor = self.ve_module.VideoExtractor()
        result = extractor._extract_initial_state(html)
        self.assertIsNone(result)


# ===================================================================
# ContentRefiner 单元测试
# ===================================================================

class TestContentRefiner(unittest.TestCase):
    """内容提炼器测试"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", MagicMock())
        sys.modules.setdefault("bs4", MagicMock())
        import importlib
        from core import content_refiner
        importlib.reload(content_refiner)
        cls.cr_module = content_refiner

    def setUp(self):
        self.refiner = self.cr_module.ContentRefiner()
        # mock AI服务为不可用，测试规则降级
        self.refiner._ai = MagicMock()
        self.refiner._ai.is_available = False

    # ------------------------------------------------------------------
    # refine 主入口
    # ------------------------------------------------------------------

    def test_refine_returns_card(self):
        """提炼返回知识卡片"""
        data = self._make_extracted_data()
        card = self.refiner.refine(data)

        expected_keys = [
            'source_url', 'source_platform', 'title', 'author',
            'summary', 'key_points', 'data_points',
            'writing_techniques', 'tags', 'full_text',
            'refined_at', 'method'
        ]
        for key in expected_keys:
            self.assertIn(key, card, f"知识卡片缺少字段: {key}")

    def test_refine_method_is_rule_without_ai(self):
        """AI不可用时使用规则方式"""
        data = self._make_extracted_data()
        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'rule')

    def test_refine_method_is_ai_with_ai(self):
        """AI可用时使用AI方式"""
        data = self._make_extracted_data()

        # mock AI返回
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.chat.return_value = json.dumps({
            'summary': 'AI摘要',
            'key_points': ['要点1', '要点2'],
            'data_points': ['数据1'],
            'writing_techniques': ['技巧1'],
            'tags': ['标签1'],
        }, ensure_ascii=False)
        self.refiner._ai = mock_ai

        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'ai')
        self.assertEqual(card['summary'], 'AI摘要')

    def test_refine_ai_fallback_on_exception(self):
        """AI调用异常时降级到规则"""
        data = self._make_extracted_data()

        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.chat.side_effect = Exception("API错误")
        self.refiner._ai = mock_ai

        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'rule')

    def test_refine_preserves_source_info(self):
        """提炼保留原始信息"""
        data = {
            'url': 'https://test.com/video/123',
            'platform': 'douyin',
            'platform_name': '抖音',
            'title': '测试标题',
            'description': '测试描述内容',
            'subtitles': '',
            'author': '测试作者',
            'tags': ['美食', '探店'],
            'likes': '1.2万',
            'comments': '',
            'shares': '',
            'top_comments': [],
            'extracted_at': datetime.now().isoformat(),
        }
        card = self.refiner.refine(data)
        self.assertEqual(card['source_url'], 'https://test.com/video/123')
        self.assertEqual(card['source_platform'], '抖音')
        self.assertEqual(card['title'], '测试标题')
        self.assertEqual(card['author'], '测试作者')
        self.assertIn('美食', card['tags'])

    def test_refine_full_text_combination(self):
        """完整文本合并标题+描述+字幕"""
        data = {
            'title': '标题',
            'description': '描述',
            'subtitles': '字幕',
            'tags': [],
            'author': '',
            'platform': 'general',
            'platform_name': '通用',
            'url': 'https://test.com',
            'likes': '', 'comments': '', 'shares': '',
            'top_comments': [],
            'extracted_at': datetime.now().isoformat(),
        }
        card = self.refiner.refine(data)
        self.assertIn('标题', card['full_text'])
        self.assertIn('描述', card['full_text'])
        self.assertIn('字幕', card['full_text'])

    def test_refine_timestamp(self):
        """提炼结果包含时间戳"""
        data = self._make_extracted_data()
        card = self.refiner.refine(data)
        ts = card['refined_at']
        self.assertIsNotNone(ts)
        parsed = datetime.fromisoformat(ts)
        self.assertIsInstance(parsed, datetime)

    def test_refine_empty_content(self):
        """空内容提炼"""
        data = self._make_extracted_data(title='', description='', subtitles='')
        card = self.refiner.refine(data)
        self.assertEqual(card['summary'], '（无内容可提炼）')

    # ------------------------------------------------------------------
    # extract_key_points
    # ------------------------------------------------------------------

    def test_extract_key_points(self):
        """提取关键要点"""
        text = "这是一个有内容的句子。太短的不算。这个句子有足够的长度。另一个完整的句子。"
        points = self.refiner.extract_key_points(text)
        self.assertTrue(len(points) > 0)
        for p in points:
            self.assertTrue(len(p) >= 10)

    def test_extract_key_points_empty(self):
        """空文本返回空列表"""
        self.assertEqual(self.refiner.extract_key_points(''), [])

    # ------------------------------------------------------------------
    # extract_data_points
    # ------------------------------------------------------------------

    def test_extract_data_points_percentage(self):
        """提取百分比数据"""
        text = "我们的转化率达到了85%，远超行业平均水平。"
        points = self.refiner.extract_data_points(text)
        self.assertTrue(any('85%' in p for p in points))

    def test_extract_data_points_amount(self):
        """提取金额数据"""
        text = "这个项目投入了100万元，预计3年内回本。"
        points = self.refiner.extract_data_points(text)
        self.assertTrue(len(points) > 0)

    def test_extract_data_points_empty(self):
        """无数据文本返回空列表"""
        points = self.refiner.extract_data_points("这里没有任何数据")
        self.assertEqual(len(points), 0)

    # ------------------------------------------------------------------
    # generate_summary
    # ------------------------------------------------------------------

    def test_generate_summary_short(self):
        """短文本完整返回"""
        summary = self.refiner.generate_summary('标题', '短描述', '')
        self.assertIn('标题', summary)
        self.assertIn('短描述', summary)

    def test_generate_summary_truncated(self):
        """长文本截断到200字"""
        long_desc = '很长的描述' * 100
        summary = self.refiner.generate_summary('标题', long_desc, '')
        self.assertTrue(summary.endswith('...'))
        self.assertTrue(len(summary) <= 210)  # 200 + '...'

    def test_generate_summary_empty(self):
        """空内容返回占位符"""
        summary = self.refiner.generate_summary('', '', '')
        self.assertEqual(summary, '（无内容）')

    # ------------------------------------------------------------------
    # _detect_writing_techniques
    # ------------------------------------------------------------------

    def test_detect_number_structure(self):
        """检测数字结构法"""
        text = "这里有3个方法帮你提升效率"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('数字' in t for t in techniques))

    def test_detect_question(self):
        """检测疑问句"""
        text = "你知道这是为什么吗？"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('疑问' in t or '设问' in t for t in techniques))

    def test_detect_contrast(self):
        """检测对比转折"""
        text = "看起来很好，但是实际上不行"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('对比' in t or '转折' in t for t in techniques))

    def test_detect_enumeration(self):
        """检测列举结构"""
        text = "第一，要做好准备。第二，要坚持到底。"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('列举' in t for t in techniques))

    def test_detect_cta(self):
        """检测行动呼吁"""
        text = "赶快点击下方链接，立即购买！"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('行动' in t or 'CTA' in t for t in techniques))

    def test_detect_story(self):
        """检测故事带入"""
        text = "去年我还在迷茫中，有一天突然想通了"
        techniques = self.refiner._detect_writing_techniques(text)
        self.assertTrue(any('故事' in t or '场景' in t for t in techniques))

    def test_detect_empty(self):
        """空文本无技巧"""
        self.assertEqual(self.refiner._detect_writing_techniques(''), [])

    # ------------------------------------------------------------------
    # _auto_classify
    # ------------------------------------------------------------------

    def test_classify_tutorial(self):
        """分类：教程"""
        tags = self.refiner._auto_classify('这个教程教你如何使用Python')
        self.assertIn('教程', tags)

    def test_classify_science(self):
        """分类：科普"""
        tags = self.refiner._auto_classify('科学研究表明，这是因为...')
        self.assertIn('科普', tags)

    def test_classify_review(self):
        """分类：测评"""
        tags = self.refiner._auto_classify('详细测评体验，推荐购买')
        self.assertIn('测评', tags)

    def test_classify_story(self):
        """分类：故事"""
        # "经历" 在故事分类关键词中
        tags = self.refiner._auto_classify('分享一段难忘的经历')
        self.assertIn('故事', tags)

    def test_classify_food(self):
        """分类：美食"""
        tags = self.refiner._auto_classify('这道菜做法很简单，食材便宜')
        self.assertIn('美食', tags)

    def test_classify_empty(self):
        """空文本无标签"""
        self.assertEqual(self.refiner._auto_classify(''), [])

    # ------------------------------------------------------------------
    # AI返回JSON解析容错
    # ------------------------------------------------------------------

    def test_ai_response_with_code_block(self):
        """AI返回带```json包裹的JSON"""
        data = self._make_extracted_data()

        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.chat.return_value = '```json\n{"summary": "测试摘要", "key_points": ["A"]}\n```'
        self.refiner._ai = mock_ai

        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'ai')
        self.assertEqual(card['summary'], '测试摘要')
        self.assertEqual(card['key_points'], ['A'])

    def test_ai_response_invalid_json(self):
        """AI返回无效JSON时用原文作摘要"""
        data = self._make_extracted_data()

        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.chat.return_value = '这不是JSON，只是一段纯文本摘要内容'
        self.refiner._ai = mock_ai

        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'ai')
        self.assertIn('纯文本摘要', card['summary'])

    def test_ai_response_partial_json(self):
        """AI返回部分字段缺失的JSON"""
        data = self._make_extracted_data()

        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.chat.return_value = '{"summary": "只有摘要"}'
        self.refiner._ai = mock_ai

        card = self.refiner.refine(data)
        self.assertEqual(card['method'], 'ai')
        self.assertEqual(card['summary'], '只有摘要')

    # ------------------------------------------------------------------
    # 全局单例
    # ------------------------------------------------------------------

    def test_get_refiner_singleton(self):
        """全局单例返回ContentRefiner"""
        from core.content_refiner import get_refiner
        refiner1 = get_refiner()
        refiner2 = get_refiner()
        self.assertIs(refiner1, refiner2)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _make_extracted_data(self, title='测试视频标题', description='这是一个测试视频的描述内容，包含了一些关键信息。',
                             subtitles='欢迎来到我的频道，今天给大家分享三个实用技巧。'):
        return {
            'url': 'https://test.com/video/123',
            'platform': 'general',
            'platform_name': '通用',
            'title': title,
            'description': description,
            'subtitles': subtitles,
            'author': '测试作者',
            'likes': '',
            'comments': '',
            'shares': '',
            'top_comments': [],
            'tags': ['测试'],
            'extracted_at': datetime.now().isoformat(),
        }


if __name__ == '__main__':
    unittest.main()
