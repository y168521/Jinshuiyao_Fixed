# -*- coding: utf-8 -*-
"""胆拖号码串解析 —— JS-20261006-03

背景（实测取证）：
  `utils/lottery_prize.py::judge_prize` 与 `utils/number_utils.py::count_match`
  都是**按逗号切分**号码串。而胆拖的 nums 写法是：

      大乐透：[前区胆:23,27 拖:14,16,25,26] [后区胆:12 拖:01,07]
      双色球：[胆:04,24]拖:03,07,08,15,27+07,11

  按逗号切出来的片段是 "[前区胆:23"、"27 拖:14"、"15] [后区胆:12 拖:01" 这种，
  **连胆码都识别不了**，只有碰巧是纯数字的片段（如 "04"）才被当成号码。
  后果：胆拖的 hits 只反映极少数片段、prize_tier 几乎恒为 None，
  且 status 还写成 `lose`（看起来像"确实没中奖"，而不是"判定不了"）——静默失效。
  实测 28 条大乐透胆拖：平均命中 0.250，正确算法 0.929（低估 3.7 倍）。

本模块提供胆拖解析与「最优一注」命中计算，供两个真源调用。
**非胆拖输入一律返回 None，调用方回退原逻辑** —— 保证向后兼容。

用法：
    from utils.dantuo import parse_dantuo, best_hits, is_dantuo
    st = parse_dantuo("[前区胆:23,27 拖:14,16,25,26] [后区胆:12 拖:01,07]")
    # -> ([23, 27], [14, 16, 25, 26], [12], [1, 7])
    best_hits(st, {14,15,16,23,26}, {7,9}, 5, 2)
    # -> (4, 1)   即前区中 4、后区中 1 = 四等奖
"""
from __future__ import annotations

import re

# 胆拖主段：[前区胆:.. 拖:..] / [胆:..]拖:..   （两种写法都要吃下）
_RE_DAN = re.compile(r"(?:前区)?胆[:：]([\d,]+)\s*\]?\s*拖[:：]([\d,]*)")
_RE_BACK_DAN = re.compile(r"后区胆[:：]([\d,]+)\s*\]?\s*拖[:：]([\d,]*)")


def _nums(text):
    return [int(x) for x in str(text or "").split(",") if x.strip().isdigit()]


def is_dantuo(s):
    """是否为胆拖写法

    判据刻意放宽到「含『胆』字即可」：只要看出是胆拖意图，就走胆拖分支；
    解析不出胆码时由调用方判 `not_applicable`，**而不是回退成普通单注**。
    回退更危险——它会把 "[前区胆:23" 这类片段当号码去比对，得出看似合理
    的假结果（这正是本次要修的静默失效：算不出来伪装成"确实没中/中了"）。
    """
    return "胆" in str(s or "")


def parse_dantuo(s):
    """解析胆拖号码串 → (前区胆, 前区拖, 后区胆, 后区拖)

    非胆拖或解析不出胆码时返回 None，由调用方回退到普通单注/复式逻辑。
    """
    s = str(s or "")
    m = _RE_DAN.search(s)
    if not m:
        return None
    fd = _nums(m.group(1))
    if not fd:
        return None
    ft = _nums(m.group(2))
    mb = _RE_BACK_DAN.search(s)
    if mb:
        bd, bt = _nums(mb.group(1)), _nums(mb.group(2))
    else:
        # 双色球写法：后区跟在 "+" 后面，无「后区胆」前缀
        tail = s.split("+", 1)
        bd, bt = (_nums(tail[1]), []) if len(tail) > 1 else ([], [])
    return (fd, ft, bd, bt)


def best_hits(struct, actual_front, actual_back, k, kb):
    """胆拖的「最优一注」命中数 = (前区命中, 后区命中)

    原理：胆码每注必含，拖码只需补 (k - 胆数) 个，因此最优一注必然把
    **拖码里命中的那些**优先补进去：
        命中 = |胆 ∩ 开奖| + min(|拖 ∩ 开奖|, 需补个数)
    这样无需展开 C(拖, 需补) 个组合（会爆炸），O(1) 即可求出最优值。
    """
    fd, ft, bd, bt = struct
    need_f = max(0, k - len(fd))
    need_b = max(0, (kb or 0) - len(bd))
    af = set(actual_front or ())
    ab = set(actual_back or ())
    hf = len(set(fd) & af) + min(len(set(ft) & af), need_f)
    hb = len(set(bd) & ab) + min(len(set(bt) & ab), need_b) if kb else 0
    return hf, hb
