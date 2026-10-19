# -*- coding: utf-8 -*-
"""巡检聚合器（JS-20261020-02 · 主动发现体系的"巡检"层）

做什么：把项目里**已有但结果没人看**的检查器统一跑一遍，结果结构化落盘，
并按级别交给 `utils/alert_hub` 推送。

嵌入方式：
    - 每日：`core/infra/automation_mirror.py` 的 MIRROR_TASKS 加一行（15 分钟守卫窗口）
    - 手动：`python tools/inspect_all.py [--full] [--digest] [--quiet]`

设计约束（沿用项目铁律与方案文档 §八）：
    - **不新增检查逻辑**，只调度既有脚本（避免口径分裂）
    - 用 `sys.executable` 跑，**不写第 5 份 venv 探测逻辑**
    - 每项有超时，超时记 FAIL 而非挂死
    - 自身异常绝不静默：捕获后以 CRITICAL 告警
    - 只报"能变绿的项"（沿用 tools/health_watch.py:19-23 既有铁律）
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.alert_hub import (  # noqa: E402
    LEVEL_CRITICAL, LEVEL_WARN, alert, flush_digest,
)

LOG_DIR = os.path.join(ROOT, "金水谣数据", "log")
STATUS_FILE = os.path.join(LOG_DIR, "inspect_status.json")

# 快检清单（秒级，可每次更新后跑）
FAST_CHECKS = [
    {
        "name": "系统一致性",
        "script": "tools/check_consistency.py",
        "timeout": 60,
        "level": LEVEL_CRITICAL,
        "how_to_fix": "按报告 [ERR] 项修复；活文档改动后需拷回根镜像并校准 mtime",
    },
    {
        "name": "AST静态检查",
        "script": "tools/ast_checker.py",
        "args": ["--quick"],
        "timeout": 60,
        "level": LEVEL_WARN,
        "how_to_fix": "修 P0 项（P1/P2 仅提示，不阻断）",
    },
    {
        "name": "健康看门狗",
        "script": "tools/health_watch.py",
        "args": ["--quiet"],
        "timeout": 60,
        "level": LEVEL_WARN,
        "how_to_fix": "见 金水谣数据/log/健康告警.md 的『如何变绿』列",
    },
    {
        "name": "仓库卫生",
        "script": "tools/repo_hygiene.py",
        "timeout": 60,
        "level": LEVEL_WARN,
        "how_to_fix": "备份/临时文件不得入仓，用 git rm --cached",
    },
    {
        "name": "页面API契约",
        "script": "tools/page_api_lint.py",
        "timeout": 60,
        "level": LEVEL_WARN,
        "how_to_fix": "页面 fetch 的 API 必须在 router.py 注册",
    },
]

# 慢检清单（--full 时才跑，含分钟级）
FULL_CHECKS = [
    {
        "name": "冒烟测试",
        "script": "tools/smoke_test.py",
        "args": ["--quick"],
        "timeout": 300,
        "level": LEVEL_CRITICAL,
        "how_to_fix": "按 [!!] 项修复端到端链路",
    },
    {
        "name": "收工门禁",
        "script": "tools/closeout_gate.py",
        "timeout": 300,
        "level": LEVEL_WARN,
        "how_to_fix": "补留痕三件套 / 修未跟踪源码",
    },
]


def _extract_reason(output: str, script: str = "", limit: int = 3) -> str:
    """从检查器输出里抓失败原因（优先 [ERR]/FAIL/[!!] 行）。"""
    keys = ("[ERR]", "FAIL", "[!!]", "ERROR", "错误", "P0=", "扫描结果")
    hits = []
    for line in (output or "").splitlines():
        s = line.strip()
        if any(k in s for k in keys) and len(s) < 300:
            hits.append(s)
        if len(hits) >= limit:
            break
    if hits:
        return " ｜ ".join(hits)
    # 无输出时不能只写"（无输出）"——告警必须可行动 [useintact]。
    # 特例（**仅** health_watch）：它的结果写在 健康告警.md 里，不往 stdout 打印。
    # 不能对所有检查器都用这个兜底，否则会把别的检查项的原因错填成健康告警内容。
    if "health_watch" not in script:
        tail = [l.strip() for l in (output or "").splitlines() if l.strip()]
        return tail[-1][:300] if tail else "（检查器无输出，需人工查看对应日志）"
    try:
        p = os.path.join(LOG_DIR, "健康告警.md")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                rows = [l.strip() for l in f if l.strip().startswith("|")]
            rows = [r for r in rows if "---" not in r and "类别" not in r]
            if rows:
                return "健康告警：%s" % rows[-1][:260]
    except Exception as e:
        sys.stderr.write("[inspect] 读取健康告警失败: %s\n" % e)
    tail = [l.strip() for l in (output or "").splitlines() if l.strip()]
    return tail[-1][:300] if tail else "（检查器无输出，需人工查看对应日志）"


def run_one(chk: dict) -> dict:
    cmd = [sys.executable, os.path.join(ROOT, chk["script"])] + chk.get("args", [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=chk.get("timeout", 60))
        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = 124, "检查超时（>%ss）" % chk.get("timeout", 60)
    except Exception as e:
        rc, out = 1, "检查器自身异常: %s" % e
    dur = round(time.time() - t0, 2)
    ok = (rc == 0)
    return {
        "name": chk["name"],
        "script": chk["script"],
        "ok": ok,
        "rc": rc,
        "duration_s": dur,
        "reason": "" if ok else _extract_reason(out, chk.get("script", "")),
        "level": chk.get("level", LEVEL_WARN),
        "how_to_fix": chk.get("how_to_fix", ""),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    full = "--full" in argv
    digest = "--digest" in argv
    quiet = "--quiet" in argv

    if digest:
        n = flush_digest()
        if not quiet:
            print("[inspect] 每日告警汇总已弹出，共 %d 条" % n)
        return 0

    checks = FAST_CHECKS + (FULL_CHECKS if full else [])
    results = [run_one(c) for c in checks]

    failed = [r for r in results if not r["ok"]]
    status = {
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "full" if full else "fast",
        "total": len(results),
        "failed": len(failed),
        "all_ok": not failed,
        "checks": results,
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        import json
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write("[inspect] 状态落盘失败: %s\n" % e)

    for r in failed:
        alert(r["level"], r["name"], r["reason"], r["how_to_fix"],
              signature=r["reason"][:200])

    if not quiet:
        print("=" * 60)
        print("巡检聚合器 · %s（%d 项，失败 %d）" % (status["mode"], len(results), len(failed)))
        for r in results:
            print("  [%s] %-12s %5.1fs  %s" % (
                "OK" if r["ok"] else "!!", r["name"], r["duration_s"],
                "" if r["ok"] else r["reason"][:80]))
        print("状态文件: %s" % STATUS_FILE)
    return 0 if status["all_ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
