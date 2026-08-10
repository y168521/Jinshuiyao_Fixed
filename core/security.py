# -*- coding: utf-8 -*-
"""金水谣 · 安全基础（单一真源）

- is_safe_http_url：SSRF 防护的核心判定（JS-20260807-01 下沉）。
- get_secret：API 密钥读取统一入口（JS-20260810-09 收口：原 ai_service.get_api_key /
  free_model_pool._read_secret / adaptive_models 各读各的，现统一委托本函数）。

仅依赖标准库，不反向依赖 server 包，故 server 与 core 均可安全复用，无循环依赖。
"""
import os
import socket
import ipaddress
import urllib.parse

_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")


def get_secret(name, env=None):
    """统一密钥读取单一真源。

    读取顺序：
      1. name 为绝对路径且文件存在 → 直读（内容空/异常则返回空串）
      2. ~/.jinshuiyao-secrets/<name> 存在 → 直读
      3. env 指定环境变量 → 读取（如 DEEPSEEK_API_KEY）

    安全铁律（JS-20260724）：密钥只允许放安全目录 ~/.jinshuiyao-secrets/ 或环境变量，
    禁止回退项目根/CWD 明文（项目在坚果云同步树内，明文密钥会被同步外泄）。

    Args:
        name: 密钥文件名（如 deepseek_key.txt）或绝对路径
        env: 可选环境变量名兜底

    Returns:
        str: 密钥字符串，未找到返回空串
    """
    if not name:
        return ""
    if os.path.isfile(name):
        try:
            with open(name, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    p = os.path.join(_SECRETS_DIR, name)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except Exception:
            pass
    if env:
        v = os.environ.get(env, "")
        if v:
            return v
    return ""


def is_safe_http_url(url):
    """校验 URL 是否允许被服务器代取。

    仅允许 http/https，且解析后的任一 IP 不得为
    环回/私网/链路本地/保留/组播地址（防 SSRF 访问内网或云元数据 169.254.169.254）。

    Returns:
        (bool, str)：是否安全 + 失败原因（安全时原因为空串）。
    """
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, "仅支持 http/https 链接"
        host = (p.hostname or '').strip().lower()
        if not host:
            return False, "无效的域名"
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            return False, "域名解析失败"
        for info in infos:
            ip = info[4][0]
            try:
                net = ipaddress.ip_address(ip)
            except Exception:
                return False, "无法解析的地址"
            if net.is_loopback or net.is_private or net.is_link_local \
                    or net.is_reserved or net.is_multicast:
                return False, "禁止访问内网/保留地址"
        return True, ""
    except Exception as e:
        return False, "URL 校验异常：" + str(e)
