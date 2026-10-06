# -*- coding: utf-8 -*-
"""官方中奖规则判定（单一真源）—— JS-20260924-34

背景：系统此前的「命中」只是**号码重合了几个**（`utils.number_utils.count_match`），
与官方中奖规则**双向错位**（实测取证 2026-09-24）：

| 情形（双色球）        | 系统判定 | 官方结果        |
|-----------------------|----------|-----------------|
| 中 1 红球、没中蓝球   | 命中     | **无奖**        |
| 中 2 红球、没中蓝球   | 命中     | **无奖**        |
| 0 红球、只中蓝球      | 未中     | **六等奖 5 元** |

用户选择「并存」方案：保留现有 `hits`（号码重合数，用于学习与既有统计），
**另外**按官方奖级判定并落 `prize_tier` 字段，两边都展示、互不顶替。

规则真源：`config/lottery_prize_rules.json`
  - 人工核对录入，**非自动抓取**（自动抓官方站点一旦页面改版就会静默抓错规则，
    比不更新更危险；且项目有商业化意向，接数据源前须过授权评估）。
  - 带 `updated_at` 与 `stale_days`：超过 **180 天**未核对 → 门禁告警提醒人工复核。
    本模块**只提醒，绝不自动改数字**（诚实铁律：取不到写「暂缺」，不编造）。

用法：
    from utils.lottery_prize import judge_prize
    r = judge_prize("双色球", "01,02,03,04,05,06+07", "01,11,12,13,14,15+16")
    # -> {"tier": None, "is_win": False, "status": "lose", "prize": None}

status 取值：
  - "win"             中奖，tier 为奖级名
  - "lose"            有规则、判定为未中奖
  - "no_rule"         该彩种没有规则 / 规则文件读不到（**不作任何猜测**）
  - "not_applicable"  玩法不适用官方奖级（如 3D 组六复式、快乐8 复式非 10 码）
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime

# 规则文件：官方奖级的唯一真源（前端奖金计算器与后端复盘共用同一份）
RULES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "lottery_prize_rules.json")

# 规则新鲜度告警阈值（天）：规则文件自身也带 stale_days，读不到时用此兜底。
# 依据：彩票玩法规则变更属低频事件（近年主要为快乐8 玩法调整），
# 半年复核一次足以覆盖，且不至于让告警变成天天响的噪音。
PRIZE_RULES_STALE_DAYS = 180

_RULES_CACHE = {"mtime": None, "data": None}

STATUS_WIN = "win"
STATUS_LOSE = "lose"
STATUS_NO_RULE = "no_rule"
STATUS_NOT_APPLICABLE = "not_applicable"

# 胆拖解析（JS-20261006-03）：judge_prize / count_match 都按逗号切分号码串，
# 解析不了胆拖写法，需先走本模块。非胆拖输入返回 None → 回退原逻辑。
try:
    from utils.dantuo import is_dantuo, parse_dantuo, best_hits
except Exception:  # pragma: no cover —— 解析模块缺失时降级为「无胆拖支持」
    def is_dantuo(_s):
        return False
    def parse_dantuo(_s):
        return None
    def best_hits(*_a, **_k):
        return (0, 0)


def load_rules(force: bool = False):
    """读取官方奖级规则（按 mtime 缓存，改文件即生效，无需重启）

    Returns:
        dict|None: 规则字典；文件缺失或解析失败返回 None（调用方须按「暂缺」处理）
    """
    try:
        mt = os.path.getmtime(RULES_FILE)
    except OSError:
        _RULES_CACHE["mtime"] = None
        _RULES_CACHE["data"] = None
        return None
    if not force and _RULES_CACHE["data"] is not None and _RULES_CACHE["mtime"] == mt:
        return _RULES_CACHE["data"]
    try:
        with io.open(RULES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    _RULES_CACHE["mtime"] = mt
    _RULES_CACHE["data"] = data
    return data


def rules_staleness(rules=None):
    """规则新鲜度：用于门禁告警「规则已 X 天未核对」

    Returns:
        dict: {"updated_at": str|None, "days": int|None, "stale_days": int,
               "is_stale": bool, "missing": bool}
    """
    rules = rules if rules is not None else load_rules()
    stale_days = PRIZE_RULES_STALE_DAYS
    if isinstance(rules, dict):
        try:
            stale_days = int(rules.get("stale_days") or PRIZE_RULES_STALE_DAYS)
        except (TypeError, ValueError):
            pass
    if not isinstance(rules, dict):
        return {"updated_at": None, "days": None, "stale_days": stale_days,
                "is_stale": True, "missing": True}
    updated_at = rules.get("updated_at")
    days = None
    if updated_at:
        try:
            d = datetime.strptime(str(updated_at)[:10], "%Y-%m-%d")
            days = (datetime.now() - d).days
        except ValueError:
            days = None
    # 读不出日期时按「已过期」处理 —— 不能因为缺字段就假装新鲜（静默失败才是敌人）
    is_stale = True if days is None else days >= stale_days
    return {"updated_at": updated_at, "days": days, "stale_days": stale_days,
            "is_stale": is_stale, "missing": False}


def _split(s):
    return [p.strip() for p in str(s or "").split(",") if p.strip()]


def _digits3(s):
    """把 3D/排三 的号码串归一化成 3 位；不是 3 位玩法返回 None"""
    parts = _split(s)
    if len(parts) == 3:
        return parts
    if len(parts) == 1 and len(parts[0]) == 3 and parts[0].isdigit():
        return list(parts[0])
    return None


def _longest_run(seq):
    best = cur = 0
    for v in seq:
        if v:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def judge_prize(lot, pred_str, actual_str, rules=None):
    """按官方规则判定中奖

    Args:
        lot: 彩种名
        pred_str: 预测号码串，如 "01,02,03,04,05,06+07"
        actual_str: 开奖号码串，如 "02,05,16,19,26,32+14"
        rules: 规则字典（默认自动加载，便于测试注入）

    Returns:
        dict: {"tier": str|None, "is_win": bool, "status": str, "prize": ...}
    """
    def _ret(tier, status, prize=None):
        return {"tier": tier, "is_win": status == STATUS_WIN,
                "status": status, "prize": prize}

    rules = rules if rules is not None else load_rules()
    if not isinstance(rules, dict):
        return _ret(None, STATUS_NO_RULE)
    spec = (rules.get("rules") or {}).get(lot or "")
    if not spec:
        return _ret(None, STATUS_NO_RULE)

    mode = spec.get("judge")
    try:
        if mode == "red_blue":
            # 胆拖：[前区胆:23,27 拖:..] [后区胆:12 拖:..] —— 不能用逗号切分，
            # 否则切出 "[前区胆:23" 这类片段（JS-20261006-03）。
            # 判据放宽到「含『胆』字」：解析不出就判不适用，绝不回退成普通单注
            # 以免「算不出来」伪装成「确实没中」。
            af = str(actual_str or "").split("+")
            if is_dantuo(pred_str):
                st = parse_dantuo(pred_str)
                if st is None:
                    return _ret(None, STATUS_NOT_APPLICABLE)
                from utils.number_utils import parse_reds
                pick = spec.get("pick") or {}
                k = int(pick.get("front") or 5)
                kb = int(pick.get("back") or 0)
                afs = set(parse_reds(af[0] if af else ""))
                abs_ = set(parse_reds(af[1])) if len(af) > 1 else set()
                front, back = best_hits(st, afs, abs_, k, kb)
            else:
                pf = str(pred_str or "").split("+")
                front = len(set(_split(pf[0])) & set(_split(af[0])))
                back = len(set(_split(pf[1])) & set(_split(af[1]))) if len(pf) > 1 and len(af) > 1 else 0
            for t in spec.get("tiers", []):
                for cond in t.get("match", []):
                    if len(cond) < 2:
                        continue
                    if front >= cond[0] and back >= cond[1]:
                        return _ret(t.get("tier"), STATUS_WIN, t.get("prize"))
            return _ret(None, STATUS_LOSE)

        if mode == "three_digit":
            p, a = _digits3(pred_str), _digits3(actual_str)
            if not p or not a:
                return _ret(None, STATUS_NOT_APPLICABLE)
            if p == a:
                return _ret("直选", STATUS_WIN, _prize_of(spec, "直选"))
            from collections import Counter
            if Counter(p) == Counter(a):
                # 组三/组六由**开奖号形态**决定（官方口径），不是由投注方式决定
                name = "组三" if len(set(a)) == 2 else "组六"
                return _ret(name, STATUS_WIN, _prize_of(spec, name))
            return _ret(None, STATUS_LOSE)

        if mode == "positional_consecutive":
            p, a = _split(pred_str), _split(actual_str)
            if len(p) != len(a) or not p:
                return _ret(None, STATUS_NOT_APPLICABLE)
            run = _longest_run([x == y for x, y in zip(p, a)])
            for t in spec.get("tiers", []):
                if run >= int(t.get("n", 0)):
                    return _ret(t.get("tier"), STATUS_WIN, t.get("prize"))
            return _ret(None, STATUS_LOSE)

        if mode == "keno10":
            p, a = _split(pred_str), _split(actual_str)
            # 官方奖级表是「选十」玩法；非 10 码（复式）套不上，返回暂缺不猜
            if len(p) != int(spec.get("pick", 10)):
                return _ret(None, STATUS_NOT_APPLICABLE)
            hit = len(set(p) & set(a))
            for t in spec.get("tiers", []):
                n = int(t.get("n", 0))
                ok = (hit == n) if t.get("exact") else (hit >= n)
                if ok:
                    return _ret(t.get("tier"), STATUS_WIN, t.get("prize"))
            return _ret(None, STATUS_LOSE)
    except Exception:
        return _ret(None, STATUS_NO_RULE)

    return _ret(None, STATUS_NO_RULE)


def _prize_of(spec, tier_name):
    for t in spec.get("tiers", []):
        if t.get("tier") == tier_name:
            return t.get("prize")
    return None
