# -*- coding: utf-8 -*-
"""知识入库：把现役数据源接进 `knowledge_store`（版本化存储层）

为什么有本模块（JS-20261002-11 的 A3）：
存储层建好了、也接进了一致性门禁第 ⑬ 项，但**里面一条数据都没有**——
门禁在空库上恒绿，等于"装了个监控空房间的摄像头"。
本模块提供第一个真实写入源：AI 决策卡。

设计取舍：
  1. **幂等优先**：调度器每 15 秒轮询一次，如果每次都 `put` 一条，WAL 会无限膨胀。
     故先比对 payload，**内容没变就跳过**（不产生新版本）。
  2. **补齐走 patch 而不是覆盖**：决策卡"反事实对照"字段约 52% 缺失（总纲现状体检），
     后续补齐时应当追加新版本，历史留得住、可回滚。
  3. **单条失败不阻断全批**：坏卡记进 errors 继续跑，但**必须报出来**（静默才是真敌人）。

复用的现役口径（不另起一套）：
  - 条目切分正则与 `core/ai/ai_decisions_extractor._load_new_decision_entries` **完全一致**
    （`^### YYYY-MM-DD`），避免出现"两套切分结果不一样"的漂移。
  - 存储走 `core/infra/knowledge_store`，不直接写 JSON。
"""
import os
import re

from core.infra import knowledge_store as ks

# 决策卡所属命名空间
NS_DECISION = "决策卡"

# 条目切分：与 ai_decisions_extractor 同一口径（改一处必须改两处）
_ENTRY_SPLIT_RE = re.compile(r"(?m)^### \d{4}-\d{2}-\d{2}.*$")
_DATE_IN_HEADING_RE = re.compile(r"^###\s*(\d{4}-\d{2}-\d{2})")
# 字段行：`- 字段名：值`（值可跨行，直到下一个 `- 字段：` 或条目结束）
# ⚠️ 必须容忍加粗写法 `- **反事实对照**：…`：不加 `\**` 会把字段名捕获成
# `**反事实对照**`，导致 5 张明明写了反事实的卡被判成"缺失"（假绿）。
# 字段名长度下限必须是 **1**：「坑」是单字必填字段，写成 {2,10} 会让 73 张卡
# 全部被判成"缺坑"（实测 100% 假缺失）。
_FIELD_RE = re.compile(r"(?m)^-\s*\**([^\s：:*]{1,10})\**\s*[：:]\s*")

# 决策卡必填字段（ai_decisions.md 头部声明的 10 项）
REQUIRED_FIELDS = (
    "属主", "做了什么", "为什么根因", "验证", "坑",
    "有效方法", "关联文件", "关联总索引", "反事实对照", "置信度",
)

DECISIONS_PATH = os.path.join(ks.BASE_DIR, "金水谣数据", "log", "ai_decisions.md")


def parse_fields(entry):
    """把一条决策条目解析成 {字段名: 值}，并列出缺失的必填项。

    Returns:
        dict: {"fields": {...}, "missing": [...], "title": str, "date": str}
    """
    heading = entry.split("\n", 1)[0].replace("###", "", 1).strip()
    m = _DATE_IN_HEADING_RE.match(entry.strip())
    date = m.group(1) if m else ""

    marks = [(mm.start(), mm.end(), mm.group(1)) for mm in _FIELD_RE.finditer(entry)]
    fields = {}
    for i, (_pos, vpos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(entry)
        fields[name.strip("*").strip()] = entry[vpos:end].strip()

    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    return {"fields": fields, "missing": missing, "title": heading, "date": date}


def split_entries(text):
    """按 `### YYYY-MM-DD` 切分出决策条目（与 ai_decisions_extractor 同口径）。"""
    positions = [m.start() for m in _ENTRY_SPLIT_RE.finditer(text)]
    out = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(text)
        entry = text[pos:end].strip()
        if any(k in entry for k in ("做了什么", "为什么根因", "有效方法")):
            out.append(entry)
    return out


def _build_payload(entry):
    """构造入库 payload：结构化字段 + 原文 + 完整性标记。"""
    p = parse_fields(entry)
    return {
        "title": p["title"],
        "date": p["date"],
        "fields": p["fields"],
        "missing_fields": p["missing"],
        "complete": not p["missing"],
        "raw": entry,
    }


def _meta_of(payload):
    # ⚠️ 踩坑：`"".split()[0]` 会 IndexError。缺「属主」的旧卡正是因为这一行整批入库失败
    # （25 条），而这些卡恰恰是字段最不全的那批——最需要进库体检的反而进不来。
    parts = (payload["fields"].get("属主") or "").strip().split()
    owner = parts[0] if parts else "unknown"
    return {
        "author": owner[:32],
        "source": "金水谣数据/log/ai_decisions.md",
        "tags": ["决策卡", "自动入库"] + ([owner] if owner != "unknown" else []),
        "tier": "L2",            # 结构化（字段已解析）
        "maturity": "draft",
        "acl": "internal",
        "expires_at": None,      # 决策卡是长期资产，不设过期
    }


def ingest_decision_entries(entries):
    """把决策条目写入知识存储层（幂等：内容未变则跳过，不产生新版本）。

    Returns:
        dict: {"total", "created", "updated", "skipped", "errors": [...]}
    """
    stats = {"total": len(entries or []), "created": 0, "updated": 0,
             "skipped": 0, "errors": []}
    for entry in (entries or []):
        try:
            payload = _build_payload(entry)
            key = "%s#%s" % (payload["date"] or "无日期", payload["title"][:40])
            cur = ks.get(NS_DECISION, key)
            if cur is not None:
                if (cur.get("payload") or {}) == payload:
                    stats["skipped"] += 1
                    continue
                ks.put(NS_DECISION, key, payload, _meta_of(payload))
                stats["updated"] += 1
            else:
                ks.put(NS_DECISION, key, payload, _meta_of(payload))
                stats["created"] += 1
        except Exception as e:      # 单条失败不阻断全批，但必须报出来
            stats["errors"].append("%s: %s" % (type(e).__name__, e))
    return stats


def ingest_all_from_file(path=None):
    """全量导入（首次灌库 / 补跑用）。文件读不到一律抛错，不静默返回空。"""
    p = path or DECISIONS_PATH
    if not os.path.isfile(p):
        raise FileNotFoundError("决策卡文件不存在: %s" % p)
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    return ingest_decision_entries(split_entries(text))


def completeness_report():
    """完整性体检：多少张卡缺必填字段（现状体检实测反事实约 52% 缺失）。"""
    # ⚠️ 必须 with_payload=True：scan 默认只返回索引摘要（无 payload），
    # 漏了它就会得到"缺失 0"的假绿。
    try:
        nodes = ks.scan(ns=NS_DECISION, with_payload=True)
    except Exception:
        return {"error": "扫描失败"}
    total = len(nodes)
    missing_counter = {}
    incomplete = 0
    for n in nodes:
        miss = (n.get("payload") or {}).get("missing_fields") or []
        if miss:
            incomplete += 1
        for f in miss:
            missing_counter[f] = missing_counter.get(f, 0) + 1
    return {"total": total, "incomplete": incomplete,
            "missing_by_field": dict(sorted(missing_counter.items(),
                                            key=lambda kv: -kv[1]))}
