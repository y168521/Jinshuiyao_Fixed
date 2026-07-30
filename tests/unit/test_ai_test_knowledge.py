# -*- coding: utf-8 -*-
"""金水谣万物引擎 - AI测试知识库单元测试

测试 AITestKnowledge 类的所有类属性和方法的正确性。
"""

import unittest

from knowledge.ai_test_knowledge import AITestKnowledge


class TestAITestKnowledgeClassAttributes(unittest.TestCase):
    """测试 AITestKnowledge 的类属性完整性"""

    def test_test_categories_has_7_entries(self):
        """TEST_CATEGORIES 应包含7类测试场景"""
        self.assertEqual(len(AITestKnowledge.TEST_CATEGORIES), 7)

    def test_test_categories_contains_normal(self):
        """TEST_CATEGORIES 应包含 'normal' 正常流程测试"""
        self.assertIn('normal', AITestKnowledge.TEST_CATEGORIES)
        self.assertEqual(AITestKnowledge.TEST_CATEGORIES['normal'], '正常流程测试')

    def test_test_categories_contains_security(self):
        """TEST_CATEGORIES 应包含 'security' 安全性测试"""
        self.assertIn('security', AITestKnowledge.TEST_CATEGORIES)

    def test_test_categories_all_values_non_empty(self):
        """TEST_CATEGORIES 所有值应为非空字符串"""
        for key, value in AITestKnowledge.TEST_CATEGORIES.items():
            self.assertIsInstance(key, str, f"键类型应为str，实际: {type(key)}")
            self.assertTrue(len(value) > 0, f"'{key}' 对应的值不应为空")

    def test_priority_levels_has_4_levels(self):
        """PRIORITY_LEVELS 应包含 P0-P3 共4个优先级"""
        self.assertEqual(len(AITestKnowledge.PRIORITY_LEVELS), 4)

    def test_priority_levels_contains_p0(self):
        """PRIORITY_LEVELS 应包含 P0 冒烟测试"""
        self.assertIn('P0', AITestKnowledge.PRIORITY_LEVELS)
        self.assertIn('冒烟测试', AITestKnowledge.PRIORITY_LEVELS['P0'])

    def test_priority_levels_contains_all_expected(self):
        """PRIORITY_LEVELS 应包含全部4个级别"""
        expected_keys = {'P0', 'P1', 'P2', 'P3'}
        self.assertEqual(set(AITestKnowledge.PRIORITY_LEVELS.keys()), expected_keys)

    def test_industry_trends_not_empty(self):
        """INDUSTRY_TRENDS 应包含至少5条趋势数据"""
        self.assertGreaterEqual(len(AITestKnowledge.INDUSTRY_TRENDS), 5)

    def test_industry_trend_items_have_required_fields(self):
        """每条趋势应包含 title/description/benefit/tools 四个字段"""
        for trend in AITestKnowledge.INDUSTRY_TRENDS:
            self.assertIn('title', trend, "趋势项缺少 'title' 字段")
            self.assertIn('description', trend, "趋势项缺少 'description' 字段")
            self.assertIn('benefit', trend, "趋势项缺少 'benefit' 字段")
            self.assertIn('tools', trend, "趋势项缺少 'tools' 字段")
            self.assertIsInstance(trend['tools'], list, "tools 应为列表类型")

    def test_industry_trend_tools_non_empty(self):
        """每条趋势的 tools 列表不应为空"""
        for trend in AITestKnowledge.INDUSTRY_TRENDS:
            self.assertGreater(len(trend['tools']), 0,
                               f"趋势 '{trend['title']}' 的 tools 列表为空")

    def test_skill_roadmap_has_4_stages(self):
        """SKILL_ROADMAP 应包含4个学习阶段"""
        self.assertEqual(len(AITestKnowledge.SKILL_ROADMAP), 4)

    def test_skill_roadmap_stages_have_required_fields(self):
        """每个学习阶段应包含 stage/skills/duration 三个字段"""
        for stage in AITestKnowledge.SKILL_ROADMAP:
            self.assertIn('stage', stage, "学习阶段缺少 'stage' 字段")
            self.assertIn('skills', stage, "学习阶段缺少 'skills' 字段")
            self.assertIn('duration', stage, "学习阶段缺少 'duration' 字段")
            self.assertIsInstance(stage['skills'], list, "skills 应为列表类型")
            self.assertGreater(len(stage['skills']), 0,
                               f"阶段 '{stage['stage']}' 的 skills 列表为空")

    def test_skill_roadmap_stage_order(self):
        """学习阶段应按顺序排列（基础测试 -> 自动化入门 -> AI赋能 -> 测试开发）"""
        stages = AITestKnowledge.SKILL_ROADMAP
        self.assertIn('基础测试', stages[0]['stage'])
        self.assertIn('自动化入门', stages[1]['stage'])
        self.assertIn('AI赋能', stages[2]['stage'])
        self.assertIn('测试开发', stages[3]['stage'])

    def test_prompt_templates_has_3_templates(self):
        """PROMPT_TEMPLATES 应包含3个模板"""
        self.assertEqual(len(AITestKnowledge.PROMPT_TEMPLATES), 3)

    def test_prompt_templates_contains_api_test(self):
        """PROMPT_TEMPLATES 应包含 'api_test' 模板"""
        self.assertIn('api_test', AITestKnowledge.PROMPT_TEMPLATES)

    def test_prompt_templates_contains_performance_plan(self):
        """PROMPT_TEMPLATES 应包含 'performance_plan' 模板"""
        self.assertIn('performance_plan', AITestKnowledge.PROMPT_TEMPLATES)

    def test_prompt_templates_contains_test_report_analysis(self):
        """PROMPT_TEMPLATES 应包含 'test_report_analysis' 模板"""
        self.assertIn('test_report_analysis', AITestKnowledge.PROMPT_TEMPLATES)

    def test_prompt_templates_values_non_empty(self):
        """所有模板内容应为非空字符串"""
        for name, template in AITestKnowledge.PROMPT_TEMPLATES.items():
            self.assertIsInstance(template, str, f"模板 '{name}' 应为字符串类型")
            self.assertTrue(len(template) > 0, f"模板 '{name}' 内容不应为空")


class TestAITestKnowledgeMethods(unittest.TestCase):
    """测试 AITestKnowledge 的类方法"""

    def test_get_trend_by_title_exact_match(self):
        """精确匹配标题应返回对应趋势详情"""
        result = AITestKnowledge.get_trend_by_title('AI驱动用例生成')
        self.assertIsNotNone(result)
        self.assertEqual(result['title'], 'AI驱动用例生成')
        self.assertIn('tools', result)

    def test_get_trend_by_title_partial_match(self):
        """部分匹配标题应返回对应趋势详情"""
        result = AITestKnowledge.get_trend_by_title('自愈')
        self.assertIsNotNone(result)
        self.assertIn('自愈测试机制', result['title'])

    def test_get_trend_by_title_no_match(self):
        """不存在的标题应返回 None"""
        result = AITestKnowledge.get_trend_by_title('不存在的趋势标题')
        self.assertIsNone(result)

    def test_get_roadmap_stage_valid(self):
        """有效阶段编号应返回对应阶段详情"""
        result = AITestKnowledge.get_roadmap_stage(1)
        self.assertIsNotNone(result)
        self.assertIn('基础测试', result['stage'])
        self.assertIn('skills', result)
        self.assertIn('duration', result)

    def test_get_roadmap_stage_last_valid(self):
        """最后一个有效阶段编号应返回测试开发阶段"""
        result = AITestKnowledge.get_roadmap_stage(4)
        self.assertIsNotNone(result)
        self.assertIn('测试开发', result['stage'])

    def test_get_roadmap_stage_zero(self):
        """阶段编号0（无效）应返回 None"""
        result = AITestKnowledge.get_roadmap_stage(0)
        self.assertIsNone(result)

    def test_get_roadmap_stage_out_of_range(self):
        """阶段编号超出范围应返回 None"""
        result = AITestKnowledge.get_roadmap_stage(5)
        self.assertIsNone(result)
        result = AITestKnowledge.get_roadmap_stage(-1)
        self.assertIsNone(result)

    def test_get_prompt_valid_api_test(self):
        """获取 api_test 模板并正确填充参数"""
        result = AITestKnowledge.get_prompt(
            'api_test',
            path='/api/chat',
            method='POST',
            description='AI对话接口',
            params='message',
            count=5
        )
        self.assertIsNotNone(result)
        self.assertIn('/api/chat', result)
        self.assertIn('POST', result)
        self.assertIn('AI对话接口', result)

    def test_get_prompt_valid_performance_plan(self):
        """获取 performance_plan 模板并正确填充参数"""
        result = AITestKnowledge.get_prompt(
            'performance_plan',
            system='金水谣系统',
            apis='/api/chat, /api/status',
            concurrency=100
        )
        self.assertIsNotNone(result)
        self.assertIn('金水谣系统', result)
        self.assertIn('100', result)

    def test_get_prompt_valid_report_analysis(self):
        """获取 test_report_analysis 模板并正确填充参数"""
        result = AITestKnowledge.get_prompt(
            'test_report_analysis',
            results='通过: 8, 失败: 2'
        )
        self.assertIsNotNone(result)
        self.assertIn('通过: 8', result)

    def test_get_prompt_nonexistent(self):
        """获取不存在的模板名称应返回 None"""
        result = AITestKnowledge.get_prompt('nonexistent_template')
        self.assertIsNone(result)

    def test_get_prompt_missing_placeholder(self):
        """模板占位符缺失时应返回原始模板（不抛异常）"""
        result = AITestKnowledge.get_prompt('api_test')  # 缺少 path/method 等参数
        # 缺少占位符时会触发 KeyError，方法应返回原始模板
        self.assertIsNotNone(result)
        self.assertIn('请为以下API接口生成测试用例', result)


class TestAITestKnowledgeGetAll(unittest.TestCase):
    """测试 get_all_knowledge 方法"""

    def test_get_all_knowledge_returns_dict(self):
        """get_all_knowledge 应返回字典"""
        result = AITestKnowledge.get_all_knowledge()
        self.assertIsInstance(result, dict)

    def test_get_all_knowledge_has_5_keys(self):
        """get_all_knowledge 应包含5个知识板块"""
        result = AITestKnowledge.get_all_knowledge()
        self.assertEqual(len(result), 5)

    def test_get_all_knowledge_contains_all_sections(self):
        """get_all_knowledge 应包含全部知识板块"""
        result = AITestKnowledge.get_all_knowledge()
        expected_keys = {'test_categories', 'priority_levels', 'industry_trends',
                         'skill_roadmap', 'prompt_templates'}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_get_all_knowledge_data_integrity(self):
        """get_all_knowledge 返回的数据应与原始类属性一致"""
        result = AITestKnowledge.get_all_knowledge()
        # 验证引用完整性
        self.assertIs(result['test_categories'], AITestKnowledge.TEST_CATEGORIES)
        self.assertIs(result['priority_levels'], AITestKnowledge.PRIORITY_LEVELS)
        self.assertIs(result['industry_trends'], AITestKnowledge.INDUSTRY_TRENDS)
        self.assertIs(result['skill_roadmap'], AITestKnowledge.SKILL_ROADMAP)
        self.assertIs(result['prompt_templates'], AITestKnowledge.PROMPT_TEMPLATES)


if __name__ == '__main__':
    unittest.main()
