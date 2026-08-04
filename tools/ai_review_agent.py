# -*- coding: utf-8 -*-
"""金水谣 · AI 语义审查 Agent

调用 DeepSeek API 对指定文件做语义审查，检测逻辑缺陷/可维护性/设计模式问题。
输出 JSON 结构化结果，与 ruff/AST 扫描结果合并进审查报告。

用法：
  python tools/ai_review_agent.py --files a.py,b.py [--diff-only] [--json]
  python tools/ai_review_agent.py --pr 42                    # GitHub PR 模式
"""
import ast
import json
import os
import re
import sys
import time
import argparse
import threading
import hashlib

# ─── 项目根 ───
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 确保 core 包可 import（供免费模型池管理器）
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ─── 免费模型池（配置外部化 + 故障转移 + 探活）───
try:
    from core.free_model_pool import get_free_provider_cfgs, call_ai_failover
except Exception:
    get_free_provider_cfgs = None
    call_ai_failover = None

# ─── Pattern Library 路径 ───
_PATTERN_LIB_PATH = os.path.join(_PROJECT_ROOT, "knowledge", "pattern_library.json")

# ─── 审查数据目录 ───
_REVIEW_DATA_DIR = os.path.join(_PROJECT_ROOT, "金水谣数据", "review")
_PATTERN_HITS_FILE = os.path.join(_REVIEW_DATA_DIR, "pattern_hits.jsonl")

# ─── 锁 ───
_review_lock = threading.Lock()

# ─── DeepSeek 结果缓存（避免同一文件重复扣费）───
# 键=文件内容 sha256；值={ts, issues, rel}；TTL 默认24h，可用 AI_REVIEW_CACHE_TTL_HOURS 覆盖
_CACHE_FILE = os.path.join(_REVIEW_DATA_DIR, "ai_review_cache.json")
_CACHE_TTL = int(os.environ.get("AI_REVIEW_CACHE_TTL_HOURS", "24")) * 3600


def _load_review_cache():
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_review_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with _review_lock:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _file_content_hash(filepath):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except Exception:
        return None
    return h.hexdigest()


# ─── 省费门禁：本地 + 知识库优先，DeepSeek 最后兜底 ───
# 对应需求：能用本地分析/知识库判断的就不调付费 API，避免浪费。
_LOW_VALUE_NAMES = {"conftest.py", "setup.py", "setup.cfg", "migrate.py",
                    "__init__.py", "manage.py", "wsgi.py", "asgi.py"}
_LOW_VALUE_DIRS = {"tests", "test", "fixtures", "fixture", "migrations",
                   "generated", "gen", "_vendor", "vendor", "node_modules",
                   "venv_314", "__pycache__", "snapshots", "mock", "mocks",
                   "docs", "doc"}
_TRIVIAL_MAX_LINES = 25


def _is_low_value_file(rel_path):
    """路径启发式：测试/夹具/迁移/生成/文档等非重点文件 → 不值得花 API"""
    parts = rel_path.replace("\\", "/").split("/")
    name = parts[-1].lower()
    if name in _LOW_VALUE_NAMES:
        return True
    for p in parts:
        if p.lower() in _LOW_VALUE_DIRS:
            return True
    if name.endswith((".pb.go", ".pb2.py", ".pb.py", "_generated.py")):
        return True
    if "generated" in name or name.startswith("gen_"):
        return True
    return False


def _is_trivial(content):
    """内容极简（仅 import/注释/极少量代码）→ 语义审查价值低"""
    if not content:
        return True
    lines = [l for l in content.splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if len(lines) > _TRIVIAL_MAX_LINES:
        return False
    code_lines = [l for l in lines
                  if not (l.strip().startswith("import ")
                          or l.strip().startswith("from "))]
    return len(code_lines) <= 3


# 高风险面标记：文件含这些 token 说明有严重 bug 风险，kb_covered 不得跳过 AI（避免漏真 bug）
_SERIOUS_TOKENS = ("threading", "thread(", "lock(", "rlock", "global ",
                   "subprocess", "os.system", "requests.", "urllib",
                   "exec(", "eval(", "pickle", "sqlite3", "socket",
                   "asyncio", "multiprocessing", "concurrent", "with open(")


def _has_serious_tokens(content):
    """文件含高风险面（并发/子进程/网络/反序列化等）→ 应走高质量模型而非免费小模型"""
    if not content:
        return False
    low = content.lower()
    return any(tok in low for tok in _SERIOUS_TOKENS)


def _kb_covers(abs_path, content, patterns):
    """知识库(模式库)已用 evidence 覆盖该文件风险 → 可用本地知识替代 API（即'联网'层）。

    安全约束：仅对 P2/P3 级已知小问题生效，且文件不得含高风险面(并发/子进程/网络/反序列化等)，
    否则宁可花一次 API 调用也不漏严重 bug。
    """
    if not content or not patterns:
        return None
    low = content.lower()
    if any(tok in low for tok in _SERIOUS_TOKENS):
        return None
    rel = abs_path.replace("\\", "/")
    for pid, pat in patterns.items():
        if pat.get("severity") not in ("P2", "P3"):
            continue
        if not pat.get("evidence"):
            continue
        det = pat.get("detection", {})
        fp = det.get("file_pattern", "*.py")
        if fp != "*.py" and not rel.endswith(fp.replace("*", "")):
            continue
        triggers = det.get("triggers", []) or pat.get("triggers", [])
        for kw in triggers:
            if kw and kw in content:
                return pid
    return None


def _local_quick_check(content):
    """免费本地预检：抓裸 except(P0) 与疑似硬编码密钥(P0)。本地已兜底则无需再花 API"""
    issues = []
    if not content:
        return issues
    try:
        tree = ast.parse(content)
    except Exception:
        return issues
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None and node.name is None:
                issues.append({"severity": "P0", "category": "concurrency",
                               "line": getattr(node, "lineno", None),
                               "description": "裸 except:（本地AST预检，未指定异常类型）",
                               "pattern_id": "AST-002",
                               "fix_hint": "改为 except Exception: 或指定具体异常",
                               "confidence": 0.95})
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and re.search(r"(key|secret|token|password|passwd)", t.id, re.I):
                    v = node.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) > 8:
                        issues.append({"severity": "P0", "category": "security",
                                       "line": getattr(node, "lineno", None),
                                       "description": "疑似硬编码密钥（本地AST预检）",
                                       "pattern_id": None,
                                       "fix_hint": "存入 ~/.jinshuiyao-secrets/",
                                       "confidence": 0.7})
    return issues


def _should_call_ai(abs_path, rel_path, content, patterns, local_issues,
                    always_ai=False, budget=None, used=0):
    """决定是否值得调用 DeepSeek（省钱门禁）。

    不调用的情况（返回 (False, reason)）：
      - always_ai=False 且 budget==0        → 'no_ai'（用户要求纯本地）
      - 已达预算上限                          → 'budget_exhausted'
      - 低价值文件（测试/夹具/迁移/生成/文档）→ 'low_value_file'
      - 内容极简                             → 'trivial'
      - 知识库已 evidence 覆盖该风险          → 'kb_covered:<PID>'（本地+知识库已替代 API）
      - 本地预检已识别 P0/P1                  → 'local_p01_covered'（安全已由本地兜底）
    其余（需语义判断的复杂/核心文件）→ (True, 'needs_semantic')
    """
    if always_ai:
        return True, "always_ai"
    if budget == 0:
        return False, "no_ai"
    if budget is not None and used >= budget:
        return False, "budget_exhausted"
    if _is_low_value_file(rel_path):
        return False, "low_value_file"
    if _is_trivial(content):
        return False, "trivial"
    kb = _kb_covers(abs_path, content, patterns)
    if kb:
        return False, f"kb_covered:{kb}"
    if any(i.get("severity") in ("P0", "P1") for i in local_issues):
        return False, "local_p01_covered"
    return True, "needs_semantic"


def load_pattern_library():
    """加载模式库，返回 {pattern_id: pattern_dict}"""
    if not os.path.isfile(_PATTERN_LIB_PATH):
        return {}
    with open(_PATTERN_LIB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {p["id"]: p for p in data.get("patterns", [])}


def read_file_content(filepath):
    """读取文件内容（带容错）"""
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def extract_diff_files(diff_output):
    """从 git diff 输出提取变更文件列表"""
    files = []
    for line in diff_output.splitlines():
        match = re.match(r'^\+\+\+ b/(.+)$', line)
        if match:
            files.append(match.group(1))
    return [f for f in files if f.endswith('.py')]


def build_review_prompt(file_path, content, patterns):
    """构建 AI 审查提示词"""
    pattern_context = ""
    relevant_patterns = []
    # 找与文件路径相关的模式
    for pid, pat in patterns.items():
        fp = pat.get("detection", {}).get("file_pattern", "*.py")
        if fp == "*.py" or file_path.endswith(fp.replace("*", "")):
            relevant_patterns.append(f"  - {pid}: {pat.get('title', pid)} ({pat['severity']})")

    if relevant_patterns:
        pattern_context = "\n已知模式库（请特别关注这些模式是否命中）：\n" + "\n".join(relevant_patterns[:10])

    return f"""你是金水谣代码审查 AI Agent。请对以下 Python 文件做语义级审查。

审查维度（只报真正有问题的地方，不报格式/命名等 ruff 已覆盖的）：
1. 逻辑缺陷：条件分支遗漏、边界条件缺失、异常恢复不当
2. 并发安全：共享资源读写无锁、状态改后不恢复（缺 try/finally）
3. 可维护性：上帝函数/死代码/跨域盲并/过度耦合
4. 安全风险：SSRF/路径穿越/密钥泄露/不安全反序列化
5. 性能反模式：O(n²) 循环/全局缓存无限增长/集合切片

输出格式（严格 JSON 对象，顶层必须是 {{"issues": [...]}}，每个问题一个对象）：
```json
{{
  "issues": [
    {{
      "pattern_id": "PAT-xxx 或 null",
      "severity": "P0/P1/P2/P3",
      "line": 行号或null,
      "category": "logic/concurrency/maintainability/security/performance",
      "description": "问题描述（中文，简洁具体）",
      "fix_hint": "修复建议",
      "confidence": 0.0-1.0
    }}
  ]
}}
```

字段名必须严格为上面列出的 7 个（不要改名，如不要写 pattern_review/review/suggestion）。
description 和 fix_hint 的值中禁止使用英文双引号 "，如需引用请用单引号 ' 或中文引号「」。
如果文件没有问题，返回 {{"issues": []}}。
{pattern_context}

文件: {file_path}
内容:
```python
{content}
```
"""


def _read_secret(fname):
    """从安全目录读取密钥文件内容（仅 .jinshuiyao-secrets，禁止项目根/CWD 明文回退）"""
    _SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
    p = os.path.join(_SECRETS_DIR, fname)
    if os.path.isfile(p):
        try:
            with open(p, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def _deepseek_cfg():
    """DeepSeek 官方 provider 配置（付费，质量高）"""
    return {
        "base_url": "https://api.deepseek.com/chat/completions",
        # 安全铁律 JS-20260724：仅安全目录 + 环境变量；禁止明文回退
        "api_key": _read_secret("deepseek_key.txt") or os.environ.get("DEEPSEEK_API_KEY", ""),
        # 当前账号仅支持 v4-pro / v4-flash（旧 deepseek-chat 已弃用）
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    }


def _siliconflow_cfg():
    """硅基流动 provider 配置（默认用免费开源模型，零成本）

    免费模型实测（2026-07-26 两轮）：
      - THUDM/GLM-4-9B-0414       ✅ 默认：8661字符真实审查prompt 3秒返回；JSON模式下结构干净、
                                     能准确抓 P0（除零/KeyError/缺finally），免费区当前最优
      - Qwen/Qwen2.5-7B-Instruct  ⚠️ 可用但慢（4419字符55s）且JSON模式下内容质量崩坏(severity乱码)
      - Qwen/Qwen3-8B             ❌ 长prompt(>2000字符)普遍超时90s+
      - Qwen2.5-Coder-7B / glm-4-9b-chat / DeepSeek-V2.5 ❌ 403 Model disabled（网传免费清单已过期）
    覆盖方式：设 SILICONFLOW_MODEL=其他免费模型名。带 "Pro/" 前缀为收费，不在免费区。
    json_mode=True → call_ai 会带 response_format={"type":"json_object"} 强制结构化输出
    （官方文档：平台所有 LLM 均支持；这是小模型 JSON 可靠性的关键，比提示词约束有效得多）。
    """
    return {
        "base_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": _read_secret("siliconflow_key.txt") or os.environ.get("SILICONFLOW_API_KEY", ""),
        "model": os.environ.get("SILICONFLOW_MODEL", "THUDM/GLM-4-9B-0414"),
        "json_mode": True,
    }


def call_ai(cfg, system_prompt, user_prompt, max_retries=2,
            timeout=None, max_tokens=None, temperature=None):
    """通用 AI 调用（DeepSeek / SiliconFlow 共用 OpenAI 兼容格式）。

    cfg = {"base_url", "api_key", "model"}
    timeout/max_tokens/temperature: 可选覆盖默认值（call_ai_failover 透传用）；
                                    未传时沿用默认（审查场景 120s / 2048 / 0.1）。
    """
    if not cfg.get("api_key"):
        return None, "NO_API_KEY"

    import urllib.request
    body_obj = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        # 低温度确保审查严谨（随机性是结构化输出之敌）；可由外部透传覆盖
        "temperature": 0.1 if temperature is None else temperature,
        # 免费模型生成慢，2048足够覆盖单文件审查结果；如需更详细可设环境变量覆盖
        "max_tokens": int(os.environ.get("AI_REVIEW_MAX_TOKENS", "2048"))
        if max_tokens is None else max_tokens,
    }
    # JSON 模式：API 层强制结构化输出（免费小模型可靠性关键；DeepSeek 官方 API 不需要）
    if cfg.get("json_mode"):
        body_obj["response_format"] = {"type": "json_object"}
    payload = json.dumps(body_obj).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }

    for attempt in range(max_retries + 1):
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected
            req = urllib.request.Request(cfg["base_url"], data=payload, headers=headers)
            # 免费模型响应慢，超时提到120s（可用 AI_REVIEW_TIMEOUT 覆盖，外部透传优先）
            _timeout = timeout if timeout is not None else int(os.environ.get("AI_REVIEW_TIMEOUT", "120"))
            with urllib.request.urlopen(req, timeout=_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"], None
        except Exception as e:
            if attempt == max_retries:
                return None, f"API_ERROR: {e}"
            time.sleep(2 ** attempt)

    return None, "MAX_RETRIES_EXCEEDED"


def call_deepseek(system_prompt, user_prompt, max_retries=2):
    """向后兼容别名：默认走 DeepSeek provider"""
    return call_ai(_deepseek_cfg(), system_prompt, user_prompt, max_retries)


def _coerce_issue_list(result):
    """把模型返回的各种形状统一成 issue 列表：
    - [ {...}, ... ]              → 直接用
    - {"issues": [...]}           → 取 issues（JSON 模式标准包装）
    - { 单个 issue 对象 }          → 包成单元素列表（小模型只报一个问题时常见）
    """
    if isinstance(result, list):
        return [_normalize_issue(i) for i in result if isinstance(i, dict)]
    if isinstance(result, dict):
        if isinstance(result.get("issues"), list):
            return [_normalize_issue(i) for i in result["issues"] if isinstance(i, dict)]
        # 单对象：含 severity/description/review 任一字段即视为一个 issue
        if any(k in result for k in ("severity", "description", "review", "category")):
            return [_normalize_issue(result)]
    return []


def parse_ai_response(response_text):
    """解析 AI 返回的 JSON（容错：对象/数组/围栏块 + 正则兜底 + 字段归一化）"""
    if not response_text:
        return []

    # 尝试直接解析（JSON 模式下通常一次成功；解析成功且为空 = 真没问题）
    try:
        return _coerce_issue_list(json.loads(response_text))
    except json.JSONDecodeError:
        pass

    # 提取 ```json ... ``` 围栏 或 [ ... ] / { ... } 块
    fence = re.search(r'```(?:json)?\s*([\[{][\s\S]*?[\]}])\s*```', response_text)
    match = fence or re.search(r'\[[\s\S]*\]', response_text) or re.search(r'\{[\s\S]*\}', response_text)
    if match:
        blob = match.group(1) if fence else match.group()
        try:
            issues = _coerce_issue_list(json.loads(blob))
            if issues:
                return issues
        except json.JSONDecodeError:
            pass
        # 免费模型可能输出未转义引号破坏 JSON，退化为正则逐对象提取
        issues = _extract_issues_regex(blob)
        if not issues and len(response_text) > 100:
            # 模型返回了很长内容但无法解析，说明输出格式/质量异常
            print(f"[ai_review_agent] [WARN] AI 返回内容无法解析为有效 JSON issues（{len(response_text)} 字符），可能模型输出质量不足",
                  file=sys.stderr)
        return issues

    return []


def _normalize_issue(issue):
    """字段名归一化（兼容模型偏差：pattern_review→pattern_id, review→description）"""
    if not isinstance(issue, dict):
        return issue
    if "pattern_review" in issue and "pattern_id" not in issue:
        issue["pattern_id"] = issue.pop("pattern_review")
    if "review" in issue and "description" not in issue:
        issue["description"] = issue.pop("review")
    if "suggestion" in issue and "fix_hint" not in issue:
        issue["fix_hint"] = issue.pop("suggestion")
    return issue


def _extract_issues_regex(text):
    """JSON 不严格时的容错：逐 {…} 块正则提取字段（容忍未转义引号）

    策略：按已知字段名把对象切块，取字段值到下一个字段名（或块尾）之间，
    再 strip 首尾双引号/逗号/空白。这样即使字符串内部有未转义双引号也能正确提取。
    """
    fields = ("pattern_id", "pattern_review", "severity", "line", "category",
              "description", "review", "fix_hint", "suggestion", "confidence")
    issues = []
    for block in re.findall(r'\{[^{}]*\}', text, re.DOTALL):
        positions = []
        for field in fields:
            m = re.search(rf'"{field}"\s*:\s*', block)
            if m:
                positions.append((m.start(), m.end(), field))
        positions.sort()
        if not positions:
            continue
        issue = {}
        for idx, (_, start, field) in enumerate(positions):
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(block) - 1
            val = block[start:end].strip().rstrip(",").strip()
            # 去首尾双引号
            if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
                val = val[1:-1]
            vlow = val.lower()
            if vlow in ("null", "none"):
                issue[field] = None
            elif vlow == "true":
                issue[field] = True
            elif vlow == "false":
                issue[field] = False
            elif re.match(r'^-?\d+$', val):
                issue[field] = int(val)
            elif re.match(r'^-?\d+\.\d+$', val):
                issue[field] = float(val)
            else:
                issue[field] = val
        if issue:
            issues.append(_normalize_issue(issue))
    return issues


def review_file(file_path, patterns, ai_cfg=None, ai_cfg_list=None, content=None):
    """审查单个文件，返回 issues 列表。
    ai_cfg=None 且 ai_cfg_list=None 时默认 DeepSeek；
    ai_cfg_list 给定（免费模型池）→ 故障转移逐个尝试。
    """
    if content is None:
        content = read_file_content(file_path)

    if content is None:
        return [{"severity": "P3", "category": "maintainability",
                  "line": None, "description": f"文件 {file_path} 无法读取",
                  "pattern_id": None, "fix_hint": "", "confidence": 0.0}]

    # 限制文件大小（超大文件只审查前 300 行，免费模型对超长prompt易超时）
    lines = content.splitlines()
    if len(lines) > 300:
        content = "\n".join(lines[:300])
        note = f"（文件 {len(lines)} 行，仅审查前 300 行）"
    else:
        note = ""

    system_prompt = "你是金水谣代码审查 AI，只报真正的语义问题，不报格式/命名。"
    user_prompt = build_review_prompt(file_path + note, content, patterns)

    if ai_cfg_list:
        # 免费模型池故障转移（call_fn=call_ai 保证重试逻辑/超时/JSON 一致）
        # 免费池全挂时允许退付费兜底（受 llm_budget 成本闸约束）：用户约定"优先免费，实在不行才付费"
        response, error, used_cfg = call_ai_failover(
            ai_cfg_list, system_prompt, user_prompt, call_fn=call_ai,
            allow_paid_fallback=True)
    else:
        if ai_cfg is None:
            ai_cfg = _deepseek_cfg()
        response, error = call_ai(ai_cfg, system_prompt, user_prompt)
        used_cfg = ai_cfg

    if error:
        return [{"severity": "P3", "category": "maintainability",
                  "line": None, "description": f"AI审查调用失败: {error}",
                  "pattern_id": None, "fix_hint": "", "confidence": 0.0}]

    issues = parse_ai_response(response)

    # 修复重试环（业界标准 Self-Correction）：模型返回了长内容但解析不出 issue
    # 且原文不是合法 JSON → 把烂输出回喂让它自我修正一次。仅免费 provider（json_mode）
    # 启用：零成本；DeepSeek 极少格式坏，不为此多花一次付费调用。
    if not issues and response and len(response) > 200 and used_cfg.get("json_mode"):
        try:
            json.loads(response)
        except json.JSONDecodeError:
            repair_prompt = (
                "你上一次的输出不是合法 JSON，无法解析。请把下面内容重新整理为严格合法的 JSON 对象，"
                '顶层格式 {"issues": [...]}，每个 issue 仅含 pattern_id/severity/line/category/'
                "description/fix_hint/confidence 七个字段，不要输出任何其他文字：\n\n" + response[:3000]
            )
            fixed, err2 = call_ai(used_cfg, "你是 JSON 修复器，只输出合法 JSON。", repair_prompt)
            if not err2 and fixed:
                issues = parse_ai_response(fixed)

    # 标准化每个 issue
    for issue in issues:
        issue.setdefault("pattern_id", None)
        issue.setdefault("confidence", 0.5)
        issue.setdefault("fix_hint", "")
        # 确保行号是整数或 null
        if issue.get("line") is not None:
            try:
                issue["line"] = int(issue["line"])
            except (ValueError, TypeError):
                issue["line"] = None

    return issues


def record_pattern_hits(issues, file_path, review_id):
    """记录模式命中到 pattern_hits.jsonl"""
    hits = []
    for issue in issues:
        pid = issue.get("pattern_id")
        if pid:
            hits.append({
                "review_id": review_id,
                "pattern_id": pid,
                "file": file_path,
                "line": issue.get("line"),
                "severity": issue.get("severity", "P2"),
                "confidence": issue.get("confidence", 0.5),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

    if not hits:
        return

    with _review_lock:
        os.makedirs(_REVIEW_DATA_DIR, exist_ok=True)
        with open(_PATTERN_HITS_FILE, "a", encoding="utf-8") as f:
            for hit in hits:
                f.write(json.dumps(hit, ensure_ascii=False) + "\n")


def run_review(files=None, diff_only=False, json_output=False, no_cache=False,
               always_ai=False, no_ai=False, ai_budget=None, fallback=False):
    """执行完整审查流程"""
    review_id = f"R-{time.strftime('%Y%m%d')}-{int(time.time()) % 10000:04d}"
    start_time = time.time()

    # ── provider 配置：默认 DeepSeek；设 AI_REVIEW_PROVIDER=siliconflow 走免费模型 ──
    # 分层省费：普通文件用 primary（免费硅基流动 / DeepSeek），高风险文件回退 DeepSeek 保质量
    _primary_name = os.environ.get("AI_REVIEW_PROVIDER", "deepseek").lower()
    _primary_cfg = _deepseek_cfg()  # 默认单模型 cfg（非 siliconflow 时用）
    _primary_cfgs = None            # 免费模型池（siliconflow 时填充）
    if _primary_name == "siliconflow":
        _primary_cfgs = get_free_provider_cfgs() if get_free_provider_cfgs else []
        if not _primary_cfgs:
            # 池为空（配置缺失/无密钥）→ 退回 DeepSeek，不静默失败
            _primary_name = "deepseek"
            print("[ai_review_agent] [WARN] 免费模型池为空（配置缺失或无密钥），回退 DeepSeek。",
                  file=sys.stderr)
        else:
            _primary_cfg = _primary_cfgs[0]  # 占位，实际走 ai_cfg_list
    _fallback_cfg = _deepseek_cfg()  # 高风险文件兜底用 DeepSeek（若有 key）

    # 友好提示：选了硅基流动但池里没有任何可用密钥，避免普通文件静默失败(NO_API_KEY)
    if _primary_name == "siliconflow":
        _any_key = any(c.get("api_key") for c in _primary_cfgs)
        if not _any_key:
            print("[ai_review_agent] [WARN] 未找到硅基流动密钥（~/.jinshuiyao-secrets/siliconflow_key.txt）。"
                  "请用 `tools/set_secret.py --name siliconflow_key` 配置，否则普通文件 AI 审查会失败(NO_API_KEY)。",
                  file=sys.stderr)

    # 1. 确定审查文件列表
    if files:
        file_list = [f.strip() for f in files.split(",")]
    elif diff_only:
        import subprocess
        try:
            diff = subprocess.check_output(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=_PROJECT_ROOT, text=True, timeout=10
            )
            file_list = [f for f in diff.splitlines() if f.endswith('.py')]
        except Exception:
            file_list = []
    else:
        # 默认：扫描最近修改的 .py 文件
        file_list = []
        for root, dirs, filenames in os.walk(_PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", "venv_314", ".git", "node_modules"}]
            for fn in filenames:
                if fn.endswith('.py'):
                    fp = os.path.join(root, fn)
                    try:
                        mtime = os.path.getmtime(fp)
                        if time.time() - mtime < 86400:  # 24小时内修改
                            file_list.append(fp)
                    except Exception:
                        pass
        file_list.sort(key=lambda f: os.path.getmtime(f) if os.path.isfile(f) else 0, reverse=True)
        file_list = file_list[:10]  # 最多10个文件

    if not file_list:
        print("[ai_review_agent] 无审查文件")
        return {"review_id": review_id, "files": [], "issues": [], "duration_ms": 0}

    # 2. 加载模式库
    patterns = load_pattern_library()

    # 3. 逐文件审查（带结果缓存 + 本地/知识库门禁，避免无谓调用 DeepSeek）
    use_cache = not no_cache
    cache = _load_review_cache() if use_cache else {}
    all_issues = []
    # AI 调用统计：让用户看到省了多少次 API
    ai_stats = {"calls": 0, "skipped": 0, "reasons": {}}
    # 有效预算：--no-ai 强制 0（纯本地）；否则用 --ai-budget（None=不限）
    effective_budget = 0 if no_ai else ai_budget
    budget_used = 0
    for filepath in file_list:
        # 相对路径
        rel_path = filepath.replace(_PROJECT_ROOT + os.sep, "")
        if not os.path.isabs(filepath):
            abs_path = os.path.join(_PROJECT_ROOT, filepath)
            rel_path = filepath
        else:
            abs_path = filepath

        content = read_file_content(abs_path)
        # 本地轻量预检（免费，始终跑，避免漏掉 P0）
        local_issues = _local_quick_check(content) if content else []

        # 缓存命中（内容未变且未过期）→ 直接复用，不调 API
        fhash = _file_content_hash(abs_path) if use_cache else None
        cached = cache.get(fhash) if fhash else None
        if cached and (time.time() - cached.get("ts", 0) < _CACHE_TTL):
            print(f"[ai_review_agent] 命中缓存 {rel_path}（跳过 DeepSeek，省一次调用）", file=sys.stderr)
            issues = cached.get("issues", [])
            ai_stats["skipped"] += 1
            ai_stats["reasons"]["cache"] = ai_stats["reasons"].get("cache", 0) + 1
        else:
            call, reason = _should_call_ai(
                abs_path, rel_path, content, patterns, local_issues,
                always_ai=always_ai, budget=effective_budget, used=budget_used)
            if call:
                # 选 provider：
                #  - 高风险文件（并发/网络/子进程等）：若有 DeepSeek key 且未禁用回退 → 用 DeepSeek 保质量
                #  - 硅基流动：走免费模型池故障转移（ai_cfg_list）
                #  - 其余：用 primary（deepseek 付费），绝不偷偷回退 DeepSeek
                if (_has_serious_tokens(content) and _fallback_cfg.get("api_key")
                        and fallback):
                    _use_cfg, _use_prov = _fallback_cfg, "deepseek(fallback:serious)"
                    ai_issues = review_file(abs_path, patterns, ai_cfg=_use_cfg)
                elif _primary_name == "siliconflow" and _primary_cfgs:
                    # 精准匹配：按文件复杂度选质量合适的免费模型（light/medium/heavy），
                    # 复杂推理文件强制高质量模型，免费不够格则退付费兜底
                    from core.free_model_pool import pick_cfg_for_task
                    if _has_serious_tokens(content):
                        _pick = pick_cfg_for_task(_primary_cfgs, complexity="heavy")
                        if _pick:
                            _use_prov = f"siliconflow-pick(heavy:{_pick.get('model')})"
                            ai_issues = review_file(abs_path, patterns, ai_cfg=_pick)
                        elif _fallback_cfg.get("api_key"):
                            _use_prov = "deepseek(fallback:heavy)"
                            ai_issues = review_file(abs_path, patterns, ai_cfg=_fallback_cfg)
                        else:
                            _use_prov = "siliconflow-pool(failover)"
                            ai_issues = review_file(abs_path, patterns, ai_cfg_list=_primary_cfgs)
                    else:
                        _use_prov = "siliconflow-pool(failover)"
                        ai_issues = review_file(abs_path, patterns, ai_cfg_list=_primary_cfgs)
                else:
                    _use_cfg, _use_prov = _primary_cfg, _primary_name
                    ai_issues = review_file(abs_path, patterns, ai_cfg=_use_cfg)
                print(f"[ai_review_agent] 审查 {rel_path} via {_use_prov} ...", file=sys.stderr)
                # 合并本地预检结论，避免丢失
                issues = ai_issues + local_issues
                budget_used += 1
                ai_stats["calls"] += 1
            else:
                print(f"[ai_review_agent] 跳过 {rel_path}（{reason}，省 API）", file=sys.stderr)
                issues = local_issues  # 仅保留本地预检结论
                ai_stats["skipped"] += 1
                ai_stats["reasons"][reason] = ai_stats["reasons"].get(reason, 0) + 1
            if use_cache and fhash:
                cache[fhash] = {"ts": time.time(), "rel": rel_path, "issues": issues}

        for issue in issues:
            issue["file"] = rel_path
        all_issues.extend(issues)

        # 记录模式命中
        record_pattern_hits(issues, rel_path, review_id)

    if use_cache:
        _save_review_cache(cache)

    duration_ms = int((time.time() - start_time) * 1000)

    # 4. 生成报告
    report = {
        "review_id": review_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "files_reviewed": [f.replace(_PROJECT_ROOT + os.sep, "") if os.path.isabs(f) else f for f in file_list],
        "total_issues": len(all_issues),
        "p0_count": sum(1 for i in all_issues if i.get("severity") == "P0"),
        "p1_count": sum(1 for i in all_issues if i.get("severity") == "P1"),
        "p2_count": sum(1 for i in all_issues if i.get("severity") == "P2"),
        "p3_count": sum(1 for i in all_issues if i.get("severity") == "P3"),
        "issues": all_issues,
        "duration_ms": duration_ms,
        "ai_call_stats": ai_stats,
    }

    # 保存审查历史
    history_file = os.path.join(_REVIEW_DATA_DIR, "review_history.jsonl")
    with _review_lock:
        os.makedirs(_REVIEW_DATA_DIR, exist_ok=True)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")

    # 输出
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        # Markdown 报告（避免 emoji，兼容 Windows GBK 控制台）
        print(f"\n## [报告] AI 语义审查报告 {review_id}")
        print(f"审查文件: {len(file_list)} 个 | 耗时: {duration_ms}ms")
        print(f"P0: {report['p0_count']} | P1: {report['p1_count']} | P2: {report['p2_count']} | P3: {report['p3_count']}")
        st = report.get("ai_call_stats", {})
        if st.get("calls") or st.get("skipped"):
            reason_str = f" | 省API原因: {st['reasons']}" if st.get("reasons") else ""
            print(f"[费用] AI 调用: {st['calls']} 次 | 跳过(省API): {st['skipped']} 次{reason_str}")
        if all_issues:
            for issue in sorted(all_issues, key=lambda x: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(x.get("severity", "P3"), 3)):
                sev_mark = {"P0": "[P0]", "P1": "[P1]", "P2": "[P2]", "P3": "[P3]"}.get(issue.get("severity", "P3"), "[?]")
                print(f"  {sev_mark} [{issue['severity']}] {issue.get('file', '?')}:{issue.get('line', '?')} — {issue['description']}")
                if issue.get("fix_hint"):
                    print(f"    [提示] {issue['fix_hint']}")
        else:
            print("  [OK] AI 语义审查无问题")

    return report


def main():
    # Windows 控制台默认 GBK，reconfigure 为 UTF-8 避免中文/特殊字符编码崩溃
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="金水谣 AI 语义审查 Agent")
    parser.add_argument("--files", help="逗号分隔的文件路径")
    parser.add_argument("--diff-only", action="store_true", help="仅审查 git diff 变更文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--pr", type=int, help="GitHub PR 号（需 gh CLI）")
    parser.add_argument("--no-cache", action="store_true", help="禁用结果缓存，强制重新调用 DeepSeek")
    parser.add_argument("--always-ai", action="store_true", help="强制对所有文件调用 DeepSeek（忽略省费门禁）")
    parser.add_argument("--no-ai", action="store_true", help="纯本地审查，绝不调用 DeepSeek（零 API 费用）")
    parser.add_argument("--ai-budget", type=int, default=None, help="单次运行最多调用 AI 次数（0=禁用，默认不限）")
    parser.add_argument("--provider", choices=["deepseek", "siliconflow"], default=None,
                        help="强制指定 AI 审查 provider（覆盖 AI_REVIEW_PROVIDER 环境变量）")
    parser.add_argument("--fallback", action="store_true",
                        help="高风险文件（并发/网络/子进程/文件IO等）回退 DeepSeek 保质量（默认全免费，此项才花 DeepSeek 钱）")
    args = parser.parse_args()

    if args.provider:
        os.environ["AI_REVIEW_PROVIDER"] = args.provider

    if args.pr:
        # PR 模式：获取 PR 变更文件列表
        import subprocess
        try:
            diff = subprocess.check_output(
                ["gh", "pr", "diff", str(args.pr)],
                cwd=_PROJECT_ROOT, text=True, timeout=30
            )
            files_list = extract_diff_files(diff)
            result = run_review(files=",".join(files_list), json_output=args.json,
                                no_cache=args.no_cache, always_ai=args.always_ai,
                                no_ai=args.no_ai, ai_budget=args.ai_budget,
                                fallback=args.fallback)
        except Exception as e:
            print(f"[ai_review_agent] PR 模式失败: {e}")
            result = {"review_id": "ERROR", "issues": [], "error": str(e)}
    else:
        result = run_review(files=args.files, diff_only=args.diff_only, json_output=args.json,
                            no_cache=args.no_cache, always_ai=args.always_ai,
                            no_ai=args.no_ai, ai_budget=args.ai_budget,
                            fallback=args.fallback)

    return result


if __name__ == "__main__":
    main()
