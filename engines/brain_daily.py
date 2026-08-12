# -*- coding: utf-8 -*-
"""大脑日报引擎 - 智能大脑第2步·长脑子

三个能力（全部免费模型优先、失败静默降级，不打扰主流程）：
1. ensure_daily_brief(lot)  生成前取当天AI简报（每天每彩种最多1次）→ 可注入 extra_hot
2. ensure_daily_summary()   当天AI复盘总结（每天1次，总结近期失误模式）
3. gen_daily_report()       生成《大脑日报》（纯统计+自动调整结论+AI总结段，人话版）
4. run_daily()              scheduler 定时入口：summary + report

数据位置：
- 简报缓存: 金水谣数据/brain/ai_brief_{lot}.json（date+brief，当天复用）
- 总结:     金水谣数据/brain/ai_summary_YYYY-MM-DD.md
- 日报:     金水谣数据/log/大脑日报_YYYY-MM-DD.md
"""
import io
import json
import logging
import os
import re
from datetime import datetime

# 单一真源（债务-203）：期望命中基准在 prediction_service.py 模块级维护，此处复用不再各自维护
from engines.prediction_service import _PLAY_EXPECTED

logger = logging.getLogger(__name__)

_BRAIN_DIR = os.path.join("金水谣数据", "brain")
_REPORT_DIR = os.path.join("金水谣数据", "log")
_PRED_FILE = os.path.join("金水谣数据", "predictions.json")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _load_json(path, default=None):
    try:
        if os.path.isfile(path):
            with io.open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.debug("brain_daily 读取失败 %s: %s", path, e)
    return default


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.debug("brain_daily 写入失败 %s: %s", path, e)


def _get_ai():
    try:
        from core.ai_service import get_ai_service
        return get_ai_service()
    except Exception:
        return None


def _ai_json(system_prompt, user_prompt, max_tokens=800):
    """调用AI并要求返回JSON对象，失败返回 None"""
    ai = _get_ai()
    if ai is None:
        return None
    try:
        raw = ai.chat(system_prompt, user_prompt, free_first=True, max_tokens=max_tokens)
        if not raw:
            return None
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
        if m:
            raw = m.group(1)
        j = re.search(r"\{.*\}", raw, re.S)
        if j:
            raw = j.group(0)
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except Exception as e:
        logger.debug("brain_daily AI调用失败: %s", e)
        return None


def _load_recent_predictions(lot=None, play_type=None, window=30):
    """从复盘数据取 (lot,type) 近N条 [lot,type,nums,hits]"""
    rows = _load_json(_PRED_FILE, [])
    if not isinstance(rows, list):
        return []
    if lot:
        rows = [r for r in rows if r.get("lot") == lot]
    if play_type:
        rows = [r for r in rows if r.get("type") == play_type]
    return rows[-window:]


# ============================================================ 1. AI 简报
def _build_brief(lot, arr):
    """近20期历史 → AI 结构化建议"""
    recent = [d for d in (arr or []) if d.get("nums")][-20:]
    if len(recent) < 10:
        return None
    lines = []
    for d in recent:
        lines.append(f"{d.get('period')}: {d.get('nums')}")
    system = (
        "你是资深彩票数据分析师。请基于给定的开奖历史序列，输出一个JSON对象，"
        '格式: {"hot":[3个最值得关注的号码,从小到大],"kill":[2个应回避的号码],'
        '"morph":"组三/组六/直选等形态提示","reason":"不超过50字的理由"}。'
        "只输出JSON，不要任何其他文字。"
    )
    out = _ai_json(system, "\n".join(lines))
    if not out:
        return None
    digits = []
    for x in (out.get("hot") or []):
        s = str(x).strip()
        if s.lstrip("-").isdigit():
            digits.append(int(s))
    kills = []
    for x in (out.get("kill") or []):
        s = str(x).strip()
        if s.lstrip("-").isdigit():
            kills.append(int(s))
    return {
        "hot": sorted(set(digits))[:5],
        "kill": sorted(set(kills))[:3],
        "morph": str(out.get("morph", ""))[:12],
        "reason": str(out.get("reason", ""))[:100],
    }


def ensure_daily_brief(lot, arr=None):
    """生成前取当天AI简报（每天每彩种≤1次，当天缓存复用；失败返回 None）"""
    try:
        os.makedirs(_BRAIN_DIR, exist_ok=True)
        path = os.path.join(_BRAIN_DIR, "ai_brief_%s.json" % lot)
        data = _load_json(path, {})
        if data.get("date") == _today() and isinstance(data.get("brief"), dict):
            return data["brief"]
        brief = _build_brief(lot, arr) if arr is not None else None
        if brief is not None:
            _save_json(path, {"date": _today(), "brief": brief})
        return brief
    except Exception as e:
        logger.debug("brain_daily 简报失败: %s", e)
        return None


# ============================================================ 2. AI 复盘总结
def _stats_by_play(lot=None, window=30):
    """统计 (lot,type) 近N期: {lot: {type: {n, avg, exp, ratio}}}"""
    stats = {}
    rows = _load_recent_predictions(lot=lot, window=10000)
    buckets = {}
    for r in rows:
        key = (r.get("lot"), r.get("type"))
        buckets.setdefault(key, []).append(r.get("hits", 0))
    for (l, t), hs in buckets.items():
        hs = hs[-window:]
        exp = _PLAY_EXPECTED.get((l, t))
        st = {"n": len(hs), "avg": sum(hs) / len(hs) if hs else 0}
        st["exp"] = exp
        st["ratio"] = (st["avg"] / exp) if (exp and exp > 0) else None
        stats.setdefault(l, {})[t] = st
    return stats


def _load_recent_history(limit=50):
    rows = _load_json(_PRED_FILE, [])
    if not isinstance(rows, list):
        return []
    return rows[-limit:]


def _build_summary_text(ai_out):
    return str(ai_out or "")


def ensure_daily_summary():
    """当天AI复盘总结（每天1次）。返回总结文本，失败返回 None。"""
    try:
        path = os.path.join(_BRAIN_DIR, "ai_summary_%s.md" % _today())
        if os.path.isfile(path):
            with io.open(path, encoding="utf-8") as f:
                return f.read()
        os.makedirs(_BRAIN_DIR, exist_ok=True)
        history = _load_recent_history(60)
        if len(history) < 10:
            return None
        sample = []
        for r in history[-15:]:
            sample.append("%s %s %s hits=%s" % (r.get("lot"), r.get("period"), r.get("nums"), r.get("hits")))
        system = (
            "你是彩票预测系统的复盘教练。给定最近若干期的预测记录（格式: 彩种 期号 预测号码 hits=命中数），"
            "请用中文总结近期的失误模式与改进方向，输出一个JSON对象，"
            '格式: {"pattern":"不超过80字的失误模式总结","advice":"不超过80字的下期改进建议"}。'
            "只输出JSON，不要其他文字。"
        )
        out = _ai_json(system, "\n".join(sample), max_tokens=400)
        if not out:
            return None
        text = (
            "### AI 复盘总结 %s\n"
            "- 失误模式：%s\n"
            "- 改进建议：%s\n" % (_today(), out.get("pattern", ""), out.get("advice", ""))
        )
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    except Exception as e:
        logger.debug("brain_daily 复盘总结失败: %s", e)
        return None


# ============================================================ 3. 大脑日报
def _collect_stats():
    return _stats_by_play(window=30)


def gen_daily_report(date=None):
    """生成《大脑日报》（人话版）。返回文件路径。"""
    try:
        date = date or _today()
        stats = _collect_stats()
        lines = []
        lines.append("# 大脑日报 %s" % date)
        lines.append("")
        lines.append("> 这份日报由系统自动生成：今天的玩法健康度、自动调整结论、AI 复盘总结。")
        lines.append("")
        if not stats:
            lines.append("暂无复盘数据，明天再来。")
        for lot in sorted(stats.keys()):
            lines.append("## %s" % lot)
            lines.append("")
            lines.append("| 玩法 | 近30期 | 平均命中 | 随机期望 | 效果 | 结论 |")
            lines.append("|------|-------|---------|---------|------|------|")
            for t, st in sorted(stats[lot].items(), key=lambda x: -(x[1]["ratio"] if x[1]["ratio"] is not None else 1)):
                ratio = st["ratio"]
                if ratio is None:
                    eff = "-"
                elif ratio >= 1.4:
                    eff = "良好"
                elif ratio >= 1.0:
                    eff = "正常"
                elif ratio >= 0.6:
                    eff = "偏弱"
                else:
                    eff = "亏损"
                if ratio is None:
                    verdict = "数据不足"
                elif ratio < 0.6:
                    verdict = "已自动停用" if t != "胆拖" else "已停用"
                elif ratio >= 1.4:
                    verdict = "自动加注"
                elif t == "胆拖":
                    verdict = "已停用"
                else:
                    verdict = "维持"
                exp_txt = "%.2f" % st["exp"] if st["exp"] else "-"
                ratio_txt = "%.0f%%" % (ratio * 100) if ratio is not None else "-"
                lines.append("| %s | %d | %.2f | %s | %s | %s |" % (t, st["n"], st["avg"], exp_txt, eff, verdict))
            lines.append("")
        summary = ensure_daily_summary()
        if summary:
            lines.append("## AI 复盘总结")
            lines.append("")
            lines.append(summary)
        os.makedirs(_REPORT_DIR, exist_ok=True)
        out_path = os.path.join(_REPORT_DIR, "大脑日报_%s.md" % date)
        with io.open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info("大脑日报已生成: %s", out_path)
        return out_path
    except Exception as e:
        logger.debug("brain_daily 日报失败: %s", e)
        return None


# ============================================================ 4. 定时入口
def run_daily():
    """scheduler 每天1次：AI总结 + 日报"""
    try:
        ensure_daily_summary()
    except Exception:
        pass
    try:
        gen_daily_report()
    except Exception:
        pass
    return True
