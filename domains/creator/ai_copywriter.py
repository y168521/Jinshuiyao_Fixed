# -*- coding: utf-8 -*-
"""AI智能文案生成模块

支持多种文案风格生成，复用 core.ai_service 进行AI增强。
延迟加载AI服务，不可用时使用模板生成降级。
"""
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class AICopywriter:
    """AI智能文案生成器

    支持风格：
      - xiaohongshu: 小红书种草文
      - douyin: 抖音带货文
      - wechat: 朋友圈文案
      - article: 公众号文章
      - product: 产品描述
      - script: 视频脚本
    """

    STYLES = ['xiaohongshu', 'douyin', 'wechat', 'article', 'product', 'script']

    # 风格中文映射
    STYLE_NAMES = {
        'xiaohongshu': '小红书种草文',
        'douyin': '抖音带货文',
        'wechat': '朋友圈文案',
        'article': '公众号文章',
        'product': '产品描述',
        'script': '视频脚本',
    }

    # 各风格模板（降级模式使用）
    _TEMPLATES = {
        'xiaohongshu': {
            'title': '必看！{topic}，{tone}推荐',
            'body': (
                '姐妹们！今天来分享一个超级好用的{topic}！\n\n'
                '使用感受：\n'
                '1. 第一点太惊艳了\n'
                '2. 第二点超实用\n'
                '3. 第三点性价比高\n\n'
                '总结：真心推荐，一定要试试！\n\n'
                '#{topic} #好物分享 #种草'
            ),
            'tags': ['种草', '好物分享', '测评'],
        },
        'douyin': {
            'title': '{topic}，{tone}揭秘',
            'body': (
                '家人们！{topic}这个东西真的绝了！\n\n'
                '前3秒吸引你的理由：\n'
                '- 好用\n'
                '- 实惠\n'
                '- 效果好\n\n'
                '想要同款？评论区告诉我！\n\n'
                '关注我，更多好物推荐！'
            ),
            'tags': ['带货', '好物', '推荐'],
        },
        'wechat': {
            'title': '{topic}',
            'body': (
                '关于{topic}，我想说几句心里话。\n\n'
                '生活就是这样，总有一些东西值得分享。'
            ),
            'tags': ['生活', '分享'],
        },
        'article': {
            'title': '{topic}：{tone}解读',
            'body': (
                '一、引言\n\n'
                '关于{topic}，这是近年来备受关注的话题。\n\n'
                '二、核心观点\n\n'
                '1. 第一个核心观点\n'
                '2. 第二个核心观点\n'
                '3. 第三个核心观点\n\n'
                '三、总结\n\n'
                '以上是对{topic}的{tone}解读，希望对大家有所帮助。'
            ),
            'tags': ['深度', '解读', '分析'],
        },
        'product': {
            'title': '{topic}',
            'body': (
                '【产品名称】{topic}\n\n'
                '【产品特点】\n'
                '- 特点一\n'
                '- 特点二\n'
                '- 特点三\n\n'
                '【适用场景】\n'
                '日常使用、送礼、收藏。\n\n'
                '【产品优势】\n'
                '{tone}品质，值得信赖。'
            ),
            'tags': ['产品', '介绍'],
        },
        'script': {
            'title': '{topic}',
            'body': (
                '[画面] 开场特写\n'
                '旁白：{topic}，你了解多少？\n\n'
                '[画面] 产品展示\n'
                '旁白：今天带大家深入了解{topic}。\n\n'
                '[画面] 使用演示\n'
                '旁白：使用方法非常简单。\n\n'
                '[画面] 效果对比\n'
                '旁白：效果一目了然！\n\n'
                '[画面] 结尾引导\n'
                '旁白：关注我，了解更多。'
            ),
            'tags': ['视频', '脚本'],
        },
    }

    def __init__(self):
        self._ai = None  # 延迟加载AIService

    def _get_ai(self):
        """延迟加载AI服务"""
        if self._ai is None:
            try:
                from core.ai_service import get_ai_service
                self._ai = get_ai_service()
            except Exception as e:
                logger.debug("AI服务加载失败: %s", e)
                self._ai = None
        return self._ai

    def generate(self, topic, style='xiaohongshu', keywords=None, tone='专业'):
        """生成AI文案

        Args:
            topic: 文案主题
            style: 文案风格，默认小红书种草文
            keywords: 关键词列表（可选）
            tone: 语气风格，如"专业"/"活泼"/"温馨"

        Returns:
            dict: {
                'title': '标题',
                'content': '正文',
                'tags': ['标签1', '标签2'],
                'word_count': 500,
                'style': 'xiaohongshu',
                'mode': 'ai' | 'template',
            }
        """
        if style not in self.STYLES:
            style = 'xiaohongshu'

        # 尝试AI生成
        ai = self._get_ai()
        if ai and ai.is_available:
            try:
                return self._generate_with_ai(ai, topic, style, keywords, tone)
            except Exception as e:
                logger.warning("AI文案生成失败，降级为模板: %s", e)

        # 模板降级
        return self._generate_with_template(topic, style, tone)

    def _generate_with_ai(self, ai, topic, style, keywords, tone):
        """使用AI服务生成文案"""
        style_name = self.STYLE_NAMES.get(style, style)
        keywords_str = '、'.join(keywords) if keywords else '无特殊关键词'
        prompt = (
            f"请生成一篇{style_name}风格的文案。\n"
            f"主题：{topic}\n"
            f"语气：{tone}\n"
            f"关键词：{keywords_str}\n\n"
            f"要求：\n"
            f"1. 风格贴合{style_name}的特点\n"
            f"2. 语气{tone}\n"
            f"3. 包含吸引人的标题和正文\n"
            f"4. 结尾给出3-5个标签\n\n"
            f"请按以下格式输出：\n"
            f"【标题】xxx\n"
            f"【正文】xxx\n"
            f"【标签】xxx,xxx,xxx"
        )

        result = ai.analyze('creator', prompt)
        if not result:
            raise ValueError("AI返回空结果")

        # 解析AI返回结果
        title = topic
        content = result
        tags = []

        # 尝试解析结构化输出
        if '【标题】' in result:
            parts = result.split('【正文】')
            title_part = parts[0]
            title = title_part.replace('【标题】', '').strip()
            content = parts[1].split('【标签】')[0].strip() if '【标签】' in parts[1] else parts[1].strip()
            if '【标签】' in result:
                tag_part = result.split('【标签】')[-1].strip()
                tags = [t.strip() for t in tag_part.replace('，', ',').split(',') if t.strip()]

        return {
            'title': title,
            'content': content,
            'tags': tags or [topic, style_name],
            'word_count': len(content),
            'style': style,
            'mode': 'ai',
        }

    def _generate_with_template(self, topic, style, tone):
        """使用模板生成文案（降级模式）"""
        tpl = self._TEMPLATES.get(style, self._TEMPLATES['xiaohongshu'])
        title = tpl['title'].format(topic=topic, tone=tone)
        content = tpl['body'].format(topic=topic, tone=tone)
        tags = list(tpl['tags'])

        return {
            'title': title,
            'content': content,
            'tags': tags,
            'word_count': len(content),
            'style': style,
            'mode': 'template',
        }

    def generate_batch(self, topic, styles=None, count=3):
        """批量生成多风格文案

        Args:
            topic: 文案主题
            styles: 风格列表，None表示默认前count个
            count: 每种风格生成数量

        Returns:
            list: 文案结果列表
        """
        if not styles:
            styles = self.STYLES[:count]

        results = []
        for style in styles:
            try:
                result = self.generate(topic, style=style)
                result['batch_index'] = len(results) + 1
                results.append(result)
            except Exception as e:
                logger.warning("批量生成 %s 风格失败: %s", style, e)
                results.append({
                    'title': f'生成失败: {style}',
                    'content': f'{style}风格文案生成失败: {e}',
                    'tags': [],
                    'word_count': 0,
                    'style': style,
                    'mode': 'error',
                    'batch_index': len(results) + 1,
                })

        return results