# -*- coding: utf-8 -*-
"""基金「外围风险」采集与评估 —— 基金经理变更 + 规模变化/清盘预警

补齐方向（JS-20260920-04）：项目原本只有净值类量化指标（回撤/波动/夏普/Calmar/
止盈/限购），缺少「谁在管、盘子有多大」这两类持仓外围风险。本模块补这两块。

数据源（全部为免费公开源，绝不接付费授权源）：
  1) 基金经理变动一览
     http://fundf10.eastmoney.com/jjjl_<code>.html
     页面内首个 <table class="w782 comm jloff"> 即「本基金历任基金经理」变动一览
     列：起始期 / 截止期 / 基金经理 / 任职期间 / 任职回报
  2) 规模变动（季度）
     https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=gmbd&code=<code>&page=1&per=20
     列：日期 / 期间申购(亿份) / 期间赎回(亿份) / 期末总份额(亿份) / 期末净资产(亿元) / 净资产变动率

合规与诚实度（项目铁律）：
  - 只抓公开页面、低速串行抓取（默认每个请求间隔 0.6s），标明来源；
  - 抓取失败一律返回 ok=False + reason，**不编造、不用模拟值冒充真实数据**；
  - 允许使用过期缓存兜底，但必须置 stale=True 并由调用方在展示层标注。

阈值出处：
  - 清盘线 5000 万元：公募基金合同常见条款为「连续 60 个工作日基金资产净值
    低于 5000 万元，基金管理人可终止基金合同」，故 0.5 亿元作为 danger 阈值。
  - 2 亿元以下俗称「迷你基金」，流动性/运作稳定性风险上升，作为 warn 阈值。
"""

import os
import re
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from utils.safe_json import safe_load_json, safe_write_json
except Exception:  # pragma: no cover - 独立运行兜底
    def safe_load_json(path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def safe_write_json(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SOURCE_TAG = "天天基金(fundf10.eastmoney.com)"

MANAGER_URL = "http://fundf10.eastmoney.com/jjjl_{code}.html"
SCALE_URL = ("https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
             "?type=gmbd&code={code}&page=1&per=20")

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 缓存 TTL：经理变动按天、规模按季度更新即可
MANAGER_TTL_HOURS = 24
SCALE_TTL_DAYS = 7

# 规模风险阈值（单位：亿元）
SCALE_DANGER_YI = 0.5     # 5000 万清盘线
SCALE_WARN_YI = 2.0       # 迷你基金线
SCALE_DROP_WARN_PCT = -30.0  # 单季净资产跌幅预警线


# ---------------------------------------------------------------------------
# HTML 解析（纯函数，便于单测）
# ---------------------------------------------------------------------------
def parse_table_rows(table_html: str) -> List[List[str]]:
    """把一段 <table>...</table> 解析成二维列表（去标签、strip）"""
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html or "", re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        if not cells:
            continue
        rows.append([re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells])
    return rows


def parse_manager_history(html: str) -> List[Dict[str, str]]:
    """解析『基金经理变动一览』表格

    Returns:
        [{"起始期":..., "截止期":..., "基金经理":..., "任职期间":..., "任职回报":...}, ...]
        按页面顺序（第一条为现任）。
    """
    if not html:
        return []
    blocks = re.findall(
        r"<table[^>]*class=['\"]w782 comm\s*jloff['\"].*?</table>", html, re.S)
    if not blocks:
        return []
    rows = parse_table_rows(blocks[0])
    if len(rows) < 2:
        return []
    header = rows[0]
    out = []
    for r in rows[1:]:
        item = {}
        for i, col in enumerate(header):
            item[col] = r[i] if i < len(r) else ""
        out.append(item)
    return out


def parse_scale_history(raw_text: str) -> List[Dict[str, str]]:
    """解析规模变动接口返回（var gmbd_apidata={ content:"<table ...>" , ...}）"""
    if not raw_text:
        return []
    key = 'content:"'
    i = raw_text.find(key)
    if i < 0:
        return []
    sub = raw_text[i + len(key):]
    j = sub.find("</table>")
    if j < 0:
        return []
    table_html = sub[:j + len("</table>")]
    rows = parse_table_rows(table_html)
    if len(rows) < 2:
        return []
    header = rows[0]
    out = []
    for r in rows[1:]:
        item = {}
        for i, col in enumerate(header):
            item[col] = r[i] if i < len(r) else ""
        out.append(item)
    return out


def _to_float(text: str) -> Optional[float]:
    """'39.38' / '-9.96%' / '122.23*' / '--' → float 或 None

    注意：天天基金季度表用 "*" 标记未确认/估算值（如 122.23*），
    这里保留数值本身（不丢弃），由上层用 estimated 标记提示用户。
    """
    if text is None:
        return None
    s = str(text).strip().replace("%", "").replace(",", "").replace("*", "").strip()
    if not s or s in ("--", "-", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    s = str(text).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# 评估（纯函数，不触网）
# ---------------------------------------------------------------------------
def eval_manager_change(history: List[Dict[str, str]],
                        config_manager: Optional[str] = None,
                        recent_days: int = 180,
                        today: Optional[datetime] = None) -> Dict:
    """评估基金经理变更风险

    Args:
        history: parse_manager_history 结果（第一条为现任）
        config_manager: 配置中记录的经理名（用于发现"配置已过时"）
        recent_days: 多少天内发生变更算「近期变更」
        today: 便于单测注入当前时间

    Returns:
        dict: ok / level('info'|'notice'|'warn') / changed_recently / latest_managers /
              latest_since / prev_managers / mismatch_config / message

        level 口径：
          warn   = 近期（默认180天内）确有经理变更 —— 真风险
          notice = 仅"配置里记录的经理名"与线上现任不符 —— 提示核对配置，非新发变更
          info   = 正常
    """
    today = today or datetime.now()
    result = {
        "ok": bool(history),
        "level": "info",
        "changed_recently": False,
        "latest_managers": "",
        "latest_since": "",
        "prev_managers": "",
        "mismatch_config": False,
        "message": "",
    }
    if not history:
        result["message"] = "暂缺：未取到基金经理数据"
        return result

    current = history[0]
    result["latest_managers"] = current.get("基金经理", "")
    result["latest_since"] = current.get("起始期", "")

    since = _parse_date(result["latest_since"])
    if since and (today - since).days <= recent_days:
        result["changed_recently"] = True
        result["level"] = "warn"
        prev = history[1].get("基金经理", "") if len(history) > 1 else ""
        result["prev_managers"] = prev
        result["message"] = ("基金经理于 %s 发生变更：%s → %s（任职回报 %s）" % (
            result["latest_since"], prev or "未知", result["latest_managers"],
            current.get("任职回报", "--")))
    else:
        result["message"] = "现任经理 %s（自 %s 起，任职回报 %s）" % (
            result["latest_managers"], result["latest_since"] or "--",
            current.get("任职回报", "--"))

    if config_manager and config_manager not in (result["latest_managers"] or ""):
        result["mismatch_config"] = True
        if result["level"] != "warn":
            result["level"] = "notice"
        result["message"] += ("；配置中记录的经理「%s」与线上现任不符，建议核对配置"
                              "（大概率早已变更，非本轮新发）" % config_manager)

    return result


def eval_scale_risk(history: List[Dict[str, str]],
                    danger_yi: float = SCALE_DANGER_YI,
                    warn_yi: float = SCALE_WARN_YI,
                    drop_warn_pct: float = SCALE_DROP_WARN_PCT) -> Dict:
    """评估规模变化与清盘风险

    Args:
        history: parse_scale_history 结果（第一条为最新一期，季度数据）

    Returns:
        dict: ok / level('safe'|'warn'|'danger') / latest_date / net_asset(亿元) /
              change_pct / consecutive_down / message
    """
    result = {
        "ok": bool(history),
        "level": "safe",
        "latest_date": "",
        "net_asset": None,
        "change_pct": None,
        "consecutive_down": 0,
        "estimated": False,
        "message": "",
    }
    if not history:
        result["message"] = "暂缺：未取到规模数据"
        return result

    def _col(item, keyword):
        for k, v in item.items():
            if keyword in k:
                return v
        return ""

    latest = history[0]
    result["latest_date"] = _col(latest, "日期") or latest.get("日期", "")
    raw_asset = _col(latest, "净资产")
    result["estimated"] = "*" in str(raw_asset)
    net_asset = _to_float(raw_asset)
    result["net_asset"] = net_asset
    result["change_pct"] = _to_float(_col(latest, "变动率"))

    # 连续下滑季度数
    down = 0
    for item in history:
        pct = _to_float(_col(item, "变动率"))
        if pct is not None and pct < 0:
            down += 1
        else:
            break
    result["consecutive_down"] = down

    if net_asset is None:
        result["message"] = "暂缺：最新净资产缺失"
        return result

    if net_asset < danger_yi:
        result["level"] = "danger"
        result["message"] = ("最新净资产 %.2f 亿元（%s），低于 5000 万清盘线，"
                             "触发清盘风险条款（连续60个工作日低于5000万可终止合同）"
                             % (net_asset, result["latest_date"]))
    elif net_asset < warn_yi:
        result["level"] = "warn"
        result["message"] = ("最新净资产 %.2f 亿元（%s），属迷你基金（<2亿），"
                             "需关注流动性与运作稳定性" % (net_asset, result["latest_date"]))
    else:
        result["message"] = "最新净资产 %.2f 亿元（%s），规模正常" % (
            net_asset, result["latest_date"])

    if result["estimated"]:
        result["message"] += "（该期数值带 * 号，为未确认/估算值）"

    pct = result["change_pct"]
    if pct is not None and pct <= drop_warn_pct:
        result["level"] = "danger" if result["level"] == "danger" else "warn"
        result["message"] += "；最近一期环比 %.2f%%，赎回压力较大" % pct
    elif result["consecutive_down"] >= 2:
        if result["level"] == "safe":
            result["level"] = "warn"
        result["message"] += "；已连续 %d 个季度规模下滑" % result["consecutive_down"]

    return result


# ---------------------------------------------------------------------------
# 抓取（带缓存 + 降级）
# ---------------------------------------------------------------------------
class FundProfileFetcher:
    """基金外围风险数据抓取器（经理变更 / 规模变动）

    - 串行低速抓取，失败不抛异常，返回 ok=False + reason
    - 缓存优先；网络失败时允许用过期缓存兜底并标记 stale
    """

    def __init__(self, cache_dir: Optional[str] = None, timeout: int = 15,
                 delay: float = 0.6, retries: int = 2, enabled: bool = True):
        self.cache_dir = cache_dir or os.path.join(
            _SCRIPT_DIR, "金水谣数据", "fund", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.enabled = enabled
        self._session = None
        self._last_request_at = 0.0

    # ---------------- 内部 ----------------
    def _http_get(self, url: str, referer: str = "") -> Optional[str]:
        if not self.enabled:
            return None
        try:
            import requests
        except ImportError:
            logger.warning("requests 不可用，基金外围风险数据无法抓取")
            self.enabled = False
            return None

        headers = {"User-Agent": DEFAULT_UA}
        if referer:
            headers["Referer"] = referer

        for attempt in range(1, self.retries + 1):
            # 低速：两次请求之间至少间隔 delay 秒
            wait = self.delay - (time.time() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                self._last_request_at = time.time()
                if resp.status_code == 200:
                    resp.encoding = "utf-8"
                    return resp.text
                logger.debug("抓取 %s 返回 %s", url, resp.status_code)
            except Exception as e:
                self._last_request_at = time.time()
                logger.debug("抓取 %s 失败(%d): %s", url, attempt, e)
        return None

    def _cache_path(self, kind: str, code: str) -> str:
        return os.path.join(self.cache_dir, "profile_%s_%s.json" % (kind, code))

    def _read_cache(self, kind: str, code: str, ttl_seconds: float):
        path = self._cache_path(kind, code)
        if not os.path.isfile(path):
            return None, False
        payload = safe_load_json(path, default=None)
        if not isinstance(payload, dict):
            return None, False
        fetched = payload.get("fetched_at", "")
        try:
            age = (datetime.now() - datetime.strptime(fetched, "%Y-%m-%d %H:%M:%S")).total_seconds()
        except Exception:
            age = ttl_seconds + 1
        return payload, age > ttl_seconds

    def _write_cache(self, kind: str, code: str, rows: List[Dict], ok: bool, reason: str = ""):
        safe_write_json(self._cache_path(kind, code), {
            "code": code,
            "kind": kind,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": SOURCE_TAG,
            "ok": ok,
            "reason": reason,
            "rows": rows,
        })

    # ---------------- 公开方法 ----------------
    def fetch_manager_history(self, code: str, use_cache: bool = True) -> Dict:
        """返回 {'ok','rows','source','fetched_at','stale','reason'}"""
        code = str(code).strip()
        if use_cache:
            payload, expired = self._read_cache(
                "manager", code, MANAGER_TTL_HOURS * 3600)
            if payload and not expired:
                payload["stale"] = False
                return payload
        html = self._http_get(MANAGER_URL.format(code=code),
                              referer=MANAGER_URL.format(code=code))
        rows = parse_manager_history(html) if html else []
        if rows:
            self._write_cache("manager", code, rows, True)
            return {"ok": True, "rows": rows, "source": SOURCE_TAG,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "stale": False, "reason": ""}
        reason = "网络抓取失败或页面结构变化"
        cached, _ = self._read_cache("manager", code, MANAGER_TTL_HOURS * 3600)
        if cached and cached.get("rows"):
            cached["stale"] = True
            cached["reason"] = reason + "（使用过期缓存）"
            return cached
        return {"ok": False, "rows": [], "source": SOURCE_TAG, "fetched_at": "",
                "stale": False, "reason": reason}

    def fetch_scale_history(self, code: str, use_cache: bool = True) -> Dict:
        code = str(code).strip()
        if use_cache:
            payload, expired = self._read_cache(
                "scale", code, SCALE_TTL_DAYS * 86400)
            if payload and not expired:
                payload["stale"] = False
                return payload
        raw = self._http_get(SCALE_URL.format(code=code),
                             referer="http://fundf10.eastmoney.com/gmbd_%s.html" % code)
        rows = parse_scale_history(raw) if raw else []
        if rows:
            self._write_cache("scale", code, rows, True)
            return {"ok": True, "rows": rows, "source": SOURCE_TAG,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "stale": False, "reason": ""}
        reason = "网络抓取失败或接口结构变化"
        cached, _ = self._read_cache("scale", code, SCALE_TTL_DAYS * 86400)
        if cached and cached.get("rows"):
            cached["stale"] = True
            cached["reason"] = reason + "（使用过期缓存）"
            return cached
        return {"ok": False, "rows": [], "source": SOURCE_TAG, "fetched_at": "",
                "stale": False, "reason": reason}

    def get_profile(self, code: str, config_manager: Optional[str] = None,
                    use_cache: bool = True) -> Dict:
        """一次取回该基金的外围风险档案（含评估结果）"""
        mgr = self.fetch_manager_history(code, use_cache=use_cache)
        scale = self.fetch_scale_history(code, use_cache=use_cache)
        return {
            "code": code,
            "source": SOURCE_TAG,
            "manager_raw": mgr,
            "scale_raw": scale,
            "manager": eval_manager_change(mgr.get("rows") or [], config_manager),
            "scale": eval_scale_risk(scale.get("rows") or []),
            "stale": bool(mgr.get("stale") or scale.get("stale")),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def build_profiles(funds: List[Dict], delay: float = 0.6) -> Dict[str, Dict]:
    """按基金配置列表批量取外围风险档案

    Args:
        funds: [{'code':..., 'manager':...}, ...]
    Returns:
        {code: profile}
    """
    fetcher = FundProfileFetcher(delay=delay)
    out = {}
    for fund in funds or []:
        code = str(fund.get("code", "")).strip()
        if not code:
            continue
        try:
            out[code] = fetcher.get_profile(code, fund.get("manager"))
        except Exception as e:  # 单只失败不影响整体
            logger.warning("基金 %s 外围风险采集失败: %s", code, e)
            out[code] = {
                "code": code,
                "source": SOURCE_TAG,
                "manager_raw": {"ok": False, "rows": [], "reason": str(e)},
                "scale_raw": {"ok": False, "rows": [], "reason": str(e)},
                "manager": eval_manager_change([]),
                "scale": eval_scale_risk([]),
                "stale": False,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
    return out


if __name__ == "__main__":  # pragma: no cover - 手动自检入口
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s: %(message)s")
    codes = sys.argv[1:] or ["000001"]
    for c in codes:
        p = FundProfileFetcher().get_profile(c)
        print("-" * 60)
        print("基金", c)
        print("  经理:", p["manager"]["message"], "| level=", p["manager"]["level"])
        print("  规模:", p["scale"]["message"], "| level=", p["scale"]["level"])
        print("  来源:", p["source"], "| 过期缓存:", p["stale"])
