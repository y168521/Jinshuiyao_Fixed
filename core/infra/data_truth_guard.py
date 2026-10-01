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
from typing import Optional, List, Dict

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

# -----------------------------------------------------------------------
# 新鲜度阈值（天）：JS-20260920-15 从函数体内的魔数提出来
# —— 阈值写死在函数里，文档就无从指向它，改的人也找不到它（标准唯一真源 §五-1）
# -----------------------------------------------------------------------
MATCH_STALE_WARN_DAYS = 30    # 历史赛果超过 30 天未补更 → warn
MATCH_STALE_FAIL_DAYS = 180   # 历史赛果超过 180 天 → fail（赛季彻底过时）
LOT_STALE_WARN_DAYS = 3       # 彩票数据文件超过 3 天未更新 → warn


def _dtg_find_jinshuiyao_dir() -> str:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshuiyao"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Jinshuiyao_Fixed", "jinshuiyao"),
    ]
    for p in candidates:
        p = os.path.normpath(p)
        if os.path.isdir(p):
            return p
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jinshuiyao"))


def _dtg_iter_csv_matches(csv_path: str):
    if not os.path.exists(csv_path):
        return
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mt = (row.get("match_time", row.get("date", "")) or "").strip()
                date = mt[:10] if len(mt) >= 10 else ""
                yield {"home": row.get("home", ""), "away": row.get("away", ""),
                       "league": row.get("league", ""), "date": date}
    except Exception as e:
        logger.warning("读取CSV失败: %s", e)


def _dtg_iter_csv_rows(csv_path: str):
    if not os.path.exists(csv_path):
        return
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield row
    except Exception as e:
        logger.warning("读取CSV失败: %s", e)


def _dtg_count_real_json(json_path: str) -> int:
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return len(json.load(f).get("matches") or [])
    except Exception:
        return 0


def _dtg_check_real_json(json_path: str, today: str):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        matches = payload.get("matches") or []
        if not matches:
            return "warn", SOURCE_UNKNOWN, f"真实赛事 JSON 为空（{json_path}）", "执行足彩数据刷新"
        source = payload.get("source", "sporttery")
        total = len(matches)
        expired = future = today_matches = 0
        for m in matches:
            date = str(m.get("match_time", "") or "")[:10]
            if not date:
                continue
            if date < today:
                expired += 1
            elif date == today:
                today_matches += 1
            else:
                future += 1
        if future or today_matches:
            return "pass", SOURCE_CACHE, f"共{total}场真实赛事（{source}），未来/今日{today_matches + future}场，历史{expired}场", None
        return "warn", SOURCE_CACHE, f"共{total}场真实赛事（{source}），全部已过期，请刷新", "执行足彩数据刷新"
    except Exception as e:
        return "warn", SOURCE_UNKNOWN, f"真实赛事 JSON 读取失败: {e}", None


def _dtg_check_real_odds(json_path: str):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            matches = json.load(f).get("matches") or []
        if not matches:
            return "warn", "真实赛事 JSON 为空，无赔率可检", None
        bad = []
        checked = unsold = 0
        for m in matches:
            mid = m.get("match_id", "?")
            trio = []
            for key in ("odds_win", "odds_draw", "odds_lose"):
                raw = m.get(key)
                if raw is None or (isinstance(raw, str) and raw.strip() in ("", "-1")):
                    continue
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if val <= 0:
                    continue
                trio.append((key, val))
            if not trio:
                unsold += 1
                continue
            checked += 1
            for key, val in trio:
                if val < 1.01 or val > 1000.0:
                    bad.append(f"{mid}({key}={val})")
        if bad:
            return "warn", f"{len(bad)} 处赔率数值异常（合理区间 1.01~1000）: {bad[:5]}", "检查赔率来源，更新为真实赔率数据"
        detail = f"{checked} 场含赔率的比赛数值均正常（体彩官方源）"
        if unsold:
            detail += f"；{unsold} 场未开售/无胜平负盘口（正常，已跳过）"
        return "pass", detail, None
    except Exception as e:
        return "warn", f"赔率检查失败: {e}", None


def _dtg_check_csv_matches(csv_path: str, today: str):
    if not os.path.exists(csv_path):
        return "warn", SOURCE_UNKNOWN, f"CSV文件不存在（{csv_path}）", None
    matches = list(_dtg_iter_csv_matches(csv_path))
    if not matches:
        return "warn", SOURCE_UNKNOWN, "CSV文件为空", None
    total = len(matches)
    expired = [m for m in matches if m.get("date") and m["date"] < today]
    today_m = [m for m in matches if m.get("date") == today]
    future = [m for m in matches if m.get("date") and m["date"] > today]
    no_date = [m for m in matches if not m.get("date")]
    if expired:
        valid = len(today_m) + len(future)
        if valid > 0:
            return "pass", SOURCE_CACHE, f"共{total}场，未来/今日{valid}场，历史{len(expired)}场（回测素材）", None
        detail = f"共{total}场，已过期{len(expired)}场，今日{len(today_m)}场，未来{len(future)}场"
        for m in expired[:3]:
            detail += f"\n    过期: {m.get('league', '')} {m.get('home', '')} vs {m.get('away', '')} ({m['date']})"
        return "fail", SOURCE_FALLBACK, detail, "移除已过期的比赛数据，更新为当前赛事"
    if no_date:
        if len(no_date) == total:
            return "warn", SOURCE_UNKNOWN, f"共{total}场，match_time缺少日期，无法判断时效性", "补充完整日期"
        detail = f"共{total}场，{len(no_date)}场缺少日期"
        if today_m or future:
            return "pass", SOURCE_CACHE, detail + f"，有{len(today_m) + len(future)}场有效", None
        return "warn", SOURCE_UNKNOWN, detail, "补充缺失的日期信息"
    if today_m:
        return "pass", SOURCE_CACHE, f"共{total}场，今日{len(today_m)}场，未来{len(future)}场 — 时效性正常", None
    if future:
        return "pass", SOURCE_CACHE, f"共{total}场，全部为未来赛事（无今日比赛）", None
    return "warn", SOURCE_UNKNOWN, f"共{total}场，无法判断日期有效性", "检查比赛日期字段格式"


def _dtg_check_odds_validity(odds_path: str):
    if not os.path.exists(odds_path):
        return "warn", "赔率文件不存在", None
    skip = {"match_id", "match", "id", "home", "away", "league", "date", "time"}
    issues = []
    rows = list(_dtg_iter_csv_rows(odds_path))
    for row in rows:
        try:
            vals = []
            for k, v in row.items():
                if k.strip().lower() in skip:
                    continue
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    continue
            for v in vals:
                if v < 1.01 or v > 50.0:
                    issues.append(f"赔率 {v:.2f} 超出合理范围(1.01-50.0)")
            if len(vals) >= 3 and vals[0] == vals[1] == vals[2]:
                issues.append(f"胜平负赔率完全相同({vals[0]:.2f})，疑似假数据")
        except (ValueError, TypeError):
            issues.append("赔率格式错误")
    if issues:
        return "fail", "发现异常: " + "; ".join(issues[:3]), "检查赔率来源，更新为真实赔率数据"
    return "pass", f"{len(rows)}组赔率均在合理范围内", None


def _dtg_check_hardcoded_football(jinshuiyao_dir: str):
    fetcher_path = os.path.join(jinshuiyao_dir, "fetcher.py")
    if not os.path.exists(fetcher_path):
        return "warn", "fetcher.py 不存在，无法检测", None
    try:
        with open(fetcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        signs = []
        if "_generate_fallback_matches" in content:
            signs.append("存在备用数据生成函数")
        if "random.uniform" in content and "odds" in content.lower():
            signs.append("赔率使用随机生成")
        if signs:
            return "warn", "检测到硬编码兜底逻辑: " + "; ".join(signs), "删除模拟兜底，改用真实数据源"
        return "pass", "未检测到硬编码/模拟兜底逻辑（演示数据已剔除）", None
    except Exception as e:
        return "warn", f"检测失败: {e}", None


def _dtg_check_history_freshness(csv_path: str):
    if not os.path.exists(csv_path):
        return "warn", f"历史赛果素材不存在（{csv_path}）", "生成 matches_real.csv 回测素材"
    try:
        dates = []
        total = 0
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                total += 1
                mt = (row.get("match_time") or "").strip()
                if len(mt) >= 10:
                    try:
                        dates.append(datetime.strptime(mt[:10], "%Y-%m-%d"))
                    except ValueError:
                        continue
        if not dates:
            return "warn", f"历史赛果素材共{total}行，match_time 无可解析日期", "检查 match_time 字段格式"
        newest = max(dates)
        age_days = (datetime.now() - newest).days
        if age_days > MATCH_STALE_FAIL_DAYS:
            return ("fail", f"历史赛果最新一场为 {newest:%Y-%m-%d}（{age_days}天前），已超{MATCH_STALE_FAIL_DAYS}天",
                    "补更最新赛季真实赛果，或暂停基于该素材的回测")
        if age_days > MATCH_STALE_WARN_DAYS:
            return ("warn", f"历史赛果最新一场为 {newest:%Y-%m-%d}（{age_days}天前），超{MATCH_STALE_WARN_DAYS}天未补更",
                    "将已完赛的真实结果追加进 matches_real.csv")
        return "pass", f"历史赛果最新一场为 {newest:%Y-%m-%d}（{age_days}天前），共{total}行，新鲜度正常", None
    except Exception as e:
        return "warn", f"历史赛果新鲜度检测失败: {e}", None


def _dtg_check_football(jinshuiyao_dir: str) -> dict:
    checks = []
    today = datetime.now().strftime("%Y-%m-%d")
    real_json = os.path.join(os.path.dirname(jinshuiyao_dir), "金水谣数据", "football_matches.json")
    if not os.path.exists(real_json):
        real_json = None
    primary_csv = os.path.join(jinshuiyao_dir, "data", "matches_real.csv")
    fallback_csv = os.path.join(jinshuiyao_dir, "data", "matches_supplemented.csv")
    csv_path = primary_csv if os.path.exists(primary_csv) else fallback_csv
    if real_json:
        csv_status, csv_source, csv_detail, csv_action = _dtg_check_real_json(real_json, today)
        total_count = _dtg_count_real_json(real_json)
    else:
        csv_status, csv_source, csv_detail, csv_action = _dtg_check_csv_matches(csv_path, today)
        total_count = sum(1 for _ in _dtg_iter_csv_matches(csv_path))
    checks.append({"name": "赛事数据时效性", "status": csv_status, "source": csv_source,
                   "detail": csv_detail, "action": csv_action, "count": total_count, "counts_as_source": True})
    if real_json:
        odds_status, odds_detail, odds_action = _dtg_check_real_odds(real_json)
        odds_count = _dtg_count_real_json(real_json)
    else:
        odds_path = os.path.join(jinshuiyao_dir, "data", "odds.csv")
        odds_status, odds_detail, odds_action = _dtg_check_odds_validity(odds_path)
        odds_count = sum(1 for _ in _dtg_iter_csv_rows(odds_path))
    checks.append({"name": "赔率合理性", "status": odds_status, "source": csv_source,
                   "detail": odds_detail, "action": odds_action, "count": odds_count, "counts_as_source": False})
    hc_s, hc_d, hc_a = _dtg_check_hardcoded_football(jinshuiyao_dir)
    checks.append({"name": "硬编码兜底检测", "status": hc_s, "source": SOURCE_HARDCODED,
                   "detail": hc_d, "action": hc_a, "count": 0, "counts_as_source": False})
    hist_s, hist_d, hist_a = _dtg_check_history_freshness(primary_csv)
    checks.append({"name": "历史赛果新鲜度", "status": hist_s, "source": SOURCE_CACHE,
                   "detail": hist_d, "action": hist_a, "count": 0, "counts_as_source": False})
    statuses = [c["status"] for c in checks]
    ss = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {"status": ss, "checks": checks}


def _dtg_check_akshare():
    try:
        import importlib
        ak = importlib.import_module("akshare")
        return "pass", f"akshare {getattr(ak, '__version__', '未知版本')} 已安装，数据源可用", None
    except ImportError:
        return "fail", "akshare未安装，股票数据无法获取真实数据", "安装akshare: pip install akshare"
    except Exception as e:
        return "warn", f"akshare检测异常: {e}", "检查akshare安装是否完整"


def _dtg_check_stock_cache(jinshuiyao_dir: str):
    cache_dir = os.path.normpath(os.path.join(jinshuiyao_dir, "..", "domains", "stock", "cache"))
    if not os.path.exists(cache_dir):
        return "pass", "无本地缓存（首次运行或缓存已清理）", None
    try:
        now = datetime.now()
        stale = fresh = total = 0
        for fname in os.listdir(cache_dir):
            if not fname.endswith(".json"):
                continue
            try:
                age_hours = (now - datetime.fromtimestamp(os.path.getmtime(os.path.join(cache_dir, fname)))).total_seconds() / 3600
                total += 1
                if age_hours > 24:
                    stale += 1
                else:
                    fresh += 1
            except OSError:
                continue
        if total == 0:
            return "pass", "缓存目录为空", None
        if stale > 0:
            return "warn", f"共{total}个缓存，{stale}个超24小时，{fresh}个新鲜", "清除过期缓存，重新拉取真实数据"
        return "pass", f"{fresh}个缓存文件均在24小时内", None
    except Exception as e:
        return "warn", f"缓存检测失败: {e}", None


def _dtg_check_stock_circuit_breaker():
    try:
        from core.infra.circuit_breaker import CircuitBreakerRegistry
        breaker = CircuitBreakerRegistry().get("stock_akshare")
        if breaker is None:
            return "pass", "熔断器未初始化（可能尚未开始请求）", None
        stats = breaker.get_stats()
        state = stats.get("state", "closed")
        failures = stats.get("failure_count", 0)
        if state == "open":
            return "fail", f"熔断器处于[熔断中]，连续失败{failures}次", "等待熔断恢复或检查网络连接"
        if state == "half_open":
            return "warn", f"熔断器处于[恢复探测]，之前连续失败{failures}次", "观察恢复探测结果"
        if failures > 0:
            return "warn", f"熔断器正常，但有{failures}次历史失败记录", None
        return "pass", "熔断器正常（closed）", None
    except Exception as e:
        return "warn", f"熔断器检测失败: {e}", None


def _dtg_check_stock(jinshuiyao_dir: str) -> dict:
    checks = []
    ak_s, ak_d, ak_a = _dtg_check_akshare()
    checks.append({"name": "akshare数据源", "status": ak_s, "source": SOURCE_REAL_API if ak_s == "pass" else SOURCE_FALLBACK,
                   "detail": ak_d, "action": ak_a, "count": 1})
    cs_s, cs_d, cs_a = _dtg_check_stock_cache(jinshuiyao_dir)
    checks.append({"name": "缓存数据时效性", "status": cs_s, "source": SOURCE_CACHE,
                   "detail": cs_d, "action": cs_a, "count": 1})
    cb_s, cb_d, cb_a = _dtg_check_stock_circuit_breaker()
    checks.append({"name": "熔断器状态", "status": cb_s, "source": SOURCE_REAL_API,
                   "detail": cb_d, "action": cb_a, "count": 1})
    statuses = [c["status"] for c in checks]
    ss = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {"status": ss, "checks": checks}


def _dtg_check_predictions_file(pred_path: str):
    if not os.path.exists(pred_path):
        return "warn", "predictions.json 不存在", "运行预测生成功能"
    try:
        with open(pred_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            if not data:
                return "warn", "predictions.json 为空（无预测记录）", "运行预测生成功能"
            lot_names = {d.get("lot", "") for d in data if isinstance(d, dict) and d.get("lot")}
            no_time = [d for d in data if isinstance(d, dict) and not d.get("time") and not d.get("date")]
            if no_time:
                return "warn", f"predictions.json 有{len(no_time)}条记录缺时间字段", "检查预测生成写入端字段契约"
            return "pass", f"包含{len(data)}条预测记录（{len(lot_names)}个彩种）", None
        if not isinstance(data, dict) or "predictions" not in data:
            return "warn", "predictions.json 格式异常（缺少predictions字段）", "检查数据文件完整性"
        preds = data.get("predictions", {})
        if not preds:
            return "warn", "predictions.json 为空（无预测记录）", "运行预测生成功能"
        return "pass", f"包含{len(preds)}个彩种的预测记录", None
    except (json.JSONDecodeError, OSError) as e:
        return "fail", f"predictions.json 读取/解析失败: {e}", "运行健康检查自愈机制"


def _dtg_check_lottery(jinshuiyao_dir: str) -> dict:
    checks = []
    lot_dir = os.path.normpath(os.path.join(jinshuiyao_dir, "..", "金水谣数据", "lot_data"))
    lot_names = {"双色球": "双色球", "大乐透": "大乐透", "福彩3D": "福彩3D", "排列三": "排列三",
                 "七乐彩": "七乐彩", "七星彩": "七星彩", "快乐8": "快乐8"}
    total_files = stale_files = 0
    stale_names = []
    if os.path.exists(lot_dir):
        for lot_key, lot_label in lot_names.items():
            for fname in os.listdir(lot_dir):
                fc = fname.replace(" ", "")
                if (fc.startswith(lot_key) or fc.startswith(lot_label)) and fname.endswith(".json"):
                    total_files += 1
                    try:
                        age_days = (datetime.now() - datetime.fromtimestamp(
                            os.path.getmtime(os.path.join(lot_dir, fname)))).total_seconds() / 86400
                        if age_days > LOT_STALE_WARN_DAYS:
                            stale_files += 1
                            stale_names.append(f"{lot_label}({int(age_days)}天未更新)")
                    except OSError:
                        pass
                    break
    if total_files == 0:
        checks.append({"name": "彩票数据文件", "status": "warn", "source": SOURCE_UNKNOWN,
                       "detail": "未找到任何彩票数据文件", "action": "运行系统抓取最新开奖数据", "count": 0})
    elif stale_files > 0:
        detail = f"共{total_files}个数据文件，{stale_files}个超{LOT_STALE_WARN_DAYS}天未更新: {', '.join(stale_names[:3])}"
        checks.append({"name": "彩票数据文件", "status": "warn", "source": SOURCE_CACHE,
                       "detail": detail, "action": "检查数据抓取模块是否正常运行", "count": total_files})
    else:
        checks.append({"name": "彩票数据文件", "status": "pass", "source": SOURCE_REAL_API,
                       "detail": f"{total_files}个彩种数据文件均在3天内更新", "action": None, "count": total_files})
    pred_path = os.path.normpath(os.path.join(jinshuiyao_dir, "..", "金水谣数据", "predictions.json"))
    ps, pd, pa = _dtg_check_predictions_file(pred_path)
    checks.append({"name": "预测记录有效性", "status": ps,
                   "source": SOURCE_REAL_API if ps == "pass" else SOURCE_UNKNOWN,
                   "detail": pd, "action": pa, "count": 1})
    statuses = [c["status"] for c in checks]
    ss = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {"status": ss, "checks": checks}


def _dtg_run_full_check(jinshuiyao_dir: str) -> dict:
    subsystems = {
        "football": _dtg_check_football(jinshuiyao_dir),
        "stock": _dtg_check_stock(jinshuiyao_dir),
        "lottery": _dtg_check_lottery(jinshuiyao_dir),
    }
    source_dist = {SOURCE_REAL_API: 0, SOURCE_CACHE: 0, SOURCE_FALLBACK: 0, SOURCE_HARDCODED: 0, SOURCE_UNKNOWN: 0}
    for ss in subsystems.values():
        for chk in ss.get("checks", []):
            if not chk.get("counts_as_source", True):
                continue
            src = chk.get("source", SOURCE_UNKNOWN)
            if src in source_dist:
                source_dist[src] += chk.get("count", 1)
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for ss in subsystems.values():
        summary[ss["status"]] = summary.get(ss["status"], 0) + 1
    if summary["fail"] > 0:
        overall = "critical"
    elif summary["warn"] > 0:
        overall = "degraded"
    else:
        overall = "healthy"
    actions = []
    for ss_name, ss in subsystems.items():
        for chk in ss.get("checks", []):
            if chk.get("action"):
                actions.append(f"[{ss_name}] {chk['action']}")
    report = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "overall": overall,
              "subsystems": subsystems,
              "source_distribution": {k: v for k, v in source_dist.items() if v > 0},
              "summary": summary, "action_required": actions}
    try:
        from core.infra.audit_log import log_event
        log_event(event_type="DATA_TRUTH", subsystem="global", summary=f"数据真实性检测: {overall}",
                  detail=f"通过={summary['pass']}, 警告={summary['warn']}, 失败={summary['fail']}",
                  data={"source_distribution": source_dist},
                  level="info" if overall == "healthy" else ("warn" if overall == "degraded" else "error"))
    except Exception:
        logger.debug("审计日志写入跳过（DATA_TRUTH）")
    return report


def _dtg_format_report(report: dict) -> str:
    lines = ["=" * 60, "  金水谣系统 - 数据真实性检测报告", f"  {report['timestamp']}", "=" * 60]
    overall_map = {"healthy": "✅ 健康", "degraded": "⚠️ 降级", "critical": "❌ 异常"}
    lines.extend(["", f"总体状态: {overall_map.get(report['overall'], report['overall'])}"])
    dist = report.get("source_distribution", {})
    if dist:
        lines.extend(["", "数据来源分布:"])
        for src, count in dist.items():
            lines.append(f"  {SOURCE_LABELS.get(src, src)}: {count}条")
    status_map = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
    for ss_name, ss in report.get("subsystems", {}).items():
        ss_label = {"football": "足彩", "stock": "股票", "lottery": "彩票"}.get(ss_name, ss_name)
        lines.extend(["", "-" * 40, f"  {ss_label}子系统 {status_map.get(ss['status'], '')}"])
        for chk in ss.get("checks", []):
            icon = status_map.get(chk.get("status", "pass"), "  ")
            src_label = SOURCE_LABELS.get(chk.get("source", ""), chk.get("source", ""))
            lines.append(f"  {icon} [{src_label}] {chk.get('name', '')}")
            lines.append(f"      {chk.get('detail', '')}")
            if chk.get("action"):
                lines.append(f"      → {chk['action']}")
    actions = report.get("action_required", [])
    if actions:
        lines.extend(["", "-" * 40, "  需要关注的操作:"])
        for act in actions:
            lines.append(f"  ⚡ {act}")
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


class DataTruthGuard:
    """全局数据真实性守卫（方法委托模块级函数）。"""

    def __init__(self):
        self._report_items = []
        self._jinshuiyao_dir = _dtg_find_jinshuiyao_dir()

    def run_full_check(self) -> dict:
        return _dtg_run_full_check(self._jinshuiyao_dir)

    def format_report(self, report: dict) -> str:
        return _dtg_format_report(report)

    def _check_csv_matches(self, csv_path: str, today: str):
        return _dtg_check_csv_matches(csv_path, today)

    def _check_odds_validity(self, odds_path: str):
        return _dtg_check_odds_validity(odds_path)

    def _check_hardcoded_football(self):
        return _dtg_check_hardcoded_football(self._jinshuiyao_dir)

    def _check_akshare(self):
        return _dtg_check_akshare()

    def _check_stock_cache(self):
        return _dtg_check_stock_cache(self._jinshuiyao_dir)

    def _check_predictions_file(self, pred_path: str):
        return _dtg_check_predictions_file(pred_path)


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
