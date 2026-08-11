#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣基金净值每日刷新脚本

抓取"当前分析基金池"（用户持仓优先，空则内置池）的净值数据写入 cache，
供基金分析引擎/仪表盘/历史回测使用。抓取失败自动重试 3 次；
全部失败退出码 1（供 automation_mirror 巡检留痕）。

触发：automation_mirror mirror_fund_nav（daily@18:45）
"""

import os
import sys
import time

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj not in sys.path:
    sys.path.insert(0, _proj)


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[fund-nav-refresh {ts}] {msg}")
    sys.stdout.flush()


def main():
    from domains.fund.domain import FundDomain

    codes = None
    try:
        from domains.fund.fund_data_manager import FundDataManager
        mgr = FundDataManager()
        codes = [h.get("code") for h in mgr.get_holdings() if h.get("code")]
        _log(f"用户持仓 {len(codes) if codes else 0} 只" + ("" if codes else "，使用内置基金池"))
    except Exception as e:
        _log(f"读取持仓失败（回退内置池）: {e}")

    domain = FundDomain()
    try:
        if not domain.setup():
            _log("FundDomain.setup() 返回 False")
            return 1
    except Exception as e:
        _log(f"基金子系统初始化失败: {e}")
        return 1

    last_err = "未知"
    for attempt in range(1, 4):
        try:
            res = domain.fetch(codes)
            data = res.get("data") or {}
            if res.get("success") and data:
                _log(f"刷新完成：{len(data)} 只基金，mode={res.get('mode')}")
                return 0
            last_err = res.get("message") or "抓取返回空数据"
        except Exception as e:
            last_err = str(e)
        _log(f"第 {attempt}/3 次尝试失败: {last_err}")
        time.sleep(10 * attempt)

    _log(f"3 次尝试全部失败: {last_err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())