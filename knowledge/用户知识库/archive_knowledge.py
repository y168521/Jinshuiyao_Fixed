# -*- coding: utf-8 -*-
"""金水谣助手 · 用户知识库归档小工具

让「自动收集有价值信息 → 整理 → 归档」的闭环真正可落地。
助手在对话中遇到值得长期记住的知识，可调用本工具把它写成一张带时间戳的
知识卡片，追加到 用户知识库/ 目录，并自动维护一份索引。

设计原则：纯标准库、零外部依赖、可被任意 Python 版本直接运行；每张卡片
都是一个独立 .md 文件，普通人用记事本也能看懂。

用法（命令行）：
    python archive_knowledge.py --title "共形预测" --tags "方法,不确定性" \
        --body "一句话解释：给预测加一个可信区间的方法。" --source "本次对话" \
        --type "概念页"

说明：--type 可选，取值 概念页 / 实体页 / 摘要页（参见 schema.md）。

用法（作为模块）：
    import sys, os
    sys.path.insert(0, r"Jinshuiyao_Fixed/knowledge/用户知识库")
    from archive_knowledge import archive
    path = archive(title="...", body="...", tags=["..."], source="...")
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile
from typing import List, Optional, Sequence

__all__ = ["archive", "list_cards", "rebuild_index", "slugify"]

# 默认归档目录：本文件所在文件夹即「用户知识库」
KB_DIR = os.path.dirname(os.path.abspath(__file__))


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _date_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d")


def slugify(text: str) -> str:
    """把标题转成安全的文件名片段：保留中文/字母/数字，其余替换为 _。"""
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(text).strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:40] or "card"


def _safe_filename(title: str) -> str:
    return f"{_date_stamp()}_{slugify(title)}.md"


def _index_files(kb_dir: str):
    return (os.path.join(kb_dir, "INDEX.json"), os.path.join(kb_dir, "索引.md"))


def archive(title: str, body: str, tags: Optional[Sequence[str]] = None,
            source: str = "", author: str = "金水谣助手",
            type: str = "", kb_dir: str = KB_DIR) -> str:
    """把一条知识写成卡片文件并更新索引，返回卡片路径。

    Args:
        title: 知识标题（必填）。
        body:  正文（必填，可多行）。
        tags:  标签列表，便于检索。
        source: 来源说明，如「本次对话」「XXX网页」。
        author: 记录者。
        kb_dir: 归档目录（默认为本工具所在目录）。
    """
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        raise ValueError("title 与 body 均不能为空")

    tags = [t.strip() for t in (tags or []) if str(t).strip()]
    ts = _now()
    card_path = os.path.join(kb_dir, _safe_filename(title))

    md = [
        f"# {title}\n",
        f"- 记录时间：{ts}",
        f"- 记录者：{author}",
    ]
    if source:
        md.append(f"- 来源：{source}")
    if tags:
        md.append(f"- 标签：{', '.join(tags)}")
    if type:
        md.append(f"- 类型：{type}")
    md += ["", "## 内容", body, ""]

    with open(card_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    _append_index({
        "title": title, "tags": tags, "source": source, "type": type,
        "time": ts, "file": os.path.basename(card_path),
    }, kb_dir)
    return card_path


def _append_index(entry: dict, kb_dir: str) -> None:
    index_file, _ = _index_files(kb_dir)
    data = []
    if os.path.isfile(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    data.append(entry)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _write_index_md(data, kb_dir)


def _write_index_md(data: List[dict], kb_dir: str) -> None:
    _, index_md = _index_files(kb_dir)
    lines = ["# 用户知识库 · 索引", ""]
    if not data:
        lines.append("（暂无知识卡片）")
    for i, e in enumerate(data, 1):
        tags = ", ".join(e.get("tags", [])) or "-"
        lines.append(
            f"{i}. **{e.get('title', '?')}**  \n"
            f"   - 时间：{e.get('time', '?')}  \n"
            f"   - 标签：{tags}  \n"
            f"   - 来源：{e.get('source', '-')}  \n"
            f"   - 文件：`{e.get('file', '?')}`"
        )
    lines.append("")
    with open(index_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def list_cards(kb_dir: str = KB_DIR) -> List[dict]:
    """返回索引中的全部卡片条目。"""
    index_file, _ = _index_files(kb_dir)
    if not os.path.isfile(index_file):
        return []
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def rebuild_index(kb_dir: str = KB_DIR) -> int:
    """扫描目录下的 .md 卡片，重建索引。返回卡片数。"""
    index_file, _ = _index_files(kb_dir)
    cards = []
    for fn in sorted(os.listdir(kb_dir)):
        if not fn.endswith(".md") or fn in ("索引.md", "README.md", "schema.md", "SCHEMA.md"):
            continue
        fp = os.path.join(kb_dir, fn)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                head = f.read(2000)
        except Exception:
            continue
        title = ""
        tags, source, time = [], "", ""
        for line in head.splitlines():
            if line.startswith("# ") and not title:
                title = line[2:].strip()
            elif line.startswith("- 标签："):
                tags = [t.strip() for t in line[len("- 标签："):].split(",") if t.strip()]
            elif line.startswith("- 来源："):
                source = line[len("- 来源："):].strip()
            elif line.startswith("- 记录时间："):
                time = line[len("- 记录时间："):].strip()
        cards.append({"title": title or fn, "tags": tags, "source": source,
                      "time": time, "file": fn})
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    _write_index_md(cards, kb_dir)
    return len(cards)


def _self_test() -> None:
    """在临时目录中验证 写入→检索→重建 闭环，不污染真实知识库。"""
    tmp = tempfile.mkdtemp(prefix="jinshuiyao_kb_test_")
    print("→ 临时目录:", tmp)
    print("→ 写入测试卡片…")
    p = archive(
        title="自测知识卡片",
        body="这是一条用于自测的知识卡片，验证归档工具能正常写入并检索。",
        tags=["自测", "工具"],
        source="archive_knowledge._self_test",
        kb_dir=tmp,
    )
    assert os.path.isfile(p), "卡片未写入"
    print("  写入成功:", os.path.basename(p))

    print("→ 检索索引…")
    cards = list_cards(kb_dir=tmp)
    assert any(c["title"] == "自测知识卡片" for c in cards), "索引里找不到测试卡片"
    print("  索引条目数:", len(cards))

    print("→ 重建索引…")
    n = rebuild_index(kb_dir=tmp)
    assert n >= 1, "重建后卡片数异常"
    print("  重建后卡片数:", n)

    # 清理：尽力删除临时目录；沙箱若阻止删除也不算失败（临时目录无害）
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    print("✓ 自测全部通过")


def _main() -> int:
    ap = argparse.ArgumentParser(description="金水谣助手用户知识库归档工具")
    ap.add_argument("--title", default="", help="知识标题")
    ap.add_argument("--body", default="", help="知识正文")
    ap.add_argument("--tags", default="", help="标签，逗号分隔")
    ap.add_argument("--source", default="", help="来源说明")
    ap.add_argument("--type", default="", help="卡片类型：概念页/实体页/摘要页")
    ap.add_argument("--list", action="store_true", help="列出全部卡片")
    ap.add_argument("--rebuild", action="store_true", help="重建索引")
    ap.add_argument("--self-test", action="store_true", help="运行自我测试")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if args.rebuild:
        print(f"重建完成，共 {rebuild_index()} 张卡片")
        return 0
    if args.list:
        for c in list_cards():
            print(f"- {c.get('time','?')} | {c.get('title','?')} | {c.get('file','?')}")
        return 0

    if not args.title or not args.body:
        ap.error("归档需要 --title 和 --body（或使用 --self-test / --list / --rebuild）")

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    p = archive(title=args.title, body=args.body, tags=tags, source=args.source,
                type=args.type)
    print("已归档:", p)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
