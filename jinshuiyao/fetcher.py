# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 多源数据抓取器 v2.0

数据源（按优先级）：
  1. 竞彩官网 (sporttery.cn)      — 最权威，API 接口
  2. 500.com 竞彩 (trade.500.com) — JSON 数据嵌入 HTML
  3. 澳客网 (okooo.com)           — 简洁 HTML 表格
  4. 500.com 赔率 (odds.500.com)  — 移动版 HTML

超时保障：
  - 单个请求 5 秒超时
  - 全流程最多 25 秒
  - 所有源失败自动生成模拟数据兜底
"""

import os
import re
import json
import time
import datetime
import threading
import requests
import csv
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

MATCHES_FILE = os.path.join(DATA_DIR, "matches.csv")
ODDS_FILE = os.path.join(DATA_DIR, "odds.csv")
TEAM_STATS_FILE = os.path.join(DATA_DIR, "team_stats.csv")

# 每源超时（秒）
PER_SOURCE_TIMEOUT = 5
# 全局超时（秒）
GLOBAL_TIMEOUT = 25


class FootballFetcher:
    """足彩数据抓取器 v2.0 — 4 源 + 模拟兜底"""

    def __init__(self):
        self.s = self._make_session()
        self.timeout = PER_SOURCE_TIMEOUT
        self.matches_data = []
        self.odds_data = []
        self.log_callback = None

    @staticmethod
    def _make_session():
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=1)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        s.verify = False
        return s

    def log(self, msg):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        try:
            print(line, flush=True)
        except (OSError, IOError):
            pass  # stdout 管道已关闭（父进程退出时）
        if self.log_callback:
            try:
                self.log_callback(line)
            except Exception:
                pass

    # ================================================================
    # 源1: 竞彩官网 API
    # ================================================================
    def _fetch_sporttery(self) -> list:
        self.log("  [1/5] 尝试竞彩官网 (sporttery.cn)...")
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        # 尝试多个 API 端点
        urls = [
            (f"https://webapi.sporttery.cn/gateway/uniform/football/"
             f"getUniformMatchResultV1.qry?matchPage=1&pageSize=50&pageNo=1&isFix=0&pcOrWap=1&matchDate={today_str}",
             {"Referer": "https://www.sporttery.cn/"}),
            ("https://webapi.sporttery.cn/gateway/uniform/football/"
             "getUniformMatchResultV1.qry?matchPage=1&pageSize=50&pageNo=1&isFix=1&pcOrWap=1",
             {"Referer": "https://www.sporttery.cn/"}),
            ("https://webapi.sporttery.cn/gateway/uniform/football/"
             "getUniformMatchResultV1.qry?matchPage=1&pageSize=50&pageNo=1&isFix=0&pcOrWap=1",
             {"Referer": "https://www.sporttery.cn/"}),
        ]
        for url, headers in urls:
            try:
                resp = self.s.get(url, timeout=self.timeout, headers=headers)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('errorCode') != '0':
                    self.log(f"    竞彩官网: API errorCode={data.get('errorCode')} (尝试下一端点)")
                    continue
                match_list = data.get('value', {}).get('matchResultList', [])
                if not match_list:
                    continue
                matches = []
                for m in match_list:
                    h_odds = self._first_val(m.get('h', 0))
                    d_odds = self._first_val(m.get('d', 0))
                    a_odds = self._first_val(m.get('a', 0))
                    matches.append({
                        'match_id': f"spt_{m.get('id', '')}",
                        'home': str(m.get('homeTeam', '')).strip(),
                        'away': str(m.get('awayTeam', '')).strip(),
                        'league': str(m.get('leagueName', '')).strip(),
                        'match_time': str(m.get('fullDate', '')).strip(),
                        'odds_win': float(h_odds) if h_odds else 0,
                        'odds_draw': float(d_odds) if d_odds else 0,
                        'odds_lose': float(a_odds) if a_odds else 0,
                    })
                if matches:
                    self.log(f"    竞彩官网: 成功获取 {len(matches)} 场")
                    return matches
            except Exception:
                continue
        self.log("    竞彩官网: 所有端点均无数据")
        return []

    @staticmethod
    def _first_val(val):
        s = str(val)
        return s.split('|')[0] if '|' in s else s

    # ================================================================
    # 源2: 500.com 竞彩 (trade.500.com)
    # ================================================================
    def _fetch_500_trade(self) -> list:
        self.log("  [2/5] 尝试 500.com ...")
        # 多个 500.com URL 按优先级尝试
        urls = [
            "https://trade.500.com/jczq/",
            "https://live.500.com/",
        ]
        for url in urls:
            try:
                resp = self.s.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    self.log(f"    500.com ({url[:30]}...): HTTP {resp.status_code}")
                    continue

                html = resp.text
                json_match = re.search(r'data-match="([^"]+)"', html)
                json_odds = re.search(r'data-odds="([^"]+)"', html)

                matches = []
                if json_match:
                    try:
                        raw = json_match.group(1).replace('&quot;', '"').replace('&amp;', '&')
                        match_data = json.loads(raw)
                        if isinstance(match_data, list):
                            for m in match_data:
                                matches.append({
                                    'match_id': str(m.get('id', '')),
                                    'home': m.get('homename', '').strip(),
                                    'away': m.get('awayname', '').strip(),
                                    'league': m.get('leaguename', '').strip(),
                                    'match_time': f"{m.get('date','')} {m.get('time','')}",
                                    'odds_win': 0, 'odds_draw': 0, 'odds_lose': 0,
                                })
                    except (json.JSONDecodeError, KeyError):
                        pass

                if json_odds and matches:
                    try:
                        raw = json_odds.group(1).replace('&quot;', '"')
                        odds_data = json.loads(raw)
                        if isinstance(odds_data, dict):
                            for m in matches:
                                entry = odds_data.get(m['match_id'])
                                if isinstance(entry, list) and len(entry) >= 3:
                                    m['odds_win'] = float(entry[0] or 0)
                                    m['odds_draw'] = float(entry[1] or 0)
                                    m['odds_lose'] = float(entry[2] or 0)
                    except (json.JSONDecodeError, ValueError):
                        pass

                if matches:
                    self.log(f"    500.com (JSON): 成功获取 {len(matches)} 场")
                    return matches

                # JSON 失败 → 尝试 HTML 解析
                html_matches = self._parse_500_html(html)
                if html_matches:
                    self.log(f"    500.com (HTML): {len(html_matches)} 场")
                    return html_matches

            except requests.Timeout:
                continue
            except requests.RequestException:
                continue
            except Exception as e:
                self.log(f"    500.com ({url[:30]}...): {e}")
                continue

        self.log("    500.com: 所有URL均无数据")
        return []

    def _parse_500_html(self, html: str) -> list:
        """解析 500.com HTML 格式的比赛列表（智能版 — 跳过编号/赛事/系统词）"""
        from .match_validator import filter_matches_lenient, MATCH_NO_RE, LEAGUE_WORDS, SYSTEM_WORDS

        matches = []
        if len(html) > 500000:
            html = html[:500000]

        # 诊断：输出 HTML 结构快照
        sample_links = re.findall(r'<a[^>]*>(.{1,30}?)</a>', html[:30000])
        self.log(f"    诊断: HTML开头30KB中找到 {len(sample_links)} 个链接, "
                 f"前5个: {sample_links[:5]}")

        rows = re.split(r'</tr>', html, flags=re.IGNORECASE)
        raw_link_count = 0
        skipped_no_team = 0
        skipped_trash = 0

        for row in rows:
            if len(matches) >= 80:
                break

            # 灵活提取所有链接
            links = re.findall(r'<a[^>]*?href="([^"]*)"[^>]*?>(.*?)</a>',
                               row, re.DOTALL | re.IGNORECASE)
            raw_link_count += len(links)

            if len(links) < 2:
                continue

            # 提取链接文本（去 HTML 标签）
            link_texts = [re.sub(r'<[^>]+>', '', t[1]).strip() for t in links]

            # ── 智能过滤：跳过比赛编号、赛事名、系统词，找真正的球队名 ──
            team_texts = []
            for text in link_texts:
                if not text or len(text) < 2 or len(text) > 20:
                    continue
                # 跳过比赛编号 (周日001, 周一002, ...)
                if MATCH_NO_RE.match(text):
                    continue
                # 跳过赛事名
                if text in LEAGUE_WORDS:
                    continue
                # 跳过系统/UI 词
                if text in SYSTEM_WORDS:
                    continue
                # 跳过纯数字/日期
                if re.match(r'^\d{1,4}$', text):
                    continue
                if re.match(r'^\d{2}:\d{2}$', text):
                    continue
                team_texts.append(text)

            # 至少需要 2 个球队名
            if len(team_texts) < 2:
                skipped_no_team += 1
                continue

            # 取前两个作为主客队
            home = team_texts[0]
            away = team_texts[1]

            # 提取赔率
            odds_cells = re.findall(r'>\s*(\d+\.\d{2})\s*<', row)
            odds_win = float(odds_cells[-3]) if len(odds_cells) >= 3 else 0
            odds_draw = float(odds_cells[-2]) if len(odds_cells) >= 2 else 0
            odds_lose = float(odds_cells[-1]) if len(odds_cells) >= 1 else 0

            # 提取 match ID
            mid = ''
            for href, text in links:
                m = re.search(r'(\d{4,})', href)
                if m:
                    mid = m.group(1)
                    break

            # 提取联赛名（team_texts 之前的 link_text 可能是联赛名）
            league = ''
            for text in link_texts:
                if text in LEAGUE_WORDS:
                    league = text
                    break

            matches.append({
                'match_id': f"500_{mid}" if mid else f"500_{len(matches)}",
                'home': home, 'away': away,
                'league': league, 'match_time': '',
                'odds_win': odds_win, 'odds_draw': odds_draw, 'odds_lose': odds_lose,
            })

        # ── 最终过滤：用 match_validator 再过滤一遍 ──
        raw_count = len(matches)
        matches = filter_matches_lenient(matches)
        filtered_out = raw_count - len(matches)

        self.log(f"    诊断: 共扫描 {len(rows)} 行, {raw_link_count} 个链接, "
                 f"候选 {raw_count} 场, 有效 {len(matches)} 场 "
                 f"(无球队名:{skipped_no_team} 校验过滤:{filtered_out})")
        if matches:
            self.log(f"    500.com HTML: {len(matches)} 场")
            for m in matches[:5]:
                self.log(f"      {m['home']} vs {m['away']} "
                         f"({m['odds_win']}/{m['odds_draw']}/{m['odds_lose']})")
        else:
            # 输出更多诊断
            all_texts = []
            for row in rows[:20]:
                row_links = re.findall(r'<a[^>]*?>(.*?)</a>', row, re.DOTALL)
                for t in row_links:
                    clean = re.sub(r'<[^>]+>', '', t).strip()
                    if clean and len(clean) >= 2:
                        all_texts.append(clean)
            if all_texts:
                self.log(f"    诊断: 前20行的链接文本: {all_texts[:15]}")
        return matches

    @staticmethod
    def _is_valid_team_pair(home: str, away: str) -> bool:
        """严格验证一对字符串是否是合法的球队名（委托给 match_validator）"""
        from .match_validator import is_valid_team_name
        return is_valid_team_name(home) and is_valid_team_name(away) and home != away

    # ================================================================
    # 源3: 澳客网 (okooo.com)
    # ================================================================
    def _fetch_okooo(self) -> list:
        self.log("  [3/5] 尝试澳客网 (okooo.com)...")
        try:
            resp = self.s.get("https://www.okooo.com/jingcai/", timeout=self.timeout)
            if resp.status_code != 200:
                self.log(f"    澳客网: HTTP {resp.status_code}")
                return []

            html = resp.text
            if len(html) > 500000:
                html = html[:500000]

            matches = []
            rows = re.split(r'<tr[^>]*>', html, flags=re.IGNORECASE)
            for row in rows:
                if len(matches) >= 80:
                    break
                teams = re.findall(r'<a[^>]*?href="[^"]*?(\d+)[^"]*"[^>]*>(.*?)</a>', row, re.DOTALL)
                if len(teams) >= 2:
                    mid = teams[0][0]
                    home = re.sub(r'<[^>]+>', '', teams[0][1]).strip()
                    away = re.sub(r'<[^>]+>', '', teams[1][1]).strip()
                    if not self._is_valid_team_pair(home, away):
                        continue
                    odds_cells = re.findall(r'>\s*(\d+\.?\d*)\s*<', row)
                    odds_win = float(odds_cells[-3]) if len(odds_cells) >= 3 else 0
                    odds_draw = float(odds_cells[-2]) if len(odds_cells) >= 2 else 0
                    odds_lose = float(odds_cells[-1]) if len(odds_cells) >= 1 else 0
                    matches.append({
                        'match_id': f"oko_{mid}",
                        'home': home, 'away': away,
                        'league': '', 'match_time': '',
                        'odds_win': odds_win, 'odds_draw': odds_draw, 'odds_lose': odds_lose,
                    })

            if matches:
                self.log(f"    澳客网: 原始候选 {len(matches)} 场")
                from .match_validator import filter_matches_lenient
                matches = filter_matches_lenient(matches)
                if matches:
                    self.log(f"    澳客网: 有效 {len(matches)} 场")
                else:
                    self.log("    澳客网: 校验后无有效数据")
                    return []
            return matches

        except requests.Timeout:
            self.log("    澳客网: 连接超时")
        except requests.RequestException:
            self.log("    澳客网: 网络不可达")
        except Exception as e:
            self.log(f"    澳客网: {e}")
        return []

    # ================================================================
    # 源4: 500.com 赔率（多 URL 尝试）
    # ================================================================
    def _fetch_500_mobile(self) -> list:
        self.log("  [4/5] 尝试 500.com 赔率...")
        mobile_urls = [
            "https://live.500.com/jczq.php",
            "https://odds.500.com/fenxi/index.php?lottype=jczq",
            f"https://live.500.com/?e={datetime.date.today().strftime('%Y-%m-%d')}",
        ]
        for url in mobile_urls:
            try:
                resp = self.s.get(url, timeout=self.timeout,
                                  headers={"Accept": "text/html,application/xhtml+xml,*/*"})
                if resp.status_code == 200 and len(resp.text) > 5000:
                    matches = self._parse_500_html(resp.text)
                    if matches:
                        self.log(f"    500.com赔率 ({url[:40]}...): {len(matches)} 场")
                        return matches
            except Exception:
                continue
        self.log("    500.com赔率: 所有URL均无数据")
        return []

    # ================================================================
    # 源5: sporttery.cn HTML 页面（API 兜底）
    # ================================================================
    def _fetch_sporttery_html(self) -> list:
        """尝试直接爬取竞彩官网 HTML 页面"""
        self.log("  [5/5] 尝试竞彩官网 HTML...")
        try:
            resp = self.s.get("https://www.sporttery.cn/jcjs/", timeout=self.timeout)
            if resp.status_code != 200 or len(resp.text) < 3000:
                self.log("    竞彩官网HTML: 页面不可用")
                return []

            html = resp.text
            matches = []
            # 从 HTML 中提取比赛数据（script 标签中的 JSON）
            scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for script in scripts:
                # 寻找包含 matchList 或 matchResult 的 JSON
                json_match = re.search(r'(?:matchList|matchResult|match_list)\s*[:=]\s*(\[.*?\])',
                                       script, re.DOTALL)
                if not json_match:
                    continue
                try:
                    data = json.loads(json_match.group(1))
                    if isinstance(data, list):
                        for m in data:
                            if isinstance(m, dict) and m.get('homeTeam'):
                                matches.append({
                                    'match_id': f"spt_h_{m.get('id', len(matches))}",
                                    'home': str(m.get('homeTeam', '')).strip(),
                                    'away': str(m.get('awayTeam', '')).strip(),
                                    'league': str(m.get('leagueName', '')).strip(),
                                    'match_time': str(m.get('fullDate', '')).strip(),
                                    'odds_win': float(self._first_val(m.get('h', 0) or 0)),
                                    'odds_draw': float(self._first_val(m.get('d', 0) or 0)),
                                    'odds_lose': float(self._first_val(m.get('a', 0) or 0)),
                                })
                    if matches:
                        break
                except (json.JSONDecodeError, ValueError):
                    continue

            if matches:
                self.log(f"    竞彩官网HTML: {len(matches)} 场")
            else:
                self.log("    竞彩官网HTML: 未解析到数据")
            return matches
        except Exception:
            pass
        return []

    # ================================================================
    # 主流程
    # ================================================================
    def fetch_today(self) -> dict:
        """
        多源抓取今日比赛，带超时保护和模拟兜底

        Returns: {'total': int, 'with_odds': int, 'matches': list, 'source': str}
        """
        overall_start = time.time()
        self.log("========== 开始多源抓取(5源) ==========")

        all_matches = []
        source_name = "none"

        # 依次尝试 5 个源，找到数据立即返回
        sources = [
            (self._fetch_sporttery, "sporttery.cn"),
            (self._fetch_500_trade, "500.com"),
            (self._fetch_okooo, "okooo.com"),
            (self._fetch_500_mobile, "500mobile"),
            (self._fetch_sporttery_html, "sporttery_html"),
        ]

        for fetch_fn, name in sources:
            elapsed = time.time() - overall_start
            if elapsed > GLOBAL_TIMEOUT:
                self.log(f"  [!] 全局超时 ({GLOBAL_TIMEOUT}s)，停止抓取")
                break

            try:
                matches = fetch_fn()
                if matches:
                    all_matches = matches
                    source_name = name
                    break
            except Exception as e:
                self.log(f"  [!] {name} 异常: {type(e).__name__}: {e}")
                continue

        # 兜底：所有源都失败 → 生成模拟数据
        if not all_matches:
            self.log("  [!] 所有源均无数据，生成模拟数据兜底...")
            all_matches = self._generate_fallback_matches()
            source_name = "fallback"
            if all_matches:
                self.log(f"  [兜底] 生成 {len(all_matches)} 场模拟比赛")
        else:
            # ── 全局校验：过滤所有无效比赛 ──
            from .match_validator import filter_matches_lenient
            raw_count = len(all_matches)
            all_matches = filter_matches_lenient(all_matches)
            if len(all_matches) < raw_count:
                self.log(f"  [校验] 过滤无效比赛: {raw_count} → {len(all_matches)} 场")

        # 统计
        with_odds = sum(1 for m in all_matches if m.get('odds_win', 0) > 0)

        elapsed = time.time() - overall_start
        self.log(f"========== 抓取完成 ({elapsed:.1f}s): "
                 f"{len(all_matches)}场/含赔率{with_odds}场 | 源: {source_name} ==========")

        self.matches_data = all_matches
        try:
            self._save_csv()
        except Exception as e:
            self.log(f"  [!] CSV 保存失败: {e}")

        return {
            'total': len(all_matches),
            'with_odds': with_odds,
            'matches': all_matches,
            'source': source_name,
        }

    def _save_csv(self):
        with open(MATCHES_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['match_id', 'home', 'away', 'league', 'match_time',
                             'odds_win', 'odds_draw', 'odds_lose'])
            for m in self.matches_data:
                writer.writerow([
                    m.get('match_id', ''), m.get('home', ''), m.get('away', ''),
                    m.get('league', ''), m.get('match_time', ''),
                    m.get('odds_win', 0), m.get('odds_draw', 0), m.get('odds_lose', 0),
                ])
        with open(ODDS_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['match_id', 'home_win', 'draw', 'away_win'])
            for m in self.matches_data:
                writer.writerow([
                    m.get('match_id', ''),
                    m.get('odds_win', 0), m.get('odds_draw', 0), m.get('odds_lose', 0),
                ])

    def load_local_matches(self) -> list:
        matches = []
        if not os.path.exists(MATCHES_FILE):
            return matches
        try:
            with open(MATCHES_FILE, 'r', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    home = row.get('home', '')
                    away = row.get('away', '')
                    # 加载时也做验证，过滤脏数据
                    if not self._is_valid_team_pair(home, away):
                        continue
                    matches.append({
                        'match_id': row.get('match_id', ''),
                        'home': home,
                        'away': away,
                        'league': row.get('league', ''),
                        'match_time': row.get('match_time', ''),
                        'odds_win': float(row.get('odds_win', 0)),
                        'odds_draw': float(row.get('odds_draw', 0)),
                        'odds_lose': float(row.get('odds_lose', 0)),
                    })
        except Exception as e:
            self.log(f"  [!] 加载CSV失败: {e}")
        if matches:
            self.log(f"  从本地CSV加载 {len(matches)} 场比赛")
        return matches

    def cleanup_dirty_csv(self):
        """清理 CSV 中的脏数据（启动时调用）"""
        if not os.path.exists(MATCHES_FILE):
            return
        try:
            all_rows = []
            dirty_count = 0
            with open(MATCHES_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    home = row.get('home', '')
                    away = row.get('away', '')
                    if self._is_valid_team_pair(home, away):
                        all_rows.append(row)
                    else:
                        dirty_count += 1
            if dirty_count > 0:
                # 重写干净数据
                if fieldnames and all_rows:
                    with open(MATCHES_FILE, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(all_rows)
                elif dirty_count > 0 and not all_rows:
                    # 全部是脏数据 → 删除文件
                    os.remove(MATCHES_FILE)
        except Exception as e:
            self.log(f"  [!] CSV清理失败: {e}")

    def fetch_team_stats(self, team_name: str) -> dict:
        try:
            if not os.path.exists(TEAM_STATS_FILE):
                return self._default_team_stats()
            with open(TEAM_STATS_FILE, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if row.get('team_name', '').strip() == team_name.strip():
                        return {
                            'goals_scored_avg': float(row.get('goals_scored_avg', 1.3)),
                            'goals_conceded_avg': float(row.get('goals_conceded_avg', 1.3)),
                        }
        except Exception:
            pass
        return self._default_team_stats()

    @staticmethod
    def _default_team_stats() -> dict:
        return {'goals_scored_avg': 1.3, 'goals_conceded_avg': 1.3}

    def _generate_fallback_matches(self) -> list:
        """所有数据源失败时，生成基于近期热门赛事的模拟数据兜底"""
        import random
        random.seed(int(time.time()) % 10000)
        
        # 近期热门联赛和球队
        leagues = [
            ("英超", [
                ("曼城", "利物浦"), ("阿森纳", "切尔西"),
                ("热刺", "纽卡斯尔"), ("曼联", "阿斯顿维拉"),
            ]),
            ("西甲", [
                ("皇马", "巴萨"), ("马竞", "皇家社会"),
                ("塞维利亚", "皇家贝蒂斯"),
            ]),
            ("德甲", [
                ("拜仁", "多特蒙德"), ("莱比锡", "勒沃库森"),
                ("斯图加特", "法兰克福"),
            ]),
            ("意甲", [
                ("国米", "AC米兰"), ("尤文", "那不勒斯"),
                ("罗马", "拉齐奥"),
            ]),
            ("法甲", [
                ("巴黎", "马赛"), ("里昂", "摩纳哥"),
                ("里尔", "尼斯"),
            ]),
            ("中超", [
                ("上海海港", "山东泰山"), ("北京国安", "上海申花"),
                ("成都蓉城", "浙江队"),
            ]),
        ]
        
        today = datetime.date.today()
        matches = []
        
        for league_name, teams in leagues:
            random.shuffle(teams)
            count = random.randint(1, 2)
            for i in range(min(count, len(teams))):
                home, away = teams[i]
                hour = random.choice([15, 18, 19, 20, 21, 23])
                minute = random.choice([00, 15, 30, 45])
                match_time = f"{today.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}"
                
                # 生成合理赔率
                base_win = round(random.uniform(1.3, 3.5), 2)
                base_draw = round(random.uniform(2.8, 3.8), 2)
                base_lose = round(random.uniform(1.5, 5.0), 2)
                
                matches.append({
                    'match_id': f"fb_{len(matches)}",
                    'home': home,
                    'away': away,
                    'league': league_name,
                    'match_time': match_time,
                    'odds_win': base_win,
                    'odds_draw': base_draw,
                    'odds_lose': base_lose,
                    'source': '离线兜底-模拟数据(所有数据源失败时生成)',
                })
        
        random.shuffle(matches)
        return matches[:12]


# ================================================================
# 全局单例
# ================================================================
_fetcher_instance = None
_fetcher_lock = threading.Lock()


def get_fetcher() -> FootballFetcher:
    global _fetcher_instance
    if _fetcher_instance is None:
        with _fetcher_lock:
            if _fetcher_instance is None:
                _fetcher_instance = FootballFetcher()
    return _fetcher_instance