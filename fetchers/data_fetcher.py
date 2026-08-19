# -*- coding: utf-8 -*-
"""足彩专用 — 真实数据拉取 CLI 入口（体彩官方竞彩 API 主源 + 500.com 兜底）

与 fetchers/fetcher.py 的关系（非重复，职责不同）：
  - fetchers/data_fetcher.py  — 足彩真实赛事拉取 CLI（调用 domains/football/fetcher.py）
  - fetchers/fetcher.py       — 彩票开奖数据抓取（多源采集、合并、持久化）

用法:
    python data_fetcher.py                # 拉取真实赛事并写入 金水谣数据/football_matches.json
    python data_fetcher.py --refresh      # 强制联网刷新（跳过缓存）

数据互通:
    - 写入 金水谣数据/football_matches.json（Web 服务器 / GUI / 调度器统一读取）
    - 历史真实赛果回测使用 jinshuiyao/data/matches_real.csv（不在此写入）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fetch_all(force=False):
    from domains.football.fetcher import fetch_matches
    matches = fetch_matches(force_refresh=force)
    print(f"\n[OK] 真实赛事抓取完成: {len(matches)} 场（体彩官方竞彩 API）")
    for m in matches[:5]:
        print(f"  {m.get('league', '')} {m.get('home', '')} vs {m.get('away', '')} "
              f"{m.get('match_time', '')} 胜/平/负={m.get('odds_win')}/{m.get('odds_draw')}/{m.get('odds_lose')}")
    return matches


def main():
    args = sys.argv[1:]
    force = "--refresh" in args or "-f" in args
    fetch_all(force=force)


if __name__ == "__main__":
    main()
