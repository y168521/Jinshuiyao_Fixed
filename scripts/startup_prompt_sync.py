# -*- coding: utf-8 -*-
"""启动提示词同步校验（startup_prompt_sync.py）

检查 启动提示词.txt 含全部关键铁律标记，且与 ai_decisions.md / 提示词库.html
的同步点一致（启动提示词不应落后于知识库最新改动）。

道衍推导（JS-20260727-22）：
  知止：启动提示词是系统脊梁，失同步 = 系统失锚（阴阳失衡，阴失阳随）。
  天地人：天=规划三层闭环同步（提示词↔知识卡↔启动提示词）；地=文件比对隔离；
         人=校验失败即告警，逼出滞后（复盘）。
纯文件操作，0 API，0 积分。退出码：0=通过 1=缺标记/滞后 2=文件缺失。
"""
import os
import sys
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
_ROOT = os.path.dirname(_PROJ)
_PROMPT = os.path.join(_ROOT, "启动提示词.txt")
_DECISIONS = os.path.join(_ROOT, "Jinshuiyao_Fixed", "金水谣数据", "log", "ai_decisions.md")
_LIB = os.path.join(_ROOT, "金水谣助手提示词库.html")

_REQUIRED = ["安全删除铁律", "道衍脊梁", "同频", "写入纪律", "自动化镜像"]


def check():
    if not os.path.isfile(_PROMPT):
        print("[sync] 缺失 启动提示词.txt")
        return 2
    text = open(_PROMPT, encoding="utf-8").read()
    missing = [k for k in _REQUIRED if k not in text]
    if missing:
        print("[sync] 启动提示词.txt 缺关键铁律: %s" % missing)
        return 1
    # mtime 一致性：提示词库.html / ai_decisions.md 不应比启动提示词新（否则提示词滞后）
    pt = os.path.getmtime(_PROMPT)
    lag = []
    for name, p in (("提示词库.html", _LIB), ("ai_decisions.md", _DECISIONS)):
        if os.path.isfile(p) and os.path.getmtime(p) > pt + 60:
            lag.append(name)
    if lag:
        print("[sync] 以下文件比启动提示词新(可能提示词滞后): %s" % lag)
        return 1
    print("[sync] 启动提示词同步校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(check())
