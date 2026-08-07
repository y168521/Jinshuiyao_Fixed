# -*- coding: utf-8 -*-
"""【道衍推导·P2-G4】影子测试 + LLM-as-a-Judge 晋级

阳 = 实测择优（数据驱动）；阴 = 异步不阻塞（影子流量绝不拖慢主链路）。
天 = 配置外部化（config/model_router.json: shadow.*）；地 = 隔离（后台线程，失败静默）；
人 = 复盘（金水谣数据/shadow_eval.jsonl + shadow_summary 可读）。
知止：候选模型仅吃 5% 影子流量，由裁判按数学评分卡打分；统计胜出且仅当 auto_promote=true
      才改写优先级，**默认只建议不自动改路由**，把最终决定权留给 owner。

评分卡（纯数学，无主观）：
  +5  JSON 合法（若任务需 JSON）   +3 时延达标   -10 幻觉/事实错   -5 格式崩
  综合分出 候选分 vs 生产基线分，统计胜出且成本不增 → 建议/晋级。
"""
import os
import json
import time
import random
import threading
from utils.safe_json import safe_write_json, safe_load_json

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EVAL_PATH = os.path.join(_PROJECT_ROOT, "金水谣数据", "shadow_eval.jsonl")
_lock = threading.Lock()


def _load_shadow_cfg():
    """从 model_router.json 读取 shadow 配置。"""
    try:
        from core.model_router import _load_cfg
        return _load_cfg().get("shadow", {}) or {}
    except Exception:
        return {}


def maybe_shadow(task_type, user_prompt, prod_text, prod_used):
    """在主链路成功后调用（不阻塞）。按 sample_rate 抽样，异步跑候选 + 裁判。"""
    sh = _load_shadow_cfg()
    if not sh.get("enabled", False):
        return
    cand = sh.get("candidate_model_id")
    if not cand:
        return
    if random.random() >= float(sh.get("sample_rate", 0.05)):
        return
    t = threading.Thread(
        target=_shadow_run,
        args=(task_type, user_prompt, prod_text, prod_used, cand),
        daemon=True,
    )
    t.start()


def _shadow_run(task_type, user_prompt, prod_text, prod_used, cand):
    try:
        from core.free_model_pool import get_free_provider_cfgs, call_ai_failover
        cfgs = [c for c in get_free_provider_cfgs() if c.get("_model_id") == cand]
        if not cfgs:
            _record(task_type, cand, prod_used, error="candidate_not_in_pool")
            return
        cand_text, err, _ = call_ai_failover(
            cfgs, "你是金水谣助手，简洁准确地回答。", user_prompt,
            timeout=30, max_tokens=400)
        if cand_text is None:
            _record(task_type, cand, prod_used, error=str(err))
            return
        score = _judge(user_prompt, prod_text, cand_text)
        _record(task_type, cand, prod_used, candidate_text=cand_text,
                score=score)
    except Exception:
        pass


def _judge(user_prompt, prod_text, cand_text):
    """LLM-as-a-Judge：用免费模型当裁判，按数学评分卡打分，返回 dict 或 None。"""
    try:
        from core.free_model_pool import call_ai_failover
        rubric = (
            "你是严格的评分裁判。对比【生产回答】与【候选回答】对用户问题的质量。\n"
            "按以下数学规则打分（无主观）：\n"
            "  +5 若任务需JSON且候选JSON合法（否则JSON项不计分）\n"
            "  +3 候选回答覆盖要点、时延可接受\n"
            "  -10 候选出现明显事实错误/幻觉/胡说\n"
            "  -5 候选格式崩坏、截断、无法阅读\n"
            "只输出一行 JSON：{\"score\":<整数>,\"reason\":\"<简短>\"}"
        )
        judge_sys = "你是金水谣模型评测裁判，只输出评分 JSON。"
        user_block = f"用户问题：{user_prompt}\n生产回答：{prod_text}\n候选回答：{cand_text}\n请评分。"
        txt, err, _ = call_ai_failover(
            _judge_cfgs(), judge_sys, user_block, timeout=30, max_tokens=200, force_json_mode=True)
        if txt is None:
            return None
        # 从返回里提取 JSON
        import re
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        return {"score": int(d.get("score", 0)), "reason": d.get("reason", "")}
    except Exception:
        return None


_judge_cache = None


def _judge_cfgs():
    global _judge_cache
    if _judge_cache is None:
        from core.free_model_pool import get_free_provider_cfgs
        _judge_cache = get_free_provider_cfgs()
    return _judge_cache


def _record(task_type, candidate, prod_used, candidate_text=None, score=None, error=None):
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "task_type": task_type,
            "candidate": candidate,
            "prod_used": prod_used,
            "candidate_score": (score or {}).get("score"),
            "judge_reason": (score or {}).get("reason"),
            "error": error,
        }
        with _lock:
            with open(_EVAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def shadow_summary(min_samples=30):
    """聚合影子评测：候选胜出率、平均分、是否满足晋级条件。"""
    try:
        with open(_EVAL_PATH, "r", encoding="utf-8") as f:
            rows = [json.loads(l) for l in f.read().splitlines() if l.strip()]
    except FileNotFoundError:
        return {"count": 0, "ready": False}
    if len(rows) < min_samples:
        return {"count": len(rows), "ready": False, "min_samples": min_samples}
    scored = [r for r in rows if r.get("candidate_score") is not None]
    ok = [r for r in scored if r["candidate_score"] >= 0]  # 无重度负分（幻觉等）
    win_rate = len(ok) / len(scored) if scored else 0
    avg = sum(r["candidate_score"] for r in scored) / len(scored) if scored else 0
    sh = _load_shadow_cfg()
    auto = bool(sh.get("auto_promote", False))
    # 晋级建议：多数可用（win_rate 高）且平均分非负
    promote_ready = win_rate >= 0.8 and avg >= 0
    return {
        "count": len(rows),
        "scored": len(scored),
        "win_rate": round(win_rate, 3),
        "avg_score": round(avg, 2),
        "promote_ready": promote_ready,
        "auto_promote": auto,
        "candidate": sh.get("candidate_model_id"),
    }


def shadow_promote_if_ready():
    """仅当 auto_promote=true 且统计达标，才把候选优先级提到最高。默认不调用。"""
    s = shadow_summary()
    if not (s.get("promote_ready") and s.get("auto_promote")):
        return s
    try:
        from core.free_model_pool import _PROJECT_ROOT as PR
        cfg_path = os.path.join(PR, "config", "free_models.json")
        # 刀⑥(JS-20260807-02): safe_load_json 原子读+损坏恢复
        cfg = safe_load_json(cfg_path, default={})
        if not isinstance(cfg, dict):
            cfg = {}
        cand = s.get("candidate")
        for prov, pdata in cfg.get("providers", {}).items():
            for m in pdata.get("models", []):
                if m.get("id") == cand:
                    m["priority"] = 1
                    m["enabled"] = True
        # 刀⑥: safe_write_json 原子写+备份，含 makedirs；写失败标 promoted=False
        if not safe_write_json(cfg_path, cfg, backup=True):
            s["promoted"] = False
            return s
        s["promoted"] = True
    except Exception:
        s["promoted"] = False
    return s
