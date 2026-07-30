# -*- coding: utf-8 -*-
"""金水谣系统 - HTTP 路由调度

GuideHandler 类：继承 http.server.SimpleHTTPRequestHandler，
负责 do_GET / do_POST 的顶层异常保护、错误追踪、并分发到各 handler 模块。
"""
import http.server
import json
import os
import urllib.parse
import socket
import ipaddress
import time

from .config import (
    PORT, MAX_BODY, ROOT_DIR,
)
from .utils import log
from .rate_limiter import rate_limiter

# 导入各 handler 模块
from .handlers import health as h_health
from .handlers import ai as h_ai
from .handlers import knowledge as h_knowledge
from .handlers import prediction as h_prediction
from .handlers import static as h_static
from .handlers import sync as h_sync
from .handlers import error_report as h_error_report
from .handlers import scheduler as h_scheduler
from .handlers import lottery as h_lottery
from .handlers import review as h_review
from .handlers import trend as h_trend
from .handlers import backtest as h_backtest
from .handlers import fund as h_fund
from .handlers import stock as h_stock
from .handlers import filter as h_filter


class GuideHandler(http.server.SimpleHTTPRequestHandler):
    """带顶层异常保护、错误追踪、健康检查的 HTTP 处理器"""
    # 类级别请求计数器（所有实例共享）
    _request_count = 0
    _error_count = 0
    _errors_recent = []  # 最近 20 条错误记录
    _start_time = time.time()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    # ------------------------------------------------------------------
    # GET 入口
    # ------------------------------------------------------------------
    def do_GET(self):
        GuideHandler._request_count += 1
        # P0-G3 限流 + 全局异常流量跳闸（/health 健康检查与本地请求放行，其余受控）
        _p = (self.path or "").split("?", 1)[0]
        if _p != "/health":
            _ok, _ra = rate_limiter().allow(self.client_address[0])
            if not _ok:
                self.send_response(429)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Retry-After", str(_ra))
                self.end_headers()
                self.wfile.write(json.dumps({"error": "请求过于频繁，请稍后重试", "ok": False}, ensure_ascii=False).encode("utf-8"))
                return
        try:
            self._do_GET_impl()
        except Exception as e:
            GuideHandler._error_count += 1
            err = f'[{__import__("datetime").datetime.now().isoformat()}] GET {self.path} → {type(e).__name__}: {e}'
            GuideHandler._errors_recent.append(err)
            if len(GuideHandler._errors_recent) > 20:
                GuideHandler._errors_recent.pop(0)
            log(f'[ERROR-GET] {err}')
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "服务器内部错误，请稍后重试", "ok": False}, ensure_ascii=False).encode('utf-8'))
            except Exception:
                pass  # 连接可能已断开

    def _do_GET_impl(self):
        parsed = urllib.parse.urlparse(self.path)

        # /health — 健康检查端点（供前端定时探测 + 运维监控）
        if parsed.path == '/health':
            h_health.handle_health(self)
            return

        # /status — 子系统状态API（兼容旧前端）
        if parsed.path == '/status':
            h_health.handle_status(self)
            return

        # /api/fund-notification — 获取基金日报通知状态
        if parsed.path == '/api/fund-notification':
            h_health.handle_fund_notification(self)
            return

        # /api/fund-notification/read — 标记通知为已读
        if parsed.path == '/api/fund-notification/read':
            h_health.handle_fund_notification_read(self)
            return

        # /api/ip — 获取本机局域网IP（手机端用）
        if parsed.path == '/api/ip':
            h_health.handle_ip(self)
            return

        # /api/test-results — 获取最近测试结果
        if parsed.path == '/api/test-results':
            h_health.handle_test_results(self)
            return

        # /api/selfcheck — 获取最近一次启动自检报告（独特测试工程）
        if parsed.path == '/api/selfcheck':
            h_health.handle_selfcheck(self)
            return

        # /api/selfcheck/history — 获取自检历史日志（最近10条）
        if parsed.path == '/api/selfcheck/history':
            h_health.handle_selfcheck_history(self)
            return

        # /api/ai/mode — 获取当前AI运行模式（online/offline）
        if parsed.path == '/api/ai/mode':
            h_health.handle_ai_mode(self)
            return

        # /api/ai/mode/set — 切换AI运行模式（POST请求）
        if parsed.path == '/api/ai/mode/set':
            h_health.handle_ai_mode_set_get(self)
            return

        # /sync — 跨设备任务同步看板（HTML）
        if parsed.path == '/sync':
            h_sync.handle_sync_dashboard(self)
            return

        # /sync-api/state — 读取跨设备任务同步状态与总账
        if parsed.path == '/sync-api/state':
            h_sync.handle_sync_state(self)
            return

        # /api/ai/status — 获取AI服务详细状态
        if parsed.path == '/api/ai/status':
            h_health.handle_ai_status(self)
            return

        # /api/status — AI服务状态（GET兼容，前端ai-agent.html用GET探测）
        if parsed.path == '/api/status':
            h_ai.handle_post_status(self)
            return
        if parsed.path == '/api/model_status':
            h_ai.handle_model_status(self)
            return
        # /api/telemetry — 统一遥测查询（最近调用记录 + 聚合，供可观测面板）
        if parsed.path == '/api/telemetry':
            try:
                from core.telemetry import recent, summary
                self._send_json({"ok": True, "summary": summary(), "events": recent(200)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        # /api/theme — 主题分层读写（GET 取当前主题+预设；POST 存用户自选）
        if parsed.path == '/api/theme':
            h_ai.handle_theme(self, parsed)
            return

        # /api/route — 任务智能路由（只读"判断"，不真正执行；对局域网开放）
        if parsed.path.startswith('/api/route'):
            h_ai.handle_route(self, parsed)
            return

        # /api/project/scan — 项目自动扫描（只读，对局域网开放）
        if parsed.path.startswith('/api/project/scan'):
            h_ai.handle_project_scan(self, parsed)
            return

        # /api/project/recommend — 仅生成四维推荐（只读）
        if parsed.path.startswith('/api/project/recommend'):
            h_ai.handle_project_recommend(self, parsed)
            return

        # /api/memory — AI 记忆读取（GET，只读，对局域网开放）
        if parsed.path == '/api/memory':
            h_knowledge.handle_get_memory(self)
            return

        # /api/user-kb/list — 个人知识库卡片列表
        if parsed.path.startswith('/api/user-kb/list'):
            h_knowledge.handle_user_kb_list(self)
            return

        # /api/user-kb/detail — 个人知识库卡片详情
        if parsed.path.startswith('/api/user-kb/detail'):
            h_knowledge.handle_user_kb_detail(self, parsed)
            return

        # /api/user-kb/stats — 个人知识库统计
        if parsed.path.startswith('/api/user-kb/stats'):
            h_knowledge.handle_user_kb_stats(self)
            return

        # /api/knowledge/crosslinks/stats — 交叉链接统计
        if parsed.path == '/api/knowledge/crosslinks/stats':
            h_knowledge.handle_crosslinks_stats(self)
            return

        # /api/knowledge/crosslinks/all — 全部交叉链接
        if parsed.path == '/api/knowledge/crosslinks/all':
            h_knowledge.handle_crosslinks_all(self)
            return

        # /api/knowledge/crosslinks?lib=&id= — 查询某卡片的跨库链接
        if parsed.path.startswith('/api/knowledge/crosslinks'):
            h_knowledge.handle_crosslinks_get(self, parsed)
            return

        # /api/knowledge/graph — 知识图谱数据（可视化）
        if parsed.path == '/api/knowledge/graph':
            h_knowledge.handle_kg_data(self, parsed)
            return

        # /api/knowledge/graph/neighbors — 实体关联查询
        if parsed.path.startswith('/api/knowledge/graph/neighbors'):
            h_knowledge.handle_kg_neighbors(self, parsed)
            return

        # /api/knowledge/graph/top — 最重要实体
        if parsed.path == '/api/knowledge/graph/top':
            h_knowledge.handle_kg_top(self)
            return
        # /api/knowledge/graph/search — 图谱三元组检索（实体/关系）
        if parsed.path.startswith('/api/knowledge/graph/search'):
            h_knowledge.handle_kg_search(self, parsed)
            return

        # /api/knowledge/vector/search — 语义向量召回（离线 VSM）
        if parsed.path.startswith('/api/knowledge/vector/search'):
            h_knowledge.handle_knowledge_vector_search(self, parsed)
            return

        # /api/knowledge/tags/validate — 经验箱标签校验（白名单+一致性）
        if parsed.path.startswith('/api/knowledge/tags/validate'):
            h_knowledge.handle_knowledge_tags_validate(self, parsed)
            return

        # /api/knowledge/vector/rebuild — 手动重建语义向量索引（P3-4，POST 仅本机）
        if parsed.path.startswith('/api/knowledge/vector/rebuild'):
            h_knowledge.handle_knowledge_vector_rebuild(self)
            return

        # /api/scheduler/status — 定时任务运行状态
        if parsed.path == '/api/scheduler/status':
            h_scheduler.handle_scheduler_status(self)
            return

        # /api/scheduler/log — 定时任务执行日志
        if parsed.path.startswith('/api/scheduler/log'):
            h_scheduler.handle_scheduler_log(self, parsed)
            return

        # /api/lottery/sources-health — 彩票数据源健康 + 数据新鲜度（S6 可观测）
        if parsed.path == '/api/lottery/sources-health':
            h_lottery.handle_sources_health(self)
            return

        # /lottery-sources-health — 数据源健康仪表盘页面（S6 可观测）
        if parsed.path == '/lottery-sources-health':
            h_lottery.handle_sources_health_page(self)
            return

        # /api/lottery/reference — 福彩3D/排列三 多维参考特征 + SQI（不生成号码）
        if parsed.path.startswith('/api/lottery/reference'):
            h_lottery.handle_reference(self)
            return

        # /api/lottery/math-model — 数学模型选号（六维：组合/统计/蒙特卡洛/时序/校准）
        if parsed.path.startswith('/api/lottery/math-model'):
            h_lottery.handle_math_model(self)
            return

        # /api/trend/data — 走势图数据（分片）
        if parsed.path == '/api/trend/data':
            h_trend.handle_trend_data(self, parsed)
            return

        # /api/trend/freshness — 走势图数据新鲜度
        if parsed.path == '/api/trend/freshness':
            h_trend.handle_trend_freshness(self)
            return

        # /api/review/dashboard — 审查效果仪表盘数据
        if parsed.path == '/api/review/dashboard':
            h_review.handle_review_dashboard_api(self, parsed)
            return

        # /api/review/patterns — 查模式库
        if parsed.path == '/api/review/patterns':
            h_review.handle_review_patterns_api(self, parsed)
            return

        # /review-dashboard — 审查仪表盘页面（HTML）
        if parsed.path == '/review-dashboard':
            h_review.handle_review_dashboard_page(self)
            return

        # /api/stock/* — 股票子系统专用路由（拆分自 backtest.py）
        if parsed.path == '/api/stock/screen':
            h_stock.handle_screen(self, parsed)
            return
        if parsed.path == '/api/stock/backtest':
            h_stock.handle_backtest(self, parsed)
            return
        if parsed.path == '/api/stock/status':
            h_stock.handle_status(self, parsed)
            return
        if parsed.path == '/api/stock/factors':
            h_stock.handle_factors(self, parsed)
            return

        # /api/fund/* — 基金子系统专用路由（拆分自 backtest.py）
        if parsed.path == '/api/fund/backtest':
            h_fund.handle_backtest(self, parsed)
            return
        if parsed.path == '/api/fund/compare':
            h_fund.handle_compare(self, parsed)
            return
        if parsed.path == '/api/fund/strategies':
            h_fund.handle_strategies(self, parsed)
            return
        if parsed.path == '/api/fund/compare-strategies':
            h_fund.handle_compare_strategies(self, parsed)
            return
        if parsed.path == '/api/fund/status':
            h_fund.handle_status(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio':
            h_fund.handle_portfolio_list(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/add':
            h_fund.handle_portfolio_add(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/update':
            h_fund.handle_portfolio_update(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/remove':
            h_fund.handle_portfolio_remove(self, parsed)
            return

        # /api/backtest — 统一股基回测（type=fund|stock，默认 fund）
        if parsed.path == '/api/backtest':
            h_backtest.handle_backtest(self, parsed)
            return

        # /api/fund-backtest — 基金回测（买入持有/均线择时/定投）
        if parsed.path == '/api/fund-backtest':
            h_backtest.handle_fund_backtest(self, parsed)
            return

        # /api/fund-compare — 基金横向对比视图（多基金同屏对比）
        if parsed.path == '/api/fund-compare':
            h_backtest.handle_fund_compare(self, parsed)
            return

        # /api/prediction/stats — 预测统计（按域聚合 + 趋势）
        if parsed.path == '/api/prediction/stats':
            h_prediction.handle_prediction_stats(self)
            return

        # /api/prediction/history — 各域历史命中率趋势 + 置信度（R1 可视化）
        if parsed.path == '/api/prediction/history':
            h_prediction.handle_prediction_history(self)
            return

        # /open?file=xxx — 打开文件（返回JSON，前端fetch静默调用）
        # 注意：/open 路由必须在 / 之前检查，否则 / 路径中的 return 会导致此处死代码
        if parsed.path == '/open':
            h_static.handle_open(self, parsed)
            return

        # /api/audit — 获取最近一次自动模型审查报告
        if parsed.path == '/api/audit':
            h_static.handle_audit(self)
            return

        # /api/audit-trail — 操作留痕看板数据
        if parsed.path == '/api/audit-trail':
            h_static.handle_audit_trail(self)
            return

        # 已知页面路由（批量查表）
        if h_static.handle_page(self, parsed.path):
            return

        # / — 根路径：直接返回金水谣助手门户（零基础中文主入口）
        if parsed.path == '/':
            if h_static.handle_root(self):
                return
            return super().do_GET()

        # 其他请求 — 从模型根目录(ROOT_DIR)或 jinshuiyao-guide(HTML_DIR) 提供静态文件
        return self._serve_static()

    # ------------------------------------------------------------------
    # POST 入口
    # ------------------------------------------------------------------
    def do_POST(self):
        """处理POST请求（带顶层异常保护）"""
        GuideHandler._request_count += 1
        # P0-G3 限流 + 全局异常流量跳闸（本地请求放行，其余受控）
        _ok, _ra = rate_limiter().allow(self.client_address[0])
        if not _ok:
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", str(_ra))
            self.end_headers()
            self.wfile.write(json.dumps({"error": "请求过于频繁，请稍后重试", "ok": False}, ensure_ascii=False).encode("utf-8"))
            return
        try:
            self._do_POST_impl()
        except Exception as e:
            GuideHandler._error_count += 1
            err = f'[{__import__("datetime").datetime.now().isoformat()}] POST {self.path} → {type(e).__name__}: {e}'
            GuideHandler._errors_recent.append(err)
            if len(GuideHandler._errors_recent) > 20:
                GuideHandler._errors_recent.pop(0)
            log(f'[ERROR-POST] {err}')
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "服务器内部错误，请稍后重试", "ok": False}, ensure_ascii=False).encode('utf-8'))
            except Exception:
                pass

    def _do_POST_impl(self):
        """POST 请求的实际路由逻辑"""
        parsed = urllib.parse.urlparse(self.path)

        # 统一请求体上限（防超大 body 拖垮服务器 / 内存耗尽）
        try:
            _cl = int(self.headers.get('Content-Length', 0) or 0)
        except Exception:
            _cl = 0
        if _cl > MAX_BODY:
            self._send_json({"ok": False, "error": "请求体过大（上限 %d 字节）" % MAX_BODY}, 413)
            return

        # /api/route — 任务智能路由（POST 同样支持，复用 GET 的判断逻辑）
        if parsed.path.startswith('/api/route'):
            h_ai.handle_route(self, parsed)
            return

        # /api/ask — 智能代码助手问答（可能调用 DeepSeek 付费，仅允许本机）
        if parsed.path.startswith('/api/ask'):
            h_ai.handle_ask(self)
            return

        # /api/chat — AI体对话接口
        if parsed.path == '/api/chat':
            h_ai.handle_chat(self)
            return

        # /api/prediction/* — 预测记录与复盘接口
        if parsed.path == '/api/prediction/record':
            h_prediction.handle_prediction_record(self)
            return

        if parsed.path == '/api/prediction/list':
            h_prediction.handle_prediction_list(self)
            return

        if parsed.path == '/api/prediction/outcome':
            h_prediction.handle_prediction_outcome(self)
            return

        # /api/status — AI服务状态
        if parsed.path == '/api/status':
            h_ai.handle_post_status(self)
            return
        if parsed.path == '/api/model_status':
            h_ai.handle_model_status(self)
            return
        # /api/theme — 主题分层读写（GET 取当前主题+预设；POST 存用户自选）
        if parsed.path == '/api/theme':
            h_ai.handle_theme(self, parsed)
            return

        # /api/ai/mode/set — 切换AI运行模式（POST，JSON body）
        if parsed.path == '/api/ai/mode/set':
            h_health.handle_ai_mode_set_post(self)
            return

        # /api/review/trigger — 触发代码审查
        if parsed.path == '/api/review/trigger':
            h_review.handle_review_trigger(self, parsed)
            return

        # /api/review/feedback — 提交审查反馈（自学习）
        if parsed.path == '/api/review/feedback':
            h_review.handle_review_feedback(self, parsed)
            return

        # /api/stock/* — 股票子系统专用路由（POST）
        if parsed.path == '/api/stock/screen':
            h_stock.handle_screen(self, parsed)
            return
        if parsed.path == '/api/stock/backtest':
            h_stock.handle_backtest(self, parsed)
            return
        if parsed.path == '/api/stock/status':
            h_stock.handle_status(self, parsed)
            return
        if parsed.path == '/api/stock/factors':
            h_stock.handle_factors(self, parsed)
            return

        # /api/fund/* — 基金子系统专用路由（POST）
        if parsed.path == '/api/fund/backtest':
            h_fund.handle_backtest(self, parsed)
            return
        if parsed.path == '/api/fund/compare':
            h_fund.handle_compare(self, parsed)
            return
        if parsed.path == '/api/fund/strategies':
            h_fund.handle_strategies(self, parsed)
            return
        if parsed.path == '/api/fund/compare-strategies':
            h_fund.handle_compare_strategies(self, parsed)
            return
        if parsed.path == '/api/fund/status':
            h_fund.handle_status(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio':
            h_fund.handle_portfolio_list(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/add':
            h_fund.handle_portfolio_add(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/update':
            h_fund.handle_portfolio_update(self, parsed)
            return
        if parsed.path == '/api/fund/portfolio/remove':
            h_fund.handle_portfolio_remove(self, parsed)
            return

        # /api/filter/smart — 智能缩水过滤
        if parsed.path == '/api/filter/smart':
            h_filter.handle_smart_filter(self)
            return

        # /api/backtest — 统一股基回测（type=fund|stock，POST）
        if parsed.path == '/api/backtest':
            h_backtest.handle_backtest(self, parsed)
            return

        # /api/fund-backtest — 基金回测（POST）
        if parsed.path == '/api/fund-backtest':
            h_backtest.handle_fund_backtest(self, parsed)
            return

        # /api/fund-compare — 基金横向对比视图（POST）
        if parsed.path == '/api/fund-compare':
            h_backtest.handle_fund_compare(self, parsed)
            return

        # /api/extract — 视频文案提取接口
        if parsed.path == '/api/extract':
            h_ai.handle_extract(self)
            return

        # /api/refine — 内容提炼接口
        if parsed.path == '/api/refine':
            h_ai.handle_refine(self)
            return

        # ===== 知识库接口 =====

        # /api/knowledge/stats — 知识库统计
        if parsed.path == '/api/knowledge/stats':
            h_knowledge.handle_knowledge_stats(self)
            return

        # /api/knowledge/search — 搜索知识
        if parsed.path.startswith('/api/knowledge/search'):
            h_knowledge.handle_knowledge_search(self, parsed)
            return

        # /api/knowledge/list — 知识卡片列表
        if parsed.path.startswith('/api/knowledge/list'):
            h_knowledge.handle_knowledge_list(self, parsed)
            return

        # /api/knowledge/add — 添加知识卡片
        if parsed.path == '/api/knowledge/add':
            h_knowledge.handle_knowledge_add(self)
            return

        # /api/user-kb/add — 新增个人知识库卡片（前端"新建卡片"按钮）
        if parsed.path == '/api/user-kb/add':
            h_knowledge.handle_user_kb_add(self)
            return

        # /api/knowledge/extract-archive — URL提取并归档
        if parsed.path == '/api/knowledge/extract-archive':
            h_knowledge.handle_knowledge_extract_archive(self)
            return

        # /api/knowledge/crosslinks/discover — 触发双库交叉链接自动发现
        if parsed.path == '/api/knowledge/crosslinks/discover':
            h_knowledge.handle_crosslinks_discover(self)
            return

        # /api/knowledge/graph/build — 重建知识图谱
        if parsed.path == '/api/knowledge/graph/build':
            h_knowledge.handle_kg_build(self)
            return

        # /api/video/ingest — 视频文案提取并归档到「闭环成长」知识库
        if parsed.path == '/api/video/ingest':
            h_knowledge.handle_video_ingest(self)
            return

        # /api/memory — AI 记忆 新增/删除/编辑（POST，写操作仅本机）
        if parsed.path == '/api/memory':
            h_knowledge.handle_post_memory(self)
            return

        # /api/run-tests — 运行自动化测试
        if parsed.path == '/api/run-tests':
            h_static.handle_run_tests(self)
            return

        # 跨设备同步：记录一条任务完成状态（写入坚果云共享文件 → 同步到另一台设备）
        if parsed.path == '/sync-api/task':
            h_sync.handle_sync_task(self)
            return

        # 跨设备同步：修改本机设备名（仅本机）
        if parsed.path == '/sync-api/identity':
            h_sync.handle_sync_identity(self)
            return

        # /api/error-report — 前端JS错误上报（仅本机，写入日志文件）
        if parsed.path == '/api/error-report':
            h_error_report.handle_error_report(self)
            return

        self._send_json({"error": "未知接口"}, 404)

    # ------------------------------------------------------------------
    # 工具方法（被 handler 函数调用，保留在类上以访问 self）
    # ------------------------------------------------------------------
    def _is_local(self):
        """判断请求是否来自本机（127.0.0.1 / ::1）。
        执行类接口（打开/运行文件）仅允许本机调用，防止局域网越权执行。"""
        try:
            ip = self.client_address[0]
            return ip in ('127.0.0.1', '::1', 'localhost')
        except Exception:
            return False

    def _is_same_origin(self, origin):
        """判断请求 Origin 是否与本服务同源（同主机 + 同端口）。
        用于 CORS 反射与 /open 同源校验，挡住本机浏览器中的恶意跨域网页。"""
        try:
            p = urllib.parse.urlparse(origin)
            if p.scheme not in ('http', 'https'):
                return False
            host = (p.hostname or '').lower()
            if host in ('127.0.0.1', 'localhost', '::1', '[::1]'):
                try:
                    op = p.port
                except Exception:
                    op = 80 if p.scheme == 'http' else 443
                # 端口须与当前服务一致，避免其他本机服务伪造
                return op == getattr(self.server, 'server_port', None)
            return False
        except Exception:
            return False

    def _set_cors(self):
        """P0-① 安全修复：CORS 仅当请求 Origin 与本机服务同源时才回显，
        去掉全局 '*'，避免恶意跨域网页读取响应。"""
        origin = self.headers.get('Origin')
        if origin and self._is_same_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)

    def _is_safe_http_url(self, url):
        """校验 URL 是否允许被服务器代取：仅允许 http/https，且解析后的 IP 不得为
        环回/私网/链路本地/保留/组播地址（防 SSRF 访问内网或云元数据 169.254.169.254）。"""
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
                if net.is_loopback or net.is_private or net.is_link_local or net.is_reserved or net.is_multicast:
                    return False, "禁止访问内网/保留地址"
            return True, ""
        except Exception as e:
            return False, "URL 校验异常：" + str(e)

    def _send_json(self, data, code=200):
        """发送JSON响应"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._set_cors()  # P0-① 安全修复：CORS 仅同源反射，去掉全局 '*'
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _read_body(self):
        """读取 POST 请求体（UTF-8 JSON 字符串）"""
        cl = int(self.headers.get('Content-Length', 0))
        if cl <= 0:
            return ''
        return self.rfile.read(cl).decode('utf-8', errors='replace')

    # 常见静态文件 MIME 类型
    _MIME = {
        '.html': 'text/html; charset=utf-8',
        '.htm':  'text/html; charset=utf-8',
        '.js':   'application/javascript; charset=utf-8',
        '.mjs':  'application/javascript; charset=utf-8',
        '.css':  'text/css; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.png':  'image/png',
        '.jpg':  'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif':  'image/gif',
        '.svg':  'image/svg+xml',
        '.ico':  'image/x-icon',
        '.webp': 'image/webp',
        '.txt':  'text/plain; charset=utf-8',
        '.md':   'text/markdown; charset=utf-8',
        '.csv':  'text/csv; charset=utf-8',
        '.py':   'text/plain; charset=utf-8',
        '.bat':  'application/octet-stream',
        '.exe':  'application/octet-stream',
        '.pdf':  'application/pdf',
        '.zip':  'application/zip',
    }

    def _send_file(self, fp):
        """以正确 MIME 发送一个静态文件"""
        import os.path as _osp
        ext = _osp.splitext(fp)[1].lower()
        mime = self._MIME.get(ext, 'application/octet-stream')
        try:
            with open(fp, 'rb') as f:
                data = f.read()
        except Exception as e:
            self._send_json({"error": f"读取失败: {e}"}, 500)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self._set_cors()  # P0-① 安全修复：CORS 仅同源反射，去掉全局 '*'
        self.end_headers()
        self.wfile.write(data)

    # === 静态服务安全策略（P0-1 修复：原仅挡 '..'，可下载密钥/源码）===
    # 危险后缀黑名单：一律拒绝（即便不在白名单逻辑内）
    _STATIC_DANGER_EXT = {
        '.py', '.pyc', '.pyw', '.key', '.pem', '.crt', '.cer', '.db',
        '.sqlite', '.sqlite3', '.bat', '.exe', '.sh', '.ps1', '.dll',
        '.so', '.env', '.pfx', '.keystore', '.p12',
    }
    # 密钥/凭证文件名黑名单（含 api_key 的 config.json 等）
    import re as _re_secret
    # 注意：用前缀/特定后缀匹配，避免锚点 $ 漏掉带扩展名的密钥文件
    # （如 deepseek_key.txt 不能因"不以 deepseek_key 结尾"而漏拦）；
    # 也不能用裸 _key 子串（会误伤 monkey.txt 等），故限定 _key.txt$/_cookie.txt$。
    _SECRET_NAME_RE = _re_secret.compile(
        r'(^deepseek_key|^douyin_cookie|_secret|_token|secrets|credentials|'
        r'config\.json$|_key\.txt$|_cookie\.txt$)')
    # 安全静态资源后缀白名单：默认拒绝其它一切
    _STATIC_ALLOW_EXT = {
        '.html', '.htm', '.js', '.mjs', '.css', '.png', '.jpg', '.jpeg',
        '.gif', '.svg', '.ico', '.webp', '.woff', '.woff2', '.ttf', '.map',
        '.json', '.txt', '.md', '.csv', '.pdf', '.zip',
    }

    def _serve_static(self):
        """多根静态服务：仅允许白名单内的安全前端资源，显式屏蔽密钥/源码等敏感文件。

        安全加固（P0-1，JS-20260723-37）：原实现仅挡 '..'、未限制目录/后缀，
        而 ROOT_DIR 实为项目父目录，导致 GET /Jinshuiyao_Fixed/deepseek_key.txt、
        GET /Jinshuiyao_Fixed/AI代码助手(DeepSeek备用)/config.json（含 api_key）、
        .py 源码等均可被下载。现改为：危险后缀黑名单 + 密钥文件名黑名单 + 安全后缀
        白名单，默认拒绝一切未显式允许的类型。
        """
        from .config import HTML_DIR as _HTML_DIR
        rel = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).lstrip('/')
        # 防目录穿越：拒绝任何包含 '..' 的路径段
        norm = rel.replace('\\', '/')
        if '..' in norm.split('/'):
            self._send_json({"error": "非法路径（禁止目录穿越）"}, 404)
            return
        basename = norm.rsplit('/', 1)[-1].lower()
        ext = os.path.splitext(basename)[1]
        # 1) 危险后缀黑名单
        if ext in GuideHandler._STATIC_DANGER_EXT:
            self._send_json({"error": "禁止访问该类型文件（安全策略）"}, 403)
            return
        # 2) 密钥/凭证文件名黑名单
        if GuideHandler._SECRET_NAME_RE.search(basename):
            self._send_json({"error": "禁止访问敏感文件（安全策略）"}, 403)
            return
        # 3) 安全后缀白名单（默认拒绝）
        if ext not in GuideHandler._STATIC_ALLOW_EXT:
            self._send_json({"error": "不支持的文件类型（安全策略）"}, 403)
            return
        candidates = [os.path.join(ROOT_DIR, rel), os.path.join(_HTML_DIR, rel)]
        for fp in candidates:
            if os.path.isfile(fp):
                self._send_file(fp)
                return
        self._send_json({"error": f"文件不存在: {rel}"}, 404)

    def log_message(self, format, *args):
        """仅记录异常状态码（4xx/5xx），静默正常请求避免日志膨胀"""
        msg = format % args
        if ' 200 ' not in msg and ' 302 ' not in msg:
            log(f'[HTTP] {msg}')
