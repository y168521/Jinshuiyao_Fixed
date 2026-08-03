# -*- coding: utf-8 -*-
"""金水谣 · 审查报告生成器

合并 ruff / semgrep / AST / AI语义 / 测试 6步输出，生成 P0-P3 分级审查报告（JSON + Markdown）。

用法：
  python tools/review_report.py --merge-all                    # 合并所有步骤输出
  python tools/review_report.py --ruff result.json             # 单步
  python tools/review_report.py --ast ast_result.json          # 单步
  python tools/review_report.py --quick                        # 快速模式（仅 ruff + AST）
"""
import json
import os
import sys
import time
import argparse
import subprocess

# ─── 项目根 ───
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 审查数据目录 ───
_REVIEW_DATA_DIR = os.path.join(_PROJECT_ROOT, "金水谣数据", "review")

# ─── 优先级 emoji ───
_SEVERITY_EMOJI = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢", "P4": "⚪"}
_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}

# Windows GBK 控制台兜底：子进程输出统一按 UTF-8 解码（text=True 默认 GBK 会崩 0x80）
_SUB = dict(text=True, encoding="utf-8", errors="replace")


def run_ruff_check(files=None, json_output=True, whole=False):
    """Step 1: ruff 快速 lint。

    whole=True（full 模式）→ 整仓扫描；
    files 指定 → 只查指定文件（增量审查，pre-commit/CI/手动指定时用）；
    files=None 且非 whole（quick 例行/启动后台）→ 跳过全文件存量噪音，避免假红灯。
    """
    if files is None and not whole:
        return {"step": "ruff", "duration_ms": 0, "issues": [],
                "note": "例行模式跳过全文件ruff（避免存量P1噪音假红灯）"}
    config = os.path.join(_PROJECT_ROOT, "pyproject.toml")
    cmd = ["ruff", "check", _PROJECT_ROOT, "--config", config]
    if json_output:
        cmd.append("--output-format=json")

    # 只检查最近修改的文件（快速模式）；ruff 仅处理 .py，跳过 html/js/yml 等
    if files:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return {"step": "ruff", "duration_ms": 0, "issues": []}
        cmd = ["ruff", "check"] + py_files + ["--config", config]
        if json_output:
            cmd.append("--output-format=json")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, **_SUB,
                                cwd=os.path.dirname(_PROJECT_ROOT))
        if json_output:
            try:
                data = json.loads(result.stdout)
                issues = []
                for item in data:
                    sev = classify_ruff_severity(item.get("code", ""))
                    issues.append({
                        "step": "ruff",
                        "rule": item.get("code", ""),
                        "file": item.get("filename", ""),
                        "line": item.get("location", {}).get("row"),
                        "message": item.get("message", ""),
                        "severity": sev,
                        "category": "format",
                    })
                return {"step": "ruff", "duration_ms": 0, "issues": issues}
            except json.JSONDecodeError:
                return {"step": "ruff", "duration_ms": 0, "issues": []}
        return {"step": "ruff", "duration_ms": 0, "raw": result.stdout}
    except FileNotFoundError:
        return {"step": "ruff", "duration_ms": 0, "issues": [], "error": "ruff not installed"}
    except Exception as e:
        return {"step": "ruff", "duration_ms": 0, "issues": [], "error": str(e)}


def classify_ruff_severity(code):
    """根据 ruff 规则码分类优先级"""
    # 安全类
    if code.startswith("S"):
        if code in ("S101", "S108", "S301", "S506", "S602"):
            return "P0" if code in ("S602",) else "P1"
        return "P2"
    # 未用 import / 重复 import
    if code in ("F401", "F811", "F403"):
        return "P1"
    # import 排序 / 行末空格
    if code in ("I001", "W291", "W292"):
        return "P3"
    # 命名
    if code.startswith("N"):
        return "P2"
    # 复杂度
    if code == "C901":
        return "P1"
    # 其他 E/W
    if code.startswith("E") or code.startswith("W"):
        return "P2"
    # 其他 F
    if code.startswith("F"):
        return "P1"
    return "P2"


def run_semgrep_check(files=None, whole=False):
    """Step 2: semgrep 深度安全扫描（Layer 2，设计文档要求）。
    容错：未安装/超时/离线规则下载失败均跳过，不阻断 Pipeline（ruff S 规则已覆盖基础安全）。

    whole=True（full 模式）→ 整仓扫描；
    files 指定 → 只扫指定文件（pre-commit/CI/手动）；
    files=None 且非 whole（quick 例行/启动后台）→ 跳过，避免每次全仓 27s。
    """
    if not files and not whole:
        return {"step": "semgrep", "duration_ms": 0, "issues": [],
                "note": "例行模式跳过semgrep（整仓27s，仅full/指定文件时跑）"}
    targets = files if files else [_PROJECT_ROOT]
    cmd = ["semgrep", "--config=auto", "--json", "--timeout=60",
           "--exclude=AI代码助手(DeepSeek备用)"] + targets
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=90, **_SUB,
                                cwd=_PROJECT_ROOT)
        if not result.stdout.strip():
            return {"step": "semgrep", "duration_ms": 0, "issues": [],
                    "error": "no output（可能规则未下载/离线）"}
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"step": "semgrep", "duration_ms": 0, "issues": [], "error": "json 解析失败"}
        issues = []
        for finding in data.get("results", []):
            path = finding.get("path", "")
            if _PROJECT_ROOT in path:
                path = path[len(_PROJECT_ROOT) + 1:]
            issues.append({
                "step": "semgrep",
                "rule": finding.get("check_id", ""),
                "file": path,
                "line": finding.get("start", {}).get("line"),
                "message": finding.get("extra", {}).get("message", ""),
                "severity": classify_semgrep_severity(finding),
                "category": "security",
            })
        return {"step": "semgrep", "duration_ms": 0, "issues": issues}
    except FileNotFoundError:
        return {"step": "semgrep", "duration_ms": 0, "issues": [],
                "error": "semgrep 未安装（可选 Layer 2，CI 已独立覆盖）"}
    except subprocess.TimeoutExpired:
        return {"step": "semgrep", "duration_ms": 0, "issues": [], "error": "超时跳过"}
    except Exception as e:
        return {"step": "semgrep", "duration_ms": 0, "issues": [], "error": str(e)[:120]}


def classify_semgrep_severity(finding):
    """semgrep 结果按严重性/规则分类优先级"""
    sev = finding.get("extra", {}).get("severity", "").upper()
    if sev == "ERROR":
        return "P0"
    if sev == "WARNING":
        return "P1"
    if sev == "INFO":
        return "P2"
    check_id = finding.get("check_id", "").lower()
    if any(k in check_id for k in ("hardcoded", "ssrf", "path-traversal", "sql-injection")):
        return "P0"
    return "P2"


def run_ast_check(files=None, severity=None):
    """Step 4: AST 自定义扫描"""
    checker = os.path.join(_PROJECT_ROOT, "tools", "ast_checker.py")
    cmd = [sys.executable, checker]
    if severity:
        cmd.append(f"--severity={severity}")
    if files:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return {"step": "ast_custom", "duration_ms": 0, "issues": []}
        cmd.extend(py_files)
    else:
        cmd.append("--quick")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30, **_SUB,
                                cwd=_PROJECT_ROOT)
        issues = []
        for line in result.stdout.splitlines():
            # 格式: [P0] AST-001:xxx  file:line  msg...
            match = None
            # 尝试匹配带行号格式
            if "[" in line and "AST-" in line:
                sev_match = re.search(r'\[(P\d+)\]', line)
                rule_match = re.search(r'AST-\d+', line)
                if sev_match and rule_match:
                    issues.append({
                        "step": "ast_custom",
                        "rule": rule_match.group(),
                        "severity": sev_match.group(1),
                        "file": "",
                        "line": None,
                        "message": line.strip(),
                        "category": "project_specific",
                    })
        return {"step": "ast_custom", "duration_ms": 0, "issues": issues}
    except Exception as e:
        return {"step": "ast_custom", "duration_ms": 0, "issues": [], "error": str(e)}


def run_smoke_test():
    """Step 5: 冒烟测试"""
    smoke = os.path.join(_PROJECT_ROOT, "tools", "smoke_test.py")
    cmd = [sys.executable, smoke, "--quick"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60, **_SUB,
                                cwd=_PROJECT_ROOT)
        # 检查是否全绿
        passed = "7/7" in result.stdout or "all green" in result.stdout.lower()
        return {
            "step": "smoke_test",
            "duration_ms": 0,
            "result": "PASS" if passed else "FAIL",
            "output": result.stdout[-200:] if len(result.stdout) > 200 else result.stdout,
        }
    except Exception as e:
        return {"step": "smoke_test", "duration_ms": 0, "result": "ERROR", "error": str(e)}


def run_wrapup_check():
    """Step 补充: 收工自检"""
    wrapup = os.path.join(_PROJECT_ROOT, "tools", "wrapup_check.py")
    cmd = [sys.executable, wrapup]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120, **_SUB,
                                cwd=_PROJECT_ROOT)
        # 检查是否全绿
        passed = "全绿" in result.stdout or "all green" in result.stdout.lower()
        return {
            "step": "wrapup_check",
            "duration_ms": 0,
            "result": "PASS" if passed else "FAIL",
            "output": result.stdout[-300:] if len(result.stdout) > 300 else result.stdout,
        }
    except Exception as e:
        return {"step": "wrapup_check", "duration_ms": 0, "result": "ERROR", "error": str(e)}


def generate_report(steps_data, review_id=None):
    """合并所有步骤数据，生成最终报告"""
    if not review_id:
        review_id = f"R-{time.strftime('%Y%m%d')}-{int(time.time()) % 10000:04d}"

    # 合并所有 issues
    all_issues = []
    for step in steps_data:
        issues = step.get("issues", [])
        all_issues.extend(issues)

    # 按优先级排序
    all_issues.sort(key=lambda x: _SEVERITY_ORDER.get(x.get("severity", "P3"), 3))

    # 统计
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for i in all_issues:
        counts[i.get("severity", "P3")] = counts.get(i.get("severity", "P3"), 0) + 1

    # 健康评分（100 - P0*10 - P1*5 - P2*2 - P3*1）
    health_score = max(0, 100 - counts.get("P0", 0) * 10 - counts.get("P1", 0) * 5
                       - counts.get("P2", 0) * 2 - counts.get("P3", 0) * 1)

    # 建议
    if counts["P0"] > 0:
        recommendation = "⚠️ 需修复 P0 后再合并"
    elif counts["P1"] > 3:
        recommendation = "🟠 P1 较多，建议优先处理"
    elif counts["P1"] > 0:
        recommendation = "🟡 有少量 P1，建议 24h 内补修"
    else:
        recommendation = "✅ 审查通过，可以合并"

    # 测试结果
    test_results = {}
    for step in steps_data:
        if step.get("result"):
            test_results[step["step"]] = step["result"]

    report = {
        "review_id": review_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "steps": steps_data,
        "summary": {
            "total_issues": len(all_issues),
            "p0_count": counts["P0"],
            "p1_count": counts["P1"],
            "p2_count": counts["P2"],
            "p3_count": counts["P3"],
            "health_score": health_score,
            "recommendation": recommendation,
            "test_results": test_results,
        },
        "issues": all_issues,
    }

    return report


def format_markdown_report(report):
    """将报告格式化为 Markdown"""
    lines = []
    lines.append(f"## 📋 代码审查报告 {report['review_id']}")
    lines.append(f"时间: {report['timestamp']}")
    lines.append(f"健康评分: **{report['summary']['health_score']}/100**")
    lines.append(f"建议: {report['summary']['recommendation']}")
    lines.append("")
    lines.append(f"P0阻断: {report['summary']['p0_count']} | P1高优: {report['summary']['p1_count']} "
                 f"| P2建议: {report['summary']['p2_count']} | P3信息: {report['summary']['p3_count']}")
    lines.append("")

    # P0-P3 分组
    for sev in ["P0", "P1", "P2", "P3"]:
        issues = [i for i in report["issues"] if i.get("severity") == sev]
        if not issues:
            continue
        emoji = _SEVERITY_EMOJI.get(sev, "⚪")
        label = {"P0": "阻断(必须修复)", "P1": "高优(24h内)", "P2": "改善建议", "P3": "信息提示"}.get(sev, "")
        lines.append(f"### {emoji} {sev} {label}")
        lines.append("| # | 文件 | 行 | 规则 | 描述 |")
        lines.append("|---|------|---|------|------|")
        for idx, issue in enumerate(issues, 1):
            file_short = issue.get("file", "").replace(_PROJECT_ROOT + os.sep, "")
            lines.append(f"| {idx} | {file_short} | {issue.get('line', '?')} | "
                         f"{issue.get('rule', '?')} | {issue.get('message', '')[:60]} |")
        lines.append("")

    # 测试结果
    test_results = report["summary"].get("test_results", {})
    if test_results:
        lines.append("### ✅ 测试结果")
        for step, result in test_results.items():
            emoji = "✅" if result == "PASS" else "❌"
            lines.append(f"- {emoji} {step}: {result}")
        lines.append("")

    lines.append(f"### 📊 总评")
    lines.append(f"- 阻断数: {report['summary']['p0_count']} → {report['summary']['recommendation']}")
    lines.append(f"- 健康评分: {report['summary']['health_score']}")

    return "\n".join(lines)


def save_report(report):
    """保存报告到审查数据目录"""
    os.makedirs(_REVIEW_DATA_DIR, exist_ok=True)

    # JSON 报告
    report_file = os.path.join(_REVIEW_DATA_DIR, f"review_{report['review_id']}.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    md_file = os.path.join(_REVIEW_DATA_DIR, f"review_{report['review_id']}.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(format_markdown_report(report))

    # 追加到历史
    history_file = os.path.join(_REVIEW_DATA_DIR, "review_history.jsonl")
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "review_id": report["review_id"],
            "timestamp": report["timestamp"],
            "p0": report["summary"]["p0_count"],
            "p1": report["summary"]["p1_count"],
            "p2": report["summary"]["p2_count"],
            "p3": report["summary"]["p3_count"],
            "health_score": report["summary"]["health_score"],
            "recommendation": report["summary"]["recommendation"],
        }, ensure_ascii=False) + "\n")

    return report_file, md_file


def run_quick_review(files=None):
    """快速审查：ruff + AST + smoke（约 5s）

    无 files（启动/后台例行）时：ruff/semgrep 跳过全文件存量问题（P1 存量噪音
    会造成每次假红灯），只跑 AST + smoke 轻量体检，秒级完成；
    有 files（pre-commit/CI/手动指定）时：ruff + semgrep + AST + smoke 全量增量审查。
    """
    import re as _re  # noqa: already imported at top

    steps = []

    # Step 1: ruff（无 files 时跳过——全文件存量 P1 噪音会淹没增量信号，假红灯）
    ruff_result = run_ruff_check(files=files)
    steps.append(ruff_result)

    # Step 2: semgrep 深度安全（Layer 2，容错跳过；无 files 时跳过全仓 27s）
    steps.append(run_semgrep_check(files=files))

    # Step 4: AST
    ast_result = run_ast_check(files=files, severity="P0")
    steps.append(ast_result)

    # Step 5: smoke test
    smoke_result = run_smoke_test()
    steps.append(smoke_result)

    report = generate_report(steps)
    return report


def run_full_review(files=None, always_ai=False, no_ai=False, ai_budget=None):
    """完整审查：ruff + AST + smoke + wrapup（约 3min）"""
    steps = []

    # Step 1: ruff
    print("[review_report] Step 1: ruff lint ...")
    steps.append(run_ruff_check(files=files, whole=True))

    # Step 2: semgrep 深度安全（Layer 2，容错跳过）
    print("[review_report] Step 2: semgrep 深度扫描 ...")
    steps.append(run_semgrep_check(files=files, whole=True))

    # Step 4: AST
    print("[review_report] Step 4: AST 自定义扫描 ...")
    steps.append(run_ast_check(files=files))

    # Step 5: smoke test
    print("[review_report] Step 5: 冒烟测试 ...")
    steps.append(run_smoke_test())

    # Step 补充: wrapup check
    print("[review_report] 收工自检 ...")
    steps.append(run_wrapup_check())

    # Step 6: AI 语义审查（可选，需要 API Key）
    print("[review_report] Step 6: AI 语义审查（需 DeepSeek Key）...")
    try:
        ai_agent = os.path.join(_PROJECT_ROOT, "tools", "ai_review_agent.py")
        # 透传省费门禁开关
        extra = []
        if always_ai:
            extra.append("--always-ai")
        if no_ai:
            extra.append("--no-ai")
        if ai_budget is not None:
            extra.append(f"--ai-budget={ai_budget}")
        if files:
            cmd = [sys.executable, ai_agent, "--files", ",".join(files), "--json"] + extra
        else:
            cmd = [sys.executable, ai_agent, "--diff-only", "--json"] + extra
        result = subprocess.run(cmd, capture_output=True, timeout=120, **_SUB,
                                cwd=_PROJECT_ROOT)
        if result.returncode == 0:
            ai_data = json.loads(result.stdout)
            steps.append(ai_data)
        else:
            steps.append({"step": "ai_semantic", "issues": [], "error": result.stderr[:200]})
    except Exception as e:
        steps.append({"step": "ai_semantic", "issues": [], "error": str(e)[:200]})

    report = generate_report(steps)
    report_file, md_file = save_report(report)
    print(f"[review_report] 报告已保存: {report_file}")
    print(f"[review_report] Markdown: {md_file}")
    return report


import re  # noqa: E402 — needed by run_ast_check


def main():
    parser = argparse.ArgumentParser(description="金水谣审查报告生成器")
    parser.add_argument("--merge-all", action="store_true", help="完整审查全流程")
    parser.add_argument("--quick", action="store_true", help="快速模式（ruff+AST+smoke）")
    parser.add_argument("--files", help="指定审查文件（逗号分隔）")
    parser.add_argument("--ruff", help="ruff 结果 JSON 文件路径")
    parser.add_argument("--ast", help="AST 结果 JSON 文件路径")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    parser.add_argument("--always-ai", action="store_true", help="强制对所有文件调用 DeepSeek（忽略省费门禁）")
    parser.add_argument("--no-ai", action="store_true", help="纯本地审查，绝不调用 DeepSeek（零 API 费用）")
    parser.add_argument("--ai-budget", type=int, default=None, help="单次运行最多调用 DeepSeek 次数（0=禁用）")
    args = parser.parse_args()

    if args.merge_all:
        report = run_full_review(files=args.files.split(",") if args.files else None,
                                 always_ai=args.always_ai, no_ai=args.no_ai,
                                 ai_budget=args.ai_budget)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_markdown_report(report))
    elif args.quick:
        report = run_quick_review(files=args.files.split(",") if args.files else None)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_markdown_report(report))
    elif args.ruff or args.ast:
        # 单步模式
        steps = []
        if args.ruff:
            with open(args.ruff, "r") as f:
                steps.append(json.load(f))
        if args.ast:
            with open(args.ast, "r") as f:
                steps.append(json.load(f))
        report = generate_report(steps)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        # 默认快速模式
        report = run_quick_review()
        print(format_markdown_report(report))

    return report


if __name__ == "__main__":
    main()
