#!/usr/bin/env python3
"""
JS 编号集中分配器 —— 解决多 AI 并发写留痕时的编号撞车问题。

用法：
    py -3 tools/next_js_number.py              # 取今天的下一个可用编号（并创建占位锁）
    py -3 tools/next_js_number.py --date 2026-09-24   # 指定日期
    py -3 tools/next_js_number.py --dry-run    # 只显示当前已用编号列表，不取号不建锁
    py -3 tools/next_js_number.py --release JS-20260924-13  # 手动释放编号锁

逻辑（JS-20260924-22 修复编号撞号）：
1. 扫描 总索引.md、交接中心.md 中所有 JS-YYYYMMDD-NN 编号
2. 扫描 tools/.js_locks/ 目录下的占位锁文件（排除过期锁）
3. 取指定日期的最大编号 NN，返回 max+1
4. 返回前在 tools/.js_locks/ 创建占位锁文件，防止其他 AI 取到同号

占位锁机制：
- 锁文件：tools/.js_locks/JS-YYYYMMDD-NN.lock，内容为创建时间戳
- 锁文件超过 LOCK_TTL_SECONDS（默认 600 秒=10 分钟）自动失效，不计入已用编号
- AI 写完留痕后应手动 --release 释放，或等 10 分钟自动过期
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = REPO_ROOT / "工作留痕总索引.md"
HANDOFF_FILE = REPO_ROOT / "AI协作交接中心.md"
LOCK_DIR = REPO_ROOT / "tools" / ".js_locks"

# 锁文件有效期（秒），超过后自动失效
LOCK_TTL_SECONDS = 600

# 匹配 JS-YYYYMMDD-NN（NN 为 1-3 位数字，兼容历史不规范写法）
JS_PATTERN = re.compile(r"JS-(\d{8})-(\d{1,3})")
LOCK_PATTERN = re.compile(r"JS-(\d{8})-(\d{1,3})\.lock$")


def collect_used_numbers(target_date: str) -> set[int]:
    """收集指定日期已使用的所有编号（含留痕文件 + 未过期的占位锁）。"""
    used: set[int] = set()
    # 1. 留痕文件中的编号
    for f in (INDEX_FILE, HANDOFF_FILE):
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in JS_PATTERN.finditer(text):
            if m.group(1) == target_date:
                used.add(int(m.group(2)))
    # 2. 占位锁文件中的编号（排除过期锁）
    if LOCK_DIR.exists():
        now = time.time()
        for lock_file in LOCK_DIR.glob("*.lock"):
            m = LOCK_PATTERN.search(lock_file.name)
            if not m or m.group(1) != target_date:
                continue
            # 读取锁文件中的时间戳判断是否过期
            try:
                ts = float(lock_file.read_text(encoding="utf-8").strip())
                if now - ts < LOCK_TTL_SECONDS:
                    used.add(int(m.group(2)))
                else:
                    # 过期锁自动清理
                    lock_file.unlink(missing_ok=True)
            except (ValueError, OSError):
                # 锁文件损坏或无法读取，视为过期并清理
                lock_file.unlink(missing_ok=True)
    return used


def acquire_lock(js_id: str) -> bool:
    """为编号创建占位锁文件，成功返回 True。"""
    try:
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        lock_file = LOCK_DIR / f"{js_id}.lock"
        lock_file.write_text(str(time.time()), encoding="utf-8")
        return True
    except OSError as e:
        print(f"[next_js_number] 创建锁文件失败: {e}", file=sys.stderr)
        return False


def release_lock(js_id: str) -> bool:
    """手动释放编号锁。"""
    lock_file = LOCK_DIR / f"{js_id}.lock"
    if lock_file.exists():
        lock_file.unlink(missing_ok=True)
        print(f"[next_js_number] 已释放锁 {js_id}")
        return True
    else:
        print(f"[next_js_number] 未找到锁 {js_id}（可能已过期或从未创建）", file=sys.stderr)
        return False


def next_number(target_date: str | None = None, dry_run: bool = False) -> str:
    """返回下一个可用编号，并创建占位锁。"""
    if target_date is None:
        target_date = date.today().strftime("%Y%m%d")

    used = collect_used_numbers(target_date)

    if dry_run:
        if not used:
            print(f"日期 {target_date} 暂无已用编号")
        else:
            print(f"日期 {target_date} 已用编号: {sorted(used)}")
        return ""

    next_n = 1 if not used else max(used) + 1
    js_id = f"JS-{target_date}-{next_n:02d}"

    # 创建占位锁，防止其他 AI 取到同号
    if not acquire_lock(js_id):
        print(f"[next_js_number] 警告：无法为 {js_id} 创建锁，编号可能被并发抢占", file=sys.stderr)

    return js_id


def main() -> int:
    args = sys.argv[1:]
    target_date = None
    dry_run = False
    release_id = None

    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            target_date = args[i + 1].replace("-", "")
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--release" and i + 1 < len(args):
            release_id = args[i + 1]
            i += 2
        else:
            print(f"未知参数: {args[i]}", file=sys.stderr)
            print("用法: next_js_number.py [--date YYYY-MM-DD] [--dry-run] [--release JS-YYYYMMDD-NN]", file=sys.stderr)
            return 1

    if release_id:
        return 0 if release_lock(release_id) else 1

    result = next_number(target_date, dry_run)
    if result:
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
