# -*- coding: utf-8 -*-
"""MiroFish 万物知识库 - 管理器
万物预测引擎的知识记忆层

知识卡片结构（PARA分类法 + 万物扩展）：
- category: PARA分类 (inspiration/project/area/resource/skill/archive)
- domain: 领域标签 (lottery/3d/football/music/general/...)
- tags: 自由标签列表
- value_level: 价值分层 (数据/信息/知识/智慧)
- content: 知识内容（文本）
- source: 来源（url/用户/自动复盘/...）
- source_url: 来源URL（如果从URL提取）
- extracted_at: 提取时间
- engine_hook: 引擎钩子（告诉预测引擎什么时候用这条知识）
- effectiveness: 有效性评分 0-100（使用后自动更新）
- use_count: 被引擎调用次数
- created/updated: 时间戳

核心功能：
1. add_card() - 添加知识卡片（支持AI自动提取）
2. search() - 搜索知识（按领域/标签/关键词/引擎钩子）
3. get_for_engine() - 引擎调用：根据当前场景获取相关知识
4. update_effectiveness() - 使用后更新有效性评分
5. import_from_text() - 从文本自动提取知识卡片
6. stats() - 知识库统计
"""
import os
import json
import time
import logging
import threading
from datetime import datetime
from collections import Counter

logger = logging.getLogger(__name__)

# 跨实例并发写锁：服务器线程化后，多个请求可能各自 new MiroFishDB() 并同时 add_card，
# 若不串行化，后保存者会覆盖先保存者的数据造成丢失。该锁保证 read-modify-write 原子。
_DB_WRITE_LOCK = threading.Lock()

# 默认数据库路径
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirofish_db.json")


class MiroFishDB:
    """MiroFish 万物知识库"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._data = self._load()

    def _load(self):
        """加载数据库"""
        default = {
            "version": "1.0.0",
            "name": "MiroFish 万物知识库",
            "cards": [],
            "stats": {"total_cards": 0, "by_category": {}, "by_domain": {}, "by_tag": {}, "by_value_level": {}}
        }
        if not os.path.exists(self.db_path):
            # 初始化空库
            return default
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("知识库加载失败: %s", e)
            return default

    def _save(self):
        """保存数据库（原子写入）"""
        self._update_stats()
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            try:
                from utils.safe_json import safe_write_json
                safe_write_json(self.db_path, self._data)
            except ImportError:
                # 降级为原子写入（手动实现）
                import tempfile
                fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.db_path))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(self._data, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, self.db_path)
                except Exception as e:
                    logger.warning("知识库加载失败，使用默认空库: %s", e)
                    try: os.unlink(tmp)
                    except Exception: pass
                    raise
            return True
        except IOError as e:
            logger.error("知识库保存失败: %s", e)
            return False

    def _update_stats(self):
        """更新统计信息"""
        cards = self._data.get("cards", [])
        by_cat = Counter(c.get("category", "unknown") for c in cards)
        by_dom = Counter(c.get("domain", "unknown") for c in cards)
        by_tag = Counter()
        by_value = Counter(c.get("value_level", "信息") for c in cards)
        for c in cards:
            for t in c.get("tags", []):
                by_tag[t] += 1

        self._data["stats"] = {
            "total_cards": len(cards),
            "by_category": dict(by_cat),
            "by_domain": dict(by_dom),
            "by_tag": dict(by_tag.most_common(50)),  # 最多50个标签
            "by_value_level": dict(by_value),
        }

    # ------------------------------------------------------------------
    # 核心操作
    # ------------------------------------------------------------------

    def add_card(self, title, content, category="inspiration", domain="general",
                 tags=None, source="用户输入", engine_hook=None, priority=5,
                 subsystem=None, value_level=None, source_url=None, extracted_at=None,
                 effectiveness=50):
        """添加一张知识卡片。

        Parameters
        ----------
        title : str
            知识标题（简短描述）
        content : str
            知识内容（详细描述）
        category : str
            PARA分类: inspiration/project/area/resource/skill/archive
        domain : str
            领域: lottery/3d/pl3/football/music/general/ai/...
        tags : list[str] | None
            标签列表（为空时自动生成）
        source : str
            来源描述
        engine_hook : str | None
            引擎钩子描述（告诉引擎什么时候用这条知识）
            例如: "position_analysis" / "weight_calibration" / "kill_strategy"
        priority : int
            优先级 1-10（10最重要）
        subsystem : str | None
            子系统标识: lottery/football/stock/global
            如果为None，根据domain自动推断
        value_level : str | None
            价值分层: 数据/信息/知识/智慧（为None时自动判断）
        source_url : str | None
            来源URL（如果从URL提取）
        extracted_at : str | None
            提取时间（如果从URL提取）
        effectiveness : int
            初始效果分 10-90（默认50=中性，供引擎挂钩卡/复盘提炼使用）

        Returns
        -------
        str
            卡片ID
        """
        # ===== 并发安全: 在锁内重新加载最新数据并写入，避免多线程/多实例覆盖 =====
        with _DB_WRITE_LOCK:
            self._data = self._load()
            # ===== 自动去重: 按title检查是否已存在 =====
            existing = self._data.get("cards", [])
            for existing_card in existing:
                if existing_card.get("title") == title:
                    logger.info("知识卡片已存在，跳过重复添加: [%s] %s", category, title)
                    return existing_card.get("id")

            card_id = self._gen_id()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 自动推断subsystem（如果未显式指定）
            if subsystem is None:
                subsystem = self._infer_subsystem(domain)

            # 自动判断价值分层（如果未显式指定）
            if value_level is None:
                value_level = self.auto_classify_value(content)

            # 自动生成标签（如果tags为空）
            final_tags = list(tags) if tags else []
            if not final_tags:
                final_tags = self.auto_generate_tags(title, content, domain)

            card = {
                "id": card_id,
                "title": title,
                "content": content,
                "category": category,
                "domain": domain,
                "subsystem": subsystem,
                "value_level": value_level,
                "tags": final_tags,
                "source": source,
                "source_url": source_url or "",
                "extracted_at": extracted_at or now,
                "engine_hook": engine_hook or "",
                "priority": min(10, max(1, priority)),
                "effectiveness": min(90, max(10, effectiveness)),  # 初始50分（可指定），使用后调整
                "use_count": 0,
                "last_used": None,
                "created": now,
                "updated": now,
            }

            self._data.setdefault("cards", []).append(card)
            self._save()

        logger.info("知识卡片已添加: [%s] %s (领域=%s, 层级=%s, 钩子=%s)",
                     category, title, domain, value_level, engine_hook or "无")
        return card_id

    def search(self, query=None, category=None, domain=None, tags=None,
               engine_hook=None, min_effectiveness=0, limit=20, subsystem=None,
               value_level=None):
        """搜索知识卡片。

        支持多条件组合搜索：
        - query: 关键词模糊搜索（匹配标题和内容）
        - category: 按PARA分类过滤
        - domain: 按领域过滤
        - tags: 按标签过滤（任一匹配）
        - engine_hook: 按引擎钩子过滤
        - min_effectiveness: 最低有效性评分
        - subsystem: 按子系统过滤（"lottery"/"football"/"stock"/"global"）
        - value_level: 按价值分层过滤（"数据"/"信息"/"知识"/"智慧"）

        Returns
        -------
        list[dict]
            匹配的知识卡片列表
        """
        cards = self._data.get("cards", [])
        results = []

        for card in cards:
            # 子系统过滤（默认返回当前子系统 + global共享知识）
            if subsystem:
                card_sub = card.get("subsystem", self._infer_subsystem(card.get("domain", "")))
                if card_sub != subsystem and card_sub != "global":
                    continue
            # 类别过滤
            if category and card.get("category") != category:
                continue
            # 领域过滤
            if domain and card.get("domain") != domain:
                continue
            # 价值分层过滤
            if value_level and card.get("value_level", "信息") != value_level:
                continue
            # 标签过滤（任一匹配）
            if tags:
                if not any(t in card.get("tags", []) for t in tags):
                    continue
            # 引擎钩子过滤
            if engine_hook and card.get("engine_hook") != engine_hook:
                continue
            # 有效性过滤
            if card.get("effectiveness", 0) < min_effectiveness:
                continue
            # 关键词搜索
            if query:
                q_lower = query.lower()
                title_match = q_lower in card.get("title", "").lower()
                content_match = q_lower in card.get("content", "").lower()
                tag_match = any(q_lower in t.lower() for t in card.get("tags", []))
                if not (title_match or content_match or tag_match):
                    continue

            results.append(card)

        # 按优先级+有效性排序
        results.sort(key=lambda c: (c.get("priority", 5) + c.get("effectiveness", 50) / 10), reverse=True)
        return results[:limit]

    def get_for_engine(self, scenario, domain="lottery", limit=5):
        """引擎专用：根据当前分析场景获取相关知识。

        这是知识库和预测引擎的桥接点。
        引擎在分析时调用此方法，自动获取相关知识来辅助决策。

        Parameters
        ----------
        scenario : str
            当前分析场景，例如:
            - "position_analysis" → 位置感知分析时
            - "weight_calibration" → 权重校准时
            - "kill_strategy" → 杀号策略时
            - "miss_breakthrough" → 遗漏突破预测时
            - "morph_constraint" → 形态约束时
            - "smart_brain" → 智能大脑学习时
            - "reposition" → 摆位决策时
            - "backtest" → 回测分析时
        domain : str
            当前分析的领域
        limit : int
            最多返回几条知识

        Returns
        -------
        list[dict]
            相关知识卡片（按优先级+有效性排序）
        """
        # 1. 精确匹配engine_hook的卡片
        exact = [c for c in self._data.get("cards", [])
                 if c.get("engine_hook") == scenario
                 and c.get("domain", "") in (domain, "general", "")]
        # 2. 标签包含场景关键词的卡片
        tag_matched = [c for c in self._data.get("cards", [])
                       if scenario in c.get("tags", [])
                       and c.get("domain", "") in (domain, "general", "")]
        # 3. 去重合并，按优先级+有效性排序
        seen = set()
        merged = []
        for c in exact + tag_matched:
            if c["id"] not in seen:
                seen.add(c["id"])
                merged.append(c)

        merged.sort(key=lambda c: (c.get("priority", 5) + c.get("effectiveness", 50) / 10), reverse=True)
        result = merged[:limit]

        # 更新使用计数（加锁：防止与并发写竞争导致丢更新/损坏，JS-20260723-37）
        with _DB_WRITE_LOCK:
            for c in result:
                c["use_count"] = c.get("use_count", 0) + 1
                c["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save()

        if result:
            logger.info("引擎调用知识库: 场景=%s, 返回%d条知识", scenario, len(result))
        return result

    def update_effectiveness(self, card_id, delta):
        """更新知识卡片的有效性评分。

        当引擎使用了某条知识并得到结果后，调用此方法反馈效果。
        delta > 0 表示有效（命中/提升），delta < 0 表示无效（未命中/降低）

        Parameters
        ----------
        card_id : str
            卡片ID
        delta : int
            评分变化量（-50 ~ +50）
        """
        with _DB_WRITE_LOCK:
            for card in self._data.get("cards", []):
                if card["id"] == card_id:
                    old_eff = card.get("effectiveness", 50)
                    card["effectiveness"] = max(0, min(100, old_eff + delta))
                    card["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._save()
                    logger.info("知识卡片有效性更新: %s (%d → %d, delta=%+d)",
                                 card.get("title", card_id), old_eff, card["effectiveness"], delta)
                    return card["effectiveness"]
        return None

    def remove_card(self, card_id):
        """删除知识卡片"""
        with _DB_WRITE_LOCK:
            cards = self._data.get("cards", [])
            before = len(cards)
            self._data["cards"] = [c for c in cards if c["id"] != card_id]
            self._save()
            return len(self._data["cards"]) < before

    def import_from_text(self, text, category="inspiration", domain="general",
                         source="自动提取", tags=None):
        """从文本自动提取并创建知识卡片（增强版）。

        智能段落分割、标题提取、领域识别、自动分类。
        适合用户直接粘贴一段文字（如短视频文案、文章内容），
        系统自动按段落拆分，识别编号标题，检测领域和分类，生成知识卡片。

        Parameters
        ----------
        text : str
            原始文本
        category : str
            PARA分类（默认值"inspiration"时自动逐段分类；手动指定则全局覆盖）
        domain : str
            领域（默认值"general"时自动逐段识别；手动指定则全局覆盖）
        source : str
            来源
        tags : list[str] | None
            额外标签

        Returns
        -------
        list[str]
            创建的卡片ID列表
        """
        import re

        # 检测用户是否手动指定了分类/领域（非默认值视为手动指定）
        user_set_category = (category != "inspiration")
        user_set_domain = (domain != "general")

        # --- 智能段落分割 ---
        # 尝试按编号格式分割（第X章、一、、1. 等）
        heading_pattern = r'(?m)^(?:第[一二三四五六七八九十百零\d]+[章节回]|[一二三四五六七八九十]+[、.．]|\d+[.．、])\s*'
        parts = re.split(heading_pattern, text)
        paragraphs = [p.strip() for p in parts if len(p.strip()) >= 15]

        # 如果标题格式分割后段落太少，回退到普通段落分割
        if len(paragraphs) <= 1:
            paragraphs = [p.strip() for p in text.replace("\n\n", "\n").split("\n")
                          if len(p.strip()) >= 15]

        if not paragraphs:
            return []

        # 对全文做一次智能分类，获取全局标签
        full_classify = self.smart_classify(text)

        card_ids = []
        for i, para in enumerate(paragraphs):
            # --- 标题提取：取前30个字，更简洁 ---
            title_text = para[:30]
            title_text = re.sub(r'[，。、！？；：\n\r\s]+$', '', title_text)
            title = f"知识卡片 #{i+1}: {title_text}"

            # --- 对每段做独立智能分类 ---
            para_classify = self.smart_classify(para)
            auto_tags = list(tags or [])
            auto_tags.extend(para_classify["tags"])
            auto_tags.extend(full_classify["tags"])

            # 领域和分类：用户手动指定则全局覆盖，否则用智能逐段结果
            if user_set_domain:
                auto_domain = domain
            else:
                auto_domain = para_classify["domain"]

            if user_set_category:
                auto_category = category
            else:
                auto_category = para_classify["category"]

            # 引擎钩子
            auto_hook = para_classify.get("hook", "")

            # 去重标签
            auto_tags = list(set(auto_tags))

            card_id = self.add_card(
                title=title,
                content=para,
                category=auto_category,
                domain=auto_domain,
                tags=auto_tags,
                source=source,
                engine_hook=auto_hook,
                priority=5,
            )
            card_ids.append(card_id)

        logger.info("从文本导入了%d张知识卡片", len(card_ids))
        return card_ids

    def smart_classify(self, text):
        """智能分类：分析文本内容，自动推荐分类、领域、标签和引擎钩子。

        可被GUI调用，在用户粘贴文字后实时预览分类结果。

        Parameters
        ----------
        text : str
            待分析的文本内容

        Returns
        -------
        dict
            {"category": str, "domain": str, "tags": list, "hook": str}
        """
        result = {
            "category": "inspiration",
            "domain": "general",
            "tags": [],
            "hook": "",
        }

        # --- 领域关键词识别 ---
        football_keywords = ["足彩", "足球", "赔率", "欧赔", "亚盘", "让球", "进球",
                            "比赛", "联赛", "球队", "主客场", "盘口", "串关", "泊松"]
        life_keywords = ["生活", "健康", "饮食", "运动", "睡眠", "习惯"]
        invest_keywords = ["股票", "基金", "投资", "理财", "收益", "利率"]
        lottery_keywords = ["3D", "排列三", "福彩", "体彩", "双色球", "大乐透",
                            "遗漏", "杀号", "冷热", "形态", "位置", "百位", "十位", "个位",
                            "组选", "直选", "复式", "组三", "组六", "豹子",
                            "奇偶", "大小", "和值", "跨度"]
        music_keywords = ["音频", "MP3", "音乐", "转码", "音量", "采样", "LUFS"]
        ai_keywords = ["AI", "人工智能", "模型", "训练", "权重", "知识库", "Obsidian"]

        if any(k in text for k in football_keywords):
            result["domain"] = "football"
            result["tags"].extend(["足彩", "足球"])
        elif any(k in text for k in lottery_keywords):
            if any(k in text for k in ["3D", "排列三", "百位", "十位", "个位", "位置"]):
                result["domain"] = "3d"
                result["tags"].extend(["3D", "位置分析"])
            elif any(k in text for k in ["双色球", "大乐透"]):
                result["domain"] = "lottery"
                result["tags"].append("大盘")
            else:
                result["domain"] = "lottery"
                result["tags"].append("彩票")
        elif any(k in text for k in life_keywords):
            result["domain"] = "general"
            result["tags"].append("生活")
        elif any(k in text for k in invest_keywords):
            result["domain"] = "general"
            result["tags"].append("投资")
        elif any(k.lower() in text.lower() for k in music_keywords):
            result["domain"] = "music"
            result["tags"].append("音频")
        elif any(k.lower() in text.lower() for k in ai_keywords):
            result["domain"] = "ai"
            result["tags"].append("AI")

        # --- 自动分类建议 ---
        if any(k in text for k in ["方法", "步骤", "怎么做", "技巧"]):
            result["category"] = "skill"
        elif any(k in text for k in ["灵感", "想法", "感悟", "发现"]):
            result["category"] = "inspiration"
        elif any(k in text for k in ["项目", "开发", "代码", "bug", "测试"]):
            result["category"] = "project"
        elif any(k in text for k in ["资料", "参考", "教程", "文档"]):
            result["category"] = "resource"

        # --- 自动匹配引擎钩子 ---
        hook_keywords = {
            "position_analysis": ["位置", "百位", "十位", "个位", "摆位"],
            "weight_calibration": ["权重", "调优", "系数"],
            "kill_strategy": ["杀号", "排除"],
            "miss_breakthrough": ["遗漏", "突破"],
        }
        for hook, kws in hook_keywords.items():
            if any(k in text for k in kws):
                result["hook"] = hook
                break

        # 去重标签
        result["tags"] = list(set(result["tags"]))

        return result

    def auto_classify_value(self, content):
        """自动判断知识内容的价值分层。

        4个层级（从低到高）：
        - "数据" (raw data): 只有数字/结果/原始数据
        - "信息" (processed info): 有结论/总结/说明
        - "知识" (patterns): 有规律/方法/策略/模式
        - "智慧" (insights): 有深刻洞察/方法论/哲学/顶层设计

        Parameters
        ----------
        content : str
            知识内容

        Returns
        -------
        str
            价值分层：数据/信息/知识/智慧
        """
        import re

        if not content or not content.strip():
            return "信息"

        text = content.strip()

        # ===== 智慧层：深刻洞察/方法论/哲学 =====
        wisdom_keywords = [
            "方法论", "哲学", "本质", "底层逻辑", "第一性原理", "顶层设计",
            "道", "法", "术", "器", "认知", "思维模型", "范式", "辩证",
            "从根本上", "归根结底", "核心要义", "精髓", "智慧", "洞见",
            "长期主义", "复利思维", "逆向思维", "系统思维", "概率思维"
        ]
        wisdom_patterns = [
            r"之所以.*是因为", r"从本质上", r"根本原因", r"核心在于",
            r"这就是.*的本质", r".*的底层逻辑", r"方法论是", r"哲学层面"
        ]

        wisdom_score = 0
        for kw in wisdom_keywords:
            if kw in text:
                wisdom_score += 2
        for pat in wisdom_patterns:
            if re.search(pat, text):
                wisdom_score += 3
        if wisdom_score >= 4:
            return "智慧"

        # ===== 知识层：规律/方法/策略/模式 =====
        knowledge_keywords = [
            "规律", "策略", "方法", "技巧", "模式", "法则", "公式", "步骤",
            "流程", "框架", "模型", "体系", "机制", "原理", "算法",
            "如何", "怎么", "怎样", "经验", "心得", "体会", "总结出",
            "一般来说", "通常", "往往", "总是", "大概率", "小概率",
            "如果.*那么", "只要.*就", "只有.*才", "建议", "应该",
            "必须", "需要", "注意", "避免", "防止", "关键是", "重点是"
        ]
        knowledge_patterns = [
            r"第[一二三四五六七八九十\d]+[步条点]",
            r"方法[是叫为]",
            r"策略[是叫为]",
            r"规律[是叫为]",
            r"模式[是叫为]",
            r"公式[是叫为]",
            r"步骤如下",
            r"流程如下"
        ]

        knowledge_score = 0
        for kw in knowledge_keywords:
            if kw in text:
                knowledge_score += 1
        for pat in knowledge_patterns:
            if re.search(pat, text):
                knowledge_score += 2
        if knowledge_score >= 3 or wisdom_score >= 2:
            return "知识"

        # ===== 数据层：只有数字/结果/原始数据 =====
        # 统计数字占比
        digits = len(re.findall(r'\d+', text))
        total_chars = len(text)
        digit_density = digits / max(total_chars, 1)

        # 纯数据特征：只有数字、简短、无结论性词汇
        info_keywords = ["结论", "总结", "因此", "所以", "表明", "说明",
                         "显示", "发现", "得出", "可见", "综上", "概言之"]
        has_info_words = any(kw in text for kw in info_keywords)

        # 如果数字密度高且无结论性词汇，判定为数据层
        if digit_density > 0.15 and not has_info_words and len(text) < 200:
            return "数据"

        # 如果有明确的结论/总结词汇，判定为信息层
        if has_info_words:
            return "信息"

        # 默认：信息层
        return "信息"

    def auto_generate_tags(self, title, content, domain="general"):
        """基于内容自动生成标签。

        最多生成5个标签，按领域特性提取关键词：
        - 彩票领域：彩种名称、号码模式、遗漏、热号等
        - 股票领域：股票名、指标名称、买卖信号等
        - 通用领域：高频名词（2-4字词）

        Parameters
        ----------
        title : str
            知识标题
        content : str
            知识内容
        domain : str
            领域标识

        Returns
        -------
        list[str]
            自动生成的标签列表（最多5个）
        """
        import re

        text = title + " " + content
        tags = []

        # ===== 彩票领域标签 =====
        lottery_domains = {"lottery", "3d", "pl3", "kl8", "ssq", "dlt", "qxc", "7lc"}
        if domain.lower() in lottery_domains:
            # 彩种名称
            lottery_types = {
                "双色球": "双色球", "大乐透": "大乐透", "3D": "3D", "福彩3D": "福彩3D",
                "排列三": "排列三", "排列五": "排列五", "七乐彩": "七乐彩",
                "七星彩": "七星彩", "快乐8": "快乐8", "快乐八": "快乐8"
            }
            for name, tag in lottery_types.items():
                if name in text and tag not in tags:
                    tags.append(tag)

            # 号码模式关键词
            pattern_keywords = [
                "组选", "直选", "组三", "组六", "豹子", "顺子", "对子",
                "奇偶", "大小", "和值", "跨度", "质合", "012路", "路数",
                "百位", "十位", "个位", "万位", "千位", "位置",
                "遗漏", "热号", "冷号", "温号", "杀号", "胆码",
                "复式", "单式", "倍投", "守号", "追号",
                "形态", "走势", "趋势", "规律", "周期"
            ]
            for kw in pattern_keywords:
                if kw in text and kw not in tags:
                    tags.append(kw)
                if len(tags) >= 5:
                    break

        # ===== 股票领域标签 =====
        elif domain.lower() in {"stock", "fund", "invest"}:
            # 技术指标
            stock_indicators = [
                "MACD", "KDJ", "RSI", "MA", "均线", "BOLL", "布林带",
                "成交量", "成交额", "换手率", "市盈率", "市净率",
                "金叉", "死叉", "背离", "突破", "支撑位", "压力位",
                "止损", "止盈", "仓位", "加仓", "减仓", "清仓",
                "短线", "中线", "长线", "波段", "趋势", "震荡"
            ]
            for ind in stock_indicators:
                if ind.lower() in text.lower() and ind not in tags:
                    tags.append(ind)
                if len(tags) >= 5:
                    break

        # ===== 通用领域标签提取 =====
        if len(tags) < 3:
            # 提取2-4字的高频名词/术语
            # 先提取候选词
            candidates = []

            # 2字词
            two_char_pattern = r'[\u4e00-\u9fa5]{2}'
            two_chars = re.findall(two_char_pattern, text)

            # 3字词
            three_char_pattern = r'[\u4e00-\u9fa5]{3}'
            three_chars = re.findall(three_char_pattern, text)

            # 4字词
            four_char_pattern = r'[\u4e00-\u9fa5]{4}'
            four_chars = re.findall(four_char_pattern, text)

            all_candidates = two_chars + three_chars + four_chars

            # 过滤停用词
            stopwords = {
                "的话", "这个", "那个", "什么", "怎么", "为什么", "因为", "所以",
                "但是", "然而", "如果", "那么", "虽然", "还是", "就是", "不是",
                "可以", "可能", "应该", "必须", "需要", "已经", "正在", "将要",
                "我们", "你们", "他们", "她们", "它们", "自己", "大家", "别人",
                "时候", "地方", "东西", "事情", "问题", "方法", "方面", "情况",
                "现在", "过去", "将来", "以后", "以前", "之前", "之后", "目前",
                "一下", "一起", "一样", "一般", "一定", "一直", "经常", "偶尔",
                "主要", "重要", "关键", "核心", "基本", "根本", "彻底", "完全",
                "比较", "相当", "非常", "特别", "十分", "极其", "最", "更",
                "通过", "进行", "实现", "达到", "完成", "开始", "结束", "停止",
                "知道", "明白", "理解", "觉得", "认为", "相信", "希望", "打算",
                "很多", "许多", "大量", "不少", "少许", "几乎", "差不多",
            }

            word_count = Counter()
            for w in all_candidates:
                if w not in stopwords and len(w) >= 2:
                    word_count[w] += 1

            # 取频率最高的补充到tags
            for word, count in word_count.most_common(10):
                if count >= 2 and word not in tags:
                    tags.append(word)
                if len(tags) >= 5:
                    break

        # 去重并限制最多5个
        unique_tags = list(dict.fromkeys(tags))
        return unique_tags[:5]

    @staticmethod
    def estimate_card_count(text):
        """预估文本会被拆分成多少张卡片（供GUI预览用）"""
        import re
        heading_pattern = r'(?m)^(?:第[一二三四五六七八九十百零\d]+[章节回]|[一二三四五六七八九十]+[、.．]|\d+[.．、])\s*'
        parts = re.split(heading_pattern, text)
        paragraphs = [p.strip() for p in parts if len(p.strip()) >= 15]
        if len(paragraphs) <= 1:
            paragraphs = [p.strip() for p in text.replace("\n\n", "\n").split("\n")
                          if len(p.strip()) >= 15]
        return len(paragraphs)

    def get_all_cards(self, category=None, domain=None):
        """获取所有卡片（支持过滤）"""
        return self.search(category=category, domain=domain, limit=9999)

    def list_cards(self, domain=None, value_level=None, limit=50):
        """获取知识卡片列表（按创建时间倒序）。

        Parameters
        ----------
        domain : str | None
            按领域过滤
        value_level : str | None
            按价值分层过滤（数据/信息/知识/智慧）
        limit : int
            返回数量限制

        Returns
        -------
        list[dict]
            卡片列表
        """
        cards = self.search(domain=domain, value_level=value_level, limit=9999)
        # 按创建时间倒序
        cards.sort(key=lambda c: c.get("created", ""), reverse=True)
        return cards[:limit]

    def stats(self):
        """获取知识库统计信息（含使用率统计）"""
        self._update_stats()
        result = dict(self._data.get("stats", {}))
        try:
            cards = self._data.get("cards", [])
            # top_used: use_count 最高的前10张卡片
            sorted_by_use = sorted(cards, key=lambda c: c.get("use_count", 0), reverse=True)
            top_used = [
                {
                    "id": c.get("id", ""),
                    "title": c.get("title", ""),
                    "use_count": c.get("use_count", 0),
                    "effectiveness": c.get("effectiveness", 50),
                }
                for c in sorted_by_use[:10]
            ]
            # avg_effectiveness: 所有有评分卡片的平均 effectiveness
            scored = [c.get("effectiveness", 50) for c in cards if c.get("use_count", 0) > 0]
            avg_eff = round(sum(scored) / len(scored), 2) if scored else 0.0
            # unused_count: use_count 为 0 的卡片数
            unused_count = sum(1 for c in cards if c.get("use_count", 0) == 0)
            result["usage_stats"] = {
                "top_used": top_used,
                "avg_effectiveness": avg_eff,
                "unused_count": unused_count,
                "total_cards": len(cards),
            }
        except Exception:
            result["usage_stats"] = {
                "top_used": [],
                "avg_effectiveness": 0.0,
                "unused_count": 0,
                "total_cards": 0,
            }
        return result

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _gen_id():
        """生成唯一ID"""
        import uuid
        return uuid.uuid4().hex[:8]

    @staticmethod
    def _infer_subsystem(domain):
        """根据domain自动推断subsystem
        
        Args:
            domain: 领域标签
            
        Returns:
            str: subsystem标识
        """
        # lottery系列domain → lottery子系统
        lottery_domains = {"lottery", "3d", "pl3", "kl8", "ssq", "dlt", "qxc", "7lc"}
        if domain.lower() in lottery_domains:
            return "lottery"
        # 足球相关 → football子系统
        football_domains = {"football", "soccer", "match"}
        if domain.lower() in football_domains:
            return "football"
        # 其他 → global（跨域共享知识）
        return "global"

    def migrate_subsystem_field(self):
        """自动迁移：为所有缺少subsystem字段的卡片补充subsystem
        
        根据 domain 字段自动推断 subsystem 值。
        只在卡片缺少 subsystem 字段时才添加，已有则不修改。
        """
        with _DB_WRITE_LOCK:
            cards = self._data.get("cards", [])
            migrated = 0
            for card in cards:
                if "subsystem" not in card:
                    domain = card.get("domain", "general")
                    card["subsystem"] = self._infer_subsystem(domain)
                    migrated += 1
            if migrated > 0:
                self._save()
                logger.info("知识库迁移完成: %d张卡片已补充subsystem字段", migrated)
        return migrated

    def migrate_value_fields(self):
        """自动迁移：为所有缺少新字段的卡片补充 value_level、source_url、extracted_at

        为旧版本创建的卡片补充新增字段，保持向后兼容。
        - value_level: 自动根据内容判断
        - source_url: 默认为空字符串
        - extracted_at: 默认为created时间
        """
        with _DB_WRITE_LOCK:
            cards = self._data.get("cards", [])
            migrated = 0
            for card in cards:
                needs_save = False
                # 补充 value_level
                if "value_level" not in card:
                    content = card.get("content", "")
                    card["value_level"] = self.auto_classify_value(content)
                    needs_save = True
                # 补充 source_url
                if "source_url" not in card:
                    card["source_url"] = ""
                    needs_save = True
                # 补充 extracted_at
                if "extracted_at" not in card:
                    card["extracted_at"] = card.get("created", "")
                    needs_save = True
                if needs_save:
                    migrated += 1
            if migrated > 0:
                self._save()
                logger.info("知识库迁移完成: %d张卡片已补充价值分层等新字段", migrated)
        return migrated

    def __repr__(self):
        s = self.stats()
        return f"<MiroFishDB: {s.get('total_cards', 0)} cards>"


# ========== 模块级便捷接口 ==========

_KB_INSTANCE = None
_KB_INSTANCE_LOCK = threading.Lock()


def get_kb(db_path=None):
    """获取知识库单例（线程安全）。

    首次调用时创建实例并加载 JSON 文件，后续调用复用同一实例。
    若传入不同的 db_path，则重新创建。
    """
    global _KB_INSTANCE
    with _KB_INSTANCE_LOCK:
        if _KB_INSTANCE is None or (db_path and _KB_INSTANCE.db_path != db_path):
            _KB_INSTANCE = MiroFishDB(db_path)
        return _KB_INSTANCE


def query_by_tags(tags, domain=None, limit=10, min_effectiveness=0):
    """按标签快捷查询知识卡片（模块级函数，无需手动实例化）。

    Parameters
    ----------
    tags : list[str]
        标签列表，任一匹配即返回（OR 逻辑）。
    domain : str, optional
        限定领域（如 "lottery", "football", "ai"）。
    limit : int
        最多返回条数。
    min_effectiveness : int
        最低有效性评分。

    Returns
    -------
    list[dict]  匹配的知识卡片列表
    """
    kb = get_kb()
    return kb.search(tags=tags, domain=domain, limit=limit,
                     min_effectiveness=min_effectiveness)


def query_recent(n=10, domain=None, category=None):
    """获取最近添加的 N 张知识卡片（按创建时间倒序）。

    Parameters
    ----------
    n : int
        返回条数。
    domain : str, optional
        限定领域。
    category : str, optional
        限定 PARA 分类。

    Returns
    -------
    list[dict]
    """
    kb = get_kb()
    cards = kb.search(domain=domain, category=category, limit=9999)
    # 按创建时间倒序
    cards.sort(key=lambda c: c.get("created", ""), reverse=True)
    return cards[:n]
