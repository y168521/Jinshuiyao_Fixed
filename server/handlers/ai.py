# -*- coding: utf-8 -*-
"""金水谣系统 - AI 对话与智能路由端点

路由：
  POST /api/chat         — AI 体对话
  POST /api/ask          — 智能代码助手问答（DeepSeek 付费，仅本机）
  GET/POST /api/route    — 任务智能路由（判断走免费路径还是付费路径）
  GET /api/project/scan  — 项目自动扫描
  GET /api/project/recommend — 四维推荐
  POST /api/status       — AI 服务状态（POST 变体）
  POST /api/extract      — 视频文案提取
  POST /api/refine       — 内容提炼
"""
import json
import os
import urllib.parse

from ..config import BASE_DIR
from ..utils import log, run_external
from .prediction import record_prediction


def handle_chat(handler):
    """POST /api/chat — AI体对话接口"""
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length > 10000:
        handler._send_json({"error": "消息过长"}, 400)
        return
    body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return

    user_input = data.get('message', '').strip()
    if not user_input:
        handler._send_json({"error": "消息不能为空"}, 400)
        return

    # 调用AI体（包裹接口级总超时熔断，防止外部 API 卡死线程）
    def _do_chat():
        try:
            from core.ai_agent import get_agent
            agent = get_agent()
            reply = agent.chat(user_input)
        except Exception as e:
            return ({"reply": f"处理异常：{e}", "ok": False}, 200)
        # 自动沉淀预测记录（失败不影响聊天）
        try:
            record_prediction(user_input, reply)
        except Exception:
            pass
        model_used = getattr(agent, '_last_model_used', None)
        return {"reply": reply, "ok": True, "model_used": model_used}

    resp, status = run_external(_do_chat, "chat")
    handler._send_json(resp, status)


def handle_ask(handler):
    """POST /api/ask — 智能代码助手问答（可能调用 DeepSeek 付费，仅允许本机）"""
    if not handler._is_local():
        handler._send_json({"ok": False, "error": "安全限制：问答仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0) or 0)
        raw = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else ''
        data = json.loads(raw) if raw else {}
    except Exception as e:
        handler._send_json({"ok": False, "error": "请求解析失败：" + str(e)})
        return

    def _do_ask():
        return _smart_ask(handler, data.get('question', ''), data.get('path', ''),
                          selected=data.get('selected'), enable_kb=data.get('enable_kb'))
    resp, status = run_external(_do_ask, "ask")
    handler._send_json(resp, status)


def handle_route(handler, parsed):
    """GET/POST /api/route — 任务智能路由：只读"判断"，不真正执行。GET 取 ?task=，POST 取 JSON body。
    返回 {path, reason, scores, cost}。这是「全局调度中枢」的决策核心，
    专门解决"会不会乱花 DeepSeek"的担忧——cost=paid 才走付费路径。"""
    try:
        from jinshuiyao_router import classify
        task = urllib.parse.parse_qs(parsed.query).get('task', [''])[0]
        if handler.command == 'POST':
            try:
                cl = int(handler.headers.get('Content-Length', 0))
                raw = handler.rfile.read(cl).decode('utf-8', errors='replace')
                d = json.loads(raw) if raw else {}
                task = d.get('task', task)
            except Exception:
                pass
        if not (task or '').strip():
            handler._send_json({"path": "clarify", "reason": "未提供任务描述，无法路由。",
                                "scores": {}, "cost": "free"})
            return
        r = dict(classify(task))
        r["cost"] = "paid" if r["path"] == "deepseek" else "free"
        handler._send_json(r)
    except Exception as e:
        handler._send_json({"error": f"路由判断失败：{e}"}, 500)


def handle_project_scan(handler, parsed):
    """GET /api/project/scan — 项目自动扫描（只读，限制本机 + BASE_DIR 内）
    输入 ?path=目录；返回目录树 + 文件分级 + 四维推荐。"""
    # P1-⑤ 安全修复：仅本机 + 路径限制在项目根内，防越界枚举泄露
    if not handler._is_local():
        handler._send_json({"error": "安全限制：项目扫描仅允许本机操作。"}, 403)
        return
    qs = urllib.parse.parse_qs(parsed.query)
    raw = qs.get('path', [''])[0] or ''
    # 拒绝绝对路径与 '..' 越界，限制在 BASE_DIR 子树内
    norm = raw.replace('\\', '/')
    if not raw or os.path.isabs(raw) or '..' in norm.split('/'):
        raw = BASE_DIR
    abs_raw = os.path.abspath(raw)
    if not (abs_raw == BASE_DIR or abs_raw.startswith(BASE_DIR + os.sep)):
        abs_raw = BASE_DIR
    handler._send_json(_smart_scan(handler, abs_raw))


def handle_project_recommend(handler, parsed):
    """GET /api/project/recommend — 仅生成四维推荐（只读）"""
    qs = urllib.parse.parse_qs(parsed.query)
    p = qs.get('path', [''])[0]
    try:
        import project_loader, recommender
        scan = project_loader.scan_directory(p)
        if scan.get("error"):
            handler._send_json(scan)
            return
        handler._send_json(recommender.recommend(p, scan["files"]))
    except Exception as e:
        handler._send_json({"error": str(e)})


def handle_post_status(handler):
    """POST /api/status — AI服务状态"""
    try:
        from core.ai_service import get_ai_service
        ai = get_ai_service()
        handler._send_json({"ai": ai.stats})
    except Exception as e:
        handler._send_json({"ai": {"available": False, "error": str(e)}})


def handle_model_status(handler):
    """GET/POST /api/model_status — 返回免费/付费模型可用性与路由策略（供前端状态标签）"""
    try:
        from core.free_model_pool import get_free_provider_cfgs, get_fallback_cfg
        from core.model_router import _load_cfg
        free_cfgs = get_free_provider_cfgs() or []
        fb = get_fallback_cfg() or {}
        cfg = _load_cfg() or {}
        handler._send_json({
            "free_available": bool(free_cfgs),
            "paid_available": bool(fb.get("api_key")),
            "policy": cfg.get("policy", "auto"),
            "free_models": [c.get("name") or c.get("_model_id") for c in free_cfgs],
            "paid_model": fb.get("name") or fb.get("_model_id"),
        })
    except Exception as e:
        handler._send_json({"free_available": False, "paid_available": False,
                            "policy": "auto", "error": str(e)})


def handle_theme(handler, parsed=None):
    """GET/POST /api/theme — 主题分层（客户自选 / 系统默认 / 个人七色）读写接口

    GET  ?user_id=xxx  返回：当前生效主题(vars+source)、内置预设清单、变量含义表
    POST {user_id, vars}  持久化某用户自选主题变量；vars=None 表示清除(回退)
    """
    try:
        from core import theme_manager as tm
    except Exception as e:
        handler._send_json({"error": "主题模块未就绪：" + str(e)}, 500)
        return

    if handler.command == "POST":
        try:
            cl = int(handler.headers.get('Content-Length', 0) or 0)
            raw = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
            data = json.loads(raw) if raw else {}
        except Exception as e:
            handler._send_json({"error": "请求解析失败：" + str(e)}, 400)
            return
        user_id = str(data.get('user_id', '') or '').strip()
        if not user_id:
            handler._send_json({"error": "缺少 user_id"}, 400)
            return
        vars_dict = data.get('vars')
        if vars_dict is None:
            # 清除自选 → 回退系统默认/个人默认
            ok = tm.clear_user_theme(user_id)
            handler._send_json({"ok": ok, "cleared": True})
            return
        if not isinstance(vars_dict, dict) or not vars_dict:
            handler._send_json({"error": "vars 必须为非空对象"}, 400)
            return
        ok = tm.save_user_theme(user_id, vars_dict)
        handler._send_json({"ok": ok, "saved": True})
        return

    # GET：解析查询参数
    qs = {}
    if parsed is not None:
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
    user_id = (qs.get('user_id', [''])[0] or '').strip()
    resolved = tm.resolve_theme(user_id=user_id or None)
    presets = []
    for t in tm.list_themes():
        name = t["name"]
        presets.append({"name": name, "label": t["label"], "kind": t["kind"],
                        "vars": tm.get_theme_vars(name)})
    cfg = tm._load_cfg()
    var_order = cfg.get("variable_order", [])
    meaning = getattr(tm, "_VAR_MEANING", {})
    handler._send_json({
        "current": {"vars": resolved["vars"], "source": resolved["source"]},
        "presets": presets,
        "variable_order": var_order,
        "variable_meaning": meaning,
    })


def handle_extract(handler):
    """POST /api/extract — 视频文案提取接口"""
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length > 10000:
        handler._send_json({"error": "请求体过大"}, 400)
        return
    body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return

    # P0-② 安全修复：代取类接口仅允许本机调用，屏蔽局域网越权抓取
    if not handler._is_local():
        handler._send_json({"error": "安全限制：提取仅允许本机操作。"}, 403)
        return
    url = data.get('url', '').strip()
    if not url:
        handler._send_json({"error": "请提供视频链接"}, 400)
        return
    # SSRF 防护（P0-2，JS-20260723-37）：代取 URL 必须过安全校验，
    # 禁止访问内网/环回/云元数据(169.254.169.254)等保留地址。
    ok, reason = handler._is_safe_http_url(url)
    if not ok:
        handler._send_json({"error": f"链接不安全，已拒绝：{reason}"}, 400)
        return

    try:
        from core.video_extractor import VideoExtractor
        extractor = VideoExtractor()
        result = extractor.extract(url)
        handler._send_json({"ok": True, "data": result})
    except ValueError as e:
        handler._send_json({"error": str(e)}, 400)
    except Exception as e:
        log(f'视频提取异常: {e}')
        handler._send_json({"error": f"提取失败：{e}"}, 500)


def handle_refine(handler):
    """POST /api/refine — 内容提炼接口"""
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length > 100000:
        handler._send_json({"error": "请求体过大"}, 400)
        return
    body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return

    extracted_data = data.get('data', {})
    if not extracted_data:
        handler._send_json({"error": "请提供提取数据"}, 400)
        return

    try:
        from core.content_refiner import ContentRefiner
        refiner = ContentRefiner()
        card = refiner.refine(extracted_data)
        handler._send_json({"ok": True, "card": card})
    except Exception as e:
        log(f'内容提炼异常: {e}')
        handler._send_json({"error": f"提炼失败：{e}"}, 500)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------
def _smart_scan(handler, path):
    """智能代码助手：扫描项目结构 + 生成四维推荐（只读，安全）。"""
    try:
        import project_loader, recommender
        scan = project_loader.scan_directory(path)
        if scan.get("error"):
            return scan
        try:
            scan["recommend"] = recommender.recommend(path, scan["files"])
        except Exception:
            scan["recommend"] = {"preset_questions": [], "style_issues": [],
                                 "warnings": [], "perf": [], "summary": {}}
        return scan
    except Exception as e:
        return {"error": "扫描失败：" + str(e)}


def _smart_ask(handler, question, path, selected=None, enable_kb=None):
    """智能代码助手：问答编排（可能调用 DeepSeek，受 localhost 限制）。"""
    try:
        import qa_engine
        return qa_engine.ask(question, path or BASE_DIR, selected=selected, enable_kb=enable_kb)
    except Exception as e:
        return {"ok": False, "error": "问答失败：" + str(e)}
