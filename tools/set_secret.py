#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互式安全写入密钥到 ~/.jinshuiyao-secrets/

为什么需要它：
  密钥目录是隐藏目录（以 . 开头），手动去资源管理器找容易漏看；
  Windows cmd 下 getpass 不认右键粘贴（已知坑），导致密钥粘不进去。
  本脚本改为：优先从剪贴板自动读取（复制密钥后直接跑即可），
  回退用 input()（支持右键粘贴），写入后权限置 600 并尽量清空剪贴板。

用法（在 Jinshuiyao_Fixed/ 目录下）：
    py -3.14 tools/set_secret.py --name deepseek_key
    py -3.14 tools/set_secret.py --name douyin_cookie
    py -3.14 tools/set_secret.py --name siliconflow_key   # 硅基流动（免费模型用）

最简流程：复制密钥 → 跑命令 → 看到预览按回车确认。全程无需在终端内粘贴。
"""
import argparse
import os
import sys

# 与 core/ai_service.py / tools/ai_review_agent.py 读取路径保持一致
SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

KNOWN = {
    "deepseek_key": "deepseek_key.txt",
    "douyin_cookie": "douyin_cookie.txt",
    "siliconflow_key": "siliconflow_key.txt",
}


def write_secret(secrets_dir: str, name: str, value: str) -> str:
    """把 value 写入 secrets_dir/<file>，返回最终路径。可被测试时传入临时目录。"""
    fname = KNOWN[name]
    os.makedirs(secrets_dir, exist_ok=True)
    path = os.path.join(secrets_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    try:
        os.chmod(path, 0o600)  # 仅当前用户可读写
    except OSError:
        pass
    return path


def read_clipboard_windows() -> str:
    """从 Windows 剪贴板读取文本（无依赖，失败返回空串）。"""
    try:
        import ctypes
        cf_unicode = 13  # CF_UNICODETEXT
        if not ctypes.windll.user32.OpenClipboard(0):
            return ""
        try:
            h = ctypes.windll.user32.GetClipboardData(cf_unicode)
            if not h:
                return ""
            p = ctypes.windll.kernel32.GlobalLock(h)
            if not p:
                return ""
            try:
                size = ctypes.windll.kernel32.GlobalSize(h)
                buf = ctypes.create_unicode_buffer(size // 2)
                ctypes.memmove(buf, p, size)
                return buf.value or ""
            finally:
                ctypes.windll.kernel32.GlobalUnlock(h)
        finally:
            ctypes.windll.user32.CloseClipboard()
    except Exception:
        return ""


def clear_clipboard_windows() -> None:
    """尽量清空剪贴板里的密钥（best-effort）。finally 保证关闭，避免异常时资源泄露。"""
    try:
        import ctypes
        if ctypes.windll.user32.OpenClipboard(0):
            try:
                ctypes.windll.user32.EmptyClipboard()
            finally:
                ctypes.windll.user32.CloseClipboard()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="交互式安全写入密钥到 ~/.jinshuiyao-secrets/")
    ap.add_argument("--name", required=True, choices=list(KNOWN.keys()),
                    help="要设置的密钥名（deepseek_key / douyin_cookie / siliconflow_key）")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="自动确认（用于脚本/非交互式调用，仍需剪贴板或 stdin 有内容）")
    args = ap.parse_args()

    # 1) 优先从剪贴板读取（复制密钥后直接跑，最省事）
    clip = read_clipboard_windows() if sys.platform == "win32" else ""
    val = ""
    if clip and clip.strip():
        val = clip.strip()
        print(f"📋 已从剪贴板获取 {args.name}（长度 {len(val)}）")
    else:
        # 回退：input() 在 Windows cmd 下支持右键粘贴（getpass 不支持，故不用）
        if args.yes:
            print("❌ 指定了 --yes 但剪贴板为空，无法自动确认。", file=sys.stderr)
            return 1
        val = input(f"请粘贴 {args.name} 的值后回车（屏幕上会显示）: ").strip()

    if not val:
        print("❌ 输入为空，已取消。", file=sys.stderr)
        return 1

    masked = (val[:6] + "…" + val[-4:]) if len(val) > 10 else "***"
    print(f"  预览: {masked}")
    if not args.yes:
        confirm = input("确认写入以上密钥? [回车=确认, 输入任意字符=取消]: ").strip()
        if confirm:
            print("❌ 已取消。", file=sys.stderr)
            return 1

    path = write_secret(SECRETS_DIR, args.name, val)
    print(f"✅ 已写入: {path}")
    print(f"   权限=600（仅当前系统用户可读）")
    clear_clipboard_windows()
    print("🧹 已尝试清空剪贴板中的密钥")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
