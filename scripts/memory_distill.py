# -*- coding: utf-8 -*-
"""记忆蒸馏（memory_distill.py）

把 >30 天的每日留痕日志（.workbuddy/memory/YYYY-MM-DD.md）按主题蒸馏进
长期记忆 MEMORY.md，再删除旧日log，避免日志无限膨胀又保留可查沉淀。

道衍推导（JS-20260727-22）：
  阴阳两仪：阳 = 持续记录（每天写留痕）；阴 = 定期蒸馏（压缩沉淀，防噪声淹没信号）。
  天地人三才：
    天 = 前瞻规划：定下“30 天蒸馏”节奏，为之于未有（垃圾不堆积）。
    地 = 执行隔离：只动 >30 天旧文件，近期日志绝不碰（隔）。
    人 = 复盘迭代：蒸馏后旧文件删除，但要点已进 MEMORY.md，可随时回溯（反事实自检）。
  知止：绝不蒸馏/删除今日及近 30 天日志，绝不误删 MEMORY.md 本身。

纯文件操作，0 API，0 积分。
"""
import os
import re
import sys
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
_ROOT = os.path.dirname(_PROJ)
_MEM_DIR = os.path.join(_ROOT, ".workbuddy", "memory")
_MEM_MD = os.path.join(_MEM_DIR, "MEMORY.md")
_RETENTION_DAYS = 30


def _collect_old():
    old = []
    if not os.path.isdir(_MEM_DIR):
        return old
    for fn in os.listdir(_MEM_DIR):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.md$", fn)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
        except Exception:
            continue
        if (datetime.now() - d).days > _RETENTION_DAYS:
            old.append((d, os.path.join(_MEM_DIR, fn)))
    return sorted(old, key=lambda x: x[0])


def _extract_themes(path):
    """提取 ## 标题 + 每条首行作为主题摘要（规则法，不调 API，省成本）。"""
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return []
    blocks, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                blocks.append(cur)
            cur = {"title": line[3:].strip(), "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur:
        blocks.append(cur)
    out = []
    for b in blocks:
        first = next((l.strip() for l in b["body"] if l.strip()), "")
        out.append("%s: %s" % (b["title"], first[:160]))
    return out


def distill():
    old = _collect_old()
    if not old:
        print("[memory_distill] 无 >30天 日log需蒸馏。")
        return 0
    chunks = []
    for d, p in old:
        themes = _extract_themes(p)
        if themes:
            chunks.append("\n### %s 蒸馏\n" % d.strftime("%Y-%m-%d")
                          + "\n".join("- %s" % t for t in themes))
    if chunks:
        os.makedirs(os.path.dirname(_MEM_MD), exist_ok=True)
        with open(_MEM_MD, "a", encoding="utf-8") as f:
            f.write("\n".join(chunks) + "\n")
    removed = 0
    for d, p in old:
        try:
            os.remove(p)
            removed += 1
        except Exception:
            pass
    print("[memory_distill] 蒸馏 %d 天日志，删除旧文件 %d 个。" % (len(chunks), removed))
    return 0


if __name__ == "__main__":
    sys.exit(distill())
