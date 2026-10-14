# -*- coding: utf-8 -*-
"""当日购票数据（诚实记账层）——**唯一写入端点（SSOT）**。

背景
----
- JS-20261012-13 决策：现有链路只统计「命中率」，回答不了「实际亏了多少」；
  命中率 ≠ 盈利能力（官方返奖率锚点见下）。
- JS-20261012-20 落地：本模块 + `tools/purchase_log.py` CLI。

官方返奖率锚点
--------------
依据财政部公告 2026 年第 24 号（各玩法奖金池/公益金/发行费比例）：

| 彩种 | 奖金池 | 公益金 | 发行费 |
|---|---|---|---|
| 双色球 / 大乐透 | 51% | 36% | 13% |
| 福彩3D / 排列三 | 53% | 34% | 13% |
| 快乐8（基诺型） | 58% | 30% | 12% |
| 七星彩 / 七乐彩 | 50% | 37% | 13% |

⇒ 长期每投 100 元最多拿回 50~58 元，净亏 42~50 元。
（财政部公开的是宏观月度聚合销量，无个人级或逐日数据 ⇒ 只能用户自录。）

设计原则
--------
1. **只记账，不预测**：本模块数据**禁止**进入选号/权重/杀号等任何预测环节。
2. **缺数据 ≠ 没发生**：`purchased=false` 必须显式落库，否则「无记录」与
   「买了但没登记」无法区分（与 JS-20261012-12 大乐透断档同类的坑）。
3. **最小必要（PIPL 第 6 条） / 最短保存（第 19 条）/ 可删除（第 47 条）**：
   红线字段一律拒收并留痕，不静默丢弃。
4. **派生不录入**：`net = payout - purchase_amount` 只在读取时计算，不落库。

存储
----
`金水谣数据/purchase_log.json`（运行时数据，**不入仓**，已加入 .gitignore）。
"""

import logging
import os
import threading
import time

from config import BASE_DIR

logger = logging.getLogger(__name__)

PURCHASE_LOG_PATH = os.path.join(BASE_DIR, "purchase_log.json")

# 允许录入的字段（最小必要）
PURCHASE_FIELDS = (
    "purchased",         # bool：当日是否实际购票
    "purchase_amount",   # float（元）：实际投入
    "purchase_count",    # int：购买注数
    "payout",            # float（元）：实际兑奖所得（未中奖记 0）
    "purchase_note",     # str（可选）：备注
)

# 派生字段（禁止录入，应计算得出，避免双写不同步）
_DERIVED_FIELDS = ("net", "net_profit", "盈亏", "净盈亏")

# 红线字段（一律拒收）：可兑价 / 行踪轨迹 / 金融账户 / 超最小必要
PURCHASE_BANNED_FIELDS = (
    "ticket_no", "ticket_id", "serial_no", "票号", "序列号",
    "ticket_photo", "ticket_image", "票面照片",
    "shop", "store", "shop_name", "网点", "销售网点",
    "location", "geo", "gps", "address", "地理位置", "经纬度",
    "account", "bank_card", "card_no", "payment", "支付账户", "银行卡",
    "id_card", "phone", "mobile", "身份证", "手机号",
)


def _ensure_dir():
    try:
        os.makedirs(os.path.dirname(PURCHASE_LOG_PATH), exist_ok=True)
    except Exception as e:  # pragma: no cover
        logger.warning("purchase_log 目录创建失败: %s", e)


def load_log():
    """读取购票流水。返回 list；文件缺失/损坏返回 []（异常只 warning 留痕，不静默吞）。"""
    try:
        from utils.safe_json import safe_load_json
        data = safe_load_json(PURCHASE_LOG_PATH, default=[])
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("purchase_log 读取失败: %s", e)
        return []


def _save_log(entries):
    """原子落盘（tmp + os.replace），带锁。"""
    from utils.safe_json import safe_write_json
    from utils.locks import purchase_lock
    _ensure_dir()
    with purchase_lock:
        safe_write_json(PURCHASE_LOG_PATH, entries)


def sanitize_entry(entry):
    """字段白名单 + 红线字段拒收。

    - 只保留 lot / period / date + PURCHASE_FIELDS；
    - 命中红线字段 ⇒ **剔除并 warning 留痕**（绝不静默丢弃，也绝不落库）；
    - purchased 缺失 ⇒ False；payout 缺失 ⇒ 0.0（未中奖记 0，不得留空）；
    - net 为派生值，**若传入会被剔除**。

    返回 (清洗后的 dict, 被剔除的字段名列表)。

    ⚠️ 备注 `purchase_note` 是自由文本，本模块**不做内容扫描**（避免误报）。
    录入端应禁止在备注里写票号／手机号／网点等红线信息——一旦写入即等同落库。
    """
    out = {}
    dropped = []

    lot = entry.get("lot")
    period = entry.get("period")
    if not lot or period in (None, ""):
        raise ValueError("购票记录必须包含 lot 与 period")

    out["lot"] = str(lot)
    out["period"] = period
    if entry.get("date"):
        out["date"] = str(entry.get("date"))

    for k in PURCHASE_FIELDS:
        if k in entry:
            out[k] = entry[k]

    for k in entry:
        if k in _DERIVED_FIELDS:
            # 派生值：由 payout - purchase_amount 计算得出，禁止录入
            dropped.append(k)
            logger.warning("purchase_log 剔除派生字段: %s（应计算得出，不落库）", k)
        elif k in PURCHASE_BANNED_FIELDS:
            dropped.append(k)
            # 只记字段名，绝不记值（防密钥/身份信息入日志）
            logger.warning("purchase_log 拒绝红线字段: %s（已剔除，未落库）", k)

    # 语义兜底：未买也必须有明确的 False，而不是字段缺失
    if "purchased" not in out:
        out["purchased"] = False
    if out.get("purchased") and "payout" not in out:
        out["payout"] = 0.0

    return out, dropped


def _key(entry):
    return "%s|%s" % (entry.get("lot"), entry.get("period"))


def record(entry):
    """记录/更新一条购票流水（**幂等**：按 (lot, period) 覆盖同 key 旧值）。

    entry: 至少含 lot / period；其余按 PURCHASE_FIELDS 白名单收录。
    返回 (清洗后的 entry, 被剔除的字段列表)。
    """
    clean, dropped = sanitize_entry(entry)
    entries = load_log()
    k = _key(clean)
    for i, e in enumerate(entries):
        if _key(e) == k:
            entries[i] = clean
            break
    else:
        entries.append(clean)
    _save_log(entries)
    return clean, dropped


def get(lot, period):
    """按 (lot, period) 取一条；无则返回 None。"""
    k = "%s|%s" % (lot, period)
    for e in load_log():
        if _key(e) == k:
            return e
    return None


# 官方奖金池比例（财政部公告 2026 年第 24 号）
_OFFICIAL_PAYOUT_RATIO = {
    "双色球": 0.51,
    "大乐透": 0.51,
    "福彩3D": 0.53,
    "排列三": 0.53,
    "快乐8": 0.58,
    "七星彩": 0.50,
    "七乐彩": 0.50,
}


def official_payout_ratio(lot):
    """该彩种官方奖金池比例；未知彩种返回 None（**不猜**）。"""
    return _OFFICIAL_PAYOUT_RATIO.get(lot)


def summary(lot=None):
    """汇总统计：投入 / 返还 / 净盈亏 / 实际返还率。

    返回的 ratio 为 None 表示**样本为空**（无从计算），
    调用方须区分「0」与「不知道」——与计数场景同一纪律。
    """
    entries = load_log()
    if lot:
        entries = [e for e in entries if e.get("lot") == lot]
    spend = 0.0
    payout = 0.0
    bought = 0
    for e in entries:
        try:
            if e.get("purchased"):
                bought += 1
                spend += float(e.get("purchase_amount") or 0.0)
                payout += float(e.get("payout") or 0.0)
        except (TypeError, ValueError):
            logger.warning("purchase_log 金额解析失败，已跳过: lot=%s period=%s",
                           e.get("lot"), e.get("period"))
            continue
    return {
        "lot": lot or "全部",
        "records": len(entries),
        "bought": bought,
        "spend": round(spend, 2),
        "payout": round(payout, 2),
        "net": round(payout - spend, 2),
        "ratio": round(payout / spend, 4) if spend > 0 else None,
        "official_ratio": official_payout_ratio(lot) if lot else None,
    }


def clear(older_than_days=None):
    """清空流水（支持 PIPL 第 47 条删除权）。

    older_than_days=None ⇒ 全清；否则仅删除超过 N 天的条目（最短保存期限）。
    返回被删除条数。
    """
    entries = load_log()
    if older_than_days is None:
        n = len(entries)
        _save_log([])
        return n
    cutoff = time.time() - older_than_days * 86400
    kept = []
    removed = 0
    for e in entries:
        ts = e.get("_ts")
        if isinstance(ts, (int, float)) and ts < cutoff:
            removed += 1
        else:
            kept.append(e)
    _save_log(kept)
    return removed
