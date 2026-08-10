#!/usr/bin/env python3
"""金水谣项目结构一键整理工具 v2

用法:
    py tools/reorg.py --dry-run      # 预览
    py tools/reorg.py --apply        # 执行
    py tools/reorg.py --rollback     # 回滚

本次优化:
    - 10个空目录清理
    - 前端 HTML 统一迁入 frontend/ 目录
    - echarts.min.js 去重 (3份一模一样)
    - jinshuiyao-* 前端子项目统一迁入 frontend/
    - 服务端路由表 static.py 自动更新
    - HTML 内 echarts 引用路径自动修正
"""

import os
import sys
import json
import shutil
import hashlib
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(BASE, "tools", "reorg_manifest.json")
BACKUP_ROOT = os.path.join(BASE, ".reorg_backup")


def rel(path):
    return os.path.relpath(path, BASE)


def log(msg):
    print(f"  {msg}")


def file_hash(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()[:12]


def backup_item(path):
    bak = os.path.join(BACKUP_ROOT, rel(path))
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    if os.path.isdir(path):
        if os.path.isdir(bak):
            shutil.rmtree(bak)
        shutil.copytree(path, bak)
    else:
        shutil.copy2(path, bak)
    return bak


class ReorgPlan:
    def __init__(self):
        self.moves = []
        self.deletes = []
        self.edits = {}

    def move(self, src, dst):
        self.moves.append((src, dst))

    def delete(self, path):
        self.deletes.append(path)

    def add_edit(self, filepath, old, new):
        self.edits.setdefault(filepath, []).append((old, new))

    def summary(self):
        lines = []
        if self.deletes:
            lines.append(f"  删除 {len(self.deletes)} 个空目录")
        if self.moves:
            lines.append(f"  移动 {len(self.moves)} 个文件/目录")
        if self.edits:
            lines.append(f"  更新 {len(self.edits)} 个文件内容")
        return "\n".join(lines) if lines else "  无变更"


def build_plan():
    plan = ReorgPlan()

    # ─── 1. 空目录清理 ───
    for d in [
        ".uploads",
        "jinshuiyao-guide/assets",
        "jinshuiyao-dashboard/_shared/fonts",
        "jinshuiyao-gap-analysis/_shared/fonts",
        "jinshuiyao-guide/_shared/fonts",
        "金水谣数据/creator_output",
        "金水谣数据/test_creator_output",
        "金水谣数据/test_creator_review",
        "domains/金水谣数据/users",
        "tests/金水谣数据/video_cache/_test",
    ]:
        full = os.path.join(BASE, d)
        if os.path.isdir(full) and not os.listdir(full):
            plan.delete(full)

    # ─── 2. 前端目录统一迁入 frontend/ ───
    frontend_moves = {
        "lottery": "frontend/lottery",
        "fund": "frontend/fund",
        "stock": "frontend/stock",
        "football": "frontend/football",
        "jinshuiyao-dashboard": "frontend/dashboard",
        "jinshuiyao-gap-analysis": "frontend/gap-analysis",
        "jinshuiyao-guide": "frontend/guide",
        "jinshuiyao-quant-dashboard": "frontend/quant-dashboard",
        "jinshuiyao-trend": "frontend/trend",
    }
    for src_rel, dst_rel in frontend_moves.items():
        src = os.path.join(BASE, src_rel)
        dst = os.path.join(BASE, dst_rel)
        if os.path.isdir(src) and not os.path.isdir(dst):
            plan.move(src, dst)

    # ─── 3. echarts.min.js 去重 + HTML 引用更新 ───
    # 源文件在 dashboard 目录（搬家前的位置）
    echart_src_old = os.path.join(BASE, "jinshuiyao-dashboard", "_shared", "js", "echarts.min.js")
    echart_dst = os.path.join(BASE, "frontend", "_shared", "js", "echarts.min.js")
    os.makedirs(os.path.dirname(echart_dst), exist_ok=True)

    # 所有本地引用的 HTML（搬家前的路径）
    html_refs = [
        ("jinshuiyao-dashboard/jinshuiyao-dashboard.html", "./_shared/js/echarts.min.js"),
        ("jinshuiyao-gap-analysis/jinshuiyao-gap-analysis.html", "./_shared/js/echarts.min.js"),
        ("jinshuiyao-trend/jinshuiyao-trend.html", "./_shared/js/echarts.min.js"),
        ("jinshuiyao-trend/omission-heatmap.html", "./_shared/js/echarts.min.js"),
        ("lottery/omission-heatmap.html", "./_shared/js/echarts.min.js"),
        ("football/dashboard.html", "./_shared/js/echarts.min.js"),
        ("jinshuiyao-quant-dashboard/index.html", "vendor/echarts.min.js"),
    ]

    for html_rel, old_ref in html_refs:
        html_path = os.path.join(BASE, html_rel)
        if not os.path.isfile(html_path):
            continue
        # 计算新路径: frontend/<subdir>/xxx.html -> ../../_shared/js/echarts.min.js
        # 搬家后: frontend/dashboard/jinshuiyao-dashboard.html
        subdir = html_rel.split("/")[0]
        dst_map = {
            "jinshuiyao-dashboard": "frontend/dashboard",
            "jinshuiyao-gap-analysis": "frontend/gap-analysis",
            "jinshuiyao-trend": "frontend/trend",
            "lottery": "frontend/lottery",
            "football": "frontend/football",
            "jinshuiyao-quant-dashboard": "frontend/quant-dashboard",
        }
        if subdir not in dst_map:
            continue
        new_html_rel = html_rel.replace(subdir, dst_map[subdir])
        new_html_dir = os.path.dirname(os.path.join(BASE, new_html_rel))
        new_ref = os.path.relpath(echart_dst, new_html_dir).replace("\\", "/")
        plan.add_edit(html_path, old_ref, new_ref)

    # ─── 4. 服务端路由 static.py 更新 ───
    static_py = os.path.join(BASE, "server", "handlers", "static.py")
    if os.path.isfile(static_py):
        path_map = {
            "'jinshuiyao-dashboard'": "'frontend/dashboard'",
            "'jinshuiyao-trend'": "'frontend/trend'",
            "'jinshuiyao-quant-dashboard'": "'frontend/quant-dashboard'",
            "'jinshuiyao-gap-analysis'": "'frontend/gap-analysis'",
            "os.path.join(BASE_DIR, 'lottery'": "os.path.join(BASE_DIR, 'frontend', 'lottery'",
            "os.path.join(BASE_DIR, 'fund'": "os.path.join(BASE_DIR, 'frontend', 'fund'",
            "os.path.join(BASE_DIR, 'stock'": "os.path.join(BASE_DIR, 'frontend', 'stock'",
            "os.path.join(BASE_DIR, 'football'": "os.path.join(BASE_DIR, 'frontend', 'football'",
        }
        for old, new in path_map.items():
            plan.add_edit(static_py, old, new)

    return plan


def apply(plan):
    print("\n========== 金水谣项目结构整理 v2 ==========\n")
    manifest_entries = []

    # 先做文件内容替换（文件还在原位）
    for fpath, edits in plan.edits.items():
        if not os.path.isfile(fpath):
            continue
        bak = backup_item(fpath)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        for old, new in edits:
            count = content.count(old)
            if count:
                content = content.replace(old, new)
                print(f"[更新] {rel(fpath)}: {old[:40]} -> {new[:40]} ({count}处)")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        manifest_entries.append({"action": "edit", "file": fpath})

    # 再删除空目录
    for d in plan.deletes:
        print(f"[删除目录] {rel(d)}/")
        manifest_entries.append({"action": "rmdir", "path": d})
        os.rmdir(d)

    # 最后移动目录
    for src, dst in plan.moves:
        print(f"[移动] {rel(src)} -> {rel(dst)}")
        bak = backup_item(src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        manifest_entries.append({"action": "move", "src": src, "dst": dst, "backup": bak})

    manifest = {
        "timestamp": datetime.now().isoformat(),
        "entries": manifest_entries,
    }
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n整理完成！记录: tools/reorg_manifest.json")
    if manifest_entries:
        print(f"  回滚: py tools/reorg.py --rollback")
    print()


def rollback():
    if not os.path.isfile(MANIFEST):
        print("未找到整理记录")
        return
    with open(MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"\n========== 回滚 ({manifest['timestamp']}) ==========\n")
    for entry in reversed(manifest["entries"]):
        action = entry["action"]
        if action == "rmdir":
            os.makedirs(entry["path"], exist_ok=True)
            print(f"[恢复目录] {rel(entry['path'])}/")
        elif action == "move":
            bak = entry["backup"]
            if os.path.isfile(bak) or os.path.isdir(bak):
                os.makedirs(os.path.dirname(entry["src"]), exist_ok=True)
                if os.path.isdir(bak):
                    if os.path.isdir(entry["src"]):
                        shutil.rmtree(entry["src"])
                    shutil.copytree(bak, entry["src"])
                else:
                    shutil.copy2(bak, entry["src"])
                print(f"[恢复] {rel(entry['src'])}")
                if os.path.isdir(entry["dst"]):
                    shutil.rmtree(entry["dst"])
                elif os.path.isfile(entry["dst"]):
                    os.remove(entry["dst"])
            else:
                print(f"[警告] 备份丢失: {bak}")
        elif action == "edit":
            print(f"[注意] {rel(entry['file'])} 需手动还原 (备份在 .reorg_backup/)")

    print(f"\n回滚完成")
    os.remove(MANIFEST)


def dry_run(plan):
    print("\n========== 金水谣项目结构整理 v2 [预览] ==========\n")
    print(f"项目: {BASE}\n")

    plan.summary()

    if plan.deletes:
        print(f"  删除 {len(plan.deletes)} 个空目录:")
        for d in sorted(plan.deletes):
            print(f"    [DEL] {rel(d)}/")

    if plan.moves:
        print(f"\n  移动 {len(plan.moves)} 个目录:")
        for src, dst in sorted(plan.moves):
            print(f"    [MOVE] {rel(src)}")
            print(f"           -> {rel(dst)}")

    if plan.edits:
        print(f"\n  更新 {len(plan.edits)} 个文件:")
        for fpath in sorted(plan.edits):
            print(f"    [EDIT] {rel(fpath)}")

    print(f"\n运行: py tools/reorg.py --apply")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    plan = build_plan()

    if cmd == "--dry-run":
        dry_run(plan)
    elif cmd == "--apply":
        apply(plan)
    elif cmd == "--rollback":
        rollback()
    else:
        print(f"未知参数: {cmd}")
        sys.exit(1)
