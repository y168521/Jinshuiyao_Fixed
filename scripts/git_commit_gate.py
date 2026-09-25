# -*- coding: utf-8 -*-
"""
金水谣 · 收工 git 门禁 (git_commit_gate.py)
============================================

一句话：替你把"该提交但忘了提交"的源码/文档改动捞出来列清单，并揪出
"运行时文件没被 .gitignore 屏蔽"的噪音隐患。只读检查，绝不自动提交。

设计对齐项目铁律（见 .workbuddy/memory/MEMORY.md）：
  - 铁律⑥：收工必 git commit 入库；运行时生成文件不提交。
  - F3 红线：提交要精确，不卷无关文件。
  - F5 红线：pre-commit 报 P0 时如实转述，不擅自 --no-verify。
  - F10 红线：最小权限，本脚本零写入（不改任何文件、不 git add/commit）。

用法：
  python git_commit_gate.py            # 检查并输出报告
  python git_commit_gate.py --quiet    # 仅输出结论行（供自动化调度摘要）
退出码：0=干净；1=有待提交项/有隐患（供调度判"需关注"）；2=工具异常。
"""

import os
import sys
import subprocess

# ROOT 由脚本位置推导，不再写死绝对路径。
# 背景（JS-20260925-10）：原值硬编码 C:/.../模型/Jinshuiyao_Fixed。双机部署时
# 台式机=D 盘、笔记本=E 盘，写死路径在另一台机器上指向不存在的目录 →
# 所有 git 调用失败 → 门禁静默失效（"不可用"会被误读成"干净"）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# git 可执行文件。默认 "git"（依赖 PATH）；调用方可覆写为本机真实路径
# （如 E:\下载\Git\bin\git.exe，它不在 PATH 里）。
GIT_EXE = os.environ.get("JS_GIT_EXE", "git")

# 视为"源码"的后缀 —— 未跟踪闸只关心这些，运行时产物由 .gitignore 负责。
SOURCE_SUFFIX = (".py", ".sh", ".ps1", ".bat")
SOURCE_SKIP_DIRS = ("__pycache__", ".git", "node_modules", "venv", ".venv")

# 运行时噪音黑名单（目录前缀 / 文件名模式 / 后缀）
# 这些产物按铁律不入库，出现在本地的未提交清单里属于噪音，应被过滤。
# 注意：knowledge/ 混有源码(.py)与生成物，不能整目录当噪音（会漏掉 kb_engine.py 源码）。
# 仅按「纯生成物目录」+「精确文件名」判定，避免误伤源码（F3 红线）。
NOISE_DIR_PREFIX = (
    "predictions/",
    "video_cache/",
    "__pycache__/",
)
NOISE_SUFFIX = (".pyc", ".pyo", ".tmp", ".log")
NOISE_NAME = (
    "vector_index.json",
    "knowledge_graph.json",
    "predictions.json",
    "correlation_matrix.json",
    "cache_meta.json",
    "INDEX.json",
    "索引.md",
    ".file_hash_baseline.json",
    "watchdog_state.json",
)


def is_noise(path: str) -> bool:
    p = path.replace("\\", "/")
    low = p.lower()
    for pre in NOISE_DIR_PREFIX:
        if low.startswith(pre.lower()) or ("/" + pre.lower()) in low:
            return True
    for suf in NOISE_SUFFIX:
        if low.endswith(suf):
            return True
    base = os.path.basename(p)
    if base in NOISE_NAME:
        return True
    return False


def git_porcelain():
    """返回 git status --porcelain，中文路径用原样（quotepath=false）。"""
    try:
        out = subprocess.check_output(
            [GIT_EXE, "-c", "core.quotepath=false", "status", "--porcelain"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", "ignore")
        return out
    except Exception as e:
        sys.stderr.write(f"[git 状态获取失败] {e}\n")
        return ""


def git_porcelain_all():
    """同上，但强制 --untracked-files=all 展开目录。

    为什么必须单独一个函数（JS-20260925-09）：
    `git status` 默认把未跟踪**目录**折叠成一行 `?? audio_toolkit/`，
    里面有几个 .py 完全看不出来。曾因此让 20 个源码文件停留在未跟踪状态。
    """
    try:
        out = subprocess.check_output(
            [GIT_EXE, "-c", "core.quotepath=false", "status",
             "--porcelain", "--untracked-files=all"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", "ignore")
        return out
    except Exception as e:
        sys.stderr.write(f"[git 状态获取失败] {e}\n")
        return ""


def untracked_sources(porcelain=None):
    """返回「从未入库的源码文件」列表（相对仓库根，正斜杠）。

    只收 SOURCE_SUFFIX；.json/.log 等运行时产物不算 —— 它们该由 .gitignore
    管，报出来是噪音（铁律：告警只报能变绿的）。

    注意：返回 [] 有两种可能——真干净，或 git 调用失败。调用方必须自行
    区分（本模块的 closeout_gate 第 10 闸在 git 不可用时直接 FAIL，不退化放行）。
    """
    if porcelain is None:
        porcelain = git_porcelain_all()
    out = []
    for line in porcelain.splitlines():
        if not line.startswith("??"):
            continue
        p = line[3:].strip().strip('"').replace("\\", "/")
        if not p.lower().endswith(SOURCE_SUFFIX):
            continue
        parts = p.split("/")
        if any(d in parts for d in SOURCE_SKIP_DIRS):
            continue
        out.append(p)
    return out


def is_ignored(path: str) -> bool:
    """用 check-ignore 判断路径是否被忽略；仅看退出码，不打印噪音。"""
    rc = subprocess.call(
        [GIT_EXE, "-c", "core.quotepath=false", "check-ignore", "-q", path],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return rc == 0


def main():
    quiet = "--quiet" in sys.argv
    porcelain = git_porcelain()
    if porcelain == "":
        # 可能是真的干净，也可能是 git 不可用；用一次简单探测区分
        probe = subprocess.call(
            [GIT_EXE, "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe != 0:
            print("⚠ 无法获取 git 状态（git 不可用或不在仓库内）。" if not quiet else "GIT-ERROR")
            return 2

    candidate = []   # 建议提交项
    noise = []       # 噪音项（命中黑名单）

    for line in porcelain.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        path = line[3:].strip().strip('"')
        if is_noise(path):
            noise.append((status, path))
        else:
            candidate.append((status, path))

    # 反向检查 .gitignore：噪音项里哪些其实"未被忽略"
    not_ignored = []
    for status, path in noise:
        if not is_ignored(path):
            not_ignored.append((status, path))

    # 输出报告
    print("=" * 60)
    print("金水谣 · 收工 git 门禁检查")
    print("=" * 60)

    if candidate:
        print(f"\n【建议提交清单】（{len(candidate)} 项，源码/文档类）")
        for status, path in candidate:
            print(f"  [{status.strip() or '??'}] {path}")
        print("\n  提示：请人工确认后精确提交，例如：")
        print('    git add <具体路径> && git commit -m "..."')

    if not_ignored:
        print(f"\n【gitignore 隐患】以下运行时文件未被 .gitignore 屏蔽（{len(not_ignored)} 项）：")
        for status, path in not_ignored:
            print(f"  [{status.strip() or '??'}] {path}")
        print("  建议：在 .gitignore 补充对应规则，避免它们长期污染 git status。")

    if not candidate and not not_ignored:
        print("\n✅ 仓库干净：无待提交改动，无 gitignore 隐患。")

    if not candidate and not_ignored:
        print("\n（无待提交源码/文档，但存在 gitignore 隐患，见上。）")

    print("\n" + "=" * 60)
    print("本门禁仅检查、不提交。需要时由人确认后执行 git commit。")

    return 1 if (candidate or not_ignored) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        sys.stderr.write(f"[门禁异常] {e}\n")
        sys.exit(2)
