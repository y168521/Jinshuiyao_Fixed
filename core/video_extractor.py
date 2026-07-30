# -*- coding: utf-8 -*-
"""金水谣引擎 - 视频文案提取核心模块

支持从各大视频平台提取文案、字幕、评论等内容。
功能类似轻抖的文案提取：用户粘贴链接 → 系统提取 → 提炼价值 → 存入知识库。

支持平台：
  - 抖音 / TikTok：网页抓取视频描述和评论
  - B站 (bilibili)：通过B站API获取字幕和描述
  - 快手 (kuaishou)：网页抓取
  - 小红书 (xiaohongshu)：网页抓取
  - 微信视频号 (weishi)：网页抓取
  - 通用：优先使用yt-dlp（如果已安装），否则网页抓取

提取内容：
  - 视频标题 / 描述 / 文案
  - 视频字幕（如有）
  - 热门评论
  - 视频元数据（作者、点赞、播放量等）

使用方式：
    from core.video_extractor import VideoExtractor
    ext = VideoExtractor()
    result = ext.extract("https://www.douyin.com/video/xxx")
    print(result["title"], result["description"])
"""

import json
import os
import re
import time
import hashlib
import logging
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs
import socket
import ipaddress

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

# 项目根目录（相对于此文件）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "金水谣数据", "video_cache")

# 网络请求默认超时（秒）
_DEFAULT_TIMEOUT = 15
# 最大重试次数
_MAX_RETRIES = 2
# 重试间隔基数（秒）
_RETRY_BASE_DELAY = 1

# 平台域名映射
_PLATFORM_PATTERNS = {
    'douyin': ['douyin.com', 'tiktok.com', 'iesdouyin.com'],
    'bilibili': ['bilibili.com', 'b23.tv'],
    'kuaishou': ['kuaishou.com', 'v.kuaishou.com', 'gifshow.com', 'chenzhongtech.com'],
    'xiaohongshu': ['xiaohongshu.com', 'xhslink.com', 'xhs.cn'],
    'weishi': ['channels.weixin.qq.com', 'weishi.qq.com', 'video.qq.com'],
}

# 平台中文名映射
_PLATFORM_NAMES = {
    'douyin': '抖音',
    'bilibili': 'B站',
    'kuaishou': '快手',
    'xiaohongshu': '小红书',
    'weishi': '微信视频号',
    'general': '通用',
}

# yt-dlp 是否可用（运行时检测）
_yt_dlp_available = shutil.which('yt-dlp') is not None

# cookie 读取位置（用户「手动」维护，含登录凭证）。
# 安全：从云同步目录迁到用户主目录下的非同步目录 _SECRETS_DIR，避免被同步到云端/其他设备。
# 读取顺序：新位置(优先) → 旧 config/ 位置(兼容回退)。
_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
_OLD_COOKIE_FILE = os.path.join(_CONFIG_DIR, "douyin_cookie.txt")


def _resolve_cookie_file():
    """返回首个存在的 cookie 文件路径（新位置优先，旧位置回退）。"""
    for p in (os.path.join(_SECRETS_DIR, "douyin_cookie.txt"), _OLD_COOKIE_FILE):
        if os.path.isfile(p):
            return p
    return os.path.join(_SECRETS_DIR, "douyin_cookie.txt")


class VideoExtractor:
    """视频文案提取器

    特性：
      - 自动识别视频平台
      - 多平台适配提取策略
      - 网络请求超时 + 自动重试
      - 提取结果本地缓存
      - 优雅降级：yt-dlp不可用时回退到网页抓取
    """

    def __init__(self, cache_dir: str = "", cookie: str = ""):
        """初始化视频提取器

        Args:
            cache_dir: 缓存目录路径，默认为 金水谣数据/video_cache/
            cookie:    用户「手动」提供的登录态 cookie 字符串（抖音等需登录平台用）。
                       优先用此参数；为空时尝试从环境变量 TIANSHU_DOUYIN_COOKIE
                       或本地文件 config/douyin_cookie.txt 读取（均需用户自行粘贴）。
                       ⚠️ 本工具绝不自动从浏览器窃取 cookie（高危操作）。
        """
        # 延迟导入 requests/BeautifulSoup（避免在无网络环境报错）
        self._requests = None
        self._bs4 = None
        self._session = None
        self._cache_dir = cache_dir or _CACHE_DIR
        os.makedirs(self._cache_dir, exist_ok=True)
        # cookie：优先用传入值，其次本地配置（用户手动维护）
        self._cookie = cookie or self._load_cookie_from_config()

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _get_requests(self):
        """延迟加载 requests 库"""
        if self._requests is None:
            try:
                import requests
                self._requests = requests
            except ImportError:
                logger.error("[video_extractor] requests 库未安装，网页抓取不可用")
                raise ImportError("需要安装 requests 库: pip install requests")
        return self._requests

    def _get_bs4(self):
        """延迟加载 BeautifulSoup"""
        if self._bs4 is None:
            try:
                from bs4 import BeautifulSoup
                self._bs4 = BeautifulSoup
            except ImportError:
                logger.error("[video_extractor] beautifulsoup4 库未安装")
                raise ImportError("需要安装 beautifulsoup4 库: pip install beautifulsoup4")
        return self._bs4

    def _load_cookie_from_config(self) -> str:
        """读取用户手动维护的 cookie。

        顺序：① 环境变量 TIANSHU_DOUYIN_COOKIE ② 新密钥目录(优先) ③ 旧 config/(回退)。
        密钥文件已迁出云同步目录，存放于用户主目录下的非同步目录，降低泄露风险。
        """
        env_cookie = os.environ.get("TIANSHU_DOUYIN_COOKIE")
        if env_cookie:
            logger.info("[video_extractor] 从环境变量 TIANSHU_DOUYIN_COOKIE 读取 cookie")
            return env_cookie.strip()
        cookie_file = _resolve_cookie_file()
        if cookie_file and os.path.isfile(cookie_file):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    c = f.read().strip()
                if c:
                    logger.info("[video_extractor] 从 %s 读取 cookie（含登录凭证，已存于非同步目录）", cookie_file)
                    return c
            except Exception as e:
                logger.warning("[video_extractor] 读取 cookie 文件失败: %s", e)
        return ""

    def _apply_cookie(self):
        """把 cookie 注入到 session 的 cookie jar（每次请求前刷新，支持运行时变更）。

        注意：必须用 cookie jar 而非 headers['Cookie']。因为抖音短链会经过
        iesdouyin.com 等中转域 302 跳转，若用 headers 注入，登录态 cookie 会被
        原样带去中转域，触发抖音风控返回「验证码中间页」；用 jar 则跨域重定向时
        按域自动过滤，只在 douyin.com 域发送，可正常拿到 RENDER_DATA。
        """
        if self._cookie and self._session is not None:
            try:
                self._session.cookies.clear()
            except Exception:
                pass
            for part in self._cookie.split(';'):
                part = part.strip()
                if not part or '=' not in part:
                    continue
                k, v = part.split('=', 1)
                self._session.cookies.set(k.strip(), v.strip())

    def _get_session(self):
        """获取或创建 HTTP Session（含默认headers）"""
        if self._session is None:
            req = self._get_requests()
            self._session = req.Session()
            self._session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
        self._apply_cookie()
        return self._session

    def _is_safe_host(self, url: str) -> bool:
        """校验 URL 的 host 解析后的 IP 不得为环回/私网/链路本地/保留/组播地址
        （防 SSRF 访问内网或云元数据 169.254.169.254）。仅 http/https 且解析安全才放行。"""
        try:
            p = urlparse(url)
            if p.scheme not in ('http', 'https'):
                return False
            host = (p.hostname or '').strip().lower()
            if not host:
                return False
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                ip = info[4][0]
                net = ipaddress.ip_address(ip)
                if net.is_loopback or net.is_private or net.is_link_local or net.is_reserved or net.is_multicast:
                    return False
            return True
        except Exception:
            return False

    def _request_with_retry(self, url: str, timeout: int = _DEFAULT_TIMEOUT,
                             retries: int = _MAX_RETRIES, **kwargs) -> Optional['requests.Response']:
        """带超时、重试与**受控重定向跟随**的 HTTP GET。

        P0-② 安全修复：禁止无校验自动跟随重定向（SSRF 重定向绕过）。
        强制 allow_redirects=False，改为手动跟随：每跳目标 host 必须过
        _is_safe_host 校验，最多 5 跳，避免跳转到内网/云元数据地址。
        """
        kwargs['allow_redirects'] = False  # 强制关闭自动跟随，改由下方受控跟随
        session = self._get_session()
        self._apply_cookie()  # 确保本次请求带最新 cookie
        last_error = None
        current_url = url

        for _hop in range(6):  # 初始请求 + 最多 5 次重定向
            resp = None
            for attempt in range(retries + 1):
                try:
                    resp = session.get(current_url, timeout=timeout, **kwargs)
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "[video_extractor] 请求失败 (第%d次): %s - %s",
                        attempt + 1, current_url, e
                    )
                    if attempt < retries:
                        time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
            if resp is None:
                break
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get('Location'):
                loc = resp.headers['Location']
                if loc.startswith('/'):
                    from urllib.parse import urljoin
                    loc = urljoin(current_url, loc)
                if self._is_safe_host(loc):
                    logger.info("[video_extractor] 受控重定向(第%d跳): %s", _hop, loc)
                    current_url = loc
                    continue
                logger.warning("[video_extractor] 重定向目标被拒(SSRF): %s", loc)
                return resp  # 返回 3xx 响应，由调用方视为失败
            try:
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                logger.warning("[video_extractor] 响应异常: %s - %s", current_url, e)
            return resp

        logger.error("[video_extractor] 请求最终失败: %s - %s", url, last_error)
        return None

    def _post_with_retry(self, url: str, data: dict = None, json_data: dict = None,
                          timeout: int = _DEFAULT_TIMEOUT,
                          retries: int = _MAX_RETRIES, **kwargs) -> Optional['requests.Response']:
        """带超时和重试机制的HTTP POST请求"""
        session = self._get_session()
        self._apply_cookie()
        last_error = None

        for attempt in range(retries + 1):
            try:
                resp = session.post(
                    url, data=data, json=json_data,
                    timeout=timeout, **kwargs
                )
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_error = e
                logger.warning(
                    "[video_extractor] POST请求失败 (第%d次): %s - %s",
                    attempt + 1, url, e
                )
                if attempt < retries:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)

        logger.error("[video_extractor] POST请求最终失败: %s - %s", url, last_error)
        return None

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    def _get_cache_key(self, url: str) -> str:
        """根据URL生成缓存文件名（MD5）"""
        return hashlib.md5(url.encode('utf-8')).hexdigest() + '.json'

    def _get_cache_path(self, url: str) -> str:
        """获取缓存文件完整路径"""
        return os.path.join(self._cache_dir, self._get_cache_key(url))

    def _load_cache(self, url: str) -> Optional[dict]:
        """从缓存加载提取结果

        缓存有效期：24小时

        Args:
            url: 视频URL

        Returns:
            缓存数据字典，无缓存返回 None
        """
        cache_path = self._get_cache_path(url)
        if not os.path.isfile(cache_path):
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 检查缓存有效期（24小时）
            extracted_at = data.get('extracted_at', '')
            if extracted_at:
                try:
                    cached_time = datetime.fromisoformat(extracted_at)
                    if (datetime.now() - cached_time).total_seconds() > 86400:
                        logger.info("[video_extractor] 缓存已过期: %s", url[:50])
                        return None
                except (ValueError, TypeError):
                    pass

            logger.info("[video_extractor] 命中缓存: %s", url[:50])
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[video_extractor] 缓存读取失败: %s", e)
            return None

    def _save_cache(self, url: str, data: dict):
        """保存提取结果到缓存"""
        cache_path = self._get_cache_path(url)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("[video_extractor] 缓存已保存: %s", url[:50])
        except IOError as e:
            logger.warning("[video_extractor] 缓存保存失败: %s", e)

    # ------------------------------------------------------------------
    # 平台识别
    # ------------------------------------------------------------------

    def _detect_platform(self, url: str) -> str:
        """识别视频链接所属平台

        Args:
            url: 视频链接

        Returns:
            平台标识符字符串
        """
        url_lower = url.lower()
        for platform, domains in _PLATFORM_PATTERNS.items():
            for domain in domains:
                if domain in url_lower:
                    return platform
        return 'general'

    def _parse_video_id(self, url: str, platform: str) -> str:
        """从URL中解析视频ID

        Args:
            url: 视频URL
            platform: 平台标识符

        Returns:
            视频ID字符串，解析失败返回空字符串
        """
        try:
            parsed = urlparse(url)

            if platform == 'bilibili':
                # https://www.bilibili.com/video/BV1xx411c7mD
                # https://www.bilibili.com/video/av123456
                path = parsed.path
                if '/video/' in path:
                    vid = path.split('/video/')[-1].strip('/')
                    return vid
                # b23.tv 短链接需要跳转后获取
                return parsed.path.strip('/')

            elif platform == 'douyin':
                # https://www.douyin.com/video/7xxxxxxxxxxxx
                path = parsed.path
                if '/video/' in path:
                    return path.split('/video/')[-1].strip('/')
                # 从note路径提取
                if '/note/' in path:
                    return path.split('/note/')[-1].strip('/')
                return parsed.path.strip('/')

            elif platform == 'kuaishou':
                path = parsed.path
                if '/video/' in path:
                    return path.split('/video/')[-1].strip('/')
                return parsed.path.strip('/')

            elif platform == 'xiaohongshu':
                path = parsed.path
                if '/explore/' in path:
                    return path.split('/explore/')[-1].strip('/')
                if '/note/' in path:
                    return path.split('/note/')[-1].strip('/')
                return parsed.path.strip('/')

            elif platform == 'weishi':
                return parsed.path.strip('/')

            else:
                # 通用：返回路径最后一部分
                return parsed.path.strip('/').split('/')[-1]

        except Exception as e:
            logger.warning("[video_extractor] 解析视频ID失败: %s - %s", url, e)
            return ''

    # ------------------------------------------------------------------
    # 各平台提取器
    # ------------------------------------------------------------------

    def _extract_douyin(self, url: str) -> dict:
        """提取抖音视频内容

        重要：抖音 PC/移动分享页均为 CSR 架构，初始 HTML（含 RENDER_DATA）只是配置
        壳，视频文案/作者/标签等真实数据由前端通过签名 API 异步加载，不在 HTML 里。
        因此这里走抖音 Web 官方详情接口 `aweme/v1/web/aweme/detail`，带登录态 cookie
        可直接返回结构化 JSON（含 desc 文案），无需逆向签名算法。

        Args:
            url: 抖音视频链接（短链 v.douyin.com 或完整 www.douyin.com/video/xxx）

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'douyin')

        try:
            # 1) 跟随短链拿到最终 URL，从中解析 video id
            resp = self._request_with_retry(url, allow_redirects=True)
            if not resp:
                return result
            vid = self._parse_douyin_vid(resp.url) or self._parse_douyin_vid(url)
            if not vid:
                logger.warning("[video_extractor] 无法从链接解析抖音 video id: %s", url)
                return result

            # 2) 官方详情接口（主页面是 CSR 空壳，真实文案在异步接口里）
            api = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={vid}"
            r2 = self._request_with_retry(api, allow_redirects=True)
            aweme = None
            if r2:
                try:
                    aweme = r2.json().get("aweme_detail")
                except Exception:
                    aweme = None
            if not aweme:
                logger.warning(
                    "[video_extractor] 抖音详情接口未返回数据（可能链接失效或需签名）")
                return result

            # 3) 解析字段
            desc = (aweme.get("desc") or "").strip()
            author = aweme.get("author", {}) or {}
            result["title"] = (desc[:40] or author.get("nickname", ""))[:40]
            result["description"] = desc
            result["author"] = author.get("nickname", "")
            st = aweme.get("statistics", {}) or {}
            result["likes"] = self._format_number(st.get("digg_count", 0))
            result["comments"] = self._format_number(st.get("comment_count", 0))
            result["shares"] = self._format_number(st.get("share_count", 0))
            result["collects"] = self._format_number(st.get("collect_count", 0))
            tags = []
            for t in aweme.get("text_extra", []) or []:
                if isinstance(t, dict) and t.get("hashtag_name"):
                    tags.append(t["hashtag_name"])
            result["tags"] = tags
            result["status"] = "ok"
            result["used_cookie"] = bool(self._cookie)

        except Exception as e:
            logger.error("[video_extractor] 抖音提取异常: %s", e)

        return result

    def _parse_douyin_vid(self, url: str):
        """从抖音链接中解析 video id（19 位数字）。"""
        m = re.search(r"video/(\d+)", url or "")
        if m:
            return m.group(1)
        # 短链/其他形态：最后一串较长数字
        m = re.search(r"(\d{15,})", url or "")
        if m:
            return m.group(1)
        return ''

    def _extract_bilibili(self, url: str) -> dict:
        """提取B站视频内容

        策略：
          1. 解析视频BV号/AV号
          2. 通过B站Web API获取视频详情
          3. 尝试获取字幕（CC字幕）

        Args:
            url: B站视频链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'bilibili')

        try:
            # 解析视频ID
            video_id = self._parse_video_id(url, 'bilibili')
            if not video_id:
                return result

            # 将BV号转为API所需的格式
            bvid = video_id if video_id.startswith('BV') else ''
            aid = video_id if video_id.isdigit() else ''

            # 通过B站API获取视频信息
            api_url = "https://api.bilibili.com/x/web-interface/view"
            params = {}
            if bvid:
                params['bvid'] = bvid
            elif aid:
                params['aid'] = aid
            else:
                return result

            resp = self._request_with_retry(api_url, params=params)
            if resp:
                data = resp.json()
                if data.get('code') == 0:
                    info = data.get('data', {})
                    result['title'] = info.get('title', '')
                    result['description'] = info.get('desc', '')
                    result['author'] = info.get('owner', {}).get('name', '') if isinstance(info.get('owner'), dict) else str(info.get('owner', ''))
                    result['likes'] = self._format_number(info.get('like', 0))
                    result['comments'] = self._format_number(info.get('reply', 0))
                    result['shares'] = self._format_number(info.get('share', 0))
                    result['tags'] = [
                        t.get('name', '') for t in info.get('tags', [])
                        if isinstance(t, dict) and 'name' in t
                    ]

                    # 尝试获取字幕
                    cid = info.get('cid', 0)
                    if cid and bvid:
                        subtitles = self._fetch_bilibili_subtitles(bvid, cid)
                        if subtitles:
                            result['subtitles'] = subtitles

        except Exception as e:
            logger.error("[video_extractor] B站提取异常: %s", e)

        return result

    def _fetch_bilibili_subtitles(self, bvid: str, cid: int) -> str:
        """获取B站视频字幕

        Args:
            bvid: 视频BV号
            cid: 视频CID

        Returns:
            字幕文本，无字幕返回空字符串
        """
        try:
            api_url = "https://api.bilibili.com/x/player/v2"
            resp = self._request_with_retry(api_url, params={'bvid': bvid, 'cid': cid})
            if not resp:
                return ''

            data = resp.json()
            subtitle_info = data.get('data', {}).get('subtitle', {})
            subtitles_list = subtitle_info.get('subtitles', [])

            if not subtitles_list:
                return ''

            # 选取第一个可用字幕
            subtitle_url = subtitles_list[0].get('subtitle_url', '')
            if not subtitle_url:
                return ''

            # 拼接完整URL（可能以 // 开头）
            if subtitle_url.startswith('//'):
                subtitle_url = 'https:' + subtitle_url

            resp = self._request_with_retry(subtitle_url)
            if resp:
                sub_data = resp.json()
                lines = sub_data.get('body', [])
                return ' '.join(line.get('content', '') for line in lines if isinstance(line, dict))

        except Exception as e:
            logger.warning("[video_extractor] B站字幕获取失败: %s", e)
            return ''

    def _extract_kuaishou(self, url: str) -> dict:
        """提取快手视频内容

        策略：网页抓取，从HTML和meta标签提取信息

        Args:
            url: 快手视频链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'kuaishou')

        try:
            resp = self._request_with_retry(url, allow_redirects=True)
            if not resp:
                return result

            html = resp.text
            BS = self._get_bs4()
            soup = BS(html, 'html.parser')

            # 从meta标签提取
            meta_props = {
                'title': ['og:title', 'description'],
                'description': ['og:description', 'description'],
                'author': ['author'],
            }
            for field, names in meta_props.items():
                if not result.get(field):
                    for name in names:
                        tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
                        if tag:
                            result[field] = tag.get('content', '').strip()

            # 提取标题
            if not result['title']:
                title_tag = soup.find('title')
                if title_tag:
                    result['title'] = title_tag.get_text(strip=True)

            # 尝试从页面脚本中提取数据
            page_data = self._extract_json_from_script(html)
            if page_data:
                result['title'] = page_data.get('title', result['title'])
                result['description'] = page_data.get('caption', page_data.get('desc', result['description']))

        except Exception as e:
            logger.error("[video_extractor] 快手提取异常: %s", e)

        return result

    def _extract_xiaohongshu(self, url: str) -> dict:
        """提取小红书视频/笔记内容

        策略：网页抓取，从SSR数据和meta标签提取信息

        Args:
            url: 小红书链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'xiaohongshu')

        try:
            resp = self._request_with_retry(url, allow_redirects=True)
            if not resp:
                return result

            html = resp.text
            BS = self._get_bs4()
            soup = BS(html, 'html.parser')

            # 从meta标签提取
            if not result['title']:
                meta_title = soup.find('meta', attrs={'property': 'og:title'}) or soup.find('meta', attrs={'name': 'title'})
                if meta_title:
                    result['title'] = meta_title.get('content', '').strip()

            if not result['description']:
                meta_desc = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'description'})
                if meta_desc:
                    result['description'] = meta_desc.get('content', '').strip()

            # 提取标题
            if not result['title']:
                title_tag = soup.find('title')
                if title_tag:
                    result['title'] = title_tag.get_text(strip=True)

            # 从页面script中提取 __INITIAL_STATE__
            init_state = self._extract_initial_state(html)
            if init_state:
                note_data = init_state.get('note', {}).get('noteDetailMap', {})
                if note_data:
                    # 取第一个note
                    first_note_key = list(note_data.keys())[0] if note_data else ''
                    note_info = note_data.get(first_note_key, {}).get('note', {})
                    if isinstance(note_info, dict):
                        result['title'] = note_info.get('title', result['title'])
                        result['description'] = note_info.get('desc', result['description'])
                        result['author'] = note_info.get('user', {}).get('nickname', '') if isinstance(note_info.get('user'), dict) else ''
                        result['likes'] = self._format_number(note_info.get('interactInfo', {}).get('likedCount', '0'))
                        result['tags'] = [
                            t.get('name', '') for t in note_info.get('tagList', [])
                            if isinstance(t, dict) and 'name' in t
                        ]

        except Exception as e:
            logger.error("[video_extractor] 小红书提取异常: %s", e)

        return result

    def _extract_weishi(self, url: str) -> dict:
        """提取微信视频号内容

        策略：网页抓取，从meta标签和og数据提取

        Args:
            url: 微信视频号链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'weishi')

        try:
            resp = self._request_with_retry(url, allow_redirects=True)
            if not resp:
                return result

            html = resp.text
            BS = self._get_bs4()
            soup = BS(html, 'html.parser')

            # 从meta标签提取
            meta_og = soup.find('meta', attrs={'property': 'og:title'})
            if meta_og:
                result['title'] = meta_og.get('content', '').strip()

            meta_desc = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                result['description'] = meta_desc.get('content', '').strip()

            meta_author = soup.find('meta', attrs={'property': 'og:author'}) or soup.find('meta', attrs={'name': 'author'})
            if meta_author:
                result['author'] = meta_author.get('content', '').strip()

            if not result['title']:
                title_tag = soup.find('title')
                if title_tag:
                    result['title'] = title_tag.get_text(strip=True)

        except Exception as e:
            logger.error("[video_extractor] 微信视频号提取异常: %s", e)

        return result

    def _extract_general(self, url: str) -> dict:
        """通用视频内容提取

        策略：
          1. 优先尝试 yt-dlp（如已安装）
          2. 回退到网页抓取

        Args:
            url: 视频链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'general')

        # 尝试使用 yt-dlp
        if _yt_dlp_available:
            result = self._extract_with_yt_dlp(url)
            if result.get('title') or result.get('description'):
                return result

        # 回退到网页抓取
        try:
            resp = self._request_with_retry(url, allow_redirects=True)
            if not resp:
                return result

            html = resp.text
            BS = self._get_bs4()
            soup = BS(html, 'html.parser')

            # 从meta标签提取
            meta_og_title = soup.find('meta', attrs={'property': 'og:title'})
            if meta_og_title:
                result['title'] = meta_og_title.get('content', '').strip()

            meta_og_desc = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'description'})
            if meta_og_desc:
                result['description'] = meta_og_desc.get('content', '').strip()

            if not result['title']:
                title_tag = soup.find('title')
                if title_tag:
                    result['title'] = title_tag.get_text(strip=True)

        except Exception as e:
            logger.error("[video_extractor] 通用提取异常: %s", e)

        return result

    def _extract_with_yt_dlp(self, url: str) -> dict:
        """使用yt-dlp提取视频内容

        Args:
            url: 视频链接

        Returns:
            提取结果字典
        """
        result = self._empty_result(url, 'general')
        try:
            import subprocess
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-download',
                '--skip-download',
                '--write-auto-sub',
                '--sub-lang', 'zh',
                '--quiet',
                url
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=60, cwd=self._cache_dir
            )

            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                result['title'] = data.get('title', '')
                result['description'] = data.get('description', '')
                result['author'] = data.get('uploader', '') or data.get('channel', '')
                result['likes'] = self._format_number(data.get('like_count', 0))
                result['comments'] = self._format_number(data.get('comment_count', 0))
                result['tags'] = data.get('tags', [])

                # 字幕
                if data.get('automatic_captions'):
                    for lang, sub_list in data.get('automatic_captions', {}).items():
                        if 'zh' in lang:
                            # 取第一个字幕URL
                            for sub in sub_list:
                                if sub.get('url'):
                                    sub_resp = self._request_with_retry(sub['url'])
                                    if sub_resp:
                                        # 字幕可能是VTT格式
                                        result['subtitles'] = self._parse_vtt(sub_resp.text)
                                    break
                            break

                # 手动字幕
                if not result['subtitles'] and data.get('subtitles'):
                    for lang, sub_list in data.get('subtitles', {}).items():
                        if 'zh' in lang:
                            for sub in sub_list:
                                if sub.get('url'):
                                    sub_resp = self._request_with_retry(sub['url'])
                                    if sub_resp:
                                        result['subtitles'] = self._parse_vtt(sub_resp.text)
                                    break
                            break

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning("[video_extractor] yt-dlp提取失败: %s", e)
        except Exception as e:
            logger.error("[video_extractor] yt-dlp异常: %s", e)

        return result

    # ------------------------------------------------------------------
    # HTML解析辅助
    # ------------------------------------------------------------------

    def _extract_render_data(self, html: str) -> Optional[dict]:
        """从抖音HTML中提取RENDER_DATA（URL编码的JSON）

        Args:
            html: 页面HTML文本

        Returns:
            解析出的数据字典，失败返回None
        """
        try:
            import urllib.parse
            # 匹配 <script id="RENDER_DATA" ...>...</script>
            pattern = r'<script\s+id="RENDER_DATA"[^>]*>([^<]+)</script>'
            match = re.search(pattern, html)
            if match:
                encoded = match.group(1)
                decoded = urllib.parse.unquote(encoded)
                data = json.loads(decoded)
                # 抖音RENDER_DATA通常是嵌套结构，尝试取到视频详情
                for key, val in data.items():
                    if isinstance(val, dict):
                        if 'aweme' in val or 'detail' in val:
                            # 可能有多层嵌套
                            aweme = val.get('aweme', {}).get('awemeDetail', {}) if isinstance(val.get('aweme'), dict) else {}
                            if not aweme:
                                aweme = val.get('detail', {})
                            if isinstance(aweme, dict) and aweme:
                                return aweme
                return data
        except Exception as e:
            logger.warning("[video_extractor] RENDER_DATA解析失败: %s", e)
        return None

    def _extract_json_from_script(self, html: str) -> Optional[dict]:
        """从HTML的script标签中提取JSON数据

        Args:
            html: 页面HTML文本

        Returns:
            解析出的数据字典，失败返回None
        """
        try:
            BS = self._get_bs4()
            soup = BS(html, 'html.parser')
            for script in soup.find_all('script'):
                text = script.string or ''
                if not text:
                    continue
                # 尝试解析JSON（可能是 window.__data__ = {...} 格式）
                json_match = re.search(r'(?:window\.__DATA__\s*=\s*|__INITIAL_DATA__\s*=\s*)(\{.+?\})\s*;?\s*$', text, re.DOTALL)
                if json_match:
                    try:
                        return json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("[video_extractor] 脚本数据提取失败: %s", e)
        return None

    def _extract_initial_state(self, html: str) -> Optional[dict]:
        """从小红书HTML中提取 __INITIAL_STATE__

        Args:
            html: 页面HTML文本

        Returns:
            解析出的数据字典，失败返回None
        """
        try:
            pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*</script>'
            match = re.search(pattern, html, re.DOTALL)
            if match:
                raw = match.group(1)
                # 小红书的INITIAL_STATE中可能包含 undefined，需要替换
                raw = raw.replace('undefined', 'null')
                return json.loads(raw)
        except Exception as e:
            logger.warning("[video_extractor] INITIAL_STATE解析失败: %s", e)
        return None

    @staticmethod
    def _parse_vtt(text: str) -> str:
        """解析WebVTT字幕文件，提取纯文本

        Args:
            text: VTT文件内容

        Returns:
            字幕纯文本（去除时间戳和标签）
        """
        lines = text.strip().split('\n')
        text_lines = []
        in_block = False

        for line in lines:
            line = line.strip()
            # 跳过WEBVTT头部
            if line.startswith('WEBVTT') or not line:
                continue
            # 跳过时间戳行（格式: 00:00:00.000 --> 00:00:00.000）
            if '-->' in line:
                in_block = True
                continue
            # 跳过序号行
            if re.match(r'^\d+$', line):
                continue
            # 跳过样式标签
            if line.startswith('<') and line.endswith('>'):
                # 去除HTML标签
                clean = re.sub(r'<[^>]+>', '', line)
                if clean:
                    text_lines.append(clean)
                continue
            if in_block and line:
                # 去除HTML标签
                clean = re.sub(r'<[^>]+>', '', line)
                if clean:
                    text_lines.append(clean)

        return ' '.join(text_lines)

    @staticmethod
    def _format_number(num) -> str:
        """格式化数字为可读字符串

        Args:
            num: 数字（可能是int、str、float）

        Returns:
            格式化后的字符串，如 "1.2万"
        """
        try:
            n = int(num) if not isinstance(num, (int, float)) else num
            if n >= 100000000:
                return f"{n / 100000000:.1f}亿"
            elif n >= 10000:
                return f"{n / 10000:.1f}万"
            else:
                return str(n)
        except (ValueError, TypeError):
            return str(num) if num else '0'

    def _empty_result(self, url: str, platform: str) -> dict:
        """创建空的结果字典

        Args:
            url: 原始链接
            platform: 平台标识符

        Returns:
            标准格式的空结果字典
        """
        return {
            "url": url,
            "platform": platform,
            "platform_name": _PLATFORM_NAMES.get(platform, platform),
            "title": "",
            "description": "",
            "subtitles": "",
            "author": "",
            "likes": "",
            "comments": "",
            "shares": "",
            "top_comments": [],
            "tags": [],
            "extracted_at": datetime.now().isoformat(),
            "used_cookie": False,
        }

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def extract(self, url: str, use_cache: bool = True, cookie: str = None) -> dict:
        """提取视频内容，返回结构化数据

        自动识别平台并选择对应提取策略。
        支持缓存机制减少重复请求。

        Args:
            url: 视频链接
            use_cache: 是否使用缓存，默认True
            cookie: 用户手动提供的登录态 cookie（覆盖初始化时的 cookie），
                   用于抖音等需登录态才能取到数据的平台。

        Returns:
            提取结果字典，包含以下字段：
            - url: 原始链接
            - platform: 平台标识符
            - platform_name: 平台中文名
            - title: 视频标题
            - description: 视频描述/文案
            - subtitles: 字幕文本（如有）
            - author: 作者
            - likes: 点赞数
            - comments: 评论数
            - shares: 分享数
            - top_comments: 热门评论列表
            - tags: 标签列表
            - extracted_at: 提取时间
            - used_cookie: 本次请求是否带了登录态 cookie

        Raises:
            ValueError: URL为空或格式无效
        """
        if not url or not url.strip():
            raise ValueError("视频链接不能为空")

        url = url.strip()
        if not url.startswith('http://') and not url.startswith('https://'):
            # 尝试补全协议
            url = 'https://' + url

        # 运行时覆盖 cookie（用户每次调用可传入不同账号的登录态）
        if cookie is not None:
            self._cookie = cookie
            self._apply_cookie()

        # 尝试从缓存加载
        if use_cache:
            cached = self._load_cache(url)
            if cached:
                return cached

        # 识别平台
        platform = self._detect_platform(url)
        logger.info("[video_extractor] 开始提取: platform=%s, url=%s", platform, url[:60])

        # 根据平台选择提取器
        extractors = {
            'douyin': self._extract_douyin,
            'bilibili': self._extract_bilibili,
            'kuaishou': self._extract_kuaishou,
            'xiaohongshu': self._extract_xiaohongshu,
            'weishi': self._extract_weishi,
            'general': self._extract_general,
        }

        extractor = extractors.get(platform, self._extract_general)
        try:
            result = extractor(url)
        except ImportError as e:
            # requests/beautifulsoup4 未安装时的降级
            logger.warning("[video_extractor] 依赖库缺失: %s", e)
            result = self._empty_result(url, platform)
            result['description'] = f"提取失败：{e}，请安装依赖 pip install requests beautifulsoup4"
        except Exception as e:
            logger.error("[video_extractor] 提取异常: %s", e, exc_info=True)
            result = self._empty_result(url, platform)
            result['description'] = f"提取失败：{e}"

        # 更新时间戳 + 记录是否使用 cookie
        result['extracted_at'] = datetime.now().isoformat()
        result['used_cookie'] = bool(self._cookie)

        # 保存缓存
        self._save_cache(url, result)

        return result
