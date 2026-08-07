# -*- coding: utf-8 -*-
"""金水谣 · 网络安全基础校验（单一真源）

SSRF 防护的核心判定：一个外部 URL 是否允许被服务器代取。

此前该逻辑在 ``server/router.py`` 与 ``core/video_extractor.py`` 各写一份（近乎复制），
本次下沉为唯一实现，杜绝两处漂移（JS-20260807-01）。

仅依赖标准库，不反向依赖 server 包，故 server 与 core 均可安全复用，无循环依赖。
"""
import socket
import ipaddress
import urllib.parse


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
