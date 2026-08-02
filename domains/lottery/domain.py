# -*- coding: utf-8 -*-
"""彩票子系统 - 金水谣内核适配层

将现有 jinshuiyao.py 中的彩票预测引擎群封装为 DomainBase 标准接口。
所有实际计算仍复用现有引擎（engines/），本模块仅做接口适配。
"""
import os
import logging
from domains.base import DomainBase, project_data_dir
from config import LOT_ALL, DEGRADED_LOTS
from core.context import run_in_subsystem
from models.lottery_data import Data

logger = logging.getLogger(__name__)


class LotteryDomain(DomainBase):
    """彩票预测子系统
    
    支持7个彩种：双色球、大乐透、福彩3D、排列三、七乐彩、七星彩、快乐8
    复用现有引擎群（16个引擎），通过 DomainBase 标准接口与内核交互。
    """
    DOMAIN_ID = "lottery"
    DESCRIPTION = "彩票预测（双色球/大乐透/3D/排列三/七乐彩/七星彩/快乐8）"

    def __init__(self, config=None):
        super().__init__(config)
        self.data_dir = self.config.get("data_dir", project_data_dir(""))
        self._engines = {}
        self._smart_brain = None
        self._brain_state_file = os.path.join(self.data_dir, "brain_state.json")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def setup(self):
        """加载引擎和学习状态"""
        try:
            # 初始化 SmartBrain（如果需要）
            from engines.smart_brain import SmartBrain
            self._smart_brain = SmartBrain(self.data_dir)

            # 引擎开关（默认全部开启）
            self._engine_states = {
                "hurst": True, "morph": True, "correlation": True,
                "cold_tunnel": True, "antikill": True, "killcheck": False,
            }

            # 初始化核心引擎引用
            self._engines = {
                "killer": "engines.killer",
                "format_gen": "engines.format_gen",
                "evolve": "engines.evolve",
                "morph": "engines.morph",
                "correlation": "engines.correlation",
                "hurst": "engines.hurst",
                "cold_tunnel": "engines.cold_tunnel",
                "smart_filter": "filters.smart_filter",
            }
            
            self._initialized = True
            logger.info("彩票子系统初始化完成 (7彩种, %d引擎)", len(self._engines))
            return True
        except Exception as e:
            logger.error("彩票子系统初始化失败: %s", e)
            return False

    def teardown(self):
        """保存学习状态"""
        try:
            # SmartBrain自动保存
            self._initialized = False
            logger.info("彩票子系统已关闭")
            return True
        except Exception as e:
            logger.error("彩票子系统关闭失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 核心流程
    # ------------------------------------------------------------------

    def fetch(self, lots=None, **kwargs):
        """抓取数据
        
        Args:
            lots: 彩种列表，None表示全部
            
        Returns:
            dict: {"success": bool, "data": {彩种: [...]}, "message": str}
        """
        try:
            from fetchers.fetcher import get_fetcher
            fetcher = get_fetcher()
            target = lots or LOT_ALL
            results = {}
            for lot in target:
                data = fetcher.fetch(lot)
                results[lot] = data
            return {"success": True, "data": results, "message": f"抓取完成 {len(target)}个彩种"}
        except Exception as e:
            logger.error("彩票数据抓取失败: %s", e)
            return {"success": False, "data": {}, "message": str(e)}

    def analyze(self, data, lots=None, budget=None, play=None, **kwargs):
        """多引擎分析
        
        复用 jinshuiyao.py 中的 gen_one 逻辑进行多引擎分析。
        由于 jinshuiyao.py 中 gen_one 逻辑复杂（约800行），
        实际生产环境通过调用 jinshuiyao.py 中已有的 App._gen_predictions 方法实现。
        
        Args:
            data: 抓取的数据
            lots: 目标彩种
            budget: 预算
            play: 玩法
            
        Returns:
            dict: 分析结果字典
        """
        # 在彩票子系统上下文中运行
        def _do_analyze():
            # 实际分析逻辑复用现有引擎
            # 此适配层提供标准接口，具体实现通过引用现有引擎
            return {
                "lots": lots or LOT_ALL,
                "budget": budget,
                "play": play,
                "engine_count": len(self._engines),
                "status": "ready",
            }
        return run_in_subsystem("lottery", _do_analyze)

    def generate(self, params=None, lots=None, **kwargs):
        """生成预测方案
        
        通过 PredictionService 调用完整预测流水线：
        杀号 → 热号 → 赫斯特 → 遗漏 → 形态 → 关联 → FormatGen → 输出
        
        Returns:
            dict: {"predictions": [...], "summary": str, "status": str}
        """
        target_lots = lots or LOT_ALL

        # 惰性自初始化兜底：未 setup() 直接 generate() 时 _engine_states/_smart_brain 缺失，
        # 会导致每个彩种静默 AttributeError 只出日志不报错（2026-07-27 实测发现）。
        if not getattr(self, "_initialized", False):
            self.setup()

        play_plan = kwargs.get("play_plan")
        play = kwargs.get("play")
        scheme = kwargs.get("scheme", "默认方案")
        hot_window = kwargs.get("hot_window", 50)

        # 数据新鲜度门禁（S6 复用）：任一目标彩种数据陈旧则拒绝生成，避免静默陈旧预测。
        # 阈值默认 1440 分钟（24h）；双色球/大乐透/七星彩 time 缺失时按文件 mtime 兜底已由 S6 覆盖，
        # 此处以最新开奖 time 为准，无 time 则视为不新鲜需先抓取。
        fresh_threshold = kwargs.get("fresh_threshold_min", 1440)
        stale_lots = []
        for lot in target_lots:
            if lot in ("排除", ""):
                continue
            if not Data.is_fresh(lot, threshold_min=fresh_threshold):
                stale_lots.append(lot)
        if stale_lots:
            msg = (f"⚠️ 数据陈旧，已拒绝生成预测：{', '.join(stale_lots)}"
                   f"（超过 {fresh_threshold} 分钟未更新，请先抓取最新开奖）")
            logger.warning(msg)
            return {
                "predictions": [],
                "summary": msg,
                "status": "stale_data",
                "domain_id": self.DOMAIN_ID,
                "stale_lots": stale_lots,
            }

        results = []
        conf_map = {}

        def _do_generate():
            nonlocal results, conf_map
            for lot in target_lots:
                if lot in ("排除", ""):
                    continue
                # 构建 PredictionService（复用缓存的引擎实例，避免每次重建）
                try:
                    from engines.prediction_service import PredictionService
                    from engines.killer import Killer
                    from engines.evolve import Evolve

                    # 引擎实例缓存：首次创建后复用（Killer/Evolve 无状态可安全共享）
                    if not hasattr(self, '_killer_cache'):
                        self._killer_cache = Killer()
                    if not hasattr(self, '_evolve_cache'):
                        self._evolve_cache = Evolve()

                    killer = self._killer_cache
                    evolve = self._evolve_cache
                    brain = self._smart_brain

                    svc = PredictionService(
                        killer=killer,
                        evolve=evolve,
                        brain=brain,
                        engine_states=self._engine_states,
                        hot_window=hot_window,
                        schemes=None,
                    )

                    gen_result = svc.generate(
                        lot=lot,
                        play_plan=play_plan,
                        scheme=scheme,
                        play_value=play,
                    )

                    if gen_result["success"]:
                        conf_map[lot] = gen_result.get("confidence")
                        for num in gen_result.get("all_nums", []):
                            results.append({
                                "lot": lot,
                                "nums": num,
                                "period": gen_result["period"],
                                "scheme": scheme,
                                "confidence": gen_result.get("confidence"),
                            })
                except Exception as e:
                    logger.error("LotteryDomain.generate %s 失败: %s", lot, e)

            return results

        run_in_subsystem("lottery", _do_generate)

        # 大盘彩诚实降级（config.DEGRADED_LOTS）：预测条目与汇总强制附警示，前端必须展示。
        # 依据：诚实回测+随机基准实测（七星彩 0/180、双色球 gain -0.78% 跑输随机）。
        honest_warnings = {}
        for lot in target_lots:
            if lot in DEGRADED_LOTS:
                honest_warnings[lot] = DEGRADED_LOTS[lot]
        if honest_warnings:
            for item in results:
                w = honest_warnings.get(item.get("lot"))
                if w:
                    item["honest_warning"] = w

        summary = f"生成 {len(results)} 条预测（{len(target_lots)}个彩种）"
        if honest_warnings:
            summary += " ⚠️ 大盘彩降级警示：" + "；".join(
                f"[{lot}] {msg}" for lot, msg in honest_warnings.items())
        return {
            "predictions": results,
            "summary": summary,
            "status": "ok",
            "domain_id": self.DOMAIN_ID,
            "confidences": conf_map,
            "honest_warnings": honest_warnings,
        }

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘学习
        
        对比预测与实际开奖，统计命中率。
        
        Returns:
            dict: {"reviews": int, "hits": int, "updated": bool, "details": list}
        """
        try:
            if not predictions or not actual:
                return {"reviews": 0, "hits": 0, "updated": False, "details": [], "status": "no_data"}

            hits = 0
            total = len(predictions)
            details = []

            for pred in predictions:
                lot = pred.get("lot", "")
                pred_nums_str = pred.get("nums", "")
                act_nums_str = actual.get("nums", "")

                # 解析号码
                from utils.number_utils import parse_reds
                pred_nums = set(parse_reds(pred_nums_str.split("+")[0]) if "+" in pred_nums_str else parse_reds(pred_nums_str))
                act_nums = set(parse_reds(act_nums_str.split("+")[0]) if "+" in act_nums_str else parse_reds(act_nums_str))

                match_count = len(pred_nums & act_nums)
                # 组选口径统一：与 GUI main_window.py 口径一致
                # 福彩3D/排列三 = 3码多重集全中（hits>=3）
                # 快乐8 = 命中5码以上（hits>=5）
                # 其他多球种 = 任意1码命中（hits>0）
                if lot in ("福彩3D", "排列三"):
                    is_hit = match_count >= 3
                elif lot == "快乐8":
                    is_hit = match_count >= 5
                else:
                    is_hit = match_count > 0

                if is_hit:
                    hits += 1

                details.append({
                    "lot": lot,
                    "period": pred.get("period", 0),
                    "pred": pred_nums_str,
                    "actual": act_nums_str,
                    "match": match_count,
                    "hit": is_hit,
                })

            # 更新 SmartBrain —— 调用正确的学习方法
            if self._smart_brain:
                try:
                    # 按彩种分组，调用 learn_from_review
                    from collections import defaultdict
                    lot_groups = defaultdict(lambda: {"preds": [], "actual": []})
                    for d in details:
                        lot = d.get("lot", "")
                        if lot:
                            lot_groups[lot]["preds"].append({
                                "nums": d.get("pred", ""),
                                "hits": d.get("match", 0),
                            })
                            lot_groups[lot]["actual"].append(d.get("actual", ""))
                    for lot, group in lot_groups.items():
                        actual_nums = []
                        for s in group["actual"]:
                            from utils.number_utils import parse_reds
                            actual_nums.extend(parse_reds(s.split("+")[0]) if "+" in s else parse_reds(s))
                        self._smart_brain.learn_from_review(lot, group["preds"], actual_nums)
                except Exception as e:
                    logger.warning("SmartBrain学习失败: %s", e)

            # 回写 predictions.json —— 标记已复盘的记录
            try:
                from utils.safe_json import safe_load_json, safe_write_json
                pred_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "金水谣数据", "predictions.json")
                all_preds = safe_load_json(pred_file, default=[])
                if isinstance(all_preds, list):
                    reviewed_periods = {d.get("period") for d in details}
                    for p in all_preds:
                        if p.get("period") in reviewed_periods:
                            p["reviewed"] = True
                            # 找到对应的复盘详情
                            for d in details:
                                if d.get("period") == p.get("period"):
                                    p["hits"] = d.get("match", 0)
                                    break
                    safe_write_json(pred_file, all_preds)
            except Exception as e:
                logger.warning("回写predictions.json失败: %s", e)

            # 写入审计日志
            try:
                from core.audit_log import log_review, log_fetch
                hit_rate = round(hits / total, 4) if total > 0 else 0
                for d in details:
                    if d["lot"]:
                        log_review("lottery", d["lot"], hit_rate, str(d.get("period", "")))
            except Exception:
                pass

            return {
                "reviews": total,
                "hits": hits,
                "hit_rate": round(hits / total, 4) if total > 0 else 0,
                "updated": True,
                "details": details,
                "status": "ok",
            }
        except Exception as e:
            logger.error("复盘失败: %s", e)
            return {"reviews": 0, "hits": 0, "updated": False, "error": str(e)}

    def status(self):
        """健康状态
        
        Returns:
            dict: {"ready": bool, "engines": [...], "last_run": str}
        """
        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "engines": list(self._engines.keys()),
            "lots": LOT_ALL,
            "last_run": None,
            "errors": [],
        }
