# -*- coding: utf-8 -*-
"""彩票市场休市日历 —— 分清「休市没开奖」和「数据源故障」。

为什么要这个模块（JS-20261002-21）
----------------------------------
国庆/春节等法定休市期间，彩票**停止销售与开奖**。此时：
  - 系统照常生成下一期的预测；
  - 这些期**还没开奖** ⇒ 自动复盘查不到开奖号 ⇒ 只能跳过；
  - 但日志只写「未开奖跳过」，用户看到「昨天怎么没复盘」，
    很容易（连我自己也曾经）误判成「抓取挂了 / 数据源断了」。

这次事故让我警醒：**把休市误报成故障，和把故障误报成休市，同样有害**。
前者让人白修一圈，后者让人错过真实的线路中断。本模块把两者分开。

诚实边界
--------
休市区间一律取自**本地配置文件** `config/lottery_market_calendar.json`，
**禁止自动抓官方站点**（官方改版会静默抓错，与「彩票规则更新」同一铁律）。
配置带 `updated_at` + `expires_after_days`，过期只告警提示人工核对，
程序绝不自行推算或修改日期。对**未核实**的条目保留 `verified=false`，
对外文案会明确标注「以官方公告为准」。

兜底启发式
----------
万一漏配某个节假日：某彩种距上次开奖已超过「正常开奖间隔 × 系数」，
判定为**疑似休市或数据源异常**（两种可能都给出，不下独断），
提醒人工确认，而不是假装正常。

References:
    JS-20261002-21（本次事故驱动：昨天的预测为什么没复盘）
"""
import io
import json
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALENDAR_PATH = os.path.join(BASE_DIR, "config", "lottery_market_calendar.json")

# ── 模块级常量（阈值五件套：判断+文案+docstring+标准真源+闸门）──
# 距上次开奖超过「正常间隔 × 该系数」→ 疑似休市或数据源异常
STALE_MULTIPLE_FALLBACK = 2.5
# 兜底：未配置该彩种时按「每天开奖」处理（保守，宁可漏报不误报）
DEFAULT_INTERVAL_DAYS = 1


def _parse(d):
    if isinstance(d, date):
        return d
    if isinstance(d, datetime):
        return d.date()
    s = str(d or "").strip()
    if not s:
        return None
    s = s.replace("/", "-")[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def load_calendar(path=None):
    """读取休市日历配置。文件缺失/损坏 → 返回空日历（降级不停服）。"""
    path = path or CALENDAR_PATH
    empty = {"holidays": [], "heuristic": {}, "policy": {}, "updated_at": None}
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("[休市日历] 读取失败(降级为空日历): %s", e)
        return empty
    if not isinstance(data, dict):
        return empty
    data.setdefault("holidays", [])
    data.setdefault("heuristic", {})
    return data


def current_holiday(on_date=None, calendar=None):
    """返回覆盖该日期的休市条目；不在休市期则返回 None。"""
    cal = calendar if calendar is not None else load_calendar()
    d = _parse(on_date) or date.today()
    for h in cal.get("holidays", []) or []:
        start = _parse(h.get("start"))
        end = _parse(h.get("end"))
        if not start or not end:
            continue
        lots = h.get("lots", "*")
        if start <= d <= end:
            return h
        # lots 字段保留给将来「只休部分彩种」的场景，当前一律为 "*"
        del lots
    return None


def is_market_closed(lot=None, on_date=None, calendar=None):
    """该彩种当天是否处于休市期。"""
    h = current_holiday(on_date=on_date, calendar=calendar)
    if h is None:
        return False
    return _covers_lot(h, lot)


def _covers_lot(holiday, lot):
    lots = holiday.get("lots", "*")
    if lots in ("*", "", None):
        return True
    if isinstance(lots, list):
        return lot in lots
    return True


def days_since(date_str, today=None):
    """给定 YYYY-MM-DD，返回距今天数；无法解析返回 None。"""
    d = _parse(date_str)
    if d is None:
        return None
    t = today or date.today()
    return (t - d).days


def normal_interval_days(lot, calendar=None):
    """该彩种正常多久开一次奖（来自配置，非估算）。"""
    cal = calendar if calendar is not None else load_calendar()
    table = (cal.get("heuristic") or {}).get("normal_interval_days", {}) or {}
    for k, v in table.items():
        if k.startswith("_"):
            continue
        if k == lot:
            return float(v)
    return float(DEFAULT_INTERVAL_DAYS)


def classify(lot, last_draw_time, calendar=None, today=None):
    """判断某彩种当前状态。

    Returns:
        dict: {
            "status": "normal" | "holiday" | "suspect_stale",
            "message": str,        # 可直接给用户看的文案
            "holiday_name": str|None,
            "resume_date": str|None,
            "verified": bool|None,  # 该休市条目是否已核实
            "days_since": int|None,
        }
    """
    cal = calendar if calendar is not None else load_calendar()
    t = today or date.today()

    holiday = current_holiday(on_date=t, calendar=cal)
    stall = days_since(last_draw_time, t)
    interval = normal_interval_days(lot, cal)
    multiple = float((cal.get("heuristic") or {}).get(
        "stale_multiple", STALE_MULTIPLE_FALLBACK) or STALE_MULTIPLE_FALLBACK)

    if holiday is not None and _covers_lot(holiday, lot):
        name = holiday.get("name", "休市")
        resume = holiday.get("resume_date")
        verified = bool(holiday.get("verified"))
        msg = "%s%s期间：停止销售与开奖" % (name, ("" if verified else "（区间未核实）"))
        if resume:
            msg += "，预计 %s 恢复" % resume
        if not verified:
            msg += "（日期以中彩中心官方公告为准）"
        return {
            "status": "holiday",
            "message": msg,
            "holiday_name": name,
            "resume_date": resume,
            "verified": verified,
            "days_since": stall,
        }

    threshold = interval * multiple
    if stall is not None and stall > threshold:
        return {
            "status": "suspect_stale",
            "message": ("距上次开奖已 %d 天，超过常规间隔（%.1f 天）。"
                        "可能是休市（日历未收录），也可能是数据没抓到，请人工确认。"
                        % (stall, interval)),
            "holiday_name": None,
            "resume_date": None,
            "verified": None,
            "days_since": stall,
        }

    return {
        "status": "normal",
        "message": "正常开奖周期",
        "holiday_name": None,
        "resume_date": None,
        "verified": None,
        "days_since": stall,
    }


def calendar_freshness(calendar=None, today=None):
    """日历是否需要人工核对（过期提醒，不自动改任何数字）。

    Returns:
        dict: {"ok": bool, "age_days": int|None, "expired": bool, "message": str}
    """
    cal = calendar if calendar is not None else load_calendar()
    t = today or date.today()
    age = days_since(cal.get("updated_at"), t)
    limit = cal.get("expires_after_days")
    expired = False
    if age is not None and limit:
        expired = age > int(limit)
    msg = "休市日历"
    if age is None:
        msg += "缺 updated_at，请补"
    elif expired:
        msg += ("已 %d 天未核对（阈值 %s 天），请对照官方公告更新 "
                "config/lottery_market_calendar.json" % (age, limit))
    else:
        msg += "在有效期内（%d 天 / 阈值 %s 天）" % (age, limit)
    return {"ok": not expired, "age_days": age, "expired": expired, "message": msg}
