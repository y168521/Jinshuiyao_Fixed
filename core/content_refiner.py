# -*- coding: utf-8 -*-
"""金水谣引擎 - 内容提炼模块

使用AI服务（core.ai_service）对视频提取的内容进行智能提炼。
当AI服务不可用时，自动降级为规则方式提炼。

提炼功能：
  - 提取核心观点和关键信息
  - 生成知识摘要
  - 识别可复用的文案技巧
  - 提取数据/数字/事实
  - 自动分类标签
  - 生成结构化知识卡片

使用方式：
    from core.content_refiner import ContentRefiner
    refiner = ContentRefiner()
    card = refiner.refine(extracted_data)
    print(card["summary"])
    print(card["key_points"])
"""

import json
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContentRefiner:
    """内容提炼器 -- 用AI从视频中提炼有价值信息

    特性：
      - AI驱动的内容分析（调用DeepSeek）
      - 规则降级：AI不可用时使用正则和文本分析
      - 结构化知识卡片输出
      - 自动标签分类
      - 核心要点 / 数据事实 / 文案技巧 三维提炼
    """

    def __init__(self):
        self._ai = None

    def _get_ai(self):
        """延迟加载AI服务"""
        if self._ai is None:
            try:
                from core.ai_service import get_ai_service
                self._ai = get_ai_service()
            except Exception as e:
                logger.warning("[content_refiner] AI服务加载失败: %s", e)
        return self._ai

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def refine(self, extracted_data: dict) -> dict:
        """提炼视频内容为知识卡片

        将VideoExtractor提取的原始数据提炼为结构化知识卡片。
        优先使用AI提炼，AI不可用时使用规则提炼。

        Args:
            extracted_data: VideoExtractor.extract() 的返回结果

        Returns:
            知识卡片字典，包含以下字段：
            - source_url: 原始链接
            - source_platform: 来源平台
            - title: 标题
            - author: 作者
            - summary: 知识摘要
            - key_points: 关键要点列表
            - data_points: 数据/数字/事实列表
            - writing_techniques: 文案技巧列表
            - tags: 分类标签列表
            - full_text: 完整文本（描述+字幕合并）
            - refined_at: 提炼时间
            - method: 提炼方式（ai / rule）
        """
        title = extracted_data.get('title', '')
        description = extracted_data.get('description', '')
        subtitles = extracted_data.get('subtitles', '')
        tags = extracted_data.get('tags', [])
        author = extracted_data.get('author', '')
        platform = extracted_data.get('platform_name', extracted_data.get('platform', ''))

        # 合并完整文本
        full_text_parts = []
        if title:
            full_text_parts.append(title)
        if description:
            full_text_parts.append(description)
        if subtitles:
            full_text_parts.append(subtitles)
        full_text = '\n\n'.join(full_text_parts)

        # 基础信息
        card = {
            'source_url': extracted_data.get('url', ''),
            'source_platform': platform,
            'title': title,
            'author': author,
            'summary': '',
            'key_points': [],
            'data_points': [],
            'writing_techniques': [],
            'tags': list(tags) if tags else [],
            'full_text': full_text,
            'refined_at': datetime.now().isoformat(),
            'method': 'rule',
        }

        # 尝试AI提炼
        ai = self._get_ai()
        if ai and ai.is_available and full_text.strip():
            try:
                card = self._refine_with_ai(ai, card, full_text)
                card['method'] = 'ai'
                return card
            except Exception as e:
                logger.warning("[content_refiner] AI提炼失败，降级到规则方式: %s", e)

        # 规则提炼
        card = self._refine_with_rules(card, full_text)
        return card

    # ------------------------------------------------------------------
    # AI提炼
    # ------------------------------------------------------------------

    def _refine_with_ai(self, ai, card: dict, full_text: str) -> dict:
        """使用AI进行内容提炼

        Args:
            ai: AIService实例
            card: 基础知识卡片
            full_text: 完整文本内容

        Returns:
            AI提炼后的知识卡片
        """
        # 限制文本长度，避免超出API限制
        max_len = 3000
        text_for_ai = full_text[:max_len]
        if len(full_text) > max_len:
            text_for_ai += "\n\n...(内容已截断)"

        prompt = (
            f"请对以下视频内容进行专业提炼分析，返回JSON格式结果。\n\n"
            f"视频标题：{card['title']}\n"
            f"作者：{card['author']}\n"
            f"平台：{card['source_platform']}\n\n"
            f"视频内容：\n{text_for_ai}\n\n"
            f"请按以下JSON结构返回（只返回JSON，不要其他内容）：\n"
            f"{{\n"
            f"  \"summary\": \"100字以内的知识摘要\",\n"
            f"  \"key_points\": [\"核心要点1\", \"核心要点2\", \"核心要点3\"],\n"
            f"  \"data_points\": [\"数据/数字/事实1\", \"数据/数字/事实2\"],\n"
            f"  \"writing_techniques\": [\"文案技巧1\", \"文案技巧2\"],\n"
            f"  \"tags\": [\"标签1\", \"标签2\", \"标签3\"]\n"
            f"}}"
        )

        system_prompt = (
            "你是一位专业的内容分析专家，擅长从视频内容中提炼核心价值信息。"
            "你需要：\n"
            "1. 生成简明的知识摘要\n"
            "2. 提取核心要点\n"
            "3. 识别其中的数据、数字和事实\n"
            "4. 分析文案写作技巧\n"
            "5. 自动分类标签\n"
            "只返回JSON格式，不要其他内容。"
        )

        response = ai.chat(system_prompt, prompt, max_tokens=1500, temperature=0.3)

        if response:
            try:
                # 尝试解析AI返回的JSON
                # 可能包含 ```json ``` 包裹
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                    cleaned = re.sub(r'\n?```$', '', cleaned)

                ai_result = json.loads(cleaned)

                if isinstance(ai_result, dict):
                    # 合并AI结果到卡片
                    if ai_result.get('summary'):
                        card['summary'] = ai_result['summary']
                    if ai_result.get('key_points') and isinstance(ai_result['key_points'], list):
                        card['key_points'] = ai_result['key_points']
                    if ai_result.get('data_points') and isinstance(ai_result['data_points'], list):
                        card['data_points'] = ai_result['data_points']
                    if ai_result.get('writing_techniques') and isinstance(ai_result['writing_techniques'], list):
                        card['writing_techniques'] = ai_result['writing_techniques']
                    if ai_result.get('tags') and isinstance(ai_result['tags'], list):
                        # 合并标签（去重）
                        existing = set(card['tags'])
                        for t in ai_result['tags']:
                            if t not in existing:
                                card['tags'].append(t)

            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("[content_refiner] AI返回JSON解析失败: %s", e)
                # 使用AI原始文本作为摘要
                card['summary'] = response.strip()[:500]

        return card

    # ------------------------------------------------------------------
    # 规则提炼（降级方案）
    # ------------------------------------------------------------------

    def _refine_with_rules(self, card: dict, full_text: str) -> dict:
        """使用规则方式提炼内容

        当AI服务不可用时的降级方案。
        使用正则表达式和文本分析方法进行简单提炼。

        Args:
            card: 基础知识卡片
            full_text: 完整文本内容

        Returns:
            规则提炼后的知识卡片
        """
        # 1. 生成摘要（取前200字）
        text_clean = re.sub(r'\s+', ' ', full_text).strip()
        if len(text_clean) > 200:
            card['summary'] = text_clean[:200] + '...'
        elif text_clean:
            card['summary'] = text_clean
        else:
            card['summary'] = '（无内容可提炼）'

        # 2. 提取关键要点（按句子分割，过滤短句）
        sentences = self._split_sentences(full_text)
        key_points = [s.strip() for s in sentences if len(s.strip()) >= 10][:5]
        card['key_points'] = key_points

        # 3. 提取数据/数字/事实
        card['data_points'] = self.extract_data_points(full_text)

        # 4. 分析文案技巧（基于简单模式匹配）
        card['writing_techniques'] = self._detect_writing_techniques(full_text)

        # 5. 自动补充标签
        auto_tags = self._auto_classify(full_text)
        for tag in auto_tags:
            if tag not in card['tags']:
                card['tags'].append(tag)

        return card

    # ------------------------------------------------------------------
    # 规则提炼辅助方法
    # ------------------------------------------------------------------

    def extract_key_points(self, text: str) -> list:
        """提取关键要点

        将文本按句子分割，过滤掉过短的句子。

        Args:
            text: 待分析的文本

        Returns:
            关键要点列表
        """
        sentences = self._split_sentences(text)
        return [s.strip() for s in sentences if len(s.strip()) >= 10]

    def extract_data_points(self, text: str) -> list:
        """提取数据和数字

        使用正则表达式从文本中提取包含数字的句子或短语。

        匹配模式：
          - 百分比（如 85%、87.5%）
          - 金额（如 100万、3.5亿）
          - 具体数字 + 单位（如 1000人、5年）
          - 排名/编号（如 第1名、TOP3）

        Args:
            text: 待分析的文本

        Returns:
            数据事实列表
        """
        if not text:
            return []

        data_points = []

        # 匹配百分比
        percent_pattern = r'[^。\n]*?\d+\.?\d*%[^。\n]*'
        for match in re.finditer(percent_pattern, text):
            point = match.group().strip()
            if point and len(point) >= 3:
                data_points.append(point)

        # 匹配金额/数量（数字 + 中文单位）
        amount_pattern = r'[^。\n]*?\d+\.?\d*\s*[万亿千百十元人个次天年月日号期步公斤斤米公里%][^。\n]*'
        for match in re.finditer(amount_pattern, text):
            point = match.group().strip()
            if point and len(point) >= 3 and point not in data_points:
                data_points.append(point)

        # 匹配"第X"排名
        rank_pattern = r'第[一二三四五六七八九十\d]+[名位期届次号章节篇]'
        for match in re.finditer(rank_pattern, text):
            point = match.group().strip()
            if point and point not in data_points:
                # 尝试取完整句子
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                sentence = text[start:end].strip()
                if len(sentence) > len(point):
                    data_points.append(sentence)
                else:
                    data_points.append(point)

        # 去重并限制数量
        seen = set()
        unique_points = []
        for p in data_points:
            p_key = p[:30]  # 用前30字符去重
            if p_key not in seen:
                seen.add(p_key)
                unique_points.append(p)

        return unique_points[:10]

    def generate_summary(self, title: str, description: str, subtitles: str) -> str:
        """生成摘要

        合并标题、描述和字幕，截取前200字作为摘要。

        Args:
            title: 视频标题
            description: 视频描述
            subtitles: 视频字幕

        Returns:
            摘要文本
        """
        parts = []
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if subtitles:
            parts.append(subtitles)

        full_text = '\n'.join(parts)
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        if len(full_text) > 200:
            return full_text[:200] + '...'
        return full_text or '（无内容）'

    def _split_sentences(self, text: str) -> list:
        """按句子分割文本

        支持中文标点（。！？；）和英文标点（.!?;）作为分割符。

        Args:
            text: 待分割的文本

        Returns:
            句子列表
        """
        if not text:
            return []
        # 按中英文句末标点分割
        sentences = re.split(r'[。！？；!?\n]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _detect_writing_techniques(self, text: str) -> list:
        """检测文案写作技巧

        基于简单模式匹配识别常见的文案技巧：
          - 数字开头（如"3个方法"、"5个步骤"）
          - 疑问句（如"你知道吗？"）
          - 对比/转折（如"但是"、"然而"）
          - 列举（如"第一"、"首先"）
          - 引用（如引号内容）
          - 感叹号（加强语气）
          - 呼吁行动（如"赶快"、"立即"）

        Args:
            text: 待分析的文本

        Returns:
            检测到的文案技巧列表
        """
        techniques = []

        if not text:
            return techniques

        # 数字结构
        if re.search(r'\d+\s*[个种条步方法技巧建议理由秘诀原则]', text):
            techniques.append('数字结构法（列举式）')

        # 疑问句
        if re.search(r'[?？]', text):
            techniques.append('设问/疑问句式')

        # 对比/转折
        if re.search(r'(但是|然而|不过|却|反而|与之相比|相比之下|不但|不仅|反而)', text):
            techniques.append('对比转折手法')

        # 列举结构
        if re.search(r'(第一|首先|其次|再次|最后|一是|二是|三是|一方面|另一方面)', text):
            techniques.append('分层列举法')

        # 引用
        if re.search(r'["""\"][^""\""]+["""\"]', text):
            techniques.append('引用/金句')

        # 感叹加强
        if text.count('!') + text.count('！') >= 2:
            techniques.append('感叹语气加强')

        # 呼吁行动
        if re.search(r'(赶快|立即|马上|现在|赶紧|别犹豫|不要错过|限时|仅剩)', text):
            techniques.append('行动呼吁(CTA)')

        # 故事/案例
        if re.search(r'(有一次|我记得|曾经|去年|前天|那天|那天晚上|小时候)', text):
            techniques.append('故事/场景带入')

        # 干货标签
        if re.search(r'(干货|收藏|建议收藏|码住|转发|分享|必看|必学|宝典|秘籍)', text):
            techniques.append('互动引导词')

        return techniques

    def _auto_classify(self, text: str) -> list:
        """基于关键词自动分类标签

        Args:
            text: 待分类的文本

        Returns:
            自动分类的标签列表
        """
        tags = []
        if not text:
            return tags

        # 内容类型
        type_keywords = {
            '教程': ['教程', '教学', '怎么', '如何', '学会', '方法', '步骤', '操作', '使用'],
            '科普': ['科普', '科学', '原理', '为什么', '原因', '真相', '研究', '实验', '数据'],
            '测评': ['测评', '评测', '体验', '试用', '对比', '区别', '选择', '推荐', '排行'],
            '观点': ['观点', '认为', '看法', '思考', '分析', '解读', '评论', '态度'],
            '故事': ['故事', '经历', '回忆', '那年', '从前', '小时候', '大学', '工作'],
            '带货': ['购买', '下单', '链接', '优惠', '折扣', '直播间', '价格', '划算', '便宜'],
            '美食': ['美食', '好吃', '推荐', '餐厅', '做法', '菜谱', '食材', '味道'],
            '旅行': ['旅行', '旅游', '景点', '攻略', '打卡', '民宿', '酒店', '行程'],
            '健身': ['健身', '运动', '锻炼', '减肥', '增肌', '拉伸', '跑步', '瑜伽'],
            '职场': ['职场', '工作', '面试', '薪资', '跳槽', '简历', '升职', '管理', '创业'],
        }

        for tag_name, keywords in type_keywords.items():
            for kw in keywords:
                if kw in text:
                    tags.append(tag_name)
                    break

        return tags


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_refiner_instance: Optional[ContentRefiner] = None


def get_refiner() -> ContentRefiner:
    """获取全局ContentRefiner单例"""
    global _refiner_instance
    if _refiner_instance is None:
        _refiner_instance = ContentRefiner()
    return _refiner_instance
