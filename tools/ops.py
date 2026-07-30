#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 统一运维入口（ops.py）
===============================
合并 safe_cleanup / auto_backup / data_backup / data_restore /
session_coordinator / kb_append / doctor / tag_validator 为单一入口。

新增高阶操作（闭环三件套）：
  py -3.14 tools/ops.py --start           # 开工令：体检 + 议程 + 索引新鲜度 + 最近工作
  py -3.14 tools/ops.py --close           # 收工令：digest→sync→extract→round→commit提醒
  py -3.14 tools/ops.py --status [file]   # 开工雷达：环境体检 + 文件知识索引查询
  py -3.14 tools/ops.py --round            # 全场扫描：doctor→sync-ai→extract-patterns→audit→index→agenda
  py -3.14 tools/ops.py --digest           # 经验提取器：交互式提取本轮经验→经验收集箱

用法：
  py -3.14 tools/ops.py --clean           # 安全清理（原 safe_cleanup）
  py -3.14 tools/ops.py --backup          # 启动快照（原 auto_backup）
  py -3.14 tools/ops.py --data-backup     # 数据层备份（原 data_backup）
  py -3.14 tools/ops.py --data-restore    # 数据层恢复（原 data_restore）
  py -3.14 tools/ops.py --lease           # 会话租约（原 session_coordinator）
  py -3.14 tools/ops.py --doctor          # 体检（原 doctor.py）
  py -3.14 tools/ops.py --append          # KB 仅追加（原 kb_append）
  py -3.14 tools/ops.py --tag             # 标签校验（原 tag_validator）
  py -3.14 tools/ops.py --sync-ai         # 同步 AI 决策卡（原 sync_ai_decisions）
  py -3.14 tools/ops.py --extract-patterns # 抽取模式库（原 extract_patterns）
  py -3.14 tools/ops.py --digest           # 经验提取器（交互式追加到经验收集箱）
各子命令透传额外参数。
旧入口脚本保留作为兼容别名，但新调用请统一走 ops.py。
"""
import sys, os, subprocess, json

# GBK 安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
MODEL = os.path.dirname(ROOT)
SCRIPTS = os.path.join(ROOT, "scripts")

SCRIPT_MAP = {
    "clean":        (os.path.join(SCRIPTS, "safe_cleanup.py"),       "安全清理"),
    "backup":       (os.path.join(BASE, "auto_backup.py"),           "启动快照"),
    "data-backup":  (os.path.join(SCRIPTS, "data_backup.py"),        "数据层备份"),
    "data-restore": (os.path.join(SCRIPTS, "data_restore.py"),       "数据层恢复"),
    "lease":        (os.path.join(SCRIPTS, "session_coordinator.py"),"会话租约"),
    "doctor":       (os.path.join(BASE, "doctor.py"),                "体检修复"),
    "append":       (os.path.join(SCRIPTS, "kb_append.py"),          "KB 仅追加"),
    "tag":           (os.path.join(BASE, "tag_validator.py"),          "标签校验"),
    "sync-ai":       (os.path.join(BASE, "sync_ai_decisions.py"),      "同步 AI 决策卡"),
    "extract-patterns": (os.path.join(BASE, "extract_patterns.py"),    "抽取模式库"),
}

def run_script(script_path, label, extra_args):
    cmd = [sys.executable, script_path] + extra_args
    print(f"[ops] {'='*50}")
    print(f"[ops] 执行: {label}")
    print(f"[ops] 命令: {' '.join(cmd)}")
    print(f"[ops] {'='*50}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[ops] FAIL {label} 失败 (exit={result.returncode})")
    else:
        print(f"[ops] OK {label} 通过")
    return result.returncode

# ---------------------------------------------------------------------------
# 高阶功能：--status（开工雷达）、--round（全场扫描）
# ---------------------------------------------------------------------------

def _load_index():
    idx_path = os.path.join(ROOT, "knowledge", "file_knowledge_index.json")
    if not os.path.isfile(idx_path):
        return None
    with open(idx_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _last_js_records(n=3):
    idx_path = os.path.join(MODEL, "工作留痕总索引.md")
    if not os.path.isfile(idx_path):
        return []
    import re
    with open(idx_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    def _find_all_js():
        records = []
        # ###-pipe格式
        for m in re.finditer(r'### (JS-\d{8}-\d{2})\s*\|[^|]*\|[^|]*\|[^|]*\|([^|]+)', text):
            records.append((m.group(1), m.group(2).strip()))
        # ###-dot格式
        for m in re.finditer(r'### (JS-\d{8}-\d{2})\s*·[^·]*·([^·]+)', text):
            records.append((m.group(1), m.group(2).strip()))
        # 表格式
        for m in re.finditer(r'(?m)^\| (JS-\d{8}-\d{2}) \|[^|]*\|([^|]+)\|', text):
            records.append((m.group(1), m.group(2).strip()))
        # 去重 + 按 JS 编号排序
        seen = set()
        unique = []
        for js_id, topic in records:
            if js_id not in seen:
                seen.add(js_id)
                unique.append((js_id, topic))
        unique.sort(key=lambda x: x[0])
        return unique
    records = _find_all_js()
    return records[-n:]

def _do_status(args, extra):
    print(f"\n{'='*60}")
    print("  金水谣 · 开工雷达 (ops.py --status)")
    print(f"{'='*60}\n")
    # 1. 体检
    script_path, label = SCRIPT_MAP["doctor"]
    run_script(script_path, label, [])
    # 1b. 索引新鲜度
    print(f"\n[status]  知识索引: {_index_freshness()}")
    # 2. 知识索引查询
    query = extra[0] if extra else None
    if query:
        index = _load_index()
        if not index:
            print(f"\n[status] 知识索引未找到，请先运行 py -3.14 tools/knowledge_index.py")
        else:
            q = query.replace("\\", "/").strip().lower()
            q_basename = os.path.basename(q)
            entries = index.get("entries", {})
            # 精确匹配 → 模糊匹配 → basename 匹配
            matched = None
            matches = []
            for path, items in entries.items():
                if path == q or path.endswith("/" + q):
                    matched = (path, items)
                    break
                if q in path:
                    matches.append((path, items))
            if not matched and not matches:
                # basename 搜索
                for path, items in entries.items():
                    if q_basename in path.split("/")[-1]:
                        matches.append((path, items))
            if matched:
                path, items = matched
                print(f"\n[status]  文件: {path}")
                print(f"[status]  {'─'*40}")
                for it in items:
                    kind_icon = {"pattern": "⚠", "risk": "☣", "js": "📋"}.get(it["type"], "?")
                    print(f"  {kind_icon} [{it['type']}] {it['id']}")
                    print(f"     {it['summary'][:100]}")
                    print(f"     来源: {it['source']}")
            elif matches:
                print(f"\n[status]  模糊匹配 \"{query}\" ({len(matches)} 个文件):")
                print(f"[status]  {'─'*40}")
                for path, items in sorted(matches)[:10]:
                    n = len(items)
                    types_str = ",".join(set(it["type"] for it in items))
                    print(f"  {path} ({n} 条, {types_str})")
                if len(matches) > 10:
                    print(f"  ... 还有 {len(matches)-10} 个")
            else:
                print(f"\n[status]  文件 \"{query}\" 在知识索引中暂无记录")
                print(f"[status]  提示: 知识索引已覆盖 {len(entries)} 个文件，可尝试更精确的文件名")
    # 3. 最近工作记录
    print(f"\n[status]  最近工作记录:")
    print(f"[status]  {'─'*40}")
    for js_id, topic in reversed(_last_js_records(3)):
        print(f"  {js_id}: {topic.strip()}")
    print()
    return 0

def _do_round(args, extra):
    print(f"\n{'='*60}")
    print("  金水谣 · 全场扫描 (ops.py --round)")
    print(f"{'='*60}\n")
    codes = []
    # 1. 体检
    script_path, label = SCRIPT_MAP["doctor"]
    codes.append(run_script(script_path, label, []))
    # 2. sync-ai（若存在）
    sync_path = SCRIPT_MAP.get("sync-ai")
    if sync_path and os.path.isfile(sync_path[0]):
        print(f"\n[round]  同步 AI 决策卡...")
        codes.append(run_script(sync_path[0], sync_path[1], []))
    # 3. extract-patterns（若存在）
    extract_path = SCRIPT_MAP.get("extract-patterns")
    if extract_path and os.path.isfile(extract_path[0]):
        print(f"\n[round]  抽取模式库...")
        codes.append(run_script(extract_path[0], extract_path[1], []))
    # 4. 跨文档审计
    gate_path = os.path.join(BASE, "gate.py")
    if os.path.isfile(gate_path):
        print(f"\n[round]  执行 gate.py --audit")
        codes.append(subprocess.call([sys.executable, gate_path, "--audit"]))
    # 5. 刷新知识索引
    ki_path = os.path.join(BASE, "knowledge_index.py")
    if os.path.isfile(ki_path):
        print(f"\n[round]  刷新知识索引")
        codes.append(subprocess.call([sys.executable, ki_path]))
    # 6. 更新议程
    _update_agenda()
    max_code = max(codes) if codes else 0
    print(f"\n[round]  全场扫描{'通过' if max_code == 0 else '发现异常'}")
    return max_code

def _update_agenda():
    agenda_path = os.path.join(BASE, "agenda.md")
    index = _load_index()
    js = _last_js_records(5)
    lines = [
        "# 金水谣 · 前瞻议程 (auto-generated by ops.py --round)",
        "",
        f"> 生成时间: {__import__('datetime').date.today()}",
        "> 由 ops.py --round 自动生成，指示下一轮关注点。",
        "",
        "---",
        "",
        "## 最近工作",
        "",
    ]
    for js_id, topic in reversed(js):
        lines.append(f"- {js_id}: {topic.strip()}")
    lines.extend([
        "",
        "---",
        "",
        "## 代码健康",
        "",
        "- 运行 `py -3.14 tools/gate.py --check` 确认全绿",
        "- 检查 `gate.py --audit` 输出的跨文档一致性",
        "- 确保 `ops.py --doctor` 体检无报错",
        "",
        "## 关注点",
        "",
        "- 新 AI 启动前阅读本议程 + 纲 + 契 + 录",
        "- 改文件前先查知识索引：`ops.py --status <文件路径>`",
        "- 收工前必须执行 `ops.py --round` 刷新全系统",
        "",
        "---",
        "",
        "## 文件级关注",
        "",
    ])
    if index:
        entries = index.get("entries", {})
        # 列出有多条关联记录的文件（高关注度）
        hot = [(p, items) for p, items in entries.items()
                if len(items) >= 5 and ':' not in p
                and not p.endswith('.txt') and not p.endswith('.cfg')
                and not p.startswith('venv_') and not p.startswith('.')]
        if hot:
            lines.append("### 高频关注文件（>=5 条关联记录，自动筛选）")
            lines.append("")
            for p, items in sorted(hot, key=lambda x: -len(x[1]))[:30]:
                lines.append(f"- **{p}** ({len(items)} 条)")
            lines.append("")
    lines.extend([
        "",
        "_议程文件由 ops.py --round 自动维护，请勿手动编辑。_",
    ])
    with open(agenda_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[round]  议程已更新: {agenda_path}")

# ---------------------------------------------------------------------------
# 闭环工具：索引新鲜度 / --start（开工令）/ --close（收工令）
# ---------------------------------------------------------------------------

def _index_freshness():
    idx_path = os.path.join(ROOT, "knowledge", "file_knowledge_index.json")
    if not os.path.isfile(idx_path):
        return "索引不存在，请运行 py -3.14 tools/knowledge_index.py"

    idx_mtime = os.path.getmtime(idx_path)
    sources = [
        os.path.join(MODEL, "工作留痕总索引.md"),
        os.path.join(ROOT, "knowledge", "pattern_library.json"),
        os.path.join(ROOT, "金水谣数据", "risk_register.json"),
        os.path.join(ROOT, "金水谣数据", "log", "ai_decisions.md"),
        os.path.join(ROOT, "金水谣数据", "log", "经验收集箱.md"),
    ]
    stale = []
    for s in sources:
        if os.path.isfile(s) and os.path.getmtime(s) > idx_mtime:
            stale.append(os.path.basename(s))
    if stale:
        return f"索引可能过时：{', '.join(stale)} 在索引生成后有更新。请运行 ops.py --round"
    return "索引新鲜（所有源文件均在索引生成前未改动）"

def _do_start(args, extra):
    print(f"\n{'='*60}")
    print("  金水谣 · 开工令 (ops.py --start)")
    print(f"{'='*60}\n")
    # 记录开工
    try:
        from tools.audit_trail import log_event
        log_event("session_start", detail="ops.py --start 开工令")
    except Exception:
        pass
    # 1. 体检
    script_path, label = SCRIPT_MAP["doctor"]
    run_script(script_path, label, [])
    # 2. 最近工作
    print(f"\n[start]  最近5条工作记录:")
    print(f"[start]  {'─'*40}")
    for js_id, topic in reversed(_last_js_records(5)):
        print(f"  {js_id}: {topic.strip()}")
    # 3. 索引新鲜度
    print(f"\n[start]  知识索引状态:")
    print(f"[start]  {'─'*40}")
    print(f"  {_index_freshness()}")
    # 4. agenda 概要
    agenda_path = os.path.join(BASE, "agenda.md")
    if os.path.isfile(agenda_path):
        print(f"\n[start]  议程概览 ({agenda_path}):")
        print(f"[start]  {'─'*40}")
        with open(agenda_path, "r", encoding="utf-8") as f:
            content = f.read()
        # show lines with ##
        import re
        for line in content.split("\n"):
            if line.startswith("##") and "generated" not in line:
                print(f"  {line}")
    # 5. 建议
    print(f"\n[start]  开工建议:")
    print(f"[start]  {'─'*40}")
    print(f"  1. 阅读 模型/AI协作交接中心.md 了解当前上下文")
    print(f"  2. 改文件前: ops.py --status <文件路径>")
    print(f"  3. 收工前:  ops.py --digest → ops.py --close")
    print()
    return 0

def _do_close(args, extra):
    print(f"\n{'='*60}")
    print("  金水谣 · 收工令 (ops.py --close)")
    print(f"{'='*60}\n")
    codes = []
    # 1. 提醒 --digest
    print("[close]  第一步：经验已提取？")
    ans = input("  已运行 ops.py --digest？(y/N): ").strip().lower()
    if ans != "y":
        print("  → 请先运行 py -3.14 tools/ops.py --digest 提取经验\n")
    # 2. sync-ai（若存在）
    sync_path = SCRIPT_MAP.get("sync-ai")
    if sync_path and os.path.isfile(sync_path[0]):
        print(f"\n[close]  同步 AI 决策卡...")
        codes.append(run_script(sync_path[0], sync_path[1], []))
    # 3. extract-patterns（若存在）
    extract_path = SCRIPT_MAP.get("extract-patterns")
    if extract_path and os.path.isfile(extract_path[0]):
        print(f"\n[close]  抽取模式库...")
        codes.append(run_script(extract_path[0], extract_path[1], []))
    # 4. 全场扫描
    print(f"\n[close]  全场扫描...")
    codes.append(_do_round(args, extra))
    # 5. 收工门禁
    print(f"\n[close]  收工门禁检查...")
    gate_code = run_script(
        os.path.join(os.path.dirname(__file__), "closeout_gate.py"),
        "收工门禁",
        ["--override"] if "--override" in extra else []
    )
    codes.append(gate_code)

    # 记录收工
    try:
        from tools.audit_trail import log_event, write_replay
        ok = gate_code == 0 and max(codes) == 0
        log_event("session_close",
                   detail=f"收工令 {'成功' if ok else '有异常'}",
                   files=[f"门禁={'通过' if gate_code==0 else '拦截'}",
                          f"扫描={'通过' if max(codes)==0 else '有异常'}"])
        write_replay()
    except Exception:
        pass
    # 6. commit 提醒
    print(f"\n{'='*60}")
    print(f"  收工清单:")
    print(f"  {'─'*40}")
    print(f"  1. (必) 确认总索引已登记本条JS记录")
    print(f"  2. (必) py -3.14 tools/gate.py --check 确认全绿")
    print(f"  3. (必) git add + git commit")
    print(f"  4. 收工门禁: {'已通过' if gate_code == 0 else '未通过!'}")
    print(f"  {'='*60}")
    max_code = max(codes) if codes else 0
    return max_code

def main():
    import argparse
    parser = argparse.ArgumentParser(description="金水谣统一运维入口")
    for key, (_, label) in SCRIPT_MAP.items():
        parser.add_argument(f"--{key}", action="store_true", help=label)
    parser.add_argument("--status", action="store_true", help="开工雷达：体检 + 文件知识查询")
    parser.add_argument("--round", action="store_true", help="全场扫描：体检 + 审计 + 索引刷新 + 议程")
    parser.add_argument("--digest", action="store_true", help="经验提取器：提取对话经验→经验收集箱")
    parser.add_argument("--start", action="store_true", help="开工令：体检 + 议程 + 最近工作")
    parser.add_argument("--close", action="store_true", help="收工令：digest→sync→extract→round→commit")
    parser.add_argument("--all", action="store_true", help="全跑一遍")
    args, extra = parser.parse_known_args()

    if args.start:
        return _do_start(args, extra)
    if args.close:
        return _do_close(args, extra)
    if args.status:
        return _do_status(args, extra)
    if args.round:
        return _do_round(args, extra)
    if args.digest:
        digest_path = os.path.join(BASE, "digest_experience.py")
        if os.path.isfile(digest_path):
            return subprocess.call([sys.executable, digest_path] + extra)
        print("[ops] tools/digest_experience.py 不存在")
        return 1

    selected = []
    if args.all:
        selected = list(SCRIPT_MAP.keys())
    else:
        for key in SCRIPT_MAP:
            if getattr(args, key, False):
                selected.append(key)

    if not selected:
        parser.print_help()
        print("\n[ops] 未指定子命令。例如: py -3.14 tools/ops.py --doctor")
        return 1

    exit_codes = []
    for key in selected:
        script_path, label = SCRIPT_MAP[key]
        code = run_script(script_path, label, extra)
        exit_codes.append(code)

    max_code = max(exit_codes) if exit_codes else 0
    if max_code == 0:
        print(f"\n[ops] OK 全部 {len(selected)} 项通过")
    else:
        n_fail = sum(1 for c in exit_codes if c != 0)
        print(f"\n[ops] WARN 有 {n_fail} 项失败，最高退出码={max_code}")
    return max_code

if __name__ == "__main__":
    sys.exit(main())
