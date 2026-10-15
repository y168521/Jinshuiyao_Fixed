# -*- coding: utf-8 -*-
"""列表查询统一层：关键词搜索 / 多条件筛选 / 排序 / 分页（P0，JS-20261015-04）。

设计取向（低耦合、可扩展）
--------------------------
* **纯函数、无状态、无 IO**：只吃 `records` 列表，不做文件读写、不碰全局状态，
  因此 API 层（server/handlers）与 GUI 层（gui）可以**共用同一套口径**，
  不会出现"网页搜得到、桌面搜不到"的分裂。
* **字段取值器注册表**：`FIELD_GETTERS` 决定"哪些字段可被筛选/排序"。
  新增一个列表页 = 注册几个取值器，**不改动本文件的任何既有逻辑**（开闭原则）。
* **输入兜底**：任何非法入参（非数字 limit、越界 page、坏日期）一律退回安全值，
  **绝不抛异常给前端**。

不做什么
--------
* 不做鉴权/权限（本项目为单用户本机，安全边界是"是否本机"）。
* 不做数据落库（写入仍走各自的唯一写入端点，如 `utils/purchase_log.record()`）。
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

# 单页上限：防止 ?limit=999999 把 3636 条（未来更多）一次性打回前端
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

# 号码字段里常见的分隔符，归一化时会被剔除
_NUM_SEPARATORS = " \t,，、;；/|-_.。+*#"


# ---------------------------------------------------------------------------
# 归一化 / 号码解析
# ---------------------------------------------------------------------------
def _fullwidth_to_halfwidth(s: str) -> str:
    """全角数字与字母转半角（０１→01、Ａ→A）。仅处理 ASCII 区间，其余原样返回。"""
    out = []
    for ch in s:
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:      # ０-９
            out.append(chr(code - 0xFEE0))
        elif 0xFF21 <= code <= 0xFF3A:    # Ａ-Ｚ
            out.append(chr(code - 0xFEE0))
        elif 0xFF41 <= code <= 0xFF5A:    # ａ-ｚ
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize_text(s: Any) -> str:
    """关键词归一化：字符串化 → 全角转半角 → 小写 → 去空白与常见分隔符。

    解决「01 02 03」/「010203」/「01,02,03」互不相认的问题。
    """
    if s is None:
        return ""
    text = _fullwidth_to_halfwidth(str(s)).lower()
    return "".join(ch for ch in text if ch not in _NUM_SEPARATORS)


def extract_numbers(s: Any) -> set:
    """从任意文本中抽号码集合（忽略分隔符差异）。'01 02' 与 '0102' 结果不同，
    因此号码比对优先用 `numbers_match`。"""
    text = normalize_text(s)
    return {text[i:i + 2] for i in range(0, len(text) - 1, 2) if text[i:i + 2].isdigit()}


def numbers_match(hay: Any, needle: Any) -> bool:
    """号码结构化比对：把两侧都拆成 2 位号码集合后再比包含关系。

    只有当查询串本身像号码串（纯数字且长度 ≥2）时才走这条路径，
    避免普通关键词被误拆。
    """
    n = normalize_text(needle)
    if not (n.isdigit() and len(n) >= 2):
        return False
    return set(extract_numbers(n)).issubset(extract_numbers(hay))


def keyword_hit(record: Dict[str, Any], kw: str,
                fields: Sequence[str],
                number_fields: Sequence[str] = ()) -> bool:
    """关键词是否命中记录。

    子串匹配（归一化后）对 fields 全生效；**号码结构化比对只对 number_fields 生效**。
    不对所有字段生效的原因：把日期 "2026-10-11" 拆成号码集合会产生**假命中** ——
    实测搜期号 "2026115" 会误中日期为 2026-10-11 的记录。
    """
    if not kw:
        return True
    nq = normalize_text(kw)
    if not nq:
        return True
    numeric = nq.isdigit() and len(nq) >= 2
    for f in fields:
        val = get_field(record, f)
        if val is None:
            continue
        if nq and nq in normalize_text(val):
            return True
        if numeric and f in number_fields and numbers_match(val, nq):
                return True
    return False


# ---------------------------------------------------------------------------
# 字段取值器注册表（扩展点）
# ---------------------------------------------------------------------------
def _get_nested(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


FIELD_GETTERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    # AI 问答预测沉淀（predictions/predictions.json）
    "question": lambda r: r.get("question") or "",
    "answer": lambda r: r.get("answer") or "",
    "domain": lambda r: r.get("domain") or "",
    # 彩票预测（金水谣数据/predictions.json）
    "lot": lambda r: r.get("lot") or r.get("彩种"),
    "period": lambda r: str(r.get("period") or r.get("期号") or ""),
    "date": lambda r: r.get("date") or (r.get("time") or "")[:10],
    "time": lambda r: r.get("time") or "",
    "status": lambda r: "已复盘" if r.get("reviewed") else "待复盘",
    "reviewed": lambda r: bool(r.get("reviewed")),
    "purchased": lambda r: bool(r.get("purchased")),
    "hits": lambda r: r.get("hits"),
    "sqi": lambda r: r.get("confidence"),
    "purchase_amount": lambda r: r.get("purchase_amount"),
    "payout": lambda r: r.get("payout"),
}


def register_field(name: str, getter: Callable[[Dict[str, Any]], Any]) -> None:
    """注册一个可被筛选/排序的字段（新增列表页的扩展点）。"""
    FIELD_GETTERS[name] = getter


def get_field(record: Dict[str, Any], name: str) -> Any:
    v = FIELD_GETTERS.get(name)
    if v is not None:
        return v(record)
    return _get_nested(record, name)


# ---------------------------------------------------------------------------
# 查询规格
# ---------------------------------------------------------------------------
@dataclass
class QuerySpec:
    """一次列表查询的完整条件。所有字段都有安全默认值。"""

    q: str = ""
    lots: List[str] = field(default_factory=list)
    status: str = ""            # 待复盘 / 已复盘 / 命中 / 未中
    date_from: str = ""         # YYYY-MM-DD
    date_to: str = ""           # YYYY-MM-DD
    sort: str = "time"          # time / period / sqi / hits
    desc: bool = True
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def is_empty(self) -> bool:
        return not (self.q or self.lots or self.status
                    or self.date_from or self.date_to)


def _int_param(params: Dict[str, Any], key: str, default: int,
               lo: int, hi: int) -> int:
    raw = _first(params.get(key, None), str(default))
    try:
        v = int(raw or default)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _split_scalar(s):
    """按常见分隔符拆标量（逗号/顿号/分号/竖线/空白）。"""
    return [p.strip() for p in re.split(r"[,，|;；\s]+", s) if p.strip()]


def _split_lots(raw):
    """解析彩种入参：支持标量、列表、以及「a,b」/「a，b」等分隔写法。

    注意：来自 parse_qs 的入参本身就是列表（如 ["双色球,大乐透"]），
    此时仍要对每个元素再拆一次，否则多选框的值会被当成单个彩种名。
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = []
        for x in raw:
            items.extend(_split_scalar(str(x)))
    else:
        items = _split_scalar(str(raw))
    return [x for x in items if x and x != "全部"]


def _first(v, default=""):
    """取值：兼容 urllib.parse_qs 的列表形态与 GUI 的标量形态。"""
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        v = v[0] if v else default
    return str(v if v is not None else default).strip()


def parse_query(params: Dict[str, Any], default_sort: str = "time") -> QuerySpec:
    """把 HTTP query / GUI 表单 转成 QuerySpec。非法值一律兜底，不抛异常。"""
    spec = QuerySpec()
    spec.q = _first(params.get("q"))
    spec.lots = _split_lots(params.get("lot") or params.get("lots"))
    spec.status = _first(params.get("status"))
    spec.date_from = _first(params.get("date_from"))
    spec.date_to = _first(params.get("date_to"))
    spec.sort = _first(params.get("sort"), default_sort)
    spec.desc = _first(params.get("order"), "desc").lower() != "asc"
    spec.page = _int_param(params, "page", 1, 1, 10 ** 6)
    spec.page_size = _int_param(params, "limit",
                                 DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
    return spec


# ---------------------------------------------------------------------------
# 执行：筛选 → 排序 → 分页
# ---------------------------------------------------------------------------
def _to_num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def filter_records(records: Sequence[Dict[str, Any]], spec: QuerySpec,
                 search_fields: Sequence[str],
                 number_fields: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """按 spec 过滤记录（关键词 + 彩种 + 状态 + 日期区间）。"""
    out: List[Dict[str, Any]] = []
    for r in records:
        if spec.lots and get_field(r, "lot") not in spec.lots:
            continue
        if spec.status:
            st = get_field(r, "status")
            if spec.status == "命中":
                if not (_to_num(get_field(r, "hits")) or 0) > 0:
                    continue
            elif spec.status == "未中":
                if (_to_num(get_field(r, "hits")) or 0) > 0:
                    continue
            elif st != spec.status:
                continue
        if spec.date_from or spec.date_to:
            d = str(get_field(r, "date") or "")[:10]
            if spec.date_from and d and d < spec.date_from:
                continue
            if spec.date_to and d and d > spec.date_to:
                continue
        if spec.q and not keyword_hit(r, spec.q, search_fields,
                                   number_fields):
            continue
        out.append(r)
    return out


def _is_missing(record: Dict[str, Any], name: str) -> bool:
    """字段是否有值（None / 空串视为缺失）。"""
    v = get_field(record, name)
    return v is None or v == ""


def _sort_value(record: Dict[str, Any], name: str) -> Any:
    """排序取值：能转数字走数字轨(0)，否则走字符串轨(1)。

    用「轨道标记 + 值」的元组而非裸值，保证跨类型比较不会 TypeError。
    """
    v = get_field(record, name)
    num = _to_num(v)
    return (0, num) if num is not None else (1, str(v or ""))


def sort_records(records: List[Dict[str, Any]], spec: QuerySpec) -> List[Dict[str, Any]]:
    """排序：数值按数值、其余按字符串；**缺失值恒排最后**，不随升降序翻转。

    直接 `sorted(reverse=True)` 会把缺失值顶到最前 —— 用户看到一片空白行，
    会误以为"排序把数据弄丢了"，故缺失值单独摘出拼到末尾。
    """
    name = spec.sort
    have = [r for r in records if not _is_missing(r, name)]
    lack = [r for r in records if _is_missing(r, name)]
    have.sort(key=lambda r: _sort_value(r, name), reverse=spec.desc)
    return have + lack


def paginate(records: Sequence[Dict[str, Any]], spec: QuerySpec):
    """分页：返回 (当前页数据, total, total_pages)。page 越界自动夹到最后一页。"""
    total = len(records)
    size = max(1, spec.page_size)
    pages = max(1, (total + size - 1) // size)
    page = min(max(1, spec.page), pages)
    start = (page - 1) * size
    return list(records[start:start + size]), total, pages


def apply_query(records: Sequence[Dict[str, Any]], spec: QuerySpec,
                search_fields: Sequence[str],
                number_fields: Sequence[str] = ()):
    """一站式：筛选 → 排序 → 分页，返回 (页数据, total, total_pages)。"""
    rows = filter_records(records, spec, search_fields,
                                   number_fields)
    rows = sort_records(rows, spec)
    return paginate(rows, spec)


# ---------------------------------------------------------------------------
# 回显：把当前条件还原成 URL query（供前端刷新/分享后恢复）
# ---------------------------------------------------------------------------
def to_query_string(spec: QuerySpec) -> str:
    """QuerySpec → URL query 字符串（空条件省略，避免 URL 噪音）。"""
    parts: List[str] = []
    if spec.q:
        parts.append("q=" + urllib_quote(spec.q))
    if spec.lots:
        parts.append("lot=" + urllib_quote(",".join(spec.lots)))
    if spec.status:
        parts.append("status=" + urllib_quote(spec.status))
    if spec.date_from:
        parts.append("date_from=" + urllib_quote(spec.date_from))
    if spec.date_to:
        parts.append("date_to=" + urllib_quote(spec.date_to))
    if spec.sort and spec.sort != "time":
        parts.append("sort=" + urllib_quote(spec.sort))
    if not spec.desc:
        parts.append("order=asc")
    if spec.page > 1:
        parts.append("page=%d" % spec.page)
    if spec.page_size != DEFAULT_PAGE_SIZE:
        parts.append("limit=%d" % spec.page_size)
    return "&".join(parts)


def describe_filters(spec: QuerySpec) -> List[Dict[str, str]]:
    """生成「已选条件」chips，供前端逐条展示与单条清除。"""
    chips: List[Dict[str, str]] = []
    if spec.q:
        chips.append({"key": "q", "label": "关键词", "value": spec.q})
    if spec.lots:
        chips.append({"key": "lot", "label": "彩种", "value": "、".join(spec.lots)})
    if spec.status:
        chips.append({"key": "status", "label": "状态", "value": spec.status})
    if spec.date_from or spec.date_to:
        chips.append({
            "key": "date",
            "label": "日期",
            "value": "%s ~ %s" % (spec.date_from or "不限", spec.date_to or "不限"),
        })
    return chips


try:
    from urllib.parse import quote as urllib_quote
except Exception:  # pragma: no cover
    def urllib_quote(s: str) -> str:
        return s


# 让 dataclass 的 field 与 Callable 等引用可被静态检查识别（避免被当未使用）
__all__ = [
    "MAX_PAGE_SIZE", "DEFAULT_PAGE_SIZE", "QuerySpec", "parse_query",
    "apply_query", "filter_records", "sort_records", "paginate",
    "to_query_string", "describe_filters", "normalize_text",
    "extract_numbers", "register_field", "get_field",
]
