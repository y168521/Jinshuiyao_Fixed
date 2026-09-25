#!/usr/bin/env python3
"""金水谣 · 留痕合规检查 (trail compliance)

用途：pre-commit hook 第6步 + 自动同步 commit 前预检。
逻辑：若本次暂存区包含「需要留痕的源码/文档改动」，但交接中心 / 总索引 / 经验箱
      三者中任意一个没有当日新增登记，则阻断提交，强制 AI 先补留痕。

被判定为「需要留痕的改动」：
  - 扩展名属于 .py/.md/.html/.css/.js/.json/.bat/.sh/.ps1/.mermaid
  - 且不属于三个留痕文件本身（留痕文件的改动不算"需要留痕的源码改动"）
  - 且不属于运行时噪音（predictions.json / brain_state.json / token_usage.json 等）

退出码：
  0 = 通过（无源码改动，或三件套齐全）
  1 = 缺留痕（打印缺失项）
  2 = 环境异常（git 不可用等）

环境变量：
  SKIP_TRAIL_CHECK=1  紧急跳过（仅用于自动同步自身配置变更等极少数场景）
"""

import os
import re
import subprocess
import sys
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要留痕的扩展名
TRAIL_REQUIRED_EXTS = {".py", ".md", ".html", ".css", ".js", ".json", ".bat", ".sh", ".ps1", ".mermaid"}

# 运行时噪音（即便扩展名命中，也不算"需要留痕的改动"）
NOISE_PATTERNS = [
    "predictions.json", "brain_state.json", "token_usage.json",
    "correlation_matrix.json", "auto_audit_report.json",
    "auto_sync.log", "telemetry.jsonl", "scheduler_exec.jsonl",
    "ai_conversations.jsonl", "knowledge_refresh.jsonl",
    "model_route_stats.jsonl", "risk_state.json",
    "free_model_status.json", "user_themes.json",
    "football_matches.json", "reference_pool.json",
    "schemes.json", "engines.json", "evolution_",
    "server/config.py", "__pycache__", ".ruff_cache", ".pytest_cache",
    ".git", "金水谣数据/backups", "金水谣数据/insurance",
]

# 三个留痕文件（相对项目根）
TRAIL_FILES = {
    "交接中心": "AI协作交接中心.md",
    "总索引": "工作留痕总索引.md",
    "经验箱": os.path.join("金水谣数据", "log", "经验收集箱.md"),
}


def _run_git(args):
    """运行 git 命令，返回 (stdout_lines, returncode)"""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return r.stdout.splitlines(), r.returncode
    except FileNotFoundError:
        # git 不在 PATH（hook 环境可能如此），尝试常见路径
        for cand in [
            r"C:\Users\Administrator\.workbuddy\binaries\PortableGit\versions\1.2.0\cmd\git.exe",
            r"C:\Program Files\Git\cmd\git.exe",
        ]:
            if os.path.isfile(cand):
                try:
                    r = subprocess.run(
                        [cand] + args, cwd=BASE_DIR,
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                    )
                    return r.stdout.splitlines(), r.returncode
                except Exception:
                    continue
        return [], 127


def get_staged_files():
    """获取暂存区文件列表"""
    lines, rc = _run_git(["diff", "--cached", "--name-only"])
    if rc != 0:
        return []
    return [l.strip() for l in lines if l.strip()]


def is_trail_required(path):
    """判断该文件改动是否需要留痕"""
    # 留痕文件本身的改动不算"需要留痕的源码改动"
    rel = path.replace("\\", "/")
    for tf in TRAIL_FILES.values():
        if rel == tf.replace("\\", "/"):
            return False
    # 噪音排除
    for noise in NOISE_PATTERNS:
        if noise in rel:
            return False
    # 扩展名检查
    ext = os.path.splitext(rel)[1].lower()
    return ext in TRAIL_REQUIRED_EXTS


def today_str():
    return date.today().strftime("%Y-%m-%d")


def date_variants(today: str) -> list[str]:
    """生成今日日期的多种写法变体，用于宽松匹配。

    today 格式 "2026-09-24"，返回：
    ["2026-09-24", "2026-9-24", "2026/09/24", "2026/9/24", "09-24", "9-24", "09/24", "9/24",
     "20260924", "9月24日", "09月24日"]
    """
    y, m, d = today.split("-")
    mi, di = int(m), int(d)
    return [
        today,                          # 2026-09-24
        f"{y}-{mi}-{di}",               # 2026-9-24
        f"{y}/{m}/{d}",                 # 2026/09/24
        f"{y}/{mi}/{di}",               # 2026/9/24
        f"{m}-{d}",                     # 09-24
        f"{mi}-{di}",                   # 9-24
        f"{m}/{d}",                     # 09/24
        f"{mi}/{di}",                   # 9/24
        f"{y}{m}{d}",                   # 20260924
        f"{mi}月{di}日",                 # 9月24日
        f"{m}月{d}日",                   # 09月24日
    ]


def check_trail_file(name, rel_path):
    """检查留痕文件是否有当日登记，返回 (ok, message)"""
    full = os.path.join(BASE_DIR, rel_path)
    if not os.path.isfile(full):
        return False, f"文件不存在: {rel_path}"
    try:
        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return False, f"读取失败: {e}"

    today = today_str()
    variants = date_variants(today)
    compact = today.replace("-", "")

    if name == "总索引":
        # 总索引：匹配 "### JS-YYYYMMDD-NN | YYYY-MM-DD | ..." 或表格行
        # 宽松匹配：JS 编号 + 任一日期变体
        short_variants = [v for v in variants if len(v) <= 5]  # 09-24, 9-24, 09/24, 9/24
        date_alt = "|".join(re.escape(v) for v in short_variants)
        pattern = re.compile(
            rf"JS-\d{{8}}-\d{{2}}.*?(?:{date_alt})",
            re.MULTILINE)
    else:
        # 交接中心 / 经验箱：匹配任一日期变体 或 JS-YYYYMMDD-NN 编号
        date_alt = "|".join(re.escape(v) for v in variants)
        pattern = re.compile(rf"({date_alt}|JS-{compact}-\d{{2}})")

    if pattern.search(content):
        return True, "已登记"
    return False, f"未找到 {today} 登记（支持格式：2026-09-24 / 2026/9/24 / 9月24日 / JS-20260924-NN）"


def main():
    if os.environ.get("SKIP_TRAIL_CHECK") == "1":
        print("[trail] SKIP 留痕检查（SKIP_TRAIL_CHECK=1）")
        return 0

    staged = get_staged_files()
    if not staged:
        print("[trail] OK 暂存区为空，无需留痕检查")
        return 0

    # 筛选需要留痕的改动
    need_trail = [p for p in staged if is_trail_required(p)]
    if not need_trail:
        print(f"[trail] OK 暂存 {len(staged)} 文件均为留痕文件/运行时数据，无需留痕")
        return 0

    print(f"[trail] 检测到 {len(need_trail)} 个需要留痕的文件改动，检查三件套...")

    missing = []
    for name, rel in TRAIL_FILES.items():
        ok, msg = check_trail_file(name, rel)
        status = "OK" if ok else "MISS"
        print(f"[trail]   {status} {name}: {msg}")
        if not ok:
            missing.append(name)

    if missing:
        print("[trail] FAIL 缺少留痕：" + "、".join(missing))
        print("[trail] 修复：在对应文件追加当日登记（JS编号 / 日期 / 做了什么），再重新提交")
        print("[trail] 紧急跳过：SKIP_TRAIL_CHECK=1 git commit")
        return 1

    print("[trail] OK 三件套齐全，留痕合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())
