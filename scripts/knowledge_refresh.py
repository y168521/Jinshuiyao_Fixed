# -*- coding: utf-8 -*-
"""联网新知注入（knowledge_refresh.py）

抓 GitHub trending + 用免费模型总结对金水谣知识库有增量价值的要点，落库。

道衍推导（JS-20260727-22）：
  流水不腐：开放系统负熵，定期破闭塞（阴守底、阳主动联网）。
  阴阳：阳=联网抓取（破信息茧房）；阴=免费模型总结（0 成本）。
  天地人：天=规划“每周破闭塞”节律；地=隔离（落库 jsonl，不污染知识卡）；
         人=落库后可复盘趋势命中率（反事实：若不破闭塞则认知滞后）。
  知止：抓取失败/模型挂 → 仍落库标记错误，不崩；绝不因联网失败改写业务文件。

依赖 core/free_model_pool（硅基流动免费模型 + 故障转移 + 付费兜底）。
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
_ROOT = os.path.dirname(_PROJ)
sys.path.insert(0, _ROOT)
_OUT = os.path.join(_ROOT, "Jinshuiyao_Fixed", "金水谣数据", "knowledge_refresh.jsonl")
_TRENDING = "https://github.com/trending"

try:
    from core.free_model_pool import get_free_provider_cfgs, call_ai_failover
except Exception:
    get_free_provider_cfgs = None
    call_ai_failover = None


def _fetch_trending():
    try:
        req = urllib.request.Request(_TRENDING, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "ignore")
        repos = re.findall(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', html)
        return repos[:15]
    except Exception as e:
        return ["FETCH_ERR:%s" % e]


def run():
    repos = _fetch_trending()
    summary = {"ts": datetime.now().isoformat(), "repos": repos, "insight": ""}
    if call_ai_failover:
        cfgs = get_free_provider_cfgs()
        if cfgs and repos and not repos[0].startswith("FETCH_ERR"):
            joined = "\n".join(repos)
            sys_p = ("你是技术趋势分析师。基于以下 GitHub 热门仓库，"
                     "提炼 3 条对'个人AI知识库/自动化'有增量价值的要点。")
            user_p = "热门仓库：\n%s\n\n输出 JSON：{\"insights\":[string]}" % joined
            text, err, _ = call_ai_failover(cfgs, sys_p, user_p, timeout=120)
            if not err:
                summary["insight"] = text
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    with open(_OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    ok = len([r for r in repos if not r.startswith("FETCH_ERR")])
    print("[knowledge_refresh] 抓取 %d 仓库，已落库。" % ok)
    return 0


if __name__ == "__main__":
    sys.exit(run())
