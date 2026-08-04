# -*- coding: utf-8 -*-
"""金水谣数据「门禁去盲区」守护核心模块 (T01)

背景
----
原 quality_gate.py 的 EXCLUDE_DIRS 把整个「金水谣数据」目录排除在快照比对之外，
导致该目录内的核心业务数据（彩票历史、智能体记忆、模型/风险状态等）被误删时
门禁毫无察觉——循环删除事故即源于此。本模块是独立、轻量、纯标准库的目录级强校验，
作为「盲区」补丁，与既有 check_vital_docs() 并存不冲突。

设计铁律
--------
1. 强校验（缺失 -> 红色告警 / 返回 False）：业务根目录存在性 + 唯一难重建的当前态文件。
2. 弱校验 / 排除（防误报核心）：运行时高频写入、缓存、备份、派生物一律排除，
   从源头消除「误报破门禁」这一头号失败模式。
3. 与 check_vital_docs() 并存不冲突：本模块显式跳过已归命门的
   「金水谣数据/风险登记册.md」「金水谣数据/log/ai_decisions.md」，避免重复报红。
4. fail-safe：返回布尔仅表示「数据是否完好」；是否阻断由调用方决定
   （quality_gate 默认模式只告警不阻断；verify 模式硬失败；closeout 每日巡检仅告警）。
5. 纯标准库，零新依赖（os/re/sys）。
"""
import os
import re
import sys

# 确保本模块可被 quality_gate / closeout_gate 以
# `from jinshuiyao_data_guard import check_jinshuiyao_data` 直接导入。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JINSHUIYAO_DATA_DIR = os.path.join(PROJECT_DIR, "金水谣数据")

# —— A. 业务根目录存在性（整目录被删 = 事故主战场）——
STRONG_DIRS = [
    "lot_data",            # 彩票历史数据根，循环删事故主战场
    "backtest_results",    # 回测资产，删了无法复盘
    "agent_memory",        # 智能体记忆唯一副本
    "log",                 # 决策/日志根（仅守目录存在性；文件见排除清单）
    "stock",               # 股票业务域根
    "fund",                # 基金业务域根
    "music",               # 音乐业务域根
    "creator_output",      # 创作产出根
    "users",               # 用户数据根
    "review",              # 评审数据根
]

# —— B. 核心「当前态」文件（每个 = 唯一难重建）——
STRONG_FILES = [
    # 7 彩种历史主数据，删 = 历史全失
    "lot_data/双色球.json",
    "lot_data/大乐透.json",
    "lot_data/快乐8.json",
    "lot_data/七乐彩.json",
    "lot_data/七星彩.json",
    "lot_data/排列三.json",
    "lot_data/福彩3D.json",
    # 预测与参考池核心
    "predictions.json",
    "reference_pool.json",
    # 模型 / 引擎 / 风险状态，重建成本高
    "correlation_matrix.json",
    "brain_state.json",
    "risk_state.json",
    "engines.json",
    "schemes.json",
    "evolution_rules.json",
    "evolution_patterns.json",
    "user_themes.json",
    "free_model_status.json",
    # 彩票健康报告关键产出
    "lottery_health_report.json",
    # 智能体记忆唯一副本（pending_reminders.json 为运行时生成，见 EXCLUDE_PATTERNS）
    "agent_memory/history.json",
]

# —— C. 命门文档（交给 check_vital_docs 守护，本模块显式跳过，不重复报）——
VITAL_SKIP = {
    os.path.join(JINSHUIYAO_DATA_DIR, "风险登记册.md"),
    os.path.join(JINSHUIYAO_DATA_DIR, "log", "ai_decisions.md"),
}

# —— 排除模式（防误报核心）：运行时高频/缓存/备份/派生物，拉进门禁必天天破 ——
#    应用于「相对金水谣数据根」的路径（统一为正斜杠）。当前 STRONG 清单不含这些项，
#    此处既是文档化安全网，也确保未来若新增条目不会误伤运行时目录。
EXCLUDE_PATTERNS = [
    # 备份（可重建、高频变化）：lot_data/*.bak.0~2 等
    r"\.bak\.\d+$",
    r"\.bak\.[^/]+$",
    # 运行时日志（持续追加重写，内容随时变）
    r"\.log$",
    r"\.logl$",
    r"\.audit\.log",
    r"/ai_conversations\.jsonl$",
    r"/automation_mirror\.jsonl$",
    r"/scheduler_.*\.jsonl$",
    r"/health_.*\.jsonl$",
    r"/jinshuiyao\.log$",
    # 缓存 / 派生（可重建派生物）
    r"/(cache|fund/cache|stock/cache|video_cache|_backup_time_backfill|backups|fund_reports)(/|$)",
    # 测试产物（临时产出）
    r"/(test_creator_output|test_creator_review)(/|$)",
    # 审计 / 日志子目录（弱校验，仅目录存在）
    r"/(lot_data/log|log/err_log)(/|$)",
    # 小配置（弱校验，存在即过）
    r"/log/manifest\.json$",
    # 智能体提醒（运行时生成物，未创建属正常）
    r"/agent_memory/pending_reminders\.json$",
]

_COMPILED_EXCLUDE = [re.compile(p) for p in EXCLUDE_PATTERNS]


def _is_excluded(path):
    """路径是否命中排除模式（相对金水谣数据根）。"""
    try:
        rel = os.path.relpath(path, JINSHUIYAO_DATA_DIR).replace(os.sep, "/")
    except ValueError:
        return False
    return any(pat.search(rel) for pat in _COMPILED_EXCLUDE)


def _is_vital_skip(path):
    """路径是否属命门文档（已由 check_vital_docs 守护，避免重复报）。"""
    return os.path.abspath(path) in VITAL_SKIP


def _rel(path):
    """相对项目根的可读路径，用于告警展示。"""
    return os.path.relpath(path, PROJECT_DIR)


def check_jinshuiyao_data(override=False):
    """扫描金水谣数据核心目录/文件完整性。

    返回 True = 全部完好；False = 存在强校验缺失（数据盲区）。
    override=True 时：即便缺失也降级为 🟡 黄灯「已人工确认放行」并返回 True，
        与既有 OVERRIDE 铁律「人工确认后放行」语义一致（不阻断收工）。
    """
    missing = []

    for d in STRONG_DIRS:
        full = os.path.join(JINSHUIYAO_DATA_DIR, d)
        if _is_excluded(full):
            continue
        if not os.path.isdir(full):
            missing.append(full)

    for f in STRONG_FILES:
        full = os.path.join(JINSHUIYAO_DATA_DIR, f)
        if _is_excluded(full) or _is_vital_skip(full):
            continue
        if not os.path.isfile(full):
            missing.append(full)

    if not missing:
        print("✅ 金水谣数据完整性守护: 全部核心目录/文件完好")
        return True

    if override:
        for full in missing:
            print("🟡 金水谣数据盲区(已人工确认放行): %s 缺失" % _rel(full))
        return True

    for full in missing:
        print("❌ 金水谣数据盲区: %s 缺失" % _rel(full))
    return False


if __name__ == "__main__":
    ok = check_jinshuiyao_data()
    sys.exit(0 if ok else 1)
