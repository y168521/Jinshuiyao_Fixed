# -*- coding: utf-8 -*-
"""金水谣 · 代码检索器（纯标准库，零外部依赖）
============================================
对应需求 2「上下文感知问答」里的"自动定位相关代码文件"。
给定已加载项目的文件清单，按自然语言问题找出最相关的文件，
并抽取命中行作为片段（snippet），供 DeepSeek 回答时作为上下文。

做法：中文 2-gram + 英文/数字词 分词（与知识库桥接一致），
对查询词与每个文件/每行做交集打分，挑分数最高的文件与行。
"""
import os
import re
import json

# 可检索的文本类型
_INDEX_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp", ".h",
    ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".scala", ".sh", ".bat",
    ".ps1", ".sql", ".html", ".htm", ".css", ".scss", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".md", ".txt", ".rst",
    ".xml", ".csv", ".log",
}

# 停用词（降噪）
_STOP = set(
    "的 了 是 在 我 你 他 它 这 那 和 与 或 对 把 被 用 请 帮 给 一个 一种 怎么 如何 "
    "什么 哪些 最近 要求 整理 看看 帮我 我们 你们 他们 可以 不要 如果 但是 因为 所以 "
    "之后 之前 这个 那个 这些 那些 一些 进行 需要 希望 能够 通过 使用 增加 减少 添加 "
    "删除 说明 参考 情况 现在 已经 还是 或者 以及 完全 无关 不懂 领域 出现 先 里 "
    "自己 一样 没有 就是 这样 那样 一句 让 一个 该 其 将 并 也 都 吗 呢 啊 吧".split()
)


def _tokenize(text):
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


def build_index(root, files, max_bytes=80000, max_lines_per_file=1500):
    """读入可检索文件内容，建立内存索引（文件名/行/分词）。

    参数 files: project_loader.scan_directory 返回的 files 列表。
    返回 index 字典（可重复用于多次检索，避免重复读盘）。
    """
    index = {"root": root, "files": []}
    for f in files:
        if f["ext"] not in _INDEX_EXTS:
            continue
        if f["category"] in ("asset", "data") and f["ext"] not in (
                ".md", ".txt", ".html", ".json", ".yaml", ".yml", ".csv", ".log", ".xml"):
            continue
        ab = os.path.join(root, f["rel"])
        try:
            with open(ab, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read(max_bytes)
        except Exception:
            continue
        lines = text.splitlines()[:max_lines_per_file]
        line_toks = [_tokenize(ln) for ln in lines]
        file_tok = set()
        for lt in line_toks:
            file_tok |= lt
        index["files"].append({
            "rel": f["rel"], "name": f["name"], "category": f["category"],
            "importance": f["importance"], "lines": lines,
            "line_toks": line_toks, "file_tok": file_tok,
        })
    return index


def snippets_for(fi, query, top_k_lines=4):
    """返回某文件中最匹配查询的若干行（带行号）。"""
    qt = _tokenize(query)
    if not qt:
        return []
    ranked = []
    for i, lt in enumerate(fi["line_toks"]):
        ov = len(qt & lt)
        if ov:
            ranked.append((ov, i))
    ranked.sort(key=lambda x: -x[0])
    picks = sorted(i for _, i in ranked[:top_k_lines])
    return [{"line": i + 1, "text": fi["lines"][i]} for i in picks]


def search(index, query, top_k=5, top_k_lines=4):
    """按查询检索最相关文件，返回 [{rel, name, category, importance, score, snippets}]。"""
    qt = _tokenize(query)
    if not qt:
        return []
    scored = []
    for fi in index["files"]:
        overlap = qt & fi["file_tok"]
        if not overlap:
            continue
        scored.append((len(overlap), fi))
    scored.sort(key=lambda x: -x[0])
    results = []
    for score, fi in scored[:top_k]:
        snips = snippets_for(fi, query, top_k_lines=top_k_lines)
        results.append({
            "rel": fi["rel"], "name": fi["name"], "category": fi["category"],
            "importance": fi["importance"], "score": score, "snippets": snips,
        })
    return results


def build_context_code(results, max_chars=6000):
    """把检索结果拼成给 DeepSeek 的代码上下文（限定长度）。"""
    parts = []
    total = 0
    for r in results:
        head = f"【文件 {r['rel']}】（相关度 {r['score']}）"
        block = head + "\n"
        for s in r["snippets"]:
            line = f"{s['line']}: {s['text']}"
            if total + len(line) > max_chars:
                block += "...(上下文已截断)\n"
                break
            block += line + "\n"
            total += len(line)
        parts.append(block)
        if total >= max_chars:
            break
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test():
    import tempfile
    import shutil
    print("== code_retriever 自测 ==")
    tmp = tempfile.mkdtemp(prefix="cr_test_")
    try:
        open(os.path.join(tmp, "auth.py"), "w", encoding="utf-8").write(
            "def login(user, pwd):\n    # 校验密码\n    if pwd == '':\n        return False\n    return True\n")
        open(os.path.join(tmp, "util.py"), "w", encoding="utf-8").write(
            "def add(a, b):\n    return a + b\n")
        files = [
            {"rel": "auth.py", "name": "auth.py", "ext": ".py", "category": "core", "importance": "high"},
            {"rel": "util.py", "name": "util.py", "ext": ".py", "category": "module", "importance": "medium"},
        ]
        idx = build_index(tmp, files)
        assert len(idx["files"]) == 2, len(idx["files"])
        res = search(idx, "登录 密码 校验", top_k=3)
        assert res and res[0]["rel"] == "auth.py", res
        assert res[0]["snippets"], "未抽取到片段"
        print("✓ 检索：查询『登录 密码』正确命中 auth.py 并抽取片段")
        ctx = build_context_code(res)
        assert "auth.py" in ctx and "校验" in ctx, ctx
        print("✓ 上下文拼接：含文件名与片段")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("code_retriever 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
