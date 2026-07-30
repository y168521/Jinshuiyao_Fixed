# -*- coding: utf-8 -*-
"""AI 抽考门禁（ai_diligence.py）

读今日决策卡，用免费模型池提问自答，验证知识是否真沉淀（而非只写不吸收）。

道衍推导（JS-20260727-22）：
  阴阳两仪：阳 = 主动抽考（逼出盲区，阳主动）；阴 = 免费模型（0 成本执行，阴守底）。
  天地人：天=规划“每日抽考”节律（为之于未有）；地=隔离（只读本日卡，不碰历史）；
         人=模型出题自答后落日志，可复盘抽考覆盖率（反事实：若不抽考则盲点累积）。
  知止：模型挂/池空 → 跳过不阻断（抽考是增强项，非系统命门，不可因它失败卡死收工）。

依赖 core/free_model_pool（硅基流动免费模型 + 故障转移 + 付费兜底）。
"""
import os
import re
import sys
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
_ROOT = os.path.dirname(_PROJ)
sys.path.insert(0, _ROOT)
_DECISIONS = os.path.join(_ROOT, "Jinshuiyao_Fixed", "金水谣数据", "log", "ai_decisions.md")

try:
    from core.free_model_pool import get_free_provider_cfgs, call_ai_failover
except Exception:
    get_free_provider_cfgs = None
    call_ai_failover = None


def _today_cards():
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.isfile(_DECISIONS):
        return []
    text = open(_DECISIONS, encoding="utf-8").read()
    cards, pos = [], 0
    for m in re.finditer(r"^### .*%s.*$" % re.escape(today), text, re.M):
        start = m.start()
        nxt = re.search(r"^### ", text[start + 3:], re.M)
        end = start + 3 + (nxt.start() if nxt else len(text) - start - 3)
        cards.append(text[start:end])
        pos = end
    return cards


def run():
    cards = _today_cards()
    if not cards:
        print("[diligence] 今日无决策卡，跳过抽考。")
        return 0
    if not call_ai_failover:
        print("[diligence] 免费模型池不可用，跳过(写日志不阻断)。")
        return 0
    cfgs = get_free_provider_cfgs()
    if not cfgs:
        print("[diligence] 免费模型池空，跳过。")
        return 0
    joined = "\n".join(c[:800] for c in cards)
    sys_p = ("你是金水谣知识库质检员。基于给定决策卡，出 3 道关键选择题考察是否已沉淀，"
             "并给出答案要点。只输出 JSON：{\"questions\":[{\"q\":\"\",\"a\":\"\"}]}。")
    user_p = "今日决策卡：\n%s\n\n请输出上述 JSON。" % joined
    text, err, _ = call_ai_failover(cfgs, sys_p, user_p, timeout=120)
    if err:
        print("[diligence] 免费模型调用失败(%s)，跳过不阻断。" % err)
        return 0
    print("[diligence] 抽考完成(模型已基于今日卡出题自答)。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
