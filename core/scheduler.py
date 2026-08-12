# -*- coding: utf-8 -*-
"""
金水谣系统 - 定时任务调度器

基于 threading.Timer 的轻量级定时任务调度器，不引入额外依赖。
支持运行时动态注册/注销/启停，单例模式，可重入。

类:
  - TaskScheduler: 通用定时任务调度基类
  - JinshuiyaoScheduler: 金水谣专用调度器，预注册6项默认定时任务

模块级函数:
  - get_scheduler(): 获取全局金水谣调度器单例
  - start_background_scheduler(): 启动后台调度器（供 main.py 调用）
"""

import os
import sys
import glob
import time
import logging
import threading
from datetime import datetime

# 日志轮转工具（防止 JSONL 文件无限增长）
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)
from utils.log_rotation import check_and_rotate

logger = logging.getLogger(__name__)

from .scheduler_tasks import TaskScheduler  # 拆分自本文件(J S-20260810-10), 重导出保持 import 兼容

# P2-2: PRED_CACHE 进程内短 TTL 缓存，避免同周期多任务重复整文件 reload
_PRED_CACHE_TTL = 30  # 秒
_pred_cache_cache = {"data": None, "ts": 0.0}


def _load_pred_cache_cached():
    """带 TTL 的 PRED_CACHE 读取：30 秒内复用已解析结果，减少磁盘 IO。"""
    now = time.time()
    if _pred_cache_cache["data"] is not None and (now - _pred_cache_cache["ts"]) < _PRED_CACHE_TTL:
        return _pred_cache_cache["data"]
    from utils.safe_json import safe_load_json
    from config import PRED_CACHE
    data = safe_load_json(PRED_CACHE, default={})
    _pred_cache_cache["data"] = data
    _pred_cache_cache["ts"] = now
    return data



# ================================================================
# JinshuiyaoScheduler - 金水谣专用调度器
# ================================================================

class JinshuiyaoScheduler(TaskScheduler):
    """金水谣系统专用调度器

    继承 TaskScheduler，在初始化时自动注册6项金水谣默认定时任务：

    1. data_refresh     - 数据刷新（每 60 分钟）
    2. auto_review      - 自动复盘（每 120 分钟）
    3. knowledge_extract - 知识提取（每次复盘后触发）
    4. data_maintenance  - 数据维护（每 24 小时）
    5. health_backup     - 健康备份（每 24 小时）
    6. file_cleanup      - 文件清理（每 24 小时）

    每个任务的 func 实际调用对应子系统的方法，
    任何任务失败不影响其他任务。
    """

    def __init__(self):
        """创建金水谣调度器并注册所有默认定时任务"""
        super().__init__()
        self._register_default_tasks()

    def start(self):
        """启动调度器，并额外拉起经验收集箱文件监听线程（B：近实时同步）。

        先启动基类定时任务，再启动监听线程；任一失败都不影响其余。
        """
        super().start()
        try:
            from core.auto_knowledge import start_experience_box_watcher
            start_experience_box_watcher(interval=15)
        except Exception as e:
            logger.warning("[经验监听] 启动失败（不影响其余定时任务）: %s", e)
        # 拉起 AI 决策监听线程（Layer A+B：让每个 AI 的"为什么改"都能被后续 AI 搜到）
        try:
            from core.auto_knowledge import start_ai_decisions_watcher
            start_ai_decisions_watcher(interval=15)
        except Exception as e:
            logger.warning("[AI决策监听] 启动失败（不影响其余定时任务）: %s", e)

    # 数据表驱动（债务-215：原 193 行逐块注册 → 表+循环）
    # (name, method, interval_key, run_now, first_delay)
    # data_refresh/auto_review 开机会补跑（run_now），auto_review 延迟 420s 等数据抓取完成错峰
    _TASKS_ALWAYS = [
        ("data_refresh", "_task_data_refresh", "data_refresh", True, None),
        ("auto_review", "_task_auto_review", "auto_review", True, 420),
        ("knowledge_extract", "_task_knowledge_extract", "knowledge_extract", False, None),
        ("data_maintenance", "_task_data_maintenance", "data_maintenance", False, None),
        ("health_backup", "_task_health_backup", "health_backup", False, None),
        ("file_cleanup", "_task_file_cleanup", "file_cleanup", False, None),
        ("memory_decay", "_task_memory_decay", "memory_decay", False, None),
        ("cross_link", "_task_cross_link", "cross_link", False, None),
        ("kg_rebuild", "_task_kg_rebuild", "kg_rebuild", False, None),
        ("kb_lint", "_task_kb_lint", "kb_lint", False, None),
        ("vector_index_rebuild", "_task_vector_index_rebuild", "vector_index_rebuild", False, None),
    ]
    # 条件任务（config/scheduler.json 对应 key >0 才注册）
    _TASKS_CONDITIONAL = ["ai_code_review", "free_model_sync", "free_model_health"]
    # 兜底任务（注册失败不影响其余任务，间隔固定）
    _TASKS_SAFE = [
        ("proactive_reminder", "_task_proactive_reminder", 30),
        ("brain_daily", "_task_brain_daily", 1440),
    ]

    def _register_default_tasks(self):
        """注册金水谣系统的16项默认定时任务（11 无条件 + 3 条件开关 + 2 兜底注册；间隔可从 config/scheduler.json 覆盖；实际注册数随条件开关浮动，以 register() 调用为准）"""
        # 加载用户自定义间隔配置（可选）
        _defaults = {
            "data_refresh": 60,
            "auto_review": 120,
            "knowledge_extract": 120,
            "data_maintenance": 24 * 60,
            "health_backup": 24 * 60,
            "file_cleanup": 24 * 60,
            # 知识维护自动化（N1/N3）：每日/每月自动跑，免去手动
            "memory_decay": 24 * 60,   # 记忆衰减：每24小时
            "cross_link": 24 * 60,     # 双库自动发现链接：每24小时
            "kg_rebuild": 24 * 60,     # 知识图谱重建：每24小时
            "kb_lint": 24 * 60,        # 知识体检(Lint)：每日触发，但仅每月1号真正执行
            "vector_index_rebuild": 24 * 60,  # 向量索引重建(P3-4)：每24小时主动重建离线VSM索引，与 mtime 失效机制互补
            "ai_code_review": 24 * 60,  # AI代码语义审查(免费模型优先)：每日1次，0=禁用
            # 免费模型自动化（W63补38）：配置自动更新+健康自动探活，零手动
            "free_model_sync": 24 * 60,   # 免费模型清单自动同步：每日拉取→探活→质量排序写回配置，0=禁用
            "free_model_health": 120,     # 免费模型健康探活：每2小时，0=禁用
        }
        try:
            import json as _json
            _cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "config", "scheduler.json")
            if os.path.isfile(_cfg_path):
                with open(_cfg_path, "r", encoding="utf-8") as _f:
                    _user_cfg = _json.load(_f)
                _defaults.update({k: v for k, v in _user_cfg.items() if isinstance(v, (int, float))})
        except Exception:
            pass  # 配置文件不存在或格式错误时用默认值

        # 1. 无条件任务（数据驱动注册）
        for _name, _meth, _key, _run_now, _first_delay in self._TASKS_ALWAYS:
            self.register(
                name=_name,
                func=getattr(self, _meth),
                interval_minutes=_defaults[_key],
                enabled=True,
                run_now=_run_now,
                first_delay=_first_delay,
            )

        # 2. 条件任务（对应配置 key >0 才注册，0=禁用）
        for _name in self._TASKS_CONDITIONAL:
            if _defaults.get(_name, 0) > 0:
                self.register(
                    name=_name,
                    func=getattr(self, "_task_" + _name),
                    interval_minutes=_defaults[_name],
                    enabled=True,
                )

        # 3. 自动化镜像：把原 WorkBuddy 平台自动化（仅计时触发器）平移进金水谣调度器，
        #    用 sys.executable 调同一批本地 scripts/*.py → 免 WorkBuddy 积分（详见 core/automation_mirror.py）。
        #    任何失败仅告警，不影响上述原生任务（地：隔离）。
        try:
            from core.automation_mirror import register_mirrors
            register_mirrors(self)
        except Exception as e:
            logger.warning("[自动化镜像] 注册失败（不影响其余定时任务）: %s", e)

        # 4. 兜底任务（间隔固定，注册失败静默跳过，不影响其余任务）
        for _name, _meth, _interval in self._TASKS_SAFE:
            try:
                self.register(
                    name=_name,
                    func=getattr(self, _meth),
                    interval_minutes=_interval,
                    enabled=True,
                )
            except Exception as e:
                logger.warning("[%s] 注册失败（不影响其余定时任务）: %s", _name, e)

    def _task_data_refresh():
        """数据刷新任务 - 抓取最新彩票/股票/足彩数据

        依次调用:
          1. Fetcher 抓取各彩种最新数据
          2. StockFetcher 更新股票缓存
          3. 足彩数据更新
        """
        logger.info("[数据刷新] 开始刷新全部数据源...")

        # 1) 彩票数据刷新
        try:
            from fetchers.fetcher import get_fetcher
            from config import LOT_ALL
            fetcher = get_fetcher()
            for lot in LOT_ALL:
                try:
                    success, data = fetcher.fetch(lot)
                    if success and data:
                        logger.info("[数据刷新] %s: 获取到 %d 条数据", lot, len(data))
                    else:
                        logger.debug("[数据刷新] %s: 无新数据", lot)
                except Exception as e:
                    logger.warning("[数据刷新] %s 抓取失败: %s", lot, e)
        except Exception as e:
            logger.error("[数据刷新] 彩票数据刷新异常: %s", e)

        # 2) 股票数据刷新
        try:
            from domains.stock.fetcher import StockFetcher
            stock_fetcher = StockFetcher()
            for sym in ["sh000001", "sz399001", "sh000300"]:
                try:
                    df = stock_fetcher.get_history(sym)
                    if df is not None and not df.empty:
                        logger.info("[数据刷新] 股票 %s: 获取到 %d 条K线", sym, len(df))
                except Exception as e:
                    logger.warning("[数据刷新] 股票 %s 抓取失败: %s", sym, e)
        except Exception as e:
            logger.error("[数据刷新] 股票数据刷新异常: %s", e)

        # 3) 足彩数据刷新
        try:
            from jinshuiyao.data_fetcher import DataFetcher
            foot_df = DataFetcher()
            try:
                matches = foot_df.fetch_worldcup_matches()
                if matches:
                    logger.info("[数据刷新] 足彩: 获取到 %d 场比赛数据", len(matches))
            except Exception as e:
                logger.warning("[数据刷新] 足彩数据抓取失败: %s", e)
        except Exception as e:
            logger.error("[数据刷新] 足彩模块加载失败: %s", e)

        logger.info("[数据刷新] 数据刷新完成")

    @staticmethod
    def _task_auto_review():
        """自动复盘任务 - 对已开奖的预测自动复盘并喂给智能大脑

        与 GUI 手动复盘同口径（main_window._review_job）：
        - 只复盘"数据文件里已有开奖号码"的记录（未开奖/数据缺失的跳过，等下轮）
        - 命中数按彩种分别计算（福彩3D/排列三 多重集、快乐8 集合、其余红+蓝）
        - 写回 reviewed/hits/hit_type/coverage/draw_date 到 predictions.json
        - 分组喂给 SmartBrain.learn_from_review 学习
        """
        logger.info("[自动复盘] 开始自动复盘...")

        try:
            from config import PRED_CACHE
            from utils.safe_json import safe_write_json
            from utils.locks import preds_lock
            from models.lottery_data import Data
            from utils.number_utils import clean_nums, parse_reds
            from collections import Counter as _Ctr

            preds_data = _load_pred_cache_cached()
            if not isinstance(preds_data, list) or not preds_data:
                logger.info("[自动复盘] 无预测数据，跳过复盘")
                return

            unreviewed = [p for p in preds_data if isinstance(p, dict) and not p.get("reviewed")]
            if not unreviewed:
                logger.info("[自动复盘] 无待复盘记录")
                return

            logger.info("[自动复盘] 发现 %d 条待复盘记录", len(unreviewed))

            reviewed_now = []
            skip_no_draw = 0
            for pred in unreviewed:
                lot = pred.get("lot", "")
                per = pred.get("period")
                if not Data.has_period(lot, per):
                    skip_no_draw += 1
                    continue
                act, dt = Data.result(lot, per)
                if not act:
                    skip_no_draw += 1
                    continue

                pn = clean_nums(pred.get("nums", ""))
                ac = clean_nums(act)
                hits = 0
                if lot in ("福彩3D", "排列三"):
                    pc = _Ctr(parse_reds(pn))
                    ac_ctr = _Ctr(parse_reds(ac))
                    hits = sum(min(pc[d], ac_ctr.get(d, 0)) for d in pc)
                elif lot == "快乐8":
                    hits = len(set(parse_reds(pn)) & set(parse_reds(ac)))
                else:
                    pr = pn.split("+")[0] if "+" in pn else pn
                    ar = ac.split("+")[0] if "+" in ac else ac
                    hits = len(set(parse_reds(pr)) & set(parse_reds(ar)))
                    if "+" in pn and "+" in ac:
                        hits += len(set(parse_reds(pn.split("+")[1])) & set(parse_reds(ac.split("+")[1])))

                pred["draw_date"] = dt if dt else ""
                pred["reviewed"] = True
                pred["hits"] = hits
                hit_type = "未中"
                if lot in ("福彩3D", "排列三"):
                    if pn == ac:
                        hit_type = "直选"
                    elif hits >= 3:
                        hit_type = "组选"
                else:
                    if hits > 0:
                        hit_type = "组选"
                pred["hit_type"] = hit_type
                act_num_count = len(parse_reds(ac.replace("+", ",")))
                pred["coverage"] = round(hits / act_num_count, 3) if act_num_count else 0
                reviewed_now.append(pred)

            if reviewed_now:
                with preds_lock:
                    safe_write_json(PRED_CACHE, preds_data)
                _pred_cache_cache["ts"] = 0.0  # 使 TTL 缓存失效
                logger.info("[自动复盘] 已复盘 %d 条并写回缓存文件", len(reviewed_now))

            # 智能大脑学习（按彩种分组，只学本次新复盘的最新一期）
            try:
                from engines.smart_brain import SmartBrain
                brain = SmartBrain()
                reviewed_lots = {p.get("lot", "") for p in reviewed_now}
                for lot_name in sorted(reviewed_lots):
                    lot_preds = [p for p in reviewed_now if p.get("lot") == lot_name]
                    if not lot_preds:
                        continue
                    latest_per = max(p.get("period", 0) for p in lot_preds)
                    if Data.has_period(lot_name, latest_per):
                        act_data, _ = Data.result(lot_name, latest_per)
                        if act_data:
                            act_nums = parse_reds(clean_nums(act_data))
                            brain.learn_from_review(lot_name, lot_preds, act_nums)
                logger.info("[自动复盘] 智能大脑学习完成")
                # 策略卡提炼: 复盘统计 → 引擎挂钩知识卡（幂等, 失败降级不影响复盘）
                try:
                    from engines.strategy_cards import refresh_strategy_cards
                    refresh_strategy_cards()
                except Exception as e:
                    logger.warning("[自动复盘] 策略卡提炼失败(降级跳过): %s", e)
            except Exception as e:
                logger.error("[自动复盘] 智能大脑学习失败: %s", e)

            logger.info("[自动复盘] 复盘完成 (已复盘 %d 条 / 未开奖跳过 %d 条)",
                        len(reviewed_now), skip_no_draw)

        except Exception as e:
            logger.error("[自动复盘] 自动复盘异常: %s", e, exc_info=True)

    @staticmethod
    def _task_knowledge_extract():
        """知识提取任务 - 从复盘中自动提取知识卡片

        读取最近的复盘结果，调用 MiroFishDB 提取知识。
        """
        logger.info("[知识提取] 开始知识提取...")

        try:
            from knowledge.mirofish_db import MiroFishDB

            db = MiroFishDB()
            stats = db.stats()
            before_count = stats.get("total_cards", 0)

            # 读取最近复盘的预测结果作为提取素材
            try:
                from config import PRED_CACHE

                preds_data = _load_pred_cache_cached()
                predictions = []

                if isinstance(preds_data, list):
                    predictions = preds_data
                elif isinstance(preds_data, dict) and "predictions" in preds_data:
                    for lot, items in preds_data["predictions"].items():
                        if isinstance(items, list):
                            predictions.extend(items)

                # 只处理已复盘的记录
                reviewed = [p for p in predictions if isinstance(p, dict) and p.get("reviewed")]

                if reviewed:
                    # 取最近5条复盘记录作为知识提取素材
                    recent = reviewed[-5:]
                    for pred in recent:
                        # 从预测缓存取值，并对可能为字符串/None 的字段做安全兜底
                        # （缓存来自 JSON 反序列化，confidence/hits/total 可能为字符串，
                        #  而 lot/strategy 为 None 时 .get 默认值不生效，会拼出 "None" 怪值）
                        lot = pred.get("lot") or "unknown"
                        # hits/total 安全转 int（默认 0），避免拼接出怪值
                        try:
                            hits = int(pred.get("hits", 0))
                        except (TypeError, ValueError):
                            hits = 0
                        try:
                            total = int(pred.get("total", 0))
                        except (TypeError, ValueError):
                            total = 0
                        # confidence 必须转 float 才能用 % 格式码，否则字符串会抛
                        # "Unknown format code '%' for object of type 'str'"
                        _conf_raw = pred.get("confidence", 0.5)
                        try:
                            confidence = float(_conf_raw)
                        except (TypeError, ValueError):
                            confidence = 0.5
                        strat = pred.get("strategy") or "默认"

                        # 构建知识文本
                        text = (
                            "彩种: {lot}, 命中: {hits}/{total}, "
                            "置信度: {conf:.0%}, "
                            "策略: {strat}".format(
                                lot=lot,
                                hits=hits,
                                total=total,
                                conf=confidence,
                                strat=strat,
                            )
                        )

                        try:
                            db.import_from_text(
                                text,
                                category="archive",
                                domain=lot if lot in (
                                    "双色球", "大乐透", "福彩3D", "排列三",
                                    "七乐彩", "七星彩", "快乐8",
                                    "stock", "football", "fund",
                                ) else "general",
                            )
                        except Exception as e:
                            logger.debug("[知识提取] 单条提取失败: %s", e)

            except Exception as e:
                logger.warning("[知识提取] 读取预测数据失败: %s", e)

            after_stats = db.stats()
            after_count = after_stats.get("total_cards", 0)
            new_cards = after_count - before_count

            logger.info("[知识提取] 提取完成 (新增 %d 张知识卡片, 总计 %d 张)", new_cards, after_count)

            # 从AI对话日志中提取通用经验知识
            try:
                from core.auto_knowledge import extract_from_conversation_log
                conv_result = extract_from_conversation_log(max_new=30)
                if conv_result.get("extracted", 0) > 0:
                    logger.info(
                        "[知识提取] 对话经验提取: 处理%d条, 提取%d张, 保存%d张",
                        conv_result["processed"], conv_result["extracted"], conv_result["saved"],
                    )
            except Exception as e:
                logger.debug("[知识提取] 对话经验提取跳过: %s", e)

            # 从经验收集箱提取跨AI共享经验（Qoder/豆包/TRAE/WorkBuddy写入）
            try:
                from core.auto_knowledge import extract_from_experience_box
                exp_result = extract_from_experience_box()
                if exp_result.get("extracted", 0) > 0:
                    logger.info(
                        "[知识提取] 经验收集箱: %d条新经验, 保存%d张卡片",
                        exp_result["new_entries"], exp_result["saved"],
                    )
            except Exception as e:
                logger.debug("[知识提取] 经验收集箱提取跳过: %s", e)

            # D：GraphRAG 三元组抽取（与卡片同步共用经验箱，独立标记/降级）
            try:
                from core.auto_knowledge import extract_triples_from_experience_box
                triple_result = extract_triples_from_experience_box()
                if triple_result.get("saved", 0) > 0:
                    logger.info(
                        "[知识提取] GraphRAG: 处理%d条经验, 新增%d个三元组",
                        triple_result["processed"], triple_result["saved"],
                    )
            except Exception as e:
                logger.debug("[知识提取] GraphRAG 三元组抽取跳过: %s", e)

            # Layer A+B：从 AI 决策卡抽取知识（让每个 AI 的改动可被后续 AI 搜到）
            try:
                from core.auto_knowledge import extract_from_ai_decisions
                ai_result = extract_from_ai_decisions()
                if ai_result.get("saved", 0) > 0:
                    logger.info(
                        "[知识提取] AI决策: %d条新决策, 保存%d张卡片",
                        ai_result["new_entries"], ai_result["saved"],
                    )
            except Exception as e:
                logger.debug("[知识提取] AI决策卡片抽取跳过: %s", e)
            try:
                from core.auto_knowledge import extract_triples_from_ai_decisions
                ai_triple = extract_triples_from_ai_decisions()
                if ai_triple.get("saved", 0) > 0:
                    logger.info(
                        "[知识提取] AI决策 GraphRAG: 处理%d条, 新增%d个三元组",
                        ai_triple["processed"], ai_triple["saved"],
                    )
            except Exception as e:
                logger.debug("[知识提取] AI决策三元组抽取跳过: %s", e)

        except Exception as e:
            logger.error("[知识提取] 知识提取异常: %s", e, exc_info=True)

    @staticmethod
    def _task_data_maintenance():
        """数据维护任务 - 清理过期数据、压缩归档

        执行:
          1. 清理过期预测记录
          2. 清理旧的错误日志
          3. 清理离线同步队列中的已处理条目
        """
        logger.info("[数据维护] 开始数据维护...")

        # 1) 清理过期预测记录
        try:
            from utils.safe_json import safe_write_json
            from config import PRED_CACHE
            import json as _json

            preds_data = _load_pred_cache_cached()
            if preds_data:
                if isinstance(preds_data, dict) and "predictions" in preds_data:
                    cleaned = 0
                    for lot, items in preds_data["predictions"].items():
                        if isinstance(items, list) and len(items) > 200:
                            # 只保留最近200条
                            removed = len(items) - 200
                            preds_data["predictions"][lot] = items[-200:]
                            cleaned += removed
                    if cleaned > 0:
                        safe_write_json(PRED_CACHE, preds_data)
                        _pred_cache_cache["data"] = None  # P2-2: 写后失效缓存
                        logger.info("[数据维护] 清理过期预测记录 %d 条", cleaned)
                elif isinstance(preds_data, list) and len(preds_data) > 200:
                    removed = len(preds_data) - 200
                    safe_write_json(PRED_CACHE, preds_data[-200:])
                    _pred_cache_cache["data"] = None  # P2-2: 写后失效缓存
                    logger.info("[数据维护] 清理过期预测记录 %d 条", removed)
        except Exception as e:
            logger.error("[数据维护] 预测记录清理失败: %s", e)

        # 2) 清理旧的错误日志（保留最近7天）
        try:
            from config import ERR_LOG_DIR
            import re

            if os.path.isdir(ERR_LOG_DIR):
                cutoff = time.time() - 7 * 24 * 3600
                removed = 0
                for fname in os.listdir(ERR_LOG_DIR):
                    if not fname.startswith("error_") or not fname.endswith(".log"):
                        continue
                    fpath = os.path.join(ERR_LOG_DIR, fname)
                    try:
                        if os.path.getmtime(fpath) < cutoff:
                            os.remove(fpath)
                            removed += 1
                    except OSError:
                        pass
                if removed > 0:
                    logger.info("[数据维护] 清理旧错误日志 %d 个", removed)
        except Exception as e:
            logger.error("[数据维护] 错误日志清理失败: %s", e)

        # 3) 清理备份文件（保留最近5个）
        try:
            backup_dir = os.path.join("金水谣数据", "backups")
            if os.path.isdir(backup_dir):
                backups = sorted(
                    glob.glob(os.path.join(backup_dir, "jinshuiyao_backup_*.zip")),
                    key=os.path.getmtime,
                )
                if len(backups) > 5:
                    for old_backup in backups[:-5]:
                        try:
                            os.remove(old_backup)
                            logger.info("[数据维护] 删除旧备份: %s", os.path.basename(old_backup))
                        except OSError:
                            pass
        except Exception as e:
            logger.error("[数据维护] 备份清理失败: %s", e)

        logger.info("[数据维护] 数据维护完成")

    @staticmethod
    def _task_health_backup():
        """健康备份任务 - 全量数据备份

        调用 utils.data_backup.backup_all 创建带时间戳的 zip 备份。
        """
        logger.info("[健康备份] 开始全量数据备份...")

        try:
            from utils.data_backup import backup_all

            backup_path = backup_all()
            size_mb = os.path.getsize(backup_path) / (1024 * 1024) if os.path.isfile(backup_path) else 0
            logger.info("[健康备份] 备份完成: %s (%.2f MB)", backup_path, size_mb)

        except Exception as e:
            logger.error("[健康备份] 全量备份失败: %s", e, exc_info=True)

    @staticmethod
    def _task_file_cleanup():
        """文件清理任务 - 清理临时文件、整理目录

        执行:
          1. 清理 __pycache__ 目录
          2. 清理 .pyc 文件
          3. 清理临时数据文件
          4. 整理目录结构
        """
        logger.info("[文件清理] 开始文件清理...")

        # 获取项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 1) 清理 __pycache__ 目录
        cache_count = 0
        for root, dirs, files in os.walk(project_root):
            if "__pycache__" in dirs:
                cache_dir = os.path.join(root, "__pycache__")
                try:
                    import shutil
                    shutil.rmtree(cache_dir)
                    cache_count += 1
                except OSError as e:
                    logger.debug("[文件清理] 删除 %s 失败: %s", cache_dir, e)

        if cache_count > 0:
            logger.info("[文件清理] 清理 __pycache__ 目录 %d 个", cache_count)

        # 2) 清理临时 .bak 文件（保留最近3个）
        try:
            for pattern in ["金水谣数据/*.bak.*", "金水谣数据/**/*.bak.*", "knowledge/*.bak.*"]:
                bak_files = sorted(glob.glob(os.path.join(project_root, pattern)), key=os.path.getmtime)
                if len(bak_files) > 3:
                    for old_bak in bak_files[:-3]:
                        try:
                            os.remove(old_bak)
                        except OSError:
                            pass
        except Exception as e:
            logger.debug("[文件清理] .bak 文件清理异常: %s", e)

        # 3) 清理离线队列中的已处理条目
        try:
            sync_queue = os.path.join(project_root, "金水谣数据", "sync", "offline_queue.jsonl")
            if os.path.isfile(sync_queue):
                import json as _json
                lines = []
                with open(sync_queue, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = _json.loads(line)
                            if not entry.get("processed"):
                                lines.append(line)
                        except _json.JSONDecodeError:
                            lines.append(line)

                with open(sync_queue, "r", encoding="utf-8") as _f:
                    _total_lines = sum(1 for _line in _f if _line.strip())
                if len(lines) < _total_lines:
                    with open(sync_queue, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines) + "\n" if lines else "")
                    logger.info("[文件清理] 离线队列已清理")
        except Exception as e:
            logger.debug("[文件清理] 离线队列清理异常: %s", e)

        # 4) 确保必要目录存在
        required_dirs = [
            os.path.join(project_root, "金水谣数据", "log"),
            os.path.join(project_root, "金水谣数据", "log", "err_log"),
            os.path.join(project_root, "金水谣数据", "lot_data"),
            os.path.join(project_root, "金水谣数据", "stock", "cache"),
            os.path.join(project_root, "金水谣数据", "fund", "cache"),
        ]
        for d in required_dirs:
            os.makedirs(d, exist_ok=True)

        logger.info("[文件清理] 文件清理完成")

    # ------------------------------------------------------------------
    # 知识维护自动化任务（N1/N3）
    # ------------------------------------------------------------------

    @staticmethod
    def _task_memory_decay():
        """记忆衰减任务 - 对所有知识卡做衰减+自动归档（每24小时）"""
        logger.info("[记忆衰减] 开始衰减周期...")
        try:
            from core.memory_decay import run_decay_cycle
            result = run_decay_cycle()
            logger.info(
                "[记忆衰减] 完成 (衰减:%d, 归档:%d, 强化:%d, 总计:%d)",
                result.get("decayed", 0), result.get("archived", 0),
                result.get("boosted", 0), result.get("total", 0),
            )
        except Exception as e:
            logger.error("[记忆衰减] 执行异常: %s", e, exc_info=True)

    @staticmethod
    def _task_cross_link():
        """双库自动发现链接任务 - 发现左脑MiroFish↔右脑用户库关联（每24小时）"""
        logger.info("[双库链接] 开始自动发现链接...")
        try:
            from knowledge.cross_linker import get_linker
            result = get_linker().discover()
            logger.info(
                "[双库链接] 完成 (本轮新发现:%d, 总链接:%d)",
                len(result.get("new_links", [])), result.get("total_links", 0),
            )
        except Exception as e:
            logger.error("[双库链接] 执行异常: %s", e, exc_info=True)

    @staticmethod
    def _task_kg_rebuild():
        """知识图谱重建任务 - 重建知识图谱（每24小时）"""
        logger.info("[知识图谱] 开始重建...")
        try:
            from knowledge.knowledge_graph import get_graph
            result = get_graph().build()
            logger.info(
                "[知识图谱] 完成 (节点:%s, 边:%s)",
                result.get("nodes", 0), result.get("edges", 0),
            )
        except Exception as e:
            logger.error("[知识图谱] 执行异常: %s", e, exc_info=True)

    @staticmethod
    def _task_kb_lint():
        """知识体检(Lint)任务 - 每月1号自动体检（孤儿卡片/空内容/缺字段）

        调度器原生只支持「每 N 分钟」，这里用「每日触发 + 日期守卫」实现每月1号。
        """
        now = datetime.now()
        if now.day != 1:
            logger.info("[知识体检] 跳过（非每月1号，当前为 %d 号）", now.day)
            return
        logger.info("[知识体检] 开始月度体检...")
        try:
            import importlib
            mod = importlib.import_module("knowledge.用户知识库.lint_knowledge")
            report = mod.lint()
            rd = report.to_dict() if hasattr(report, "to_dict") else report
            errors = rd.get("errors", []) if isinstance(rd, dict) else []
            warns = rd.get("warns", []) if isinstance(rd, dict) else []
            cards = rd.get("cards", 0) if isinstance(rd, dict) else 0
            logger.info(
                "[知识体检] 完成 (卡片:%d, 错误:%d, 警告:%d)",
                cards, len(errors), len(warns),
            )
            if errors:
                _write_kb_lint_log(rd)
        except Exception as e:
            logger.error("[知识体检] 执行异常: %s", e, exc_info=True)

    @staticmethod
    def _task_vector_index_rebuild():
        """向量索引定时重建任务(P3-4) - 主动重建离线VSM语义索引（每24小时）

        与 get_vector_index 的 mtime 失效机制互补：
        - 主动重建使磁盘索引保持新鲜，首个语义检索无需临时构建
        - 索引文件 mtime/内容随知识库变化刷新，命中新增知识卡
        - 进程内缓存单例(_INDEX)同步指向最新索引，消除「磁盘新/内存旧」窗口期

        任何异常被隔离，不影响其他定时任务。
        """
        logger.info("[向量索引] 开始定时重建...")
        try:
            from knowledge.vector_index import rebuild_vector_index
            idx = rebuild_vector_index()
            logger.info(
                "[向量索引] 重建完成 (卡片:%d, 构建于:%s)",
                idx.doc_count, idx.built_at,
            )
        except Exception as e:
            logger.error("[向量索引] 重建异常: %s", e, exc_info=True)

    @staticmethod
    def _task_ai_code_review():
        """AI代码语义审查定时任务 - 对最近改动的 .py 文件做模型级审查

        与 pre-commit 钩子互补：钩子拦"本次提交"，此任务兜底"已入库/已改动代码"。
        模型策略（用户约定：能用免费模型就用，不然就算了）：
          - 优先免费：硅基流动免费模型池（free_models.json，GLM-4-9B 等），AI_REVIEW_PROVIDER=siliconflow
          - 免费无密钥/全部宕机 → 直接跳过（不调用付费 DeepSeek），记 WARN 日志
        范围：最近 7 天 git 修改过的 .py 文件（git log --since），上限 20 个，避免无界耗时。
        任何异常被隔离，不影响其他定时任务。
        """
        logger.info("[AI代码审查] 开始定时语义审查...")
        try:
            import subprocess as _sp
            import json as _json

            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            # 1) 收集最近7天改动的 .py 文件（git 跟踪的源码，排除测试/生成目录）
            try:
                out = _sp.check_output(
                    ["git", "log", "--since=7.days", "--name-only", "--pretty=format:",
                     "--diff-filter=ACM"],
                    cwd=_root, text=True, timeout=30, errors="replace",
                )
            except Exception:
                out = ""
            files = []
            for f in (out or "").splitlines():
                f = f.strip()
                if not f.endswith(".py"):
                    continue
                if f.startswith(("tests/", "test_", "scripts/", "knowledge/")):
                    continue
                p = os.path.join(_root, f)
                if os.path.isfile(p):
                    files.append(p)
            files = list(dict.fromkeys(files))[:20]
            if not files:
                logger.info("[AI代码审查] 最近7天无 .py 改动，跳过")
                return

            # 2) 只走免费模型：硅基流动池；无密钥/不可用则跳过（用户约定不烧付费）
            secrets_dir = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
            if not os.path.isfile(os.path.join(secrets_dir, "siliconflow_key.txt")):
                logger.info("[AI代码审查] 无硅基流动密钥，跳过（免费优先约定）")
                return

            env = dict(os.environ)
            env["AI_REVIEW_PROVIDER"] = "siliconflow"
            script = os.path.join(_root, "tools", "ai_review_agent.py")
            proc = _sp.run(
                [sys.executable, script, "--files", ",".join(files), "--json"],
                cwd=_root, capture_output=True, timeout=30 * 60, env=env,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
            if proc.returncode != 0 or not stdout.strip():
                logger.warning("[AI代码审查] 无结果(rc=%s)，跳过", proc.returncode)
                return
            report = _json.loads(stdout)
            issues = report.get("issues", [])
            p0 = sum(1 for i in issues if i.get("severity") == "P0")
            p1 = sum(1 for i in issues if i.get("severity") == "P1")
            logger.info(
                "[AI代码审查] 完成: 审查%d个文件, P0=%d, P1=%d, 其他=%d",
                len(files), p0, p1, len(issues) - p0 - p1,
            )
            if p0:
                logger.warning("[AI代码审查] 检出P0: %s", _json.dumps(
                    [{"file": i.get("file"), "line": i.get("line"),
                      "desc": i.get("description", "")[:100]} for i in issues
                     if i.get("severity") == "P0"][:5], ensure_ascii=False))
        except Exception as e:
            logger.warning("[AI代码审查] 执行失败（不影响其余定时任务）: %s", e)

    @staticmethod
    def _task_free_model_sync():
        """免费模型清单自动同步 - 每日拉取→探活→质量排序→写回 free_models.json

        调 tools/sync_free_models.py（子进程隔离，任何失败仅告警）。
        免费模型是"活"资源：官方免费额度随时下线（如 GLM-4-9B 免费档已 403），
        新模型随时出现。每日自动同步让免费池永远保持新鲜、精准。
        """
        logger.info("[免费模型] 开始每日自动同步...")
        try:
            import subprocess as _sp
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            secrets_dir = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")
            if not os.path.isfile(os.path.join(secrets_dir, "siliconflow_key.txt")):
                logger.info("[免费模型] 无硅基流动密钥，跳过同步（免费优先约定）")
                return
            script = os.path.join(_root, "tools", "sync_free_models.py")
            proc = _sp.run(
                [sys.executable, script],
                cwd=_root, capture_output=True, timeout=20 * 60,
            )
            stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            tail = (stdout or stderr).strip().splitlines()[-3:]
            if proc.returncode == 0:
                logger.info("[免费模型] 同步完成: %s", " | ".join(tail))
            else:
                logger.warning("[免费模型] 同步退出码=%s: %s", proc.returncode, " | ".join(tail))
        except Exception as e:
            logger.warning("[免费模型] 自动同步失败（不影响其余定时任务）: %s", e)

    @staticmethod
    def _task_free_model_health():
        """免费模型健康探活 - 每2小时对池内模型发探活请求更新健康状态

        与外部 WorkBuddy 定时（scripts/free_model_health_check.py）互补：
        本任务内置于调度器，即使外部平台不跑，也能自动发现免费模型宕机。
        全池宕机时写告警（金水谣数据/free_model_status.json），供界面/日志预警。
        """
        logger.info("[免费模型] 开始健康探活...")
        try:
            import json as _json
            from core.free_model_pool import health_check_all
            res = health_check_all()
            checked = res.get("checked", [])
            down = res.get("down", [])
            degraded = res.get("degraded", [])
            logger.info(
                "[免费模型] 探活完成: 检查%d 宕机%d 降级%d",
                len(checked), len(down), len(degraded),
            )
            if down:
                logger.warning("[免费模型] 宕机模型: %s", _json.dumps(down, ensure_ascii=False)[:300])
            if res.get("all_down"):
                logger.error("[免费模型] ⚠ 免费模型全池宕机！检查硅基流动额度/密钥")
        except Exception as e:
            logger.warning("[免费模型] 健康探活失败（不影响其余定时任务）: %s", e)

    @staticmethod
    def _task_proactive_reminder():
        """主动提醒引擎：扫描到期提醒写入 pending_reminders.json（对话开始时助手主动开口）。

        系统级（收工23:30/探活08:30/基金18:00）+ 用户画像周期事项（"记住：每天X点Y事"）。
        同一规则当天只推一次（fired_log 去重），不骚扰。
        """
        try:
            from core.agent_reminder import render_due
            mem_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "金水谣数据", "agent_memory",
            )
            n = render_due(mem_dir)
            if n:
                logger.info("[主动提醒] 写入 %d 条待提醒", n)
        except Exception as e:
            logger.warning("[主动提醒] 执行失败（不影响其余定时任务）: %s", e)

    @staticmethod
    def _task_brain_daily():
        """大脑日报：每天1次AI复盘总结 + 生成《大脑日报》（人话版，免费模型优先，失败静默）"""
        try:
            from engines.brain_daily import run_daily
            ok = run_daily()
            if ok:
                logger.info("[大脑日报] 已生成（AI复盘总结+玩法健康度日报）")
        except Exception as e:
            logger.warning("[大脑日报] 执行失败（不影响其余定时任务）: %s", e)


def _write_kb_lint_log(rd):
    """把知识体检结果写入日志（便于追溯每月体检情况）"""
    try:
        import json as _json
        _log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "金水谣数据", "log",
        )
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, "kb_lint.jsonl")
        from utils.log_rotation import check_and_rotate
        check_and_rotate(_log_path, max_size_mb=5)
        _entry = {
            "timestamp": datetime.now().isoformat(),
            "cards": rd.get("cards", 0),
            "errors": rd.get("errors", []),
            "warns": rd.get("warns", []),
        }
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps(_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志写入失败不影响任务执行


# ================================================================
# 模块级函数
# ================================================================

_global_scheduler = None
_global_scheduler_lock = threading.Lock()


def get_scheduler():
    """获取全局金水谣调度器单例

    首次调用时创建 JinshuiyaoScheduler 实例，后续调用返回同一实例。

    Returns:
        JinshuiyaoScheduler: 全局金水谣调度器单例
    """
    global _global_scheduler
    with _global_scheduler_lock:
        if _global_scheduler is None:
            _global_scheduler = JinshuiyaoScheduler()
            logger.info("全局金水谣调度器单例已创建")
        return _global_scheduler


def start_background_scheduler():
    """启动后台调度器

    供 main.py 调用。获取全局单例并启动所有已注册的任务。
    多次调用安全（可重入）。

    Returns:
        JinshuiyaoScheduler: 已启动的调度器实例
    """
    scheduler = get_scheduler()
    scheduler.start()
    return scheduler
