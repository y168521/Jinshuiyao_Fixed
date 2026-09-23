# -*- coding: utf-8 -*-
"""金水谣本地助手 - 联网搜索工具（进化·上网求证 / JS-20260727-31）

默认走免密钥的 DuckDuckGo HTML 搜索（0 成本），可选接入 Tavily（需密钥，返回干净 JSON）。
只抓取「公开搜索引擎」的固定域名结果（标题/链接/摘要文本），绝不主动抓取结果链接指向的网页，
从设计上规避 SSRF：不把用户任意 URL 当抓取目标，只打白名单内的公开搜索引擎域名。

返回结构：{"ok": bool, "results": [{"title","url","snippet"}], "error": str}
"""
import os
import re
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# 固定公开搜索引擎域名（白名单：只打这两个，杜绝 SSRF 打内网/云元数据）
_DDG_HTML = "https://html.duckduckgo.com/html/"
_TAVILY_API = "https://api.tavily.com/search"


def _read_secret(name: str) -> str:
    """从密钥目录读取密钥（与项目其他模块一致：~/.jinshuiyao-secrets/），也支持环境变量。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets", name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return os.environ.get(name.replace(".txt", "").upper(), "") or ""


def _clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s)
    s = urllib.parse.unquote(s)
    return s.strip()


def _search_duckduckgo(query: str, max_results: int = 5) -> dict:
    """免密钥 DuckDuckGo HTML 搜索（POST，带 UA 防拦）。"""
    try:
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            _DDG_HTML, data=data, method="POST",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        return _parse_ddg(html, max_results)
    except urllib.error.URLError as e:
        return {"ok": False, "results": [], "error": f"联网失败（DuckDuckGo 不可达）：{e}"}
    except Exception as e:
        return {"ok": False, "results": [], "error": f"搜索解析异常：{e}"}


def _parse_ddg(html: str, max_results: int) -> dict:
    """从 DuckDuckGo HTML 抽取结果（标题/链接/摘要）。链接需解码 uddg 参数。"""
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
    hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)

    titles = [_clean(t) for t in titles]
    snippets = [_clean(s) for s in snippets]
    links = []
    for h in hrefs:
        m = re.search(r'uddg=([^&"]+)', h)
        links.append(urllib.parse.unquote(m.group(1)) if m else h)

    results = []
    for i in range(min(len(titles), max_results)):
        title = titles[i]
        if not title:
            continue
        results.append({
            "title": title,
            "url": links[i] if i < len(links) else "",
            "snippet": snippets[i] if i < len(snippets) else "",
        })
    if not results:
        return {"ok": False, "results": [], "error": "搜索无结果（可能触发反爬或查询为空）"}
    return {"ok": True, "results": results, "error": ""}


def _search_tavily(query: str, max_results: int = 5) -> dict:
    """Tavily 搜索 API（需密钥，返回干净 JSON）。"""
    key = _read_secret("tavily_key.txt")
    if not key:
        return {"ok": False, "results": [], "error": "未配置 Tavily 密钥"}
    try:
        payload = json.dumps({
            "api_key": key, "query": query, "max_results": max_results,
            "search_depth": "basic"
        }).encode("utf-8")
        req = urllib.request.Request(
            _TAVILY_API, data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": _clean(r.get("content", "")),
        } for r in data.get("results", [])]
        return {"ok": True, "results": results, "error": ""}
    except Exception as e:
        return {"ok": False, "results": [], "error": f"Tavily 搜索失败：{e}"}


def web_search(query: str, max_results: int = 5, provider: str = "auto") -> dict:
    """统一入口。provider=auto 优先 Tavily(有密钥) 否则 DuckDuckGo；Tavily 失败降级 DuckDuckGo。"""
    if provider in ("tavily", "auto"):
        key = _read_secret("tavily_key.txt")
        if key:
            r = _search_tavily(query, max_results)
            if r["ok"]:
                return r
    return _search_duckduckgo(query, max_results)


def format_results(query: str, res: dict) -> str:
    """把搜索结果格式化为可读文本，供免费模型总结；失败给出友好提示。"""
    if not res.get("ok"):
        return ("⚠️ 联网搜索暂不可用：" + res.get("error", "未知错误") +
                "\n（可能是本机无外网或搜索引擎限流，稍后再试；也可直接问我，我用已有知识回答。）")
    lines = [f"🔍 联网搜索「{query}」得到 {len(res['results'])} 条结果："]
    for i, r in enumerate(res["results"], 1):
        lines.append(f"\n【{i}】{r['title']}")
        if r.get("url"):
            lines.append(f"链接：{r['url']}")
        if r.get("snippet"):
            lines.append(f"摘要：{r['snippet']}")
    return "\n".join(lines)
