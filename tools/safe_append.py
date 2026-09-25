#!/usr/bin/env python3
"""
留痕文件安全追加器 —— 解决多 AI 并发写留痕时相互覆盖的问题。

用法：
    py -3 tools/safe_append.py --file "工作留痕总索引.md" --content "要追加的内容"
    py -3 tools/safe_append.py --file "经验收集箱.md" --content-file "temp_entry.md"

逻辑：
1. 先 git pull --rebase 拉取最新（如果失败则跳过，提示用户）
2. 追加内容到文件末尾
3. 校验内容确实写入成功

约定（写在 AGENTS.md 铁律0）：
- 留痕三件套（交接中心/总索引/经验箱）**只追加不修改已有行**
- 追加前先跑本脚本拉取最新，减少覆盖风险
- 如果两个 AI 同时追加，后追加的内容在文件更后面，不会覆盖前者
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_git(args: list[str]) -> tuple[int, str, str]:
    """运行 git 命令，返回 (exit_code, stdout, stderr)。"""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def pull_latest() -> bool:
    """尝试 git pull --rebase 拉取最新。成功返回 True。"""
    # 先检查是否有远程
    code, out, err = run_git(["remote", "-v"])
    if code != 0 or not out.strip():
        print("[safe_append] 无远程仓库，跳过 pull", file=sys.stderr)
        return False

    code, out, err = run_git(["pull", "--rebase", "--no-edit"])
    if code == 0:
        print("[safe_append] git pull --rebase 成功")
        return True
    else:
        print(f"[safe_append] git pull 失败（可能有本地冲突），跳过拉取: {err.strip()[:200]}", file=sys.stderr)
        return False


def append_to_file(file_path: Path, content: str, expected_mtime: float | None = None) -> bool:
    """追加内容到文件末尾，返回是否成功。

    修复（JS-20260924-20）：原实现是 read-modify-write（先 read_text 再 write_text），
    两个 AI 并发执行时后者会覆盖前者。改为真正的追加模式 open(..., "a")，
    OS 层面保证追加写入的原子性（同进程内单次 write 不会被同文件其他 write 打断）。

    修复（JS-20260924-22）：新增 expected_mtime 参数。若传入，则在真正追加前检查
    文件当前 mtime 是否与 expected_mtime 一致；不一致说明 pull 后文件被其他 AI
    修改，返回 False 让调用方重新 pull 重试，避免基于过时版本追加。
    """
    try:
        # 并发冲突检测：mtime 不一致说明文件被其他 AI 修改
        if expected_mtime is not None:
            actual_mtime = get_mtime(file_path)
            if actual_mtime != expected_mtime:
                print("[safe_append] 文件在 pull 后被其他 AI 修改（mtime 不一致），需要重新拉取", file=sys.stderr)
                return False

        # 确保文件存在
        if not file_path.exists():
            file_path.write_text("", encoding="utf-8")
        # 检查末尾是否已有换行（只读最后 1 字节，避免读全文件）
        # 空文件不需要补换行；非空文件且末尾无换行时才补
        needs_newline = False
        try:
            size = file_path.stat().st_size
            if size > 0:
                with open(file_path, "rb") as f:
                    f.seek(-1, 2)  # 跳到最后一个字节
                    last = f.read(1)
                    needs_newline = last != b"\n"
        except OSError:
            needs_newline = False
        # 真正追加："a" 模式下 OS 保证写入原子性
        with open(file_path, "a", encoding="utf-8") as f:
            if needs_newline:
                f.write("\n")
            f.write(content)
        return True
    except Exception as e:
        print(f"[safe_append] 写入失败: {e}", file=sys.stderr)
        return False


def verify_write(file_path: Path, content: str) -> bool:
    """校验内容确实写入了文件。"""
    if not file_path.exists():
        return False
    written = file_path.read_text(encoding="utf-8", errors="ignore")
    # 取 content 的前 50 字符作为校验指纹
    fingerprint = content.strip()[:50]
    return fingerprint in written


def get_mtime(file_path: Path) -> float:
    """获取文件 mtime，文件不存在返回 0。"""
    try:
        return file_path.stat().st_mtime
    except OSError:
        return 0.0


def main() -> int:
    args = sys.argv[1:]
    file_path = None
    content = None
    content_file = None

    i = 0
    while i < len(args):
        if args[i] == "--file" and i + 1 < len(args):
            file_path = args[i + 1]
            i += 2
        elif args[i] == "--content" and i + 1 < len(args):
            content = args[i + 1]
            i += 2
        elif args[i] == "--content-file" and i + 1 < len(args):
            content_file = args[i + 1]
            i += 2
        else:
            print(f"未知参数: {args[i]}", file=sys.stderr)
            print("用法: safe_append.py --file <文件> --content <内容> [--content-file <文件>]", file=sys.stderr)
            return 1

    if not file_path:
        print("必须指定 --file", file=sys.stderr)
        return 1

    if content_file:
        content = Path(content_file).read_text(encoding="utf-8")

    if content is None:
        print("必须指定 --content 或 --content-file", file=sys.stderr)
        return 1

    full_path = REPO_ROOT / file_path

    # 修复（JS-20260924-22）：并发冲突预警 + 重试。
    # pull 后记录文件 mtime，写入前若 mtime 变化说明其他 AI 已修改该文件，
    # 重新 pull 后重试，最多 3 次，避免覆盖他人内容。
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        # 1. 拉取最新
        pulled = pull_latest()
        if not pulled:
            print("[safe_append] 拉取最新失败，中止写入以避免覆盖他人留痕。请手动 git pull 后重试。", file=sys.stderr)
            return 1

        # 2. 记录 pull 后文件 mtime，用于并发冲突检测
        mtime_before = get_mtime(full_path)

        # 3. 追加（内部会检查 mtime 是否被其他 AI 修改）
        if not append_to_file(full_path, content, expected_mtime=mtime_before):
            # append_to_file 返回 False 可能是 mtime 不一致（并发冲突）或写入失败
            if attempt < max_retries:
                print(f"[safe_append] 第 {attempt} 次追加失败（可能并发冲突），重新拉取后重试...", file=sys.stderr)
                continue
            else:
                print(f"[safe_append] 连续 {max_retries} 次追加失败，中止写入。请稍后重试。", file=sys.stderr)
                return 1

        # 4. 校验
        if verify_write(full_path, content):
            print(f"[safe_append] 成功追加到 {file_path}")
            return 0
        else:
            print(f"[safe_append] 校验失败：内容未正确写入 {file_path}", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
