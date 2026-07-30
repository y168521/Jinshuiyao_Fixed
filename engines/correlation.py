# -*- coding: utf-8 -*-
"""金水谣系统 - 关联分析引擎 V2.0
共现条件概率矩阵 + 序列转移概率矩阵
将号码间关联信息融入选号权重"""
import os
import json
from collections import Counter, defaultdict
from utils.number_utils import parse_reds
from config import MATRIX_CACHE
from utils.locks import json_lock
from utils.safe_json import safe_load_json, safe_write_json


class CorrelationMatrix:
    def __init__(self, lot):
        self.lot = lot
        self.matrix = defaultdict(lambda: defaultdict(float))
        self.transition = defaultdict(lambda: defaultdict(float))
        self.load()

    # ───────── 共现条件概率矩阵 ─────────

    def build(self, history):
        """构建共现条件概率矩阵：P(B|A) = count(A,B) / count(A)"""
        if not history:
            return
        recent = history[-200:]
        pair = Counter()
        single = Counter()
        for d in recent:
            reds = parse_reds(d["nums"].split("+")[0])
            for r in reds:
                single[r] += 1
            for i in range(len(reds)):
                for j in range(i + 1, len(reds)):
                    a, b = reds[i], reds[j]
                    if a > b:
                        a, b = b, a
                    pair[(a, b)] += 1
        self.matrix.clear()
        for (a, b), cnt in pair.items():
            self.matrix[a][b] = cnt / max(1, single[a])
            self.matrix[b][a] = cnt / max(1, single[b])
        self.save()

    # ───────── 序列转移概率矩阵 ─────────

    def build_transition(self, history):
        """构建序列转移概率矩阵：P(本期B | 上期A)
        使用最近100期数据，统计相邻两期号码转移概率"""
        if not history or len(history) < 2:
            return
        recent = history[-101:]  # 取101期以便形成100对相邻期
        if len(recent) < 2:
            return

        # 统计上期每个号码出现的次数（分母）
        prev_count = Counter()
        # 统计上期A → 本期B的转移次数（分子）
        trans_count = defaultdict(lambda: defaultdict(int))

        for idx in range(len(recent) - 1):
            prev_reds = set(parse_reds(recent[idx]["nums"].split("+")[0]))
            curr_reds = set(parse_reds(recent[idx + 1]["nums"].split("+")[0]))
            for a in prev_reds:
                prev_count[a] += 1
                for b in curr_reds:
                    trans_count[a][b] += 1

        # 计算转移概率
        self.transition.clear()
        for a, targets in trans_count.items():
            denom = max(1, prev_count[a])
            for b, cnt in targets.items():
                self.transition[a][b] = cnt / denom

    # ───────── 转移概率加成 ─────────

    def get_transition_boost(self, last_nums, candidate):
        """计算每个候选号码基于上期号码的转移概率加成
        score(c) = sum(transition[last][c] for last in last_nums if last in transition)"""
        result = {}
        for c in candidate:
            score = 0.0
            for last in last_nums:
                if last in self.transition and c in self.transition[last]:
                    score += self.transition[last][c]
            result[c] = score
        return result

    # ───────── 共现加成 ─────────

    def get_co_occurrence_boost(self, selected, candidate):
        """计算每个候选号码与已选号码的平均共现概率
        score(c) = mean(matrix[s][c] for s in selected if s in matrix and c in matrix[s])"""
        result = {}
        for c in candidate:
            scores = []
            for s in selected:
                if s in self.matrix and c in self.matrix[s]:
                    scores.append(self.matrix[s][c])
            result[c] = sum(scores) / len(scores) if scores else 0.0
        return result

    # ───────── 综合调整权重 ─────────

    def adjust_weights(self, base_weights, last_nums=None, selected=None):
        """将转移概率加成和共现加成融入基础权重
        adjusted = base * (1 + 0.2 * transition_boost + 0.15 * co_occurrence_boost)
        """
        adjusted = dict(base_weights)

        # 转移概率加成
        if last_nums is not None and self.transition:
            candidate = list(base_weights.keys())
            tb = self.get_transition_boost(last_nums, candidate)
            for num in adjusted:
                adjusted[num] = adjusted[num] * (1.0 + 0.2 * tb.get(num, 0.0))

        # 共现加成
        if selected is not None:
            candidate = list(base_weights.keys())
            cb = self.get_co_occurrence_boost(selected, candidate)
            for num in adjusted:
                adjusted[num] = adjusted[num] * (1.0 + 0.15 * cb.get(num, 0.0))

        return adjusted

    # ───────── 查询关联号码 ─────────

    def get_related(self, num, topk=2):
        if num not in self.matrix:
            return []
        return sorted(self.matrix[num].items(), key=lambda x: x[1], reverse=True)[:topk]

    # ───────── 缓存持久化 ─────────

    def save(self):
        ser = {
            "matrix": {str(k): {str(kk): vv for kk, vv in v.items()}
                       for k, v in self.matrix.items()},
            "transition": {str(k): {str(kk): vv for kk, vv in v.items()}
                           for k, v in self.transition.items()},
        }
        with json_lock:
            safe_write_json(MATRIX_CACHE, ser)

    def load(self):
        if not os.path.exists(MATRIX_CACHE):
            return
        try:
            data = safe_load_json(MATRIX_CACHE, default={})
            # 兼容旧格式（仅有 matrix）和新格式（matrix + transition）
            self.matrix = defaultdict(lambda: defaultdict(float))
            if isinstance(data, dict) and "matrix" in data:
                for k, v in data["matrix"].items():
                    self.matrix[int(k)] = defaultdict(float, {int(kk): vv for kk, vv in v.items()})
                trans_data = data.get("transition", {})
            else:
                # 旧格式：整个data就是matrix
                for k, v in data.items():
                    self.matrix[int(k)] = defaultdict(float, {int(kk): vv for kk, vv in v.items()})
                trans_data = {}

            self.transition = defaultdict(lambda: defaultdict(float))
            for k, v in trans_data.items():
                self.transition[int(k)] = defaultdict(float, {int(kk): vv for kk, vv in v.items()})
        except Exception:
            pass
