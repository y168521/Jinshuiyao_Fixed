# -*- coding: utf-8 -*-
"""JS-20260925-06：档案清理守卫单测（predictions.json 被硬截 3258→200 的事故）

事故复盘：scheduler._task_data_maintenance 里一句 `preds_data[-200:]`
把「历史复盘档案」当缓存按条数硬截，3058 条含 actual/prize_tier 的记录一夜蒸发，
且全程无告警。本文件把守卫行为钉死，并加 AST 闸防止同类写法复活。

跑法（沙箱内需关掉捕获，避免 --capture 与新文件冲突的假失败）：
    python -m pytest tests/unit/test_prediction_archive_guard.py -q --capture=no
"""
import ast
import io
import json
import os
import sys
import time

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.infra import archive_guard as AG  # noqa: E402
from core.infra.archive_guard import extract_record_ts, trim_archive  # noqa: E402
from core.infra import scheduler as SC  # noqa: E402


def _rec(days_ago, i):
    """造一条 days_ago 天前的记录"""
    t = time.time() - days_ago * 86400
    return {"date": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)), "i": i}


# ---------------------------------------------------------------------------
# 1. 守卫基本行为
# ---------------------------------------------------------------------------

def test_keep_days_does_not_touch_fresh_archive():
    """档案都在保留期内 → 一条都不删（真实档案 3258 条即此情形）"""
    recs = [_rec(d, i) for i, d in enumerate(range(0, 60))]
    kept, before, after, blocked = trim_archive(recs, keep_days=1095, now=time.time())
    assert (before, after, blocked) == (60, 60, False)
    assert kept is recs or kept == recs


def test_expired_records_are_dropped():
    """明显超期 → 正常淘汰（渐进式，不应触发骤降保护）"""
    recs = [_rec(2000, i) for i in range(10)] + [_rec(1, i) for i in range(90)]
    kept, before, after, blocked = trim_archive(recs, keep_days=1095, now=time.time())
    assert (before, after, blocked) == (100, 90, False)


def test_guard_blocks_huge_shrink():
    """核心：一次砍掉一半以上 → 必须 blocked，且原样返回（调用方放弃写入）"""
    recs = [_rec(1, i) for i in range(100)]
    kept, before, after, blocked = trim_archive(recs, keep_days=0, now=time.time())
    assert blocked is True
    assert (before, after) == (100, 100)   # 关键：after 回到 before，绝不写入 0 条
    assert kept == recs


def test_max_records_cap_applied():
    """条数兜底上限生效（只作防膨胀，不是日常保留量）"""
    recs = [_rec(1, i) for i in range(500)]
    kept, before, after, blocked = trim_archive(recs, keep_days=1095,
                                                max_records=400, now=time.time())
    assert (before, after, blocked) == (500, 400, False)
    assert kept[-1]["i"] == 499          # 保留的是最新的


def test_missing_date_is_kept():
    """日期缺失不能成为删除历史的理由——宁可留不可删"""
    recs = [{"i": 0}, {"i": 1, "date": None}, {"i": 2, "date": "not-a-date"}]
    kept, before, after, blocked = trim_archive(recs, keep_days=1095, now=time.time())
    assert (before, after, blocked) == (3, 3, False)


def test_empty_archive_is_noop():
    assert trim_archive([], keep_days=1095) == ([], 0, 0, False)


def test_extract_record_ts_supports_multiple_keys():
    assert extract_record_ts({"time": "2026-09-19 06:27"}) is not None
    assert extract_record_ts({"draw_date": "2026-09-19"}) is not None
    assert extract_record_ts({"timestamp": 1.0}) == 1.0
    assert extract_record_ts({}) is None
    assert extract_record_ts("not a dict") is None


# ---------------------------------------------------------------------------
# 2. scheduler 必须委托同一真源（禁止各处重写一遍数字）
# ---------------------------------------------------------------------------

def test_scheduler_constants_exist():
    assert SC.PRED_ARCHIVE_KEEP_DAYS == 1095
    assert SC.PRED_ARCHIVE_MAX_RECORDS == 50000


def test_scheduler_delegates_to_single_source():
    """scheduler 的档案清理必须委托 archive_guard，不能自己再实现一份"""
    assert SC._trim_pred_archive.__doc__ and "archive_guard" in SC._trim_pred_archive.__doc__
    recs = [_rec(1, i) for i in range(100)]
    # 骤降场景：委托后应表现为 blocked
    assert SC._trim_pred_archive(recs, keep_days=0)[3] is True


def test_guard_ratio_is_defined_once():
    """护卫比例只准有一份真源"""
    assert AG.ARCHIVE_SHRINK_GUARD_RATIO == 0.5
    assert hasattr(AG, "DEFAULT_ARCHIVE_KEEP_DAYS")


# ---------------------------------------------------------------------------
# 3. AST 闸：禁止任何清理点再写 [-N:] 尾部截断
#    能落成 AST 闸就落——靠人记住"别这么写"一定会再犯
# ---------------------------------------------------------------------------

# 只扫「真正会写档案」的函数；None 表示整个文件都扫。
# 教训（本次实测）：一开始扫的是整个文件的所有 [-N:]，立刻被
# `recent = reviewed[-5:]`、`splitlines()[-3:]` 这类**读取**用法打成假红。
# 闸太宽 = 假警 = 噪音，噪音比没有告警更糟。所以必须精确到函数。
_GUARDED_FUNCS = {
    os.path.join("core", "infra", "scheduler.py"):
        ["_task_data_maintenance", "_trim_pred_archive"],
    os.path.join("core", "infra", "archive_guard.py"): None,
    os.path.join("core", "ai", "agent_vector_memory.py"): ["_save_entries"],
    os.path.join("core", "ai", "ai_agent.py"): ["_aa_add_memory"],
}


def _tail_truncations(nodes):
    """找出形如 x[-N:] 的尾部切片（N 为整数字面量）"""
    found = []
    for root in nodes:
        for node in ast.walk(root):
            if not isinstance(node, ast.Subscript):
                continue
            sl = node.slice
            # 形如 x[-200:] ：Slice(lower=UnaryOp(USub, Constant(200)), upper=None)
            if not isinstance(sl, ast.Slice) or sl.upper is not None:
                continue
            lo = sl.lower
            if (isinstance(lo, ast.UnaryOp) and isinstance(lo.op, ast.USub)
                    and isinstance(lo.operand, ast.Constant)
                    and isinstance(lo.operand.value, int)):
                found.append(node.lineno)
    return found


def test_no_tail_truncation_in_archive_writers():
    """档案**写入**函数里禁止出现 `x[-N:]` 尾部硬截（会重演 3258→200 事故）。"""
    bad = []
    for rel, funcs in _GUARDED_FUNCS.items():
        path = os.path.join(BASE_DIR, rel)
        assert os.path.isfile(path), "源文件缺失：%s（闸门基准可能错了）" % path
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        if funcs is None:
            scopes = [tree]
        else:
            scopes = [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name in funcs]
            missing = set(funcs) - {n.name for n in scopes}
            assert not missing, "%s 缺少目标函数 %s（改名后闸门会静默失效）" % (rel, missing)
        for ln in _tail_truncations(scopes):
            bad.append("%s:%d" % (rel, ln))
    assert bad == [], "档案写入函数出现尾部硬截：%s" % bad


# ---------------------------------------------------------------------------
# 4. 健康看门狗第 ④ 项：档案骤降告警
# ---------------------------------------------------------------------------

def test_health_watch_flags_archive_shrink(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(BASE_DIR, "tools"))
    import health_watch as HW

    arch = tmp_path / "arch.json"
    arch.write_text(json.dumps([{"i": i} for i in range(300)]), encoding="utf-8")
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"T": {"count": 1000, "ts": "x"}}), encoding="utf-8")

    monkeypatch.setattr(HW, "CORE_ARCHIVES", {"T": str(arch)})
    monkeypatch.setattr(HW, "ARCHIVE_BASELINE_FILE", str(base))
    monkeypatch.setattr(HW, "_save_baseline", lambda b: None)

    alerts = HW.check_archives()
    assert len(alerts) == 1
    assert alerts[0]["item"] == "档案条数骤降"
    assert alerts[0]["how"]  # 必须给处置动作（告警价值＝能不能变绿）


def test_health_watch_silent_when_healthy(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(BASE_DIR, "tools"))
    import health_watch as HW

    arch = tmp_path / "arch.json"
    arch.write_text(json.dumps([{"i": i} for i in range(300)]), encoding="utf-8")

    monkeypatch.setattr(HW, "CORE_ARCHIVES", {"T": str(arch)})
    monkeypatch.setattr(HW, "ARCHIVE_BASELINE_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(HW, "_save_baseline", lambda b: None)

    assert HW.check_archives() == []


def test_health_watch_reuses_single_guard_ratio():
    """看门狗的骤降比例必须来自 archive_guard，不能另写一份数字"""
    sys.path.insert(0, os.path.join(BASE_DIR, "tools"))
    import health_watch as HW
    assert HW.ARCHIVE_SHRINK_GUARD_RATIO == AG.ARCHIVE_SHRINK_GUARD_RATIO


# ---------------------------------------------------------------------------
# 5. 端到端：真实档案不会被删（这条最有价值，防"修完还删数据"）
# ---------------------------------------------------------------------------

def test_real_predictions_archive_is_not_trimmed():
    path = os.path.join(BASE_DIR, "金水谣数据", "predictions.json")
    if not os.path.isfile(path):
        pytest.skip("真实档案不存在，跳过端到端")
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list) and len(data) > 0
    _kept, before, after, blocked = SC._trim_pred_archive(data)
    assert blocked is False
    assert after == before, "默认保留策略下真实档案不应被删任何一条"
