# -*- coding: utf-8 -*-
"""维度共识引擎 - 吸收朋友方法的三路系统 + 位置热码覆盖率 + 逐号码共识度

W63补20：对话方法吸收（朋友"超级分析师"方法论）
  1. 路数守恒：012路(除3余数) + 大中小路 的近10期强弱
     （朋友口中的"147路/258路/012路"实际是同一划分的两种叫法：
      147/258/0369 与 除3余数1/2/0 完全等价，故归并为012路；
      另补大中小路提供正交信息）
  2. 位置热码覆盖率：五码 vs 百/十/个位近10期热码的交集（命中/失手分水岭，见26204复盘）
  3. 逐号码共识度：0-9 每码多维打分 + 标签 + 冲突检测（解释层：为什么选这5个码）

诚实约束：全部输出均为"信号清晰度/结构诊断"描述，绝不承诺中奖概率。
纯计算无GUI依赖；任何异常由调用方 try/except 兜底，绝不抛入主流程。
"""
import logging

logger = logging.getLogger(__name__)

# 路数族定义：键->成员集合
ROUTE_012 = {0: [0, 3, 6, 9], 1: [1, 4, 7], 2: [2, 5, 8]}          # 除3余数(即147/258/0369)
ROUTE_BSZ = {"小": [0, 1, 2], "中": [3, 4, 5, 6], "大": [7, 8, 9]}  # 大中小


def _parse_draw(nums_str):
    """"6,7,4" -> [6,7,4]（兼容 +/- 分隔与空格）"""
    try:
        head = nums_str.split("+")[0].replace(" ", "")
        return [int(x) for x in head.split(",") if x.strip().isdigit()]
    except Exception:
        return []


class DimensionConsensus:
    """维度共识分析（福彩3D / 排列三专用）"""

    def __init__(self, lot):
        self.lot = lot

    def analyze(self, arr, five=None, kill=None, morph_suggest=None):
        """主入口

        Args:
            arr: 历史数据（旧→新顺序，Data.load 格式）
            five: 候选五码 list[int]（复式池或热号池）
            kill: 杀号集合（冲突检测用）
            morph_suggest: 形态预测文本（可选）

        Returns:
            dict: {
                "route": {...012路/对码路强弱...},
                "pos_hot": {"百": [...], "十": [...], "个": [...]},
                "five_cover": {"five": [...], "rate": float, "missing": [str], "gap_hint": str},
                "consensus": [{"digit": int, "score": int, "labels": [str], "detail": str}],
                "conflicts": [str], "suggest_top5": [int], "summary": str
            }
        """
        draws = [_parse_draw(d.get("nums", "")) for d in arr if d.get("nums")]
        draws = [d for d in draws if d]
        if len(draws) < 10:
            return {"summary": "历史不足10期，维度共识暂不可用"}

        tail = draws[-10:]
        freq10 = {n: sum(1 for dr in tail if n in dr) for n in range(10)}

        def gap_of(n):
            for g, dr in enumerate(reversed(draws)):
                if n in dr:
                    return g
            return len(draws)

        # ===== 1. 路数守恒 =====
        route = {}
        for kind, fam in (("012路", ROUTE_012), ("大中路", ROUTE_BSZ)):
            stats = {}
            for key, members in fam.items():
                stats[key] = sum(1 for dr in tail if any(n in dr for n in members))
            strong = [k for k, v in stats.items() if v >= 7]
            weak = [k for k, v in stats.items() if v <= 2]
            route[kind] = {"stats": stats, "strong": strong, "weak": weak}

        # ===== 2. 位置热码（近10期每位置频次>=2） =====
        pos_hot = {}
        for p, pn in ((0, "百"), (1, "十"), (2, "个")):
            pv = [dr[p] for dr in tail if len(dr) > p]
            from collections import Counter
            cnt = Counter(pv)
            pos_hot[pn] = sorted([n for n, c in cnt.items() if c >= 2])

        # ===== 3. 逐号码共识度打分 =====
        all_pos_hot = set(n for v in pos_hot.values() for n in v)
        strong_routes = set()
        weak_routes = set()
        for kind, fam in (("012路", ROUTE_012), ("大中路", ROUTE_BSZ)):
            for k in route[kind]["strong"]:
                strong_routes.update(fam[k])
            for k in route[kind]["weak"]:
                weak_routes.update(fam[k])

        consensus = []
        for n in range(10):
            freq = freq10[n]
            gap = gap_of(n)
            score = 50
            labels = []
            # 频次温度分
            score += freq * 6
            # 遗漏结构分：3~10期=回补窗口加分；深冷(>=13)减分
            if 3 <= gap <= 10:
                score += 8
                if freq <= 1:
                    labels.append("冷回补")
            elif gap >= 13:
                score -= 10
                labels.append("深冷")
            # 路数支撑
            if n in strong_routes:
                score += 8
                labels.append("强路")
            if n in weak_routes:
                score -= 6
            # 位置支撑
            if n in all_pos_hot:
                score += 6
                labels.append("位置热")
            # 温度标签
            if freq >= 4:
                labels.append("热共振")
            elif freq >= 2:
                labels.append("温稳")
            else:
                labels.append("低温")
            score = max(0, min(100, score))
            consensus.append({
                "digit": n, "score": score,
                "labels": labels,
                "detail": "近10期%d次/遗漏%d期" % (freq, gap),
            })

        ranking = sorted(consensus, key=lambda x: x["score"], reverse=True)
        suggest_top5 = [c["digit"] for c in ranking[:5]]

        # ===== 4. 五码位置热码覆盖率 =====
        five_cover = {"five": sorted(five) if five else None, "rate": None,
                      "missing": [], "gap_hint": ""}
        if five:
            fset = set(five)
            missing = [pn for pn, hot in pos_hot.items() if not (set(hot) & fset)]
            hit_pos = 3 - len(missing)
            five_cover["rate"] = hit_pos / 3
            five_cover["missing"] = missing
            if missing:
                five_cover["gap_hint"] = ("位置热码缺口：" + "、".join(
                    "%s位(近10期热:%s)" % (pn, ",".join(map(str, pos_hot[pn])))
                    for pn in missing))

        # ===== 5. 冲突检测 =====
        conflicts = []
        if five and kill:
            clash = sorted(fset & set(kill))
            if clash:
                conflicts.append("五码与杀号冲突: %s" % ",".join(map(str, clash)))
        if five:
            hot_cnt = sum(1 for n in five if freq10[n] >= 4)
            cold_cnt = sum(1 for n in five if freq10[n] <= 1)
            if hot_cnt >= 4:
                conflicts.append("五码过热(全部追热,建议留1个回补位)")
            if cold_cnt >= 3:
                conflicts.append("五码偏冷(3个以上低温码,命中依赖回补运气)")
            strong_in = [n for n in five if n in strong_routes]
            if not strong_in:
                conflicts.append("五码与强路无交集(路数缺口)")
            if suggest_top5 and set(suggest_top5) != fset:
                conflicts.append("共识Top5建议: %s（与当前五码不同）" % ",".join(map(str, suggest_top5)))
        if morph_suggest and "组三" in morph_suggest:
            conflicts.append("形态指向组三,五码应含重号结构")

        summary = []
        for kind, rd in route.items():
            summary.append("%s强:%s 弱:%s" % (
                kind, ",".join(map(str, rd["strong"])) or "无",
                ",".join(map(str, rd["weak"])) or "无"))
        if five_cover.get("rate") is not None:
            summary.append("位置热码覆盖率%.0f%%" % (five_cover["rate"] * 100))
        if conflicts:
            summary.append("提示:%s" % "；".join(conflicts[:2]))
        summary.append("共识Top5:%s" % ",".join(map(str, suggest_top5)))

        return {
            "route": route,
            "pos_hot": pos_hot,
            "five_cover": five_cover,
            "consensus": consensus,
            "conflicts": conflicts,
            "suggest_top5": suggest_top5,
            "summary": " | ".join(summary),
        }
