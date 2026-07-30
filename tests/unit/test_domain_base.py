# -*- coding: utf-8 -*-
"""DomainBase 抽象基类单元测试

测试域子系统的标准接口规范：
  - 抽象类不可直接实例化
  - 所有抽象方法存在且必须实现
  - 具体方法 predict_full 可正常调用
  - 缺少任何抽象方法的子类不能实例化
"""
import unittest
import abc

from domains.base import DomainBase


# -----------------------------------------------------------------------
# 最小具体子类（用于正向测试）
# -----------------------------------------------------------------------
class MinimalDomain(DomainBase):
    """实现了全部抽象方法的最小子类"""

    DOMAIN_ID = "minimal"
    DESCRIPTION = "最小测试域"

    def setup(self):
        self._initialized = True
        return True

    def teardown(self):
        self._initialized = False
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [{"id": 1}], "message": "ok"}

    def analyze(self, data, **kwargs):
        return {"trend": "up", "confidence": 0.85}

    def generate(self, params=None, **kwargs):
        return {"predictions": ["A"], "summary": "测试预测"}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 1, "hits": 0, "updated": True}

    def status(self):
        return {
            "ready": self._initialized,
            "engines": ["test"],
            "last_run": "2026-01-01",
            "errors": [],
        }


# -----------------------------------------------------------------------
# 不完整子类（缺少部分抽象方法，用于反向测试）
# -----------------------------------------------------------------------
class MissingSetupDomain(DomainBase):
    """缺少 setup 方法的子类"""
    DOMAIN_ID = "missing_setup"
    DESCRIPTION = "缺少setup"

    def teardown(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def analyze(self, data, **kwargs):
        return {}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class MissingFetchDomain(DomainBase):
    """缺少 fetch 方法的子类"""
    DOMAIN_ID = "missing_fetch"
    DESCRIPTION = "缺少fetch"

    def setup(self):
        return True

    def teardown(self):
        return True

    def analyze(self, data, **kwargs):
        return {}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class MissingAnalyzeDomain(DomainBase):
    """缺少 analyze 方法的子类"""
    DOMAIN_ID = "missing_analyze"
    DESCRIPTION = "缺少analyze"

    def setup(self):
        return True

    def teardown(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class MissingStatusDomain(DomainBase):
    """缺少 status 方法的子类"""
    DOMAIN_ID = "missing_status"
    DESCRIPTION = "缺少status"

    def setup(self):
        return True

    def teardown(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def analyze(self, data, **kwargs):
        return {}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}


class MissingTeardownDomain(DomainBase):
    """缺少 teardown 方法的子类"""
    DOMAIN_ID = "missing_teardown"
    DESCRIPTION = "缺少teardown"

    def setup(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def analyze(self, data, **kwargs):
        return {}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class MissingGenerateDomain(DomainBase):
    """缺少 generate 方法的子类"""
    DOMAIN_ID = "missing_generate"
    DESCRIPTION = "缺少generate"

    def setup(self):
        return True

    def teardown(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def analyze(self, data, **kwargs):
        return {}

    def review(self, predictions, actual=None, **kwargs):
        return {"reviews": 0, "hits": 0, "updated": False}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class MissingReviewDomain(DomainBase):
    """缺少 review 方法的子类"""
    DOMAIN_ID = "missing_review"
    DESCRIPTION = "缺少review"

    def setup(self):
        return True

    def teardown(self):
        return True

    def fetch(self, **kwargs):
        return {"success": True, "data": [], "message": ""}

    def analyze(self, data, **kwargs):
        return {}

    def generate(self, params=None, **kwargs):
        return {"predictions": [], "summary": ""}

    def status(self):
        return {"ready": False, "engines": [], "last_run": "", "errors": []}


class TestDomainBase(unittest.TestCase):
    """DomainBase 抽象基类测试套件"""

    # ------------------------------------------------------------------
    # 抽象类约束
    # ------------------------------------------------------------------

    def test_cannot_instantiate_base(self):
        """验证DomainBase不能直接实例化（抽象类）"""
        with self.assertRaises(TypeError):
            DomainBase()

    def test_abstract_methods_exist(self):
        """验证所有抽象方法存在（setup/teardown/fetch/analyze/generate/review/status）"""
        expected_abstracts = [
            "setup", "teardown", "fetch", "analyze",
            "generate", "review", "status",
        ]
        # 通过 __abstractmethods__ 集合验证
        for method_name in expected_abstracts:
            self.assertIn(
                method_name, DomainBase.__abstractmethods__,
                f"预期抽象方法 {method_name} 不在 __abstractmethods__ 中"
            )

    def test_predict_full_is_concrete(self):
        """验证predict_full是具体方法（不是抽象的）"""
        self.assertNotIn(
            "predict_full", DomainBase.__abstractmethods__,
            "predict_full 不应是抽象方法"
        )
        # 验证方法确实存在且可调用
        self.assertTrue(callable(getattr(DomainBase, "predict_full", None)))

    # ------------------------------------------------------------------
    # 正向测试 - 最小具体子类
    # ------------------------------------------------------------------

    def test_concrete_subclass_works(self):
        """创建一个最小具体子类，验证可以实例化并调用所有方法"""
        domain = MinimalDomain(config={"key": "value"})

        # 验证初始化
        self.assertEqual(domain.config, {"key": "value"})
        self.assertFalse(domain._initialized)

        # 验证 setup
        result = domain.setup()
        self.assertTrue(result)
        self.assertTrue(domain._initialized)

        # 验证 fetch
        result = domain.fetch()
        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]), 1)

        # 验证 analyze
        result = domain.analyze([{"id": 1}])
        self.assertIn("trend", result)
        self.assertEqual(result["confidence"], 0.85)

        # 验证 generate
        result = domain.generate()
        self.assertIn("predictions", result)
        self.assertIn("summary", result)

        # 验证 review
        result = domain.review(predictions=["A"], actual="B")
        self.assertEqual(result["reviews"], 1)

        # 验证 status
        result = domain.status()
        self.assertTrue(result["ready"])
        self.assertEqual(result["engines"], ["test"])

        # 验证 teardown
        result = domain.teardown()
        self.assertTrue(result)
        self.assertFalse(domain._initialized)

    def test_predict_full_integration(self):
        """验证predict_full完整流程（抓取+分析+生成）"""
        domain = MinimalDomain()
        # predict_full 内部会自动调用 setup（如果未初始化）
        result = domain.predict_full()
        self.assertIn("predictions", result)
        self.assertIn("summary", result)

    def test_predict_full_fetch_failure(self):
        """验证predict_full在fetch失败时返回错误"""
        domain = MinimalDomain()

        # 让 fetch 返回失败
        original_fetch = domain.fetch
        domain.fetch = lambda **kwargs: {"success": False, "message": "网络错误"}

        result = domain.predict_full()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "网络错误")

        # 恢复
        domain.fetch = original_fetch

    def test_repr(self):
        """验证__repr__输出格式"""
        domain = MinimalDomain()
        repr_str = repr(domain)
        self.assertIn("minimal", repr_str)
        self.assertIn("最小测试域", repr_str)

    # ------------------------------------------------------------------
    # 反向测试 - 缺少抽象方法的子类不能实例化
    # ------------------------------------------------------------------

    def test_subclass_must_implement_all(self):
        """验证缺少任何抽象方法的子类不能实例化"""
        incomplete_classes = [
            (MissingSetupDomain, "setup"),
            (MissingTeardownDomain, "teardown"),
            (MissingFetchDomain, "fetch"),
            (MissingAnalyzeDomain, "analyze"),
            (MissingGenerateDomain, "generate"),
            (MissingReviewDomain, "review"),
            (MissingStatusDomain, "status"),
        ]

        for cls, missing_method in incomplete_classes:
            with self.subTest(missing=missing_method):
                with self.assertRaises(TypeError):
                    cls()

    def test_class_attributes(self):
        """验证基类和子类的类属性"""
        self.assertEqual(DomainBase.DOMAIN_ID, "base")
        self.assertEqual(DomainBase.DESCRIPTION, "基类域")
        self.assertEqual(MinimalDomain.DOMAIN_ID, "minimal")
        self.assertEqual(MinimalDomain.DESCRIPTION, "最小测试域")
