# -*- coding: utf-8 -*-
"""
本机浏览器 cookie 提取工具（金水谣·仅本机运行，绝不联网上传）
================================================================

用途：
    在【你本人的电脑】上，读取【你自己已登录】的浏览器 cookie（默认抖音域），
    解密后组装成 cookie 字符串，写入 config/douyin_cookie.txt，
    供 VideoExtractor 带登录态提取抖音文案使用。

安全边界（重要）：
    - 只读取本机浏览器的本地文件，不联网、不上传任何数据。
    - 需要用户明确授权后由用户/助手手动运行，绝不后台偷跑。
    - cookie 等同登录凭证，生成的文件请勿分享、勿同步到云盘/git。

支持的浏览器（Chromium 内核，Windows）：
    qq(QQ浏览器) / chrome / edge

解密原理（Windows Chromium）：
    1. Local State 里的 os_crypt.encrypted_key 去掉 "DPAPI" 前缀后，
       用 Windows DPAPI(CryptUnprotectData) 解出 AES 主密钥。
    2. Cookies 库里每个 encrypted_value：
       - v10/v11 开头 → AES-256-GCM 解密（nonce=3:15, tag=末16字节）。
       - 其它 → 老式 DPAPI 直接解密。

用法：
    python extract_browser_cookie.py                 # 默认 QQ 浏览器 + 抖音域
    python extract_browser_cookie.py --browser chrome
    python extract_browser_cookie.py --domain douyin.com --out ../config/douyin_cookie.txt
    python extract_browser_cookie.py --list          # 只统计，不写文件
"""
import argparse
import base64
import ctypes
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from ctypes import wintypes

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None


# ---------------------------------------------------------------- 浏览器路径
def _local_appdata():
    return os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")


BROWSERS = {
    "qq": os.path.join(_local_appdata(), "Tencent", "QQBrowser", "User Data"),
    "chrome": os.path.join(_local_appdata(), "Google", "Chrome", "User Data"),
    "edge": os.path.join(_local_appdata(), "Microsoft", "Edge", "User Data"),
}


def find_user_data(browser):
    root = BROWSERS.get(browser)
    if not root or not os.path.isdir(root):
        return None
    return root


def find_cookie_db(user_data):
    """新版 Chromium 把 Cookies 放在 Default/Network/ 下，老版在 Default/ 下。"""
    candidates = [
        os.path.join(user_data, "Default", "Network", "Cookies"),
        os.path.join(user_data, "Default", "Cookies"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# ---------------------------------------------------------------- DPAPI
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt(data):
    """调用 Windows DPAPI 解密（当前用户密钥）。"""
    blob_in = _DATA_BLOB(len(data),
                         ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise RuntimeError("DPAPI 解密失败（可能不是当前用户/机器加密的数据）")
    n = blob_out.cbData
    buf = ctypes.create_string_buffer(n)
    ctypes.memmove(buf, blob_out.pbData, n)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return buf.raw


def get_master_key(user_data):
    ls = os.path.join(user_data, "Local State")
    if not os.path.isfile(ls):
        raise RuntimeError(f"找不到 Local State 文件：{ls}")
    with open(ls, "r", encoding="utf-8") as f:
        data = json.load(f)
    enc = data.get("os_crypt", {}).get("encrypted_key")
    if not enc:
        raise RuntimeError("Local State 里没有 encrypted_key，无法取主密钥")
    raw = base64.b64decode(enc)
    if raw[:5] != b"DPAPI":
        raise RuntimeError("不支持的密钥格式（可能是新版应用绑定加密，需另行处理）")
    return dpapi_decrypt(raw[5:])


# ---------------------------------------------------------------- 值解密
def decrypt_value(enc_value, key):
    if not enc_value:
        return ""
    prefix = enc_value[:3]
    if prefix in (b"v10", b"v11"):
        if AES is None:
            raise RuntimeError("缺少 pycryptodome，无法 AES-GCM 解密。请先 pip install pycryptodome")
        nonce = enc_value[3:15]
        tag = enc_value[-16:]
        ciphertext = enc_value[15:-16]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8", "replace")
    # 老式 DPAPI
    try:
        return dpapi_decrypt(enc_value).decode("utf-8", "replace")
    except Exception:
        return ""


# ---------------------------------------------------------------- 读库（免锁）
def _query(conn, domain):
    conn.text_factory = bytes
    cur = conn.cursor()
    cur.execute(
        "SELECT host_key, name, encrypted_value FROM cookies "
        "WHERE host_key LIKE ?", ("%" + domain + "%",))
    rows = cur.fetchall()
    conn.close()
    return rows


def _shared_copy(src, dst):
    """用 Win32 CreateFileW 以“共享读写删”模式打开被浏览器占用的文件并复制字节。
    这样浏览器开着也能读取自己的数据库副本（不改动原文件）。"""
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    FILE_SHARE_DELETE = 0x4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID = ctypes.c_void_p(-1).value

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.restype = ctypes.c_void_p
    handle = CreateFileW(
        ctypes.c_wchar_p(src), GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if handle == INVALID or handle is None:
        raise ctypes.WinError()

    ReadFile = ctypes.windll.kernel32.ReadFile
    CloseHandle = ctypes.windll.kernel32.CloseHandle
    try:
        with open(dst, "wb") as out:
            buf = ctypes.create_string_buffer(1024 * 1024)
            read = wintypes.DWORD(0)
            while True:
                ok = ReadFile(ctypes.c_void_p(handle), buf, len(buf),
                              ctypes.byref(read), None)
                if not ok or read.value == 0:
                    break
                out.write(buf.raw[:read.value])
    finally:
        CloseHandle(ctypes.c_void_p(handle))


def _read_cookie_rows(db, domain):
    """浏览器开着时数据库被独占：
    1) SQLite immutable 只读直读；
    2) 普通复制；
    3) Win32 共享模式底层复制（兜底，可读被占用文件）。"""
    # 1) immutable 只读
    try:
        uri = f"file:{db.replace('?', '%3f').replace('#', '%23')}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        return _query(conn, domain)
    except Exception:
        pass
    # 2)/3) 复制到临时目录再读
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_cookie_")
    tmp_db = os.path.join(tmpdir, "Cookies")
    try:
        try:
            shutil.copy2(db, tmp_db)
        except Exception:
            _shared_copy(db, tmp_db)   # 兜底：共享模式底层复制
        conn = sqlite3.connect(tmp_db)
        return _query(conn, domain)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- 主流程
def extract(browser="qq", domain="douyin.com", out=None, list_only=False):
    if os.name != "nt":
        raise RuntimeError("本工具仅支持 Windows。")

    user_data = find_user_data(browser)
    if not user_data:
        raise RuntimeError(f"找不到浏览器数据目录：{browser}（可能未安装或路径不同）")

    db = find_cookie_db(user_data)
    if not db:
        raise RuntimeError("找不到 Cookies 数据库文件。")

    key = get_master_key(user_data)

    rows = _read_cookie_rows(db, domain)

    pairs = {}
    for host_key, name, enc_value in rows:
        name = name.decode("utf-8", "replace") if isinstance(name, bytes) else name
        try:
            val = decrypt_value(enc_value, key)
        except Exception:
            val = ""
        if name and val:
            pairs[name] = val  # 同名去重，保留最后一个

    cookie_str = "; ".join(f"{k}={v}" for k, v in pairs.items())

    # 关键登录字段自检
    key_fields = ["sessionid", "sessionid_ss", "sid_tt", "uid_tt", "passport_csrf_token"]
    hit = [k for k in key_fields if k in pairs]

    print(f"浏览器：{browser}")
    print(f"Cookies 库：{db}")
    print(f"匹配域 '{domain}' 的 cookie 条数：{len(pairs)}")
    print(f"关键登录字段命中：{', '.join(hit) if hit else '（无——可能未登录该网站）'}")

    if list_only:
        print("[--list] 仅统计，不写文件。")
        return cookie_str, pairs, hit

    if not cookie_str:
        print(f"！没有提取到任何 cookie，未写文件。请确认已在该浏览器登录 {domain}。")
        return cookie_str, pairs, hit

    if out is None:
        here = os.path.dirname(os.path.abspath(__file__))
        out = os.path.join(here, "..", "config", "douyin_cookie.txt")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(cookie_str)
    print(f"已写入：{out}")
    print(f"cookie 字符串长度：{len(cookie_str)} 字符")
    return cookie_str, pairs, hit


def main():
    ap = argparse.ArgumentParser(description="本机浏览器 cookie 提取（仅本机、不上传）")
    ap.add_argument("--browser", default="qq", choices=list(BROWSERS.keys()),
                    help="浏览器：qq / chrome / edge（默认 qq）")
    ap.add_argument("--domain", default="douyin.com", help="要提取的 cookie 域（默认 douyin.com）")
    ap.add_argument("--out", default=None, help="输出文件路径（默认 ../config/douyin_cookie.txt）")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="只统计条数，不写文件")
    args = ap.parse_args()
    try:
        extract(browser=args.browser, domain=args.domain, out=args.out, list_only=args.list_only)
    except Exception as e:
        print(f"提取失败：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
