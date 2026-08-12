#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 跨文档一致性审计 (cross_doc_audit.py)
==============================================
自动验证所有文档之间的引用一致性。
gate.py --audit 调用此脚本。

检查项：
  1. 脚本引用审计：交接中心中所有脚本引用指向真实文件
  2. 命令可执行审计：纲/契/录中的所有 cli 命令文件存在
  3. 双脚本审计：tools/ 和 scripts/ 下无同文件名的孤儿脚本
  4. 前端路由审计：jinshuiyao-guide/ 下所有 HTML 在 static.py 有路由
  5. 配置解析审计：所有 JSON 配置文件可解析
"""
import os
import re
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
MODEL = os.path.dirname(ROOT)  # 模型/
JINSHUIYAO_GUIDE = os.path.join(ROOT, "jinshuiyao-guide")
STATIC_PY = os.path.join(ROOT, "server", "handlers", "static.py")
CONFIG_DIR = os.path.join(ROOT, "config")

RESULTS = []

def ok(name, detail=""):
    RESULTS.append(("OK", name, detail))

def fail(name, detail):
    RESULTS.append(("FAIL", name, detail))

def warn(name, detail):
    RESULTS.append(("WARN", name, detail))


# 已知迁移/归档/移出仓库（历史文档引用合法保留，2026-08-12 W63补71 加白）
_KNOWN_MOVED = {
    "scripts/closeout_gate.py": "tools/closeout_gate.py",        # W63补60/W63补70 迁移 tools/
    "scripts/smoke_test.py":    "tools/smoke_test.py",            # W63补70 迁移 tools/
    "tools/extract_browser_cookie.py": "移出仓库 %LOCALAPPDATA%/Jinshuiyao/tools_sensitive/",  # W63补62 敏感工具移仓
    "tools/jinshuiyao_python310_validator.py": "tools/archive/",  # W63补55 归档
    "tools/reorg.py":           "tools/archive/",                 # W63补55 归档
    "tools/smoke_mcp.py":       "tools/archive/",                 # W63补55 归档
}

def check_1_script_references():
    """交接中心所有 .py 引用指向真实文件"""
    jx_path = os.path.join(MODEL, "AI协作交接中心.md")
    if not os.path.isfile(jx_path):
        fail("1-脚本引用审计", f"交接中心不存在: {jx_path}")
        return
    with open(jx_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    refs = set(re.findall(r'(?:tools|scripts)/[\w.-]+\.py', text))
    orphans = []
    for ref in sorted(refs):
        if ref in _KNOWN_MOVED:
            continue
        full = os.path.join(ROOT, ref)
        if not os.path.isfile(full):
            orphans.append(ref)
    if orphans:
        fail("1-脚本引用审计", f"{len(orphans)} 个引用指向不存在的文件: {', '.join(orphans)}")
    else:
        ok("1-脚本引用审计", f"全部 {len(refs)} 个引用指向真实文件")


def check_2_command_files():
    """纲/契/录 中所有 cli 命令的脚本文件存在"""
    docs = ["金水谣_纲.md", "金水谣_契.md", "金水谣_录.md"]
    commands_found = []
    for doc_name in docs:
        path = os.path.join(MODEL, doc_name)
        if not os.path.isfile(path):
            warn("2-命令可执行审计", f"{doc_name} 不存在，跳过")
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        cmds = re.findall(r'(?:py -3[\d.]*|python)\s+((?:tools|scripts)/[\w./-]+\.py)', text)
        for c in cmds:
            full = os.path.join(ROOT, c)
            if not os.path.isfile(full):
                commands_found.append((doc_name, c, "MISSING"))
            else:
                commands_found.append((doc_name, c, "OK"))
    missing = [f"{d}: {c}" for d, c, s in commands_found if s == "MISSING"]
    if missing:
        fail("2-命令可执行审计", f"{len(missing)} 个命令引用的脚本不存在: {'; '.join(missing)}")
    else:
        ok("2-命令可执行审计", f"审计 {len(commands_found)} 个命令引用，全部存在")


def check_3_dual_scripts():
    """无同名孤儿脚本（tools/ 和 scripts/ 各有一份且无归档标记）"""
    tools_py = set()
    for f in os.listdir(os.path.join(BASE)):
        if f.endswith(".py"):
            tools_py.add(f)
    scripts_py = set()
    scripts_dir = os.path.join(ROOT, "scripts")
    if os.path.isdir(scripts_dir):
        for f in os.listdir(scripts_dir):
            if f.endswith(".py"):
                scripts_py.add(f)
    duals = tools_py & scripts_py
    if duals:
        for d in sorted(duals):
            tools_path = os.path.join(BASE, d)
            scripts_path = os.path.join(ROOT, "scripts", d)
            with open(tools_path, "r", encoding="utf-8", errors="replace") as f:
                tools_header = f.read(500)
            with open(scripts_path, "r", encoding="utf-8", errors="replace") as f:
                scripts_header = f.read(500)
            has_redirect = any(m in tools_header or m in scripts_header for m in ["此文件已归档", "已归档", "已合并"])
            if not has_redirect:
                fail("3-双脚本审计", f"{d} 在 tools/ 和 scripts/ 各有一份且无归档标记")
    if not any(r[0] == "FAIL" and r[1] == "3-双脚本审计" for r in RESULTS):
        ok("3-双脚本审计", "无未标记的双脚本")


def check_4_frontend_routes():
    """jinshuiyao-guide/ 所有 HTML 在路由层有注册（static.py 或 handler 层）"""
    if not os.path.isdir(JINSHUIYAO_GUIDE):
        warn("4-前端路由审计", "jinshuiyao-guide/ 不存在，跳过")
        return
    html_files = set(f for f in os.listdir(JINSHUIYAO_GUIDE) if f.endswith(".html"))
    if not os.path.isfile(STATIC_PY):
        fail("4-前端路由审计", f"static.py 不存在: {STATIC_PY}")
        return
    with open(STATIC_PY, "r", encoding="utf-8", errors="replace") as f:
        static_text = f.read()
    registered = set()
    for m in re.finditer(r'["\']([\w-]+\.html)["\']', static_text):
        registered.add(m.group(1))
    # handler 层注册的页面（server/handlers/lottery.py/review.py），非 static.py 映射（2026-08-12 W63补71 加白）
    registered |= {"lottery-sources-health.html", "review-dashboard.html"}
    unregistered = html_files - registered
    if unregistered:
        fail("4-前端路由审计", f"{len(unregistered)} 个 HTML 无路由: {', '.join(sorted(unregistered))}")
    else:
        ok("4-前端路由审计", f"全部 {len(html_files)} 个 HTML 有路由注册")


def check_5_config_parse():
    """所有 JSON 配置文件可解析"""
    if not os.path.isdir(CONFIG_DIR):
        warn("5-配置解析审计", "config/ 不存在，跳过")
        return
    json_files = [f for f in os.listdir(CONFIG_DIR) if f.endswith(".json")]
    broken = []
    for jf in sorted(json_files):
        path = os.path.join(CONFIG_DIR, jf)
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            broken.append(f"{jf}: {e}")
    if broken:
        fail("5-配置解析审计", f"{len(broken)} 个 JSON 无法解析: {'; '.join(broken)}")
    else:
        ok("5-配置解析审计", f"全部 {len(json_files)} 个 JSON 可解析")


PAGE_REGISTRY_PATH = os.path.join(CONFIG_DIR, "page_registry.json")

def check_6_page_registry():
    """page_registry.json 中的记录与实际文件存在"""
    if not os.path.isfile(PAGE_REGISTRY_PATH):
        fail("6-页面注册表审计", "page_registry.json 不存在")
        return
    with open(PAGE_REGISTRY_PATH, "r", encoding="utf-8") as f:
        try:
            reg = json.load(f)
        except Exception as e:
            fail("6-页面注册表审计", f"page_registry.json 解析失败: {e}")
            return
    pages = reg.get("pages", [])
    missing = []
    for p in pages:
        full = os.path.join(ROOT, p["path"])
        if not os.path.isfile(full):
            missing.append(p["path"])
    if missing:
        fail("6-页面注册表审计", f"{len(missing)} 个注册页面文件不存在: {', '.join(missing)}")
    else:
        ok("6-页面注册表审计", f"全部 {len(pages)} 个注册页面文件存在")

def main():
    check_1_script_references()
    check_2_command_files()
    check_3_dual_scripts()
    check_4_frontend_routes()
    check_5_config_parse()
    check_6_page_registry()

    print(f"\n{'='*60}")
    print(f"  跨文档一致性审计报告")
    print(f"  共 {len(RESULTS)} 项")
    print(f"{'='*60}")
    passed = sum(1 for s, _, _ in RESULTS if s == "OK")
    failures = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    warnings = sum(1 for s, _, _ in RESULTS if s == "WARN")
    for status, name, detail in RESULTS:
        icon = {"OK": "  OK", "FAIL": "FAIL", "WARN": "WARN"}[status]
        print(f"  [{icon}] {name}")
        if detail:
            print(f"         {detail}")
    print(f"\n  通过={passed}  失败={failures}  警告={warnings}")
    return 1 if failures > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
