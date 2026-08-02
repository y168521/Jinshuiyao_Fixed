# -*- coding: utf-8 -*-
"""金水谣系统 - 域子系统标准接口（DomainBase）

所有子系统必须实现此接口，通过核心注册表注册后由内核统一调度。
借鉴 Home Assistant Integration Platform + OpenStack Stevedore 设计。

标准接口规范：
  register()     -> 子系统注册
  setup()        -> 初始化资源
  fetch()        -> 数据抓取
  analyze()      -> 数据分析
  generate()     -> 方案生成
  review()       -> 复盘学习
  status()       -> 健康状态
  teardown()     -> 资源清理
"""
import abc
import logging
import os

logger = logging.getLogger(__name__)

# 项目根目录：base.py -> domains/ -> 项目根（不依赖 cwd，GUI 由 explorer 中转
# 启动时 cwd 是用户目录，相对路径会导致数据写到错误位置）
PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)


def project_data_dir(sub: str) -> str:
    """返回子系统数据目录的绝对路径（项目根/金水谣数据/<sub>）"""
    return os.path.join(PROJECT_ROOT, "金水谣数据", sub)


class DomainBase(abc.ABC):
    """域子系统标准接口（抽象基类）
    
    所有子系统（彩票、足彩、股票等）必须继承此类并实现全部抽象方法。
    """

    # 子系统标识（由子类覆写）
    DOMAIN_ID = "base"
    DESCRIPTION = "基类域"

    def __init__(self, config=None):
        """初始化子系统
        
        Args:
            config: 子系统配置字典
        """
        self.config = config or {}
        self._initialized = False

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def setup(self):
        """初始化子系统资源
        
        加载引擎、模型、知识库等必要资源。
        成功返回 True，失败返回 False。
        """
        pass

    @abc.abstractmethod
    def teardown(self):
        """清理子系统资源
        
        保存状态、释放资源、关闭连接。
        成功返回 True。
        """
        pass

    # ------------------------------------------------------------------
    # 核心预测流程
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def fetch(self, **kwargs):
        """数据抓取
        
        从外部源获取最新数据。
        
        Returns:
            dict: {"success": bool, "data": [...], "message": str}
        """
        pass

    @abc.abstractmethod
    def analyze(self, data, **kwargs):
        """数据分析
        
        对原始数据进行多引擎分析。
        
        Args:
            data: 原始数据
            **kwargs: 额外参数
            
        Returns:
            dict: 分析结果
        """
        pass

    @abc.abstractmethod
    def generate(self, params=None, **kwargs):
        """方案生成
        
        基于分析结果生成预测方案。
        
        Args:
            params: 生成参数
            **kwargs: 额外参数
            
        Returns:
            dict: {"predictions": [...], "summary": str}
        """
        pass

    @abc.abstractmethod
    def review(self, predictions, actual=None, **kwargs):
        """复盘学习
        
        对比预测与实际结果，更新学习状态。
        
        Args:
            predictions: 预测记录列表
            actual: 实际开奖数据（可选）
            **kwargs: 额外参数
            
        Returns:
            dict: {"reviews": int, "hits": int, "updated": bool}
        """
        pass

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def status(self):
        """子系统健康状态
        
        Returns:
            dict: {"ready": bool, "engines": [...], "last_run": str, "errors": [...]}
        """
        pass

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def predict_full(self, **kwargs):
        """完整预测流程（抓取 + 分析 + 生成）
        
        Returns:
            dict: 包含 predictions 和 summary 的结果字典
        """
        if not self._initialized:
            self.setup()
        
        # 1. 抓取
        fetch_result = self.fetch(**kwargs)
        if not fetch_result.get("success"):
            return {"success": False, "error": fetch_result.get("message", "抓取失败")}
        
        # 2. 分析
        analysis = self.analyze(fetch_result.get("data", []), **kwargs)
        
        # 3. 生成
        return self.generate(params=analysis, **kwargs)

    def __repr__(self):
        return f"<{self.DOMAIN_ID}: {self.DESCRIPTION}>"
