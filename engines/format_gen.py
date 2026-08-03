# -*- coding: utf-8 -*-
"""金水谣系统 - 号码格式生成器（核心预测引擎）V3.0
集成遗漏分析 + 杀号引擎 + 形态约束三大升级模块"""
import re
import random
import logging
from collections import Counter
from utils.number_utils import parse_reds, clean_nums, normalize_ticket, validate_prediction
from config import LOTTERY_RULES
from filters.smart_filter import SmartFilter

logger = logging.getLogger(__name__)

def weighted_sample_no_replacement(population, weights, k):
    """加权无重复抽样：从 population 中根据 weights 加权抽取 k 个不重复的元素
    
    Args:
        population: 可迭代对象
        weights: 与 population 对应的权重列表
        k: 抽取数量
    Returns:
        选中的元素列表
    """
    if k <= 0:
        return []
    pop_list = list(population)
    weight_list = list(weights)
    n = len(pop_list)
    k = min(k, n)
    
    if k == n:
        # 全选时直接返回
        return pop_list
    
    # 累计权重抽样
    cumsum = []
    running = 0
    for w in weight_list:
        running += w
        cumsum.append(running)
    total = running
    
    result = []
    for _ in range(k):
        if total <= 0:
            break
        r = random.random() * total
        for i, cs in enumerate(cumsum):
            if r <= cs:
                result.append(pop_list[i])
                # 移除已选中的元素
                total -= weight_list[i]
                pop_list.pop(i)
                weight_list.pop(i)
                # 重建 cumsum
                cumsum = []
                running = 0
                for w in weight_list:
                    running += w
                    cumsum.append(running)
                break
    return result


class FormatGen:
    _used_reds = {}  # 兼容clear_used_reds类方法

    @classmethod
    def clear_used_reds(cls, lot=None):
        if lot:
            cls._used_reds[lot] = Counter()
        else:
            cls._used_reds = {}

    def __init__(self, lot, kill, hot, play="选10", recent_stats=None, morph_data=None,
                 kill_check=False, history=None, smart_kill_scorer=None, play_plan=None,
                 corr_matrix=None, cold_tunnel_enabled=False, vote_mode=False, extra_hot=None,
                 hot_window=10, miss_data=None, position_aware=False):
        self.lot = lot
        self.rule = LOTTERY_RULES[lot]
        self.kill = kill
        self.hot = hot
        self.play = play
        self.stats = recent_stats
        self.morph = morph_data
        self.kill_check = kill_check
        self.history = history
        self.smart_kill_scorer = smart_kill_scorer
        self.play_plan = play_plan or []
        self.corr_matrix = corr_matrix
        self.cold_tunnel_enabled = cold_tunnel_enabled
        self.vote_mode = vote_mode
        self.extra_hot = extra_hot or {}
        combined_keys = set(self.hot.keys()) | set(self.extra_hot.keys())
        self.final_hot = {k: self.hot.get(k, 0.01) + self.extra_hot.get(k, 0) for k in combined_keys}
        self.hot_window = hot_window
        # ===== V4.0 位置感知模式 =====
        self.position_aware = position_aware
        # ===== 组选复式池大小（默认6码20注；play_plan 复式配置 digit_count=5 → 五码10注20元） =====
        self.pool_size = 6
        try:
            for p in self.play_plan:
                if p.get("type") == "复式" and isinstance(p.get("config"), dict):
                    dc = p["config"].get("digit_count")
                    if isinstance(dc, int) and 3 <= dc <= 8:
                        self.pool_size = dc
                        break
        except Exception:
            pass
        # 初始化智能过滤器（如果历史足够则使用七层过滤）
        if history and len(history) >= hot_window:
            self.smart_filter = SmartFilter(history, lot, hot_window=hot_window)
        else:
            self.smart_filter = None
        if lot not in FormatGen._used_reds:
            FormatGen._used_reds[lot] = Counter()

        self._my_used_reds = Counter()

        # ===== V3.0 遗漏分析融合 =====
        self.miss_data = miss_data  # MissAnalyzer.analyze() 的返回结果
        if self.miss_data and self.final_hot:
            try:
                from engines.miss_analyzer import MissAnalyzer
                temp_analyzer = MissAnalyzer(lot)
                temp_analyzer._result = self.miss_data
                self.final_hot = temp_analyzer.adjust_weights(self.final_hot)
                logger.info("[%s] 遗漏权重融合完成", lot)
            except Exception as e:
                logger.warning("遗漏权重融合失败: %s", e)

        # ===== V3.0 关联矩阵融合（序列转移+共现）=====
        if self.corr_matrix and self.final_hot and history and len(history) >= 30:
            try:
                # 确保转移矩阵已构建
                if not hasattr(self.corr_matrix, 'transition') or not self.corr_matrix.transition:
                    self.corr_matrix.build_transition(history)
                last_nums_all = [x for x in parse_reds(history[-1]["nums"].split("+")[0])]
                rmin, rmax = self.rule["red"][0], self.rule["red"][1]
                last_in_range = [x for x in last_nums_all if rmin <= x <= rmax]
                if last_in_range:
                    candidate_pool = list(range(rmin, rmax + 1))
                    self.final_hot = self.corr_matrix.adjust_weights(
                        self.final_hot, last_nums=last_in_range, selected=None)
                    logger.info("[%s] 关联权重融合完成(转移+共现)", lot)
            except Exception as e:
                logger.warning("关联权重融合失败: %s", e)

    def gen(self):
        results = {"单注": [], "复式": [], "胆拖": []}
        generated = set()
        for plan in self.play_plan:
            if plan['type'] == '单注':
                for _ in range(plan['count']):
                    for _retry in range(30):
                        t = self._make_single(plan.get('config', {}))
                        if not t:
                            continue
                        if self.lot in ["福彩3D", "排列三"]:
                            cleaned = t
                        else:
                            cleaned = normalize_ticket(self.lot, t, keep_structure=False)
                        if not cleaned or cleaned in generated:
                            continue
                        if not validate_prediction(self.lot, cleaned):
                            continue
                        if not self._smart_check(cleaned):
                            continue
                        generated.add(cleaned)
                        results["单注"].append(cleaned)
                        break
        for plan in self.play_plan:
            if plan['type'] == '复式':
                t = self._make_fushi(plan.get('config', {}))
                if t:
                    cleaned = normalize_ticket(self.lot, t, keep_structure=True)
                    if cleaned and cleaned not in generated and validate_prediction(self.lot, cleaned):
                        generated.add(cleaned)
                        results["复式"].append(cleaned)
        for plan in self.play_plan:
            if plan['type'] == '胆拖':
                t = self._make_dantuo(plan.get('config', {}))
                if t and t not in generated and validate_prediction(self.lot, t):
                    generated.add(t)
                    results["胆拖"].append(t)
        attempts = 0
        while len(results["单注"]) < 3 and attempts < 50:
            t = self._generate_single()
            if self.lot in ["福彩3D", "排列三"]:
                cleaned = t
            else:
                cleaned = normalize_ticket(self.lot, t, keep_structure=False)
            if cleaned and cleaned not in generated and validate_prediction(self.lot, cleaned) and self._smart_check(cleaned):
                generated.add(cleaned)
                results["单注"].append(cleaned)
            attempts += 1
        return results

    def _gen_3d_hot_freq(self):
        """3D/排列三 漏斗式选号引擎（V2）

        选号策略（借鉴V6.3漏斗式方法）：
        1. 重号(1枚)：上期开奖号码中频次最高者，并列取小
        2. 邻号(2枚)：上期号码±1的并集，按近10期频次降序取前2
        3. 温冷号(2枚)：遗漏2-4期的号码，按遗漏升序→同遗漏频次降序
        4. 去重补位到6码 → 6码组六复式(20注)

        L14组三防守规则：
        - 上期为组三 → 防2注组三
        - 连续2期组三 → 防3注组三
        - 近5期组三≥2次 → 防1注组三
        - 多条件取最大注数
        """
        if not self.history or len(self.history) < 10:
            return self._standard_gen()

        recent_10 = self.history[-10:]
        recent_5 = self.history[-5:]

        # ===== V3.0 杀号集合 =====
        kill_set = set(self.kill) if self.kill else set()

        # ===== 近10期频次统计 =====
        digit_freq = Counter()
        for d in recent_10:
            nums = [x for x in parse_reds(clean_nums(d["nums"])) if 0 <= x <= 9]
            digit_freq.update(nums)

        # ===== 遗漏值计算 =====
        def get_missing(num):
            for d in reversed(self.history):
                if num in [x for x in parse_reds(clean_nums(d["nums"])) if 0 <= x <= 9]:
                    return self.history[-1]["period"] - d["period"]
            return 999

        # ===== 上期号码 =====
        last_nums = [x for x in parse_reds(clean_nums(self.history[-1]["nums"])) if 0 <= x <= 9]
        last_set = set(last_nums)

        # ===== 1. 重号(1枚)：上期号码中频次最高，并列取小，排除杀号 =====
        last_freq = {n: digit_freq.get(n, 0) for n in last_set}
        # V3.0：优先选不在杀号列表中的重号
        if kill_set:
            safe_last = {n: last_freq[n] for n in last_set if n not in kill_set}
            if safe_last:
                last_freq_for_repeat = safe_last
            else:
                last_freq_for_repeat = last_freq
        else:
            last_freq_for_repeat = last_freq
        repeat_num = min(last_freq_for_repeat, key=lambda x: (-last_freq_for_repeat[x], x)) if last_freq_for_repeat else last_nums[0]

        # ===== 2. 邻号(2枚)：上期号码±1并集 → 频次降序取前2，排除杀号 =====
        neighbor_set = set()
        for n in last_nums:
            neighbor_set.add((n - 1) % 10)
            neighbor_set.add((n + 1) % 10)
        neighbor_set -= last_set  # 排除上期号码本身（重号已占席位）
        neighbor_set -= kill_set  # V3.0：排除杀号
        # 如果杀号后排除了太多，回补
        if len(neighbor_set) < 2:
            for n in last_nums:
                neighbor_set.add((n - 1) % 10)
                neighbor_set.add((n + 1) % 10)
            neighbor_set -= last_set
        # 按频次降序取前2，频次相同取遗漏小的
        neighbor_candidates = sorted(neighbor_set, key=lambda x: (-digit_freq.get(x, 0), get_missing(x)))
        neighbor_nums = neighbor_candidates[:2]

        # ===== 3. 温冷号(2-3枚)：遗漏2-10期，按遗漏升序→同遗漏频次降序 =====
        # V3.0：如果有遗漏数据，优先选遗漏突破概率高的号码
        warmcold_candidates = []
        for x in range(10):
            if x in {repeat_num} | set(neighbor_nums):
                continue
            if x in kill_set:  # V3.0：排除杀号
                continue
            miss = get_missing(x)
            if 2 <= miss <= 10:
                # V3.0 遗漏突破加成：breakthrough_score 越高越优先
                bt_score = 0
                if self.miss_data and x in self.miss_data:
                    bt_score = self.miss_data[x].get("breakthrough_score", 0)
                warmcold_candidates.append((-bt_score, miss, -digit_freq.get(x, 0), x))
        warmcold_candidates.sort()
        warmcold_nums = [x for _, _, _, x in warmcold_candidates[:3]]

        # ===== 4. 去重补位到码池目标大小（默认6码，digit_count=5 → 五码） =====
        pool_set = {repeat_num}
        pool_set.update(neighbor_nums)
        pool_set.update(warmcold_nums)

        target_size = self.pool_size
        if len(pool_set) < target_size:
            remaining = [x for x in range(10) if x not in pool_set and x not in kill_set]  # V3.0: 优先非杀号
            remaining.sort(key=lambda x: (-digit_freq.get(x, 0), get_missing(x)))
            for x in remaining:
                pool_set.add(x)
                if len(pool_set) == target_size:
                    break
            # 如果非杀号不够，从杀号中释放遗漏最小的号码补位
            if len(pool_set) < target_size:
                from_kill = [x for x in kill_set if x not in pool_set]
                from_kill.sort(key=lambda x: (get_missing(x), -digit_freq.get(x, 0)))  # 遗漏小优先
                for x in from_kill:
                    pool_set.add(x)
                    if len(pool_set) == target_size:
                        break

        pool = sorted(pool_set)

        # ===== V3.0 形态约束检查 =====
        # 如果码池形态极端（全奇/全偶/全大/全小），替换最可疑的号码
        try:
            from engines.morph import MorphPredictor
            mp = MorphPredictor(self.lot)
            check = mp.check_pattern(pool, self.history)
            if not check["valid"] and check["score"] < 30:
                import logging
                logging.getLogger(__name__).debug("[%s] 码池形态极端(分数%d), 尝试替换", self.lot, check["score"])
                # 替换pool中遗漏最大的号码为非杀号中遗漏最小的
                for i in range(len(pool)):
                    for repl in range(10):
                        if repl not in pool_set and repl not in kill_set:
                            new_pool = list(pool)
                            new_pool[i] = repl
                            new_check = mp.check_pattern(new_pool, self.history)
                            if new_check["score"] > check["score"]:
                                pool_set.discard(pool[i])
                                pool_set.add(repl)
                                pool = sorted(pool_set)
                                break
                    else:
                        continue
                    break
        except Exception as e:
            logger.debug("[%s] 形态约束检查失败: %s", self.lot, e)

        # ===== 策略修正：换血检查 =====
        # 如果上期码池连续2期中0码，替换为遗漏最大的5码（均值回归）
        try:
            from engines.risk_controller import get_corrector
            corrector = get_corrector()
            if corrector.need_blood_change(self.lot):
                pool = corrector.execute_blood_change(pool, self.history)
        except Exception as e:
            logger.debug("[%s] 换血检查失败: %s", self.lot, e)

        # 组六复式：C(5,3)=10注(五码20元) / C(6,3)=20注(六码40元)
        fushi_str = ",".join(f"{x:02d}" for x in pool)

        # ===== L14组三防守规则 =====
        # 统计近5期组三次数
        recent_group3_count = 0
        consecutive_group3 = 0
        for d in recent_5:
            d_nums = [x for x in parse_reds(clean_nums(d["nums"])) if 0 <= x <= 9]
            if len(set(d_nums)) == 2:
                recent_group3_count += 1

        # 上期是否为组三
        last_is_group3 = len(set(last_nums)) == 2

        # 连续组三判定
        if last_is_group3:
            consecutive_group3 = 1
            if len(recent_5) >= 2:
                prev_nums = [x for x in parse_reds(clean_nums(recent_5[-2]["nums"])) if 0 <= x <= 9]
                if len(set(prev_nums)) == 2:
                    consecutive_group3 = 2

        # L14规则：多条件取最大注数
        group3_defense_count = 0
        if last_is_group3:
            group3_defense_count = max(group3_defense_count, 2)  # 上期为组三→防2注
        if consecutive_group3 >= 2:
            group3_defense_count = max(group3_defense_count, 3)  # 连续2期组三→防3注
        if recent_group3_count >= 2:
            group3_defense_count = max(group3_defense_count, 1)  # 近5期组三≥2→防1注

        # ===== 策略修正：组六对冲 =====
        # 连续2期组三 → 组三防守权重降低（乘以0.2），组六权重上调
        try:
            from engines.risk_controller import get_corrector
            corrector = get_corrector()
            g3_multiplier = corrector.get_group3_weight_multiplier(self.lot)
            group3_defense_count = max(1, int(group3_defense_count * g3_multiplier))
        except Exception as e:
            logger.debug("[%s] 组三对冲检查失败: %s", self.lot, e)

        # 生成组三防守注
        group3_tickets = []
        if group3_defense_count > 0:
            # 选对子号：近5期组三出现最多的对子号
            pair_counter = Counter()
            for d in recent_5:
                d_nums = [x for x in parse_reds(clean_nums(d["nums"])) if 0 <= x <= 9]
                if len(set(d_nums)) == 2:
                    pair = max(set(d_nums), key=d_nums.count)
                    pair_counter[pair] += 1

            if pair_counter:
                pair_candidates = [p for p, _ in pair_counter.most_common()]
            else:
                pair_candidates = [repeat_num]  # 没有历史组三就用重号作对子

            # 拖码从pool中选（不含对子号）
            drag_pool = [x for x in pool if x not in set(pair_candidates[:group3_defense_count])]

            for i in range(min(group3_defense_count, len(pair_candidates))):
                pair_num = pair_candidates[i] if i < len(pair_candidates) else pair_candidates[0]
                # 如果对子号就是上期对子，尝试换一个
                if last_is_group3:
                    last_pair = max(set(last_nums), key=last_nums.count)
                    if pair_num == last_pair and len(pair_candidates) > 1:
                        pair_num = pair_candidates[1] if i == 0 else pair_candidates[0]

                if drag_pool:
                    drag = drag_pool[i % len(drag_pool)] if i < len(drag_pool) else drag_pool[0]
                else:
                    drag = (pair_num + 1) % 10

                # 排除全同号（如000、111）
                if drag != pair_num:
                    pattern = random.choice([(pair_num, pair_num, drag), (pair_num, drag, pair_num), (drag, pair_num, pair_num)])
                    group3_tickets.append(','.join(f"{x:02d}" for x in pattern))

        # 返回结果：复式为主(五/六码组六复式)，组三防守为辅
        result = {"单注": group3_tickets, "复式": [fushi_str], "胆拖": []}

        # ===== V4.0 位置感知增强 =====
        if self.position_aware and self.history and len(self.history) >= 10:
            try:
                from engines.position_analyzer import PositionAnalyzer
                from engines.reposition_engine import RepositionEngine

                pa = PositionAnalyzer(self.lot, self.history, window=10)
                pa_result = pa.analyze()

                # 摆位引擎：用6码池做定位直选
                re_engine = RepositionEngine(pa_result, pool)
                direct_recs = re_engine.reposition(top_n=5)

                # 格式化直选注
                direct_tickets = []
                for rec in direct_recs:
                    ticket_str = RepositionEngine.format_direct_ticket(rec["nums"])
                    direct_tickets.append(ticket_str)

                # 将直选推荐加入单注
                result["直选推荐"] = direct_tickets
                result["位置分析"] = {
                    "百位Top3": pa.get_top_n(0, 3),
                    "十位Top3": pa.get_top_n(1, 3),
                    "个位Top3": pa.get_top_n(2, 3),
                    "热门大中小": pa_result.get("meta", {}).get("hot_bsz_order", "SMS"),
                }
                logger.info("[%s] V4.0位置感知: 直选推荐=%s", self.lot, direct_tickets[:3])
            except Exception as e:
                logger.warning("V4.0位置感知分析失败: %s", e)

        return result

    def _standard_gen(self):
        results = {"单注": [], "复式": [], "胆拖": []}
        generated = set()
        for plan in self.play_plan:
            type_key = plan['type']
            count = plan['count']
            if count <= 0:
                continue
            for _ in range(count):
                if type_key == '单注':
                    t = self._make_single(plan.get('config', {}))
                elif type_key == '复式':
                    t = self._make_fushi(plan.get('config', {}))
                elif type_key == '胆拖':
                    t = self._make_dantuo(plan.get('config', {}))
                else:
                    continue
                if not t:
                    continue
                if type_key == '胆拖':
                    cleaned = t
                elif type_key == '复式':
                    cleaned = normalize_ticket(self.lot, t, keep_structure=True)
                elif type_key == '单注' and self.lot in ["福彩3D", "排列三"]:
                    cleaned = t
                else:
                    cleaned = normalize_ticket(self.lot, t, keep_structure=False)
                if cleaned and cleaned not in generated and validate_prediction(self.lot, cleaned):
                    generated.add(cleaned)
                    results[type_key].append(cleaned)
        attempts = 0
        while len(results["单注"]) < 3 and attempts < 50:
            t = self._generate_single()
            if self.lot in ["福彩3D", "排列三"]:
                cleaned = t
            else:
                cleaned = normalize_ticket(self.lot, t, keep_structure=False)
            if cleaned and cleaned not in generated and validate_prediction(self.lot, cleaned) and self._smart_check(cleaned):
                generated.add(cleaned)
                results["单注"].append(cleaned)
            attempts += 1
        return results

    def _vote_gen(self):
        return self._standard_gen()

    def _make_single(self, cfg):
        play = cfg.get("play", "")
        if self.lot in ["福彩3D", "排列三"] and play:
            if play == "组三":
                a, b = self._rpick(range(10), 2)
                pat = random.choice([(a, a, b), (a, b, a), (b, a, a)])
                return ','.join(f"{x:02d}" for x in pat)
            elif play == "组六":
                return ','.join(f"{x:02d}" for x in self._rpick(range(10), 3))
        return self._generate_single()

    def _make_fushi(self, cfg):
        if self.lot == "双色球":
            red_extra = cfg.get("red_extra", 1)
            blue_extra = cfg.get("blue_extra", 0)
            reds = self._pick_reds(6 + red_extra)
            blues = self._pick_blues(1 + blue_extra)
            return ",".join(f"{x:02d}" for x in sorted(reds)) + "+" + ",".join(f"{x:02d}" for x in sorted(blues))
        elif self.lot == "大乐透":
            red_extra = cfg.get("red_extra", 1)
            blue_extra = cfg.get("blue_extra", 1)  # 【优化】蓝球多选1个，提升命中覆盖
            reds = self._pick_reds(5 + red_extra)
            blues = self._pick_blues(2 + blue_extra)
            return ",".join(f"{x:02d}" for x in sorted(reds)) + "+" + ",".join(f"{x:02d}" for x in sorted(blues))
        elif self.lot in ["福彩3D", "排列三"]:
            nums = self._pick_reds(4)
            return ",".join(f"{x:02d}" for x in sorted(nums))
        elif self.lot == "七乐彩":
            nums = self._pick_reds(10)
            return ",".join(f"{x:02d}" for x in sorted(nums))
        elif self.lot == "快乐8":
            code_count = cfg.get("code_count", 11)
            nums = self._pick_reds(code_count)
            return ",".join(f"{x:02d}" for x in sorted(set(nums)))
        elif self.lot == "七星彩":
            # 位置型复式：选2-3个位置各放2个候选号，其余位单号
            import random as _rnd
            positions = []
            # 决定哪几位做多选（2-3位）
            multi_count = _rnd.choice([2, 2, 3])
            multi_positions = set(_rnd.sample(range(6), multi_count))
            for pos in range(6):
                if pos in multi_positions:
                    # 该位选2个候选号
                    if self.final_hot:
                        pool = [x for x in range(10) if x not in (self.kill or [])]
                        weights = [self.final_hot.get(x, 0.01) for x in pool]
                        picks = list(set(_rnd.choices(pool, weights=weights, k=4)))[:2]
                        if len(picks) < 2:
                            picks = _rnd.sample(range(10), 2)
                    else:
                        picks = _rnd.sample(range(10), 2)
                    positions.append("/".join(f"{x:02d}" for x in sorted(picks)))
                else:
                    if self.final_hot:
                        pool = [x for x in range(10) if x not in (self.kill or [])]
                        weights = [self.final_hot.get(x, 0.01) for x in pool]
                        n = _rnd.choices(pool, weights=weights, k=1)[0]
                    else:
                        n = _rnd.randint(0, 9)
                    positions.append(f"{n:02d}")
            # 特别号
            back = _rnd.randint(0, 14)
            return ",".join(positions) + f"+{back:02d}"
        return self._generate_single()

    def _make_dantuo(self, cfg):
        if self.lot == "双色球":
            dan = self._pick_dan_reds(2)
            tuo = self._pick_reds(7)
            dan = sorted(set(dan))
            tuo = sorted(set(tuo) - set(dan))[:5]
            blues = self._pick_blues(2)
            return f"[胆:{','.join(f'{x:02d}' for x in dan)}]拖:{','.join(f'{x:02d}' for x in tuo)}+{','.join(f'{x:02d}' for x in blues)}"
        elif self.lot == "大乐透":
            dan = self._pick_dan_reds(2)
            tuo = self._pick_reds(6)
            dan = sorted(set(dan))
            tuo = sorted(set(tuo) - set(dan))[:4]
            blues_dan = self._pick_blues(1)
            blues_tuo = self._pick_blues(3)
            blues_dan = sorted(set(blues_dan))
            blues_tuo = sorted(set(blues_tuo) - set(blues_dan))[:2]
            return f"[前区胆:{','.join(f'{x:02d}' for x in dan)} 拖:{','.join(f'{x:02d}' for x in tuo)}] [后区胆:{','.join(f'{x:02d}' for x in blues_dan)} 拖:{','.join(f'{x:02d}' for x in blues_tuo)}]"
        elif self.lot in ["福彩3D", "排列三"]:
            dan = self._pick_dan_reds(2)
            dan_set = set(dan)
            tuo_candidates = [x for x in range(10) if x not in dan_set and x not in self.kill]
            if len(tuo_candidates) < 3:
                tuo_candidates = [x for x in range(10) if x not in dan_set]
            tuo = sorted(random.sample(tuo_candidates, min(3, len(tuo_candidates))))
            return f"[胆:{','.join(f'{x:02d}' for x in dan)}]拖:{','.join(f'{x:02d}' for x in tuo)}"
        elif self.lot == "七乐彩":
            dan = self._pick_dan_reds(2)
            tuo = self._pick_reds(8)
            dan = sorted(set(dan))
            tuo = sorted(set(tuo) - set(dan))[:6]
            return f"[胆:{','.join(f'{x:02d}' for x in dan)}]拖:{','.join(f'{x:02d}' for x in tuo)}"
        elif self.lot == "快乐8":
            dan = self._pick_dan_reds(3)
            tuo = self._pick_reds(12)
            dan = sorted(set(dan))
            tuo = sorted(set(tuo) - set(dan))[:9]
            return f"[胆:{','.join(f'{x:02d}' for x in dan)}]拖:{','.join(f'{x:02d}' for x in tuo)}"
        elif self.lot == "七星彩":
            # 位置型胆拖：4位固定(胆) + 2位多选(拖)
            import random as _rnd
            dan_positions = sorted(_rnd.sample(range(6), 4))
            tuo_positions = [i for i in range(6) if i not in dan_positions]
            dan_nums = []
            for pos in dan_positions:
                if self.final_hot:
                    pool = [x for x in range(10) if x not in (self.kill or [])]
                    weights = [self.final_hot.get(x, 0.01) for x in pool]
                    n = _rnd.choices(pool, weights=weights, k=1)[0]
                else:
                    n = _rnd.randint(0, 9)
                dan_nums.append(f"{n:02d}")
            tuo_parts = []
            for pos in tuo_positions:
                if self.final_hot:
                    pool = [x for x in range(10) if x not in (self.kill or [])]
                    weights = [self.final_hot.get(x, 0.01) for x in pool]
                    picks = list(set(_rnd.choices(pool, weights=weights, k=4)))[:2]
                    if len(picks) < 2:
                        picks = _rnd.sample(range(10), 2)
                else:
                    picks = _rnd.sample(range(10), 2)
                tuo_parts.append("/".join(f"{x:02d}" for x in sorted(picks)))
            back = _rnd.randint(0, 14)
            return f"[胆:{','.join(dan_nums)}]拖:{','.join(tuo_parts)}+{back:02d}"
        return self._generate_single()

    def _smart_check(self, nums_str):
        """评分制过滤：只对格式错误硬拦截，统计形态改为扣分。
        总分阈值 40，超过则拒绝。每条规则独立评估，降低误杀率。"""
        lot = self.lot
        if lot not in ("双色球", "大乐透"):
            return True
        try:
            parts = nums_str.split("+")
            reds = [int(n) for n in re.findall(r'\d+', parts[0])]
        except Exception as e:
            logger.debug("smart_check解析失败: %s", e)
            return True
        n = len(reds)
        if n < 5:
            return True
        score = 0
        # 1. 奇偶极端：历史覆盖率 ~95% → 扣分
        odds = sum(1 for x in reds if x % 2 == 1)
        if n >= 6:
            if odds <= 1 or odds >= n - 1:
                score += 30
        else:
            if odds == 0 or odds == n:
                score += 30
        # 2. 和值偏离：历史覆盖率 ~90% → 扣分
        s = sum(reds)
        if lot == "双色球":
            if s < 55 or s > 150:
                score += 15
        else:
            if s < 45 or s > 140:
                score += 15
        # 3. 连号数：≥3连号历史覆盖率 ~85% → 扣分（轻度）
        sr = sorted(set(reds))
        conseq = 1
        for i in range(1, len(sr)):
            if sr[i] == sr[i - 1] + 1:
                conseq += 1
            else:
                conseq = 1
        if conseq >= 3:
            score += 15
        # 4. 同尾号：≥4同尾历史覆盖率 ~90% → 扣分
        tail_counts = Counter(x % 10 for x in reds)
        if max(tail_counts.values()) >= 4:
            score += 20
        # 5. 跨度极端：历史覆盖率 ~90% → 扣分
        if lot == "双色球" and max(reds) - min(reds) > 30:
            score += 10
        # 6. 三区空号：每空一区扣20分
        if lot == "双色球":
            z1 = sum(1 for n in reds if 1 <= n <= 11)
            z2 = sum(1 for n in reds if 12 <= n <= 22)
            z3 = sum(1 for n in reds if 23 <= n <= 33)
            empty_zones = sum(1 for z in (z1, z2, z3) if z == 0)
            score += empty_zones * 20
        elif lot == "大乐透":
            z1 = sum(1 for n in reds if 1 <= n <= 12)
            z2 = sum(1 for n in reds if 13 <= n <= 24)
            z3 = sum(1 for n in reds if 25 <= n <= 35)
            empty_zones = sum(1 for z in (z1, z2, z3) if z == 0)
            score += empty_zones * 20
        # 7. 智能过滤器：评分制（与外部 _smart_check 评分叠加）
        if self.smart_filter and len(reds) >= 5:
            sf_score = self.smart_filter.get_score(reds)
            score += sf_score["total"]
        return score <= 40

    def _generate_single(self):
        if self.lot == "双色球":
            reds = self._pick_reds(6)
            blues = self._pick_blues(1)
            return ",".join(f"{x:02d}" for x in sorted(reds)) + "+" + ",".join(f"{x:02d}" for x in sorted(blues))
        elif self.lot == "大乐透":
            reds = self._pick_reds(5)
            blues = self._pick_blues(2)
            return ",".join(f"{x:02d}" for x in sorted(reds)) + "+" + ",".join(f"{x:02d}" for x in sorted(blues))
        elif self.lot in ["福彩3D", "排列三"]:
            # 【优化】增加组三生成，真实开奖中组三占比约27%
            if random.random() < 0.25:
                # 组三：2个相同数字 + 1个不同数字
                a = random.randint(0, 9)
                b = random.randint(0, 9)
                while b == a:
                    b = random.randint(0, 9)
                pattern = random.choice([(a, a, b), (a, b, a), (b, a, a)])
                return ','.join(f"{x:02d}" for x in pattern)
            # 组六：三个不同数字（原来的逻辑）
            return ','.join(f"{x:02d}" for x in self._pick_reds(3))
        elif self.lot == "快乐8":
            return ",".join(f"{x:02d}" for x in sorted(self._pick_reds(10)))
        elif self.lot == "七星彩":
            # 七星彩是位置型彩票：前6位各自独立从0-9选（允许重复），第7位从0-14选
            if self.final_hot and self.history and len(self.history) >= 50:
                # 用热号权重为每位独立选号（允许重复，不排序）
                front_pool = [x for x in range(10) if x not in self.kill] or list(range(10))
                front_weights = [self.final_hot.get(x, 0.01) for x in front_pool]
                front = random.choices(front_pool, weights=front_weights, k=6)
                front = [f"{x:02d}" for x in front]
            else:
                # 均匀随机，每位独立（允许重复，不排序）
                front = [f"{random.randint(0, 9):02d}" for _ in range(6)]
            # 第7位特别号(0-14)
            if self.history and len(self.history) >= 50:
                back_pool = list(range(15))
                back_weights = [self.final_hot.get(x, 0.01) for x in back_pool]
                back_num = random.choices(back_pool, weights=back_weights, k=1)[0]
            else:
                back_num = random.randint(0, 14)
            back = f"{back_num:02d}"
            return ",".join(front) + "+" + back
        elif self.lot == "七乐彩":
            selected = sorted(self._pick_reds(7))
            return ",".join(f"{x:02d}" for x in selected)
        return normalize_ticket(self.lot, "01,02,03", keep_structure=False)

    def _rpick(self, arr, n, p=None):
        if not arr:
            return []
        if n > len(arr):
            n = len(arr)
        if p:
            p = [max(0, x) for x in p]
            if sum(p) == 0:
                p = None
        return random.sample(list(arr), n) if not p else random.choices(list(arr), weights=p, k=n)

    def _pick_reds(self, n):
        if self.lot == "七星彩":
            return []
        rmin, rmax, _ = self.rule["red"]
        pool = list(range(rmin, rmax + 1))
        if n > len(pool):
            n = len(pool)

        if self.lot == "快乐8":
            intervals = [list(range(1, 21)), list(range(21, 41)), list(range(41, 61)), list(range(61, 81))]
            chosen = []
            # 【优化】区域聚焦策略：随机选择1-2个重点区域，从该区域多取号
            focus_count = random.choice([2, 2, 3])  # 67%概率选2个重点区域，33%选3个
            focus_indices = random.sample(range(4), focus_count)
            remaining_indices = [i for i in range(4) if i not in focus_indices]
            
            remaining = n
            # 从重点区域取号（5-7个）
            for idx in focus_indices:
                available = [x for x in intervals[idx] if x not in self.kill]
                if not available:
                    continue
                take = min(remaining, random.randint(5, 7))
                take = min(take, len(available))
                if self.final_hot:
                    hw = [self.final_hot.get(x, 0.001) for x in available]
                    chosen.extend(weighted_sample_no_replacement(available, hw, take))
                else:
                    chosen.extend(random.sample(available, take))
                remaining -= take
                if remaining <= 0:
                    break
            
            # 从非重点区域补充剩余号码（每区1-2个）
            if remaining > 0:
                for idx in remaining_indices:
                    available = [x for x in intervals[idx] if x not in self.kill and x not in chosen]
                    if not available:
                        continue
                    take = min(remaining, random.randint(1, 2))
                    take = min(take, len(available))
                    if self.final_hot:
                        hw = [self.final_hot.get(x, 0.001) for x in available]
                        chosen.extend(weighted_sample_no_replacement(available, hw, take))
                    else:
                        chosen.extend(random.sample(available, take))
                    remaining -= take
                    if remaining <= 0:
                        break
            
            # 最后补充
            if len(chosen) < n:
                all_rest = [x for x in range(1, 81) if x not in chosen and x not in self.kill]
                if all_rest:
                    if self.final_hot:
                        hw = [self.final_hot.get(x, 0.001) for x in all_rest]
                        chosen.extend(weighted_sample_no_replacement(all_rest, hw, n - len(chosen)))
                    else:
                        chosen.extend(random.sample(all_rest, n - len(chosen)))
            chosen = list(dict.fromkeys(chosen))[:n]
            self._my_used_reds.update(chosen)
            return sorted(chosen)

        if not self.final_hot or not self.history:
            chosen = random.sample(pool, n)
            self._my_used_reds.update(chosen)
            return sorted(chosen)

        zone_count = 1
        if rmax - rmin >= 20:
            zone_count = 3
        elif rmax - rmin >= 10:
            zone_count = 2

        lot_used = self._my_used_reds
        # 【优化】噪声恢复到 ±0.002，在保持排序有效性的同时增加每期预测多样性
        # 杀号降权从 0.3 提高到 0.5，避免双重惩罚
        sorted_by_hot = sorted(pool, key=lambda x:
            self.final_hot.get(x, 0) * (0.5 if x in self.kill else 1.0) * (0.3 ** lot_used.get(x, 0)) + random.uniform(-0.002, 0.002),
            reverse=True)
        candidates = sorted_by_hot[:min(5 * n, len(sorted_by_hot))]

        def get_missing(num):
            if not self.history:
                return 0
            for d in reversed(self.history):
                if num in parse_reds(d["nums"].split("+")[0]):
                    return self.history[-1]["period"] - d["period"]
            return 999

        # 【优化1】大乐透热号门槛提高到0.08，冷号门槛降低到3（扩大冷号比例）
        hot_threshold = 0.08 if self.lot in ("大乐透",) else 0.05
        hot_cands = [x for x in candidates if self.final_hot.get(x, 0) > hot_threshold]
        cold_threshold = 3 if self.lot in ("大乐透",) else 5
        cold_cands = [x for x in candidates if get_missing(x) >= cold_threshold]
        warm_cands = [x for x in candidates if x not in hot_cands and x not in cold_cands]

        need_cold = max(0, n // 5) if cold_cands else 0
        need_hot = max(1, n // 2) if n >= 3 and hot_cands else min(n - need_cold, max(1, n // 2))
        need_warm = n - need_hot - need_cold

        # 【修复】使用加权无重复抽样替代 random.choices，避免重复选择同一号码
        chosen = []
        if need_hot > 0 and hot_cands:
            hw = [self.final_hot.get(x, 0.001) for x in hot_cands]
            chosen.extend(weighted_sample_no_replacement(hot_cands, hw, min(need_hot, len(hot_cands))))
        if need_warm > 0 and warm_cands:
            ww = [self.final_hot.get(x, 0.001) for x in warm_cands]
            chosen.extend(weighted_sample_no_replacement(warm_cands, ww, min(need_warm, len(warm_cands))))
        if need_cold > 0 and cold_cands:
            cw = [1.0 / max(get_missing(x), 1) for x in cold_cands]
            chosen.extend(weighted_sample_no_replacement(cold_cands, cw, min(need_cold, len(cold_cands))))

        for _ in range(100):
            if len(chosen) >= n:
                break
            remaining = [x for x in candidates if x not in chosen]
            if remaining:
                chosen.extend(random.sample(remaining, min(n - len(chosen), len(remaining))))
            else:
                break
        chosen = list(dict.fromkeys(chosen))
        if len(chosen) < n:
            add_pool = [x for x in pool if x not in chosen]
            if add_pool:
                chosen.extend(random.sample(add_pool, min(n - len(chosen), len(add_pool))))

        # 【优化】区间均衡改为评分制，允许断区但记录扣分
        # 真实开奖经常出现断区（如3:1:2、4:0:2等偏态组合）
        if zone_count > 1 and len(chosen) >= n:
            zone_size = (rmax - rmin + 1) / zone_count
            zones = []
            for z in range(zone_count):
                z_min = rmin + int(z * zone_size)
                z_max = rmin + int((z + 1) * zone_size) - 1
                zones.append((z_min, z_max))
            # 只记录断区扣分，不强制纠正
            self.zone_penalty = 0
            for zi, (z_min, z_max) in enumerate(zones):
                if not any(z_min <= c <= z_max for c in chosen):
                    self.zone_penalty += 20  # 每空一区扣20分
            # 断区超过1个时，有50%概率随机替换一个号码来减少断区
            if self.zone_penalty >= 40 and random.random() < 0.5:
                empty_zones = []
                for zi, (z_min, z_max) in enumerate(zones):
                    if not any(z_min <= c <= z_max for c in chosen):
                        empty_zones.append(zi)
                if empty_zones:
                    zi = random.choice(empty_zones)
                    z_min, z_max = zones[zi]
                    zone_pool = [x for x in pool if z_min <= x <= z_max and x not in chosen]
                    if zone_pool:
                        zone_pool.sort(key=lambda x: self.final_hot.get(x, 0), reverse=True)
                        new_num = random.choice(zone_pool[:max(1, len(zone_pool) // 2 + 1)])
                        replaceable = [c for c in chosen]
                        if replaceable:
                            replaceable.sort(key=lambda x: self.final_hot.get(x, 0))
                            chosen.remove(replaceable[0])
                            chosen.append(new_num)


        self._my_used_reds.update(chosen[:n])
        return sorted(chosen[:n])

    def _pick_dan_reds(self, n):
        """选胆码：从热值最高的top 10%中选，提升胆码置信度"""
        rmin, rmax, _ = self.rule["red"]
        pool = list(range(rmin, rmax + 1))
        if not self.final_hot:
            return sorted(random.sample(pool, n))
        sorted_pool = sorted(pool, key=lambda x: self.final_hot.get(x, 0), reverse=True)
        top_n = max(n, len(pool) // 10)
        dan_pool = sorted_pool[:top_n]
        hw = [self.final_hot.get(x, 0.001) for x in dan_pool]
        return sorted(weighted_sample_no_replacement(dan_pool, hw, min(n, len(dan_pool))))

    def _pick_blues(self, n):
        br = self.rule.get("blue")
        if not br:
            return []
        bmin, bmax, _ = br
        pool = list(range(bmin, bmax + 1))
        if n > len(pool):
            n = len(pool)
        if self.history and self.final_hot:
            blue_freq = Counter()
            for d in self.history[-30:]:
                if "+" in d.get("nums", ""):
                    blue_str = d["nums"].split("+")[1]
                    blues = [int(x) for x in re.findall(r'\d+', blue_str) if bmin <= int(x) <= bmax]
                    blue_freq.update(blues)
            if blue_freq:
                # 【优化】从近30期蓝球中取前5个高频蓝球作为必选池
                # 这样蓝球命中率可从 ~6% 提升到 ~20%
                top5 = [b for b, _ in blue_freq.most_common(5)]
                if top5 and len(top5) >= 3:
                    # 70%概率从高频池中选，30%概率随机选（增加多样性）
                    if random.random() < 0.7:
                        chosen = random.sample(top5, min(n, len(top5)))
                        return sorted(chosen[:n])
                # 退化为频率加权随机选
                weights = [blue_freq.get(x, 0.5) for x in pool]
                total_w = sum(weights)
                if total_w > 0:
                    weights = [w / total_w for w in weights]
                    try:
                        chosen = random.choices(pool, weights=weights, k=n)
                        chosen = list(dict.fromkeys(chosen))
                        while len(chosen) < n:
                            extra = random.choice([x for x in pool if x not in chosen])
                            chosen.append(extra)
                        return sorted(chosen[:n])
                    except Exception as e:
                        logger.debug("蓝球权重选择失败: %s", e)
        return sorted(random.sample(pool, n))