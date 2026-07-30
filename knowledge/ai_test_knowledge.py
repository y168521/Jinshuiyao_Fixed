# -*- coding: utf-8 -*-
"""金水谣万物引擎 - AI测试知识库

行业最佳实践集合，供AI用例生成和测试报告使用。

知识来源：
- AI驱动测试用例生成的核心技术（NLP/CV/强化学习）
- 接口自动化测试全流程（需求分析 -> 用例设计 -> 执行 -> 报告）
- 测试开发技能体系（测试框架/AI工具/性能测试）
- 行业实践案例和收益数据
"""

from typing import Any, Dict, List, Optional


class AITestKnowledge:
    """AI测试知识库 -- 行业最佳实践集合

    知识来源：
    - AI驱动测试用例生成的核心技术（NLP/CV/强化学习）
    - 接口自动化测试全流程（需求分析->用例设计->执行->报告）
    - 测试开发技能体系（测试框架/AI工具/性能测试）
    - 行业实践案例和收益数据
    """

    # ========== 测试用例生成的7类场景 ==========
    TEST_CATEGORIES: Dict[str, str] = {
        'normal': '正常流程测试',
        'param_missing': '参数缺失测试',
        'param_error': '参数异常测试',
        'boundary': '边界值测试',
        'security': '安全性测试',
        'performance': '性能测试',
        'compatibility': '兼容性测试',
    }

    # ========== 测试优先级定义 ==========
    PRIORITY_LEVELS: Dict[str, str] = {
        'P0': '冒烟测试（核心功能，每次必测）',
        'P1': '核心功能测试（主流程，高频测试）',
        'P2': '扩展功能测试（次要功能，定期测试）',
        'P3': '异常场景测试（边界和异常，按需测试）',
    }

    # ========== AI测试行业趋势 ==========
    INDUSTRY_TRENDS: List[Dict[str, Any]] = [
        {
            'title': 'AI驱动用例生成',
            'description': '通过自然语言描述自动生成可执行测试脚本，降低技术门槛',
            'benefit': '脚本编写时间减少40-70%',
            'tools': ['ChatGPT', 'Claude', 'DeepSeek', 'TestCraft'],
        },
        {
            'title': '智能接口文档解析',
            'description': 'NLP技术自动解析Swagger/OpenAPI文档，识别参数和依赖关系',
            'benefit': '接口分析效率提升80%',
            'tools': ['BERT', 'SpaCy', 'OpenAI'],
        },
        {
            'title': '自愈测试机制',
            'description': 'UI变化时自动调整元素定位策略，减少维护成本',
            'benefit': '维护成本降低70%',
            'tools': ['Healenium', 'Mabl', 'Testim.io'],
        },
        {
            'title': '性能测试AI辅助',
            'description': '根据系统监控数据自动推荐压力测试模型和场景',
            'benefit': '性能方案编写时间减少60%',
            'tools': ['JMeter+AI', 'k6', 'Locust'],
        },
        {
            'title': '智能测试报告',
            'description': 'AI自动分析测试结果，提取缺陷趋势，提供修复建议',
            'benefit': '缺陷分析时间减少50%',
            'tools': ['Allure', 'ExtentReports', '自研'],
        },
        {
            'title': '流量回放测试',
            'description': '录制生产环境流量，自动生成回归测试用例',
            'benefit': '回归覆盖率提升90%+',
            'tools': ['Schemathesis', 'RESTler', '流量镜像'],
        },
    ]

    # ========== 测试开发技能体系（新手学习路径） ==========
    SKILL_ROADMAP: List[Dict[str, Any]] = [
        {
            'stage': '第1阶段：基础测试',
            'skills': ['手工测试用例设计', '接口基础（HTTP/REST）', '抓包工具（Fiddler/Charles）', 'Postman基本使用'],
            'duration': '2-4周',
        },
        {
            'stage': '第2阶段：自动化入门',
            'skills': ['Python基础', 'Selenium/Appium', 'pytest框架', 'HTML/CSS/JS基础'],
            'duration': '4-6周',
        },
        {
            'stage': '第3阶段：AI赋能',
            'skills': ['AI提示工程', 'AI生成测试用例', 'AI辅助脚本编写', 'AI分析测试报告'],
            'duration': '2-4周',
        },
        {
            'stage': '第4阶段：测试开发',
            'skills': ['测试平台开发', 'CI/CD集成', '性能测试', '安全测试基础', '测试数据治理'],
            'duration': '8-12周',
        },
    ]

    # ========== AI生成用例的Prompt模板库 ==========
    PROMPT_TEMPLATES: Dict[str, str] = {
        'api_test': (
            '请为以下API接口生成测试用例：\n'
            '接口路径: {path}\n'
            '方法: {method}\n'
            '说明: {description}\n'
            '参数: {params}\n\n'
            '请生成{count}个测试用例，覆盖以下场景：\n'
            '1. 正常流程（参数正确，返回成功）\n'
            '2. 参数缺失（必填参数为空）\n'
            '3. 参数异常（类型错误/超范围/特殊字符）\n'
            '4. 边界值（最大值/最小值/空值/零值）\n'
            '5. 安全性（SQL注入/XSS/越权）\n\n'
            '用JSON数组格式返回：\n'
            '[{{"id":1, "title":"标题", "category":"normal", "priority":"P0", '
            '"precondition":"前置条件", "steps":"操作步骤", "expected":"预期结果"}}]'
        ),

        'performance_plan': (
            '请为以下系统生成性能测试方案：\n'
            '系统名称: {system}\n'
            '接口列表: {apis}\n'
            '预期并发: {concurrency}\n\n'
            '请包含：\n'
            '1. 测试目标（响应时间/吞吐量/错误率）\n'
            '2. 测试场景（正常负载/峰值/压力/稳定性）\n'
            '3. 测试数据准备\n'
            '4. 执行计划（ ramp-up / steady / ramp-down）\n'
            '5. 监控指标（CPU/内存/响应时间P99）\n'
            '6. 通过/失败标准'
        ),

        'test_report_analysis': (
            '请分析以下测试结果，给出质量评估：\n'
            '{results}\n\n'
            '请输出：\n'
            '1. 整体通过率和健康评估\n'
            '2. 失败用例的根因分析\n'
            '3. 高风险模块识别\n'
            '4. 改进建议（优先级排序）'
        ),
    }

    # ========== 类方法 ==========

    @classmethod
    def get_trend_by_title(cls, title: str) -> Optional[Dict[str, Any]]:
        """根据标题获取趋势详情

        Args:
            title: 行业趋势标题（支持模糊匹配）

        Returns:
            匹配的趋势字典，未找到时返回 None
        """
        for trend in cls.INDUSTRY_TRENDS:
            if title in trend['title']:
                return trend
        return None

    @classmethod
    def get_roadmap_stage(cls, stage_num: int) -> Optional[Dict[str, Any]]:
        """获取学习路径的阶段详情

        Args:
            stage_num: 阶段编号（从1开始）

        Returns:
            阶段详情字典，编号无效时返回 None
        """
        if 1 <= stage_num <= len(cls.SKILL_ROADMAP):
            return cls.SKILL_ROADMAP[stage_num - 1]
        return None

    @classmethod
    def get_prompt(cls, template_name: str, **kwargs: Any) -> Optional[str]:
        """获取填充后的prompt模板

        Args:
            template_name: 模板名称（如 'api_test', 'performance_plan', 'test_report_analysis'）
            **kwargs: 模板占位符的值

        Returns:
            填充后的完整prompt字符串，模板不存在时返回 None
        """
        template = cls.PROMPT_TEMPLATES.get(template_name)
        if template is None:
            return None
        try:
            return template.format(**kwargs)
        except KeyError:
            # 占位符缺失时返回原始模板
            return template

    @classmethod
    def get_all_knowledge(cls) -> Dict[str, Any]:
        """获取全部知识（供AI助手参考）

        Returns:
            包含所有知识板块的完整字典
        """
        return {
            'test_categories': cls.TEST_CATEGORIES,
            'priority_levels': cls.PRIORITY_LEVELS,
            'industry_trends': cls.INDUSTRY_TRENDS,
            'skill_roadmap': cls.SKILL_ROADMAP,
            'prompt_templates': cls.PROMPT_TEMPLATES,
        }
