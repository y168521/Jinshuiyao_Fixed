# -*- coding: utf-8 -*-
"""彩票专用 — 多数据源抓取器

适用范围：彩票子系统（双色球/大乐透/福彩3D/排列三/七星彩/七乐彩/快乐8）

职责：从多个公开数据源（CWL官方/500.com/新浪/体彩/乐彩/彩宝贝/55128等）
抓取开奖数据，合并去重后保存为 JSON 文件。

与 fetchers/data_fetcher.py 的关系（非重复，职责不同）：
  - fetchers/fetcher.py       — 彩票开奖数据抓取（多源采集、合并、持久化）
  - fetchers/data_fetcher.py  — 足彩数据拉取 CLI 入口（命令行工具，调用 jinshuiyao/ 模块）

调用方：core/scheduler.py、preload.py、domains/lottery/domain.py、
        importers/lottery_data_importer.py、gui/main_window.py
"""
import os
import re
import threading
import json
import time
import datetime
import random
import subprocess
import requests
import logging
from models.lottery_data import Data
from utils.cache_manager import CacheManager
from utils.locks import json_lock
from utils.safe_json import safe_load_json, safe_write_json
from utils.number_utils import is_valid_period
from filters.period_normalizer import PeriodNormalizer
from config import DATA_SAVE, LOTTERY_RULES
from core.circuit_breaker import get_breaker


logger = logging.getLogger("jinshuiyao.fetcher")


def _norm_draw_date(s):
    """从任意字符串提取 YYYY-MM-DD 开奖日期（去除可能的星期后缀，如 '2026-07-21(二)' → '2026-07-21'）。

    修复 P0-3 根因：双色球/大乐透/七星彩/七乐彩 走 500.com 解析分支时原硬编码 time=""，
    导致开奖日期字段全空。500.com 历史页每行都带开奖日期列，这里统一归一化为干净日期。
    """
    if not s:
        return ""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', str(s))
    return m.group(1) if m else ""

# ──────────────────────────────────────────────────────────────────────────
# 统一缓存层（cache_manager 接入点）
# 仅在「抓取网络层」对幂等 GET 响应做短 TTL 缓存，降低重复抓取的网络开销，
# 不改变任何预测逻辑。缓存仅驻留内存（L1），不落盘，避免污染金水谣数据目录。
#   - 环境变量 TIANSHU_HTTP_CACHE_TTL  控制 TTL（秒，默认 120）
#   - 环境变量 TIANSHU_DISABLE_HTTP_CACHE 设为任意值即关闭缓存
# ──────────────────────────────────────────────────────────────────────────
_HTTP_CACHE_TTL = int(os.environ.get("TIANSHU_HTTP_CACHE_TTL", "120"))
_HTTP_CACHE_DISABLED = bool(os.environ.get("TIANSHU_DISABLE_HTTP_CACHE"))
_http_cache = CacheManager(memory_ttl=_HTTP_CACHE_TTL)
_http_cache.disable_file_fallback()  # 仅内存，避免 L2 文件读写


# ──────────────────────────────────────────────────────────────────────────
# 进程级单例 Fetcher
# 避免每次抓取新建 requests.Session / HTTPAdapter（降低连接开销）；
# 全局熔断器 CircuitBreakerRegistry 本身已是进程级单例，熔断状态跨调用/跨实例持久，
# 根治「Fetcher 每次新建 → 实例级熔断状态清零 → 熔断不生效」的根因（P2）。
# ──────────────────────────────────────────────────────────────────────────
_fetcher_instance = None
_fetcher_lock = threading.Lock()


def get_fetcher():
    """获取进程级单例 Fetcher（懒初始化，线程安全双重检查）。"""
    global _fetcher_instance
    if _fetcher_instance is None:
        with _fetcher_lock:
            if _fetcher_instance is None:
                _fetcher_instance = Fetcher()
    return _fetcher_instance


class _CachedHTTPResponse:
    """复用 cache_manager 缓存的 HTTP 文本结果的轻量只读响应对象。

    仅实现 fetcher 实际用到的接口（.text / .status_code / .encoding / .json()），
    让命中缓存的响应与原 requests.Response 在使用处完全等价。
    """
    __slots__ = ("text", "status_code", "encoding", "apparent_encoding")

    def __init__(self, text, status_code=200, encoding="utf-8"):
        self.text = text
        self.status_code = status_code
        self.encoding = encoding
        self.apparent_encoding = encoding

    def json(self):
        import json as _json
        return _json.loads(self.text)


def _http_cache_key(url, params, headers):
    """为一次幂等 GET 请求生成稳定缓存键。"""
    parts = [url]
    if params:
        parts.append("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())))
    if headers:
        parts.append("#" + "&".join(f"{k}={headers[k]}" for k in sorted(headers)))
    return "http:" + "|".join(str(p) for p in parts)


class Fetcher:
    def __init__(self):
        self.s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=2)
        self.s.mount('http://', adapter)
        self.s.mount('https://', adapter)
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.last_error = ""
        self.max_retries = 3
        self.timeout = 6
        # 源健康时间戳（供 S6 /api/lottery/sources-health 可观测，进程级单例持有→跨调用持久）
        self._health_lock = threading.Lock()
        self._source_health = {}  # src_name -> {"last_ok": float, "last_fail": float}

    def _source_ok(self, src_name):
        """检查数据源是否健康（经全局三态熔断器，跨调用/跨实例持久）。"""
        return get_breaker(f"lottery:{src_name}").can_execute()

    def _source_fail(self, src_name):
        """记录数据源失败，连续失败达阈值后熔断（阈值/恢复由全局熔断器管理）。"""
        get_breaker(f"lottery:{src_name}").record_failure()
        with self._health_lock:
            self._source_health.setdefault(src_name, {})["last_fail"] = time.time()

    def _source_success(self, src_name):
        """数据源成功，重置熔断失败计数。"""
        get_breaker(f"lottery:{src_name}").record_success()
        with self._health_lock:
            self._source_health.setdefault(src_name, {})["last_ok"] = time.time()

    def get_sources_health(self):
        """返回各数据源健康快照（供 S6 /api/lottery/sources-health 可观测）。"""
        with self._health_lock:
            health = {k: dict(v) for k, v in self._source_health.items()}
        result = []
        for src_name, info in health.items():
            st = get_breaker(f"lottery:{src_name}").get_stats()
            result.append({
                "source": src_name,
                "state": st["state"],
                "failure_count": st["failure_count"],
                "total_success": st["total_success"],
                "total_failure": st["total_failure"],
                "last_failure": st["last_failure"],
                "last_ok_ts": info.get("last_ok"),
                "last_fail_ts": info.get("last_fail"),
            })
        return result

    def _request_with_retry(self, url, params=None, timeout_override=None, headers=None):
        timeout = timeout_override if timeout_override else self.timeout
        req_headers = self.s.headers.copy()
        if headers:
            req_headers.update(headers)

        # —— 统一缓存层：命中则直接返回缓存的只读响应，跳过网络请求 ——
        if not _HTTP_CACHE_DISABLED:
            cache_key = _http_cache_key(url, params, headers)
            cached = _http_cache.get(cache_key)
            if cached is not None:
                logger.debug("HTTP 缓存命中: %s", url)
                return _CachedHTTPResponse(
                    text=cached.get("text", ""),
                    status_code=cached.get("status_code", 200),
                    encoding=cached.get("encoding", "utf-8"),
                )

        for attempt in range(self.max_retries):
            try:
                r = self.s.get(url, params=params, timeout=timeout, headers=req_headers)
                if r.status_code == 200:
                    r.encoding = r.apparent_encoding
                    # 写入缓存（仅内存，TTL 内复用）
                    if not _HTTP_CACHE_DISABLED:
                        _http_cache.set(
                            _http_cache_key(url, params, headers),
                            {"text": r.text, "status_code": r.status_code, "encoding": r.encoding},
                            ttl=_HTTP_CACHE_TTL,
                        )
                    return r
                self.last_error = f"HTTP {r.status_code}"
            except Exception as e:
                self.last_error = str(e)
                # —— DNS 自愈：本机曾因 Windows DNS 缓存损坏导致整晚抓取失败 ——
                # 症状：getaddrinfo failed / NameResolutionError，但 PowerShell/其他进程解析正常。
                # 处理：flushdns 后继续重试循环（仅 Windows，静默失败不致命）。
                if os.name == "nt" and ("getaddrinfo failed" in str(e) or "NameResolutionError" in str(e)):
                    try:
                        subprocess.run(["ipconfig", "/flushdns"],
                                       capture_output=True, timeout=10,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        logger.warning("[Fetcher] DNS 缓存异常，已自动 flushdns，重试 %s", url)
                    except Exception:
                        pass
                    time.sleep(2)
            if attempt < self.max_retries - 1:
                time.sleep(min(1 * (2 ** attempt), 8))  # 指数退避: 1s→2s→4s, 上限8s
        return None

    def _fetch_cwl(self, name, eng):
        # CWL(中国福利彩票官网)仅支持以下彩种，其余调用必然404/无result
        _CWL_VALID_ENG = ("ssq", "dlt", "3d", "qlc", "qxc", "kl8")
        if eng not in _CWL_VALID_ENG:
            print(f"🔍 [诊断CWL] {name}({eng}): 不在CWL支持列表{_CWL_VALID_ENG}中，跳过")
            return []
        url = f"https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name={eng}&issueCount=200"
        r = self._request_with_retry(url)
        if not r:
            print(f"🔍 [诊断CWL] {name}({eng}): 请求失败 - {self.last_error}")
            return []
        try:
            data = r.json()
            if "result" not in data:
                print(f"🔍 [诊断CWL] {name}({eng}): 返回无result字段, keys={list(data.keys())[:5]}")
                return []
            out = []
            for item in data["result"]:
                period_raw = item["code"]
                try:
                    period_int = int(period_raw)
                except Exception as e:
                    logger.debug("_fetch_cwl: 单条解析失败跳过: %s", e)
                    continue
                result = PeriodNormalizer.normalize(period_int, name)
                if result is not None:
                    period_int = result
                nums = item.get("red", "")
                if name in ("双色球", "大乐透"):
                    red = item.get("red", "")
                    blue = item.get("blue", "")
                    # 验证是否包含数字（CWL API 大乐透 red 字段可能返回"摇奖用球/套"等非数字数据）
                    red_ok = bool(red and re.search(r'\d', str(red)))
                    blue_ok = bool(blue and re.search(r'\d', str(blue)))
                    if red_ok and blue_ok:
                        nums = f"{red}+{blue}"
                    elif red_ok:
                        nums = red
                    elif blue_ok:
                        nums = blue
                    else:
                        nums = ""
                # 跳过无效号码（CWL API 可能返回"摇奖用球/套"等非数字数据）
                if not nums or not re.search(r'\d', str(nums)):
                    continue
                out.append({"period": period_int, "lottery": name, "nums": nums, "time": _norm_draw_date(item.get("date", ""))})
            # 🔍 诊断：大乐透抓取数据
            if name == "大乐透":
                raw_count = len(data.get("result", []))
                print(f"🔍 [诊断CWL] 大乐透: API返回{raw_count}条, 有效{len(out)}条")
                if out:
                    last = out[-1]
                    print(f"🔍 [诊断CWL] 大乐透最新: period={last['period']}, nums={repr(last['nums'])}")
                else:
                    # 打印第一条无效数据看看
                    for item in data.get("result", [])[:1]:
                        print(f"🔍 [诊断CWL] 大乐透无效样本: red={repr(item.get('red',''))} blue={repr(item.get('blue',''))}")
            return out
        except Exception as e:
            print(f"🔍 [诊断CWL] {name}({eng}): 异常 - {e}")
            return []

    def _fetch_500(self, name):
        urls = {
            "双色球": "https://datachart.500.com/ssq/history/newinc/history.php?start=21001&end=99999",
            "大乐透": "https://datachart.500.com/dlt/history/newinc/history.php?start=21001&end=99999",
            "福彩3D": "https://datachart.500.com/sd/history/newinc/history.php?start=21001&end=99999",
            "排列三": "http://datachart.500.com/pls/history/inc/history.php?limit=200&start=26001&end=99999",
            "七星彩": [
                "https://datachart.500.com/qxc/history/history.php?limit=200&start=21001&end=99999",
                "http://datachart.500.com/qxc/history/inc/history.php?limit=200&start=21001&end=99999",
                "https://datachart.500.com/qxc/history/newinc/history.php?start=21001&end=99999",
            ],
            "七乐彩": "https://datachart.500.com/qlc/history/newinc/history.php?start=21001&end=99999",
            "快乐8": "https://datachart.500.com/kl8/history/newinc/history.php?start=21001&end=99999",
        }
        if name not in urls:
            return []
        url_entry = urls[name]
        url_list = url_entry if isinstance(url_entry, list) else [url_entry]
        r = None
        for url in url_list:
            r = self._request_with_retry(url)
            if r:
                break
        if not r:
            if name == "七星彩":
                print(f"🔍 [诊断500] {name}: 所有URL请求均失败, 最后错误 - {self.last_error}")
            return []
        try:
            # 大乐透/双色球/七乐彩/七星彩专用行解析，避免通用列解析错位
            if name in ["大乐透", "双色球", "七乐彩", "七星彩"]:
                if name == "七星彩":
                    return self._parse_500_qxc(r.text, name)
                if name == "七乐彩":
                    return self._parse_500_qlc(r.text, name)
                return self._parse_500_row(r.text, name)
            periods = re.findall(r'<td[^>]*>(\d{5,7})<\/td>', r.text)
            nums_all = re.findall(r'<td[^>]*class="[^"]*\d[^"]*"[^>]*>(.*?)<\/td>', r.text, re.DOTALL)
            if not periods or not nums_all:
                return []
            out = []
            for i in range(min(len(periods), len(nums_all))):
                try:
                    period_int = int(periods[i])
                except Exception as e:
                    logger.debug("_fetch_500: 单条解析失败跳过: %s", e)
                    continue
                raw = re.sub(r'\s+', '', nums_all[i])
                # 剥离HTML标签
                raw = re.sub(r'<[^>]+>', '', raw)
                if name in ["双色球", "大乐透"] and '+' not in raw and ',' not in raw:
                    digits = [raw[i:i + 2] for i in range(0, len(raw), 2) if i + 1 < len(raw) and raw[i:i + 2].isdigit()]
                    if name == "双色球" and len(digits) >= 7:
                        raw = ",".join(digits[:6]) + "+" + ",".join(digits[6:7])
                    elif name == "大乐透" and len(digits) >= 7:
                        raw = ",".join(digits[:5]) + "+" + ",".join(digits[5:7])
                result = PeriodNormalizer.normalize(period_int, name)
                if result is not None:
                    period_int = result
                out.append({"period": period_int, "lottery": name, "nums": raw, "time": _norm_draw_date(row)})
            return out
        except Exception as e:
            print(f"🔍 [诊断500] {name}: 异常 - {e}")
            return []

    def _parse_500_qlc(self, html, name):
        """七乐彩500.com专用解析器：取7个基本号，忽略特别号。"""
        out = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for row in rows:
            period_match = re.search(r'<td[^>]*>\s*(\d{5,7})\s*</td>', row)
            nums_match = re.search(r'<td[^>]*class="[^"]*cfont2[^"]*"[^>]*>(.*?)</td>', row, re.DOTALL)
            if not period_match or not nums_match:
                continue
            try:
                period_int = int(period_match.group(1))
            except Exception as e:
                logger.debug("_parse_500_qlc: 单条解析失败跳过: %s", e)
                continue
            nums_text = re.sub(r'<[^>]+>', ' ', nums_match.group(1))
            nums = [int(x) for x in re.findall(r'\d+', nums_text)]
            if len(nums) < 7:
                continue
            reds = nums[:7]
            if not all(1 <= x <= 30 for x in reds):
                continue
            result = PeriodNormalizer.normalize(period_int, name)
            if result is not None:
                period_int = result
            out.append({
                "period": period_int,
                "lottery": name,
                "nums": ",".join(f"{x:02d}" for x in reds),
                "time": _norm_draw_date(row),
            })
        print(f"🔍 [诊断500-{name}] 七乐彩专用解析: 找到{len(out)}条有效记录")
        return out

    def _parse_500_qxc(self, html, name):
        """七星彩500.com专用解析器：号码以拼接字符串形式存储（如26545672）"""
        out = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for row in rows:
            # 期号td（含或不含class均可）
            period_match = re.search(r'<td[^>]*>\s*(\d{5,7})\s*</td>', row)
            if not period_match:
                continue
            period_raw = period_match.group(1)
            try:
                period_int = int(period_raw)
            except Exception as e:
                logger.debug("_parse_500_qxc: 单条解析失败跳过: %s", e)
                continue
            # 找td中包含的长数字串（彩票号码拼接串，如26545672）
            # 七星彩号码是7位拼接：前6位每位0-9，第7位可能0-14（占1-2位），总共7-8位数字
            num_match = re.search(r'<td[^>]*>\s*(\d{7,8})\s*</td>', row)
            if not num_match:
                continue
            nums_raw = num_match.group(1)
            # 拆分号码：7位=每位0-9，8位=前7位+额外数字
            if len(nums_raw) == 7:
                reds = list(nums_raw[:6])
                blue = nums_raw[6]
            elif len(nums_raw) == 8:
                # 取前7位作为号码（第8位是页面额外列如和值尾数）
                reds = list(nums_raw[:6])
                blue = nums_raw[6]
            else:
                continue
            # 前6位必须都是0-9
            if not all(c.isdigit() and 0 <= int(c) <= 9 for c in reds):
                continue
            # 第7位0-14
            try:
                blue_int = int(blue)
                if not (0 <= blue_int <= 14):
                    continue
            except Exception as e:
                logger.debug("_parse_500_qxc: 单条解析失败跳过: %s", e)
                continue
            nums_str = ",".join(reds) + "+" + blue
            result = PeriodNormalizer.normalize(period_int, name)
            if result is not None:
                period_int = result
            out.append({"period": period_int, "lottery": name, "nums": nums_str, "time": _norm_draw_date(row)})
        if out:
            print(f"🔍 [诊断500-{name}] 拼接解析: 找到{len(out)}条有效记录")
        else:
            print(f"🔍 [诊断500-{name}] 拼接解析失败: 总行={len(rows)}, 无有效记录")
        return out

    def _parse_500_row(self, html, name):
        """500.com行解析器 - 双色球/大乐透/七星彩"""
        rule = LOTTERY_RULES.get(name, {})
        red_cfg = rule.get("red", (1, 33, 6))
        blue_cfg = rule.get("blue", (1, 16, 1))
        if isinstance(red_cfg[0], tuple):
            red_count = sum(r[2] for r in red_cfg)
            red_max = max(r[1] for r in red_cfg)
            red_min = min(r[0] for r in red_cfg)
        elif len(red_cfg) >= 3:
            red_min, red_max, red_count = red_cfg[0], red_cfg[1], red_cfg[2]
        else:
            red_min, red_max, red_count = 1, 35, 7
        blue_cfg = rule.get("blue")
        if blue_cfg and len(blue_cfg) >= 3:
            blue_min, blue_max, blue_count = blue_cfg[0], blue_cfg[1], blue_cfg[2]
        else:
            blue_min, blue_max, blue_count = 0, 99, 0
        total_needed = red_count + blue_count
        out = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        for row in rows:
            period_match = re.search(r'<td[^>]*>\s*(\d{5,7})\s*</td>', row)
            if not period_match:
                continue
            period_raw = period_match.group(1)
            try:
                period_int = int(period_raw)
            except Exception as e:
                logger.debug("_parse_500_row: 单条解析失败跳过: %s", e)
                continue
            num_tds = re.findall(r'<td[^>]*class="[^"]*\d[^"]*"[^>]*>\s*(\d+)\s*</td>', row)
            if not num_tds:
                num_tds = re.findall(r'<td[^>]*class="cfont[24]"[^>]*>\s*(\d+)\s*</td>', row)
            if not num_tds:
                all_tds = re.findall(r'<td[^>]*>\s*(\d+)\s*</td>', row)
                num_tds = [n for n in all_tds if n != period_raw]
            if not num_tds:
                continue
            valid_nums = []
            for n in num_tds:
                try:
                    v = int(n)
                    if blue_count > 0:
                        if red_min <= v <= max(red_max, blue_max):
                            valid_nums.append(n.zfill(2))
                    else:
                        if red_min <= v <= red_max:
                            valid_nums.append(n)
                except Exception as e:
                    logger.debug("_parse_500_row: 单条解析失败跳过: %s", e)
                    continue
            if len(valid_nums) < total_needed:
                continue
            reds = valid_nums[:red_count]
            if blue_count > 0:
                blues = valid_nums[red_count:red_count + blue_count]
                raw = ",".join(reds) + "+" + ",".join(blues)
            else:
                raw = ",".join(reds)
            result = PeriodNormalizer.normalize(period_int, name)
            if result is not None:
                period_int = result
            out.append({"period": period_int, "lottery": name, "nums": raw, "time": _norm_draw_date(row)})
        if out:
            print(f"🔍 [诊断500-{name}] 行解析: 找到{len(out)}条有效记录")
        else:
            # 诊断：为什么没找到记录
            total_rows = len(rows)
            rows_with_period = sum(1 for row in rows if re.search(r'<td[^>]*>\s*(\d{5,7})\s*</td>', row))
            rows_with_enough = 0
            sample_nums = []
            for row in rows[:5]:
                num_tds = re.findall(r'<td[^>]*class="[^"]*\d[^"]*"[^>]*>\s*(\d+)\s*</td>', row)
                if num_tds:
                    sample_nums.append(num_tds[:10])
                    if len(num_tds) >= total_needed:
                        rows_with_enough += 1
            print(f"🔍 [诊断500-{name}] 行解析失败: 总行={total_rows} 有期号={rows_with_period} 够{total_needed}个号码={rows_with_enough} 样本={sample_nums[:3]}")
        return out

    def _fetch_55128(self, name):
        """55128.cn 移动端 - 七星彩"""
        if name != "七星彩":
            return []
        url = "https://m.55128.cn/kjh/qxc-history-80.htm"
        r = self._request_with_retry(url, timeout_override=10)
        if not r:
            print(f"🔍 [诊断55128] 七星彩: 请求失败 - {self.last_error}")
            return []
        out = []
        try:
            # 匹配: 期号 + 号码（7位数字拼接，如 35697012）
            # 格式: 第 2026066 期 ... 35697012
            pattern = r'第\s*(\d{5,7})\s*期.*?(\d{7,8})'
            matches = re.findall(pattern, r.text, re.DOTALL)
            for period_raw, nums_raw in matches:
                try:
                    period_int = int(period_raw)
                except Exception as e:
                    logger.debug("_fetch_55128: 单条解析失败跳过: %s", e)
                    continue
                # 号码拼接格式: 前6位+第7位(可能1-2位数字)
                # 如 "35697012" = 3,5,6,9,7,0 + 12
                if len(nums_raw) == 7:
                    # 最后1位是0-9
                    reds = list(nums_raw[:6])
                    blue = nums_raw[6]
                elif len(nums_raw) == 8:
                    # 最后2位是10-14
                    reds = list(nums_raw[:6])
                    blue = nums_raw[6:8]
                else:
                    continue
                # 验证每位数字
                valid = True
                for c in reds:
                    if not c.isdigit():
                        valid = False
                        break
                if not valid or not blue.isdigit():
                    continue
                nums_str = ",".join(reds) + "+" + blue
                result = PeriodNormalizer.normalize(period_int, name)
                if result is not None:
                    period_int = result
                out.append({"period": period_int, "lottery": name, "nums": nums_str, "time": ""})
            if out:
                print(f"🔍 [诊断55128] 七星彩: 找到{len(out)}条记录")
            return out
        except Exception as e:
            print(f"🔍 [诊断55128] 七星彩: 异常 - {e}")
            return []

    def _fetch_lecai(self, name):
        url_map = {
            "双色球": "https://www.lecai.com/ssq/history/",
            "大乐透": "https://www.lecai.com/dlt/history/",
            "福彩3D": "https://www.lecai.com/3d/history/",
            "排列三": "https://www.lecai.com/pl3/history/",
            "七乐彩": "https://www.lecai.com/qlc/history/",
            "七星彩": "https://www.lecai.com/qxc/history/",
            "快乐8": "https://www.lecai.com/kl8/history/",
        }
        if name not in url_map:
            return []
        r = self._request_with_retry(url_map[name])
        if not r:
            return []
        out = []
        try:
            period_list = re.findall(r'期号[:：]\s*(\d+)', r.text)
            num_list = re.findall(r'开奖号码[:：]\s*([\d\s\+]+)', r.text)
            for p, n in zip(period_list, num_list):
                try:
                    p_int = int(p)
                except Exception as e:
                    logger.debug("_fetch_lecai: 单条解析失败跳过: %s", e)
                    continue
                num_str = re.sub(r'\s+', '', n)
                result = PeriodNormalizer.normalize(p_int, name)
                if result is not None:
                    p_int = result
                out.append({"period": p_int, "lottery": name, "nums": num_str, "time": ""})
            return out
        except Exception as e:
            logger.warning("_fetch_lecai: 解析失败返回空: %s", e)
            return []

    def _fetch_sina(self, name):
        """新浪彩票 - 双色球/大乐透"""
        api_url = f"https://view.lottery.sina.com.cn/interface/lottery/history.php?type={'ssq' if name == '双色球' else 'dlt'}&num=200"
        r = self._request_with_retry(api_url)
        if not r:
            return []
        out = []
        try:
            data = r.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            if not items:
                return []
            for item in items:
                period_raw = item.get("expect", "") or item.get("issue", "")
                if not period_raw:
                    continue
                try:
                    period_int = int(period_raw)
                except Exception as e:
                    logger.debug("_fetch_sina: 单条解析失败跳过: %s", e)
                    continue
                nums_str = item.get("opencode", "")
                if not nums_str:
                    continue
                result = PeriodNormalizer.normalize(period_int, name)
                if result is not None:
                    period_int = result
                out.append({"period": period_int, "lottery": name, "nums": nums_str, "time": item.get("opentime", "")})
            return out
        except Exception as e:
            logger.warning("_fetch_sina: 解析失败返回空: %s", e)
            return []

    def _fetch_cai8(self, name):
        """彩宝贝 - 双色球/大乐透"""
        url_map = {
            "双色球": "https://www.cai8.net/ssq/kj/",
            "大乐透": "https://www.cai8.net/dlt/kj/",
        }
        if name not in url_map:
            return []
        r = self._request_with_retry(url_map[name])
        if not r:
            return []
        out = []
        try:
            html = r.text
            # 匹配期号和号码行
            pattern = r'<tr[^>]*>\s*<td[^>]*>(\d{5,7})</td>\s*<td[^>]*class="[^"]*red[^"]*"[^>]*>(.*?)</td>'
            matches = re.findall(pattern, html, re.DOTALL)
            for period_raw, nums_html in matches:
                try:
                    period_int = int(period_raw)
                except Exception as e:
                    logger.debug("_fetch_cai8: 单条解析失败跳过: %s", e)
                    continue
                reds = re.findall(r'<span[^>]*>(\d+)</span>', nums_html)
                if not reds:
                    nums_text = re.sub(r'<[^>]+>', '', nums_html)
                    reds = re.findall(r'\d+', nums_text)
                if not reds:
                    continue
                rule = LOTTERY_RULES.get(name, {})
                red_count = rule.get("red", (1, 33, 6))[2] if len(rule.get("red", (1, 33, 6))) > 2 else 6
                blue_count = rule.get("blue", (1, 16, 1))[2] if len(rule.get("blue", (1, 16, 1))) > 2 else 1
                total = red_count + blue_count
                if len(reds) >= total:
                    nums_str = ",".join(reds[:red_count]) + "+" + ",".join(reds[red_count:red_count + blue_count])
                else:
                    nums_str = ",".join(reds)
                result = PeriodNormalizer.normalize(period_int, name)
                if result is not None:
                    period_int = result
                out.append({"period": period_int, "lottery": name, "nums": nums_str, "time": ""})
            return out
        except Exception as e:
            logger.warning("_fetch_cai8: 解析失败返回空: %s", e)
            return []

    def _fetch_sporttery(self, name):
        """体彩官方API - 大乐透/七星彩/排列三"""
        game_map = {
            "大乐透": "85",
            "七星彩": "04",
            "排列三": "35",
        }
        if name not in game_map:
            return []
        game_code = game_map[name]
        url = f"https://webapi.sporttery.cn/gateway/lottery/getDigitalDrawInfoV1.qry?param={game_code},0&isVerify=1"
        r = self._request_with_retry(url, timeout_override=10)
        if not r:
            print(f"🔍 [诊断体彩] {name}: 请求失败 - {self.last_error}")
            return []
        out = []
        try:
            data = r.json()
            err_code = data.get("errorCode", "")
            if err_code != "0":
                print(f"🔍 [诊断体彩] {name}: errorCode={err_code}, msg={data.get('errorMessage','')}")
                return []
            value = data.get("value", {})
            # 遍历possible keys
            key_map = {"大乐透": "dlt", "七星彩": "qxc", "排列三": "pls", "排列五": "plw"}
            found = None
            for key in [key_map.get(name, ""), "dlt", "qxc", "pls", "plw"]:
                draw_info = value.get(key, {})
                if draw_info and draw_info.get("lotteryDrawResult"):
                    found = key
                    period_raw = draw_info.get("lotteryDrawNum", "")
                    nums_raw = draw_info.get("lotteryDrawResult", "")
                    draw_time = draw_info.get("lotteryDrawTime", "")
                    if not period_raw or not nums_raw:
                        continue
                    try:
                        period_int = int(period_raw)
                    except Exception as e:
                        logger.debug("_fetch_sporttery: 单条解析失败跳过: %s", e)
                        continue
                    # 格式化号码：空格分隔 → 逗号分隔
                    nums_str = re.sub(r'\s+', ',', nums_raw.strip())
                    result = PeriodNormalizer.normalize(period_int, name)
                    if result is not None:
                        period_int = result
                    out.append({"period": period_int, "lottery": name, "nums": nums_str, "time": draw_time})
                    break
            if not found:
                print(f"🔍 [诊断体彩] {name}: value中未找到开奖数据, keys={list(value.keys())}")
            return out
        except Exception as e:
            print(f"🔍 [诊断体彩] {name}: 异常 - {e}")
            return []

    def _fetch_tcaibei_pl3(self):
        url = "https://www.lottery.gov.cn/kj/pl3.html"
        r = self._request_with_retry(url, timeout_override=10)
        if not r:
            return []
        out = []
        try:
            html = r.text
            pattern = r'期号：(\d{5})[\s\S]*?开奖号码：(\d)\s*(\d)\s*(\d)'
            matches = re.findall(pattern, html)
            for match in matches:
                period_raw = match[0]
                nums = f"{match[1]},{match[2]},{match[3]}"
                result = PeriodNormalizer.normalize(int(period_raw), "排列三")
                if result is not None:
                    period = result
                out.append({"period": period, "lottery": "排列三", "nums": nums, "time": ""})
            if not out:
                pattern2 = r'<tr[^>]*>\s*<td[^>]*>(\d{5})<\/td>\s*<td[^>]*>(\d)\s*(\d)\s*(\d)<\/td>'
                matches2 = re.findall(pattern2, html)
                for match in matches2:
                    period_raw = match[0]
                    nums = f"{match[1]},{match[2]},{match[3]}"
                    result = PeriodNormalizer.normalize(int(period_raw), "排列三")
                if result is not None:
                    period = result
                    out.append({"period": period, "lottery": "排列三", "nums": nums, "time": ""})
            return out
        except Exception as e:
            self.last_error = f"体彩网解析失败: {str(e)}"
            return []

    def _fetch_sina_pl3(self):
        url = "https://sports.sina.com.cn/l/pl3/"
        r = self._request_with_retry(url, timeout_override=10)
        if not r:
            return []
        out = []
        try:
            html = r.text
            pattern = r'<strong>(\d{5})期</strong>[\s\S]*?开奖号码:[\s]*(\d)[\s]*(\d)[\s]*(\d)'
            matches = re.findall(pattern, html)
            for match in matches:
                period_raw = match[0]
                nums = f"{match[1]},{match[2]},{match[3]}"
                result = PeriodNormalizer.normalize(int(period_raw), "排列三")
                if result is not None:
                    period = result
                out.append({"period": period, "lottery": "排列三", "nums": nums, "time": ""})
            return out
        except Exception as e:
            self.last_error = f"新浪彩票解析失败: {str(e)}"
            return []

    def _fetch_cai8_pl3(self):
        url = "https://www.cai8.net/pl3/kj/"
        r = self._request_with_retry(url, timeout_override=10)
        if not r:
            return []
        out = []
        try:
            html = r.text
            pattern = r'<td[^>]*class="c_red"[^>]*>(\d{5})<\/td>\s*<td[^>]*>(\d)\s*(\d)\s*(\d)<\/td>'
            matches = re.findall(pattern, html)
            for match in matches:
                period_raw = match[0]
                nums = f"{match[1]},{match[2]},{match[3]}"
                result = PeriodNormalizer.normalize(int(period_raw), "排列三")
                if result is not None:
                    period = result
                out.append({"period": period, "lottery": "排列三", "nums": nums, "time": ""})
            return out
        except Exception as e:
            self.last_error = f"彩宝贝解析失败: {str(e)}"
            return []

    def _fetch_cwl_pl3_api(self):
        url = "https://www.lottery.gov.cn/api/pl3/getHistoryList"
        params = {"pageNo": 1, "pageSize": 10}
        r = self._request_with_retry(url, params=params, headers={"Referer": "https://www.lottery.gov.cn/"})
        if not r:
            return []
        try:
            data = r.json()
            if data.get("code") == 200 and data.get("data"):
                items = data["data"].get("list", [])
                out = []
                for item in items:
                    period_raw = item.get("issue", "")
                    if not period_raw:
                        continue
                    num_str = item.get("number", "")
                    nums = ",".join(num_str.split())
                    period = int(period_raw)
                    result = PeriodNormalizer.normalize(period, "排列三")
                    if result is not None:
                        period = result
                    out.append({"period": period, "lottery": "排列三", "nums": nums, "time": item.get("drawDate", "")})
                return out
        except Exception as e:
            logger.warning("_fetch_cwl_pl3_api: 解析失败返回空: %s", e)
            pass
        return []

    def _fetch_huiniao_pl3(self):
        url = "http://api.huiniao.top/interface/home/lotteryHistory"
        params = {"type": "pls", "page": 1, "limit": 200}
        r = self._request_with_retry(url, params=params)
        if not r:
            return []
        try:
            data = r.json()
            if data.get("code") != 1 or not data.get("data"):
                return []
            items = data["data"].get("data", {}).get("list", [])
            if not items:
                return []
            out = []
            for item in items:
                code = item.get("code", "")
                if not code:
                    continue
                one = item.get("one", 0)
                two = item.get("two", 0)
                three = item.get("three", 0)
                nums = f"{int(one):02d},{int(two):02d},{int(three):02d}"
                period = int(code)
                result = PeriodNormalizer.normalize(period, "排列三")
                if result is not None:
                    period = result
                if period < 2020000:
                    continue
                out.append({"period": period, "lottery": "排列三", "nums": nums, "time": item.get("day", "")})
            return out
        except Exception as e:
            logger.warning("_fetch_huiniao_pl3: 解析失败返回空: %s", e)
            return []

    def _fetch_500chart_pl3(self):
        url = "http://datachart.500.com/pls/history/inc/history.php"
        params = {"limit": 200, "start": "26001", "end": "99999"}
        r = self._request_with_retry(url, params=params)
        if not r:
            return []
        try:
            html = r.text
            out = []
            rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
            for row in rows:
                tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                if len(tds) < 3:
                    continue
                period = None
                nums_found = []
                for idx, td in enumerate(tds):
                    td_clean = re.sub(r'<[^>]+>', '', td).strip()
                    if period is None and re.match(r'^\d{5,7}$', td_clean):
                        period = int(td_clean)
                    elif not nums_found and re.match(r'^(\d\s+){1,2}\d$', td_clean):
                        nums_found = td_clean.split()
                if period is None or len(nums_found) != 3:
                    continue
                nums = ",".join(f"{int(d):02d}" for d in nums_found)
                result = PeriodNormalizer.normalize(period, "排列三")
                if result is not None:
                    period = result
                if not is_valid_period("排列三", period):
                    continue
                out.append({"period": period, "lottery": "排列三", "nums": nums, "time": ""})
            return out
        except Exception as e:
            logger.warning("_fetch_500chart_pl3: 解析失败返回空: %s", e)
            return []

    def fetch(self, name):
        """抓取某彩种开奖数据：统一经 _fetch_from_sources 管道，按策略合并/择优。"""
        self.last_error = ""
        self.last_fetch_stale = False  # P2-1: 标记本次返回是否为陈旧缓存回退
        self._cleanup_invalid_periods(name)
        if name == "排列三":
            source_list = [
                ("灰鸟API", self._fetch_huiniao_pl3),
                ("500图表", self._fetch_500chart_pl3),
                ("500网", lambda: self._fetch_500(name)),
                ("乐彩网", lambda: self._fetch_lecai(name)),
                ("新浪彩票", self._fetch_sina_pl3),
                ("彩宝贝", self._fetch_cai8_pl3),
                # ── 以下为 DNS 风险 / 低优先级源（历史失败记录）──
                ("官方API(lottery.gov.cn)", self._fetch_cwl_pl3_api),
                ("体彩网(lottery.gov.cn)", self._fetch_tcaibei_pl3),
            ]
            ok, data = self._fetch_from_sources(name, source_list, "newer_than_local")
        else:
            sources = self._build_sources(name)
            strategy = "merge_all" if name in ["双色球", "大乐透", "七星彩"] else "first_success"
            ok, data = self._fetch_from_sources(name, sources, strategy)
        if ok is not None:
            return ok, data
        # 所有线上源都未取到有效数据 → 回退本地缓存（已含 404/熔断/空响应等全部失败态）
        local = Data.load(name)
        if local:
            self.last_error = "线上数据源全部失效，使用本地缓存数据"
            self.last_fetch_stale = True  # P2-1: 下游可判新鲜度
            return True, local
        # 不再伪造随机开奖数据（数据完整性要求，见 S2 修复）
        logger.error("彩票[%s] 所有线上源失效且无本地缓存，无法获取数据", name)
        self.last_error = f"所有线上源失效且无本地缓存({name})"
        return False, []

    def _build_sources(self, name):
        """构造各彩种的有名数据源列表 (src_name, src_func)，供 _fetch_from_sources 统一调度。"""
        if name == "快乐8":
            return [("CWL", lambda: self._fetch_cwl(name, "kl8")), ("500", lambda: self._fetch_500(name)), ("乐彩", lambda: self._fetch_lecai(name))]
        if name == "双色球":
            return [("CWL", lambda: self._fetch_cwl(name, "ssq")), ("新浪", lambda: self._fetch_sina(name)), ("彩宝贝", lambda: self._fetch_cai8(name)), ("500", lambda: self._fetch_500(name)), ("乐彩", lambda: self._fetch_lecai(name))]
        if name == "大乐透":
            return [("体彩官方", lambda: self._fetch_sporttery(name)), ("CWL", lambda: self._fetch_cwl(name, "dlt")), ("新浪", lambda: self._fetch_sina(name)), ("彩宝贝", lambda: self._fetch_cai8(name)), ("500", lambda: self._fetch_500(name)), ("乐彩", lambda: self._fetch_lecai(name))]
        if name in ["福彩3D", "七乐彩"]:
            eng = {"福彩3D": "3d", "七乐彩": "qlc"}
            return [("CWL", lambda: self._fetch_cwl(name, eng[name])), ("500", lambda: self._fetch_500(name)), ("乐彩", lambda: self._fetch_lecai(name))]
        if name == "七星彩":
            return [("体彩官方", lambda: self._fetch_sporttery(name)), ("500", lambda: self._fetch_500(name)), ("CWL", lambda: self._fetch_cwl(name, "qxc")), ("乐彩", lambda: self._fetch_lecai(name)), ("55128", lambda: self._fetch_55128(name))]
        return []

    def _fetch_from_sources(self, name, sources, strategy):
        """统一多源抓取管道（S5 抽取，消除三套重复循环）。

        sources: list of (src_name, src_func) 元组
        strategy:
          - 'merge_all'        : 遍历全部源，合并有效数据后一次性保存（双色球/大乐透/七星彩）
          - 'first_success'    : 返回首个成功取到数据的源（快乐8/福彩3D/七乐彩）
          - 'newer_than_local' : 返回首个比本地更新的源（排列三）
        返回 (ok, data)：ok 为 None 表示所有源都未取到有效数据（交由 fetch 回退缓存）。
        """
        if strategy == "merge_all":
            merged = []
            for src_name, src_func in sources:
                if not self._source_ok(src_name):
                    self.last_error = f"{src_name} 熔断中，跳过"
                    continue
                try:
                    data = src_func()
                except Exception as e:
                    self._source_fail(src_name)
                    self.last_error = f"{src_name}抓取异常: {str(e)}"
                    continue
                if not data:
                    self._source_fail(src_name)
                    continue
                self._source_success(src_name)
                merged.extend(data)
            if merged:
                self._save(name, merged)
                return True, merged
            return None, None

        if strategy == "first_success":
            for src_name, src_func in sources:
                if not self._source_ok(src_name):
                    self.last_error = f"{src_name} 熔断中，跳过"
                    continue
                try:
                    data = src_func()
                except Exception as e:
                    self._source_fail(src_name)
                    self.last_error = f"{src_name}抓取异常: {str(e)}"
                    continue
                if not data:
                    self._source_fail(src_name)
                    continue
                self._source_success(src_name)
                self._save(name, data)
                return True, data
            return None, None

        # newer_than_local（排列三）：返回首个比本地更新的源
        for src_name, src_func in sources:
            if not self._source_ok(src_name):
                self.last_error = f"{src_name} 熔断中，跳过"
                continue
            try:
                data = src_func()
            except Exception as e:
                self._source_fail(src_name)
                self.last_error = f"{src_name}抓取异常: {str(e)}"
                continue
            if not data:
                self._source_fail(src_name)
                continue
            self._source_success(src_name)
            data = [d for d in data if is_valid_period(name, d.get("period", 0))]
            if not data:
                continue
            latest_in_data = max([item["period"] for item in data]) if data else 0
            local_latest = Data.latest(name)
            local_invalid = local_latest > 0 and not is_valid_period(name, local_latest)
            if latest_in_data > local_latest or local_latest == 0 or local_invalid:
                self._save(name, data)
                Data.invalidate_cache(name)
                self.last_error = f"从{src_name}成功获取{name}数据，最新期号{latest_in_data}"
                return True, data
            self.last_error = f"{src_name}返回数据未更新，最新{latest_in_data}"
        return None, None


    def _cleanup_invalid_periods(self, name):
        path = os.path.join(DATA_SAVE, f"{name}.json")
        if not os.path.exists(path):
            return
        try:
            data = safe_load_json(path, default=[])
            original_len = len(data)
            data = [d for d in data if is_valid_period(name, d.get("period", 0))]
            if len(data) < original_len:
                with json_lock:
                    safe_write_json(path, data)
                Data.invalidate_cache(name)
        except Exception as e:
            logger.warning("_cleanup_invalid_periods: 解析失败返回空: %s", e)
            pass

    def _normalize_valid_nums(self, name, nums_str):
        """按彩种校验并标准化开奖号码，避免保存公告字段或不完整号码。"""
        raw = str(nums_str or "").strip()
        low = raw.lower()
        if not raw or raw == "+" or "none" in low or "null" in low:
            return None
        stripped = re.sub(r'<[^>]+>', '', raw)
        nums = [int(x) for x in re.findall(r'\d+', stripped)]
        if name in ["双色球", "大乐透"]:
            rule = LOTTERY_RULES.get(name, {})
            red_rule = rule.get("red", (1, 33, 6))
            blue_rule = rule.get("blue", (1, 16, 1))
            red_count = red_rule[2] if len(red_rule) > 2 else 6
            blue_count = blue_rule[2] if len(blue_rule) > 2 else 1
            total_needed = red_count + blue_count
            if len(nums) < total_needed and stripped.isdigit() and len(stripped) >= total_needed * 2:
                nums = [int(stripped[i:i + 2]) for i in range(0, len(stripped), 2)]
            if len(nums) < total_needed:
                return None
            reds = nums[:red_count]
            blues = nums[red_count:red_count + blue_count]
            if not all(red_rule[0] <= x <= red_rule[1] for x in reds):
                return None
            if not all(blue_rule[0] <= x <= blue_rule[1] for x in blues):
                return None
            return ",".join(f"{x:02d}" for x in reds) + "+" + ",".join(f"{x:02d}" for x in blues)
        if name in ["福彩3D", "排列三"]:
            if len(nums) < 3 or not all(0 <= x <= 9 for x in nums[:3]):
                return None
            return ",".join(f"{x:02d}" for x in nums[:3])
        if name == "七乐彩":
            if len(nums) < 7 or not all(1 <= x <= 30 for x in nums[:7]):
                return None
            return ",".join(f"{x:02d}" for x in nums[:7])
        if name == "七星彩":
            if len(nums) < 7 or not all(0 <= x <= 14 for x in nums[:7]):
                return None
            return ",".join(f"{x:02d}" for x in nums[:7])
        if name == "快乐8":
            if len(nums) < 20 or not all(1 <= x <= 80 for x in nums[:20]):
                return None
            return ",".join(f"{x:02d}" for x in nums[:20])
        return raw if re.search(r'\d', raw) else None

    def _save(self, name, new):
        path = os.path.join(DATA_SAVE, f"{name}.json")
        diag = {"name": name, "received": len(new), "no_num": 0, "none_null": 0, "no_digit": 0, "no_plus_comma": 0, "red_range": 0, "blue_range": 0, "bad_period": 0, "saved": 0}
        with json_lock:
            try:
                old = safe_load_json(path, default=[]) if os.path.exists(path) else []
                od = {}
                for item in old:
                    if not is_valid_period(name, item.get("period", 0)):
                        continue
                    normalized_old = self._normalize_valid_nums(name, item.get("nums", ""))
                    if not normalized_old:
                        continue
                    item["nums"] = normalized_old
                    od[item["period"]] = item
                for item in new:
                    if isinstance(item["period"], str):
                        try:
                            item["period"] = int(item["period"])
                        except Exception as e:
                            logger.debug("_save: 单条解析失败跳过: %s", e)
                            continue
                    # 拒绝空号码（防止公告栏显示空白）
                    nums_str = str(item.get("nums", "")).strip()
                    if not nums_str or nums_str == "+":
                        diag["no_num"] += 1
                        continue
                    if "none" in nums_str.lower() or "null" in nums_str.lower():
                        diag["none_null"] += 1
                        continue
                    normalized_nums = self._normalize_valid_nums(name, nums_str)
                    if not normalized_nums:
                        diag["no_digit"] += 1
                        continue
                    item["nums"] = normalized_nums
                    normalized = PeriodNormalizer.normalize(item["period"], name)
                    if normalized is not None:
                        item["period"] = normalized
                    if not is_valid_period(name, item["period"]):
                        diag["bad_period"] += 1
                        continue
                    if item["period"] in od:
                        existing = od[item["period"]]
                        existing_nums = str(existing.get("nums", "")).strip()
                        new_nums = str(item.get("nums", "")).strip()
                        existing_valid = False
                        new_valid = False
                        if name in ["双色球", "大乐透"]:
                            existing_valid = "+" in existing_nums and "," in existing_nums
                            new_valid = "+" in new_nums and "," in new_nums
                        else:
                            existing_valid = bool(existing_nums and re.search(r'\d', existing_nums))
                            new_valid = bool(new_nums and re.search(r'\d', new_nums))
                        if existing_valid and not new_valid:
                            diag["bad_period"] += 1
                            continue
                    od[item["period"]] = item
                od = {k: v for k, v in od.items() if is_valid_period(name, k)}
                merged = sorted(od.values(), key=lambda x: x["period"])
                diag["saved"] = len(merged)
                safe_write_json(path, merged)
            except Exception as e:
                print(f"保存{name}数据失败: {e}")
        if name in ["双色球", "大乐透"]:
            print(f"🔍 [诊断-_save] {name}: 收到={diag['received']} 空号码={diag['no_num']} NoneNull={diag['none_null']} 无数字={diag['no_digit']} 缺+,={diag['no_plus_comma']} 红球异常={diag['red_range']} 蓝球异常={diag['blue_range']} 期号异常={diag['bad_period']} 最终保存={diag['saved']}")
            if diag['no_plus_comma'] > 0:
                samples = diag.get('_bad_samples', [])
                print(f"🔍 [诊断-_save] {name} 缺+,样本: {samples[:5]}")
        elif name in ["福彩3D", "排列三", "七乐彩", "七星彩", "快乐8"]:
            print(f"🔍 [诊断-_save] {name}: 收到={diag['received']} 空号码={diag['no_num']} NoneNull={diag['none_null']} 期号异常={diag['bad_period']} 最终保存={diag['saved']}")
        Data.invalidate_cache(name)
