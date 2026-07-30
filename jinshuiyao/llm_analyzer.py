# -*- coding: utf-8 -*-
"""金水谣足彩 - DeepSeek LLM 赛前分析模块

通过统一的 AI 服务层（core.ai_service）调用 DeepSeek API。
不再自行管理密钥、API URL、频率限制（已由 ai_service 统一处理）。

使用方式：
    from jinshuiyao.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()          # 自动读取 deepseek_key.txt
    result = analyzer.analyze_match(match_data)
"""

import json
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """DeepSeek LLM 分析器 — 复用 core.ai_service"""

    def __init__(self, api_key: str = ""):
        """初始化分析器

        Args:
            api_key: API密钥，为空则自动从 ai_service 读取
        """
        # 复用统一AI服务层，不再自行管理密钥和频率限制
        if api_key:
            from core.ai_service import AIService
            self._ai = AIService(api_key=api_key)
        else:
            from core.ai_service import get_ai_service
            self._ai = get_ai_service()

    def _call_api(self, system_prompt: str, user_prompt: str,
                  temperature: float = 0.7, max_tokens: int = 1500) -> str:
        """调用 DeepSeek API（通过 ai_service）"""
        if not self._ai.is_available:
            return ""
        return self._ai.chat(system_prompt, user_prompt,
                             temperature=temperature, max_tokens=max_tokens)

    def analyze_match(self, match: Dict) -> str:
        """对单场比赛进行 LLM 深度分析

        Args:
            match: 比赛数据字典，需包含:
                - home: 主队名
                - away: 客队名
                - league: 联赛名
                - odds_win/draw/lose: 赔率
                - date/time: 比赛日期时间（可选）
                - match_time: 比赛时间字符串（可选）

        Returns:
            LLM 分析文本，失败返回空字符串
        """
        system_prompt = (
            "你是一位专业的足球比赛分析师，精通各国联赛和杯赛。"
            "请根据提供的比赛信息和赔率数据，给出简洁专业的分析。"
            "要求：\n"
            "1. 先给出核心观点（谁更有优势，关键因素是什么）\n"
            "2. 简要分析双方实力对比和战术特点\n"
            "3. 给出胜平负建议和让球倾向\n"
            "4. 指出可能的冷门风险\n"
            "5. 推荐2-3个最可能的比分\n"
            "6. 全文控制在300字以内，用中文\n"
            "不要输出废话，直接给干货分析。"
        )

        odds_win = match.get("odds_win", match.get("odds", {}).get("win", 0))
        odds_draw = match.get("odds_draw", match.get("odds", {}).get("draw", 0))
        odds_lose = match.get("odds_lose", match.get("odds", {}).get("lose", 0))

        # 计算隐含概率
        if odds_win and odds_draw and odds_lose:
            total = 1/odds_win + 1/odds_draw + 1/odds_lose
            p_win = 1/odds_win / total
            p_draw = 1/odds_draw / total
            p_lose = 1/odds_lose / total
            prob_info = (
                f"市场隐含概率: 主胜{p_win:.1%}, 平局{p_draw:.1%}, 客胜{p_lose:.1%}\n"
                f"返还率: {total:.1%}"
            )
        else:
            prob_info = "赔率数据不完整"

        date_str = match.get("date", match.get("match_time", "未知"))
        if len(str(date_str)) > 12:
            date_str = str(date_str)[:10]

        user_prompt = (
            f"【比赛信息】\n"
            f"联赛: {match.get('league', '未知')}\n"
            f"主队: {match.get('home', '未知')}\n"
            f"客队: {match.get('away', '未知')}\n"
            f"日期: {date_str}\n\n"
            f"【赔率数据】\n"
            f"主胜: {odds_win} | 平局: {odds_draw} | 客胜: {odds_lose}\n"
            f"{prob_info}\n\n"
            f"请给出这场比赛的深度数据分析。"
        )

        return self._call_api(system_prompt, user_prompt)

    def analyze_batch(self, matches: list, callback=None) -> Dict[str, str]:
        """批量分析多场比赛

        Args:
            matches: 比赛列表
            callback: 每场比赛分析完成后的回调 callback(match_key, result)

        Returns:
            {match_key: 分析文本} 的字典
        """
        results = {}
        for match in matches:
            key = f"{match.get('home', '?')} vs {match.get('away', '?')}"
            result = self.analyze_match(match)
            results[key] = result
            if callback:
                callback(key, result)
        return results

    def quick_analysis(self, match: Dict) -> str:
        """快速分析（短token版本，适合实时显示）"""
        system_prompt = (
            "你是足球分析师。用一句话给出比赛预测和关键理由。"
            "格式：推荐X胜（概率N%）| 关键：一句话理由。"
            "不超过50字。"
        )

        odds_win = match.get("odds_win", match.get("odds", {}).get("win", 0))
        odds_draw = match.get("odds_draw", match.get("odds", {}).get("draw", 0))
        odds_lose = match.get("odds_lose", match.get("odds", {}).get("lose", 0))

        user_prompt = (
            f"{match.get('league', '')} {match.get('home', '')} vs {match.get('away', '')} "
            f"赔率{odds_win}/{odds_draw}/{odds_lose}"
        )

        return self._call_api(system_prompt, user_prompt,
                               temperature=0.3, max_tokens=200)
