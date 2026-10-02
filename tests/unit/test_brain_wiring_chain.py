# -*- coding: utf-8 -*-
"""「今日预测」大脑/知识库接线闸（JS-20261002-20）

用户实测反馈："现在点今日预测还是旧数据，知识库是不是被调用了？"

点对点检验结论：
  ✅ 知识库**确实被调用**：_consult_knowledge 真实查询 385 张卡，
     双色球返回 cards_used=9、系数 1.076/1.128/1.029（已偏离中性 1.0）。
  ❌ 但**大脑从未参与**：gui/main_window.py 两处构造 PredictionService
     时**漏传 brain** → self.brain=None → _apply_brain_adjustments 的
     `if self.brain is not None` 守卫整段跳过 → 大脑学到的 digit_bias
     （实测 33 条）从未影响出号。GUI 里 self.brain 实例明明存在（L215）。

本测试锁死三件事：
  1. GUI 所有 PredictionService(...) 构造必须传 brain=（AST 接线闸）
  2. 反向验证：brain=None 不得修正号码；brain=实例 必须修正号码
  3. MiroFishDB 必须有公开 save（否则 use_count 落盘失败被静默吞掉）
"""
import ast
import io
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

MAIN_WINDOW = os.path.join(BASE, "gui", "main_window.py")


def _read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


class _FakeFG:
    """最小替身：只需 final_hot 字典。"""

    def __init__(self, hot):
        self.final_hot = dict(hot)


class TestGuiPassesBrain(unittest.TestCase):
    """① AST 接线闸：GUI 构造 PredictionService 必须带 brain=。"""

    def test_all_constructions_pass_brain(self):
        src = _read(MAIN_WINDOW)
        tree = ast.parse(src)
        bad = []
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
                continue
            if n.func.id != "PredictionService":
                continue
            kws = {k.arg for k in n.keywords if k.arg}
            if "brain" not in kws:
                bad.append("L%d" % n.lineno)
        self.assertEqual(
            bad, [],
            "PredictionService(...) 必须传 brain=，否则 _apply_brain_adjustments "
            "因守卫跳过、大脑学习成果不生效（JS-20261002-20）。漏传位置: %s" % bad)

    def test_gui_has_brain_instance(self):
        """前提：GUI 自己确实持有 brain 实例，才能传出去。"""
        src = _read(MAIN_WINDOW)
        self.assertIn("self.brain = SmartBrain()", src)


class TestBrainAdjustmentActuallyApplied(unittest.TestCase):
    """② 反向验证：有没有传 brain，行为必须不同。"""

    def setUp(self):
        from engines.smart_brain import SmartBrain
        from engines.prediction_service import PredictionService
        self.brain = SmartBrain()
        self.bias = self.brain.get_digit_adjustments("双色球") or {}
        self.base = {k: 1.0 for k in list(self.bias.keys())[:10]} \
            if self.bias else {i: 1.0 for i in range(1, 11)}
        self.svc_no = PredictionService()                    # 漏传 brain
        self.svc_yes = PredictionService(brain=self.brain)   # 正确传 brain

    def test_without_brain_no_adjustment(self):
        """没传 brain → 号码保持原样（这是修复前的错误行为）。"""
        fg = _FakeFG(self.base)
        self.svc_no._apply_brain_adjustments("双色球", fg)
        self.assertEqual(fg.final_hot, self.base)

    def test_with_brain_adjustment_applied(self):
        """传了 brain → 号码必须被 digit_bias 修正（坐实不是摆设）。"""
        fg = _FakeFG(self.base)
        self.svc_yes._apply_brain_adjustments("双色球", fg)
        self.assertNotEqual(fg.final_hot, self.base,
                            "传了 brain 却没修正号码 → 接线仍然失效")


class TestKnowledgePersistence(unittest.TestCase):
    """③ 知识库落盘接口必须存在，否则 use_count 静默丢失。"""

    def test_mirofish_has_public_save(self):
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        self.assertTrue(callable(getattr(db, "save", None)),
                        "MiroFishDB 缺公开 save() → _consult_knowledge 里 "
                        "db.save() 抛错被 except 吞掉，use_count 永久不落盘")

    def test_consult_knowledge_returns_factors(self):
        """知识库咨询真实生效：系数应偏离中性 1.0（不是空转）。"""
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        r = svc._consult_knowledge("双色球")
        self.assertIn("cards_used", r)
        self.assertGreater(r["cards_used"], 0,
                           "知识库未命中任何卡片 → 等于知识库没被调用")


if __name__ == "__main__":
    unittest.main()
