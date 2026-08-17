# -*- coding: utf-8 -*-
"""JS-20260807-01 · SSRF 校验单一真源 is_safe_http_url 测试

验证 core/security.is_safe_http_url 对所有危险类别的判定正确，
它是 router._is_safe_http_url 与 video_extractor._is_safe_host 共用的唯一实现。
所有用例均用 IP 字面量或 mock，零网络依赖，结果确定稳定。
"""
import unittest.mock as mock

from core.security import is_safe_http_url


def test_public_ip_allowed():
    ok, msg = is_safe_http_url("https://8.8.8.8/")
    assert ok is True
    assert msg == ""


def test_loopback_rejected():
    ok, msg = is_safe_http_url("http://127.0.0.1/")
    assert ok is False
    assert ("内网" in msg) or ("禁止" in msg)


def test_private_rejected():
    ok, msg = is_safe_http_url("http://192.168.1.1/")
    assert ok is False


def test_link_local_rejected():
    # 云元数据地址，SSRF 经典目标
    ok, msg = is_safe_http_url("http://169.254.169.254/latest/meta-data/")
    assert ok is False


def test_reserved_rejected():
    ok, msg = is_safe_http_url("http://240.0.0.1/")
    assert ok is False


def test_multicast_rejected():
    ok, msg = is_safe_http_url("http://224.0.0.1/")
    assert ok is False


def test_non_http_scheme_rejected():
    ok, msg = is_safe_http_url("file:///etc/passwd")
    assert ok is False
    assert "http" in msg


def test_ftp_scheme_rejected():
    ok, msg = is_safe_http_url("ftp://example.com/")
    assert ok is False


def test_no_scheme_rejected():
    ok, msg = is_safe_http_url("not-a-url")
    assert ok is False


def test_empty_host_rejected():
    ok, msg = is_safe_http_url("http://")
    assert ok is False
    assert ("域名" in msg) or ("无效" in msg)


def test_dns_failure_rejected():
    with mock.patch("core.security.socket.getaddrinfo", side_effect=OSError("boom")):
        ok, msg = is_safe_http_url("http://nonexistent.example.invalid/")
    assert ok is False
    assert "解析" in msg


# ---------------------------------------------------------------------------
# JS-20260816-04 · get_secret 加密存储（.enc AES-GCM 优先 + 明文回退自愈）
# ---------------------------------------------------------------------------
import os as _os
import tempfile as _tf


def _encrypt_with(plain, master="test-master-key-001"):
    from tools.encrypt_secrets import _encrypt
    return _encrypt(master, plain)


def test_get_secret_enc_priority(tmp_path, monkeypatch):
    """存在 .enc 时优先解密读取，返回与明文一致的内容"""
    monkeypatch.setenv("TIANSHU_MASTER_KEY", "test-master-key-001")
    monkeypatch.setattr("core.security._SECRETS_DIR", str(tmp_path))
    plain = "sk-test-abcdef123456"
    with open(tmp_path / "demo_key.txt.enc", "w", encoding="utf-8") as f:
        f.write(_encrypt_with(plain))
    from core.security import get_secret
    assert get_secret("demo_key.txt") == plain


def test_get_secret_decrypt_fail_fallback_plaintext(tmp_path, monkeypatch):
    """.enc 解密失败（主密钥不对）时回退明文，保证系统可用"""
    monkeypatch.setenv("TIANSHU_MASTER_KEY", "wrong-master-key")
    monkeypatch.setattr("core.security._SECRETS_DIR", str(tmp_path))
    with open(tmp_path / "demo_key.txt.enc", "w", encoding="utf-8") as f:
        f.write(_encrypt_with("sk-aaa", master="right-master-key"))
    with open(tmp_path / "demo_key.txt", "w", encoding="utf-8") as f:
        f.write("sk-plaintext-fallback")
    from core.security import get_secret
    assert get_secret("demo_key.txt") == "sk-plaintext-fallback"


def test_get_secret_plaintext_legacy(tmp_path, monkeypatch):
    """无 .enc 时按原逻辑读明文（未迁移兼容）"""
    monkeypatch.setattr("core.security._SECRETS_DIR", str(tmp_path))
    with open(tmp_path / "old_key.txt", "w", encoding="utf-8") as f:
        f.write("sk-legacy")
    from core.security import get_secret
    assert get_secret("old_key.txt") == "sk-legacy"
