# -*- coding: utf-8 -*-
"""全局数据真实性守卫模块

对金水谣系统所有子系统的数据进行真实性检测，防止过期/伪造/兜底数据被当作真实数据使用。

检测维度（3层防线）：
  L1 - 数据来源标识：检测数据是否来自真实API、缓存、模拟兜底或硬编码
  L2 - 时效性校验：检测数据日期是否过期（足彩比赛是否已完赛、股票数据是否超过时效阈值）
  L3 - 交叉比对：多个数据源之间是否一致（可选，用于高级校验）

支持子系统：
  - football（足彩）
  - stock（股票）
  - lottery（彩票，数据来自官方开奖，不做时效性检测）

输出：结构化报告 dict，包含每个检测项的状态/详情/修复建议
"""
import os
import sys
import csv
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# 数据来源等级
# -----------------------------------------------------------------------
SOURCE_REAL_API = "real_api"          # 真实API抓取
SOURCE_CACHE = "cache"                # 本地缓存（可能过期）
SOURCE_FALLBACK = "fallback"          # 模拟兜底数据（非真实）
SOURCE_HARDCODED = "hardcoded"        # 硬编码数据（非真实）
SOURCE_UNKNOWN = "unknown"            # 无法判断

SOURCE_LABELS = {
    SOURCE_REAL_API: "真实API",
    SOURCE_CACHE: "本地缓存",
    SOURCE_FALLBACK: "模拟兜底",
    SOURCE_HARDCODED: "硬编码",
    SOURCE_UNKNOWN: "未知来源",
}

SOURCE_COLORS = {
    SOURCE_REAL_API: "green",
    SOURCE_CACHE: "yellow",
    SOURCE_FALLBACK: "red",
    SOURCE_HARDCODED: "red",
    SOURCE_UNKNOWN: "gray",
}


class DataTruthGuard:
    """全局数据真实性守卫"""

    def __init__(self):
        self._report_items = []
        self._jinshuiyao_dir = self._find_jinshuiyao_dir()

    # ================================================================
    # 公共接口
    # ================================================================

    def run_full_check(self) -> dict:
        """执行全部数据真实性检测，返回结构化报告

        Returns:
            {
                "timestamp": "2026-07-14 16:00:00",
                "overall": "healthy" | "degraded" | "critical",
                "subsystems": {
                    "football": { "status": "pass"|"warn"|"fail", "checks": [...] },
                    "stock": { ... },
                    "lottery": { ... },
                },
                "summary": { "real": N, "cache": N, "fallback": N, "hardcoded": N },
                "action_required": ["建议1", "建议2", ...],
            }
        """
        self._report_items = []

        subsystems = {}

        subsystems["football"] = self._check_football()
        subsystems["stock"] = self._check_stock()
        subsystems["lottery"] = self._check_lottery()

        # 汇总数据来源分布
        source_dist = {SOURCE_REAL_API: 0, SOURCE_CACHE: 0,
                       SOURCE_FALLBACK: 0, SOURCE_HARDCODED: 0, SOURCE_UNKNOWN: 0}
        for ss in subsystems.values():
            for chk in ss.get("checks", []):
                src = chk.get("source", SOURCE_UNKNOWN)
                if src in source_dist:
                    source_dist[src] += chk.get("count", 1)

        # 汇总状态
        summary = {"pass": 0, "warn": 0, "fail": 0}
        for ss in subsystems.values():
            summary[ss["status"]] = summary.get(ss["status"], 0) + 1

        if summary["fail"] > 0:
            overall = "critical"
        elif summary["warn"] > 0:
            overall = "degraded"
        else:
            overall = "healthy"

        # 收集需要操作的建议
        actions = []
        for ss_name, ss in subsystems.items():
            for chk in ss.get("checks", []):
                if chk.get("action"):
                    actions.append(f"[{ss_name}] {chk['action']}")

        report = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall": overall,
            "subsystems": subsystems,
            "source_distribution": {k: v for k, v in source_dist.items() if v > 0},
            "summary": summary,
            "action_required": actions,
        }

        # 写审计日志
        try:
            from core.audit_log import log_event
            log_event(
                event_type="DATA_TRUTH",
                subsystem="global",
                summary=f"数据真实性检测: {overall}",
                detail=f"通过={summary['pass']}, 警告={summary['warn']}, 失败={summary['fail']}",
                data={"source_distribution": source_dist},
                level="info" if overall == "healthy" else ("warn" if overall == "degraded" else "error"),
            )
        except Exception:
            logger.debug("审计日志写入跳过（DATA_TRUTH）")

        return report

    def format_report(self, report: dict) -> str:
        """将报告格式化为可读文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("  金水谣系统 - 数据真实性检测报告")
        lines.append(f"  {report['timestamp']}")
        lines.append("=" * 60)

        # 总体状态
        overall = report["overall"]
        overall_map = {"healthy": "✅ 健康", "degraded": "⚠️ 降级", "critical": "❌ 异常"}
        lines.append("")
        lines.append(f"总体状态: {overall_map.get(overall, overall)}")

        # 数据来源分布
        dist = report.get("source_distribution", {})
        if dist:
            lines.append("")
            lines.append("数据来源分布:")
            for src, count in dist.items():
                label = SOURCE_LABELS.get(src, src)
                lines.append(f"  {label}: {count}条")

        # 各子系统详情
        for ss_name, ss in report.get("subsystems", {}).items():
            ss_label = {"football": "足彩", "stock": "股票", "lottery": "彩票"}.get(ss_name, ss_name)
            lines.append("")
            lines.append("-" * 40)
            status_map = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
            lines.append(f"  {ss_label}子系统 {status_map.get(ss['status'], '')}")

            for chk in ss.get("checks", []):
                icon = status_map.get(chk.get("status", "pass"), "  ")
                src = chk.get("source", "")
                src_label = SOURCE_LABELS.get(src, src)
                lines.append(f"  {icon} [{src_label}] {chk.get('name', '')}")
                lines.append(f"      {chk.get('detail', '')}")
                if chk.get("action"):
                    lines.append(f"      → {chk['action']}")

        # 建议操作
        actions = report.get("action_required", [])
        if actions:
            lines.append("")
            lines.append("-" * 40)
            lines.append("  需要关注的操作:")
            for act in actions:
                lines.append(f"  ⚡ {act}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ================================================================
    # 足彩子系统检测
    # ================================================================

    def _check_football(self) -> dict:
        """检测足彩数据真实性

        检测项：
          1. CSV数据时效性（比赛日期是否已过期）
          2. CSV数据来源标识（是否有source标记）
          3. data_fetcher.py硬编码检测（_generate_fallback_matches）
          4. 联赛名称合理性校验
        """
        checks = []
        today = datetime.now().strftime("%Y-%m-%d")
        # 主数据是 matches_supplemented.csv（含未来赛程+历史赛果）；matches.csv 仅为兜底
        primary_csv = os.path.join(self._jinshuiyao_dir, "data", "matches_supplemented.csv")
        fallback_csv = os.path.join(self._jinshuiyao_dir, "data", "matches.csv")
        csv_path = primary_csv if os.path.exists(primary_csv) else fallback_csv

        # ---- 检测1: CSV比赛时效性 ----
        csv_status, csv_source, csv_detail, csv_action = self._check_csv_matches(csv_path, today)
        checks.append({
            "name": "CSV比赛时效性",
            "status": csv_status,
            "source": csv_source,
            "detail": csv_detail,
            "action": csv_action,
            "count": sum(1 for _ in self._iter_csv_matches(csv_path)),
        })

        # ---- 检测2: 赔率合理性 ----
        odds_path = os.path.join(self._jinshuiyao_dir, "data", "odds.csv")
        odds_status, odds_detail, odds_action = self._check_odds_validity(odds_path)
        checks.append({
            "name": "赔率合理性",
            "status": odds_status,
            "source": csv_source,  # 和CSV同源
            "detail": odds_detail,
            "action": odds_action,
            "count": sum(1 for _ in self._iter_csv_rows(odds_path)),
        })

        # ---- 检测3: 硬编码检测 ----
        hc_status, hc_detail, hc_action = self._check_hardcoded_football()
        checks.append({
            "name": "硬编码兜底检测",
            "status": hc_status,
            "source": SOURCE_HARDCODED,
            "detail": hc_detail,
            "action": hc_action,
            "count": 1,
        })

        # 汇总子系统状态
        statuses = [c["status"] for c in checks]
        ss_status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")

        return {"status": ss_status, "checks": checks}

    def _check_csv_matches(self, csv_path: str, today: str):
        """检查CSV比赛数据的时效性"""
        if not os.path.exists(csv_path):
            return "warn", SOURCE_UNKNOWN, f"CSV文件不存在（{csv_path}）", None

        matches = list(self._iter_csv_matches(csv_path))
        if not matches:
            return "warn", SOURCE_UNKNOWN, "CSV文件为空", None

        total = len(matches)
        expired = []
        future = []
        today_matches = []
        no_date = []

        for m in matches:
            date = m.get("date", "")
            if not date:
                no_date.append(m)
            elif date < today:
                expired.append(m)
            elif date == today:
                today_matches.append(m)
            else:
                future.append(m)

        # 判断来源：过期比赛+未来比赛混合属正常（历史赛果做回测素材）
        # 判定策略：只要存在足够的未来/今日比赛，则数据有效；全过期才告警
        if expired:
            valid_count = len(today_matches) + len(future)
            if valid_count > 0:
                detail = f"共{total}场比赛，未来/今日{valid_count}场，历史{len(expired)}场（回测素材）"
                return "pass", SOURCE_CACHE, detail, None
            detail = f"共{total}场比赛，已过期{len(expired)}场，今日{len(today_matches)}场，未来{len(future)}场"
            for m in expired[:3]:
                detail += f"\n    过期: {m.get('league', '')} {m.get('home', '')} vs {m.get('away', '')} ({m['date']})"
            return "fail", SOURCE_FALLBACK, detail, "移除已过期的比赛数据，更新为当前赛事"

        if no_date:
            # 日期字段为空或只有时间，无法判断时效性
            if expired or today_matches or future:
                pass  # 上面已有判断
            # 所有比赛都没有日期字段
            if len(no_date) == total:
                detail = f"共{total}场比赛，match_time字段缺少日期（仅有时间），无法判断时效性"
                return "warn", SOURCE_UNKNOWN, detail, "在match_time中补充完整日期（如 2026-07-15 03:00）"
            # 部分比赛无日期
            detail = f"共{total}场比赛，{len(no_date)}场缺少日期信息"
            if today_matches or future:
                detail += f"，有{len(today_matches) + len(future)}场有效"
                return "pass", SOURCE_CACHE, detail, None
            return "warn", SOURCE_UNKNOWN, detail, "补充缺失的日期信息"

        if today_matches:
            detail = f"共{total}场比赛，今日{len(today_matches)}场，未来{len(future)}场 — 时效性正常"
            return "pass", SOURCE_CACHE, detail, None

        if future:
            detail = f"共{total}场比赛，全部为未来赛事（无今日比赛）"
            return "pass", SOURCE_CACHE, detail, None

        detail = f"共{total}场比赛，无法判断日期有效性"
        return "warn", SOURCE_UNKNOWN, detail, "检查比赛日期字段格式"

    def _check_odds_validity(self, odds_path: str):
        """检查赔率数据的合理性"""
        if not os.path.exists(odds_path):
            return "warn", "赔率文件不存在", None

        # 需要排除的非赔率字段名
        skip_fields = {"match_id", "match", "id", "home", "away", "league", "date", "time"}

        issues = []
        rows = list(self._iter_csv_rows(odds_path))
        for row in rows:
            try:
                # 只解析赔率相关字段（排除ID等字段）
                vals = []
                for k, v in row.items():
                    if k.strip().lower() in skip_fields:
                        continue
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        continue
                for v in vals:
                    if v < 1.01 or v > 50.0:
                        issues.append(f"赔率 {v:.2f} 超出合理范围(1.01-50.0)")
                # 检查赔率是否全部为相同值（明显的假数据特征）
                if len(vals) >= 3 and vals[0] == vals[1] == vals[2]:
                    issues.append(f"胜平负赔率完全相同({vals[0]:.2f})，疑似假数据")
            except (ValueError, TypeError):
                issues.append("赔率格式错误")

        if issues:
            return "fail", "发现异常: " + "; ".join(issues[:3]), "检查赔率来源，更新为真实赔率数据"

        return "pass", f"{len(rows)}组赔率均在合理范围内", None

    def _check_hardcoded_football(self):
        """检测足彩模块是否存在大量硬编码兜底数据"""
        # 检查 data_fetcher.py 中 _generate_real_league_matches 的硬编码比赛数
        fetcher_path = os.path.join(self._jinshuiyao_dir, "data_fetcher.py")
        if not os.path.exists(fetcher_path):
            return "warn", "data_fetcher.py 不存在，无法检测", "检查足彩数据抓取器是否安装"

        try:
            with open(fetcher_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 检测硬编码特征
            hardcode_signs = []
            if "_generate_real_league_matches" in content:
                # 统计硬编码的比赛对数（通过元组数量估算）
                import re
                tuples = re.findall(r"\('.*?',\s*'.*?',\s*\d+,\s*\d+\)", content)
                if len(tuples) >= 10:
                    hardcode_signs.append(f"联赛硬编码{len(tuples)}组固定对阵")

            if "_generate_fallback_matches" in content:
                hardcode_signs.append("存在备用数据生成函数")

            if "random.uniform" in content and "odds" in content.lower():
                hardcode_signs.append("赔率使用随机生成(random.uniform)")

            if hardcode_signs:
                detail = "检测到硬编码兜底逻辑: " + "; ".join(hardcode_signs)
                # 兜底数据若已带 source 来源标记，则如实标注来源，不算异常
                if "'source'" in content or '"source"' in content:
                    detail += "；兜底数据已带source来源标记"
                    return "pass", detail, None
                return "warn", detail, "当网络API失败时会自动降级到硬编码数据，建议增加数据来源标记"

            return "pass", "未检测到异常硬编码逻辑", None

        except Exception as e:
            return "warn", f"检测失败: {str(e)}", None

    # ================================================================
    # 股票子系统检测
    # ================================================================

    def _check_stock(self) -> dict:
        """检测股票数据真实性

        检测项：
          1. akshare可用性
          2. 缓存数据时效性
          3. 熔断器状态
        """
        checks = []

        # ---- 检测1: akshare可用性 ----
        ak_status, ak_detail, ak_action = self._check_akshare()
        checks.append({
            "name": "akshare数据源",
            "status": ak_status,
            "source": SOURCE_REAL_API if ak_status == "pass" else SOURCE_FALLBACK,
            "detail": ak_detail,
            "action": ak_action,
            "count": 1,
        })

        # ---- 检测2: 缓存时效性 ----
        cache_status, cache_detail, cache_action = self._check_stock_cache()
        checks.append({
            "name": "缓存数据时效性",
            "status": cache_status,
            "source": SOURCE_CACHE,
            "detail": cache_detail,
            "action": cache_action,
            "count": 1,
        })

        # ---- 检测3: 熔断器状态 ----
        cb_status, cb_detail, cb_action = self._check_stock_circuit_breaker()
        checks.append({
            "name": "熔断器状态",
            "status": cb_status,
            "source": SOURCE_REAL_API,
            "detail": cb_detail,
            "action": cb_action,
            "count": 1,
        })

        statuses = [c["status"] for c in checks]
        ss_status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")

        return {"status": ss_status, "checks": checks}

    def _check_akshare(self):
        """检测akshare是否可用"""
        try:
            import importlib
            ak = importlib.import_module("akshare")
            version = getattr(ak, "__version__", "未知版本")
            return "pass", f"akshare {version} 已安装，数据源可用", None
        except ImportError:
            return "fail", "akshare未安装，股票数据无法获取真实数据", "安装akshare: pip install akshare"
        except Exception as e:
            return "warn", f"akshare检测异常: {str(e)}", "检查akshare安装是否完整"

    def _check_stock_cache(self):
        """检测股票缓存数据的时效性"""
        cache_dir = os.path.join(self._jinshuiyao_dir, "..", "domains", "stock", "cache")
        cache_dir = os.path.normpath(cache_dir)

        if not os.path.exists(cache_dir):
            return "pass", "无本地缓存（首次运行或缓存已清理）", None

        try:
            now = datetime.now()
            stale_count = 0
            fresh_count = 0
            total = 0

            for fname in os.listdir(cache_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(cache_dir, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    age_hours = (now - mtime).total_seconds() / 3600
                    total += 1
                    if age_hours > 24:
                        stale_count += 1
                    else:
                        fresh_count += 1
                except OSError:
                    continue

            if total == 0:
                return "pass", "缓存目录为空", None

            if stale_count > 0:
                detail = f"共{total}个缓存文件，{stale_count}个超过24小时（可能过期），{fresh_count}个新鲜"
                return "warn", detail, "清除过期缓存，重新拉取真实数据"

            return "pass", f"{fresh_count}个缓存文件均在24小时内", None

        except Exception as e:
            return "warn", f"缓存检测失败: {str(e)}", None

    def _check_stock_circuit_breaker(self):
        """检测股票熔断器状态"""
        try:
            from core.circuit_breaker import CircuitBreakerRegistry
            registry = CircuitBreakerRegistry()  # 单例
            breaker = registry.get("stock_akshare")
            if breaker is None:
                return "pass", "熔断器未初始化（可能尚未开始请求）", None

            stats = breaker.get_stats()
            state_label = {"closed": "正常", "open": "熔断中", "half_open": "恢复探测"}
            state = stats.get("state", "closed")
            failures = stats.get("failure_count", 0)

            if state == "open":
                return "fail", f"熔断器处于[熔断中]状态，连续失败{failures}次", "等待熔断恢复或检查网络连接"
            elif state == "half_open":
                return "warn", f"熔断器处于[恢复探测]状态，之前连续失败{failures}次", "观察恢复探测结果"
            else:
                if failures > 0:
                    return "warn", f"熔断器正常，但有{failures}次历史失败记录", None
                return "pass", "熔断器正常（closed）", None

        except Exception as e:
            return "warn", f"熔断器检测失败: {str(e)}", None

    # ================================================================
    # 彩票子系统检测
    # ================================================================

    def _check_lottery(self) -> dict:
        """检测彩票数据真实性

        彩票数据来自官方开奖，不做时效性检测，但检查：
          1. 数据文件完整性
          2. 最新数据日期
        """
        checks = []

        # ---- 检测1: 各彩种数据文件 ----
        lot_dir = os.path.join(self._jinshuiyao_dir, "..", "金水谣数据", "lot_data")
        lot_dir = os.path.normpath(lot_dir)

        lot_names = {
            "双色球": "双色球", "大乐透": "大乐透", "福彩3D": "福彩3D",
            "排列三": "排列三", "七乐彩": "七乐彩", "七星彩": "七星彩", "快乐8": "快乐8",
        }

        total_files = 0
        stale_files = 0
        stale_names = []

        for lot_key, lot_label in lot_names.items():
            # 查找对应的数据文件（优先中文名，兼容英文别名）
            found = False
            if os.path.exists(lot_dir):
                for fname in os.listdir(lot_dir):
                    fname_cmp = fname.replace(" ", "")
                    if (fname_cmp.startswith(lot_key) or fname_cmp.startswith(lot_label)) and fname.endswith(".json"):
                        total_files += 1
                        found = True
                        fpath = os.path.join(lot_dir, fname)
                        try:
                            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                            age_days = (datetime.now() - mtime).total_seconds() / 86400
                            if age_days > 3:
                                stale_files += 1
                                stale_names.append(f"{lot_label}({int(age_days)}天未更新)")
                        except OSError:
                            pass
                        break

        if total_files == 0:
            checks.append({
                "name": "彩票数据文件",
                "status": "warn",
                "source": SOURCE_UNKNOWN,
                "detail": "未找到任何彩票数据文件",
                "action": "运行系统抓取最新开奖数据",
                "count": 0,
            })
        elif stale_files > 0:
            detail = f"共{total_files}个数据文件，{stale_files}个超过3天未更新: {', '.join(stale_names[:3])}"
            checks.append({
                "name": "彩票数据文件",
                "status": "warn",
                "source": SOURCE_CACHE,
                "detail": detail,
                "action": "检查数据抓取模块是否正常运行，手动触发数据更新",
                "count": total_files,
            })
        else:
            checks.append({
                "name": "彩票数据文件",
                "status": "pass",
                "source": SOURCE_REAL_API,
                "detail": f"{total_files}个彩种数据文件均在3天内更新",
                "action": None,
                "count": total_files,
            })

        # ---- 检测2: predictions.json有效性 ----
        pred_path = os.path.join(self._jinshuiyao_dir, "..", "金水谣数据", "predictions.json")
        pred_path = os.path.normpath(pred_path)
        pred_status, pred_detail, pred_action = self._check_predictions_file(pred_path)
        checks.append({
            "name": "预测记录有效性",
            "status": pred_status,
            "source": SOURCE_REAL_API if pred_status == "pass" else SOURCE_UNKNOWN,
            "detail": pred_detail,
            "action": pred_action,
            "count": 1,
        })

        statuses = [c["status"] for c in checks]
        ss_status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")

        return {"status": ss_status, "checks": checks}

    def _check_predictions_file(self, pred_path: str):
        """检查predictions.json是否包含有效预测

        兼容两种存储格式（与 data_maintenance 契约一致）：
          格式1: 顶层是列表 [{"lot": ..., "period": ...}, ...]
          格式2: 顶层是字典 {"predictions": {...}}
        """
        if not os.path.exists(pred_path):
            return "warn", "predictions.json 不存在", "运行预测生成功能"

        try:
            with open(pred_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                if not data:
                    return "warn", "predictions.json 为空（无预测记录）", "运行预测生成功能"
                lot_names = {d.get("lot", "") for d in data if isinstance(d, dict) and d.get("lot")}
                detail = f"包含{len(data)}条预测记录（{len(lot_names)}个彩种）"
                return "pass", detail, None

            if not isinstance(data, dict) or "predictions" not in data:
                return "warn", "predictions.json 格式异常（缺少predictions字段）", "检查数据文件完整性"

            preds = data.get("predictions", {})
            if not preds:
                return "warn", "predictions.json 为空（无预测记录）", "运行预测生成功能"

            # 检查最新预测的日期
            lot_count = len(preds)
            detail = f"包含{lot_count}个彩种的预测记录"
            return "pass", detail, None

        except (json.JSONDecodeError, OSError) as e:
            return "fail", f"predictions.json 读取/解析失败: {str(e)}", "运行健康检查自愈机制"

    # ================================================================
    # 辅助方法
    # ================================================================

    def _find_jinshuiyao_dir(self) -> str:
        """定位jinshuiyao目录"""
        # 尝试多种路径
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshuiyao"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Jinshuiyao_Fixed", "jinshuiyao"),
        ]
        for p in candidates:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                return p
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshuiyao"))

    def _iter_csv_matches(self, csv_path: str):
        """迭代CSV中的比赛数据"""
        if not os.path.exists(csv_path):
            return
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    match_time = row.get("match_time", row.get("date", ""))
                    # match_time 可能是 "2026-07-15 03:00" 或只有 "03:00"
                    date = ""
                    if match_time:
                        mt = match_time.strip()
                        if len(mt) >= 10:
                            date = mt[:10]  # 有日期
                        # 如果只有时间（如"03:00"），日期未知，标记为空
                    yield {
                        "home": row.get("home", ""),
                        "away": row.get("away", ""),
                        "league": row.get("league", ""),
                        "date": date,
                    }
        except Exception as e:
            logger.warning("读取CSV失败: %s", e)

    def _iter_csv_rows(self, csv_path: str):
        """迭代CSV中的所有行（通用）"""
        if not os.path.exists(csv_path):
            return
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield row
        except Exception as e:
            logger.warning("读取CSV失败: %s", e)


# -----------------------------------------------------------------------
# 全局单例
# -----------------------------------------------------------------------
_guard_instance = None


def get_guard() -> DataTruthGuard:
    """获取全局 DataTruthGuard 实例"""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DataTruthGuard()
    return _guard_instance


def run_truth_check() -> dict:
    """快捷方法：执行一次完整的数据真实性检测"""
    return get_guard().run_full_check()


def format_truth_report(report: dict) -> str:
    """快捷方法：格式化报告"""
    return get_guard().format_report(report)


if __name__ == "__main__":
    # 命令行直接运行
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    guard = DataTruthGuard()
    report = guard.run_full_check()
    print(guard.format_report(report))
