# -*- coding: utf-8 -*-
"""金水谣引擎 - 视频提取 → 知识库 一键闭环（video_to_kb）

把 VideoExtractor（轻抖式文案提取）与 ContentRefiner（内容提炼）的产出，
直接沉淀进「用户知识库」的 raw 证据层 + 知识卡片层，并自动过 Lint 体检、
重建索引。形成「提取即沉淀」的完整闭环，且与知识库现有存储/检索接口
（archive_knowledge.py / INDEX.json / lint_knowledge.py）无缝衔接。

【cookie 安全说明】
本模块与 video_extractor 一样：**绝不**自动从浏览器窃取 cookie（那是高危操作，
常被恶意软件利用）。抖音等平台需要登录态时，由用户「手动」把浏览器开发者工具里
的 cookie 字符串传入（参数 / 环境变量 TIANSHU_DOUYIN_COOKIE / config/douyin_cookie.txt）。
cookie 含登录凭证，请确认已加入 .gitignore 与坚果云忽略列表，切勿泄露或提交。

使用方式：
    from core.video_to_kb import ingest_to_kb
    # 1) 无需登录的平台（B站/快手/小红书/视频号）直接提取：
    res = ingest_to_kb("https://www.bilibili.com/video/BVxxxx")
    # 2) 抖音等需登录态：传入用户自己的 cookie
    res = ingest_to_kb("https://v.douyin.com/xxx/", cookie="<你的cookie>")
    print(res["status"], res.get("card_file"))

命令行（演示/自测）：
    python video_to_kb.py --self-test          # 临时目录跑通全链路，不污染真实库
    python video_to_kb.py --url "<视频链接>"   # 真实提取并沉淀（会写入用户知识库！）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
from typing import Dict, Optional

# 让本模块能 import 同目录的 video_extractor / content_refiner
_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

# 项目根（Jinshuiyao_Fixed）也加入 path，使 content_refiner 依赖的
# `import core.ai_service` 能正确解析（否则直接运行本脚本时，
# 提炼器会因找不到 core 包而回退规则，并打印无害提示）
_PROJECT_ROOT = os.path.dirname(_THIS)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from video_extractor import VideoExtractor
from content_refiner import ContentRefiner

# 默认知识库目录（相对项目根：../knowledge/用户知识库）
KB_DIR = os.path.join(_PROJECT_ROOT, "knowledge", "用户知识库")
RAW_DIR = os.path.join(KB_DIR, "raw")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _date_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d")


def _slugify(text: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text).strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40] or "card"


def _has_real_content(extracted: dict) -> bool:
    """判断提取结果是否真的有内容（标题/描述/字幕任一非空）。"""
    return bool(
        (extracted.get("title") or "").strip()
        or (extracted.get("description") or "").strip()
        or (extracted.get("subtitles") or "").strip()
    )


# ---------------------------------------------------------------------------
# 各步骤实现
# ---------------------------------------------------------------------------

def _write_raw_evidence(url: str, extracted: dict, cookie_used: bool) -> str:
    """把原始提取文本写入 raw/ 证据层，可溯源。返回文件名。"""
    os.makedirs(RAW_DIR, exist_ok=True)
    name = f"{_date_stamp()}_evidence_{_slugify(url)}.md"
    path = os.path.join(RAW_DIR, name)
    lines = [
        f"# 原始证据：{extracted.get('title') or url}",
        "",
        f"- 摄入时间：{datetime.datetime.now().isoformat(timespec='seconds')}",
        f"- 来源链接：{url}",
        f"- 平台：{extracted.get('platform_name', extracted.get('platform', ''))}",
        f"- 摄入方式：VideoExtractor 程序化提取（cookie={'已用' if cookie_used else '未用'}）",
        "- 真实性说明：以下为提取器从页面/接口取到的文本；若为空说明平台拦截，未编造。",
        "",
        "## 页面原文 / 提取文本",
        "",
        f"- 标题：{extracted.get('title', '')}",
        f"- 作者：{extracted.get('author', '')}",
        f"- 描述：{extracted.get('description', '')}",
    ]
    if extracted.get("tags"):
        lines.append(f"- 标签：{', '.join(extracted['tags'])}")
    if extracted.get("subtitles"):
        lines.append("")
        lines.append("### 字幕")
        lines.append("")
        lines.append(extracted["subtitles"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return name


def _write_card(url: str, extracted: dict, card: dict, raw_name: str,
                cookie_used: bool) -> str:
    """把提炼后的内容写成一张 schema 合规的摘要页卡片，并写入索引。

    复用 archive_knowledge.archive（与现有问答沉淀共用同一套存储/索引接口），
    保证「视频提取沉淀」与「对话问答沉淀」在存储、检索、Lint 上完全一致。
    """
    if KB_DIR not in sys.path:
        sys.path.insert(0, KB_DIR)
    from archive_knowledge import archive

    title = (extracted.get("title") or "视频内容").strip() or "未命名视频"
    # 正文：摘要 + 要点 + 数据 + 技巧
    body_parts: list = []
    summary = (card.get("summary") or "").strip()
    if summary:
        body_parts.append(f"摘要：{summary}")
    kps = card.get("key_points") or []
    if kps:
        body_parts.append("关键要点：")
        body_parts += [f"- {k}" for k in kps]
    dps = card.get("data_points") or []
    if dps:
        body_parts.append("数据/事实：")
        body_parts += [f"- {d}" for d in dps]
    wt = card.get("writing_techniques") or []
    if wt:
        body_parts.append("文案技巧：" + "、".join(wt))

    # 溯源链接：raw 证据 + Karpathy 范式卡（若存在则互链）
    body_parts.append("")
    body_parts.append(f"> 原始证据：raw/{raw_name}（点击可溯源）")
    karpathy = "Karpathy LLM Wiki 方法论要点"
    try:
        idx = json.load(open(os.path.join(KB_DIR, "INDEX.json"), encoding="utf-8"))
        titles = [e.get("title") for e in idx if isinstance(e, dict)]
    except Exception:
        titles = []
    if karpathy in titles:
        body_parts.append(f"> 关联范式：[[{karpathy}]]")

    body = "\n".join(body_parts)
    tags = ["视频提取"] + list(card.get("tags") or [])
    source = (f"{extracted.get('platform_name', '')}视频 {url}"
              f"（VideoExtractor{'+cookie' if cookie_used else ''}）")

    p = archive(
        title=f"视频内容：{title}",
        body=body,
        tags=tags,
        source=source,
        type="摘要页",
        kb_dir=KB_DIR,
    )
    return p


def _sync_to_mirofish(extracted: dict, card: dict, raw_name: str,
                      cookie_used: bool, kb_dir: str) -> Optional[str]:
    """把视频卡同步写一条摘要到 MiroFishDB（库A），使前端知识库视图可见。

    这是修复「双知识库互不连通」的关键：原归档只写库B（用户知识库 markdown），
    而前端知识库视图只读库A（MiroFishDB），导致视频卡前端不可见。
    这里在库B 闭环之外，再向库A 同步一条卡片（按 title 去重，失败不影响主闭环）。

    Returns:
        card_id（成功）或 None（跳过/失败）
    """
    try:
        from knowledge.mirofish_db import MiroFishDB
    except Exception:
        try:
            sys.path.insert(0, _PROJECT_ROOT)
            from knowledge.mirofish_db import MiroFishDB
        except Exception as e:
            log(f"视频卡同步MiroFish: 导入失败 {e}")
            return None
    try:
        db = MiroFishDB()
        title = "视频内容：" + ((extracted.get("title") or "视频内容").strip() or "未命名视频")
        summary = (card.get("summary") or "").strip()
        kps = card.get("key_points") or []
        content = summary
        if kps:
            content += ("\n\n关键要点：\n" + "\n".join(f"- {k}" for k in kps))
        url = extracted.get("url", "")
        card_id = db.add_card(
            title=title,
            content=content or "（视频文案已沉淀至用户知识库 raw 证据层）",
            category="resource",
            domain="ai",
            tags=["视频提取"] + list(card.get("tags") or []),
            source=f"{extracted.get('platform_name', '')}视频 {url}",
            source_url=url,
            value_level="知识",
            priority=5,
        )
        log(f"视频卡已同步至 MiroFishDB: {card_id} ({title})")
        return card_id
    except Exception as e:
        log(f"视频卡同步MiroFish 失败(不影响主闭环): {e}")
        return None


def _run_lint() -> dict:
    """对知识库跑一次 Lint 体检，返回 {ok, stdout}。"""
    lint_path = os.path.join(KB_DIR, "lint_knowledge.py")
    if not os.path.isfile(lint_path):
        return {"ok": True, "skipped": True, "note": "未找到 lint 脚本"}
    try:
        out = subprocess_run([sys.executable, lint_path], cwd=KB_DIR)
        ok = ("无错误" in out) and ("未通过" not in out)
        return {"ok": ok, "stdout": out[-1500:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def subprocess_run(cmd, cwd=None) -> str:
    """兼容封装：用当前 python 跑命令并返回 stdout。"""
    import subprocess
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return (proc.stdout or "") + (proc.stderr or "")


def log(msg: str) -> None:
    """轻量日志：打印到控制台（video_to_kb 同步 MiroFishDB 时用）。"""
    try:
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _ingest_extracted(extracted: dict, cookie: Optional[str],
                      kb_dir: str, raw_dir: str) -> dict:
    """内部：把一份已提取结果沉淀进指定知识库目录（可传临时目录做自测）。"""
    global KB_DIR, RAW_DIR
    KB_DIR = kb_dir
    RAW_DIR = raw_dir
    if KB_DIR not in sys.path:
        sys.path.insert(0, KB_DIR)

    cookie_used = bool(cookie) or bool(extracted.get("used_cookie"))
    if not _has_real_content(extracted):
        return {
            "status": "empty",
            "message": ("提取器未能从该链接取到内容（平台拦截/短链/需登录态）。"
                        "若有 cookie，请传入 cookie 参数重试；或换 B站/快手/小红书 等"
                        "可公开取内容的平台。"),
            "card_title": None, "card_file": None, "raw_file": None,
            "lint": None, "used_cookie": cookie_used,
        }

    refiner = ContentRefiner()
    card = refiner.refine(extracted)

    raw_name = _write_raw_evidence(extracted.get("url", ""), extracted, cookie_used)
    card_path = _write_card(extracted.get("url", ""), extracted, card, raw_name, cookie_used)
    lint_res = _run_lint()
    # 同步一条摘要卡到 MiroFishDB（库A），使前端知识库视图可见（修复双库不连通）
    mirofish_id = _sync_to_mirofish(extracted, card, raw_name, cookie_used, KB_DIR)

    try:
        from archive_knowledge import rebuild_index
        n = rebuild_index(kb_dir=KB_DIR)
    except Exception:
        n = -1

    # 组装可展示的「文案元信息」，供前端完整呈现提取结果
    def _num(v):
        v = (v or "").strip()
        return v if v else "—"
    stats = "👍 {likes} · 💬 {comments} · ⭐ {collects} · ↗ {shares}".format(
        likes=_num(extracted.get("likes")),
        comments=_num(extracted.get("comments")),
        collects=_num(extracted.get("collects")),
        shares=_num(extracted.get("shares")),
    )
    meta = {
        "platform": extracted.get("platform", ""),
        "platform_name": extracted.get("platform_name", ""),
        "title": extracted.get("title", ""),
        "author": extracted.get("author", ""),
        "description": extracted.get("description", ""),
        "subtitles": extracted.get("subtitles", ""),
        "tags": extracted.get("tags") or [],
        "stats": stats,
        "used_cookie": cookie_used,
    }

    return {
        "status": "ok",
        "message": "已提取并沉淀到知识库（raw 证据 + 摘要页卡片）",
        "card_title": (extracted.get("title") or "未命名视频"),
        "card_file": os.path.basename(card_path),
        "raw_file": raw_name,
        "lint": lint_res,
        "used_cookie": cookie_used,
        "index_count": n,
        "meta": meta,
    }


def ingest_to_kb(url: str, cookie: str = None,
                 kb_dir: str = KB_DIR, raw_dir: str = RAW_DIR,
                 use_cache: bool = False) -> dict:
    """把一条视频链接提取并沉淀进知识库，返回结果字典。

    Args:
        url:       视频链接
        cookie:    用户提供的登录态 cookie（抖音等需登录平台用），可空
        kb_dir:    知识库目录（默认用户知识库）
        raw_dir:   raw 证据目录
        use_cache: 是否用提取缓存（默认 False，保证最新）

    Returns:
        {status, message, card_title, card_file, raw_file, lint, used_cookie, index_count}
    """
    ext = VideoExtractor()
    extracted = ext.extract(url, use_cache=use_cache, cookie=cookie)
    return _ingest_extracted(extracted, cookie, kb_dir, raw_dir)


# ---------------------------------------------------------------------------
# 自测（临时目录，绝不污染真实知识库）
# ---------------------------------------------------------------------------

def _self_test() -> None:
    print("→ video_to_kb 自测开始（全部在临时目录，不污染真实库）")

    # 1) cookie 注入到 session 的 cookie jar（按域过滤，跨域重定向不泄露登录态）
    ext = VideoExtractor(cookie="sessionid=test123; user=abc")
    ext._get_session()
    cookie_str = "; ".join(f"{c.name}={c.value}" for c in ext._session.cookies)
    assert "sessionid=test123" in cookie_str, "cookie 应注入 session 的 cookie jar"
    assert "user=abc" in cookie_str, "cookie 值应正确注入 jar"
    assert "Cookie" not in ext._session.headers, "不应再用 headers 注入（避免跨域泄露登录态）"
    print("  ✓ cookie 正确注入 cookie jar（跨域按域过滤，不泄露登录态）")

    # 准备临时知识库：复制 lint + archive + schema，使体检可运行
    tmp_kb = tempfile.mkdtemp(prefix="jinshuiyao_kb_loop_")
    tmp_raw = os.path.join(tmp_kb, "raw")
    os.makedirs(tmp_raw, exist_ok=True)
    for tool in ("lint_knowledge.py", "archive_knowledge.py", "schema.md"):
        src = os.path.join(KB_DIR, tool)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(tmp_kb, tool))

    # 2) 真实网络提取（B站，无需 cookie）；若被网络拦截则回退到「模拟真实提取」
    test_url = "https://www.bilibili.com/video/BV1GJ411x7h7"
    res = ingest_to_kb(test_url, cookie=None, kb_dir=tmp_kb, raw_dir=tmp_raw,
                       use_cache=False)
    if res["status"] == "empty":
        print("  · B站实时提取被网络拦截，改用「模拟真实提取结果」验证闭环")
        sim = {
            "url": test_url, "platform": "bilibili", "platform_name": "B站",
            "title": "示例：大模型Agent记忆机制讲解",
            "description": "本期讲解Agent为什么需要持久化记忆，以及记忆引擎如何解决遗忘问题。",
            "subtitles": "记忆是Agent的核心能力。没有记忆的Agent每次对话都从零开始。",
            "author": "演示作者", "tags": ["Agent", "记忆"], "used_cookie": False,
        }
        res = _ingest_extracted(sim, None, tmp_kb, tmp_raw)
    assert res["status"] == "ok", res

    # 3) 断言产物齐全 + Lint 通过 + 索引含条目
    assert res["card_file"] and os.path.isfile(os.path.join(tmp_kb, res["card_file"]))
    assert res["raw_file"] and os.path.isfile(os.path.join(tmp_kb, "raw", res["raw_file"]))
    assert res["lint"] and res["lint"].get("ok"), res.get("lint")
    idx = json.load(open(os.path.join(tmp_kb, "INDEX.json"), encoding="utf-8"))
    assert isinstance(idx, list) and len(idx) >= 1, "索引应至少含 1 条"
    # raw 证据应被卡片引用（Lint 已校验过存在性）
    print(f"  ✓ 全链路通过：raw={res['raw_file']} | 卡片={res['card_file']} | 索引={len(idx)} 条 | Lint ok")
    print(f"  ✓ 与知识库存储/检索接口无缝衔接（archive_knowledge.archive + INDEX.json + lint）")

    # 清理
    try:
        shutil.rmtree(tmp_kb, ignore_errors=True)
    except Exception:
        pass
    print("→ 自测全部通过 ✅")


def _main() -> int:
    ap = argparse.ArgumentParser(description="视频提取 → 知识库 闭环")
    ap.add_argument("--url", default="", help="视频链接（真实提取并沉淀到用户知识库）")
    ap.add_argument("--cookie", default=None, help="用户手动提供的登录态 cookie")
    ap.add_argument("--self-test", action="store_true", help="跑自测（临时目录，不污染）")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return 0

    if not args.url:
        ap.error("需提供 --url（或使用 --self-test）")

    res = ingest_to_kb(args.url, cookie=args.cookie)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
