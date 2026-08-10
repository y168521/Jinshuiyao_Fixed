# -*- coding: utf-8 -*-
"""金水谣系统 - L3自适应进化引擎子模块（JS-20260810-10 由 engines/evolution.py 拆分）"""
import os
import re
import json
import uuid
import math
import logging
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from utils.safe_json import safe_write_json, safe_load_json
except ImportError:
    def safe_write_json(filepath, data):
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=parent, prefix=".evolution_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def safe_load_json(filepath, default=None):
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载文件失败 [%s]: %s，返回默认值", filepath, e)
            return default

_SEVERITY_LEVELS = {"info": 1, "warn": 2, "critical": 3}
_DEFAULT_RULE_THRESHOLD = 3

from engines.evolution_rule import RuleEngine
class ExperienceMiner:

    """经验挖掘器 - 从健康日志中提炼知识

    分析历史运行数据，挖掘重复出现的模式，

    将经验自动转化为MiroFish知识库卡片供引擎调用。

    """

    def __init__(self, data_dir="金水谣数据"):

        """初始化经验挖掘器

        Args:

            data_dir: 数据目录路径

        """

        self.data_dir = data_dir

        self.patterns_file = os.path.join(data_dir, "evolution_patterns.json")

        self._lock = threading.Lock()

        self._patterns_cache = self._load_patterns()

        # MiroFish知识库引用（延迟初始化）

        self._mirofish = None

    def _load_patterns(self):

        """加载已挖掘的模式缓存"""

        default = {"patterns": [], "last_mined": None, "mine_count": 0}

        return safe_load_json(self.patterns_file, default)

    def _save_patterns(self):

        """保存模式缓存"""

        try:

            safe_write_json(self.patterns_file, self._patterns_cache)

        except Exception as e:

            logger.error("保存经验模式失败: %s", e, exc_info=True)

            raise

    def _get_mirofish(self):

        """延迟获取MiroFish知识库实例

        Returns:

            MiroFishDB|None: 知识库实例

        """

        if self._mirofish is None:

            try:

                from knowledge.mirofish_db import MiroFishDB

                db_path = os.path.join(

                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),

                    "knowledge", "mirofish_db.json"

                )

                self._mirofish = MiroFishDB(db_path=db_path)

            except ImportError:

                logger.warning("无法导入MiroFishDB，知识沉淀功能不可用")

                return None

            except Exception as e:

                logger.error("初始化MiroFishDB失败: %s", e)

                return None

        return self._mirofish

    # ------------------------------------------------------------------

    # 公开接口

    # ------------------------------------------------------------------

    def mine_patterns(self, health_log_path, min_occurrences=3):

        """从健康日志中挖掘重复模式

        扫描日志文件，统计相似错误信息的出现频率，

        提取出现次数 >= min_occurrences 的模式。

        Args:

            health_log_path: 健康日志文件路径（或目录路径）

            min_occurrences: 最小出现次数阈值

        Returns:

            list[dict]: [{

                "pattern": "模式描述",

                "frequency": 出现次数,

                "suggested_rule": "建议规则",

                "confidence": 0.0-1.0

            }]

        """

        # 收集日志行

        lines = self._collect_log_lines(health_log_path)

        if not lines:

            logger.info("未找到日志数据: %s", health_log_path)

            return []

        # 统计相似行

        pattern_counts = defaultdict(int)

        pattern_examples = {}

        for line in lines:

            line = line.strip()

            if not line or len(line) < 10:

                continue

            # 标准化：移除时间戳、期号等变化部分

            normalized = self._normalize_log_line(line)

            if normalized:

                pattern_counts[normalized] += 1

                if normalized not in pattern_examples:

                    pattern_examples[normalized] = line

        # 筛选高频模式

        results = []

        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):

            if count < min_occurrences:

                continue

            confidence = min(1.0, count / max(1, min_occurrences * 2))

            suggested_rule = RuleEngine._suggest_action(pattern_examples.get(pattern, ""), "auto")

            results.append({

                "pattern": pattern_examples.get(pattern, pattern),

                "frequency": count,

                "suggested_rule": suggested_rule,

                "confidence": round(confidence, 2),

            })

        # 更新缓存

        with self._lock:

            self._patterns_cache["patterns"] = results

            self._patterns_cache["last_mined"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self._patterns_cache["mine_count"] = self._patterns_cache.get("mine_count", 0) + 1

            self._save_patterns()

        logger.info("挖掘到 %d 个高频模式 (min_occurrences=%d)", len(results), min_occurrences)

        return results

    def auto_generate_knowledge_card(self, pattern):

        """将经验自动转化为MiroFish知识库卡片

        Args:

            pattern: 模式字典（来自mine_patterns的返回值）

                {

                    "pattern": "模式描述",

                    "frequency": 出现次数,

                    "suggested_rule": "建议规则",

                    "confidence": 0.0-1.0

                }

        Returns:

            str|None: 知识卡片ID，或None（如果知识库不可用）

        """

        mirofish = self._get_mirofish()

        if mirofish is None:

            logger.warning("知识库不可用，跳过知识卡片生成")

            return None

        frequency = pattern.get("frequency", 1)

        pattern_text = pattern.get("pattern", "未知模式")

        suggested_rule = pattern.get("suggested_rule", "")

        # confidence 可能来自持久化 JSON 缓存（字符串/None），必须安全转 float

        # 否则 {:.0%} 格式化会抛 "Unknown format code '%' for object of type 'str'"

        _conf_raw = pattern.get("confidence", 0.5)

        try:

            confidence = float(_conf_raw)

        except (TypeError, ValueError):

            confidence = 0.5

        # 构建卡片

        title = "自动发现: {} (出现{}次)".format(

            pattern_text[:40], frequency

        )

        content = (

            "系统在运行中发现重复模式: {}\n\n"

            "出现次数: {}\n"

            "置信度: {:.0%}\n"

            "建议措施: {}\n\n"

            "此知识卡片由进化引擎自动生成，基于运行数据分析。"

        ).format(

            pattern_text[:100],

            frequency,

            confidence,

            suggested_rule or "暂无"

        )

        # 确定引擎钩子

        engine_hook = "smart_brain"

        if any(kw in pattern_text for kw in ["网络", "抓取", "fetch"]):

            engine_hook = "data_fetch"

        elif any(kw in pattern_text for kw in ["预测", "命中", "复盘"]):

            engine_hook = "smart_brain"

        elif any(kw in pattern_text for kw in ["杀号", "过滤", "排除"]):

            engine_hook = "kill_strategy"

        try:

            card_id = mirofish.add_card(

                title=title,

                content=content,

                category="area",

                domain="lottery",

                tags=["自愈", "自动修复", "进化引擎"],

                source="evolution:auto",

                engine_hook=engine_hook,

                priority=min(10, max(1, int(confidence * 10))),

            )

            logger.info("知识卡片已生成: %s (模式出现%d次, 置信度%.0f%%)",

                         card_id, frequency, confidence * 100)

            return card_id

        except Exception as e:

            logger.error("生成知识卡片失败: %s", e, exc_info=True)

            return None

    def batch_generate_cards(self, patterns):

        """批量将多个模式转化为知识卡片

        Args:

            patterns: 模式列表（来自mine_patterns）

        Returns:

            list[str]: 成功创建的卡片ID列表

        """

        card_ids = []

        for pattern in patterns:

            if pattern.get("confidence", 0) >= 0.3:  # 只转化置信度>=30%的模式

                cid = self.auto_generate_knowledge_card(pattern)

                if cid:

                    card_ids.append(cid)

        if card_ids:

            logger.info("批量生成了 %d 张知识卡片", len(card_ids))

        return card_ids

    def get_cached_patterns(self):

        """获取缓存的经验模式

        Returns:

            list[dict]: 缓存的模式列表

        """

        with self._lock:

            return list(self._patterns_cache.get("patterns", []))

    # ------------------------------------------------------------------

    # 内部方法

    # ------------------------------------------------------------------

    @staticmethod

    def _collect_log_lines(log_path):

        """收集日志行（支持单文件或目录）

        Args:

            log_path: 日志文件路径或目录路径

        Returns:

            list[str]: 日志行列表

        """

        lines = []

        if not os.path.exists(log_path):

            return lines

        if os.path.isdir(log_path):

            for fname in os.listdir(log_path):

                fpath = os.path.join(log_path, fname)

                if os.path.isfile(fpath) and (fname.endswith(".log") or fname.endswith(".txt")):

                    try:

                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:

                            lines.extend(f.readlines())

                    except IOError as e:

                        logger.warning("读取日志文件失败 [%s]: %s", fpath, e)

        else:

            try:

                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:

                    lines.extend(f.readlines())

            except IOError as e:

                logger.warning("读取日志文件失败 [%s]: %s", log_path, e)

        return lines

    @staticmethod

    def _normalize_log_line(line):

        """标准化日志行，移除时间戳、期号等变化部分

        Args:

            line: 原始日志行

        Returns:

            str: 标准化后的模式字符串，或空字符串

        """

        # 移除常见时间戳格式: 2024-01-15 12:30:45

        text = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}(\.\d+)?', '', line)

        # 移除日志级别前缀: [INFO], [ERROR], [WARN]

        text = re.sub(r'\[(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]\s*', '', text)

        # 移除纯数字（期号、行号等）

        text = re.sub(r'\b\d{5,}\b', '', text)

        # 移除文件路径中的数字版本号

        text = re.sub(r'v?\d+\.\d+(?:\.\d+)?', '', text)

        # 移除多余空白

        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) < 8:

            return ""

        return text

# ===================================================================

# 3. 自适应反馈闭环 (AdaptiveFeedback)

# ===================================================================
