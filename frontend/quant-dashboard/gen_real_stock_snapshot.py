# -*- coding: utf-8 -*-
"""生成真实股票数据快照，供量化仪表盘离线使用。

数据源：金水谣 金水谣数据/stock/cache/<sym>_daily.json（akshare 真实 A 股指数日线）
输出：jinshuiyao-quant-dashboard/data/real_stock.json
  {
    generated_at, source,
    symbols: {
      <sym>: { name, latest{date,open,high,low,close,volume},
               prev{date,close}, change_pct, daily:[最近120日倒序/正序] }
    }
  }
纯标准库，可在任意 Python 3 运行。
"""
import json
import os
from datetime import datetime

SYMBOLS = {
    "sh000001": "上证指数",
    "sh000300": "沪深300",
    "sz399001": "深证成指",
}

# 从仪表盘目录回溯到项目根（模型/），再进 金水谣数据/stock/cache
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIRS = [
    os.path.normpath(os.path.join(HERE, "..", "..", "金水谣数据", "stock", "cache")),
    os.path.normpath(os.path.join(HERE, "..", "金水谣数据", "stock", "cache")),
]


def find_cache(sym):
    for d in CACHE_DIRS:
        p = os.path.join(d, f"{sym}_daily.json")
        if os.path.exists(p):
            return p
    return None


def main():
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "金水谣数据/stock/cache (akshare 真实A股指数日线)",
        "symbols": {},
    }
    for sym, name in SYMBOLS.items():
        path = find_cache(sym)
        if not path:
            print(f"  [跳过] {sym} 未找到缓存文件")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                series = json.load(f)
        except Exception as e:
            print(f"  [错误] {sym} 读取失败: {e}")
            continue
        if not isinstance(series, list) or len(series) < 2:
            print(f"  [跳过] {sym} 数据不足")
            continue
        latest = series[-1]
        prev = series[-2]
        # 最近 120 个交易日（正序）
        daily = series[-120:]
        change_pct = round((latest["close"] - prev["close"]) / prev["close"] * 100, 3)
        out["symbols"][sym] = {
            "name": name,
            "latest": {
                "date": latest.get("date"),
                "open": latest.get("open"),
                "high": latest.get("high"),
                "low": latest.get("low"),
                "close": latest.get("close"),
                "volume": latest.get("volume"),
            },
            "prev": {"date": prev.get("date"), "close": prev.get("close")},
            "change_pct": change_pct,
            "daily": daily,
        }
        print(f"  [OK] {sym} {name} 最新 {latest.get('date')} 收盘 {latest.get('close')} 涨跌 {change_pct}% (近{len(daily)}日)")
    out_path = os.path.join(HERE, "data", "real_stock.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n快照已写出: {out_path}  ({len(out['symbols'])} 个指数)")


if __name__ == "__main__":
    main()
