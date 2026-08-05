# -*- coding: utf-8 -*-
"""
金水谣 预测→验证闭环 v1.0 (PredictionVerifier)

每次预测后自动触发回测校验，生成可信度评分，
将验证结果存入知识库，支持持续优化。

流程：
  预测 → 对比已开奖数据 → 计算命中率 → 评分 → 入库 → 反馈

使用示例：
    verifier = PredictionVerifier()
    
    # 在 PredictionService.generate() 之后调用
    result = verifier.verify(
        lot_type="双色球",
        predicted_numbers=[1, 2, 3, 4, 5, 6, 7],
        period="2026078",
        prediction_type="direct_select"
    )
    print(f"命中率: {result.hit_rate:.1%}")
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set
from enum import Enum
from pathlib import Path

logger = logging.getLogger("jinshuiyao.verifier")


# ======================================================================
# 验证结果
# ======================================================================
class VerifyGrade(Enum):
    """验证评级"""
    EXCELLENT = "excellent"   # ≥80%
    GOOD = "good"             # ≥60%
    FAIR = "fair"             # ≥40%
    POOR = "poor"             # ≥20%
    BAD = "bad"               # <20%


class VerifyResult:
    """单次预测的验证结果"""

    def __init__(self, lot_type: str, period: str,
                 predicted: List[int], actual: Optional[List[int]] = None):
        self.lot_type = lot_type
        self.period = period
        self.predicted = predicted
        self.actual = actual or []

        # 命中统计
        self.red_hits: Set[int] = set()
        self.blue_hits: Set[int] = set()
        self.red_count: int = 0
        self.blue_count: int = 0
        self.total_hits: int = 0
        self.hit_rate: float = 0.0
        self.grade: VerifyGrade = VerifyGrade.BAD

        # 元数据
        self.verified_at: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.verify_ms: float = 0.0
        self.error: Optional[str] = None

    def compute(self):
        """计算命中统计"""
        start = time.time()
        try:
            if not self.actual:
                self.error = "无实际开奖数据"
                return

            pred_set = set(self.predicted)

            # 区分红蓝球（如果有blue标记）
            # 兼容不同数据格式
            if len(self.predicted) > 6 and len(self.actual) > 6:
                # 红球: 前6个，蓝球: 后续
                pred_red = set(self.predicted[:6])
                pred_blue = set(self.predicted[6:])
                actual_red = set(self.actual[:6])
                actual_blue = set(self.actual[6:])

                self.red_hits = pred_red & actual_red
                self.blue_hits = pred_blue & actual_blue
                self.red_count = len(self.red_hits)
                self.blue_count = len(self.blue_hits)
                self.total_hits = self.red_count + self.blue_count

                total_items = len(pred_red) + len(pred_blue)
            else:
                # 无颜色区分：直接比较
                self.red_hits = pred_set & set(self.actual)
                self.total_hits = len(self.red_hits)
                total_items = len(self.predicted)

            self.hit_rate = self.total_hits / total_items if total_items > 0 else 0.0

            # 评级
            if self.hit_rate >= 0.8:
                self.grade = VerifyGrade.EXCELLENT
            elif self.hit_rate >= 0.6:
                self.grade = VerifyGrade.GOOD
            elif self.hit_rate >= 0.4:
                self.grade = VerifyGrade.FAIR
            elif self.hit_rate >= 0.2:
                self.grade = VerifyGrade.POOR
            else:
                self.grade = VerifyGrade.BAD

        except Exception as e:
            self.error = str(e)
            logger.error("验证计算异常: %s", e)
        finally:
            self.verify_ms = round((time.time() - start) * 1000, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lot_type": self.lot_type,
            "period": self.period,
            "predicted": self.predicted,
            "actual": self.actual,
            "red_hits": list(self.red_hits),
            "blue_hits": list(self.blue_hits),
            "total_hits": self.total_hits,
            "hit_rate": round(self.hit_rate, 4),
            "grade": self.grade.value,
            "verified_at": self.verified_at,
            "verify_ms": self.verify_ms,
            "error": self.error
        }

    def __repr__(self) -> str:
        return (f"<Verify {self.lot_type} #{self.period}: "
                f"{self.total_hits}hit/{self.hit_rate:.1%} [{self.grade.value}]>")


# ======================================================================
# 预测验证器
# ======================================================================
class PredictionVerifier:
    """预测验证器：自动验证预测准确性，反馈优化"""

    def __init__(self):
        self._history: List[Dict] = []
        self._stats: Dict[str, Any] = {
            "total_verified": 0,
            "excellent": 0,
            "good": 0,
            "fair": 0,
            "poor": 0,
            "bad": 0,
            "avg_hit_rate": 0.0,
            "by_lot_type": {}
        }

    # ------------------------------------------------------------------
    # 获取实际开奖数据
    # ------------------------------------------------------------------
    def _fetch_actual(self, lot_type: str, period: str) -> Optional[List[int]]:
        """从缓存或数据文件获取实际开奖号码"""
        try:
            # 优先从缓存获取
            from utils.cache_manager import get_cache
            cache = get_cache()
            cache_key = f"actual:{lot_type}:{period}"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            # 从数据文件获取
            from config import LOTTERY_RULES
            from models.lottery_data import Data

            rule = LOTTERY_RULES.get(lot_type)
            if not rule:
                logger.warning("未知彩种: %s", lot_type)
                return None

            data_path = rule.get("data_path", "")
            if not data_path:
                return None

            # 读取指定期数的开奖数据
            all_data = Data.load(rule)
            if not all_data:
                return None

            for entry in all_data:
                if str(entry.get("period", "")) == str(period):
                    nums = entry.get("nums", "")
                    if nums:
                        from utils.number_utils import parse_reds
                        numbers = parse_reds(nums)
                        # 存入缓存（长期）
                        cache.set(cache_key, numbers, ttl=86400 * 30, persist=True)
                        return numbers
        except Exception as e:
            logger.debug("获取实际数据失败 %s %s: %s", lot_type, period, e)
        return None

    # ------------------------------------------------------------------
    # 单次验证
    # ------------------------------------------------------------------
    def verify(self, lot_type: str, predicted: List[int],
               period: Optional[str] = None,
               prediction_type: str = "unknown") -> VerifyResult:
        """验证一次预测结果

        Parameters
        ----------
        lot_type : str
            彩种名称，如"双色球"
        predicted : List[int]
            预测号码列表
        period : str | None
            预测期号（自动获取最新期号）
        prediction_type : str
            预测类型: direct_select/group_six/group_three

        Returns
        -------
        VerifyResult
            验证结果
        """
        # 获取期号
        if not period:
            try:
                from config import LOTTERY_RULES
                rule = LOTTERY_RULES.get(lot_type, {})
                period = str(rule.get("latest_period", ""))
            except Exception:
                period = "unknown"

        # 获取实际开奖数据
        actual = self._fetch_actual(lot_type, period)

        # 计算验证结果
        result = VerifyResult(lot_type, period, predicted, actual)
        result.compute()

        # 记录历史
        record = result.to_dict()
        record["prediction_type"] = prediction_type
        self._history.append(record)
        self._update_stats(record)

        if result.error:
            logger.warning("验证 %s #%s: %s", lot_type, period, result.error)
        else:
            logger.info("验证 %s #%s: %d命中/%.1f%% [%s] (%dms)",
                       lot_type, period, result.total_hits,
                       result.hit_rate * 100, result.grade.value,
                       result.verify_ms)

        return result

    # ------------------------------------------------------------------
    # 批量验证
    # ------------------------------------------------------------------
    def verify_batch(self, predictions: List[Dict]) -> List[VerifyResult]:
        """批量验证多条预测

        Parameters
        ----------
        predictions : List[Dict]
            [{"lot_type": "双色球", "predicted": [...], "period": "..."}, ...]

        Returns
        -------
        List[VerifyResult]
        """
        results = []
        for pred in predictions:
            result = self.verify(
                lot_type=pred.get("lot_type", ""),
                predicted=pred.get("predicted", []),
                period=pred.get("period"),
                prediction_type=pred.get("type", "unknown")
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    def _update_stats(self, record: Dict):
        s = self._stats
        s["total_verified"] += 1
        grade = record.get("grade", "bad")
        s[grade] = s.get(grade, 0) + 1

        # 按彩种统计
        lt = record.get("lot_type", "unknown")
        if lt not in s["by_lot_type"]:
            s["by_lot_type"][lt] = {"count": 0, "total_hits": 0, "total_items": 0}
        lt_s = s["by_lot_type"][lt]
        lt_s["count"] += 1
        lt_s["total_hits"] += record.get("total_hits", 0)

    @property
    def stats(self) -> Dict[str, Any]:
        """验证统计"""
        s = self._stats
        total = s["total_verified"]
        if total > 0:
            s["avg_hit_rate"] = round(
                sum(r.get("total_hits", 0) for r in self._history) /
                max(sum(len(r.get("predicted", [])) for r in self._history), 1),
                4
            )
        return s

    def summary(self) -> str:
        """生成可读摘要"""
        s = self.stats
        lines = [
            f"预测验证统计 (共 {s['total_verified']} 次)",
            f"  优秀: {s.get('excellent', 0)}",
            f"  良好: {s.get('good', 0)}",
            f"  一般: {s.get('fair', 0)}",
            f"  较差: {s.get('poor', 0)}",
            f"  很差: {s.get('bad', 0)}",
            f"  平均命中率: {s.get('avg_hit_rate', 0):.1%}"
        ]
        return "\n".join(lines)

    def save_results(self, filepath: Optional[str] = None) -> str:
        """保存验证结果到文件"""
        if not filepath:
            base = Path(__file__).resolve().parent.parent
            filepath = str(base / "金水谣数据" / "verification" /
                          f"verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        out = {
            "summary": self.stats,
            "records": self._history[-1000:],  # 保留最近1000条
            "generated_at": datetime.now().isoformat()
        }

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        try:
            import utils.safe_json as _sj
            _sj.safe_write_json(filepath, out)
            logger.info("验证结果已保存: %s", filepath)
        except Exception as e:
            logger.warning("验证结果保存失败: %s", e)

        return filepath


# ======================================================================
# 全局单例
# ======================================================================
_verifier_instance: Optional[PredictionVerifier] = None


def get_verifier() -> PredictionVerifier:
    """获取全局验证器实例"""
    global _verifier_instance
    if _verifier_instance is None:
        _verifier_instance = PredictionVerifier()
        logger.info("预测验证器已初始化")
    return _verifier_instance


# ======================================================================
# 自测
# ======================================================================
def _self_test():
    """快速自测验证功能"""
    import sys as _sys
    from pathlib import Path
    _test_dir = Path(__file__).resolve().parent.parent
    if str(_test_dir) not in _sys.path:
        _sys.path.insert(0, str(_test_dir))

    verifier = get_verifier()

    # 模拟验证（无实际数据时验证器会报无数据，但不应崩溃）
    r1 = verifier.verify("双色球", [1, 2, 3, 4, 5, 6, 7], period="2026001")
    print(f"✅ 验证1: {r1}")
    assert r1 is not None

    # 模拟批量验证
    results = verifier.verify_batch([
        {"lot_type": "大乐透", "predicted": [1, 2, 3, 4, 5, 6, 7], "period": "2026001"},
        {"lot_type": "福彩3D", "predicted": [1, 2, 3], "period": "2026001"},
    ])
    for r in results:
        print(f"✅ 批量验证: {r}")

    # 统计摘要
    print(f"\n📊 统计:\n{verifier.summary()}")

    # 保存
    path = verifier.save_results()
    print(f"📁 已保存: {path}")

    print("\n✅ 预测验证器自测通过！")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _self_test()
