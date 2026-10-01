# -*- coding: utf-8 -*-
"""金水谣引擎 - 内容提炼模块

使用AI服务（core.ai.ai_service）对视频提取的内容进行智能提炼。
当AI服务不可用时，自动降级为规则方式提炼。

提炼功能：
  - 提取核心观点和关键信息
  - 生成知识摘要
  - 识别可复用的文案技巧
  - 提取数据/数字/事实
  - 自动分类标签
  - 生成结构化知识卡片

使用方式：
    from core.ai.content_refiner import ContentRefiner
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


def _split_sentences(text: str) -> list:
    """按中英文句末标点分割文本"""
    if not text:
        return []
    sentences = re.split(r'[。！？；!?\n]+', text)
    return [s.strip() for s in sentences if s.strip()]


def _detect_writing_techniques(text: str) -> list:
    """基于模式匹配识别文案技巧"""
    if not text:
        return []
    techniques = []
    checks = [
        (r'\d+\s*[个种条步方法技巧建议理由秘诀原则]', '数字结构法（列举式）'),
        (r'[?？]', '设问/疑问句式'),
        (r'(但是|然而|不过|却|反而|与之相比|相比之下|不但|不仅)', '对比转折手法'),
        (r'(第一|首先|其次|再次|最后|一是|二是|三是|一方面|另一方面)', '分层列举法'),
        (r'["""\"][^""\""]+["""\"]', '引用/金句'),
    ]
    for pat, name in checks:
        if re.search(pat, text):
            techniques.append(name)
    if text.count('!') + text.count('！') >= 2:
        techniques.append('感叹语气加强')
    if re.search(r'(赶快|立即|马上|现在|赶紧|别犹豫|不要错过|限时|仅剩)', text):
        techniques.append('行动呼吁(CTA)')
    if re.search(r'(有一次|我记得|曾经|去年|前天|那天|小时候)', text):
        techniques.append('故事/场景带入')
    if re.search(r'(干货|收藏|建议收藏|码住|转发|分享|必看|必学|宝典|秘籍)', text):
        techniques.append('互动引导词')
    return techniques


def _auto_classify(text: str) -> list:
    """基于关键词自动分类标签"""
    if not text:
        return []
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
    tags = []
    for tag_name, keywords in type_keywords.items():
        if any(kw in text for kw in keywords):
            tags.append(tag_name)
    return tags


def extract_data_points(text: str) -> list:
    """提取数据和数字（百分比/金额/排名）"""
    if not text:
        return []
    data_points = []
    for pat in [r'[^。\n]*?\d+\.?\d*%[^。\n]*',
                r'[^。\n]*?\d+\.?\d*\s*[万亿千百十元人个次天年月日号期步公斤斤米公里%][^。\n]*']:
        for m in re.finditer(pat, text):
            p = m.group().strip()
            if p and len(p) >= 3 and p not in data_points:
                data_points.append(p)
    for m in re.finditer(r'第[一二三四五六七八九十\d]+[名位期届次号章节篇]', text):
        p = m.group().strip()
        if p and p not in data_points:
            s, e = max(0, m.start() - 20), min(len(text), m.end() + 20)
            data_points.append(text[s:e].strip() if e - s > len(p) else p)
    seen, unique = set(), []
    for p in data_points:
        k = p[:30]
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return unique[:10]


def generate_summary(title, description, subtitles) -> str:
    """合并标题/描述/字幕，截取前200字作为摘要"""
    parts = [x for x in (title, description, subtitles) if x]
    full_text = re.sub(r'\s+', ' ', '\n'.join(parts)).strip()
    if len(full_text) > 200:
        return full_text[:200] + '...'
    return full_text or '（无内容）'


def _build_ai_refine_prompt(card, full_text):
    """构建AI提炼的 system_prompt 和 user_prompt"""
    max_len = 3000
    text_for_ai = full_text[:max_len]
    if len(full_text) > max_len:
        text_for_ai += "\n\n...(内容已截断)"
    prompt = (
        f"请对以下视频内容进行专业提炼分析，返回JSON格式结果。\n\n"
        f"视频标题：{card['title']}\n作者：{card['author']}\n"
        f"平台：{card['source_platform']}\n\n视频内容：\n{text_for_ai}\n\n"
        f"请按以下JSON结构返回（只返回JSON，不要其他内容）：\n"
        f'{{\n  "summary": "100字以内的知识摘要",\n'
        f'  "key_points": ["核心要点1", "核心要点2", "核心要点3"],\n'
        f'  "data_points": ["数据/数字/事实1", "数据/数字/事实2"],\n'
        f'  "writing_techniques": ["文案技巧1", "文案技巧2"],\n'
        f'  "tags": ["标签1", "标签2", "标签3"]\n}}'
    )
    system_prompt = (
        "你是一位专业的内容分析专家，擅长从视频内容中提炼核心价值信息。"
        "你需要：1.生成简明的知识摘要 2.提取核心要点 3.识别数据和事实 "
        "4.分析文案写作技巧 5.自动分类标签。只返回JSON格式，不要其他内容。"
    )
    return system_prompt, prompt


def _build_base_card(extracted_data):
    """从提取数据构建基础知识卡片，返回 (card, full_text)"""
    title = extracted_data.get('title', '')
    description = extracted_data.get('description', '')
    subtitles = extracted_data.get('subtitles', '')
    tags = extracted_data.get('tags', [])
    author = extracted_data.get('author', '')
    platform = extracted_data.get('platform_name', extracted_data.get('platform', ''))
    full_text = '\n\n'.join(x for x in (title, description, subtitles) if x)
    card = {
        'source_url': extracted_data.get('url', ''),
        'source_platform': platform, 'title': title, 'author': author,
        'summary': '', 'key_points': [], 'data_points': [],
        'writing_techniques': [], 'tags': list(tags) if tags else [],
        'full_text': full_text, 'refined_at': datetime.now().isoformat(),
        'method': 'rule',
    }
    return card, full_text


def _merge_ai_result(card, response):
    """解析AI返回的JSON并合并到知识卡片"""
    if not response:
        return
    try:
        cleaned = response.strip()
        if cleaned.startswith('```'):
            cleaned = re.sub(r'^```\w*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned)
        ai_result = json.loads(cleaned)
        if not isinstance(ai_result, dict):
            return
        if ai_result.get('summary'):
            card['summary'] = ai_result['summary']
        for key in ('key_points', 'data_points', 'writing_techniques'):
            if ai_result.get(key) and isinstance(ai_result[key], list):
                card[key] = ai_result[key]
        if ai_result.get('tags') and isinstance(ai_result['tags'], list):
            existing = set(card['tags'])
            for t in ai_result['tags']:
                if t not in existing:
                    card['tags'].append(t)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[content_refiner] AI返回JSON解析失败: %s", e)
        card['summary'] = response.strip()[:500]


def _refine_with_rules(card: dict, full_text: str) -> dict:
    """规则方式提炼内容（AI不可用时的降级方案）"""
    text_clean = re.sub(r'\s+', ' ', full_text).strip()
    if len(text_clean) > 200:
        card['summary'] = text_clean[:200] + '...'
    elif text_clean:
        card['summary'] = text_clean
    else:
        card['summary'] = '（无内容可提炼）'
    sentences = _split_sentences(full_text)
    card['key_points'] = [s.strip() for s in sentences if len(s.strip()) >= 10][:5]
    card['data_points'] = extract_data_points(full_text)
    card['writing_techniques'] = _detect_writing_techniques(full_text)
    for tag in _auto_classify(full_text):
        if tag not in card['tags']:
            card['tags'].append(tag)
    return card


class ContentRefiner:
    """内容提炼器：用AI从视频中提炼有价值信息，AI不可用时降级为规则方式"""

    def __init__(self):
        self._ai = None

    def _get_ai(self):
        """延迟加载AI服务"""
        if self._ai is None:
            try:
                from core.ai.ai_service import get_ai_service
                self._ai = get_ai_service()
            except Exception as e:
                logger.warning("[content_refiner] AI服务加载失败: %s", e)
        return self._ai

    def refine(self, extracted_data: dict) -> dict:
        """提炼视频内容为知识卡片（优先AI，降级规则）"""
        card, full_text = _build_base_card(extracted_data)
        ai = self._get_ai()
        if ai and ai.is_available and full_text.strip():
            try:
                card = self._refine_with_ai(ai, card, full_text)
                card['method'] = 'ai'
                return card
            except Exception as e:
                logger.warning("[content_refiner] AI提炼失败，降级到规则方式: %s", e)
        return self._refine_with_rules(card, full_text)

    def _refine_with_ai(self, ai, card: dict, full_text: str) -> dict:
        """使用AI进行内容提炼，返回更新后的知识卡片"""
        system_prompt, prompt = _build_ai_refine_prompt(card, full_text)
        response = ai.chat(system_prompt, prompt, max_tokens=1500, temperature=0.3)
        _merge_ai_result(card, response)
        return card

    def _refine_with_rules(self, card: dict, full_text: str) -> dict:
        """规则方式提炼内容（AI不可用时的降级方案）"""
        return _refine_with_rules(card, full_text)

    def extract_key_points(self, text: str) -> list:
        sentences = _split_sentences(text)
        return [s.strip() for s in sentences if len(s.strip()) >= 10]

    def extract_data_points(self, text: str) -> list:
        return extract_data_points(text)

    def generate_summary(self, title: str, description: str, subtitles: str) -> str:
        return generate_summary(title, description, subtitles)

    def _detect_writing_techniques(self, text: str) -> list:
        return _detect_writing_techniques(text)

    def _split_sentences(self, text: str) -> list:
        return _split_sentences(text)

    def _auto_classify(self, text: str) -> list:
        return _auto_classify(text)


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
