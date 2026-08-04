#!/usr/bin/env python3
"""金水谣 · 收工门禁 (closeout gate) — 强制三件套留存检查 + pre-commit 自愈

检查：
  1. AI协作交接中心.md   — 登记做了什么
  2. 经验收集箱.md        — 追加经验
  3. 工作留痕总索引.md     — 登记编号
  4. pre-commit hook 是否存活（缺失则自动安装）

三项缺一不可，硬阻断（exit=1）。可用 --override 紧急跳过。
"""

import os
import re
import shutil
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.dirname(BASE_DIR)

FILES = {
    "交接中心": os.path.join(MODEL_DIR, "AI协作交接中心.md"),
    "经验收集箱": os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md"),
    "工作留痕总索引": os.path.join(MODEL_DIR, "工作留痕总索引.md"),
}

def today_str():
    return date.today().strftime("%Y-%m-%d")

def check_file_updated(path, name):
    if not os.path.isfile(path):
        return False, f"文件不存在: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return False, f"读取失败: {e}"

    today = today_str()
    if name == "工作留痕总索引":
        short_date = today[5:]  # "07-29"
        pattern = re.compile(rf"^###\s+JS-\d{{8}}-\d{{2}}\s*\|\s*{re.escape(short_date)}\s*\|", re.MULTILINE)
    else:
        pattern = re.compile(re.escape(today))

    if pattern.search(content):
        return True, f"已找到 {today} 登记"
    return False, f"未找到 {today} 登记"

def _find_git_dir():
    """从常见位置找 .git 目录"""
    for d in [MODEL_DIR, BASE_DIR]:
        git_dir = os.path.join(d, ".git")
        if os.path.isdir(git_dir):
            return git_dir, d
    return None, None


def check_precommit_hook():
    """检查 pre-commit hook 是否存在且内容正确，缺失则自动重建"""
    git_dir, repo_root = _find_git_dir()
    if not git_dir:
        return True, "非 git 仓库，跳过"

    hook_path = os.path.join(git_dir, "hooks", "pre-commit")
    # 当前部署蓝本为 wrapper（install_hooks.py 与 2026-08-03 JS-20260803-02 起统一用 wrapper.sh）
    is_win = sys.platform == "win32"
    src_name = "pre-commit-hook-wrapper.sh"
    src_path = os.path.join(BASE_DIR, "tools", src_name)

    if not os.path.isfile(src_path):
        return True, f"规范源 {src_name} 不存在，跳过"

    # 读规范源内容
    with open(src_path, "r", encoding="utf-8") as f:
        src_content = f.read()

    if os.path.isfile(hook_path):
        with open(hook_path, "r", encoding="utf-8") as f:
            hook_content = f.read()
        if "check_consistency" in hook_content and "precommit_ai_review" in hook_content:
            return True, f"已存活 ({src_name})"

    # 缺失 → 自动安装
    try:
        shutil.copyfile(src_path, hook_path)
        print(f"  [HEAL] pre-commit hook 缺失，已自动重建: {hook_path}")
        return True, f"已自动安装 ({src_name})"
    except Exception as e:
        return False, f"自动安装失败: {e}"


def main():
    override = "--override" in sys.argv

    print("=" * 60)
    print("  金水谣 · 收工门禁")
    print(f"  检查日期: {today_str()}")
    print("=" * 60)

    all_ok = True

    # 1-3: 三件套
    for name, path in FILES.items():
        ok, msg = check_file_updated(path, name)
        status = "OK" if ok else "MISS"
        print(f"  [{status}] {name}: {msg}")
        if not ok:
            all_ok = False

    # 4: pre-commit hook 自愈
    ok, msg = check_precommit_hook()
    status = "OK" if ok else "MISS"
    print(f"  [{status}] pre-commit 钩子: {msg}")
    if not ok:
        all_ok = False

    # 记录门禁结果
    try:
        from tools.audit_trail import log_event
        event = "gate_pass" if all_ok else "gate_fail"
        detail = "全部通过" if all_ok else "存在未通过项"
        if override:
            detail += " (--override 跳过)"
        log_event(event, detail=detail)
    except Exception:
        pass

    print("-" * 60)
    if all_ok:
        print("  结果: 全部通过，可以收工提交！")
        print("=" * 60)
        return 0
    elif override:
        print("  结果: 存在未通过项 (--override 跳过)")
        print("=" * 60)
        return 0
    else:
        print("  结果: 存在未通过项 —— 禁止收工提交！")
        print()
        print("  缺失项必须先补充。或 py -3.14 tools/closeout_gate.py --override 紧急跳过")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
