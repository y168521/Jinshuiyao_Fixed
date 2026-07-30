# -*- coding: utf-8 -*-
"""金水谣推送通知模块

支持多渠道推送，当前实现：
- Server酱（Server Chan）：通过 HTTP API 推送微信消息

使用方式：
  1. 在项目根目录创建 sendkey.txt，写入 Server酱 SendKey
  2. 调用 send("标题", "内容") 即可推送微信消息
  3. 无 key 文件时自动跳过，不抛异常

Server酱注册：https://sct.ftqq.com/
"""
import os
import json
import logging

logger = logging.getLogger('jinshuiyao.notifier')

_SENDKEY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sendkey.txt')
_SENDKEY = None

def _load_sendkey():
    """从 sendkey.txt 加载 Server酱 SendKey"""
    global _SENDKEY
    try:
        if os.path.isfile(_SENDKEY_PATH):
            with open(_SENDKEY_PATH, 'r', encoding='utf-8') as f:
                key = f.read().strip()
            import re
            if re.match(r'^SCT[A-Za-z0-9]{10,}$', key):
                _SENDKEY = key
                return True
        return False
    except Exception:
        return False

def is_available():
    """检查推送渠道是否可用"""
    if _SENDKEY is None:
        _load_sendkey()
    return _SENDKEY is not None

def send(title, content="", channel="serverchan"):
    """发送推送通知

    Args:
        title: 通知标题（必填）
        content: 通知内容（可选，支持Markdown）
        channel: 推送渠道，默认 serverchan

    Returns:
        dict: {"ok": True/False, "msg": 状态描述}
    """
    if _SENDKEY is None:
        if not _load_sendkey():
            logger.debug("推送跳过：未配置 sendkey.txt")
            return {"ok": False, "msg": "未配置 sendkey.txt"}

    if channel == "serverchan":
        return _send_serverchan(title, content)
    else:
        return {"ok": False, "msg": f"不支持的推送渠道: {channel}"}

def _send_serverchan(title, content):
    """通过 Server酱 推送微信消息

    API: POST https://sctapi.ftqq.com/{SendKey}.send
    """
    if not title:
        return {"ok": False, "msg": "标题不能为空"}

    try:
        import urllib.request, urllib.parse
        data = urllib.parse.urlencode({
            "title": title,
            "desp": content or "",
        }).encode('utf-8')
        url = f"https://sctapi.ftqq.com/{_SENDKEY}.send"
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get("code") == 0:
            logger.info(f"微信推送成功: {title[:30]}")
            return {"ok": True, "msg": "推送成功"}
        else:
            err = result.get("message", "未知错误")
            logger.warning(f"微信推送失败: {err}")
            return {"ok": False, "msg": f"推送失败: {err}"}
    except Exception as e:
        logger.warning(f"微信推送异常: {e}")
        return {"ok": False, "msg": str(e)}

def notify_fund_report(date, summary, report_path=""):
    """基金日报完成时推送通知"""
    if not is_available():
        return
    title = f"📊 金水谣基金日报 - {date}"
    content = f"""## 基金日报已生成

**日期**: {date}

**摘要**: {summary}

"""
    if report_path:
        content += f"报告文件: {report_path}"
    send(title, content)

def notify_startup(ip="", port=18888):
    """系统启动时推送通知"""
    if not is_available():
        return
    import datetime
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = f"🚀 金水谣系统已启动"
    content = f"""## 系统启动通知

**时间**: {now}
**端口**: {port}

"""
    if ip:
        content += f"**本机IP**: {ip}\n**手机访问**: http://{ip}:{port}/\n"
    else:
        content += "**访问地址**: http://localhost:{}/\n".format(port)
    send(title, content)

def notify_error(subsystem, error_msg):
    """系统异常时推送告警"""
    if not is_available():
        return
    import datetime
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = f"⚠️ 金水谣系统告警 - {subsystem}"
    content = f"""## 系统异常告警

**子系统**: {subsystem}
**时间**: {now}
**错误**: {error_msg}
"""
    send(title, content)
