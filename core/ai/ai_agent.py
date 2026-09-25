# -*- coding: utf-8 -*-
"""金水谣引擎 - 智能AI体核心

统一的自然语言交互入口，用户通过对话直接调用所有子系统功能。
支持彩票预测、股票行情、足彩分析、系统管理等。

架构：
  用户输入 → 意图识别 → 子系统调度 → 数据获取 → AI总结 → 返回结果

使用方式：
    from core.ai.ai_agent import JinshuiyaoAgent
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
# JS-20260925-06：档案清理唯一真源，禁止各写一份 [-N:] 尾部截断
from core.infra.archive_guard import trim_archive as _guard_trim_archive

logger = logging.getLogger(__name__)

# 用户记忆是累积档案：原硬编码 200 会导致「加一条丢一条」。
# 条数上限只作兜底（防 profile 无限膨胀），清理委托 archive_guard 保证不骤降。
AGENT_MEM_KEEP_DAYS = 1095        # 按时间保留：3 年
AGENT_MEM_MAX_RECORDS = 20000     # 条数兜底上限

# ---------------------------------------------------------------------------
# 意图关键词映射（已拆分到 core/ai/intent_rules.py）
# ---------------------------------------------------------------------------
from core.ai.intent_rules import INTENT_RULES as _INTENT_RULES, VIDEO_PLATFORM_KEYWORDS

# ---------------------------------------------------------------------------
# 结果格式化（已拆分到 core/ai/agent_formatters.py）
# ---------------------------------------------------------------------------
from core.ai.agent_formatters import (
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


# ===========================================================================
# 模块级函数（从 JinshuiyaoAgent 抽出，self 作为首参传入）
# ===========================================================================

def _aa_get_ai(self):
    """延迟加载AIService"""
    if self._ai is None:
        try:
            from core.ai.ai_service import get_ai_service
            self._ai = get_ai_service()
        except Exception as e:
            logger.error("[agent] AI服务加载失败: %s", e)
    return self._ai


def _aa_get_domain(self, name: str):
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
            elif name == "fund":
                from domains.fund.domain import FundDomain
                self._domains[name] = FundDomain()
            elif name == "music":
                from domains.music.domain import MusicDomain
                self._domains[name] = MusicDomain()
            elif name == "creator":
                from domains.creator.domain import CreatorDomain
                self._domains[name] = CreatorDomain()
            else:
                return None
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


def _aa_get_knowledge_db(self):
    if self._knowledge_db is None:
        try:
            from knowledge.mirofish_db import MiroFishDB
            self._knowledge_db = MiroFishDB()
        except Exception as e:
            logger.error("[agent] 知识库加载失败: %s", e)
    return self._knowledge_db


def _aa_get_video_extractor(self):
    if self._video_extractor is None:
        try:
            from core.infra.video_extractor import VideoExtractor
            self._video_extractor = VideoExtractor()
        except Exception as e:
            logger.error("[agent] 视频提取器加载失败: %s", e)
    return self._video_extractor


def _aa_get_content_refiner(self):
    if self._content_refiner is None:
        try:
            from core.ai.content_refiner import ContentRefiner
            self._content_refiner = ContentRefiner()
        except Exception as e:
            logger.error("[agent] 内容提炼器加载失败: %s", e)
    return self._content_refiner


def _aa_get_vector_memory(self):
    if self._vector_memory is None:
        try:
            from core.ai.agent_vector_memory import VectorMemory
            self._vector_memory = VectorMemory(self._mem_dir)
        except Exception as e:
            logger.error("[agent] 向量记忆加载失败: %s", e)
    return self._vector_memory


def _aa_search_memory(self, query: str, top_k: int = 3) -> str:
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


def _aa_unwrap_reply(text: str) -> str:
    """部分免费模型把回复包成 JSON，做兼容解包。"""
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
        except Exception as e:
            logger.debug("[agent] JSON解包异常: %s", e)
    return t


def _aa_chat_free(self, system_prompt: str, user_prompt: str, max_tokens: int = 800) -> Optional[str]:
    try:
        from core.ai.model_router import route
        text, err, meta = route("chat", system_prompt, user_prompt,
                                max_tokens=max_tokens, temperature=0.7,
                                force_json=False, data_len=len(user_prompt), timeout=60)
        if text and not err:
            self._last_model_used = meta.get("used")
            return _aa_unwrap_reply(text)
        logger.warning("[agent] 模型路由对话失败: %s meta=%s", err, meta)
    except Exception as e:
        logger.warning("[agent] 免费模型调用异常: %s", e)
    return None


def _aa_summarize_with_free(self, subsystem: str, user_input: str, data_result: str,
                            max_chars: int = 5000) -> Optional[str]:
    try:
        from core.ai.model_router import route
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
            return _aa_unwrap_reply(text)
        logger.warning("[agent] 模型路由总结失败: %s meta=%s", err, meta)
    except Exception as e:
        logger.warning("[agent] 免费模型总结异常: %s", e)
    return None


def _aa_review_with_free(self, subsystem: str, user_input: str, data_result: str, draft: str) -> Optional[str]:
    if not self._enable_review:
        return None
    try:
        from core.ai.model_router import route
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
            note = _aa_unwrap_reply(text).strip()
            if note and note.upper() != "OK":
                return draft + "\n\n（复核补充：" + note + "）"
    except Exception as e:
        logger.warning("[agent] 免费模型复核异常(忽略): %s", e)
    return None


def _aa_classify_intent_free(self, text: str) -> Optional[str]:
    try:
        from core.ai.model_router import route
        system = "你是意图分类器。只回复一个英文词：lottery/stock/football/music/system/general/knowledge/video/creator。不要解释，不要 JSON。"
        text_out, err, meta = route("classify", system, text, timeout=30, max_tokens=16, temperature=0.1, force_json_mode=False)
        if text_out and not err:
            val = _aa_unwrap_reply(text_out).strip().lower()
            for sub in ("lottery", "stock", "football", "music", "system", "general", "knowledge", "video", "creator", "fund"):
                if sub in val:
                    return sub
    except Exception as e:
        logger.debug("[agent] 免费意图分类异常: %s", e)
    return None


def _aa_parse_intent(self, text: str) -> Tuple[str, str, str]:
    text_lower = text.lower().strip()
    best_match = None
    best_score = 0
    for keywords, subsystem, action, target in _INTENT_RULES:
        score = sum(len(kw) for kw in keywords if kw.lower() in text_lower)
        if score > best_score:
            best_score = score
            best_match = (subsystem, action, target)
    if best_match and best_score > 0:
        return best_match
    intent = _aa_classify_intent_free(self, text)
    if intent:
        return (intent, "general", "用户自定义问题")
    ai = _aa_get_ai(self)
    if ai and ai.is_available:
        intent = ai.quick("general",
            f"用户说：'{text}'\n"
            f"请判断属于哪个子系统：lottery/stock/football/music/system/general\n"
            f"只回复子系统英文名，不要其他内容")
        if intent and intent.strip().lower() in ("lottery", "stock", "football", "music", "system", "knowledge", "video", "creator", "fund"):
            return (intent.strip().lower(), "general", "用户自定义问题")
    return ("general", "chat", "通用对话")


# ---- URL检测与提取归档（委托） ----
def _aa_detect_urls(self, text: str) -> list:
    from core.ai.agent_video_handler import detect_urls
    return detect_urls(text)


def _aa_detect_video_platform_keywords(self, text: str) -> bool:
    from core.ai.agent_video_handler import detect_video_platform_keywords
    return detect_video_platform_keywords(text)


def _aa_extract_and_archive_url(self, url: str, auto_archive: bool = True) -> dict:
    from core.ai.agent_video_handler import extract_and_archive_url
    return extract_and_archive_url(self, url, auto_archive)


def _aa_archive_refined_to_knowledge(self, refined_card: dict) -> str:
    from core.ai.agent_knowledge_archiver import archive_refined_to_knowledge
    return archive_refined_to_knowledge(self, refined_card)


def _aa_infer_domain_from_content(self, text: str) -> str:
    from core.ai.agent_knowledge_archiver import infer_domain_from_content
    return infer_domain_from_content(text)


# ---- 子系统调度（薄委托） ----
def _aa_dispatch_lottery(self, action: str, target: str, user_input: str = "") -> str:
    from core.dispatch.dispatch_lottery import dispatch_lottery as _dl
    return _dl(self, action, target, user_input)


def _aa_is_direct_lottery_request(self, text: str) -> bool:
    from core.dispatch.dispatch_lottery import is_direct_lottery_request as _idl
    return _idl(self, text)


def _aa_dispatch_stock(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_stock import dispatch_stock as _ds
    return _ds(self, action, target)


def _aa_dispatch_fund(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_fund import dispatch_fund as _df
    return _df(self, action, target)


def _aa_dispatch_football(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_football import dispatch_football as _df
    return _df(self, action, target)


def _aa_dispatch_music(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_music import dispatch_music as _dm
    return _dm(self, action, target)


def _aa_dispatch_creator(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_creator import dispatch_creator as _dc
    return _dc(self, action, target)


def _aa_dispatch_video(self, action: str, target: str, user_input: str = "") -> str:
    from core.dispatch.dispatch_video import dispatch_video as _dv
    return _dv(self, action, target, user_input)


def _aa_handle_video_url(self, url: str, auto_archive: bool = False) -> str:
    from core.ai.agent_video_handler import handle_video_url
    return handle_video_url(self, url, auto_archive)


def _aa_dispatch_knowledge(self, action: str, target: str, user_input: str = "") -> str:
    from core.dispatch.dispatch_knowledge import dispatch_knowledge as _dk
    return _dk(self, action, target, user_input)


def _aa_dispatch_system(self, action: str, target: str) -> str:
    from core.dispatch.dispatch_system import dispatch_system as _ds
    return _ds(self, action, target)


def _aa_dispatch_web(self, action: str, target: str, user_input: str = "") -> str:
    from core.ai.agent_web_search import web_search, format_results
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


def _aa_reason(self, user_input: str) -> str:
    try:
        from core.ai.agent_orchestrator import AgentOrchestrator
        orchestrator = AgentOrchestrator(self)
        return orchestrator.process(user_input)
    except Exception as e:
        logger.error("[agent] 多Agent编排失败，回退chat: %s", e)
        return self.chat(user_input)


# ---- 主动提醒 ----
def _aa_pop_pending_reminders(self) -> list:
    try:
        from core.ai.agent_reminder import pop_pending
        return pop_pending(self._mem_dir)
    except Exception:
        return []


def _aa_with_reminders(self, text: str) -> str:
    if not self._pending_reminders or not text:
        return text
    prefix = ("🔔 你有 " + str(len(self._pending_reminders)) + " 条待提醒：\n"
              + "\n".join(f"- {t}" for t in self._pending_reminders))
    return prefix + "\n\n" + text


def _aa_render_reminder_list(self) -> str:
    if not self._pending_reminders:
        return "🔔 当前没有待提醒的事。你可以用「记住：每天X点做Y」让我到点主动提醒你。"
    return ("🔔 你有 " + str(len(self._pending_reminders)) + " 条待提醒：\n"
            + "\n".join(f"- {t}" for t in self._pending_reminders))


# ---- 记忆持久化 ----
def _aa_ensure_mem_dir(self):
    try:
        os.makedirs(self._mem_dir, exist_ok=True)
    except Exception as e:
        logger.debug("[agent] 创建记忆目录失败: %s", e)


def _aa_load_history(self):
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


def _aa_save_history(self):
    with self._mem_lock:
        try:
            _aa_ensure_mem_dir(self)
            hist = self._history[-self._max_history * 2:]
            safe_write_json(self._history_file, hist)
        except Exception as e:
            logger.warning("[agent] 保存对话历史失败: %s", e)


def _aa_load_profile(self):
    try:
        if os.path.exists(self._profile_file):
            with open(self._profile_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._profile = data
    except Exception as e:
        logger.warning("[agent] 加载用户画像失败: %s", e)
        self._profile = {}


def _aa_save_profile(self, locked=False):
    if locked:
        try:
            _aa_ensure_mem_dir(self)
            safe_write_json(self._profile_file, self._profile)
        except Exception as e:
            logger.warning("[agent] 保存用户画像失败: %s", e)
    else:
        with self._mem_lock:
            try:
                _aa_ensure_mem_dir(self)
                safe_write_json(self._profile_file, self._profile)
            except Exception as e:
                logger.warning("[agent] 保存用户画像失败: %s", e)


def _aa_add_memory(self, content: str):
    with self._mem_lock:
        self._profile.setdefault("memories", [])
        self._profile["memories"].append({
            "text": content,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        # JS-20260925-06：委托 archive_guard，条数骤降时放弃本次截断（保留原记忆）
        kept, _b, _a, blocked = _guard_trim_archive(
            self._profile["memories"], keep_days=AGENT_MEM_KEEP_DAYS,
            max_records=AGENT_MEM_MAX_RECORDS, label="用户记忆")
        if not blocked:
            self._profile["memories"] = kept
        _aa_save_profile(self, locked=True)


def _aa_get_memories(self, limit: int = 15) -> list:
    with self._mem_lock:
        mems = self._profile.get("memories", [])
        texts = [m["text"] for m in mems if isinstance(m, dict) and m.get("text")]
        if limit and len(texts) > limit:
            texts = texts[-limit:]
        return texts


def _aa_remove_memory(self, keyword: str) -> list:
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
            _aa_save_profile(self, locked=True)
        return [m.get("text", "") for m in removed]


def _aa_handle_memory_command(self, text: str) -> Optional[str]:
    t = text.strip()
    m = re.match(r'^(记住|记一下|记着|谨记|记住这个)[:：]?\s*(.+)$', t)
    if m:
        content = m.group(2).strip()
        if not content:
            return "你想让我记住什么？请说：记住 你的内容"
        _aa_add_memory(self, content)
        return f"✅ 已记住：{content}\n（已落盘，重启也不会丢）"
    if (re.search(r'(你还?记得|回忆|想起来|你?\s*记得吗|我的偏好|关于我)', t)
            or t.startswith("回忆") or t.startswith("记得") or t.startswith("我的记忆")):
        memories = _aa_get_memories(self, limit=50)
        if not memories:
            return "我目前还没有存下关于你的记忆。你可以说「记住：xxx」让我记着。"
        return "📝 我记着的关于你的事：\n" + "\n".join(
            f"{i+1}. {x}" for i, x in enumerate(memories))
    m2 = re.match(r'^(忘掉|忘记|删除记忆|清除记忆|忘了)[:：]?\s*(.+)$', t)
    if m2:
        kw = m2.group(2).strip()
        removed = _aa_remove_memory(self, kw)
        if removed:
            return (f"🗑️ 已删除 {len(removed)} 条匹配「{kw}」的记忆：\n"
                    + "\n".join(f"- {x}" for x in removed))
        return f"没找到匹配「{kw}」的记忆。"
    return None


def _aa_clear_history(self):
    self._history = []
    _aa_save_history(self)


def _aa_init(self):
    """初始化 JinshuiyaoAgent 全部状态。"""
    self._domains = {}
    self._ai = None
    self._history = []
    self._max_history = 20
    self._mem_lock = threading.RLock()
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    self._mem_dir = os.path.join(_root, "金水谣数据", "agent_memory")
    self._history_file = os.path.join(self._mem_dir, "history.json")
    self._profile_file = os.path.join(self._mem_dir, "user_profile.json")
    self._profile = {}
    self._load_history()
    self._load_profile()
    self._initialized = {}
    self._knowledge_db = None
    self._video_extractor = None
    self._content_refiner = None
    self._last_extracted = None
    self._pending_reminders = []
    self._enable_review = True
    self._chat_lock = threading.RLock()
    self._vector_memory = None
    self._last_model_used = None


# ===========================================================================
# chat 主流程拆分
# ===========================================================================

def _aa_chat_dispatch(self, subsystem, action, target, user_input) -> str:
    """子系统调度：根据 subsystem 调用对应 dispatch，返回数据结果文本。"""
    if subsystem == "lottery":
        return _aa_dispatch_lottery(self, action, target, user_input=user_input)
    elif subsystem == "stock":
        return _aa_dispatch_stock(self, action, target)
    elif subsystem == "fund":
        return _aa_dispatch_fund(self, action, target)
    elif subsystem == "football":
        return _aa_dispatch_football(self, action, target)
    elif subsystem == "music":
        return _aa_dispatch_music(self, action, target)
    elif subsystem == "video":
        return _aa_dispatch_video(self, action, target, user_input=user_input)
    elif subsystem == "creator":
        return _aa_dispatch_creator(self, action, target)
    elif subsystem == "knowledge":
        return _aa_dispatch_knowledge(self, action, target, user_input=user_input)
    elif subsystem == "system":
        _sys_target = user_input if action == "theme" else target
        return _aa_dispatch_system(self, action, _sys_target)
    elif subsystem == "web":
        return _aa_dispatch_web(self, action, target, user_input=user_input)
    return ""


def _aa_chat_summarize(self, subsystem, user_input, data_result) -> Optional[str]:
    """有数据结果时：免费模型总结（0成本）+ 复核，失败回退付费 AI。返回回复或 None。"""
    free_summary = _aa_summarize_with_free(self, subsystem, user_input, data_result)
    if free_summary:
        if self._enable_review:
            reviewed = _aa_review_with_free(self, subsystem, user_input, data_result, free_summary)
            if reviewed:
                free_summary = reviewed
        return free_summary
    ai = _aa_get_ai(self)
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
            return enhanced
    return None


def _aa_chat_general(self, user_input) -> str:
    """纯聊天/无法识别：免费模型池优先，失败回退付费，最后给出不可用提示。"""
    system = (
        "你是金水谣万物引擎的AI助手，擅长彩票分析、股票行情、足球预测、系统运维。"
        "如果用户问的是你专业领域的问题但数据不足，请说明。"
        "如果用户问的是其他话题，可以适当回答但建议回归专业领域。"
        "回答简洁、口语化、中文，直接输出文本，不要返回 JSON 格式。"
    )
    try:
        from core.infra.knowledge_gateway import summarize
        gw_text = summarize(user_input, limit=4)
        if gw_text:
            system += (
                "\n\n以下是金水谣项目知识库中与该问题相关的线索"
                "（经验/知识卡片/项目文档，回答项目相关问题时优先参考，无需提及来源）：\n"
                + gw_text
            )
    except Exception as e:
        logger.debug("[agent] 知识网关注入异常: %s", e)
    profile_memories = _aa_get_memories(self, limit=15)
    if profile_memories:
        system += ("\n\n你记着关于这个用户的事（自然融入回答，不要生硬罗列）：\n"
                   + "\n".join(f"- {m}" for m in profile_memories))
    context = "\n".join(
        f"{'用户' if r == 'user' else 'AI'}: {c}"
        for r, c in self._history[-6:]
    )
    free_response = _aa_chat_free(self, system, f"{context}\n用户: {user_input}\nAI:")
    if free_response:
        return free_response
    ai = _aa_get_ai(self)
    if ai and ai.is_available:
        response = ai.analyze("general", user_input, extra_system=system)
        self._last_model_used = "paid"
        return response or "抱歉，我暂时无法回答这个问题。"
    if not ai or not getattr(ai, 'api_key', None):
        return ("AI暂时不可用：免费模型池与付费兜底都连不上（多半是网络断开，或付费密钥未配置）。"
                "预测/分析类功能仍可正常使用；自由聊天请检查网络或配置付费密钥后重试。")
    return ("AI对话暂时连不上：免费模型池全挂且付费接口也不可用（熔断保护已开启）。"
            "预测/分析类功能不受影响，请稍后重试。")


def _aa_chat_finally(self):
    """chat 的 finally 块：落盘历史 + 存向量记忆 + 释放锁。"""
    _aa_save_history(self)
    try:
        vm = _aa_get_vector_memory(self)
        if vm and len(self._history) >= 2:
            last_pair = self._history[-2:]
            if len(last_pair) == 2:
                q_text = last_pair[0][1]
                a_text = last_pair[1][1]
                vm.store(q_text, summary=a_text[:100], source="user_history")
    except Exception as e:
        logger.debug("[agent] 向量记忆存储异常: %s", e)
    self._chat_lock.release()


def _aa_chat_try_url(self, user_input, subsystem) -> Optional[str]:
    """URL 自动检测 + 视频提取。命中则返回回复文本，否则 None。"""
    urls = _aa_detect_urls(self, user_input)
    has_video_kw = _aa_detect_video_platform_keywords(self, user_input)
    if not urls or not (has_video_kw or subsystem in ("video", "knowledge")):
        return None
    try:
        url = urls[0]
        auto_archive = ("存入知识库" in user_input or "归档" in user_input or "保存" in user_input)
        data_result = _aa_handle_video_url(self, url, auto_archive=auto_archive)
        self._history.append(("assistant", data_result))
        return _aa_with_reminders(self, data_result)
    except Exception as e:
        logger.error("[agent] URL自动处理失败: %s", e)
        return None


def _aa_chat_system_knowledge(self, user_input, subsystem, action, data_result) -> Optional[str]:
    """system/knowledge 子系统直返（含知识网关四源补充）。命中则返回文本，否则 None。"""
    if subsystem not in ("system", "knowledge"):
        return None
    if subsystem == "knowledge" and action in ("search", "project_memory", "risk_register", "total_index"):
        try:
            from core.infra.knowledge_gateway import summarize
            gw_text = summarize(user_input, limit=5)
            if gw_text:
                data_result += "\n\n【知识网关补充·四源召回】\n" + gw_text
        except Exception as e:
            logger.debug("[agent] 知识网关补充异常: %s", e)
    self._history.append(("assistant", data_result))
    return _aa_with_reminders(self, data_result)


def _aa_chat(self, user_input: str) -> str:
    if not user_input or not user_input.strip():
        return "请输入你想了解的内容。"
    user_input = user_input.strip()
    self._last_model_used = None
    if user_input == "__clear_history__":
        _aa_clear_history(self)
        return "__cleared__"
    self._chat_lock.acquire()
    try:
        self._pending_reminders = _aa_pop_pending_reminders(self)
        mem_resp = _aa_handle_memory_command(self, user_input)
        if mem_resp is not None:
            self._history.append(("user", user_input))
            self._history.append(("assistant", mem_resp))
            return _aa_with_reminders(self, mem_resp)
        self._history.append(("user", user_input))
        if len(self._history) > self._max_history * 2:
            self._history = self._history[-self._max_history * 2:]
        subsystem, action, target = _aa_parse_intent(self, user_input)
        if subsystem == "system" and action == "reminders":
            resp = _aa_render_reminder_list(self)
            self._history.append(("user", user_input))
            self._history.append(("assistant", resp))
            return resp
        url_resp = _aa_chat_try_url(self, user_input, subsystem)
        if url_resp is not None:
            return url_resp
        data_result = _aa_chat_dispatch(self, subsystem, action, target, user_input)
        if subsystem == "web" and data_result.startswith("⚠️ 联网搜索暂不可用"):
            self._history.append(("assistant", data_result))
            return _aa_with_reminders(self, data_result)
        sk = _aa_chat_system_knowledge(self, user_input, subsystem, action, data_result)
        if sk is not None:
            return sk
        if data_result:
            summary = _aa_chat_summarize(self, subsystem, user_input, data_result)
            if summary:
                self._history.append(("assistant", summary))
                return _aa_with_reminders(self, summary)
            self._history.append(("assistant", data_result))
            return _aa_with_reminders(self, data_result)
        response = _aa_chat_general(self, user_input)
        self._history.append(("assistant", response))
        return _aa_with_reminders(self, response)
    except Exception as e:
        logger.error("[agent] chat异常: %s\n%s", e, traceback.format_exc())
        return "抱歉，处理出现异常，请稍后重试。"
    finally:
        _aa_chat_finally(self)


# ===========================================================================
# 薄包装类
# ===========================================================================

class JinshuiyaoAgent:
    """金水谣智能AI体 — 自然语言交互入口（方法委托模块级函数）。"""
    def __init__(self): _aa_init(self)
    def _get_ai(self): return _aa_get_ai(self)
    def _get_domain(self, name): return _aa_get_domain(self, name)
    def _get_knowledge_db(self): return _aa_get_knowledge_db(self)
    def _get_video_extractor(self): return _aa_get_video_extractor(self)
    def _get_content_refiner(self): return _aa_get_content_refiner(self)
    def _get_vector_memory(self): return _aa_get_vector_memory(self)
    def _search_memory(self, query, top_k=3): return _aa_search_memory(self, query, top_k)
    @staticmethod
    def _unwrap_reply(text): return _aa_unwrap_reply(text)
    def _chat_free(self, s, u, max_tokens=800): return _aa_chat_free(self, s, u, max_tokens)
    def _summarize_with_free(self, sub, ui, dr, mc=5000): return _aa_summarize_with_free(self, sub, ui, dr, mc)
    def _review_with_free(self, sub, ui, dr, d): return _aa_review_with_free(self, sub, ui, dr, d)
    def _classify_intent_free(self, text): return _aa_classify_intent_free(self, text)
    def _parse_intent(self, text): return _aa_parse_intent(self, text)
    def _detect_urls(self, text): return _aa_detect_urls(self, text)
    def _detect_video_platform_keywords(self, text): return _aa_detect_video_platform_keywords(self, text)
    def _extract_and_archive_url(self, url, auto_archive=True): return _aa_extract_and_archive_url(self, url, auto_archive)
    def _archive_refined_to_knowledge(self, card): return _aa_archive_refined_to_knowledge(self, card)
    def _infer_domain_from_content(self, text): return _aa_infer_domain_from_content(self, text)
    def _dispatch_lottery(self, a, t, user_input=""): return _aa_dispatch_lottery(self, a, t, user_input)
    def _is_direct_lottery_request(self, text): return _aa_is_direct_lottery_request(self, text)
    def _dispatch_stock(self, a, t): return _aa_dispatch_stock(self, a, t)
    def _dispatch_fund(self, a, t): return _aa_dispatch_fund(self, a, t)
    def _dispatch_football(self, a, t): return _aa_dispatch_football(self, a, t)
    def _dispatch_music(self, a, t): return _aa_dispatch_music(self, a, t)
    def _dispatch_creator(self, a, t): return _aa_dispatch_creator(self, a, t)
    def _dispatch_video(self, a, t, user_input=""): return _aa_dispatch_video(self, a, t, user_input)
    def _handle_video_url(self, url, auto_archive=False): return _aa_handle_video_url(self, url, auto_archive)
    def _dispatch_knowledge(self, a, t, user_input=""): return _aa_dispatch_knowledge(self, a, t, user_input)
    def _dispatch_system(self, a, t): return _aa_dispatch_system(self, a, t)
    def _dispatch_web(self, a, t, user_input=""): return _aa_dispatch_web(self, a, t, user_input)
    def reason(self, user_input): return _aa_reason(self, user_input)
    def chat(self, user_input): return _aa_chat(self, user_input)
    def clear_history(self): return _aa_clear_history(self)
    def _pop_pending_reminders(self): return _aa_pop_pending_reminders(self)
    def _with_reminders(self, text): return _aa_with_reminders(self, text)
    def _render_reminder_list(self): return _aa_render_reminder_list(self)
    def _ensure_mem_dir(self): return _aa_ensure_mem_dir(self)
    def _load_history(self): return _aa_load_history(self)
    def _save_history(self): return _aa_save_history(self)
    def _load_profile(self): return _aa_load_profile(self)
    def _save_profile(self, locked=False): return _aa_save_profile(self, locked)
    def _add_memory(self, content): return _aa_add_memory(self, content)
    def _get_memories(self, limit=15): return _aa_get_memories(self, limit)
    def _remove_memory(self, keyword): return _aa_remove_memory(self, keyword)
    def _handle_memory_command(self, text): return _aa_handle_memory_command(self, text)


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
