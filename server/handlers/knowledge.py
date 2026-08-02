# -*- coding: utf-8 -*-
"""金水谣系统 - 知识库 & AI 记忆端点

路由（POST）：
  /api/knowledge/stats          — 知识库统计
  /api/knowledge/search?q=     — 搜索知识（GET 变体，POST 中也支持）
  /api/knowledge/list          — 知识卡片列表
  /api/knowledge/add           — 添加知识卡片
  /api/knowledge/extract-archive — URL 提取并归档
  /api/video/ingest            — 视频文案提取并归档到知识库
  /api/memory                  — AI 记忆 新增/删除/编辑

路由（GET）：
  /api/memory                  — AI 记忆读取
"""
import json
import hashlib
import urllib.parse
import os

from ..config import BASE_DIR, ROOT_DIR
from ..utils import log, run_external


# ---------------------------------------------------------------------------
# AI 记忆辅助函数（ChatGPT Memory 范式）
# 数据源：用户级 ~/.workbuddy/MEMORY.md（跨项目共用）
#        项目级 <模型根>/.workbuddy/memory/MEMORY.md（仅本项目）
# 用行级增删改实现，避免破坏既有 markdown 结构。
# ---------------------------------------------------------------------------
def _memory_path(scope):
    if scope == 'user':
        return os.path.expanduser(os.path.join('.workbuddy', 'MEMORY.md'))
    if scope == 'project':
        return os.path.join(ROOT_DIR, '.workbuddy', 'memory', 'MEMORY.md')
    return None


def _parse_memory_file(path):
    items = []
    if not os.path.isfile(path):
        return items
    section = ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.rstrip('\n')
                if s.lstrip().startswith('#'):
                    section = s.lstrip('#').strip()
                    continue
                st = s.strip()
                if not st:
                    continue
                mid = hashlib.md5((section + '|' + st).encode('utf-8')).hexdigest()[:12]
                items.append({'id': mid, 'section': section, 'text': st})
    except Exception:
        pass
    return items


def _read_memories():
    return {
        'user': _parse_memory_file(_memory_path('user')),
        'project': _parse_memory_file(_memory_path('project')),
    }


def _ensure_section(path, section):
    """确保文件存在且含有指定 section 标题。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sec_line = '## ' + section
    if not os.path.isfile(path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# 金水谣工作台 · AI 记忆（由工作台自动管理）\n\n' + sec_line + '\n')
        return
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if sec_line not in content:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n' + sec_line + '\n')


def _memory_add(scope, text, section='记忆面板（AI 自动管理）'):
    path = _memory_path(scope)
    if not path:
        return False, '未知 scope'
    text = (text or '').strip()
    if not text:
        return False, '内容不能为空'
    _ensure_section(path, section)
    prefix = '' if text.startswith(('-', '*')) else '- '
    with open(path, 'a', encoding='utf-8') as f:
        f.write(prefix + text + '\n')
    return True, 'ok'


def _memory_remove(scope, old_text, mid=None):
    path = _memory_path(scope)
    if not path or not os.path.isfile(path):
        return False, '文件不存在'
    if not mid and not (old_text or '').strip():
        return False, '未提供待删除内容'
    lines = open(path, 'r', encoding='utf-8').read().split('\n')
    target_idx = None
    cur_section = ''
    for i, ln in enumerate(lines):
        s = ln.rstrip('\n')
        if s.lstrip().startswith('#'):
            cur_section = s.lstrip('#').strip()
            continue
        st = s.strip()
        if not st:
            continue
        if mid:
            h = hashlib.md5((cur_section + '|' + st).encode('utf-8')).hexdigest()[:12]
            if h == mid:
                target_idx = i
                break
        else:
            if st == (old_text or '').strip():
                target_idx = i
                break
    if target_idx is None:
        return False, '未找到该条记忆'
    del lines[target_idx]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return True, 'ok'


def _memory_edit(scope, old_text, new_text, mid=None):
    path = _memory_path(scope)
    if not path or not os.path.isfile(path):
        return False, '文件不存在'
    repl = (new_text or '').strip()
    if not repl:
        return False, '新内容不能为空'
    lines = open(path, 'r', encoding='utf-8').read().split('\n')
    target_idx = None
    cur_section = ''
    for i, ln in enumerate(lines):
        s = ln.rstrip('\n')
        if s.lstrip().startswith('#'):
            cur_section = s.lstrip('#').strip()
            continue
        st = s.strip()
        if not st:
            continue
        if mid:
            h = hashlib.md5((cur_section + '|' + st).encode('utf-8')).hexdigest()[:12]
            if h == mid:
                target_idx = i
                break
        else:
            if st == (old_text or '').strip():
                target_idx = i
                break
    if target_idx is None:
        return False, '未找到该条记忆'
    prefix = '' if repl.startswith(('-', '*')) else '- '
    lines[target_idx] = prefix + repl
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return True, 'ok'


# ---------------------------------------------------------------------------
# GET 路由处理函数
# ---------------------------------------------------------------------------
def handle_get_memory(handler):
    """GET /api/memory — AI 记忆读取（只读，对局域网开放）"""
    try:
        handler._send_json({"ok": True, "memories": _read_memories()})
    except Exception as e:
        handler._send_json({"error": str(e)}, 500)


# ---------------------------------------------------------------------------
# POST 路由处理函数
# ---------------------------------------------------------------------------
def handle_knowledge_stats(handler):
    """POST /api/knowledge/stats — 知识库统计"""
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        stats = db.stats()
        handler._send_json({"ok": True, "stats": stats})
    except Exception as e:
        log(f'知识库统计异常: {e}')
        handler._send_json({"error": f"获取统计失败：{e}"}, 500)


def handle_knowledge_search(handler, parsed):
    """POST /api/knowledge/search — 搜索知识（BM25 排序 + GraphRAG 三元组 + 语义向量）

    2026-08-02 升级：主检索从子串匹配升级为网关 BM25（中文滑窗+IDF），
    返回结构保持兼容（results/triples/vectors），前端无需改动。
    """
    query = urllib.parse.parse_qs(parsed.query).get('q', [''])[0]
    domain = urllib.parse.parse_qs(parsed.query).get('domain', [''])[0] or None
    value_level = urllib.parse.parse_qs(parsed.query).get('value_level', [''])[0] or None
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        cards = db._data.get('cards', [])
        docs = []
        for c in cards:
            if domain and c.get('subsystem', '') not in ('', domain):
                continue
            if value_level and c.get('value_level', '') != value_level:
                continue
            docs.append({
                'id': c.get('id', c.get('title', '')),
                'text': (c.get('title', '') + '\n' + c.get('content', '') + '\n'
                         + ' '.join(c.get('tags', [])))[:3000],
                'card': c,  # 完整卡片（兼容旧接口 19 字段）
            })
        from core.knowledge_gateway import _bm25
        scored = _bm25(query, docs, 50) if query.strip() else docs[:50]
        results = []
        for s in scored:
            card = dict(s.get('card', {}))
            card['score'] = s.get('score', 0)
            results.append(card)
        # P3-1：并入 GraphRAG 三元组证据（离线、fail-safe，不影响主检索）
        triples = []
        try:
            from core.auto_knowledge import search_graph_triples
            triples = search_graph_triples(query, limit=10)
        except Exception as e:
            log(f'图谱三元组检索降级: {e}')
        # P3-2：并入语义向量召回（离线 VSM，召回同义/近义但字面不同的知识）
        vectors = []
        try:
            from core.auto_knowledge import search_knowledge_vector
            vectors = search_knowledge_vector(query, limit=10)
        except Exception as e:
            log(f'向量检索降级: {e}')
        handler._send_json({
            "ok": True,
            "results": results,
            "triples": triples,
            "vectors": vectors,
        })
    except Exception as e:
        log(f'知识搜索异常: {e}')
        handler._send_json({"error": f"搜索失败：{e}"}, 500)


def handle_kg_search(handler, parsed):
    """GET /api/knowledge/graph/search?q=xxx — 图谱三元组检索（实体/关系）

    直接检索 knowledge/graph_triples.json 的 GraphRAG 三元组（全部来源），
    返回与 query 命中的 (主体,谓词,客体) 三元组，供前端/AI 做图谱证据检索。
    离线、无网络依赖、fail-safe。
    """
    params = urllib.parse.parse_qs(parsed.query)
    query = params.get("q", [""])[0]
    if not query:
        handler._send_json({"error": "需要 q 参数"}, 400)
        return
    try:
        limit = int(params.get("limit", ["20"])[0])
    except Exception:
        limit = 20
    source = params.get("source", [""])[0] or None
    try:
        from core.auto_knowledge import search_graph_triples
        triples = search_graph_triples(query, limit=limit, source=source)
        handler._send_json({
            "ok": True,
            "query": query,
            "source": source,
            "triples": triples,
            "total": len(triples),
        })
    except Exception as e:
        handler._send_json({"error": f"图谱检索失败：{e}"}, 500)


def handle_knowledge_vector_search(handler, parsed):
    """GET /api/knowledge/vector/search?q=xxx — 语义向量召回（离线 VSM）

    基于 knowledge.vector_index 的 TF-IDF 余弦检索，召回与 query 语义相近的知识卡片，
    能找回"同义/近义但字面不同"的内容。离线、无网络依赖、fail-safe。
    """
    params = urllib.parse.parse_qs(parsed.query)
    query = params.get("q", [""])[0]
    if not query:
        handler._send_json({"error": "需要 q 参数"}, 400)
        return
    try:
        limit = int(params.get("limit", ["10"])[0])
    except Exception:
        limit = 10
    try:
        min_score = float(params.get("min_score", ["0.01"])[0])
    except Exception:
        min_score = 0.01
    try:
        from core.auto_knowledge import search_knowledge_vector
        vectors = search_knowledge_vector(query, limit=limit, min_score=min_score)
        handler._send_json({
            "ok": True,
            "query": query,
            "min_score": min_score,
            "vectors": vectors,
            "total": len(vectors),
        })
    except Exception as e:
        handler._send_json({"error": f"向量检索失败：{e}"}, 500)


def handle_knowledge_tags_validate(handler, parsed):
    """GET /api/knowledge/tags/validate — 经验箱标签校验（白名单+数量+格式+一致性）

    调用 knowledge.tag_validator 校验经验箱《标签铁律》：标签必须来自 9 个白名单、
    每条 1~3 个、须以 [标签] 形式出现在标题行、且用到的标签在「分类索引」有对应类目。
    离线、无网络依赖、fail-safe。
    """
    try:
        from knowledge.tag_validator import validate_experience_tags
        report = validate_experience_tags()
        handler._send_json({"ok": True, "report": report})
    except Exception as e:
        handler._send_json({"error": f"标签校验失败：{e}"}, 500)


def handle_knowledge_vector_rebuild(handler):
    """POST /api/knowledge/vector/rebuild — 手动重建语义向量索引（P3-4，运维触发）

    触发 rebuild_vector_index：重建离线 VSM 索引、持久化、刷新进程内缓存单例。
    写操作（落盘 + 重建），仅允许本机触发（防局域网越权 + 避免并发重建放大 IO）。
    失败降级返回错误，不影响主检索（get_vector_index 有 mtime 失效兜底）。
    """
    if not handler._is_local():
        handler._send_json({"error": "安全限制：重建向量索引仅允许本机操作。"}, 403)
        return
    try:
        from knowledge.vector_index import rebuild_vector_index
        idx = rebuild_vector_index()
        handler._send_json({
            "ok": True,
            "doc_count": idx.doc_count,
            "built_at": idx.built_at,
            "source_mtime": idx.source_mtime,
        })
    except Exception as e:
        handler._send_json({"error": f"向量索引重建失败：{e}"}, 500)


def handle_knowledge_list(handler, parsed):
    """POST /api/knowledge/list — 知识卡片列表"""
    domain = urllib.parse.parse_qs(parsed.query).get('domain', [''])[0] or None
    value_level = urllib.parse.parse_qs(parsed.query).get('value_level', [''])[0] or None
    limit = int(urllib.parse.parse_qs(parsed.query).get('limit', ['50'])[0])
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        cards = db.list_cards(domain=domain, value_level=value_level, limit=limit)
        handler._send_json({"ok": True, "cards": cards})
    except Exception as e:
        log(f'知识列表异常: {e}')
        handler._send_json({"error": f"获取列表失败：{e}"}, 500)


def handle_knowledge_add(handler):
    """POST /api/knowledge/add — 添加知识卡片"""
    content_length = int(handler.headers.get('Content-Length', 0))
    body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    if not title or not content:
        handler._send_json({"error": "标题和内容不能为空"}, 400)
        return
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        card_id = db.add_card(
            title=title,
            content=content,
            category=data.get('category', 'inspiration'),
            domain=data.get('domain', 'general'),
            tags=data.get('tags'),
            source=data.get('source', '用户输入'),
            source_url=data.get('source_url', ''),
            value_level=data.get('value_level'),
            priority=data.get('priority', 5),
            subsystem=data.get('subsystem'),
        )
        handler._send_json({"ok": True, "card_id": card_id})
    except Exception as e:
        log(f'添加知识异常: {e}')
        handler._send_json({"error": f"添加失败：{e}"}, 500)


def handle_knowledge_extract_archive(handler):
    """POST /api/knowledge/extract-archive — URL提取并归档"""
    # 安全加固：URL提取归档会写入知识库，仅允许本机操作（防局域网 SSRF/污染）
    if not handler._is_local():
        handler._send_json({"error": "安全限制：URL 提取归档仅允许本机操作。"}, 403)
        return
    content_length = int(handler.headers.get('Content-Length', 0))
    body = handler.rfile.read(content_length).decode('utf-8', errors='replace')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return
    url = data.get('url', '').strip()
    if not url:
        handler._send_json({"error": "请提供链接"}, 400)
        return
    ok, msg = handler._is_safe_http_url(url)
    if not ok:
        handler._send_json({"error": "链接校验未通过：" + msg}, 400)
        return

    def _do_extract():
        from core.video_extractor import VideoExtractor
        from core.content_refiner import ContentRefiner
        from knowledge.mirofish_db import MiroFishDB

        def _as_text(v, default=''):
            # 类型防御（JS-20260730-04 P1-1）：AI 精炼结果字段可能为 list/dict，
            # 直接拼接 str 会 TypeError: can only concatenate str (not "list") to str
            if v is None:
                return default
            if isinstance(v, str):
                return v
            if isinstance(v, (list, tuple)):
                return '\n'.join(str(x) for x in v)
            return str(v)

        extractor = VideoExtractor()
        refiner = ContentRefiner()
        db = MiroFishDB()
        extracted = extractor.extract(url)
        refined = refiner.refine(extracted)
        card_id = db.add_card(
            title=_as_text(refined.get('title'), '未命名知识') or '未命名知识',
            content=_as_text(refined.get('summary')) + '\n\n' + _as_text(refined.get('key_points')),
            category='resource',
            domain=_as_text(refined.get('domain'), 'general') or 'general',
            source='URL提取',
            source_url=url,
            tags=refined.get('tags', []),
            value_level='知识',
            priority=5,
        )
        return {"ok": True, "card_id": card_id, "refined": refined}
    resp, status = run_external(_do_extract, "extract")
    handler._send_json(resp, status)


def handle_video_ingest(handler):
    """POST /api/video/ingest — 视频文案提取并归档到「闭环成长」知识库"""
    # 安全加固：视频归档会写入知识库，仅允许本机操作
    if not handler._is_local():
        handler._send_json({"error": "安全限制：视频归档仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0))
    except Exception:
        cl = 0
    if cl > 20000:
        handler._send_json({"error": "请求体过大"}, 400)
        return
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return
    url = data.get('url', '').strip()
    if not url:
        handler._send_json({"error": "请提供视频链接"}, 400)
        return
    # SSRF 防护（P1，JS-20260723-37）：即便已 _is_local() 本机守卫，
    # 仍须校验 URL 禁止访问内网/云元数据等保留地址。
    ok, reason = handler._is_safe_http_url(url)
    if not ok:
        handler._send_json({"error": f"链接不安全，已拒绝：{reason}"}, 400)
        return

    def _do_ingest():
        from core.video_to_kb import ingest_to_kb
        return {"ok": True, "result": ingest_to_kb(url)}
    resp, status = run_external(_do_ingest, "video")
    handler._send_json(resp, status)


def handle_post_memory(handler):
    """POST /api/memory — AI 记忆 新增/删除/编辑（写操作仅本机）"""
    if not handler._is_local():
        handler._send_json({"error": "安全限制：修改记忆仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0))
    except Exception:
        cl = 0
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return
    action = data.get('action', '')
    scope = data.get('scope', 'project')
    if scope not in ('user', 'project'):
        scope = 'project'
    if action == 'add':
        ok, msg = _memory_add(scope, data.get('text', ''),
                              data.get('section', '记忆面板（AI 自动管理）'))
        handler._send_json({"ok": ok, "message": msg,
                            "memories": _read_memories() if ok else None})
    elif action == 'delete':
        ok, msg = _memory_remove(scope, data.get('old_text', ''), data.get('id'))
        handler._send_json({"ok": ok, "message": msg,
                            "memories": _read_memories() if ok else None})
    elif action == 'edit':
        ok, msg = _memory_edit(scope, data.get('old_text', ''), data.get('new_text', ''), data.get('id'))
        handler._send_json({"ok": ok, "message": msg,
                            "memories": _read_memories() if ok else None})
    else:
        handler._send_json({"error": "未知 action（应为 add/delete/edit）"}, 400)


# ---------------------------------------------------------------------------
# 个人知识库（用户知识库）端点
# 数据源：knowledge/用户知识库/INDEX.json + *.md 卡片
# 与 MiroFish DB（模型知识库）区分：个人知识库是人可读的Markdown，手动管理
# ---------------------------------------------------------------------------
_USER_KB_DIR = os.path.join(BASE_DIR, "knowledge", "用户知识库")


def _load_user_kb_index():
    """读取个人知识库索引"""
    index_path = os.path.join(_USER_KB_DIR, "INDEX.json")
    if not os.path.isfile(index_path):
        return []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("entries", [])
    except Exception:
        return []


def _read_user_kb_card(filename):
    """读取单张个人知识卡片内容"""
    filepath = os.path.join(_USER_KB_DIR, filename)
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def handle_knowledge_gateway(handler, parsed):
    """GET /api/knowledge/gateway?q=xxx&limit=8 — 知识网关四源召回

    供外部AI/网页助手/服务器统一使用：一次调用从
    知识卡片 + 图谱三元组 + 向量 + 经验条目 + 项目文档 召回相关知识。
    本地离线、fail-safe（任一来源失败不影响其它）。
    """
    params = urllib.parse.parse_qs(parsed.query)
    query = params.get('q', params.get('query', ['']))[0].strip()
    try:
        limit = min(max(int(params.get('limit', ['8'])[0]), 1), 20)
    except Exception:
        limit = 8
    try:
        from core.knowledge_gateway import search
        data = search(query, limit=limit)
        handler._send_json({"ok": True, **data})
    except Exception as e:
        log(f'知识网关检索异常: {e}')
        handler._send_json({"ok": False, "error": f"知识网关检索失败：{e}"}, 500)


def handle_user_kb_list(handler):
    """GET /api/user-kb/list — 个人知识库卡片列表"""
    try:
        entries = _load_user_kb_index()
        cards = []
        for entry in entries:
            card = {
                "title": entry.get("title", ""),
                "file": entry.get("file", ""),
                "tags": entry.get("tags", []),
                "type": entry.get("type", "concept"),
                "source": entry.get("source", ""),
                "timestamp": entry.get("timestamp", ""),
            }
            cards.append(card)
        handler._send_json({"ok": True, "cards": cards, "total": len(cards)})
    except Exception as e:
        handler._send_json({"error": f"读取个人知识库失败：{e}"}, 500)


def handle_user_kb_detail(handler, parsed):
    """GET /api/user-kb/detail?file=xxx.md — 个人知识库卡片详情"""
    params = urllib.parse.parse_qs(parsed.query)
    filename = params.get("file", [""])[0]
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        handler._send_json({"error": "无效的文件名"}, 400)
        return
    content = _read_user_kb_card(filename)
    if content is None:
        handler._send_json({"error": "卡片不存在"}, 404)
        return
    handler._send_json({"ok": True, "file": filename, "content": content})


def handle_user_kb_stats(handler):
    """GET /api/user-kb/stats — 个人知识库统计"""
    try:
        entries = _load_user_kb_index()
        # 统计raw层文件数
        raw_dir = os.path.join(_USER_KB_DIR, "raw")
        raw_count = 0
        if os.path.isdir(raw_dir):
            raw_count = len([f for f in os.listdir(raw_dir) if f.endswith(".md")])
        # 按类型统计
        by_type = {}
        all_tags = []
        for entry in entries:
            t = entry.get("type", "concept")
            by_type[t] = by_type.get(t, 0) + 1
            all_tags.extend(entry.get("tags", []))
        handler._send_json({
            "ok": True,
            "stats": {
                "total_cards": len(entries),
                "raw_evidence": raw_count,
                "by_type": by_type,
                "top_tags": list(set(all_tags))[:20],
            }
        })
    except Exception as e:
        handler._send_json({"error": f"统计失败：{e}"}, 500)


def handle_user_kb_add(handler):
    """POST /api/user-kb/add — 新增个人知识库卡片（写操作仅本机）

    内部调用 knowledge.用户知识库.archive_knowledge.archive 写入一张 .md 卡片，
    并自动维护 INDEX.json / 索引.md，让前端用户能直接往个人库（右脑）存知识。
    """
    # 安全加固：写入个人知识库会落盘，仅允许本机操作（防局域网越权写入）
    if not handler._is_local():
        handler._send_json({"error": "安全限制：写入个人知识库仅允许本机操作。"}, 403)
        return
    try:
        cl = int(handler.headers.get('Content-Length', 0))
    except Exception:
        cl = 0
    if cl > 20000:
        handler._send_json({"error": "请求体过大"}, 400)
        return
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler._send_json({"error": "无效的JSON"}, 400)
        return
    title = (data.get('title') or '').strip()
    content = (data.get('body') or data.get('content') or '').strip()
    if not title or not content:
        handler._send_json({"error": "标题和正文不能为空"}, 400)
        return
    tags = data.get('tags')
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]
    elif not isinstance(tags, list):
        tags = None
    source = (data.get('source') or '网页录入').strip()
    card_type = (data.get('type') or 'concept').strip()
    try:
        import importlib
        mod = importlib.import_module("knowledge.用户知识库.archive_knowledge")
        file_path = mod.archive(
            title=title,
            body=content,
            tags=tags,
            source=source,
            type=card_type,
        )
        handler._send_json({"ok": True, "file": os.path.basename(file_path)})
    except Exception as e:
        log(f'个人知识库写入异常: {e}')
        handler._send_json({"error": f"写入失败：{e}"}, 500)


# ---------------------------------------------------------------------------
# 双库交叉链接（胼胝体）端点
# 连接左脑MiroFish ↔ 右脑用户知识库
# ---------------------------------------------------------------------------

def _get_linker():
    """获取CrossLinker实例"""
    from knowledge.cross_linker import get_linker
    return get_linker()


def handle_crosslinks_get(handler, parsed):
    """GET /api/knowledge/crosslinks?lib=mirofish&id=xxx — 查询某卡片的跨库链接"""
    params = urllib.parse.parse_qs(parsed.query)
    lib = params.get("lib", [""])[0]
    card_id = params.get("id", [""])[0]
    if not lib or not card_id:
        handler._send_json({"error": "需要 lib 和 id 参数"}, 400)
        return
    if lib not in ("mirofish", "user_kb"):
        handler._send_json({"error": "lib 应为 mirofish 或 user_kb"}, 400)
        return
    try:
        linker = _get_linker()
        links = linker.get_links(lib, card_id)
        handler._send_json({"ok": True, "links": links, "total": len(links)})
    except Exception as e:
        handler._send_json({"error": f"查询交叉链接失败：{e}"}, 500)


def handle_crosslinks_discover(handler):
    """POST /api/knowledge/crosslinks/discover — 触发自动发现"""
    if not handler._is_local():
        handler._send_json({"error": "安全限制：仅本机可触发发现"}, 403)
        return
    try:
        linker = _get_linker()
        result = linker.discover()
        handler._send_json({
            "ok": True,
            "new_links": len(result["new_links"]),
            "total_links": result["total_links"],
            "mirofish_count": result["mirofish_count"],
            "user_kb_count": result["user_kb_count"],
            "links": result["new_links"][:10],  # 只返回前10条预览
        })
    except Exception as e:
        handler._send_json({"error": f"自动发现失败：{e}"}, 500)


def handle_crosslinks_stats(handler):
    """GET /api/knowledge/crosslinks/stats — 交叉链接统计"""
    try:
        linker = _get_linker()
        stats = linker.get_stats()
        handler._send_json({"ok": True, "stats": stats})
    except Exception as e:
        handler._send_json({"error": f"统计失败：{e}"}, 500)


def handle_crosslinks_all(handler):
    """GET /api/knowledge/crosslinks/all — 全部交叉链接列表"""
    try:
        linker = _get_linker()
        links = linker.get_all_links()
        handler._send_json({"ok": True, "links": links, "total": len(links)})
    except Exception as e:
        handler._send_json({"error": f"读取失败：{e}"}, 500)


# ---------------------------------------------------------------------------
# 知识图谱端点
# ---------------------------------------------------------------------------

def _get_graph():
    """获取KnowledgeGraph实例"""
    from knowledge.knowledge_graph import get_graph
    return get_graph()


def handle_kg_data(handler, parsed):
    """GET /api/knowledge/graph — 图谱数据（供前端可视化）"""
    params = urllib.parse.parse_qs(parsed.query)
    max_nodes = int(params.get("max_nodes", ["50"])[0])
    try:
        kg = _get_graph()
        data = kg.get_graph_data(max_nodes=max_nodes)
        stats = kg.get_stats()
        handler._send_json({"ok": True, "graph": data, "stats": stats})
    except Exception as e:
        handler._send_json({"error": f"图谱读取失败：{e}"}, 500)


def handle_kg_build(handler):
    """POST /api/knowledge/graph/build — 重建图谱"""
    if not handler._is_local():
        handler._send_json({"error": "安全限制：仅本机可重建图谱"}, 403)
        return
    try:
        kg = _get_graph()
        result = kg.build()
        handler._send_json({"ok": True, "result": result})
    except Exception as e:
        handler._send_json({"error": f"图谱构建失败：{e}"}, 500)


def handle_kg_neighbors(handler, parsed):
    """GET /api/knowledge/graph/neighbors?entity=xxx — 查实体关联"""
    params = urllib.parse.parse_qs(parsed.query)
    entity = params.get("entity", [""])[0]
    if not entity:
        handler._send_json({"error": "需要 entity 参数"}, 400)
        return
    try:
        kg = _get_graph()
        neighbors = kg.get_neighbors(entity)
        node_info = kg.get_node_info(entity)
        handler._send_json({"ok": True, "entity": entity, "info": node_info, "neighbors": neighbors})
    except Exception as e:
        handler._send_json({"error": f"查询失败：{e}"}, 500)


def handle_kg_top(handler):
    """GET /api/knowledge/graph/top — 最重要的实体"""
    try:
        kg = _get_graph()
        top = kg.get_top_entities(20)
        clusters = kg.get_clusters()
        handler._send_json({"ok": True, "top_entities": top, "clusters": clusters[:5]})
    except Exception as e:
        handler._send_json({"error": f"查询失败：{e}"}, 500)
