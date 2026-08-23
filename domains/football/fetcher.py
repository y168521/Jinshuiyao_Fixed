# -*- coding: utf-8 -*-
"""足彩真实数据抓取器（体彩官方竞彩 API 主源 + 500.com 兜底）

数据性质：
- 主源：中国体育彩票官方竞彩足球接口（webapi.sporttery.cn），真实赛程+官方赔率，当前销售期赛事。
- 兜底：500.com 竞彩足球页（HTML 解析），真实数据。
- 输出：金水谣数据/football_matches.json（统一结构 + fetched_at 时间戳）。

统一结构（对齐旧 matches.csv 列并扩展盘口）：
    match_id, home, away, league, match_time, odds_win, odds_draw, odds_lose,
    hhad_goal_line, hhad_win, hhad_draw, hhad_lose, crs, ttg, hafu, match_date, source
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, '金水谣数据')
OUT_FILE = os.path.join(DATA_DIR, 'football_matches.json')

SPORTTERY_URL = ('https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry'
                 '?clientCode=3001&productId=9')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      'Chrome/126.0 Safari/537.36')
TIMEOUT = 20


def _log(msg):
    print(f'[football-fetcher] {msg}', flush=True)


def _safe_odds(d, key):
    """had/hhad 字典取赔率字符串，异常返回 ''"""
    try:
        v = d.get(key, '')
        return str(v) if v not in (None, '', '-1') else ''
    except Exception:
        return ''


def _urlopen_with_dns_heal(req, timeout=TIMEOUT, max_retries=3):
    """urllib 请求 + Windows DNS 缓存损坏自愈（flushdns 后重试）。

    本机曾因 Windows DNS 缓存损坏导致整晚抓取失败（getaddrinfo failed），
    但 PowerShell/其他进程解析正常，flushdns 即可恢复。仅 Windows 生效，静默失败不致命。
    逻辑对齐 fetchers/fetcher.py._request_with_retry 的 DNS 自愈分支。
    """
    last = None
    for attempt in range(max_retries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last = e
            if os.name == "nt" and ("getaddrinfo failed" in str(e) or "NameResolutionError" in str(e)):
                try:
                    subprocess.run(["ipconfig", "/flushdns"],
                                   capture_output=True, timeout=10,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    _log("DNS 缓存异常，已自动 flushdns，重试")
                except Exception:
                    pass
                time.sleep(2)
        if attempt < max_retries - 1:
            time.sleep(min(1 * (2 ** attempt), 8))
    raise last


def fetch_from_sporttery():
    """体彩官方竞彩足球接口：真实赛程+赔率"""
    req = urllib.request.Request(SPORTTERY_URL, headers={
        'User-Agent': UA, 'Referer': 'https://m.sporttery.cn/'})
    with _urlopen_with_dns_heal(req) as r:
        j = json.loads(r.read().decode('utf-8', 'replace'))
    if not j.get('success'):
        raise RuntimeError(f'体彩接口返回失败: {j.get("errorMessage")}')
    matches = []
    for m in j.get('value', {}).get('matchInfoList', []):
        for s in m.get('subMatchList', []):
            had = s.get('had') or {}
            hhad = s.get('hhad') or {}
            match_time = f"{s.get('matchDate', '')} {s.get('matchTime', '')}".strip()
            matches.append({
                'match_id': str(s.get('matchId', '')),
                'home': s.get('homeTeamAbbName') or s.get('homeTeamAllName', ''),
                'away': s.get('awayTeamAbbName') or s.get('awayTeamAllName', ''),
                'league': s.get('leagueAbbName') or s.get('leagueName', ''),
                'match_time': match_time,
                'match_date': s.get('matchDate', ''),
                'odds_win': _safe_odds(had, 'h'),
                'odds_draw': _safe_odds(had, 'd'),
                'odds_lose': _safe_odds(had, 'a'),
                'hhad_goal_line': (hhad.get('goalLineValue') or hhad.get('goalLine') or ''),
                'hhad_win': _safe_odds(hhad, 'h'),
                'hhad_draw': _safe_odds(hhad, 'd'),
                'hhad_lose': _safe_odds(hhad, 'a'),
                'crs': json.dumps(s.get('crs') or {}, ensure_ascii=False),
                'ttg': json.dumps(s.get('ttg') or {}, ensure_ascii=False),
                'hafu': json.dumps(s.get('hafu') or {}, ensure_ascii=False),
                'source': 'sporttery',
            })
    return matches


def fetch_from_500():
    """500.com 竞彩足球页兜底（HTML 解析）"""
    req = urllib.request.Request('https://trade.500.com/jczq/', headers={
        'User-Agent': UA, 'Referer': 'https://500.com/'})
    with _urlopen_with_dns_heal(req) as r:
        html = r.read().decode('gb2312', 'replace')
    matches = []
    # 500 竞彩页每场结构：<tr id="tr_0"> ... 主队/客队/联赛/赔率 单元格
    for tr in re.findall(r'<tr[^>]*id="tr_\d+"[^>]*>(.*?)</tr>', html, re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 10:
            continue
        def _txt(x):
            x = re.sub(r'<[^>]+>', '', x or '')
            return x.strip()
        home = _txt(tds[4]) if len(tds) > 4 else ''
        away = _txt(tds[6]) if len(tds) > 6 else ''
        league = _txt(tds[1]) if len(tds) > 1 else ''
        odds = [_txt(t) for t in tds[7:10]] if len(tds) >= 10 else []
        if not home or not away:
            continue
        matches.append({
            'match_id': '500_' + str(len(matches) + 1).zfill(3),
            'home': home, 'away': away, 'league': league,
            'match_time': '', 'match_date': '',
            'odds_win': odds[0] if len(odds) > 0 else '',
            'odds_draw': odds[1] if len(odds) > 1 else '',
            'odds_lose': odds[2] if len(odds) > 2 else '',
            'hhad_goal_line': '', 'hhad_win': '', 'hhad_draw': '', 'hhad_lose': '',
            'crs': '', 'ttg': '', 'hafu': '',
            'source': '500com',
        })
    return matches


def fetch_matches(force_refresh=True):
    """抓取足彩赛事；主源失败自动降级 500.com；成功写 JSON 文件"""
    if os.path.exists(OUT_FILE) and not force_refresh:
        with open(OUT_FILE, encoding='utf-8') as f:
            return json.load(f).get('matches', [])
    errs = []
    try:
        matches = fetch_from_sporttery()
        if matches:
            _log(f'体彩官方源成功: {len(matches)} 场')
            _save(matches, 'sporttery')
            return matches
        errs.append('体彩官方源返回空')
    except Exception as e:
        errs.append(f'体彩官方源失败: {type(e).__name__} {str(e)[:80]}')
    try:
        matches = fetch_from_500()
        if matches:
            _log(f'500.com 兜底成功: {len(matches)} 场')
            _save(matches, '500com')
            return matches
        errs.append('500.com 返回空')
    except Exception as e:
        errs.append(f'500.com 失败: {type(e).__name__} {str(e)[:80]}')
    # 双源都失败：若本地已有真实缓存，回退返回缓存（不刷错误日志，仪表盘仍显示上一期真实数据）
    if os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding='utf-8') as f:
                cached = json.load(f).get('matches', [])
            if cached:
                _log(f'双源抓取失败，回退本地缓存 {len(cached)} 场: {"; ".join(errs)}')
                return cached
        except Exception:
            pass
    raise RuntimeError('; '.join(errs))


def _save(matches, source):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        'fetched_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': source,
        'count': len(matches),
        'matches': matches,
    }
    tmp = OUT_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_FILE)
    _log(f'已写入 {OUT_FILE} ({len(matches)} 场)')


def main():
    force = '--no-refresh' not in sys.argv
    try:
        m = fetch_matches(force_refresh=force)
        print(f'OK: {len(m)} 场真实赛事，最新日期: {m[0]["match_date"] if m else "-"}')
        return 0
    except Exception as e:
        print(f'FAIL: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())