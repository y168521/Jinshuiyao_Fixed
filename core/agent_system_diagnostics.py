# -*- coding: utf-8 -*-
"""金水谣本地助手 · 系统诊断工具箱

让 agent 能主动检查：
  - 服务健康 /health
  - 收工门禁 closeout_gate.py
  - 自动化镜像运行状态 automation_mirror.jsonl
  - 定时调度器状态
"""
import json
import os
import subprocess
import urllib.request
from datetime import datetime
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(_PROJECT_ROOT, *parts)


def check_health() -> str:
    """调用本机 /health 检查服务状态。"""
    try:
        req = urllib.request.Request("http://127.0.0.1:18888/health", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return f"【服务健康检查】\n  HTTP状态: {resp.status}\n  响应: {body[:200]}"
    except Exception as e:
        return f"【服务健康检查】\n  ❌ 异常: {e}\n  服务可能未启动或 18888 端口不可用。"


def check_closeout() -> str:
    """运行收工门禁 closeout_gate.py。"""
    script = _path("scripts", "closeout_gate.py")
    if not os.path.isfile(script):
        return "【收工门禁】找不到脚本 closeout_gate.py。"
    try:
        proc = subprocess.run(
            [_path("..", "venv_314", "Scripts", "python.exe"), script],
            cwd=_path(".."),
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = proc.returncode == 0
        icon = "✅" if ok else "❌"
        out = proc.stdout or proc.stderr or "(无输出)"
        return f"【收工门禁】\n  {icon} 退出码: {proc.returncode}\n  输出:\n{out[:800]}"
    except Exception as e:
        return f"【收工门禁】运行失败: {e}"


def check_automation_mirror() -> str:
    """读取自动化镜像日志，汇总最近运行状态。"""
    logp = _path("金水谣数据", "log", "automation_mirror.jsonl")
    if not os.path.isfile(logp):
        return "【自动化镜像】暂无运行日志（服务重启后才会开始记录）。"
    try:
        with open(logp, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return "【自动化镜像】日志文件为空。"
        recent = [json.loads(l) for l in lines[-20:]]
        summary = {}
        for r in recent:
            name = r.get("name", "unknown")
            rc = r.get("rc", -1)
            summary[name] = summary.get(name, {"ok": 0, "fail": 0, "last": ""})
            if rc == 0:
                summary[name]["ok"] += 1
            else:
                summary[name]["fail"] += 1
            summary[name]["last"] = r.get("ts", "")
        lines = ["【自动化镜像最近状态】"]
        for name, s in summary.items():
            status = "✅" if s["fail"] == 0 else "⚠️"
            lines.append(f"  {status} {name}: 成功{s['ok']}次 / 失败{s['fail']}次 / 上次{s['last']}")
        return "\n".join(lines)
    except Exception as e:
        return f"【自动化镜像】读取日志失败: {e}"


def read_free_model_status() -> dict:
    """读取免费模型探活状态文件（运行时生成，可能不存在）。"""
    p = _path("金水谣数据", "free_model_status.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _self_heal_free_models() -> str:
    """触发免费模型探活脚本重新检测并刷新状态文件（低风险自愈，不改业务数据）。"""
    script = _path("scripts", "free_model_health_check.py")
    py = _path("..", "venv_314", "Scripts", "python.exe")
    if not os.path.isfile(script):
        return "  🔧 自愈跳过：找不到 free_model_health_check.py"
    try:
        proc = subprocess.run([py, script], cwd=_path(".."),
                              capture_output=True, text=True, timeout=90)
        out = (proc.stdout or proc.stderr or "").strip()
        return (f"  🔧 已触发免费模型重新探活（退出码 {proc.returncode}）：\n"
                f"{out[:400]}")
    except Exception as e:
        return f"  🔧 自愈触发失败：{e}"


def run_diagnostics(auto_fix: bool = False) -> str:
    """全量系统诊断；auto_fix=True 时对低风险项自动自愈（如免费模型重新探活）。

    闭环边界（道衍·知止）：只自愈"触发已有脚本刷新状态"这类低风险项；
    高风险项（如重启自身服务）不在此处理，交由看门狗/本机操作。
    """
    tag = " · 含自动修复" if auto_fix else ""
    lines = [f"【系统诊断{tag}】"]
    issues, fixed = [], []

    health = check_health()
    lines.append(health)
    if "❌" in health:
        issues.append("服务健康检查未通过（18888 端口可能未监听）")

    closeout = check_closeout()
    lines.append("\n" + closeout)
    if "❌" in closeout:
        issues.append("收工门禁未通过（需补登总索引/决策卡，详见上方）")

    mirror = check_automation_mirror()
    lines.append("\n" + mirror)

    fm = read_free_model_status()
    if fm:
        down = [m for m, s in fm.items()
                if isinstance(s, dict) and not s.get("healthy", True)]
        lines.append(f"\n【免费模型状态】共 {len(fm)} 个，异常 {len(down)} 个")
        for m in down:
            lines.append(f"  ⚠️ {m}: {fm[m].get('error', 'unknown')}")
        if down:
            issues.append(f"免费模型异常 {len(down)} 个：{', '.join(down)}")
            if auto_fix:
                lines.append("\n" + _self_heal_free_models())
                fixed.append(f"免费模型已重新探活并更新状态文件（{len(down)} 个）")
    else:
        lines.append("\n【免费模型状态】暂无状态文件（尚未探活）")
        if auto_fix:
            lines.append("\n" + _self_heal_free_models())
            fixed.append("已触发首次免费模型探活")

    lines.append("\n【结论】")
    if not issues:
        lines.append("  ✅ 未发现需处理的问题。")
    else:
        lines.append(f"  ⚠️ 发现 {len(issues)} 项问题：")
        for i in issues:
            lines.append(f"    - {i}")
    if fixed:
        lines.append(f"  🔧 已自动修复 {len(fixed)} 项：")
        for f in fixed:
            lines.append(f"    + {f}")
    if issues and not fixed:
        lines.append("  💡 上述问题需人工处理或本机操作（如重启服务/看门狗已接管）。")
    return "\n".join(lines)


def run_diagnostic(intent: str) -> str:
    """兼容旧入口：按关键词做对应诊断（相当于 auto_fix=False 全量）。"""
    return run_diagnostics(auto_fix=False)
