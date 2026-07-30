# -*- coding: utf-8 -*-
"""金水谣 · 知识库桥接（纯标准库，零外部依赖）

让 DeepSeek 代码助手做到两件事：
  1) 改代码【前】检索本地知识库 / 提示词库，把相关内容注入给 DeepSeek，
     使其一次改对、少来回 = 少花钱（防浪费）。
  2) 改代码【后】把有价值的经验自动沉淀回知识库（闭环成长，且不堆垃圾）。

所有函数都不依赖网络；检索不到就返回空，绝不报错中断主流程。
"""
import os
import re
import sys
import json
import hashlib
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 用户知识库目录：Jinshuiyao_Fixed/knowledge/用户知识库
KB_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "knowledge", "用户知识库"))
# 提示词库（模型根目录）
PROMPT_LIB = os.path.normpath(os.path.join(BASE_DIR, "..", "..", "金水谣助手提示词库.html"))
# 沉淀去重缓存（放在本助手目录，避免污染知识库）
_VALUE_CACHE = os.path.join(BASE_DIR, ".value_cache.json")

# 动态导入归档工具
sys.path.insert(0, KB_DIR)
try:
    from archive_knowledge import archive as _archive
except Exception:
    _archive = None

# 停用词：降低噪声，让关键词匹配更准（保留 代码/函数/类/注释/编码/优化 等有实义的词）
_STOP = set(
    "的 了 是 在 我 你 他 它 这 那 和 与 或 对 把 被 用 请 帮 给 一个 一种 怎么 如何 "
    "什么 哪些 最近 要求 整理 看看 帮我 我们 你们 他们 可以 不要 如果 但是 因为 所以 "
    "之后 之前 这个 那个 这些 那些 一些 进行 需要 希望 能够 通过 使用 增加 减少 添加 "
    "删除 说明 参考 情况 现在 已经 还是 或者 以及 完全 无关 不懂 领域 出现 先 里 "
    "自己 一样 没有 就是 这样 那样 一句 让 一个 该 其 将 并 也 都 吗 呢 啊 吧".split()
)

# 相关性阈值：低于此分视为不相关，不注入（避免噪声）
MIN_SCORE = 0.8


def _tokenize(text):
    """简单分词：英文/数字词 + 中文 2-gram，并剔除停用词。返回词集合。"""
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9_]+", text)
    toks = [t for t in toks if t not in _STOP]
    cn = re.findall(r"[一-鿿]{2,}", text)
    grams = []
    for w in cn:
        if len(w) == 2:
            if w not in _STOP:
                grams.append(w)
        else:
            for i in range(len(w) - 1):
                g = w[i:i + 2]
                if g not in _STOP:
                    grams.append(g)
    return set(toks + grams)


def _score(query_tokens, text):
    if not query_tokens:
        return 0
    inter = query_tokens & _tokenize(text)
    if not inter:
        return 0
    # 重叠越多分越高；除以查询长度开方，避免长查询吃亏
    sc = len(inter) / (len(query_tokens) ** 0.5)
    return sc if sc >= MIN_SCORE else 0


def kb_search(query, top_k=3, kb_dir=KB_DIR):
    """从用户知识库检索与 query 相关的卡片（标题 + 正文）。返回 [{title, body, file}]。"""
    if not os.path.isdir(kb_dir):
        return []
    qt = _tokenize(query)
    results = []
    for fn in sorted(os.listdir(kb_dir)):
        if not fn.endswith(".md") or fn in ("索引.md", "README.md"):
            continue
        fp = os.path.join(kb_dir, fn)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        title = ""
        m = re.search(r"^#\s*(.+)$", content, re.MULTILINE)
        if m:
            title = m.group(1).strip()
        mb = re.search(r"##\s*内容\s*\n(.*)", content, re.DOTALL)
        body = mb.group(1).strip() if mb else content
        sc = _score(qt, title + "\n" + body)
        if sc > 0:
            results.append({"title": title or fn, "body": body[:600], "file": fn, "score": sc})
    results.sort(key=lambda x: -x["score"])
    return results[:top_k]


def prompt_search(query, top_k=2, path=PROMPT_LIB):
    """从提示词库 HTML 解析提示词模板，按相关性返回 top_k。返回 [{name, tag, goal, template}]。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception:
        return []
    pat = re.compile(
        r'<div class="p">.*?class="name">([^<]+)</span>'
        r'.*?class="tag">([^<]+)</span>'
        r'.*?class="goal">([^<]+)</div>'
        r'.*?<span>([\s\S]*?)</span>',
        re.DOTALL,
    )
    items = []
    for name, tag, goal, tmpl in pat.findall(html):
        sc = _score(_tokenize(query), name + " " + tag + " " + goal + " " + tmpl)
        if sc > 0:
            items.append({
                "name": name.strip(), "tag": tag.strip(),
                "goal": goal.strip(), "template": tmpl.strip(), "score": sc,
            })
    items.sort(key=lambda x: -x["score"])
    return items[:top_k]


def build_context(query, top_k_kb=3, top_k_prompt=2):
    """拼接检索到的知识库经验 + 提示词模板，作为 DeepSeek 的参考上下文（字符串）。"""
    kb = kb_search(query, top_k=top_k_kb)
    pr = prompt_search(query, top_k=top_k_prompt)
    parts = []
    if kb:
        lines = ["【本地知识库相关经验（仅供参考，避免重复踩坑）】"]
        for c in kb:
            snippet = c["body"].replace("\n", " ")[:200]
            lines.append(f"- 《{c['title']}》：{snippet}")
        parts.append("\n".join(lines))
    if pr:
        lines = ["【相关提示词模板（仅参考写法风格，不必照搬）】"]
        for p in pr:
            lines.append(f"- 《{p['name']}》({p['tag']})：{p['template'][:200]}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _diff_snippet(a, b, max_lines=24):
    import difflib
    aa = a.splitlines()
    bb = b.splitlines()
    diff = list(difflib.unified_diff(aa, bb, lineterm="", n=1))
    if not diff:
        return "（无文本差异）"
    return "\n".join(diff[:max_lines])


def archive_value(instruction, code, result, model, kb_dir=KB_DIR):
    """把一次成功的代码修改沉淀为知识卡。无需沉淀时返回 None。

    防垃圾规则：
      - 结果与原代码完全相同 → 不沉淀（没价值）
      - 与近期已沉淀的(指令+结果)重复 → 不沉淀（去重）
    """
    if _archive is None:
        return None
    if result.strip() == code.strip():
        return None
    key = hashlib.md5((instruction + "\n" + result).encode("utf-8")).hexdigest()
    cache = {}
    try:
        if os.path.isfile(_VALUE_CACHE):
            cache = json.load(open(_VALUE_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    if key in cache:
        return None
    cache[key] = 1
    try:
        json.dump(cache, open(_VALUE_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    title = "代码修改：" + instruction[:30]
    body = (
        f"修改要求：{instruction}\n\n模型：{model}\n\n改动摘要（原→新，diff 片段）：\n{_diff_snippet(code, result)}"
    )
    try:
        return _archive(title=title, body=body,
                        tags=["代码修改", "DeepSeek", "知识闭环"],
                        source="DeepSeek代码助手", kb_dir=kb_dir)
    except Exception:
        return None


def archive_knowledge_qa(question, answer, tags=None, kb_dir=KB_DIR):
    """把一次有价值的问答沉淀为知识卡（与代码修改共用去重缓存，避免堆垃圾）。"""
    if _archive is None:
        return None
    key = hashlib.md5((question + "\n" + answer).encode("utf-8")).hexdigest()
    cache = {}
    try:
        if os.path.isfile(_VALUE_CACHE):
            cache = json.load(open(_VALUE_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    if key in cache:
        return None
    cache[key] = 1
    try:
        json.dump(cache, open(_VALUE_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    title = "问答：" + question[:30]
    body = f"问题：{question}\n\n回答要点：\n{(answer or '')[:1500]}"
    try:
        return _archive(title=title, body=body,
                        tags=tags or ["问答", "知识闭环", "智能助手"],
                        source="智能代码助手", kb_dir=kb_dir)
    except Exception:
        return None


def kb_card_count(kb_dir=KB_DIR):
    """返回知识库里已沉淀的卡片数量（不含索引/README）。用于让「闭环」对用户可见。"""
    if not os.path.isdir(kb_dir):
        return 0
    n = 0
    for fn in os.listdir(kb_dir):
        if fn.endswith(".md") and fn not in ("索引.md", "README.md"):
            n += 1
    return n


def _self_test():
    print("== kb_bridge 自测 ==")
    # 1) 检索：写入一张临时卡片再检索
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="kb_test_")
    try:
        from archive_knowledge import archive
        archive(title="Python 读取文件编码", body="用 open(path, encoding='utf-8') 读取，避免 GBK 乱码。",
                tags=["python", "编码"], source="self_test", kb_dir=tmp)
        res = kb_search("python 读取文件 编码 乱码", top_k=1, kb_dir=tmp)
        assert res and "编码" in res[0]["title"], res
        print(f"✓ 知识库检索：命中《{res[0]['title']}》")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 2) 提示词库解析（用真实文件）
    pr = prompt_search("分步 复杂任务", top_k=1)
    assert pr, "提示词库未解析出内容"
    print(f"✓ 提示词库检索：命中《{pr[0]['name']}》")
    # 3) 上下文拼接（用确定能命中的查询验证拼接逻辑）
    ctx = build_context("分步做复杂任务")
    assert "提示词" in ctx, ctx
    print(f"✓ 上下文拼接：长度 {len(ctx)}")
    # 3b) 无相关经验时应返回空字符串（不强行注入噪声）
    ctx_empty = build_context("zzzqqq 完全无关的词 12345")
    assert ctx_empty == "", repr(ctx_empty)
    print("✓ 无关查询：返回空（不注入噪声）")
    # 4) 沉淀去重
    class _Fake:
        def __init__(self): self.n = 0
        def __call__(self, **kw):
            self.n += 1
            return f"fake_card_{self.n}.md"
    global _archive
    old = _archive
    fake = _Fake()
    _archive = fake
    try:
        # 清理去重缓存
        try:
            if os.path.isfile(_VALUE_CACHE):
                os.remove(_VALUE_CACHE)
        except Exception:
            pass
        r1 = archive_value("加注释", "a=1", "a = 1  # 注释", "deepseek-chat")
        r2 = archive_value("加注释", "a=1", "a = 1  # 注释", "deepseek-chat")  # 重复
        r3 = archive_value("加注释", "a=1", "a=1", "deepseek-chat")            # 无变化
        assert r1 and fake.n == 1, (r1, fake.n)
        assert r2 is None and r3 is None, (r2, r3)
        print("✓ 价值沉淀：首次写入、重复/无变化均跳过（去重生效）")
    finally:
        _archive = old
        try:
            if os.path.isfile(_VALUE_CACHE):
                os.remove(_VALUE_CACHE)
        except Exception:
            pass
    print("kb_bridge 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
