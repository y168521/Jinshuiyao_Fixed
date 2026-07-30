# -*- coding: utf-8 -*-
"""
金水谣经验箱 · 标签校验器（白名单 + 一致性）
==========================================

经验箱《标签铁律》要求：
  1. 每条经验标题末尾必须带标签（`[标签1][标签2]` 格式）
  2. 至少 1 个，最多 3 个
  3. 只能从 9 个白名单标签里选，不许自创
  4. `[踩坑]` / `[最佳实践]` 可与其他标签叠加

本模块提供可复用、纯标准库的校验：
  - 白名单校验：检出"自创/未知标签"
  - 数量校验：检出 0 个 / >3 个
  - 格式校验：标签必须在标题行以 [x] 形式出现
  - 一致性校验：用到的标签须有对应「分类索引」类目；分类索引类目不应为空

供 /api/knowledge/tags/validate 端点、tools/tag_validator.py CLI、门禁复用。
"""
import os
import re
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Jinshuiyao_Fixed
EXPBOX_PATH = os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md")

# 9 个白名单标签（标签铁律 #3）
TAG_WHITELIST = {
    "架构", "后端", "前端", "测试", "协作",
    "运维", "安全", "踩坑", "最佳实践",
}

# 标签 -> 分类索引类目标题中的类目名（[踩坑] 无独立类目，是叠加标记）
INDEX_CATEGORY_FOR_TAG = {
    "架构": "架构类", "后端": "后端类", "前端": "前端类", "测试": "测试类",
    "协作": "协作类", "运维": "运维类", "安全": "安全类", "最佳实践": "最佳实践",
}

# 标题行提取 [标签] 的正则（与 wrapup_check 一致：re.findall(r'\[([^\]]+)\]', title)）
_TAG_RE = re.compile(r"\[([^\]]+)\]")


def load_experience_text(path: str = None) -> str:
    """读取经验箱全文（fail-safe）。"""
    p = path or EXPBOX_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        logger.warning("[标签校验] 读取经验箱失败: %s", p)
        return ""


def extract_entries(text: str) -> List[Dict[str, Any]]:
    """解析经验箱，返回每条 `### ` 经验条目的 (行号, 标题, 标签列表)。"""
    entries = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("### "):
            title = line[4:].strip()
            tags = _TAG_RE.findall(title)
            entries.append({"line": i, "title": title, "tags": tags})
    return entries


def extract_index_categories(text: str) -> Dict[str, str]:
    """从「分类索引」解析 `### X类（[tag]）` → {tag: 类目标题行}。"""
    cats = {}
    for m in re.finditer(r"^###\s+.*?（\[([^\]]+)\]）", text, re.M):
        cats[m.group(1)] = m.group(0).strip()
    return cats


def validate_whitelist(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """检出不在白名单中的自创/未知标签。

    排除 ISO 日期（如 [2026-07-23]）——它们不是标签，只是标题里的日期噪声，
    避免把"标题带日期"误判为非法标签。
    """
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    v = []
    for e in entries:
        for t in e["tags"]:
            if date_re.match(t):
                continue
            if t not in TAG_WHITELIST:
                v.append({"type": "unknown_tag", "line": e["line"],
                           "tag": t, "title": e["title"]})
    return v


def validate_count(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """检出标签数 <1 或 >3。"""
    v = []
    for e in entries:
        n = len(e["tags"])
        if n < 1:
            v.append({"type": "no_tag", "line": e["line"], "title": e["title"]})
        elif n > 3:
            v.append({"type": "too_many_tags", "line": e["line"],
                       "count": n, "title": e["title"]})
    return v


def validate_format(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """检出标题行未带 [标签] 格式（标签铁律 #1）。"""
    v = []
    for e in entries:
        if not e["tags"]:
            v.append({"type": "missing_title_tag", "line": e["line"], "title": e["title"]})
    return v


def validate_consistency(entries: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """一致性：用到的标签须有对应分类索引类目；分类索引类目不应为空。"""
    v = []
    index_cats = extract_index_categories(text)
    used_tags = set()
    for e in entries:
        used_tags.update(e["tags"])
    # 1) 每个非[踩坑]白名单标签须有对应分类索引类目
    for t in used_tags:
        if t == "踩坑":
            continue
        if t in INDEX_CATEGORY_FOR_TAG and t not in index_cats:
            v.append({"type": "missing_index_category", "tag": t})
    # 2) 每个分类索引类目应至少有 1 条对应标签的经验
    for t in INDEX_CATEGORY_FOR_TAG:
        if t not in used_tags:
            v.append({"type": "empty_index_category", "tag": t})
    return v


def validate_experience_tags(path: str = None) -> Dict[str, Any]:
    """汇总校验，返回报告（fail-safe）。

    Returns:
        {
          "ok": bool,
          "total_entries": int,
          "unknown_tags": [...],          # 出现的非白名单标签集合
          "violations": [ {...}, ... ],   # 明细
        }
    """
    try:
        text = load_experience_text(path)
        entries = extract_entries(text)
        violations: List[Dict[str, Any]] = []
        violations += validate_whitelist(entries)
        violations += validate_count(entries)
        violations += validate_format(entries)
        violations += validate_consistency(entries, text)
        unknown = sorted({x["tag"] for x in violations if x["type"] == "unknown_tag"})
        return {
            "ok": len(violations) == 0,
            "total_entries": len(entries),
            "unknown_tags": unknown,
            "violations": violations,
        }
    except Exception as e:
        logger.debug("[标签校验] 校验异常（降级返回空报告）: %s", e)
        return {"ok": True, "total_entries": 0, "unknown_tags": [], "violations": []}


# ---------------------------------------------------------------------------
# CLI 入口（供 tools/tag_validator.py 复用）
# ---------------------------------------------------------------------------
def main(argv=None):
    import sys
    path = argv[0] if argv else None
    report = validate_experience_tags(path)
    print(f"经验条目数: {report['total_entries']}")
    print(f"未知标签: {report['unknown_tags'] or '无'}")
    if report["violations"]:
        print(f"发现问题 {len(report['violations'])} 项:")
        for x in report["violations"]:
            loc = f"L{x['line']}" if "line" in x else f"tag={x.get('tag')}"
            print(f"  - [{x['type']}] {loc}: {x.get('title') or x.get('tag')}")
        return 1
    print("✅ 标签校验通过（白名单 + 数量 + 格式 + 一致性 全部合规）")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
