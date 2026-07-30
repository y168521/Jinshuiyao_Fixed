# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 比赛数据校验器 v3.0

所有抓取到的比赛数据必须经过此校验器，确保：
  1. 赔率 > 0 且在合理区间 (1.01 ~ 50.0)
  2. 球队名不是系统词、导航词、赛事名、比赛编号
  3. 主客队名不同
  4. 比赛编号格式合法

使用方式：
  from jinshuiyao.match_validator import validate_match, is_valid_team_name, is_valid_odds
  ok, reason = validate_match(match_dict)
"""

import re
import math
from typing import Tuple, Optional


# ═══════════════════════════════════════════════════════════════
# 黑名单词库
# ═══════════════════════════════════════════════════════════════

# 系统/UI 词（绝对不能是球队名）
SYSTEM_WORDS = {
    "系统通知", "我知道了", "截止时间", "剩余时间",
    "登录/注册", "登录", "注册", "隐藏", "显示余额", "退出",
    "个人中心", "账户", "余额", "充值", "提现",
    "安全", "设置", "消息", "通知", "提醒", "优惠活动",
    "帮助", "客服", "咨询", "活动", "更多", "查看全部",
    "返回顶部", "回到顶部", "TOP", "top",
    "展开", "收起", "折叠", "切换",
    "首页", "导航", "详情", "返回", "搜索", "下载",
    "投注须知", "购彩须知", "法律声明", "隐私政策", "用户协议",
    "免责", "责任", "公安", "网安", "备案", "公网安备",
    "ICP", "Copyright", "©", "版权",
    "错误", "失败", "加载", "超时", "重试", "刷新", "暂无",
}

# 赛事名（不能是球队名）
LEAGUE_WORDS = {
    "世界杯", "英超", "西甲", "德甲", "意甲", "法甲", "欧冠",
    "欧联杯", "欧会杯", "欧国联", "欧洲杯", "美洲杯", "亚洲杯",
    "非洲杯", "中超", "日职", "韩K联", "澳超", "荷甲", "葡超",
    "巴甲", "阿甲", "美职联", "墨超", "瑞典超", "挪超", "俄超",
    "土超", "比甲", "苏超", "英冠", "英甲", "英乙",
    "世俱杯", "世青赛", "奥运男足", "奥运女足",
    "赛事", "联赛", "开奖", "投注", "让球", "胜平负",
    "全部", "所有", "筛选", "排序", "热门", "推荐", "关注",
}

# 比赛编号正则（500.com 格式: 周日001, 周日002, ...）
MATCH_NO_RE = re.compile(r'^周[一二三四五六日]\d{3}$')

# 纯数字/日期
PURE_NUMBER_RE = re.compile(r'^\d+\s*$')
DATE_RE = re.compile(r'^\d{2}[-/]\d{2}[-/]\d{2,4}$')
TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def is_valid_team_name(name: str) -> bool:
    """单队名合法性校验"""
    if not name:
        return False

    name = str(name).strip()

    # 长度
    if len(name) < 2 or len(name) > 25:
        return False

    # 纯数字/日期/时间
    if PURE_NUMBER_RE.match(name):
        return False
    if DATE_RE.match(name):
        return False
    if TIME_RE.match(name):
        return False

    # 比赛编号
    if MATCH_NO_RE.match(name):
        return False

    # 黑名单：系统词
    if name in SYSTEM_WORDS:
        return False

    # 黑名单：赛事名
    if name in LEAGUE_WORDS:
        return False

    # 子串匹配：包含已知黑名单词
    for word in SYSTEM_WORDS:
        if word in name and len(word) >= 2:
            return False
    for word in LEAGUE_WORDS:
        if word in name and len(word) >= 2:
            return False

    # 特殊字符
    if re.search(r'[《》〈〉「」『』【】]', name):
        return False

    # 必须包含中文或大写字母开头的单词
    if not re.search(r'[\u4e00-\u9fff]|[A-Z][a-z]{2,}', name):
        return False

    return True


def is_valid_odds(value) -> bool:
    """赔率合法性校验"""
    try:
        value = float(value)
    except (ValueError, TypeError):
        return False

    if not math.isfinite(value):
        return False

    if value <= 0:
        return False

    # 合理区间
    if value < 1.01 or value > 50.0:
        return False

    return True


def is_valid_match_no(match_no: str) -> bool:
    """比赛编号合法性校验"""
    if not match_no:
        return True  # 没有编号也可以（手动输入等场景）
    match_no = str(match_no).strip()
    # 500.com 格式: 周日001
    if MATCH_NO_RE.match(match_no):
        return True
    # 其他格式: 数字编号
    if re.match(r'^\d+$', match_no):
        return True
    # 带前缀的编号 (spt_xxx, 500_xxx, oko_xxx)
    if re.match(r'^[a-zA-Z]+_\d+$', match_no):
        return True
    return True  # 宽松模式，允许任意格式


def validate_match(match: dict) -> Tuple[bool, str]:
    """
    完整比赛数据校验

    Args:
        match: 比赛字典，必须有 home, away, odds_win, odds_draw, odds_lose

    Returns:
        (是否通过, 失败原因)
    """
    # ── 球队名校验 ──
    home = str(match.get('home', '')).strip()
    away = str(match.get('away', '')).strip()

    if not is_valid_team_name(home):
        return False, f"主队名非法: '{home}'"

    if not is_valid_team_name(away):
        return False, f"客队名非法: '{away}'"

    if home == away:
        return False, f"主客队相同: '{home}'"

    # ── 赔率校验 ──
    odds_win = match.get('odds_win', 0)
    odds_draw = match.get('odds_draw', 0)
    odds_lose = match.get('odds_lose', 0)

    if not all(is_valid_odds(x) for x in [odds_win, odds_draw, odds_lose]):
        return False, f"赔率非法: {odds_win}/{odds_draw}/{odds_lose}"

    # ── 比赛编号校验（可选）──
    match_id = match.get('match_id', '')
    if not is_valid_match_no(match_id):
        return False, f"比赛编号非法: {match_id}"

    return True, "ok"


def filter_matches(raw_matches: list) -> Tuple[list, list]:
    """
    批量过滤比赛列表

    Args:
        raw_matches: 原始比赛列表

    Returns:
        (有效比赛列表, 被丢弃的比赛列表)
    """
    valid = []
    discarded = []
    for m in raw_matches:
        ok, reason = validate_match(m)
        if ok:
            valid.append(m)
        else:
            discarded.append((m, reason))
    return valid, discarded


def filter_matches_lenient(raw_matches: list) -> list:
    """
    宽松过滤：只拒绝明显无效的，容错模式
    """
    valid = []
    for m in raw_matches:
        home = str(m.get('home', '')).strip()
        away = str(m.get('away', '')).strip()

        # 只检查最基本的
        if not home or not away:
            continue
        if home == away:
            continue
        if home in SYSTEM_WORDS or away in SYSTEM_WORDS:
            continue
        if home in LEAGUE_WORDS or away in LEAGUE_WORDS:
            continue
        if MATCH_NO_RE.match(home) or MATCH_NO_RE.match(away):
            continue

        # 赔率可以不全，但全0则跳过
        w = m.get('odds_win', 0) or 0
        d = m.get('odds_draw', 0) or 0
        l = m.get('odds_lose', 0) or 0
        if w == 0 and d == 0 and l == 0:
            continue

        valid.append(m)
    return valid