# -*- coding: utf-8 -*-
"""基金本地缓存层（JS-20261021-04 从 `fetcher.FundFetcher` 拆出）

拆包理由与 `fund_mock.py` 一致（JS-20260924-28）：降低 FundFetcher 类体量，
让「取数」与「落盘/读盘」各自可独立测试与审查。

本层同时是**数据诚实铁律的落点**：只有真实数据才准写进缓存。
历史上模拟降级数据也会被 `_write_cache` 落盘，于是 24 小时内每次读取都拿到
同一套假数据，外观与真实数据完全一样（有日期、有数值、有曲线）——这就是
P0-1 的放大器。本机实测：11 个基金的持仓缓存文件里十大重仓股逐字相同。

数据来源标记取值（本模块是唯一真源，`fetcher.py` 从这里导入再转手给上层）：
  SOURCE_REAL    "real"     akshare 真实接口返回，才准落盘
  SOURCE_MOCK    "mock"     模拟兜底数据，禁止落盘
  SOURCE_UNKNOWN "unknown"  旧格式缓存等来源不明，一律按不可信处理
"""
import os
import logging
from datetime import datetime
from utils.safe_json import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)

SOURCE_REAL = "real"
SOURCE_MOCK = "mock"
SOURCE_UNKNOWN = "unknown"

# 缓存保质期：超过 1 天视为过期，需重新抓取（与原 fetcher 内口径一致）
CACHE_TTL_SECONDS = 86400


def unpack_cache_payload(raw):
    """拆开缓存文件外壳，取出 (数据, 来源标记)

    新格式：{"source": "real"|"mock", "cached_at": "...", "records": [...] 或 "data": {...}}
    旧格式：裸 list / 裸 dict，没有来源标记 → 来源记 unknown，调用方按不可信处理
    （JS-20261021-04：宁可错杀一批旧缓存，不可把模拟数据当真实数据返回）。
    """
    if isinstance(raw, dict) and "source" in raw:
        source = raw.get("source") or SOURCE_UNKNOWN
        if "records" in raw:
            return raw["records"], source
        if "data" in raw:
            return raw["data"], source
        if "value" in raw:
            return raw["value"], source
        return raw, source
    return raw, SOURCE_UNKNOWN


def _as_frame(data):
    """把缓存里的 records 还原成 DataFrame"""
    import pandas as pd
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict) and "records" in data:
        return pd.DataFrame(data["records"])
    return pd.DataFrame([data])


def _as_record(data):
    """把缓存里的 data 还原成单条记录（as_dataframe=False 的读法）"""
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return data[0] if data else None
    return None


def _is_fresh(path):
    """缓存是否还在保质期内"""
    return datetime.now().timestamp() - os.path.getmtime(path) <= CACHE_TTL_SECONDS


def _pack_payload(data, as_dataframe, source):
    """按写入时的形态打包缓存文件外壳"""
    payload = {
        "source": source,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if as_dataframe and hasattr(data, "to_dict"):
        payload["records"] = data.to_dict(orient="records")
    elif isinstance(data, dict):
        payload["data"] = data
    elif isinstance(data, list):
        payload["records"] = data
    else:
        payload["value"] = str(data)
    return payload


class FundCache:
    """基金本地 JSON 缓存（每个文件带「数据来源」标记）"""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def path(self, key):
        """缓存文件路径"""
        return os.path.join(self.cache_dir, f"{key}.json")

    def read(self, key, as_dataframe=True):
        """读取缓存

        Returns:
            (数据, 来源标记)。未命中 / 已过期 / 读取失败 / 旧格式无来源标记，
            一律返回 (None, SOURCE_UNKNOWN) —— 旧格式按未命中处理，
            因为它很可能是修复前写入的模拟数据，不能冒充当真实数据返回。
        """
        path = self.path(key)
        if not os.path.exists(path):
            return None, SOURCE_UNKNOWN
        try:
            raw = safe_load_json(path, default=None)
            if not _is_fresh(path):
                logger.debug("缓存过期: %s", key)
                return None, SOURCE_UNKNOWN
            data, source = unpack_cache_payload(raw)
            if source == SOURCE_UNKNOWN:
                logger.info("缓存无来源标记（旧格式），按未命中处理并重取真实数据: %s", key)
                return None, SOURCE_UNKNOWN
            return (_as_frame(data) if as_dataframe else _as_record(data)), source
        except Exception as e:
            logger.warning("缓存读取失败 %s: %s", key, e)
            return None, SOURCE_UNKNOWN

    def write(self, key, data, as_dataframe=True, source=SOURCE_REAL):
        """写入缓存

        只有真实数据才准落盘：模拟数据一旦写进缓存，下一次读取就会把它
        当成真实数据用（P0-1 根因）。这一层自带闸门——调用方忘判也写不进去。
        """
        if source != SOURCE_REAL:
            logger.info("跳过缓存写入（数据来源=%s，非真实数据不落盘）: %s", source, key)
            return
        try:
            safe_write_json(self.path(key), _pack_payload(data, as_dataframe, source))
        except Exception as e:
            logger.warning("缓存写入失败 %s: %s", key, e)
