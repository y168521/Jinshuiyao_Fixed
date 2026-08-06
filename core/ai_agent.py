# -*- coding: utf-8 -*-
"""金水谣引擎 - 智能AI体核心

统一的自然语言交互入口，用户通过对话直接调用所有子系统功能。
支持彩票预测、股票行情、足彩分析、系统管理等。

架构：
  用户输入 → 意图识别 → 子系统调度 → 数据获取 → AI总结 → 返回结果

使用方式：
    from core.ai_agent import JinshuiyaoAgent
    agent = JinshuiyaoAgent()
    result = agent.chat("今天双色球预测是什么")
    result = agent.chat("上证指数怎么样")
    result = agent.chat("今天有什么足球比赛")
"""

import json
import os
import re
import logging
import threading
import traceback
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from utils.safe_json import safe_write_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 意图关键词映射（已拆分到 core/intent_rules.py）
# ---------------------------------------------------------------------------
from core.intent_rules import INTENT_RULES as _INTENT_RULES, VIDEO_PLATFORM_KEYWORDS

# ---------------------------------------------------------------------------
# 结果格式化（已拆分到 core/agent_formatters.py）
# ---------------------------------------------------------------------------
from core.agent_formatters import (
    format_lottery_result as _fmt_lottery,
    format_lottery_result_detailed as _fmt_lottery_detail,
    format_stock_result as _fmt_stock,
    format_stock_picks as _fmt_stock_picks,
    format_stock_technical as _fmt_stock_tech,
    format_football_result as _fmt_football,
    format_football_odds as _fmt_football_odds,
    format_music_result as _fmt_music,
    format_music_analysis as _fmt_music_analysis,
    format_extracted_result as _fmt_extracted,
    format_refined_result as _fmt_refined,
)


class JinshuiyaoAgent:
    """金水谣智能AI体

    特性：
      - 自然语言意图识别（关键词匹配 + AI辅助）
      - 子系统自动调度（彩票/股票/足彩/系统）
      - 数据获取 + AI总结 = 专业回答
      - 对话上下文记忆
      - 错误降级（子系统不可用时给出提示）
    """

    def __init__(self):
        self._domains = {}       # 子系统实例缓存
        self._ai = None          # AIService 实例
        self._history = []       # 对话历史 (role, content)
        self._max_history = 20  # 最大保留轮数

        # 记忆持久化（重启不丢 + 长期画像）
        self._mem_lock = threading.RLock()  # 可重入锁：避免 _add_memory 内重入 _save_profile 时普通 Lock 死锁
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Jinshuiyao_Fixed
        self._mem_dir = os.path.join(_root, "金水谣数据", "agent_memory")
        self._history_file = os.path.join(self._mem_dir, "history.json")
        self._profile_file = os.path.join(self._mem_dir, "user_profile.json")
        self._profile = {}
        self._load_history()   # 启动时恢复对话记忆
        self._load_profile()   # 启动时恢复用户画像
        self._initialized = {}   # 子系统初始化状态
        self._knowledge_db = None  # 知识库实例（延迟加载）
        self._video_extractor = None  # 视频提取器（延迟加载）
        self._content_refiner = None  # 内容提炼器（延迟加载）
        self._last_extracted = None  # 最近一次提取结果（用于归档）
        # 主动提醒（进化·进阶1）：对话开始时 pop 出待提醒，主动开口
        self._pending_reminders = []
        # 多角色生成/复核（进化·进阶2）总开关：默认开，免费模型0成本；关掉则只生成不复核
        self._enable_review = True
        self._chat_lock = threading.RLock()  # 并发安全：串行化 chat 防止共享态交错/撕裂
        # 向量记忆（进化·进阶3）：按语义搜索历史对话 + 知识
        self._vector_memory = None  # 延迟加载

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _get_ai(self):
        """延迟加载AIService"""
        if self._ai is None:
            try:
                from core.ai_service import get_ai_service
                self._ai = get_ai_service()
            except Exception as e:
                logger.error("[agent] AI服务加载失败: %s", e)
        return self._ai

    def _get_domain(self, name: str):
        """获取子系统实例（延迟初始化）"""
        if name not in self._domains:
            try:
                if name == "lottery":
                    from domains.lottery.domain import LotteryDomain
                    self._domains[name] = LotteryDomain()
                elif name == "stock":
                    from domains.stock.domain import StockDomain
                    self._domains[name] = StockDomain()
                elif name == "football":
                    from domains.football.domain import FootballDomain
                    self._domains[name] = FootballDomain()
                elif name == "music":
                    from domains.music.domain import MusicDomain
                    self._domains[name] = MusicDomain()
                elif name == "creator":
                    from domains.creator.domain import CreatorDomain
                    self._domains[name] = CreatorDomain()
                else:
                    return None

                # 自动初始化
                if name not in self._initialized:
                    try:
                        self._domains[name].setup()
                        self._initialized[name] = True
                        logger.info("[agent] %s 子系统初始化成功", name)
                    except Exception as e:
                        logger.warning("[agent] %s 初始化失败: %s", name, e)
                        self._initialized[name] = False
            except Exception as e:
                logger.error("[agent] %s 子系统加载失败: %s", name, e)
                return None
        return self._domains.get(name)

    def _get_knowledge_db(self):
        """延迟加载知识库"""
        if self._knowledge_db is None:
            try:
                from knowledge.mirofish_db import MiroFishDB
                self._knowledge_db = MiroFishDB()
            except Exception as e:
                logger.error("[agent] 知识库加载失败: %s", e)
        return self._knowledge_db

    def _get_video_extractor(self):
        """延迟加载视频提取器"""
        if self._video_extractor is None:
            try:
                from core.video_extractor import VideoExtractor
                self._video_extractor = VideoExtractor()
            except Exception as e:
                logger.error("[agent] 视频提取器加载失败: %s", e)
        return self._video_extractor

    def _get_content_refiner(self):
        """延迟加载内容提炼器"""
        if self._content_refiner is None:
            try:
                from core.content_refiner import ContentRefiner
                self._content_refiner = ContentRefiner()
            except Exception as e:
                logger.error("[agent] 内容提炼器加载失败: %s", e)
        return self._content_refiner

    def _get_vector_memory(self):
        """延迟加载向量记忆引擎"""
        if self._vector_memory is None:
            try:
                from core.agent_vector_memory import VectorMemory
                self._vector_memory = VectorMemory(self._mem_dir)
            except Exception as e:
                logger.error("[agent] 向量记忆加载失败: %s", e)
        return self._vector_memory

    def _search_memory(self, query: str, top_k: int = 3) -> str:
        """语义搜索历史记忆"""
        vm = self._get_vector_memory()
        if not vm:
            return ""
        results = vm.search(query, top_k=top_k)
        if not results:
            return ""
        lines = ["[相关记忆]"]
        for r in results:
            lines.append(f"  - {r['summary']} (相似度:{r['score']})")
        return "\n".join(lines)

    @staticmethod
    def _unwrap_reply(text: str) -> str:
        """部分免费模型喜欢把回复包成 JSON（如 {"回复":"..."} / {"预测结果":"..."}），这里做兼容解包。

        策略：已知键名(回复/reply/...)优先；若是单键对象则直接取唯一字符串值（兼容模型自定键名）；
        多键结构化 JSON 不破坏、原样返回。
        """
        if not text:
            return text
        t = text.strip()
        if t.startswith("{") and t.endswith("}"):
            try:
                d = json.loads(t)
                if isinstance(d, dict):
                    for k in ("回复", "reply", "answer", "response", "内容", "content"):
                        if k in d and isinstance(d[k], str):
                            return d[k].strip()
                    if len(d) == 1:
                        v = next(iter(d.values()))
                        if isinstance(v, str):
                            return v.strip()
            except Exception:
                pass
        return t

    def _chat_free(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> Optional[str]:
        """优先使用免费模型池进行对话，全挂则回退付费兜底。

        返回值：成功返回文本，失败返回 None（调用方再决定如何处理）。
        """
        try:
            from core.model_router import route
            text, err, meta = route("chat", system_prompt, user_prompt,
                                    max_tokens=max_tokens, temperature=0.7,
                                    force_json=False, data_len=len(user_prompt), timeout=60)
            if text and not err:
                self._last_model_used = meta.get("used")
                return self._unwrap_reply(text)
            logger.warning("[agent] 模型路由对话失败: %s meta=%s", err, meta)
        except Exception as e:
            logger.warning("[agent] 免费模型调用异常: %s", e)
        return None

    def _summarize_with_free(self, subsystem: str, user_input: str, data_result: str, max_chars: int = 5000) -> Optional[str]:
        """用免费模型池对子系统数据结果做专业总结（0成本），全挂返回 None 回退付费。

        免费小模型上下文有限，过长数据先截断到 max_chars 再喂，避免超窗或质量崩。
        """
        try:
            from core.model_router import route
            data_truncated = data_result
            if len(data_truncated) > max_chars:
                data_truncated = data_truncated[:max_chars] + "\n…(数据过长已截断)"
            system = (
                "你是金水谣万物引擎的AI分析助手，擅长彩票、股票、足球、音乐等领域的数据解读。"
                "请基于下方系统计算结果，用中文给出简洁专业的口语化总结，直接输出文本，不要返回 JSON 格式。"
            )
            user_prompt = f"用户问题：{user_input}\n\n系统数据结果：\n{data_truncated}"
            text, err, meta = route("data_summary", system, user_prompt,
                                    max_tokens=800, temperature=0.3,
                                    force_json=False, data_len=len(data_truncated), timeout=90)
            if text and not err:
                self._last_model_used = meta.get("used")
                return self._unwrap_reply(text)
            logger.warning("[agent] 模型路由总结失败: %s meta=%s", err, meta)
        except Exception as e:
            logger.warning("[agent] 免费模型总结异常: %s", e)
        return None

    def _review_with_free(self, subsystem: str, user_input: str, data_result: str, draft: str) -> Optional[str]:
        """多角色协作：让免费模型再「审一遍」初稿（生成角色 + 复核角色），0成本。

        返回带复核补充的文本，或 None（主流程不动初稿）。失败不影响主流程。
        """
        if not self._enable_review:
            return None
        try:
            from core.model_router import route
            data_truncated = data_result
            if len(data_truncated) > 3000:
                data_truncated = data_truncated[:3000] + "\n…(数据过长已截断)"
            system = (
                "你是严谨的复核员。下面有一份基于真实数据的初稿，请检查两点："
                "(1)初稿是否与数据矛盾；(2)是否遗漏重要风险提示（如彩票/投资须理性、过往不代表未来）。"
                "若初稿合格，只回复「OK」；若需补充，用一句话补充最关键的一点（不要重写全文），直接输出文本，不要返回 JSON 格式。"
            )
            user_prompt = f"用户问题：{user_input}\n\n系统数据：\n{data_truncated}\n\n初稿：\n{draft}"
            text, err, meta = route("review", system, user_prompt,
                                    max_tokens=200, temperature=0.2,
                                    force_json=False, data_len=len(data_truncated), timeout=60)
            if text and not err:
                note = self._unwrap_reply(text).strip()
                if note and note.upper() != "OK":
                    return draft + "\n\n（复核补充：" + note + "）"
        except Exception as e:
            logger.warning("[agent] 免费模型复核异常(忽略): %s", e)
        return None

    def _classify_intent_free(self, text: str) -> Optional[str]:
        """无法识别意图时用免费模型判断子系统归属（0成本），失败返回 None。"""
        try:
            from core.model_router import route
            system = "你是意图分类器。只回复一个英文词：lottery/stock/football/music/system/general/knowledge/video/creator。不要解释，不要 JSON。"
            text_out, err, meta = route("classify", system, text, timeout=30, max_tokens=16, temperature=0.1, force_json_mode=False)
            if text_out and not err:
                val = self._unwrap_reply(text_out).strip().lower()
                # 宽松匹配：返回中含任一已知子系统词即认（兼容模型带引号/解释文字）
                for sub in ("lottery", "stock", "football", "music", "system", "general", "knowledge", "video", "creator"):
                    if sub in val:
                        return sub
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 意图识别
    # ------------------------------------------------------------------

    def _parse_intent(self, text: str) -> Tuple[str, str, str]:
        """识别用户意图

        Returns:
            (subsystem, action, target) 三元组
        """
        text_lower = text.lower().strip()

        # 优先精确匹配
        best_match = None
        best_score = 0

        for keywords, subsystem, action, target in _INTENT_RULES:
            # 权重 = 命中关键词「字数之和」：更长的词=更具体=信号更强，
            # 解决「搜索知识库里的彩票风险」被短词「彩票」抢走的平局问题
            score = sum(len(kw) for kw in keywords if kw.lower() in text_lower)
            if score > best_score:
                best_score = score
                best_match = (subsystem, action, target)

        if best_match and best_score > 0:
            return best_match

        # 无法识别时优先用免费模型判断（0成本）
        intent = self._classify_intent_free(text)
        if intent:
            return (intent, "general", "用户自定义问题")

        # 免费全挂再回退付费（极少触发）
        ai = self._get_ai()
        if ai and ai.is_available:
            intent = ai.quick("general",
                f"用户说：'{text}'\n"
                f"请判断属于哪个子系统：lottery/stock/football/music/system/general\n"
                f"只回复子系统英文名，不要其他内容")
            if intent and intent.strip().lower() in ("lottery", "stock", "football", "music", "system", "knowledge", "video", "creator"):
                return (intent.strip().lower(), "general", "用户自定义问题")

        return ("general", "chat", "通用对话")

    # ------------------------------------------------------------------
    # URL检测与提取归档（委托到 core/agent_video_handler.py + core/agent_knowledge_archiver.py）
    # ------------------------------------------------------------------

    def _detect_urls(self, text: str) -> list:
        """检测文本中的URL（委托）"""
        from core.agent_video_handler import detect_urls
        return detect_urls(text)

    def _detect_video_platform_keywords(self, text: str) -> bool:
        """检测是否包含视频平台关键词（委托）"""
        from core.agent_video_handler import detect_video_platform_keywords
        return detect_video_platform_keywords(text)

    def _extract_and_archive_url(self, url: str, auto_archive: bool = True) -> dict:
        """提取URL内容并归档到知识库（委托）"""
        from core.agent_video_handler import extract_and_archive_url
        return extract_and_archive_url(self, url, auto_archive)

    def _archive_refined_to_knowledge(self, refined_card: dict) -> str:
        """将提炼结果归档到知识库（委托）"""
        from core.agent_knowledge_archiver import archive_refined_to_knowledge
        return archive_refined_to_knowledge(self, refined_card)

    def _infer_domain_from_content(self, text: str) -> str:
        """根据内容关键词推断领域（委托）"""
        from core.agent_knowledge_archiver import infer_domain_from_content
        return infer_domain_from_content(text)

    # ------------------------------------------------------------------
    # 子系统调度（全部薄委托到独立 deploy_* 模块）
    # ------------------------------------------------------------------

    def _dispatch_lottery(self, action: str, target: str, user_input: str = "") -> str:
        """调度彩票子系统（委托到 core/dispatch_lottery.py）"""
        from core.dispatch_lottery import dispatch_lottery as _dl
        return _dl(self, action, target, user_input)

    def _is_direct_lottery_request(self, text: str) -> bool:
        """判断是否为直接的彩票预测请求（委托到 core/dispatch_lottery.py）"""
        from core.dispatch_lottery import is_direct_lottery_request as _idl
        return _idl(self, text)

    def _dispatch_stock(self, action: str, target: str) -> str:
        """调度股票子系统（委托到 core/dispatch_stock.py）"""
        from core.dispatch_stock import dispatch_stock as _ds
        return _ds(self, action, target)

    def _dispatch_football(self, action: str, target: str) -> str:
        """调度足彩子系统（委托到 core/dispatch_football.py）"""
        from core.dispatch_football import dispatch_football as _df
        return _df(self, action, target)

    def _dispatch_music(self, action: str, target: str) -> str:
        """调度音乐子系统（委托到 core/dispatch_music.py）"""
        from core.dispatch_music import dispatch_music as _dm
        return _dm(self, action, target)

    def _dispatch_creator(self, action: str, target: str) -> str:
        """调度创作者工具箱子系统（委托到 core/dispatch_creator.py）"""
        from core.dispatch_creator import dispatch_creator as _dc
        return _dc(self, action, target)

    def _dispatch_video(self, action: str, target: str, user_input: str = "") -> str:
        """调度视频文案提取子系统（委托到 core/dispatch_video.py）"""
        from core.dispatch_video import dispatch_video as _dv
        return _dv(self, action, target, user_input)

    def _handle_video_url(self, url: str, auto_archive: bool = False) -> str:
        """处理视频URL，提取内容并可选归档（委托到 core/agent_video_handler.py）"""
        from core.agent_video_handler import handle_video_url
        return handle_video_url(self, url, auto_archive)

    def _dispatch_knowledge(self, action: str, target: str, user_input: str = "") -> str:
        """调度知识库子系统（委托到 core/dispatch_knowledge.py）"""
        from core.dispatch_knowledge import dispatch_knowledge as _dk
        return _dk(self, action, target, user_input)

    def _dispatch_system(self, action: str, target: str) -> str:
        """调度系统管理（委托到 core/dispatch_system.py）"""
        from core.dispatch_system import dispatch_system as _ds
        return _ds(self, action, target)

    def _dispatch_web(self, action: str, target: str, user_input: str = "") -> str:
        """联网搜索（进化·上网求证 / JS-20260727-31）。返回格式化结果文本，失败给出友好提示。"""
        from core.agent_web_search import web_search, format_results
        # 查询词：去掉触发词，取用户原意
        q = user_input
        for trigger in ("上网查", "上网搜索", "网络搜索", "搜一下", "搜索", "查一下",
                        "查证", "求证", "最新消息", "最新资讯", "新闻", "查资料", "资料",
                        "百度一下", "谷歌一下", "实时"):
            q = q.replace(trigger, "")
        q = q.strip()
        if not q:
            q = user_input
        res = web_search(q, max_results=5)
        return format_results(q, res)

    # ------------------------------------------------------------------
    # 推理入口（多Agent编排，与 chat 并行可用）
    # ------------------------------------------------------------------

    def reason(self, user_input: str) -> str:
        """使用多Agent编排处理复杂问题

        与 chat() 的区别:
          - chat(): 原流程，适合快速问答
          - reason(): 多Agent流水线，适合复杂分析
        """
        try:
            from core.agent_orchestrator import AgentOrchestrator
            orchestrator = AgentOrchestrator(self)
            return orchestrator.process(user_input)
        except Exception as e:
            logger.error("[agent] 多Agent编排失败，回退chat: %s", e)
            return self.chat(user_input)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def chat(self, user_input: str) -> str:
        """处理用户输入，返回回复

        Args:
            user_input: 用户自然语言输入

        Returns:
            AI回复文本
        """
        if not user_input or not user_input.strip():
            return "请输入你想了解的内容。"

        user_input = user_input.strip()
        self._last_model_used = None  # 本次对话最终使用的模型(free/paid/local)，供前端状态标签展示

        # 特殊指令：清空历史
        if user_input == "__clear_history__":
            self.clear_history()
            return "__cleared__"

        self._chat_lock.acquire()  # 并发安全：串行化 chat 防止共享态交错/撕裂
        try:
            # 主动提醒：对话开始先取出待提醒，助手主动开口
            self._pending_reminders = self._pop_pending_reminders()

            # 记忆命令（记住/回忆/忘掉）优先处理
            mem_resp = self._handle_memory_command(user_input)
            if mem_resp is not None:
                self._history.append(("user", user_input))
                self._history.append(("assistant", mem_resp))
                return self._with_reminders(mem_resp)

            # 记录历史
            self._history.append(("user", user_input))
            if len(self._history) > self._max_history * 2:
                self._history = self._history[-self._max_history * 2:]

            # 1. 意图识别
            subsystem, action, target = self._parse_intent(user_input)

            # 待办查询：用户主动问「有什么提醒 / 待办」
            if subsystem == "system" and action == "reminders":
                resp = self._render_reminder_list()
                self._history.append(("user", user_input))
                self._history.append(("assistant", resp))
                return resp

            # 0. URL自动检测：检测用户输入是否包含URL
            urls = self._detect_urls(user_input)
            has_video_kw = self._detect_video_platform_keywords(user_input)
            if urls and (has_video_kw or subsystem in ("video", "knowledge")):
                try:
                    url = urls[0]
                    auto_archive = ("存入知识库" in user_input or "归档" in user_input or
                                   "保存" in user_input)
                    data_result = self._handle_video_url(url, auto_archive=auto_archive)
                    self._history.append(("assistant", data_result))
                    return self._with_reminders(data_result)
                except Exception as e:
                    logger.error("[agent] URL自动处理失败: %s", e)

            # 2. 子系统调度获取数据
            data_result = ""
            if subsystem == "lottery":
                data_result = self._dispatch_lottery(action, target, user_input=user_input)
            elif subsystem == "stock":
                data_result = self._dispatch_stock(action, target)
            elif subsystem == "football":
                data_result = self._dispatch_football(action, target)
            elif subsystem == "music":
                data_result = self._dispatch_music(action, target)
            elif subsystem == "video":
                data_result = self._dispatch_video(action, target, user_input=user_input)
            elif subsystem == "creator":
                data_result = self._dispatch_creator(action, target)
            elif subsystem == "knowledge":
                data_result = self._dispatch_knowledge(action, target, user_input=user_input)
            elif subsystem == "system":
                # 配色意图需用户原话（含文件路径/七色/浅色等关键词），其余用规则 target
                _sys_target = user_input if action == "theme" else target
                data_result = self._dispatch_system(action, _sys_target)
            elif subsystem == "web":
                data_result = self._dispatch_web(action, target, user_input=user_input)

            # 联网搜索失败：直接返回友好提示，不浪费免费模型去"总结"一条报错
            if subsystem == "web" and data_result.startswith("⚠️ 联网搜索暂不可用"):
                self._history.append(("assistant", data_result))
                return self._with_reminders(data_result)

            # 3. 如果是系统命令或知识库命令，直接返回
            if subsystem in ("system", "knowledge"):
                # 知识库查询类动作：用知识网关四源召回补充（卡片+三元组+向量+经验+项目文档），
                # 让"搜索知识 xxx/查项目记忆/查风险/查总索引"不再是单文件搜索。
                if subsystem == "knowledge" and action in ("search", "project_memory", "risk_register", "total_index"):
                    try:
                        from core.knowledge_gateway import summarize
                        gw_text = summarize(user_input, limit=5)
                        if gw_text:
                            data_result += "\n\n【知识网关补充·四源召回】\n" + gw_text
                    except Exception:
                        pass
                self._history.append(("assistant", data_result))
                return self._with_reminders(data_result)

            # 4. 有数据结果时，优先免费模型总结（0成本），失败回退付费
            if data_result:
                free_summary = self._summarize_with_free(subsystem, user_input, data_result)
                if free_summary:
                    # 多角色：生成角色出初稿后，复核角色再审一遍（0成本，失败不影响）
                    if self._enable_review:
                        reviewed = self._review_with_free(subsystem, user_input, data_result, free_summary)
                        if reviewed:
                            free_summary = reviewed
                    self._history.append(("assistant", free_summary))
                    return self._with_reminders(free_summary)

                ai = self._get_ai()
                if ai and ai.is_available:
                    enhanced = ai.analyze(
                        subsystem,
                        f"用户问题：{user_input}\n\n系统数据结果：\n{data_result}",
                        extra_system=(
                            "请基于系统数据结果回答用户问题。"
                            "数据为真实计算结果，必须以此为基础。"
                            "保持专业简洁，中文回答。"
                        )
                    )
                    if enhanced:
                        self._last_model_used = "paid"
                        self._history.append(("assistant", enhanced))
                        return self._with_reminders(enhanced)

                # AI不可用时直接返回原始数据
                self._history.append(("assistant", data_result))
                return self._with_reminders(data_result)

            # 5. 纯聊天/无法识别：优先走免费模型池（0成本），失败再回退付费
            system = (
                "你是金水谣万物引擎的AI助手，擅长彩票分析、股票行情、足球预测、系统运维。"
                "如果用户问的是你专业领域的问题但数据不足，请说明。"
                "如果用户问的是其他话题，可以适当回答但建议回归专业领域。"
                "回答简洁、口语化、中文，直接输出文本，不要返回 JSON 格式。"
            )
            # 注入项目级知识（知识网关四源召回：经验/卡片/项目文档，让助手懂"金水谣项目本身"）
            try:
                from core.knowledge_gateway import summarize
                gw_text = summarize(user_input, limit=4)
                if gw_text:
                    system += (
                        "\n\n以下是金水谣项目知识库中与该问题相关的线索"
                        "（经验/知识卡片/项目文档，回答项目相关问题时优先参考，无需提及来源）：\n"
                        + gw_text
                    )
            except Exception:
                pass
            # 注入长期记忆（"越来越懂你"）
            profile_memories = self._get_memories(limit=15)
            if profile_memories:
                system += ("\n\n你记着关于这个用户的事（自然融入回答，不要生硬罗列）：\n"
                           + "\n".join(f"- {m}" for m in profile_memories))
            context = "\n".join(
                f"{'用户' if r == 'user' else 'AI'}: {c}"
                for r, c in self._history[-6:]
            )
            free_response = self._chat_free(
                system,
                f"{context}\n用户: {user_input}\nAI:"
            )
            if free_response:
                self._history.append(("assistant", free_response))
                return self._with_reminders(free_response)

            # 免费全挂：回退旧版付费 AI 服务
            ai = self._get_ai()
            if ai and ai.is_available:
                response = ai.analyze(
                    "general",
                    user_input,
                    extra_system=system
                )
                self._last_model_used = "paid"
                self._history.append(("assistant", response or "抱歉，我暂时无法回答这个问题。"))
                return self._with_reminders(response) or "抱歉，我暂时无法回答这个问题。"

            # 区分两种真实原因，避免误导用户
            if not ai or not getattr(ai, 'api_key', None):
                return ("AI暂时不可用：免费模型池与付费兜底都连不上（多半是网络断开，或付费密钥未配置）。"
                        "预测/分析类功能仍可正常使用；自由聊天请检查网络或配置付费密钥后重试。")
            return ("AI对话暂时连不上：免费模型池全挂且付费接口也不可用（熔断保护已开启）。"
                    "预测/分析类功能不受影响，请稍后重试。")

        except Exception as e:
            logger.error("[agent] chat异常: %s\n%s", e, traceback.format_exc())
            return "抱歉，处理出现异常，请稍后重试。"
        finally:
            self._save_history()
            # 自动存入向量记忆（最近一次对话）
            try:
                vm = self._get_vector_memory()
                if vm and len(self._history) >= 2:
                    last_pair = self._history[-2:]
                    if len(last_pair) == 2:
                        q_text = last_pair[0][1]
                        a_text = last_pair[1][1]
                        vm.store(q_text, summary=a_text[:100], source="user_history")
            except Exception:
                pass
            self._chat_lock.release()

    def clear_history(self):
        """清空对话历史（并落盘）"""
        self._history = []
        self._save_history()

    # ------------------------------------------------------------------
    # 主动提醒（进化·进阶1）：pop 待提醒 + 注入 + 待办查询
    # ------------------------------------------------------------------
    def _pop_pending_reminders(self) -> list:
        """对话开始时取出待提醒（并清空），让助手主动开口。"""
        try:
            from core.agent_reminder import pop_pending
            return pop_pending(self._mem_dir)
        except Exception:
            return []

    def _with_reminders(self, text: str) -> str:
        """把待提醒作为前缀附加到正常回复（主动服务，不骚扰：仅当确有提醒时）。"""
        if not self._pending_reminders or not text:
            return text
        prefix = ("🔔 你有 " + str(len(self._pending_reminders)) + " 条待提醒：\n"
                  + "\n".join(f"- {t}" for t in self._pending_reminders))
        return prefix + "\n\n" + text

    def _render_reminder_list(self) -> str:
        """用户主动问「有什么提醒」时列出当前待提醒。"""
        if not self._pending_reminders:
            return "🔔 当前没有待提醒的事。你可以用「记住：每天X点做Y」让我到点主动提醒你。"
        return ("🔔 你有 " + str(len(self._pending_reminders)) + " 条待提醒：\n"
                + "\n".join(f"- {t}" for t in self._pending_reminders))

    # ------------------------------------------------------------------
    # 记忆持久化（重启不丢 + 越来越懂你）
    # ------------------------------------------------------------------
    def _ensure_mem_dir(self):
        try:
            os.makedirs(self._mem_dir, exist_ok=True)
        except Exception:
            pass

    def _load_history(self):
        """启动时从磁盘恢复对话历史。"""
        try:
            if os.path.exists(self._history_file):
                with open(self._history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    hist = [(r, c) for r, c in data if r in ("user", "assistant")]
                    if len(hist) > self._max_history * 2:
                        hist = hist[-self._max_history * 2:]
                    self._history = hist
        except Exception as e:
            logger.warning("[agent] 加载对话历史失败: %s", e)
            self._history = []

    def _save_history(self):
        """对话历史落盘（原子写 + 进程内锁，异常不影响主流程）。"""
        with self._mem_lock:
            try:
                self._ensure_mem_dir()
                hist = self._history[-self._max_history * 2:]
                safe_write_json(self._history_file, hist)
            except Exception as e:
                logger.warning("[agent] 保存对话历史失败: %s", e)

    def _load_profile(self):
        """启动时从磁盘恢复用户画像。"""
        try:
            if os.path.exists(self._profile_file):
                with open(self._profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._profile = data
        except Exception as e:
            logger.warning("[agent] 加载用户画像失败: %s", e)
            self._profile = {}

    def _save_profile(self, locked=False):
        """用户画像落盘（原子写 + 进程内锁）。locked=True 表示调用方已持锁，避免重复 acquire 导致死锁。"""
        if locked:
            try:
                self._ensure_mem_dir()
                safe_write_json(self._profile_file, self._profile)
            except Exception as e:
                logger.warning("[agent] 保存用户画像失败: %s", e)
        else:
            with self._mem_lock:
                try:
                    self._ensure_mem_dir()
                    safe_write_json(self._profile_file, self._profile)
                except Exception as e:
                    logger.warning("[agent] 保存用户画像失败: %s", e)

    def _add_memory(self, content: str):
        """追加一条长期记忆（带时间戳），超量删最旧。改 + 存 在同一把锁内完成，避免并发丢记忆/迭代中改字典；locked=True 防止重入死锁。"""
        with self._mem_lock:
            self._profile.setdefault("memories", [])
            self._profile["memories"].append({
                "text": content,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            if len(self._profile["memories"]) > 200:
                self._profile["memories"] = self._profile["memories"][-200:]
            self._save_profile(locked=True)

    def _get_memories(self, limit: int = 15) -> list:
        """返回记忆文本列表（默认最近 limit 条）。加锁读，避免与 _add_memory 并发时读到半更新状态。"""
        with self._mem_lock:
            mems = self._profile.get("memories", [])
            texts = [m["text"] for m in mems if isinstance(m, dict) and m.get("text")]
            if limit and len(texts) > limit:
                texts = texts[-limit:]
            return texts

    def _remove_memory(self, keyword: str) -> list:
        """删除含关键词的记忆，返回被删文本列表。读改写在同一把锁内完成（与 _add_memory 一致，
        JS-20260730-04 G2）；RLock 可重入，_save_profile(locked=True) 不会死锁。"""
        with self._mem_lock:
            mems = self._profile.get("memories", [])
            kw = keyword.strip().lower()
            kept, removed = [], []
            for m in mems:
                if isinstance(m, dict) and kw and kw in (m.get("text") or "").lower():
                    removed.append(m)
                else:
                    kept.append(m)
            if removed:
                self._profile["memories"] = kept
                self._save_profile(locked=True)
            return [m.get("text", "") for m in removed]

    def _handle_memory_command(self, text: str) -> Optional[str]:
        """处理记忆类元命令：记住 / 回忆 / 忘掉。非记忆命令返回 None。"""
        t = text.strip()
        # 记住
        m = re.match(r'^(记住|记一下|记着|谨记|记住这个)[:：]?\s*(.+)$', t)
        if m:
            content = m.group(2).strip()
            if not content:
                return "你想让我记住什么？请说：记住 你的内容"
            self._add_memory(content)
            return f"✅ 已记住：{content}\n（已落盘，重启也不会丢）"
        # 回忆 / 记得
        if (re.search(r'(你还?记得|回忆|想起来|你?\s*记得吗|我的偏好|关于我)', t)
                or t.startswith("回忆") or t.startswith("记得") or t.startswith("我的记忆")):
            memories = self._get_memories(limit=50)
            if not memories:
                return "我目前还没有存下关于你的记忆。你可以说「记住：xxx」让我记着。"
            return "📝 我记着的关于你的事：\n" + "\n".join(
                f"{i+1}. {x}" for i, x in enumerate(memories))
        # 忘掉
        m2 = re.match(r'^(忘掉|忘记|删除记忆|清除记忆|忘了)[:：]?\s*(.+)$', t)
        if m2:
            kw = m2.group(2).strip()
            removed = self._remove_memory(kw)
            if removed:
                return (f"🗑️ 已删除 {len(removed)} 条匹配「{kw}」的记忆：\n"
                        + "\n".join(f"- {x}" for x in removed))
            return f"没找到匹配「{kw}」的记忆。"
        return None


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_agent_instance: Optional[JinshuiyaoAgent] = None


def get_agent() -> JinshuiyaoAgent:
    """获取全局AI体单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = JinshuiyaoAgent()
    return _agent_instance
