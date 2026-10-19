# -*- coding: utf-8 -*-
"""告警中枢（JS-20261020-02 · 主动发现体系的"出口"层）

为什么要有这个模块：
    此前项目"检查跑完了没人知道"——`tools/health_watch.py` 只把告警写进
    `金水谣数据/log/健康告警.md`，无推送、无展示、无 API，一条告警能挂 25 天。
    本模块把「发现 → 让人知道」这段补齐。

设计要点（外部依据见方案文档 §二）：
    - **指纹去重**：同一 `检查项 + 失败签名` 在冷却窗口内只打扰一次 [CloudOpsNow]
    - **分级路由**：CRITICAL 立即弹窗；WARN 进每日摘要（汇总后弹一次）；
      INFO 只落盘看板，不打扰 [useintact 分级矩阵]
    - **兜底必配**：被冷却/抑制的告警仍完整落盘，避免"降噪制造盲区" [flashlog]
    - **可行动**：每条告警带「检查项 + 失败原因 + 如何变绿」三要素

渠道：Windows 桌面弹窗（复用 `scripts/daily_fund_monitor.py:1770` 已验证的
PowerShell NotifyIcon 做法，此处抽成公共函数以避免第二份实现）。
Server酱微信通道见 `utils/notifier.py`（需 sendkey，当前未启用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "金水谣数据", "log")
ALERT_LOG = os.path.join(LOG_DIR, "alert_hub.jsonl")
STATE_FILE = os.path.join(LOG_DIR, "alert_hub_state.json")
DIGEST_FILE = os.path.join(LOG_DIR, "alert_digest.json")

LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_CRITICAL = "CRITICAL"

# 冷却窗口（秒）：同指纹在此窗口内不重复打扰（但**仍会落盘**，不制造盲区）
COOLDOWN = {
    LEVEL_CRITICAL: 15 * 60,
    LEVEL_WARN: 4 * 60 * 60,
    LEVEL_INFO: 24 * 60 * 60,
}

# 是否弹窗打扰
POPUP = {
    LEVEL_CRITICAL: True,
    LEVEL_WARN: False,   # WARN 走每日摘要，避免频繁打扰
    LEVEL_INFO: False,
}


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def fingerprint(check: str, signature: str) -> str:
    """告警指纹：同一根因的重复告警合并为一条。"""
    raw = "%s|%s" % (check, (signature or "")[:200])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _load_state() -> Dict[str, float]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: Dict[str, float]):
    _ensure_dir()
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 静默失败是本项目的头号敌人，状态写不进去必须能看见
        sys.stderr.write("[ALERT-HUB] 告警状态落盘失败: %s\n" % e)


def _append_log(record: dict):
    _ensure_dir()
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        sys.stderr.write("[ALERT-HUB] 告警日志写入失败: %s\n" % e)


def popup(title: str, message: str, timeout_ms: int = 5000) -> bool:
    """Windows 桌面弹窗（不阻塞）。

    复用 `scripts/daily_fund_monitor.py:1770` 已验证的 PowerShell NotifyIcon 做法。
    非 Windows 或 PowerShell 不可用时返回 False（调用方应降级到 stderr，不静默吞）。
    """
    if sys.platform != "win32":
        return False
    # PowerShell 里单引号需转义，且内容里的引号会破坏脚本，先清理
    def _esc(s):
        return str(s).replace("'", "''").replace("\r", " ").replace("\n", " ")[:240]

    ps = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "$notify = New-Object System.Windows.Forms.NotifyIcon\n"
        "$notify.Icon = [System.Drawing.SystemIcons]::Information\n"
        "$notify.BalloonTipTitle = '%s'\n"
        "$notify.BalloonTipText = '%s'\n"
        "$notify.Visible = $true\n"
        "$notify.ShowBalloonTip(%d)\n"
        "Start-Sleep -Milliseconds %d\n"
        "$notify.Dispose()\n"
    ) % (_esc(title), _esc(message), timeout_ms, timeout_ms + 500)
    try:
        subprocess.Popen(
            ["powershell.exe", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return True
    except Exception as e:
        sys.stderr.write("[ALERT-HUB] 弹窗发送失败: %s\n" % e)
        return False


def alert(level: str, check: str, message: str,
          how_to_fix: str = "", signature: str = "") -> dict:
    """发一条告警：落盘 → 冷却判定 → 按级别路由。

    Returns
    -------
    dict: {fingerprint, level, suppressed(是否被冷却抑制), popped(是否弹了窗)}
    """
    level = level if level in COOLDOWN else LEVEL_WARN
    fp = fingerprint(check, signature or message)
    now = time.time()
    state = _load_state()
    last = state.get(fp, 0)
    suppressed = (now - last) < COOLDOWN[level]

    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": now,
        "level": level,
        "check": check,
        "message": message[:500],
        "how_to_fix": how_to_fix[:300],
        "fingerprint": fp,
        "suppressed": suppressed,
    }
    _append_log(record)

    popped = False
    if not suppressed:
        state[fp] = now
        _save_state(state)
        if POPUP[level]:
            popped = popup("金水谣告警 · %s" % level,
                           "%s：%s%s" % (check, message[:120],
                                         (" | 处理：" + how_to_fix[:80]) if how_to_fix else ""))
        elif level == LEVEL_WARN:
            # WARN 不立即打扰，累计进每日摘要（兜底，防盲区）
            _append_digest(record)
    if not suppressed and level == LEVEL_CRITICAL and not popped:
        # 弹窗失败必须可见——否则 CRITICAL 等于没发
        sys.stderr.write("[ALERT-HUB][CRITICAL] %s: %s\n" % (check, message))

    record["popped"] = popped
    return record


def _append_digest(record: dict):
    """把 WARN 级告警累计进每日摘要（供 digest 弹一次汇总）。"""
    _ensure_dir()
    data = {"date": time.strftime("%Y-%m-%d"), "items": []}
    try:
        with open(DIGEST_FILE, "r", encoding="utf-8") as f:
            old = json.load(f)
        if old.get("date") == data["date"]:
            data = old
    except Exception:
        pass
    data["items"].append({
        "ts": record["ts"], "check": record["check"],
        "message": record["message"], "how_to_fix": record.get("how_to_fix", ""),
    })
    try:
        with open(DIGEST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write("[ALERT-HUB] 每日摘要写入失败: %s\n" % e)


def flush_digest() -> int:
    """把当日累计的 WARN 汇总弹一次（每日一次，不逐个打扰）。

    返回本次汇总的条数。
    """
    try:
        with open(DIGEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    items = data.get("items", [])
    if not items:
        return 0
    # 按检查项聚合，避免同一问题重复占版面
    grouped: Dict[str, int] = {}
    for it in items:
        grouped[it["check"]] = grouped.get(it["check"], 0) + 1
    summary = "；".join("%s×%d" % (k, v) for k, v in list(grouped.items())[:5])
    popup("金水谣今日告警汇总", "共 %d 条：%s" % (len(items), summary), timeout_ms=8000)
    # 弹完归档，避免第二天重复
    try:
        os.replace(DIGEST_FILE, DIGEST_FILE + "." + data.get("date", "x") + ".sent")
    except Exception:
        pass
    return len(items)


def main(argv=None) -> int:
    """命令行入口（供 .ps1 / .bat 调用，避免各处各写一份弹窗代码）。

    用法：
        python utils/alert_hub.py CRITICAL "自动同步" "缺留痕已跳过提交" "补三件套登记"
        python utils/alert_hub.py --digest
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    if argv[0] == "--digest":
        n = flush_digest()
        print("已汇总弹出 %d 条告警" % n)
        return 0
    level = argv[0]
    check = argv[1] if len(argv) > 1 else "未命名检查"
    message = argv[2] if len(argv) > 2 else ""
    how = argv[3] if len(argv) > 3 else ""
    r = alert(level, check, message, how)
    print("level=%s check=%s suppressed=%s popped=%s"
          % (r["level"], r["check"], r["suppressed"], r.get("popped")))
    return 0


def recent(limit: int = 50, level: Optional[str] = None) -> List[dict]:
    """读取最近告警（供看板/API 使用）。"""
    if not os.path.exists(ALERT_LOG):
        return []
    out: List[dict] = []
    try:
        with open(ALERT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if level and r.get("level") != level:
                    continue
                out.append(r)
    except Exception:
        return []
    return out[-limit:]
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
