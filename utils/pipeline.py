# -*- coding: utf-8 -*-
"""
金水谣统一数据管道 v1.0 (Pipeline Pattern)

设计目标：
  统一 彩票/足球/基金/股票 各域的数据获取流程，
  减少重复代码，建立标准的数据处理契约。

核心概念：
  DataContext  - 数据流上下文（贯穿整个管道的"数据背包"）
  PipelineStep - 管道的单一处理步骤
  DataPipeline - 编排多个步骤的有序管道

使用示例：
    class MyFetcher(DataPipeline):
        def build_pipeline(self):
            self.add_step(FetchStep())
            self.add_step(CleanStep())
            self.add_step(StoreStep())

        def run(self, source, **kwargs):
            ctx = DataContext(source=source, params=kwargs)
            return super().execute(ctx)
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime

logger = logging.getLogger("jinshuiyao.pipeline")


# ======================================================================
# 步骤状态
# ======================================================================
class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


# ======================================================================
# 数据上下文
# ======================================================================
class DataContext:
    """数据流上下文：贯穿整个管道的数据容器

    特性：
    - 不可变原始输入 (source)
    - 可变处理数据 (data)
    - 步骤间通信 (artifacts)
    - 元数据追踪 (metadata)
    """

    def __init__(self, source: Any = None, params: Optional[Dict] = None):
        self.source = source          # 原始输入（不变）
        self.params = params or {}    # 运行时参数
        self.data: Any = None         # 当前处理数据
        self.artifacts: Dict[str, Any] = {}   # 步骤间共享产物
        self.metadata: Dict[str, Any] = {     # 执行元数据
            "started_at": None,
            "completed_at": None,
            "steps": [],
            "errors": [],
            "warnings": []
        }

    @property
    def elapsed(self) -> Optional[float]:
        """执行耗时（秒）"""
        if self.metadata["started_at"] and self.metadata["completed_at"]:
            return self.metadata["completed_at"] - self.metadata["started_at"]
        return None

    def add_step_record(self, step_name: str, status: StepStatus,
                        detail: str = "", duration: float = 0):
        self.metadata["steps"].append({
            "step": step_name,
            "status": status.value,
            "detail": detail,
            "duration": round(duration, 3)
        })

    def add_error(self, step: str, message: str):
        self.metadata["errors"].append({"step": step, "message": str(message)})

    def add_warning(self, step: str, message: str):
        self.metadata["warnings"].append({"step": step, "message": str(message)})

    def summary(self) -> Dict[str, Any]:
        """执行摘要"""
        steps = self.metadata["steps"]
        success = sum(1 for s in steps if s["status"] == "success")
        failed = sum(1 for s in steps if s["status"] == "failed")
        return {
            "total_steps": len(steps),
            "success": success,
            "failed": failed,
            "errors": len(self.metadata["errors"]),
            "warnings": len(self.metadata["warnings"]),
            "elapsed": self.elapsed,
            "data_type": type(self.data).__name__ if self.data is not None else "None"
        }


# ======================================================================
# 管道步骤基类
# ======================================================================
class PipelineStep(ABC):
    """管道中的一个处理步骤"""

    def __init__(self, name: Optional[str] = None):
        self.name = name or self.__class__.__name__
        self.logger = logging.getLogger(f"jinshuiyao.pipeline.{self.name}")

    @abstractmethod
    def process(self, ctx: DataContext) -> DataContext:
        """执行本步骤的处理逻辑"""
        ...

    def __repr__(self) -> str:
        return f"<{self.name}>"


# ======================================================================
# 数据管道基类
# ======================================================================
class DataPipeline(ABC):
    """统一数据管道基类

    所有域（彩票/足球/基金/股票）的数据获取流程，
    都应继承此类并实现 build_pipeline() 方法。
    """

    def __init__(self, name: Optional[str] = None):
        self.name = name or self.__class__.__name__
        self._steps: List[Tuple[PipelineStep, bool]] = []  # (step, required)
        self.logger = logging.getLogger(f"jinshuiyao.pipeline.{self.name}")

    def add_step(self, step: PipelineStep, required: bool = True):
        """添加一个处理步骤到管道末尾

        Parameters
        ----------
        step : PipelineStep
            处理步骤实例
        required : bool
            步骤失败是否中断整个管道
        """
        self._steps.append((step, required))

    @abstractmethod
    def build_pipeline(self):
        """子类实现：组装管道步骤"""
        ...

    def execute(self, ctx: Optional[DataContext] = None,
                source: Any = None, **kwargs) -> DataContext:
        """执行管道

        Parameters
        ----------
        ctx : DataContext | None
            已有的数据上下文（用于管道嵌套）
        source : Any
            数据源标识
        **kwargs
            额外参数
        """
        if ctx is None:
            ctx = DataContext(source=source, params=kwargs)
        else:
            ctx.params.update(kwargs)

        ctx.metadata["started_at"] = time.time()

        if not self._steps:
            self.logger.warning("管道 '%s' 没有注册任何步骤", self.name)
            ctx.metadata["completed_at"] = time.time()
            return ctx

        self.logger.info("管道 '%s' 启动: %d 个步骤",
                        self.name, len(self._steps))

        for step, required in self._steps:
            step_start = time.time()
            ctx.metadata["current_step"] = step.name

            try:
                self.logger.debug("执行步骤: %s", step.name)
                ctx = step.process(ctx)
                elapsed = time.time() - step_start
                ctx.add_step_record(step.name, StepStatus.SUCCESS,
                                   duration=elapsed)
                self.logger.info("  ✅ %s (%.2fs)", step.name, elapsed)

            except Exception as e:
                elapsed = time.time() - step_start
                ctx.add_step_record(step.name, StepStatus.FAILED,
                                   detail=str(e), duration=elapsed)
                ctx.add_error(step.name, str(e))
                self.logger.error("  ❌ %s (%s)", step.name, e)

                if required:
                    self.logger.error("必要步骤失败，管道终止")
                    break
                else:
                    self.logger.warning("可选步骤失败，继续执行")

        ctx.metadata["completed_at"] = time.time()
        ctx.metadata.pop("current_step", None)

        # 日志摘要
        sm = ctx.summary()
        self.logger.info("管道 '%s' 完成: %d/%d 成功 (%.2fs)",
                        self.name, sm["success"], sm["total_steps"], sm["elapsed"])
        if sm["warnings"]:
            self.logger.warning("  ⚠️  %d 个警告", sm["warnings"])
        if sm["errors"]:
            self.logger.error("  ❌ %d 个错误", sm["errors"])

        return ctx

    def run(self, source: Any = None, **kwargs) -> DataContext:
        """快捷运行：构建管道并执行"""
        self.build_pipeline()
        return self.execute(source=source, **kwargs)


# ======================================================================
# 内置通用步骤
# ======================================================================
class LogStep(PipelineStep):
    """日志记录步骤（调试用）"""
    def process(self, ctx: DataContext) -> DataContext:
        self.logger.info("上下文摘要: source=%s, data_type=%s",
                        type(ctx.source).__name__,
                        type(ctx.data).__name__ if ctx.data is not None else "None")
        return ctx


class ValidateStep(PipelineStep):
    """数据验证步骤（检查数据完整性）"""
    def __init__(self, validator=None, name="数据验证"):
        super().__init__(name)
        self._validator = validator

    def process(self, ctx: DataContext) -> DataContext:
        if ctx.data is None:
            raise ValueError("数据为空，无法验证")

        if self._validator:
            errors = self._validator(ctx.data)
            if errors:
                for err in errors:
                    ctx.add_warning(self.name, err)
                self.logger.warning("数据验证: %d 个问题", len(errors))
            else:
                self.logger.info("数据验证通过")
        return ctx


# ======================================================================
# 快捷工厂
# ======================================================================
def make_pipeline(name: str, steps: List[PipelineStep]) -> DataPipeline:
    """快速创建一个简单管道"""
    class SimplePipeline(DataPipeline):
        def build_pipeline(self):
            for step in steps:
                self.add_step(step)

    SimplePipeline.__name__ = name
    return SimplePipeline(name=name)


# ======================================================================
# 自测
# ======================================================================
def _self_test():
    """快速自测数据管道功能"""
    import sys as _sys
    from pathlib import Path
    _test_dir = Path(__file__).resolve().parent.parent
    if str(_test_dir) not in _sys.path:
        _sys.path.insert(0, str(_test_dir))

    # 创建测试步骤
    class FetchStep(PipelineStep):
        def process(self, ctx):
            self.logger.info("模拟数据获取...")
            ctx.data = {"numbers": [1, 2, 3, 4, 5, 6], "period": "2026001"}
            return ctx

    class CleanStep(PipelineStep):
        def process(self, ctx):
            self.logger.info("模拟数据清洗...")
            if ctx.data:
                ctx.data["clean"] = True
            return ctx

    class StoreStep(PipelineStep):
        def process(self, ctx):
            self.logger.info("模拟数据存储...")
            ctx.artifacts["stored"] = True
            return ctx

    # 组装管道
    pipeline = make_pipeline("测试管道", [FetchStep(), CleanStep(), StoreStep()])

    # 执行
    ctx = pipeline.run(source="test_source")
    sm = ctx.summary()

    print(f"✅ 管道 '{pipeline.name}' 执行完成")
    print(f"   步骤: {sm['success']}/{sm['total_steps']} 成功")
    print(f"   耗时: {sm['elapsed']:.2f}s")
    print(f"   数据: {ctx.data}")
    assert sm["success"] == sm["total_steps"], "步骤未全部成功"
    assert ctx.data["clean"] is True, "数据清洗失败"
    print("✅ 数据管道自测通过！")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _self_test()
