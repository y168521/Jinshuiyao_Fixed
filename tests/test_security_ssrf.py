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
