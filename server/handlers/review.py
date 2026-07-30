# -*- coding: utf-8 -*-
"""金水谣系统 - 审查 API 路由处理

路由：
  POST /api/review/trigger        — 触发全量/增量审查
  POST /api/review/feedback/:id   — 提交反馈（自学习）
  GET  /api/review/dashboard      — 审查效果仪表盘数据
  GET  /api/review/patterns       — 查模式库
  GET  /review-dashboard          — 审查仪表盘页面（HTML）
"""
import json
import os
import sys
import importlib

from ..config import BASE_DIR, HTML_DIR
from ..utils import log

# ─── 动态导入自学习模块（在 tools/ 下，不在 handlers/ 下）───
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

_review_learning = importlib.import_module("review_learning")

_handle_feedback = _review_learning.handle_review_feedback
_handle_trigger = _review_learning.handle_review_trigger
_handle_dashboard = _review_learning.handle_review_dashboard
_handle_patterns = _review_learning.handle_review_patterns


def handle_review_trigger(handler, parsed):
    """POST /api/review/trigger — 触发审查"""
    _handle_trigger(handler, parsed)


def handle_review_feedback(handler, parsed):
    """POST /api/review/feedback — 提交审查反馈"""
    _handle_feedback(handler, parsed)


def handle_review_dashboard_api(handler, parsed):
    """GET /api/review/dashboard — 审查仪表盘数据"""
    _handle_dashboard(handler, parsed)


def handle_review_patterns_api(handler, parsed):
    """GET /api/review/patterns — 查模式库"""
    _handle_patterns(handler, parsed)


def handle_review_dashboard_page(handler):
    """GET /review-dashboard — 审查仪表盘页面"""
    page_file = os.path.join(HTML_DIR, "review-dashboard.html")
    if os.path.isfile(page_file):
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.end_headers()
        with open(page_file, 'rb') as f:
            handler.wfile.write(f.read())
    else:
        handler._send_json({"error": "审查仪表盘页面不存在"}, 404)
