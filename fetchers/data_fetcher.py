# -*- coding: utf-8 -*-
"""足彩专用 — 数据拉取 CLI 入口

适用范围：足彩子系统（世界杯数据/实时比赛/多源竞彩）

职责：提供命令行接口，拉取足球比赛数据并写入 CSV 文件，
供 Web 服务器和 Tkinter 桌面程序共用。

与 fetchers/fetcher.py 的关系（非重复，职责不同）：
  - fetchers/data_fetcher.py  — 足彩数据拉取 CLI 入口（命令行工具，调用 jinshuiyao/ 模块）
  - fetchers/fetcher.py       — 彩票开奖数据抓取（多源采集、合并、持久化）

用法:
    python data_fetcher.py           # 拉取世界杯数据并写入CSV
    python data_fetcher.py --live    # 拉取实时比赛数据
    python data_fetcher.py --all     # 拉取所有源（世界杯+实时+多源竞彩）

数据互通:
    - 写入 jinshuiyao/data/matches.csv（Web 服务器读取）
    - 写入 jinshuiyao/data/odds.csv（赔率数据）
    - 与 Tkinter 桌面程序共用同一套 CSV 文件
"""

import sys
import os
import argparse

# 确保可以导入 jinshuiyao 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jinshuiyao.fetcher import get_fetcher, FootballFetcher
from jinshuiyao.data_fetcher import DataFetcher


def fetch_worldcup():
    """拉取 2026 世界杯数据并写入 CSV"""
    print("=" * 50)
    print("  金水谣数据拉取 - 2026 世界杯")
    print("=" * 50)

    df = DataFetcher()
    matches = df.fetch_worldcup_matches()

    if not matches:
        print("[!] 未获取到世界杯数据")
        return False

    print(f"[OK] 获取 {len(matches)} 场世界杯比赛")

    # 转换为 FootballFetcher 的格式并写入 CSV
    fetcher = FootballFetcher()
    fetcher.matches_data = []

    for i, m in enumerate(matches):
        odds = m.get('odds', {})
        fetcher.matches_data.append({
            'match_id': f"wc2026_{i:03d}",
            'home': m['home'],
            'away': m['away'],
            'league': m.get('league', '2026世界杯'),
            'match_time': f"{m.get('date', '')} {m.get('time', '')}",
            'odds_win': float(odds.get('win', 0)),
            'odds_draw': float(odds.get('draw', 0)),
            'odds_lose': float(odds.get('lose', 0)),
        })

    # 写入 CSV（与 web_server.py / Tkinter 共用）
    fetcher._save_csv()

    # 显示前5场
    print("\n前5场预览:")
    for m in fetcher.matches_data[:5]:
        print(f"  {m['match_time']} | {m['home']} vs {m['away']} "
              f"| 胜{m['odds_win']:.2f} 平{m['odds_draw']:.2f} 负{m['odds_lose']:.2f}")

    print(f"\n[OK] 数据已写入 jinshuiyao/data/matches.csv")
    print(f"[OK] 数据已写入 jinshuiyao/data/odds.csv")
    return True


def fetch_live():
    """拉取实时比赛数据"""
    print("=" * 50)
    print("  金水谣数据拉取 - 实时比赛")
    print("=" * 50)

    df = DataFetcher()
    matches = df.fetch_live_matches()

    if not matches:
        print("[!] 未获取到实时数据")
        return False

    print(f"[OK] 获取 {len(matches)} 场实时比赛")
    return True


def fetch_all_sources():
    """拉取所有数据源（多源竞彩 + 世界杯）"""
    print("=" * 50)
    print("  金水谣数据拉取 - 全源模式")
    print("=" * 50)

    # 1. 先尝试多源竞彩抓取
    print("\n[1/2] 多源竞彩抓取...")
    fetcher = get_fetcher()
    result = fetcher.fetch_all()

    if result and result.get('matches'):
        print(f"[OK] 竞彩数据: {len(result['matches'])} 场")
    else:
        print("[!] 竞彩数据获取失败，将使用世界杯数据")

    # 2. 补充世界杯数据
    print("\n[2/2] 世界杯数据...")
    wc_ok = fetch_worldcup()

    return wc_ok


def main():
    parser = argparse.ArgumentParser(description='金水谣足彩数据拉取工具')
    parser.add_argument('--live', action='store_true', help='拉取实时比赛数据')
    parser.add_argument('--all', action='store_true', help='拉取所有源')
    parser.add_argument('--worldcup', action='store_true', help='仅拉取世界杯数据（默认）')
    args = parser.parse_args()

    if args.all:
        fetch_all_sources()
    elif args.live:
        fetch_live()
    else:
        # 默认：拉取世界杯数据
        fetch_worldcup()

    print("\n" + "=" * 50)
    print("  数据拉取完成，可启动 web_server.py 查看")
    print("=" * 50)


if __name__ == '__main__':
    main()
