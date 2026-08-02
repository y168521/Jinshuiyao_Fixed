# -*- coding: utf-8 -*-
"""知识网关（Knowledge Gateway）— 外部AI/网页助手/服务器 统一的四源知识召回层

设计来源：2026 年主流范式（Karpathy LLM Wiki 索引 + 混合检索 BM25/向量/图谱 + 上下文图）。
一次调用，从四个来源召回与 query 相关的知识：

  1. 知识卡片  — MiroFish 库（151 张：经验/成败/方法卡片）
  2. 图谱三元组 — knowledge/graph_triples.json（567 条：实体-关系证据）
  3. 向量召回  — 离线 VSM 向量索引（语义召回）
  4. 经验条目  — 金水谣数据/log/经验收集箱.md（L1 原始层，跨AI共享）
  5. 项目文档  — 交接中心/纲/契/录/总索引/AGENTS.md（项目级上下文）

全部本地离线、零依赖、fail-safe：任一来源失败不影响其它来源。
评分统一用轻量 BM25（IDF 权重 + 位置加权），比子串匹配显著更准。
"""
import json
import math
import os
import re
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPBOX_PATH = os.path.join(BASE_DIR, '金水谣数据', 'log', '经验收集箱.md')
TRIPLE_PATH = os.path.join(BASE_DIR, 'knowledge', 'graph_triples.json')

# 项目文档（网关的"项目级上下文"来源）—— 名称 → 路径（内层优先，外层兜底）
_PROJECT_DOCS = [
    ('AI协作交接中心.md', 'AI协作交接中心.md'),
    ('工作留痕总索引.md', '工作留痕总索引.md'),
    ('金水谣_纲.md', '金水谣_纲.md'),
    ('金水谣_契.md', '金水谣_契.md'),
    ('金水谣_录.md', '金水谣_录.md'),
    ('AGENTS.md', 'AGENTS.md'),
]

_lock = threading.Lock()
_cache = {}  # 文档缓存：path -> (mtime, text)

# 知识资产缓存：key = (资产名, 文件mtime)，文件一变立即失效重载
_asset_cache = {}


def _cached_asset(key, loader, path=None):
    """mtime 键控资产缓存：外部文件变化后下次调用即重载，进程内不重复解析"""
    mtime = None
    if path:
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = None
    ckey = (key, mtime)
    with _lock:
        hit = _asset_cache.get(ckey)
        if hit is not None:
            return hit
    data = loader()
    with _lock:
        _asset_cache[ckey] = data
    return data


# ---------------------------------------------------------------------------
# BM25 轻量实现（零依赖）
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r'[\u4e00-\u9fff]+|[A-Za-z0-9_\-\.]+')


def _tokenize(text):
    """中英文混合分词：中文连续块整体为一个词 + 2字滑窗（提高短词命中）；英文按词。"""
    tokens = []
    for chunk in _WORD_RE.findall(text.lower()):
        if re.fullmatch(r'[\u4e00-\u9fff]+', chunk):
            if len(chunk) <= 4:
                tokens.append(chunk)
            for i in range(len(chunk) - 1):
                tokens.append(chunk[i:i + 2])  # 二元滑窗
        else:
            tokens.append(chunk)
    return tokens


def _bm25(query, docs, k1=1.5, b=0.75):
    """docs: [{id, text, *extra}] → [{id, score, *extra}] 按相关度降序。
    空文档/空查询安全。avgdl 为 0 时退化为词频匹配。"""
    if not docs or not query.strip():
        return []
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    n = len(docs)
    lengths = [len(_tokenize(d.get('text', ''))) for d in docs]
    avgdl = sum(lengths) / n if n else 0
    df = {}
    for d in docs:
        seen = set(_tokenize(d.get('text', '')))
        for t in seen:
            df[t] = df.get(t, 0) + 1
    scored = []
    for d, length in zip(docs, lengths):
        tokens = _tokenize(d.get('text', ''))
        tf = {t: tokens.count(t) for t in q_tokens}
        score = 0.0
        for t in set(q_tokens):
            if t not in tf:
                continue
            f = tf[t]
            idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            denom = f + k1 * (1 - b + b * (length / avgdl)) if avgdl > 0 else f + k1
            score += idf * f / denom
        if score > 0:
            item = dict(d)
            item['score'] = round(score, 4)
            scored.append(item)
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# 各来源召回
# ---------------------------------------------------------------------------
def _recall_cards(query, limit):
    """知识卡片：MiroFish 全文 + BM25 排序（资产缓存，mtime 失效）"""
    try:
        from knowledge.mirofish_db import MiroFishDB
        _MIRO_PATH = os.path.join(BASE_DIR, 'knowledge', 'mirofish_db.json')

        def _load():
            return MiroFishDB()._data.get('cards', [])
        cards = _cached_asset('cards', _load, _MIRO_PATH)
        docs = []
        for c in cards:
            docs.append({
                'id': c.get('id', c.get('title', '')),
                'text': (c.get('title', '') + '\n' + c.get('content', '') + '\n' + ' '.join(c.get('tags', [])))[:3000],
                'title': c.get('title', ''),
                'source': c.get('source', ''),
                'subsystem': c.get('subsystem', ''),
            })
        return _bm25(query, docs, limit)
    except Exception:
        return []


def _recall_triples(query, limit):
    """图谱三元组：主体/谓词/客体拼接后 BM25（资产缓存）"""
    try:
        def _load():
            with open(TRIPLE_PATH, encoding='utf-8') as f:
                return json.load(f).get('triples', [])
        triples = _cached_asset('triples', _load, TRIPLE_PATH)
        docs = [{
            'id': str(i),
            'text': (t.get('subject', '') + ' ' + t.get('predicate', '') + ' ' + t.get('object', '')
                     + ' ' + t.get('source', '')),
            'subject': t.get('subject', ''),
            'predicate': t.get('predicate', ''),
            'object': t.get('object', ''),
            'source': t.get('source', ''),
        } for i, t in enumerate(triples)]
        return _bm25(query, docs, limit)
    except Exception:
        return []


def _recall_vectors(query, limit):
    """向量召回：离线 VSM（语义近义召回，字面不同也能命中）"""
    try:
        from knowledge.knowledge_search import search_knowledge_vector
        hits = search_knowledge_vector(query, limit=limit) or []
        out = []
        for h in hits:
            if isinstance(h, dict):
                out.append({'title': h.get('title', ''), 'text': h.get('text', h.get('content', '')), 'source': 'vector'})
            else:
                out.append({'title': str(h)[:40], 'text': str(h), 'source': 'vector'})
        return out
    except Exception:
        return []


def _load_expbox_entries():
    """经验收集箱条目缓存解析：[{title, body}]（mtime 失效）"""
    def _load():
        if not os.path.isfile(EXPBOX_PATH):
            return []
        with open(EXPBOX_PATH, encoding='utf-8') as f:
            text = f.read()
        entries = []
        for m in re.finditer(r'^## (.+?)\n(.*?)(?=^## |\Z)', text, re.M | re.S):
            title = m.group(1).strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}', title):
                entries.append({'title': title, 'body': m.group(2).strip()})
        return entries
    return _cached_asset('expbox', _load, EXPBOX_PATH)


def _recall_experiences(query, limit):
    """经验条目（L1 原始层）：BM25 + 关联 JS 编号/交接记录"""
    try:
        entries = _load_expbox_entries()
        docs = [{
            'id': e['title'],
            'text': e['title'] + '\n' + e['body'][:2000],
            'title': e['title'],
            'source': '经验收集箱.md#' + e['title'].split('：')[0],
        } for e in entries]
        return _bm25(query, docs, limit)
    except Exception:
        return []


def _load_doc(name, rel_path):
    """读项目文档（内层优先外层兜底），带 mtime 缓存"""
    paths = [os.path.join(BASE_DIR, rel_path),
             os.path.join(os.path.dirname(BASE_DIR), rel_path)]
    for p in paths:
        if os.path.isfile(p):
            try:
                mtime = os.path.getmtime(p)
                with _lock:
                    cached = _cache.get(name)
                    if cached and cached[0] == mtime:
                        return cached[1]
                with open(p, encoding='utf-8', errors='replace') as f:
                    text = f.read()
                with _lock:
                    _cache[name] = (mtime, text)
                return text
            except Exception:
                return ''
    return ''


def _recall_project_docs(query, limit):
    """项目文档：全文档 BM25 评分 + 命中上下文片段"""
    out = []
    for name, rel in _PROJECT_DOCS:
        text = _load_doc(name, rel)
        if not text:
            continue
        scored = _bm25(query, [{'id': name, 'text': text[:20000]}], 1)
        if not scored:
            continue
        # 提取命中片段（含 query 词的上下文窗口）
        snippet = _snippet(text, query)
        out.append({
            'title': name,
            'text': snippet,
            'source': name,
            'score': scored[0]['score'],
        })
    out.sort(key=lambda x: x.get('score', 0), reverse=True)
    return out[:limit]


def _snippet(text, query, width=260):
    """从文档中提取 query 相关片段（首次命中位置前后各 width/2）"""
    for tok in _tokenize(query):
        if not tok:
            continue
        idx = text.lower().find(tok)
        if idx >= 0:
            start = max(0, idx - width // 2)
            return text[start:start + width].replace('\n', ' ')
    return text[:width].replace('\n', ' ')


# ---------------------------------------------------------------------------
# 网关主入口
# ---------------------------------------------------------------------------
def search(query, limit=8):
    """四源知识召回（对外统一入口）

    Returns:
        {query, total, cards, triples, vectors, experiences, project_docs, error}
    """
    query = (query or '').strip()
    if not query:
        return {'query': '', 'total': 0, 'error': '查询为空'}
    result = {'query': query}

    def _safe(key, fn, *a, **kw):
        try:
            result[key] = fn(*a, **kw)
        except Exception:
            result[key] = []  # 单源失败不致命（fail-safe）

    _safe('cards', _recall_cards, query, limit)
    _safe('triples', _recall_triples, query, limit)
    _safe('vectors', _recall_vectors, query, limit)
    _safe('experiences', _recall_experiences, query, limit)
    _safe('project_docs', _recall_project_docs, query, limit)
    result['total'] = sum(len(v) for v in result.values() if isinstance(v, list))
    return result


_WEAK_WORDS = frozenset([
    '怎么', '什么', '怎么样', '为什么', '如何', '怎样', '可否', '能不能',
    '今天', '明天', '昨天', '天气', '你好', '你们', '我们', '他们', '这个',
    '那个', '可以', '应该', '哪些', '有哪些', '怎么办', '告诉', '说说',
    '请问', '一下', '一些', '一点', '可能', '或者', '还是', '的话', '的', '了',
    '啊', '呢', '吗', '吧', '么', '是不是', '是否有', '不知道',
    '随便', '聊聊', '聊天', '说说', '讲讲', '欢迎', '您好', '嗨', '哈喽',
    # 高频口语寒暄整块（含2字滑窗产物，直接整块禁用）
    '今天天气', '天气怎么样', '今天天气怎么样', '最近怎么样', '最近好吗',
    '你叫什么', '你在干嘛', '你好吗', '今天好吗', '过得怎么样',
])


def _relevant(items, query):
    """相关性门槛：查询必须先有实质 native 词（非黑名单的原文词），
    否则视为寒暄/泛化查询一律不注入（防"文档自指"假阳性）；
    native 词命中即相关；native 无命中时滑窗强词 >=2 个命中兜底。
    """
    q_native = [w for w in _WORD_RE.findall(query.lower()) if len(w) >= 2 and w not in _WEAK_WORDS]
    if not q_native:
        return []  # 查询全是虚词/寒暄（如"今天天气怎么样"）→ 不注入
    q_tokens = set(_tokenize(query))
    q_slide_strong = q_tokens - set(q_native) - _WEAK_WORDS
    out = []
    for it in items:
        t = it.get('text', '').lower()
        if any(w in t for w in q_native):
            out.append(it)
            continue
        if len(q_slide_strong) >= 2:
            slide_hits = {w for w in q_slide_strong if w in t}
            if len(slide_hits) >= 2:
                out.append(it)
    return out


def summarize(query, limit=4):
    """轻量版：只取卡片+经验+项目文档（供 AI 助手/模型 prompt 拼装，控制 token）。
    带相关性门槛：与查询无关的话题返回空串，避免污染模型上下文。"""
    r = search(query, limit=limit)
    lines = []
    for exp in _relevant(r.get('experiences', []), query)[:2]:
        lines.append(f"· 经验[{exp['title']}]: {exp['text'][:220]}")
    for card in _relevant(r.get('cards', []), query)[:2]:
        lines.append(f"· 知识卡片[{card.get('title', '')}]: {card.get('text', '')[:220]}")
    for d in _relevant(r.get('project_docs', []), query)[:2]:
        lines.append(f"· 项目文档[{d.get('title', '')}]: {d.get('text', '')[:220]}")
    return '\n'.join(lines)
