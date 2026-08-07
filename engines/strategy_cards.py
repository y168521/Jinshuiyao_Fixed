# -*- coding: utf-8 -*-
"""策略知识卡提炼 - 从复盘数据自动提炼引擎挂钩知识卡

链路: 复盘(predictions.json) → 统计各彩种策略表现 → 提炼/更新 MiroFish 引擎挂钩卡
      → 预测时 knowledge 咨询(get_for_engine) → 杀号/热号/冷号调整系数

三类挂钩卡（与 prediction_service._consult_knowledge 的三个场景一一对应）:
  weight_calibration   权重校准: 按方案统计命中表现 → effectiveness（影响 hot_factor）
  kill_strategy        杀号策略: 彩种 0 码率 → 杀号保守度（影响 kill_factor）
  miss_breakthrough    遗漏突破: 命中趋势 → 冷号回补强度（影响 cold_factor）

诚实约束:
  1. 所有卡片数值全部来自真实复盘统计，不做主观赋值；
  2. 数据不足（彩种复盘 < 10 条）跳过，绝不伪造；
  3. effectiveness 按 0-100 映射（50=中性，>50 增强，<50 保守），
     与 prediction_service 的 factor 映射(0.8~1.2) 配合时 50 即为中性 1.0。
"""

import os
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# 项目根 = 本文件(engines/) 上一级
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRED_FILE = os.path.join(_PROJECT_ROOT, "金水谣数据", "predictions.json")

# 每彩种统计窗口（最近 N 条已复盘记录）
_STAT_WINDOW = 40
# 最小样本量（不足则跳过该彩种）
_MIN_REVIEWS = 10

HOOK_WEIGHT = "weight_calibration"
HOOK_KILL = "kill_strategy"
HOOK_MISS = "miss_breakthrough"
ALL_HOOKS = (HOOK_WEIGHT, HOOK_KILL, HOOK_MISS)

# 彩种 → 知识库 domain（与 prediction_service._consult_knowledge 的映射一致）
DOMAIN_3D = "3d"
DOMAIN_LOTTERY = "lottery"


def _domain_of(lot):
    return DOMAIN_3D if lot in ("福彩3D", "排列三") else DOMAIN_LOTTERY


def _load_reviews():
    """加载已复盘的预测记录，按彩种分组（仅取最近 _STAT_WINDOW 条）"""
    try:
        from utils.safe_json import safe_load_json
        preds = safe_load_json(_PRED_FILE, default=[])
    except Exception as e:
        logger.warning("策略卡提炼: 读取复盘数据失败: %s", e)
        return {}
    if not isinstance(preds, list):
        return {}

    by_lot = defaultdict(list)
    for p in preds:
        if not (isinstance(p, dict) and p.get("reviewed") and p.get("hits") is not None):
            continue
        by_lot[p.get("lot", "")].append(p)
    for lot in list(by_lot):
        by_lot[lot] = by_lot[lot][-_STAT_WINDOW:]
    return dict(by_lot)


def _stats(reviews):
    """统计一彩种的策略表现

    Returns:
        dict: avg_hits/hit_rate/zero_rate/trend/early_hit_rate/recent_hit_rate/by_scheme
    """
    n = len(reviews)
    hits_list = [r.get("hits", 0) for r in reviews]
    avg_hits = sum(hits_list) / n
    hit_rate = len([h for h in hits_list if h > 0]) / n
    zero_rate = len([h for h in hits_list if h == 0]) / n

    # 趋势: 后一半 vs 前一半命中率（-1..1）
    mid = n // 2
    early = hits_list[:mid] or [0]
    recent = hits_list[mid:] or [0]
    early_rate = len([h for h in early if h > 0]) / len(early)
    recent_rate = len([h for h in recent if h > 0]) / len(recent)
    trend = max(-1.0, min(1.0, recent_rate - early_rate))

    by_scheme = {}
    schemes = defaultdict(list)
    for r in reviews:
        schemes[r.get("scheme", "默认方案")].append(r.get("hits", 0))
    for name, hh in schemes.items():
        if len(hh) >= 3:
            by_scheme[name] = {
                "avg": sum(hh) / len(hh),
                "hit_rate": len([h for h in hh if h > 0]) / len(hh),
                "n": len(hh),
            }
    return {
        "n": n, "avg_hits": avg_hits, "hit_rate": hit_rate,
        "zero_rate": zero_rate, "trend": trend,
        "early_hit_rate": early_rate, "recent_hit_rate": recent_rate,
        "by_scheme": by_scheme,
    }


def _eff_weight(st):
    """权重校准卡 effectiveness: 由方案命中表现驱动（50=中性）"""
    if not st["by_scheme"]:
        return 50
    best = max(st["by_scheme"].values(), key=lambda s: s["hit_rate"])
    return max(10, min(90, round(best["hit_rate"] * 60 + 30)))


def _eff_kill(st):
    """杀号策略卡 effectiveness: 0 码率越低 → 杀号越准 → 越高"""
    return max(10, min(90, round((1 - st["zero_rate"]) * 50 + 25)))


def _eff_miss(st):
    """遗漏突破卡 effectiveness: 命中率上升 → 突破有效 → 越高"""
    return max(10, min(90, round(50 + st["trend"] * 35)))


def _content(lot, st, hook):
    """卡片正文: 真实统计明细"""
    lines = [
        f"彩种: {lot}（统计窗口: 最近 {st['n']} 条已复盘记录）",
        f"平均命中: {st['avg_hits']:.2f} 个 | 有中码率: {st['hit_rate']*100:.0f}% | 0码率: {st['zero_rate']*100:.0f}%",
        f"命中趋势: {'上升' if st['trend'] > 0.1 else ('下降' if st['trend'] < -0.1 else '平稳')}"
        f"（近{len(range(st['n']//2, st['n']))}期 {st['recent_hit_rate']*100:.0f}% vs 前{st['n']//2}期 {st['early_hit_rate']*100:.0f}%）",
    ]
    if hook == HOOK_WEIGHT and st["by_scheme"]:
        schemes = "；".join(f"{name}: 均{info['avg']:.2f}个/命中率{info['hit_rate']*100:.0f}%({info['n']}条)"
                            for name, info in sorted(st["by_scheme"].items(),
                                                    key=lambda x: -x[1]["hit_rate"]))
        lines.append(f"方案表现: {schemes}")
    elif hook == HOOK_KILL:
        lines.append("应用: 0码率高→杀号保守(减少杀号); 0码率低→维持杀号强度")
    elif hook == HOOK_MISS:
        lines.append("应用: 命中率上行→增强冷号回补权重; 下行→冷号突破谨慎")
    lines.append("来源: 复盘数据自动提炼（策略卡引擎）")
    return "\n".join(lines)


def refresh_strategy_cards(on_log=None):
    """幂等提炼/更新引擎挂钩策略卡（复盘后调用）

    Returns:
        dict: {"created": [titles], "updated": [titles], "skipped": [lots]}
    """
    result = {"created": [], "updated": [], "skipped": []}
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
    except Exception as e:
        logger.warning("策略卡提炼: 知识库不可用: %s", e)
        return result

    reviews_by_lot = _load_reviews()
    for lot, reviews in sorted(reviews_by_lot.items()):
        if not reviews:
            continue
        if len(reviews) < _MIN_REVIEWS:
            result["skipped"].append(f"{lot}(样本{len(reviews)}<{_MIN_REVIEWS})")
            continue
        st = _stats(reviews)
        domain = _domain_of(lot)

        for hook, eff_fn, label in (
            (HOOK_WEIGHT, _eff_weight, "权重校准"),
            (HOOK_KILL, _eff_kill, "杀号策略"),
            (HOOK_MISS, _eff_miss, "遗漏突破"),
        ):
            effectiveness = eff_fn(st)
            title = f"[策略] {lot} {label}"
            content = _content(lot, st, hook)
            try:
                existing = None
                for c in db._data.get("cards", []):
                    if c.get("title") == title:
                        existing = c
                        break
                if existing:
                    old_eff = existing.get("effectiveness", 50)
                    existing["effectiveness"] = effectiveness
                    existing["content"] = content
                    existing["updated"] = _now()
                    existing["engine_hook"] = hook
                    existing["domain"] = domain
                    result["updated"].append(title)
                    logger.info("策略卡更新: %s eff %d→%d", title, old_eff, effectiveness)
                else:
                    db.add_card(
                        title=title, content=content, category="skill",
                        domain=domain, tags=["策略", lot, label],
                        source="复盘数据自动提炼", engine_hook=hook,
                        priority=7, subsystem="lottery", value_level="知识",
                        effectiveness=effectiveness,
                    )
                    result["created"].append(title)
                    logger.info("策略卡新建: %s eff=%d", title, effectiveness)
            except Exception as e:
                logger.warning("策略卡处理失败 [%s]: %s", title, e)

    db._save()
    if on_log:
        on_log(f"📚 策略卡提炼: 新建{len(result['created'])} 更新{len(result['updated'])}"
               f" 跳过{len(result['skipped'])}", "INFO")
    return result


def ensure_initial_strategy_cards(on_log=None):
    """启动时兜底: 确保有策略卡（无则提炼一次），保证预测链路知识库非空"""
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        if not any(c.get("engine_hook") in ALL_HOOKS for c in db._data.get("cards", [])):
            return refresh_strategy_cards(on_log=on_log)
    except Exception:
        pass
    return {"created": [], "updated": [], "skipped": []}


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
