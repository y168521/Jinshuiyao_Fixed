# -*- coding: utf-8 -*-
"""
金水谣记忆衰减与强化模块
==========================
模拟人脑记忆机制：
  - 用进废退：被引用的知识卡片 effectiveness 上升
  - 自然衰减：长期未使用的卡片 effectiveness 缓慢下降
  - 自动归档：衰减到阈值以下的卡片移入 archive 类别
  - 间隔重复：命中验证正确的卡片获得额外强化

设计：纯标准库，可被 scheduler 定时调用（建议每24小时一次）。
"""
import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIROFISH_DB_PATH = os.path.join(BASE_DIR, "knowledge", "mirofish_db.json")

# ---------------------------------------------------------------------------
# 衰减参数（可调）
# ---------------------------------------------------------------------------
DECAY_RATE = 0.5          # 每天未使用衰减的 effectiveness 点数
DECAY_GRACE_DAYS = 7      #  grace period：最近N天内创建/更新的不衰减
ARCHIVE_THRESHOLD = 15    # effectiveness 低于此值自动归档
BOOST_ON_USE = 3          # 每次被引用时增加的 effectiveness
BOOST_ON_VERIFY = 8       # 预测验证命中时增加的 effectiveness
MAX_EFFECTIVENESS = 100   # 上限
MIN_EFFECTIVENESS = 0     # 下限


def _load_db():
    """加载 MiroFish DB"""
    if not os.path.isfile(MIROFISH_DB_PATH):
        return None
    try:
        with open(MIROFISH_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("加载 mirofish_db.json 失败: %s", e)
        return None


def _save_db(db):
    """保存 MiroFish DB（原子写入）"""
    tmp_path = MIROFISH_DB_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MIROFISH_DB_PATH)
        return True
    except Exception as e:
        logger.error("保存 mirofish_db.json 失败: %s", e)
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return False


def _days_since(date_str):
    """计算距离给定日期字符串的天数"""
    if not date_str:
        return 999
    try:
        # 支持多种格式
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return (datetime.now() - dt).days
            except ValueError:
                continue
    except Exception:
        pass
    return 999


def run_decay_cycle():
    """
    执行一次完整的衰减周期。
    返回 {decayed, archived, boosted, total} 统计。
    """
    db = _load_db()
    if not db:
        return {"error": "无法加载知识库"}

    cards = db.get("cards", [])
    stats = {"decayed": 0, "archived": 0, "boosted": 0, "total": len(cards)}
    modified = False

    for card in cards:
        if card.get("category") == "archive":
            continue  # 已归档的不再衰减

        effectiveness = card.get("effectiveness", 50)
        last_used = card.get("last_used", "")
        created = card.get("created", "")
        updated = card.get("updated", "")

        # Grace period：新卡片不衰减
        newest = max(
            _days_since(created),
            _days_since(updated),
        )
        if newest < DECAY_GRACE_DAYS:
            continue

        # 计算衰减
        days_unused = _days_since(last_used)
        if days_unused > DECAY_GRACE_DAYS:
            # 衰减量 = 超出grace的天数 * 每日衰减率（但有上限，不会一次衰太多）
            decay_amount = min(
                (days_unused - DECAY_GRACE_DAYS) * DECAY_RATE,
                10  # 单次最多衰减10点
            )
            new_eff = max(MIN_EFFECTIVENESS, effectiveness - decay_amount)
            if new_eff != effectiveness:
                card["effectiveness"] = round(new_eff, 1)
                stats["decayed"] += 1
                modified = True

                # 检查是否需要归档
                if new_eff < ARCHIVE_THRESHOLD:
                    card["category"] = "archive"
                    card["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    stats["archived"] += 1
                    logger.info("卡片归档: %s (effectiveness=%.1f)",
                                card.get("title", "?"), new_eff)

    if modified:
        _save_db(db)
        logger.info("记忆衰减完成: 衰减%d张, 归档%d张", stats["decayed"], stats["archived"])

    return stats


def boost_card(card_id, reason="use"):
    """
    强化指定卡片（被引用/验证命中时调用）。

    参数:
        card_id: 卡片ID
        reason: "use"(被引用) 或 "verify"(预测验证命中)
    """
    db = _load_db()
    if not db:
        return False

    boost = BOOST_ON_VERIFY if reason == "verify" else BOOST_ON_USE
    cards = db.get("cards", [])

    for card in cards:
        if card.get("id") == card_id:
            old_eff = card.get("effectiveness", 50)
            new_eff = min(MAX_EFFECTIVENESS, old_eff + boost)
            card["effectiveness"] = round(new_eff, 1)
            card["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            card["use_count"] = card.get("use_count", 0) + 1

            # 如果之前被归档了，恢复
            if card.get("category") == "archive" and new_eff >= ARCHIVE_THRESHOLD:
                card["category"] = card.get("subsystem", "resource")

            _save_db(db)
            logger.debug("卡片强化: %s (+%d, %s→%s)",
                         card.get("title", "?"), boost, old_eff, new_eff)
            return True

    return False


def boost_by_title(title_keyword, reason="use"):
    """按标题关键词强化（模糊匹配）"""
    db = _load_db()
    if not db:
        return 0

    boosted = 0
    for card in db.get("cards", []):
        if title_keyword in card.get("title", ""):
            if boost_card(card["id"], reason):
                boosted += 1
    return boosted


def get_decay_report():
    """获取衰减状态报告（不执行衰减，只分析）"""
    db = _load_db()
    if not db:
        return {"error": "无法加载知识库"}

    cards = db.get("cards", [])
    report = {
        "total": len(cards),
        "active": 0,
        "at_risk": 0,      # effectiveness 在 15-30 之间
        "archived": 0,
        "stale_30d": 0,    # 30天未使用
        "stale_90d": 0,    # 90天未使用
        "top_effective": [],
        "bottom_effective": [],
    }

    active_cards = []
    for card in cards:
        cat = card.get("category", "")
        eff = card.get("effectiveness", 50)
        days = _days_since(card.get("last_used", ""))

        if cat == "archive":
            report["archived"] += 1
        else:
            report["active"] += 1
            active_cards.append(card)
            if eff < 30:
                report["at_risk"] += 1
            if days > 30:
                report["stale_30d"] += 1
            if days > 90:
                report["stale_90d"] += 1

    # Top/Bottom
    active_cards.sort(key=lambda c: c.get("effectiveness", 0), reverse=True)
    report["top_effective"] = [
        {"title": c.get("title", ""), "effectiveness": c.get("effectiveness", 0)}
        for c in active_cards[:5]
    ]
    report["bottom_effective"] = [
        {"title": c.get("title", ""), "effectiveness": c.get("effectiveness", 0)}
        for c in active_cards[-5:]
    ]

    return report


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 50)
    print("  金水谣记忆衰减引擎")
    print("=" * 50)

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report = get_decay_report()
        print(f"\n  总卡片: {report['total']}")
        print(f"  活跃: {report['active']} | 归档: {report['archived']}")
        print(f"  风险(eff<30): {report['at_risk']}")
        print(f"  30天未用: {report['stale_30d']} | 90天未用: {report['stale_90d']}")
        print(f"\n  最强记忆:")
        for item in report["top_effective"]:
            print(f"    [{item['effectiveness']}] {item['title']}")
        print(f"\n  最弱记忆:")
        for item in report["bottom_effective"]:
            print(f"    [{item['effectiveness']}] {item['title']}")
    else:
        print("\n  执行衰减周期...")
        stats = run_decay_cycle()
        print(f"  完成: 衰减{stats.get('decayed', 0)}张, "
              f"归档{stats.get('archived', 0)}张, "
              f"总计{stats.get('total', 0)}张")

    if sys.platform == "win32" and sys.stdin.isatty():
        # 仅交互终端暂停，避免服务器/调度/无头上下文被 pause 卡死（JS-20260723-37）
        os.system("pause >nul 2>&1")
