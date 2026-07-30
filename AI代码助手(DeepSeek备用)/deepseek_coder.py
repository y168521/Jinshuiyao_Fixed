# -*- coding: utf-8 -*-
"""
金水谣 · DeepSeek 备用代码助手
================================
用途：当 TRAE / WorkBuddy 不可用时，仍能通过 DeepSeek API 稳定地修改和优化代码。
特点：纯标准库实现（无需 pip 安装任何包）；双击即用（网页界面）；也支持命令行；
      内置自动重试、多端点切换、待重试队列，网络不稳定时流程不中断。

防浪费 + 知识闭环（本次升级）：
  - 预算硬上限：每天最多调用 N 次（配置 daily_api_budget），用完即停，绝不失控。
  - 会话去重：同一段代码+要求本次会话内重复提交，直接返回缓存，不花第二次。
  - 本地优先：纯格式化等琐事本地免费做，不调 DeepSeek。
  - 提交前确认 + 字数预估 + 防连点：心里有数，不手滑。
  - 改代码【前】检索本地知识库/提示词库并注入上下文，使其一次改对、少来回=少花钱。
  - 改代码【后】把有价值经验自动沉淀回知识库（去重、无变化不沉淀，不堆垃圾）。

仅在本机 127.0.0.1 运行，API Key 只保存在本机 config.json，只发给 DeepSeek。
"""
import os
import sys
import json
import time
import random
import shutil
import hashlib
import datetime
import argparse
import webbrowser
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
QUEUE_FILE = os.path.join(BASE_DIR, "pending_tasks.json")
USAGE_FILE = os.path.join(BASE_DIR, "usage.json")

DEFAULT_PORT = 18900
MAX_PORT_TRIES = 30
DEFAULT_DAILY_LIMIT = 50          # 每天最多调用 DeepSeek 次数
DEFAULT_PER_CALL_CHARS = 20000    # 单次提交内容字符上限

# 知识库桥接（改前检索 + 改后沉淀）
sys.path.insert(0, BASE_DIR)
try:
    from kb_bridge import (build_context, archive_value, archive_knowledge_qa,
                            kb_search, kb_card_count)
except Exception:
    build_context = lambda q: ""
    archive_value = lambda *a, **k: None
    archive_knowledge_qa = lambda *a, **k: None
    kb_search = lambda *a, **k: []
    kb_card_count = lambda *a, **k: 0

# 任务路由器：把「免费类任务」就地拦下，绝不动用付费 DeepSeek
sys.path.insert(0, os.path.join(BASE_DIR, ".."))   # 让 Jinshuiyao_Fixed/jinshuiyao_router 可达
try:
    from jinshuiyao_router import classify as _router_classify
except Exception:
    _router_classify = None

ENDPOINTS = [
    "https://api.deepseek.com/chat/completions",
    "https://api.deepseek.com/v1/chat/completions",
]
MODELS = ["deepseek-chat", "deepseek-reasoner"]

SYSTEM_PROMPT = (
    "你是一位严谨的中文代码助手，负责帮助用户修改和优化代码。\n"
    "用户会给你一段代码，以及修改 / 优化要求。请遵循：\n"
    "1) 优先保证代码可运行、不破坏原有功能；\n"
    "2) 用最小改动达成目标，不要过度重写；\n"
    "3) 返回修改后的【完整文件内容】；\n"
    "4) 开头先用一句中文说明改了什么，然后用 ``` 代码块包裹完整代码；\n"
    "5) 不要输出与任务无关的内容，不要编造文件之外的东西。"
)


# ---------------------------------------------------------------------------
# 配置与队列（本地文件）
# ---------------------------------------------------------------------------
def _raw_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_config():
    """读取配置并补全默认值。"""
    c = _raw_config()
    c.setdefault("daily_api_budget", DEFAULT_DAILY_LIMIT)
    c.setdefault("per_call_max_chars", DEFAULT_PER_CALL_CHARS)
    c.setdefault("default_model", "deepseek-chat")
    c.setdefault("enable_kb", True)
    return c


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_api_key():
    return _raw_config().get("api_key", "").strip()


def load_queue():
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_queue(q):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 预算 / 用量（防失控）
# ---------------------------------------------------------------------------
def _today():
    return datetime.date.today().isoformat()


def get_usage():
    try:
        d = json.load(open(USAGE_FILE, encoding="utf-8"))
    except Exception:
        d = {}
    if d.get("date") != _today():
        return {"date": _today(), "count": 0}
    return d


def inc_usage():
    d = get_usage()
    d["count"] = d.get("count", 0) + 1
    d["date"] = _today()
    try:
        json.dump(d, open(USAGE_FILE, "w", encoding="utf-8"))
    except Exception:
        pass
    return d["count"]


# ---------------------------------------------------------------------------
# 会话内去重缓存 + 本地优先
# ---------------------------------------------------------------------------
_SESSION_CACHE = {}


def _cache_key(code, instruction, model):
    return hashlib.md5((model + "|" + instruction + "|" + code).encode("utf-8")).hexdigest()


def _local_safe_transform(code, instruction):
    """仅对明显是『纯格式化』的指令做免费本地处理，不调 DeepSeek。返回新代码或 None。"""
    ins = instruction.lower()
    if any(k in ins for k in ["格式化", "整理缩进", "去空格", "去尾随", "统一换行", "去空行尾部"]):
        # 安全：去尾随空格、统一为 \n 换行（不改变任何逻辑）
        lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = [ln.rstrip() for ln in lines]
        return "\n".join(lines)
    return None


# ---------------------------------------------------------------------------
# 网络请求与重试（核心容错）
# ---------------------------------------------------------------------------
def _do_request(endpoint, api_key, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class DeepSeekError(Exception):
    def __init__(self, message, fatal=False, status=None):
        super().__init__(message)
        self.fatal = fatal      # True=不可重试（如密钥错误）
        self.status = status


def chat(messages, api_key, model="deepseek-chat",
         max_retries=3, timeout=90, endpoints=None, on_attempt=None):
    """带指数退避的网络调用。on_attempt(attempt, total, status_text) 用于进度反馈。"""
    endpoints = endpoints or ENDPOINTS
    last_err = None
    for attempt in range(max_retries):
        ep = endpoints[attempt % len(endpoints)]
        try:
            if on_attempt:
                on_attempt(attempt + 1, max_retries, "请求中")
            payload = {"model": model, "messages": messages,
                       "temperature": 0.2, "stream": False}
            resp = _do_request(ep, api_key, payload, timeout)
            return resp["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise DeepSeekError("API Key 无效或未授权，请检查密钥。", fatal=True, status=401)
            if e.code == 429:
                last_err = DeepSeekError("请求过于频繁（429），将重试。", status=429)
                wait = min(30, 5 * (attempt + 1))
            elif 500 <= e.code < 600:
                last_err = DeepSeekError(f"服务端错误（{e.code}），将重试。", status=e.code)
                wait = min(20, 2 ** attempt * 2)
            else:
                raise DeepSeekError(f"HTTP {e.code} 错误", fatal=True, status=e.code)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last_err = DeepSeekError(f"网络异常：{e}", status=0)
            wait = min(20, 2 ** attempt * 2)
        if attempt < max_retries - 1:
            jit = random.uniform(0, 1.5)
            if on_attempt:
                on_attempt(attempt + 1, max_retries, f"第{attempt + 1}次失败，{wait + jit:0.1f}s后重试")
            time.sleep(wait + jit)
    raise last_err or DeepSeekError("未知错误")


def fix_code(code, instruction, api_key, model="deepseek-chat",
             max_retries=3, context="", on_attempt=None):
    sys_prompt = SYSTEM_PROMPT
    if context:
        sys_prompt = SYSTEM_PROMPT + "\n\n" + context
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"【修改要求】\n{instruction}\n\n【原代码】\n{code}"},
    ]
    return chat(messages, api_key, model=model, max_retries=max_retries, on_attempt=on_attempt)


# ---------------------------------------------------------------------------
# 问答模式（对应「上下文感知问答」：大白话、三段式、新手友好）
# ---------------------------------------------------------------------------
QA_SYSTEM_PROMPT = (
    "你是一位耐心的中文编程老师，专门给不懂代码的新手讲清楚问题。\n"
    "用户会给你一个问题，以及相关的代码片段（如果有）。请务必用【大白话】回答，"
    "尽量避免专业术语；如果必须用到术语，先用一句话通俗解释。\n"
    "回答严格按下面三段输出，每段必须带小标题：\n"
    "【问题定位】用一两句话说明问题大概出在哪（哪个文件/哪段逻辑），新手能看懂。\n"
    "【原因分析】像给朋友讲故事一样，通俗解释为什么会这样。\n"
    "【修改建议】给出具体可做的步骤，或需要改动时的代码示例（用 ``` 代码块包裹）。\n"
)


def answer_question(question, context_code, api_key, model="deepseek-chat",
                    max_retries=3, on_attempt=None):
    sys_prompt = QA_SYSTEM_PROMPT
    if context_code:
        sys_prompt = QA_SYSTEM_PROMPT + "\n\n【参考代码片段（来自用户项目，仅作定位依据）】\n" + context_code
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": question},
    ]
    return chat(messages, api_key, model=model, max_retries=max_retries, on_attempt=on_attempt)


# ---------------------------------------------------------------------------
# 路由器判断：免费类任务一律本地作答，绝不动用付费 DeepSeek
# ---------------------------------------------------------------------------
_FREE_LOCATE_KW = ["定位", "查找", "在哪", "哪个文件", "目录结构", "项目结构",
                   "这段代码做什么", "这段代码是干", "这段代码干嘛", "文件结构",
                   "代码在哪", "代码位置", "这段代码的作用"]


def classify_cost(task_text):
    """判断任务是否「免费」（不应动用 DeepSeek）。

    返回 (cost, local_answer, path)：
      ('free', 文本, path) -> 免费且可本地作答，绝不动 DeepSeek
      ('paid', None, path) -> 需要 AI 推理，走 DeepSeek
    """
    if _router_classify is None:
        return ('paid', None, None)
    cl = _router_classify(task_text)
    p = cl.get("path")
    # 1) 明确的免费本地任务：重命名 / 列出 / 统计 / 格式化 / 联网抓取
    if p in ("local", "data_fetch"):
        return ('free',
                f"这是「{p}」类任务（{cl.get('reason', '')}），属于免费路径，不需要调用 DeepSeek。",
                p)
    # 2) 查知识库 / 解释：若本地知识库已有相关经验，免费作答；否则仍走 DeepSeek
    if p == "knowledge":
        try:
            hits = kb_search(task_text, top_k=3)
        except Exception:
            hits = []
        if hits:
            lines = ["（免费·来自本地知识库）你问的这类问题，知识库里已有相关经验，先给你看：\n"]
            for h in hits:
                snip = (h.get("body") or "")[:160].replace("\n", " ")
                lines.append(f"- 《{h.get('title', '')}》：{snip}")
            lines.append("\n本次未调用 DeepSeek，没有花钱。")
            return ('free', "\n".join(lines), p)
    # 3) 「定位 / 查结构」类问题：没有写代码意图时，判为免费本地任务
    if any(k in (task_text or "") for k in _FREE_LOCATE_KW):
        if p != "deepseek":
            return ('free',
                    "这是「定位 / 查结构」类问题，属于免费路径，不需要调用 DeepSeek。"
                    "在「智能代码助手」里加载项目后提问，系统会本地免费帮你定位相关代码并给出大白话解答。",
                    "local")
    # clarify / deepseek / knowledge 无命中 -> 走 DeepSeek
    return ('paid', None, p)


def do_qa(question, context, api_key, model=None, enable_kb=None):
    """执行一次问答（三段式），复用防浪费 + 知识闭环。返回结果字典。"""
    cfg = load_config()
    if model is None:
        model = cfg.get("default_model", "deepseek-chat")
    if enable_kb is None:
        enable_kb = cfg.get("enable_kb", True)

    # 0) 路由器拦截：免费类问题就地免费作答，绝不动用付费 DeepSeek
    cost, local_ans, _p = classify_cost(question)
    if cost == 'free' and local_ans:
        return {"ok": True, "intercepted": True, "cost": "free", "local": True,
                "deepseek_used": False, "answer": local_ans,
                "kb_used": False, "archived": False,
                "kb_count": kb_card_count()}

    # 1) 预算硬上限
    usage = get_usage()
    limit = int(cfg.get("daily_api_budget", DEFAULT_DAILY_LIMIT))
    if usage.get("count", 0) >= limit:
        return {"ok": False,
                "error": f"今日 DeepSeek 调用额度已用完（{usage['count']}/{limit}）。明天自动重置，或调高配置里的 daily_api_budget。",
                "quota_exceeded": True}

    # 2) 单次字数上限
    est = len(question) + len(context or "")
    cap = int(cfg.get("per_call_max_chars", DEFAULT_PER_CALL_CHARS))
    if est > cap:
        return {"ok": False,
                "error": f"本次内容约 {est} 字符，超过单次上限 {cap}。请缩小问题范围或只勾选相关文件。"}

    # 3) 会话去重
    ck = hashlib.md5(("qa|" + model + "|" + question + "|" + (context or "")[:500]).encode("utf-8")).hexdigest()
    if ck in _SESSION_CACHE:
        return {"ok": True, "answer": _SESSION_CACHE[ck], "cached": True,
                "note": "命中本次会话缓存，未消耗额度。"}

    # 4) 知识库上下文（改前参考，减少来回=省钱）
    kb_ctx = ""
    kb_used = False
    if enable_kb:
        try:
            kb_ctx = build_context(question + "\n" + (context or "")[:500])
            kb_used = bool(kb_ctx)
        except Exception:
            kb_ctx = ""
    full_context = context or ""
    if kb_ctx:
        full_context = (full_context + "\n\n【本地知识库相关经验】\n" + kb_ctx)[:cap]

    # 5) 调用 DeepSeek
    answer = answer_question(question, full_context, api_key, model=model)

    # 6) 计预算、缓存、沉淀问答价值
    inc_usage()
    _SESSION_CACHE[ck] = answer
    archived = None
    try:
        if enable_kb:
            archived = archive_knowledge_qa(question, answer)
    except Exception:
        archived = None

    return {"ok": True, "answer": answer, "kb_used": kb_used,
            "archived": bool(archived), "kb_count": kb_card_count()}


# ---------------------------------------------------------------------------
# 待重试队列（网络恢复后继续，不丢任务）
# ---------------------------------------------------------------------------
def queue_task(code, instruction, model):
    q = load_queue()
    q.append({"code": code, "instruction": instruction, "model": model, "ts": time.time()})
    save_queue(q)
    return len(q)


def drain_queue(api_key):
    """尝试处理队列中所有任务；返回 (成功数, 剩余数, 结果列表)。"""
    q = load_queue()
    done, remaining, results = [], [], []
    for task in q:
        try:
            r = fix_code(task["code"], task["instruction"], api_key,
                         model=task.get("model", "deepseek-chat"))
            done.append(task)
            results.append({"instruction": task["instruction"], "result": r})
        except DeepSeekError as e:
            if e.fatal:
                return len(done), len(q) - len(done), results  # 密钥问题，停止
            remaining.append(task)
        except Exception:
            remaining.append(task)
    save_queue(remaining)
    return len(done), len(remaining), results


# ---------------------------------------------------------------------------
# 核心流程：防浪费 + 知识闭环（抽成函数，便于测试）
# ---------------------------------------------------------------------------
def do_fix(code, instruction, api_key, model=None, enable_kb=None):
    """执行一次代码修改，返回结果字典。网络失败会抛 DeepSeekError（由调用方入队）。"""
    cfg = load_config()
    if model is None:
        model = cfg.get("default_model", "deepseek-chat")
    if enable_kb is None:
        enable_kb = cfg.get("enable_kb", True)

    # 0) 本地优先：纯格式化（真实改动，本地免费做）
    local = _local_safe_transform(code, instruction)
    if local is not None:
        return {"ok": True, "result": local, "local": True,
                "note": "已本地免费处理（纯格式化），未消耗 DeepSeek 额度。"}

    # 1) 路由器拦截：免费类任务（查结构/查知识库/列出统计/定位等）就地拦下，不花 DeepSeek
    cost, local_ans, _p = classify_cost(instruction)
    if cost == 'free' and local_ans:
        return {"ok": True, "result": local_ans, "intercepted": True, "cost": "free",
                "local": True, "deepseek_used": False,
                "note": "免费任务已就地处理，未消耗 DeepSeek 额度。"}

    # 2) 预算硬上限
    usage = get_usage()
    limit = int(cfg.get("daily_api_budget", DEFAULT_DAILY_LIMIT))
    if usage.get("count", 0) >= limit:
        return {"ok": False,
                "error": f"今日 DeepSeek 调用额度已用完（{usage['count']}/{limit}）。明天自动重置，或调高配置里的 daily_api_budget。",
                "quota_exceeded": True}

    # 3) 单次字数上限
    est = len(code) + len(instruction)
    cap = int(cfg.get("per_call_max_chars", DEFAULT_PER_CALL_CHARS))
    if est > cap:
        return {"ok": False,
                "error": f"本次内容约 {est} 字符，超过单次上限 {cap}。请拆分后提交，避免一次花太多。"}

    # 4) 会话内去重
    ck = _cache_key(code, instruction, model)
    if ck in _SESSION_CACHE:
        return {"ok": True, "result": _SESSION_CACHE[ck], "cached": True,
                "note": "命中本次会话缓存，未消耗额度。"}

    # 5) 改前检索知识库 / 提示词库，注入上下文（减少来回=省钱）
    ctx = ""
    kb_used = False
    if enable_kb:
        try:
            ctx = build_context(instruction + "\n" + code[:500])
            kb_used = bool(ctx)
        except Exception:
            ctx = ""

    # 6) 调用 DeepSeek（失败抛异常，由上层入队）
    result = fix_code(code, instruction, api_key, model=model, context=ctx)

    # 7) 成功：计预算、缓存、沉淀价值
    inc_usage()
    _SESSION_CACHE[ck] = result
    archived = None
    try:
        if enable_kb:
            archived = archive_value(instruction, code, result, model)
    except Exception:
        archived = None

    # 8) 顺带补跑之前排队的任务
    drained = 0
    try:
        if load_queue():
            succ, _, _ = drain_queue(api_key)
            drained = succ
    except Exception:
        pass

    return {"ok": True, "result": result, "drained": drained,
            "kb_used": kb_used, "archived": bool(archived), "kb_count": kb_card_count()}


# ---------------------------------------------------------------------------
# 网页界面（纯 stdlib，仅本机 127.0.0.1）
# ---------------------------------------------------------------------------
class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>金水谣 · DeepSeek 备用代码助手</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family: "Microsoft YaHei","PingFang SC",system-ui,sans-serif;
         background:#f4f6fb; color:#1f2733; line-height:1.6; }
  .wrap { max-width:920px; margin:0 auto; padding:24px 18px 60px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#6b7785; font-size:13px; margin-bottom:18px; }
  .card { background:#fff; border:1px solid #e6eaf0; border-radius:12px;
          padding:16px 18px; margin-bottom:16px; box-shadow:0 1px 3px rgba(20,40,80,.04); }
  .card h2 { font-size:15px; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
  label { font-size:13px; color:#3a4654; display:block; margin:10px 0 4px; }
  textarea, input[type=text], input[type=password], select {
    width:100%; padding:10px; border:1px solid #d4dae3; border-radius:8px;
    font-size:13px; font-family:"Consolas","Microsoft YaHei",monospace; background:#fbfcfe; }
  textarea { min-height:150px; resize:vertical; }
  #code { min-height:260px; }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  button { cursor:pointer; border:none; border-radius:8px; padding:10px 16px;
           font-size:14px; font-weight:600; transition:.15s; }
  .primary { background:#2f6bff; color:#fff; }
  .primary:hover { background:#2257e0; }
  .primary:disabled { background:#a9c0f5; cursor:not-allowed; }
  .ghost { background:#eef2fb; color:#2f4a7a; }
  .ghost:hover { background:#e0e8f8; }
  .small { font-size:12px; padding:7px 12px; }
  .status { font-size:13px; margin-top:10px; min-height:20px; color:#3a4654; }
  .status.ok { color:#1a8a4a; }
  .status.err { color:#d23b3b; }
  .status.warn { color:#b8860b; }
  .muted { color:#8a94a3; font-size:12px; }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
          background:#eaf1ff; color:#2f6bff; }
  .pill.bad { background:#fdeaea; color:#d23b3b; }
  pre.out { white-space:pre-wrap; word-break:break-word; background:#0f1622; color:#e6edf3;
            padding:14px; border-radius:8px; max-height:420px; overflow:auto; font-size:12.5px; }
  .foot { font-size:12px; color:#8a94a3; margin-top:8px; }
  a { color:#2f6bff; text-decoration:none; }
  .quota { margin-top:8px; font-size:12px; color:#3a4654; }
</style>
</head>
<body>
<div class="wrap">
  <h1>金水谣 · DeepSeek 备用代码助手</h1>
  <div class="sub">当 TRAE / WorkBuddy 用不了时，也能改代码。仅在你的电脑本机运行，密钥只发往 DeepSeek。</div>

  <div class="card">
    <h2>🔑 第 1 步：填写并保存 API Key</h2>
    <label>DeepSeek API Key（去 platform.deepseek.com 获取，形如 sk-...）</label>
    <div class="row">
      <input type="password" id="key" placeholder="sk-..." style="flex:1">
      <button class="ghost" id="saveKey">保存密钥</button>
      <span id="keyStatus" class="pill">检测中…</span>
    </div>
    <div class="foot">密钥仅保存在本机 <code>config.json</code>，不会上传到其他地方。请在自己的电脑上使用。</div>
  </div>

  <div class="card">
    <h2>🛠 第 2 步：粘贴代码 + 写修改要求</h2>
    <label>修改 / 优化要求（用大白话写即可，例如：给这段代码加注释并优化性能）</label>
    <textarea id="instruction" placeholder="例如：把这个函数改成能处理空输入的版本，并加上中文注释"></textarea>
    <label>代码内容（点“选择文件”可加载本地代码文件）</label>
    <div class="row">
      <input type="file" id="fileInput" accept=".py,.js,.ts,.txt,.bat,.json,.html,.css,.java,.go,.cpp,.c,.md" style="flex:1">
      <button class="ghost small" id="clearCode">清空</button>
    </div>
    <textarea id="code" placeholder="把要改的代码粘到这里，或点上面的“选择文件”加载"></textarea>
    <label>模型</label>
    <select id="model">
      <option value="deepseek-chat">deepseek-chat（快、通用、便宜）</option>
      <option value="deepseek-reasoner">deepseek-reasoner（慢、更会推理、较贵）</option>
    </select>
    <label style="display:flex;align-items:center;gap:6px;margin-top:8px">
      <input type="checkbox" id="useKb" checked> 改前检索知识库/提示词（推荐：让它一次改对，少来回=省钱）
    </label>
    <div class="quota" id="quota">今日额度：读取中…</div>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="submit">🚀 提交修改</button>
      <span id="status" class="status"></span>
    </div>
  </div>

  <div class="card">
    <h2>📥 第 3 步：复制或下载结果</h2>
    <pre class="out" id="result">（结果会显示在这里）</pre>
    <div class="row" style="margin-top:10px">
      <button class="ghost small" id="copyBtn">复制结果</button>
      <button class="ghost small" id="downloadBtn">下载为 .txt</button>
    </div>
  </div>

  <div class="card">
    <h2>🔄 网络不好时的“待重试队列”</h2>
    <div class="muted">如果提交时断网 / 超时，任务会自动存进队列，网络恢复后点下面按钮即可补跑，不会丢活。</div>
    <div class="row" style="margin-top:10px">
      <button class="ghost" id="retryBtn">重试待处理任务</button>
      <span id="queueStatus" class="status"></span>
    </div>
  </div>

  <div class="foot">进阶：也可在文件夹里打开命令行，用
    <code>python deepseek_coder.py --file 你的文件.py --instruction "优化" --out 结果.txt</code> 直接跑。</div>
</div>

<script>
const $ = id => document.getElementById(id);
function setStatus(el, msg, cls){ el.textContent = msg; el.className = 'status' + (cls?(' '+cls):''); }

async function api(path, body){
  const r = await fetch(path, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  return r.json();
}

async function refreshKey(){
  try{
    const c = await (await fetch('/api/config')).json();
    if(c.has_key){ $('keyStatus').textContent='已保存'; $('keyStatus').className='pill'; }
    else { $('keyStatus').textContent='未设置'; $('keyStatus').className='pill bad'; }
  }catch(e){ $('keyStatus').textContent='读取失败'; }
}

async function refreshQuota(){
  try{
    const q = await (await fetch('/api/usage')).json();
    $('quota').textContent = '今日 DeepSeek 额度：' + q.used + ' / ' + q.limit
      + (q.enable_kb ? ' · 已开启知识库' : ' · 已关闭知识库');
  }catch(e){ $('quota').textContent='额度读取失败'; }
}

$('saveKey').onclick = async ()=>{
  const k = $('key').value.trim();
  if(!k){ setStatus($('keyStatus'),'请先填写密钥','err'); return; }
  const r = await api('/api/config', {api_key:k});
  if(r.ok){ setStatus($('keyStatus'),'已保存 ✓','ok'); $('keyStatus').textContent='已保存'; $('keyStatus').className='pill'; refreshQuota(); }
  else setStatus($('keyStatus'),'保存失败','err');
};

$('fileInput').onchange = e=>{
  const f = e.target.files[0]; if(!f) return;
  const rd = new FileReader();
  rd.onload = ev => { $('code').value = ev.target.result; };
  rd.readAsText(f);
};
$('clearCode').onclick = ()=> $('code').value='';

$('submit').onclick = async ()=>{
  const code = $('code').value, inst = $('instruction').value.trim(), model = $('model').value;
  const useKb = $('useKb').checked;
  if(!inst){ setStatus($('status'),'请填写修改要求','err'); return; }
  if(!code.trim()){ setStatus($('status'),'请粘贴或选择代码','err'); return; }
  // 提交前确认 + 字数预估，心里有数
  const est = code.length + inst.length;
  if(!confirm('本次将消耗 DeepSeek 额度，约 ' + est + ' 字符。确定提交？')) return;
  // 提交中禁用按钮，防连点（避免花两次）
  const btn = $('submit'); btn.disabled = true; btn.textContent = '处理中…';
  setStatus($('status'),'正在请求 DeepSeek…','');
  $('result').textContent = '（处理中…）';
  try {
    const r = await api('/api/fix', {code, instruction:inst, model, enable_kb:useKb});
    if(r.ok){
      $('result').textContent = r.result;
      let msg = '完成 ✓';
      if(r.extra) msg += r.extra;
      if(r.archived) msg += '；已自动沉淀到知识库（累计第 ' + (r.kb_count != null ? r.kb_count : '?') + ' 条）';
      else if(r.kb_used) msg += '；已参考知识库经验';
      if(r.drained) msg += '；并补跑 ' + r.drained + ' 个排队任务';
      setStatus($('status'), msg, 'ok');
    } else if(r.need_key){
      setStatus($('status'),'请先在上方填写并保存 API Key','err');
    } else if(r.quota_exceeded){
      setStatus($('status'), r.error, 'err');
    } else if(r.queued){
      setStatus($('status'), r.error + '（已存入待重试队列，恢复网络后点“重试待处理任务”）','warn');
    } else if(r.fatal){
      setStatus($('status'),'停止：'+r.error,'err');
    } else {
      setStatus($('status'),'失败：'+r.error,'err');
    }
  } finally {
    btn.disabled = false; btn.textContent = '🚀 提交修改';
    refreshQuota();
  }
};

$('copyBtn').onclick = ()=>{
  navigator.clipboard.writeText($('result').textContent).then(
    ()=> setStatus($('status'),'已复制到剪贴板','ok'),
    ()=> setStatus($('status'),'复制失败，请手动选择','err'));
};
$('downloadBtn').onclick = ()=>{
  const blob = new Blob([$('result').textContent], {type:'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'deepseek_result.txt'; a.click();
};

$('retryBtn').onclick = async ()=>{
  setStatus($('queueStatus'),'正在重试队列…','');
  const r = await api('/api/retry', {});
  if(r.need_key){ setStatus($('queueStatus'),'请先保存密钥','err'); return; }
  if(r.fatal){ setStatus($('queueStatus'),'停止：'+r.error,'err'); return; }
  setStatus($('queueStatus'),
    '重试 '+r.retried+' 个，成功 '+r.succeeded+' 个，剩余 '+r.remaining+' 个',
    r.remaining>0?'warn':'ok');
  if(r.results && r.results.length){
    $('result').textContent = r.results.map(x=>'# '+x.instruction+'\n'+x.result).join('\n\n');
  }
};

refreshKey();
refreshQuota();
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            b = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif self.path == "/api/config":
            self._send_json({"has_key": bool(get_api_key())})
        elif self.path == "/api/queue":
            self._send_json({"length": len(load_queue())})
        elif self.path == "/api/usage":
            cfg = load_config()
            u = get_usage()
            self._send_json({
                "date": u.get("date"),
                "used": u.get("count", 0),
                "limit": int(cfg.get("daily_api_budget", DEFAULT_DAILY_LIMIT)),
                "enable_kb": bool(cfg.get("enable_kb", True)),
                "default_model": cfg.get("default_model", "deepseek-chat"),
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}
        if self.path == "/api/config":
            self.handle_config(data)
        elif self.path == "/api/fix":
            self.handle_fix(data)
        elif self.path == "/api/retry":
            self.handle_retry(data)
        else:
            self._send_json({"ok": False, "error": "unknown endpoint"})

    def handle_config(self, data):
        key = (data.get("api_key") or "").strip()
        if not key:
            # 仅更新设置（不传密钥时）
            if any(k in data for k in ("daily_api_budget", "default_model", "enable_kb", "per_call_max_chars")):
                cfg = _raw_config()
                for k in ("daily_api_budget", "default_model", "enable_kb", "per_call_max_chars"):
                    if k in data:
                        cfg[k] = data[k]
                save_config(cfg)
                self._send_json({"ok": True})
                return
            self._send_json({"ok": False, "error": "空密钥"})
            return
        cfg = _raw_config()
        cfg["api_key"] = key
        for k in ("daily_api_budget", "default_model", "enable_kb", "per_call_max_chars"):
            if k in data:
                cfg[k] = data[k]
        save_config(cfg)
        self._send_json({"ok": True})

    def handle_fix(self, data):
        api_key = get_api_key()
        if not api_key:
            self._send_json({"ok": False, "need_key": True, "error": "请先填写并保存 API Key"})
            return
        code = data.get("code", "")
        instruction = (data.get("instruction") or "").strip()
        model = data.get("model") or load_config().get("default_model", "deepseek-chat")
        enable_kb = data.get("enable_kb", None)
        if not instruction:
            self._send_json({"ok": False, "error": "请填写修改要求"})
            return
        if not code.strip():
            self._send_json({"ok": False, "error": "请粘贴或选择代码"})
            return
        try:
            out = do_fix(code, instruction, api_key, model=model, enable_kb=enable_kb)
        except DeepSeekError as e:
            if e.fatal:
                self._send_json({"ok": False, "error": str(e), "fatal": True})
                return
            n = queue_task(code, instruction, model)
            self._send_json({"ok": False, "error": str(e), "queued": True, "queue_len": n})
            return
        except Exception as e:
            self._send_json({"ok": False, "error": "调用失败：" + str(e)})
            return
        if not out.get("ok"):
            self._send_json(out)
            return
        if out.get("local"):
            extra = "（本地免费）"
        elif out.get("cached"):
            extra = "（会话缓存，未花费）"
        elif out.get("archived"):
            cnt = out.get("kb_count")
            extra = "（已计额度，已沉淀到知识库" + (f"，累计第 {cnt} 条" if isinstance(cnt, int) else "") + "）"
        else:
            extra = "（已计额度）"
        self._send_json({
            "ok": True, "result": out["result"], "drained": out.get("drained", 0),
            "kb_used": out.get("kb_used", False), "archived": out.get("archived", False),
            "kb_count": out.get("kb_count"),
            "note": out.get("note", ""), "extra": extra,
        })

    def handle_retry(self, data):
        api_key = get_api_key()
        if not api_key:
            self._send_json({"ok": False, "need_key": True})
            return
        q = load_queue()
        if not q:
            self._send_json({"ok": True, "retried": 0, "succeeded": 0, "remaining": 0, "results": []})
            return
        try:
            succ, rem, results = drain_queue(api_key)
        except DeepSeekError as e:
            if e.fatal:
                self._send_json({"ok": False, "error": str(e), "fatal": True})
                return
            self._send_json({"ok": False, "error": str(e)})
            return
        self._send_json({"ok": True, "retried": len(q), "succeeded": succ,
                         "remaining": rem, "results": results})


def run_web():
    httpd = None
    port = DEFAULT_PORT
    for p in range(DEFAULT_PORT, DEFAULT_PORT + MAX_PORT_TRIES):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print(f"错误：无法绑定本地端口（18890 起连续 {MAX_PORT_TRIES} 个均被占用）。")
        return
    url = f"http://127.0.0.1:{port}/"
    print("金水谣 · DeepSeek 备用代码助手已启动：")
    print("  " + url)
    print("在浏览器中打开上面的地址即可使用。按 Ctrl+C 停止。")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


# ---------------------------------------------------------------------------
# 命令行模式（进阶）
# ---------------------------------------------------------------------------
def cmd_fix(args):
    api_key = args.key or get_api_key()
    if not api_key:
        print("错误：未提供 API Key。请用 --key 参数，或先在网页里保存一次。")
        return 1
    code = args.code or ""
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            print("读取文件失败：", e)
            return 1
    if not code.strip():
        print("错误：没有代码内容（用 --file 或 --code 提供）。")
        return 1
    instruction = args.instruction or ""
    if not instruction.strip():
        print("错误：没有修改要求（用 --instruction 提供）。")
        return 1
    enable_kb = not args.no_kb
    cfg = load_config()
    model = args.model or cfg.get("default_model", "deepseek-chat")
    try:
        out = do_fix(code, instruction, api_key, model=model, enable_kb=enable_kb)
    except DeepSeekError as e:
        if e.fatal:
            print("停止：", e)
            return 1
        n = queue_task(code, instruction, model)
        print(f”网络不稳定，已存入待重试队列（共 {n} 个）。恢复后运行网页里的”重试待处理任务”。”)
        return 2
    if not out.get("ok"):
        print("未能完成：", out.get("error", ""))
        return 1
    result = out["result"]
    if args.out:
        try:
            if args.file and args.backup:
                shutil.copy(args.file, args.file + ".bak")
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(result)
            print("已写入：", args.out)
        except Exception as e:
            print("写入失败：", e, "\n\n结果如下：\n", result)
            return 1
    else:
        print(result)
    tag = "（本地免费）" if out.get("local") else ("（会话缓存）" if out.get("cached") else "")
    if out.get("archived"):
        tag += "；已自动沉淀到知识库"
    elif out.get("kb_used"):
        tag += "；已参考知识库经验"
    print("[" + ("完成" + tag) + "]")
    return 0


# ---------------------------------------------------------------------------
# 自测（离线验证 重试 / 队列 / 防浪费 / 知识闭环）
# ---------------------------------------------------------------------------
def self_test():
    global _do_request, build_context, archive_value, inc_usage, get_usage
    print("== DeepSeek 代码助手 自测（含防浪费 + 知识闭环）==")
    orig_do = _do_request
    orig_ctx = build_context
    orig_archive = archive_value
    orig_inc = inc_usage
    orig_getu = get_usage
    import kb_bridge as _kbmod
    orig_kb_archive = _kbmod._archive

    calls = {"n": 0, "archive_n": 0}

    def fake_do(endpoint, api_key, payload, timeout):
        calls["n"] += 1
        return {"choices": [{"message": {"content": "# 改后\nx = 1  # 已改"}}]}

    def fake_ctx(q):
        return ""

    def fake_archive(*a, **k):
        calls["archive_n"] += 1
        return "card.md"

    def fake_inc():
        pass

    usage_state = {"count": 0}

    def fake_getu():
        return {"date": datetime.date.today().isoformat(), "count": usage_state["count"]}

    # 写入测试配置（先备份真实配置，结束时还原，绝不误删用户密钥）
    orig_cfg = _raw_config()
    save_config({"api_key": "sk-test", "daily_api_budget": 2,
                 "per_call_max_chars": 100000, "enable_kb": True,
                 "default_model": "deepseek-chat"})

    _do_request = fake_do
    build_context = fake_ctx
    archive_value = fake_archive
    inc_usage = fake_inc
    get_usage = fake_getu
    try:
        # 1) 正常修改：调用 1 次、沉淀 1 次
        calls["n"] = 0
        calls["archive_n"] = 0
        r = do_fix("x=1", "加注释", "sk-test", model="deepseek-chat")
        assert r["ok"] and calls["n"] == 1 and calls["archive_n"] == 1, (r, calls)
        print("✓ 正常修改：调用 1 次、沉淀知识库 1 次")

        # 2) 会话去重：相同输入不调 API
        calls["n"] = 0
        r2 = do_fix("x=1", "加注释", "sk-test", model="deepseek-chat")
        assert r2.get("cached") and calls["n"] == 0, (r2, calls)
        print("✓ 会话去重：第二次命中缓存，未调 API")

        # 3) 本地优先：纯格式化不调 API
        calls["n"] = 0
        r3 = do_fix("a=1   \n", "格式化 去尾随空格", "sk-test")
        assert r3.get("local") and calls["n"] == 0, (r3, calls)
        print("✓ 本地优先：纯格式化本地免费处理")

        # 4) 预算上限：额度用完后拒绝
        usage_state["count"] = 2
        r4 = do_fix("y=2", "再加注释", "sk-test")
        assert (not r4.get("ok")) and r4.get("quota_exceeded"), r4
        print("✓ 预算上限：额度用完后明确拒绝")

        # 5) 单次字数上限
        usage_state["count"] = 0
        r5 = do_fix("a" * 200000, "处理", "sk-test")
        assert (not r5.get("ok")) and "超过单次上限" in r5.get("error", ""), r5
        print("✓ 单次字数上限：超大内容被拦下")

        # 6) 网络失败：正确抛异常（由上层入队）
        def fake_fail(*a):
            raise DeepSeekError("down", status=0)
        _do_request = fake_fail
        try:
            do_fix("z=3", "改", "sk-test")
            print("✗ 应抛异常")
        except DeepSeekError:
            print("✓ 网络失败：正确抛出（将由上层入队）")
        _do_request = fake_do

        # 7) 问答模式：调用 1 次、沉淀 1 次
        _kbmod._archive = fake_archive
        try:
            if os.path.isfile(_kbmod._VALUE_CACHE):
                os.remove(_kbmod._VALUE_CACHE)
        except Exception:
            pass
        usage_state["count"] = 0
        calls["n"] = 0
        calls["archive_n"] = 0
        q = do_qa("这段代码为什么会报错？", "def f():\n  x = 1\n return x", "sk-test")
        assert q["ok"] and calls["n"] == 1 and calls["archive_n"] == 1, (q, calls)
        print("✓ 问答模式：调用 1 次、沉淀知识库 1 次")
    finally:
        _do_request = orig_do
        build_context = orig_ctx
        archive_value = orig_archive
        inc_usage = orig_inc
        get_usage = orig_getu
        _kbmod._archive = orig_kb_archive
        save_config(orig_cfg)  # 还原真实配置（不误删用户密钥/设置）
    print("DeepSeek 代码助手自测通过 ✅")


def main():
    ap = argparse.ArgumentParser(description="金水谣 · DeepSeek 备用代码助手")
    ap.add_argument("--cli", action="store_true", help="命令行模式")
    ap.add_argument("--file", help="要修改的代码文件")
    ap.add_argument("--code", help="直接传入代码文本")
    ap.add_argument("--instruction", required="--cli" in sys.argv, help="修改要求")
    ap.add_argument("--out", help="结果输出文件")
    ap.add_argument("--key", help="API Key（不填则用已保存的）")
    ap.add_argument("--model", default=None, help="模型（默认用配置 default_model）")
    ap.add_argument("--no-kb", action="store_true", help="命令行模式：关闭知识库检索/沉淀")
    ap.add_argument("--backup", action="store_true", help="命令行模式：备份原文件为 .bak")
    ap.add_argument("--self-test", action="store_true", help="离线自测")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if args.cli:
        sys.exit(cmd_fix(args))
    run_web()


if __name__ == "__main__":
    main()
