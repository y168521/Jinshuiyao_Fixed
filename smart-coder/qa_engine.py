# -*- coding: utf-8 -*-
"""金水谣 · 智能问答编排（纯标准库，零外部依赖）
============================================
把前面几个模块串起来，形成需求 2/3/5 的完整闭环：
  上传/加载项目 → 扫描结构 → 用户提问 → 自动定位相关代码 + 检索知识库
  → （有密钥）DeepSeek 三段式大白话讲解； （无密钥）本地免费定位，不花钱。
并自动把有价值的问答沉淀回知识库（知识闭环 / 需求 5）。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
# DeepSeek 助手所在目录（用于复用其防浪费 + 知识闭环的 do_qa）
_DEEPSEEK_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "AI代码助手(DeepSeek备用)"))
if os.path.isdir(_DEEPSEEK_DIR):
    sys.path.insert(0, _DEEPSEEK_DIR)

from project_loader import scan_directory
from code_retriever import build_index, search, build_context_code
from recommender import recommend
from kb_bridge import kb_card_count

# 通过模块引用调用 DeepSeek（便于自测时打桩；无密钥也不报错）
try:
    import deepseek_coder as _ds
except Exception:
    _ds = None

def get_api_key():
    return _ds.get_api_key() if _ds else ""

def load_config():
    return _ds.load_config() if _ds else {}


def analyze_project(path):
    """扫描项目 + 生成推荐，供页面首屏展示（目录树 + 四维推荐）。"""
    scan = scan_directory(path)
    if scan["error"]:
        return scan
    try:
        scan["recommend"] = recommend(path, scan["files"])
    except Exception:
        scan["recommend"] = {"preset_questions": [], "style_issues": [],
                             "warnings": [], "perf": [], "summary": {}}
    return scan


def _local_answer(question, results):
    if not results:
        return (f"（本地免费模式）我在这个项目里没找到和「{question}」明显相关的代码文件。\n"
                "你可以：换更具体的关键词再问一次；或先看目录树里标「高」重要性的"
                "入口/核心文件，从那里理解项目。")
    fuzzy = any(r.get("fuzzy") for r in results)
    if fuzzy:
        lines = ["（本地免费模式）没找到精确匹配的代码，但你项目里这些较重要的文件可以先看："]
    else:
        lines = ["（本地免费模式）根据你说的关键词，最相关的代码在以下位置，可以先点开看看："]
    _imp = {"high": "高", "medium": "中", "low": "低"}
    for r in results:
        if r.get("snippets"):
            snips = "；".join(f"{s['line']}行：{s['text'].strip()[:60]}"
                              for s in r["snippets"][:2])
            lines.append(f"- {r['rel']}（相关度 {r['score']}）：{snips}")
        else:
            imp = _imp.get(r.get("importance", ""), r.get("importance", ""))
            lines.append(f"- {r['rel']}（{imp}重要性，建议先看）")
    lines.append("")
    lines.append("想让我用大白话讲清楚「问题出在哪 / 为什么 / 怎么改」，"
                 "请在「DeepSeek 代码助手」里配置密钥后重试——本次没有花钱。")
    return "\n".join(lines)


def ask(question, path, selected=None, enable_kb=None):
    """问答主流程。返回 {ok, answer/local, sources, kb_used, archived, kb_count, note}。"""
    scan = scan_directory(path)
    if scan["error"]:
        return {"ok": False, "error": scan["error"]}
    files = scan["files"]
    if selected:
        files = [f for f in files if f["rel"] in selected]

    # 自动定位相关代码
    idx = build_index(path, files)
    results = search(idx, question, top_k=5, top_k_lines=4)
    # 兜底：精确匹配不到时，指向重要性高/中的入口、核心、配置、文档文件
    if not results:
        fb = [f for f in files if f["category"] in ("entry", "core", "config", "doc")
              and f["importance"] in ("high", "medium")]
        fb.sort(key=lambda x: (0 if x["importance"] == "high" else 1, x["category"]))
        results = [{"rel": f["rel"], "name": f["name"], "category": f["category"],
                    "importance": f["importance"], "score": 0, "snippets": [],
                    "fuzzy": True} for f in fb[:5]]
    ctx_code = build_context_code(results)

    api_key = get_api_key()
    if not api_key or _ds is None or not hasattr(_ds, "do_qa"):
        # 本地优先：免费定位，不调 DeepSeek（满足防浪费）
        return _free_local_answer(question, results)

    # 有密钥：但「免费类问题」仍走本地免费，不花 DeepSeek（坐实防烧钱）
    try:
        _cost, _la, _p = _ds.classify_cost(question)
    except Exception:
        _cost = "paid"
    if _cost == "free":
        return _free_local_answer(question, results)

    # 付费路径：调用 DeepSeek 三段式
    if enable_kb is None:
        enable_kb = load_config().get("enable_kb", True)
    try:
        out = _ds.do_qa(question, ctx_code, api_key, enable_kb=enable_kb)
    except Exception as e:
        return {"ok": False, "error": "DeepSeek 调用失败：" + str(e), "sources": results}
    if not out.get("ok"):
        out["sources"] = results
        return out
    out["sources"] = results
    if "kb_count" not in out:
        out["kb_count"] = kb_card_count()
    return out


def _free_local_answer(question, results):
    """免费路径的统一作答（不调 DeepSeek），并附上累计知识库条数。"""
    ans = _local_answer(question, results)
    return {
        "ok": True, "local": True,
        "answer": ans,
        "sources": results,
        "note": "（免费路径）已用本地定位作答，未消耗 DeepSeek 额度。",
        "kb_used": False,
        "archived": False,
        "kb_count": kb_card_count(),
    }


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test():
    import tempfile
    import shutil
    print("== qa_engine 自测 ==")
    tmp = tempfile.mkdtemp(prefix="qa_test_")
    try:
        open(os.path.join(tmp, "auth.py"), "w", encoding="utf-8").write(
            "# 登录函数：校验密码是否为空\n"
            "def login(user, pwd):\n"
            "    # 如果密码为空，直接返回 False\n"
            "    if not pwd:\n        return False\n    return True\n")
        # 1) 无密钥：本地免费定位
        r = ask("登录 密码 校验", tmp)
        assert r["ok"] and r.get("local"), r
        assert any(s["rel"] == "auth.py" for s in r["sources"]), r
        print("✓ 无密钥：本地免费定位命中 auth.py，未花 DeepSeek")

        # 2) 有密钥：走 DeepSeek 三段式（用假 do_qa）
        import deepseek_coder as ds
        orig = ds.do_qa
        ds.do_qa = lambda q, ctx, key, model=None, enable_kb=None: {
            "ok": True,
            "answer": "【问题定位】在 auth.py\n【原因分析】密码为空\n【修改建议】加校验",
            "kb_used": False, "archived": True,
        }
        # 临时写入假密钥
        orig_cfg = ds._raw_config()
        ds.save_config({"api_key": "sk-test", "daily_api_budget": 5,
                        "per_call_max_chars": 100000, "enable_kb": True,
                        "default_model": "deepseek-chat"})
        try:
            r2 = ask("登录为什么总返回 False", tmp)
            assert r2["ok"] and not r2.get("local"), r2
            assert "问题定位" in r2["answer"], r2
            assert r2["sources"], r2
            print("✓ 有密钥：走 DeepSeek 三段式，返回定位/原因/建议")
        finally:
            ds.do_qa = orig
            ds.save_config(orig_cfg)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("qa_engine 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
