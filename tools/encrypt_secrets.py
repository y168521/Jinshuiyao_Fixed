#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣 · 密钥加密迁移工具（W63补99 / JS-20260816-04）

把 ~/.jinshuiyao-secrets/ 下的明文密钥文件加密为 <name>.txt.enc（AES-256-GCM），
主密钥来自环境变量 TIANSHU_MASTER_KEY，未设置则自动生成随机主密钥写入
~/.jinshuiyao-secrets/.master.key（该目录本身在坚果云同步树之外）。

安全流程：先加密 + 解密校验一致，才删除明文；任一密钥失败则保留明文并继续。
core.security.get_secret 已支持 .enc 优先读取，解密失败自动回退明文（自愈）。

用法：
  py -3.14 tools/encrypt_secrets.py          # 加密全部明文密钥
  py -3.14 tools/encrypt_secrets.py --dry-run  # 只预览不执行
  py -3.14 tools/encrypt_secrets.py --decrypt-check  # 校验已加密文件可解
"""
import os
import sys
import base64
import secrets as _secrets

_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
_SALT = b"jinshuiyao-secrets-v1"


def _get_master_key():
    """主密钥：环境变量优先，否则生成随机 32 字节 hex 持久化到 .master.key"""
    env = os.environ.get("TIANSHU_MASTER_KEY", "").strip()
    if env:
        return env
    mk = os.path.join(_SECRETS_DIR, ".master.key")
    if os.path.isfile(mk):
        with open(mk, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    v = _secrets.token_hex(32)
    try:
        os.makedirs(_SECRETS_DIR, exist_ok=True)
        with open(mk, "w", encoding="utf-8") as f:
            f.write(v)
        try:
            os.chmod(mk, 0o600)
        except Exception:
            pass
        print(f"[encrypt_secrets] 已生成主密钥文件: {mk}（请妥善保管，勿同步外传）")
    except Exception as e:
        print(f"[encrypt_secrets] 主密钥写入失败: {e}")
        raise SystemExit(1)
    return v


def _derive_key(master):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT,
                     iterations=120000, backend=default_backend())
    return kdf.derive(master.encode("utf-8"))


def _encrypt(master, plaintext):
    import os as _os
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    key = _derive_key(master)
    iv = _os.urandom(12)
    enc = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend()).encryptor()
    ct = enc.update(plaintext.encode("utf-8")) + enc.finalize()
    return base64.b64encode(iv + enc.tag + ct).decode("utf-8")


def _decrypt(master, data_b64):
    import base64 as _b64
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    key = _derive_key(master)
    data = _b64.b64decode(data_b64)
    iv, tag, ct = data[:12], data[12:28], data[28:]
    dec = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend()).decryptor()
    return (dec.update(ct) + dec.finalize()).decode("utf-8")


def main():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher  # noqa: F401
    except ImportError:
        print("[encrypt_secrets] 缺少 cryptography 依赖，无法加密。")
        sys.exit(1)
    dry = "--dry-run" in sys.argv
    check = "--decrypt-check" in sys.argv
    master = _get_master_key()
    if not os.path.isdir(_SECRETS_DIR):
        print("[encrypt_secrets] 密钥目录不存在: " + _SECRETS_DIR)
        return
    files = sorted(f for f in os.listdir(_SECRETS_DIR)
                   if f.endswith(".txt") and not f.startswith("."))
    if check:
        encs = sorted(f for f in os.listdir(_SECRETS_DIR)
                      if f.endswith(".enc") and not f.startswith("."))
        print(f"[encrypt_secrets] 校验 {len(encs)} 个加密文件可解...")
        ok = 0
        for f in encs:
            try:
                v = _decrypt(master, open(os.path.join(_SECRETS_DIR, f), encoding="utf-8").read())
                if v:
                    ok += 1
                    print(f"  OK  {f}（{len(v)} 字符）")
                else:
                    print(f"  !!  {f} 解密为空")
            except Exception as e:
                print(f"  FAIL {f}: {e}")
        print(f"[encrypt_secrets] 校验完成：{ok}/{len(encs)} 可解")
        return
    print(f"[encrypt_secrets] 发现 {len(files)} 个明文密钥文件（dry-run={dry}）")
    done, failed = 0, []
    for f in files:
        src = os.path.join(_SECRETS_DIR, f)
        enc_path = src + ".enc"
        try:
            with open(src, "r", encoding="utf-8") as fp:
                plain = fp.read().strip()
            if not plain:
                print(f"  跳过（空文件）: {f}")
                continue
            token = _encrypt(master, plain)
            back = _decrypt(master, token)
            if back != plain:
                failed.append((f, "加密校验不一致"))
                print(f"  FAIL {f}: 校验不一致")
                continue
            if dry:
                print(f"  [dry] 可加密: {f}（{len(plain)} 字符）")
                continue
            with open(enc_path, "w", encoding="utf-8") as fp:
                fp.write(token)
            try:
                os.chmod(enc_path, 0o600)
            except Exception:
                pass
            os.remove(src)
            done += 1
            print(f"  OK   {f} -> {f}.enc（明文已删除）")
        except Exception as e:
            failed.append((f, str(e)))
            print(f"  FAIL {f}: {e}")
    print(f"\n[encrypt_secrets] 完成：加密 {done} 个，失败 {len(failed)} 个（失败项保留明文，get_secret 自动回退）")
    for f, e in failed:
        print(f"   - {f}: {e}")


if __name__ == "__main__":
    main()