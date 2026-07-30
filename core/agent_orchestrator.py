"""多Agent编排器 — 路由Agent + 工作Agent + 审查Agent

与现有 JinshuiyaoAgent 兼容，增强而非替代。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RouteAgent:
    """路由Agent: 理解用户意图，分派到合适的Worker"""

    def classify(self, text: str, agent) -> str:
        """使用关键词+AI判断意图，委托给主Agent现有逻辑"""
        return agent._parse_intent(text)[0]  # 复用现有意图识别


class WorkerAgent:
    """工作Agent: 执行具体任务"""

    def execute(self, subsystem: str, action: str, target: str, user_input: str, agent) -> str:
        """执行子系统任务，委托给主Agent现有分发逻辑"""
        dispatch_map = {
            "lottery": agent._dispatch_lottery,
            "stock": agent._dispatch_stock,
            "football": agent._dispatch_football,
            "music": agent._dispatch_music,
            "video": agent._dispatch_video,
            "creator": agent._dispatch_creator,
            "knowledge": agent._dispatch_knowledge,
            "system": agent._dispatch_system,
            "web": agent._dispatch_web,
        }
        dispatcher = dispatch_map.get(subsystem)
        if dispatcher:
            if subsystem in ("lottery", "video", "knowledge", "web"):
                return dispatcher(action, target, user_input=user_input)
            return dispatcher(action, target)
        return f"未知子系统: {subsystem}"


class ReviewAgent:
    """审查Agent: 检查和优化输出质量"""

    def review(self, subsystem: str, user_input: str, data_result: str, draft: str, agent) -> Optional[str]:
        return agent._review_with_free(subsystem, user_input, data_result, draft)


class AgentOrchestrator:
    """多Agent编排器

    将单Agent流程拆为三级流水线:
      用户输入 → RouteAgent(理解) → WorkerAgent(执行) → ReviewAgent(检查) → 输出
    """

    def __init__(self, agent):
        self._agent = agent
        self._router = RouteAgent()
        self._worker = WorkerAgent()
        self._reviewer = ReviewAgent()

    def process(self, user_input: str) -> str:
        """处理用户输入的多Agent流程"""
        # 1. 路由
        subsystem = self._router.classify(user_input, self._agent)
        action = "general"
        target = "用户自定义问题"

        # 2. 工作
        data_result = self._worker.execute(subsystem, action, target, user_input, self._agent)
        if not data_result:
            return "暂时无法处理你的请求，请换个问法。"

        # 3. 总结
        summary = self._agent._summarize_with_free(subsystem, user_input, data_result)

        # 4. 审查
        if summary and self._agent._enable_review:
            reviewed = self._reviewer.review(subsystem, user_input, data_result, summary, self._agent)
            if reviewed:
                summary = reviewed

        return summary or data_result
