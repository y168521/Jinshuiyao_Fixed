#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""金水谣智能探路引擎 - 像导航一样探测功能链路通不通 + 输出链路地图数据

用户心智模型: 导航出发前先探路——系统自动按拓扑逐跳探测每条"路线", 哪一跳断了
立即指出断点在哪、给出建议; 探完把结果画成地图。一眼知道哪条路通、哪条路断在哪。

本引擎把项目核心功能抽象为"链路拓扑"(节点=数据/引擎/输出/UI, 边=数据流),
逐节点真实探测(读真实文件/调真实函数/跑一次真实预测), 输出结构化地图数据(JSON):

  1. 命令行   py -3.14 tools/route_probe.py                终端表格
  2. 服务器   GET /api/chain-map → frontend/chain-map/chain-map.html 可视化地图
  3. 定位     tools/verify_chain.py 保持为收工固定回归清单(门禁),
             本引擎负责动态"视野/路口/断点"

探测模式:
  sequential(串行): 顺路逐跳, 靠前节点 FAIL → 后续标 blocked(前方道路不可达)
  parallel(并行):    各节点独立探测,互不阻断(审查工具各自独立)

诚实约束: 每个节点真实读取, 不做接口自嗨; 失败不谎报并给修复建议(tip)。
"""

import os
import sys
import json
import time
from datetime import datetime

# 金水谣项目根 = 本文件(tools/) 的上一级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_DATA_DIR = os.environ.get(
    "JINSHUIYAO_DATA", os.path.join(PROJECT_ROOT, "金水谣数据"))


def _data(rel):
    """数据目录相对路径 → 绝对路径"""
    return os.path.join(_DATA_DIR, rel)


def _node(pid, name, probe, tip=""):
    """构造一个探测节点: probe() -> (ok:bool, detail:str)"""
    return {"id": pid, "name": name, "probe": probe, "tip": tip}


def _file_ok(p):
    return os.path.isfile(p)


def _load_json(rel, default):
    try:
        from utils.safe_json import safe_load_json
        data = safe_load_json(_data(rel), default=default)
        return data
    except Exception:
        return default


def _lottery_with_data():
    """找一个历史数据≥30期的彩种(福彩3D/双色球/快乐8优先)"""
    try:
        from models.lottery_data import Data
        for cand in ("福彩3D", "双色球", "快乐8"):
            try:
                if len(Data.load(cand)) > 30:
                    return cand
            except Exception:
                continue
    except Exception:
        pass
    return None


# ===========================================================================
# 链路 A: 彩票预测全链路 (串行; A3 一次真实 generate 供 A4-A6 复用)
# ===========================================================================
_CTX = {}


def _build_a():
    def a1():
        n = 0
        for root, _, files in os.walk(_data("lot_data")):
            n += len([f for f in files if f.endswith(".json") and not f.endswith(".bak")])
        return n > 0, f"本地彩种数据 {n} 份 JSON"

    def a2():
        lot = _lottery_with_data()
        if not lot:
            return False, "未找到数据足量(≥30期)的彩种"
        try:
            from models.lottery_data import Data
            rows = Data.load(lot)
            return len(rows) > 0, f"{lot} 最近 {len(rows)} 期"
        except Exception as e:
            return False, f"Data.load 异常: {e}"

    def a3():
        lot = _lottery_with_data()
        if not lot:
            return False, "无彩种数据"
        try:
            from engines.smart_brain import SmartBrain
            from engines.prediction_service import PredictionService
            caps = []

            def on_log(msg, level="INFO"):
                caps.append(str(msg))

            svc = PredictionService(brain=SmartBrain(), on_log=on_log)
            result = svc.generate(lot)
            joined = "\n".join(caps)
            _CTX.update({
                "ok": bool(result.get("success")),
                "lot": lot,
                "nums": result.get("all_nums", []),
                "has_kb": "知识库" in joined,
                "has_conf": "大脑置信度" in joined,
                "has_w": "大脑策略权重" in joined,
            })
            if not _CTX["ok"]:
                return False, f"{lot} generate() 未成功: {result.get('error', '?')}"
            return True, f"{lot} generate() 跑通"
        except Exception as e:
            _CTX["ok"] = False
            return False, f"generate() 异常: {e}"

    def a4():
        if not _CTX.get("ok"):
            return False, "预测引擎未跑通"
        ok = bool(_CTX.get("has_kb"))
        return ok, ("预测日志含「知识库」咨询注入" if ok else
                    "日志无知识库咨询(查卡片/engine_hook)")

    def a5():
        if not _CTX.get("ok"):
            return False, "预测引擎未跑通"
        parts = []
        if _CTX.get("has_conf"):
            parts.append("置信度")
        if _CTX.get("has_w"):
            parts.append("策略权重")
        ok = bool(parts)
        return ok, ("大脑注入: 日志含 " + "+".join(parts) if parts
                    else "日志无大脑输出")

    def a6():
        if not _CTX.get("ok"):
            return False, "预测引擎未跑通"
        nums = _CTX.get("nums", [])
        return len(nums) > 0, f"选号输出 {len(nums)} 注"

    return [
        _node("A1", "历史数据就位", a1,
              "跑彩票数据拉取/导入, 保证 金水谣数据/lot_data/ 有数据"),
        _node("A2", "走势数据可读", a2,
              "查 models/lottery_data.Data.load 加载路径"),
        _node("A3", "预测引擎跑通", a3,
              "看 PredictionService.generate / 奖号规则配置"),
        _node("A4", "知识库咨询注入", a4,
              "查 prediction_service._consult_knowledge(须 db._data.get('cards'))"),
        _node("A5", "大脑修正注入", a5,
              "查 prediction_service 大脑置信度/策略权重接线"),
        _node("A6", "选号输出", a6,
              "查预测结果 all_nums 生成逻辑"),
    ]


# ===========================================================================
# 链路 B: 反馈学习闭环 (串行)
# ===========================================================================
def _build_b():
    state = {}

    def b1():
        data = _load_json("predictions.json", [])
        state["preds"] = data if isinstance(data, list) else []
        return len(state["preds"]) > 0, f"预测记录 {len(state['preds'])} 条"

    def b2():
        r = [p for p in state["preds"] if isinstance(p, dict) and p.get("reviewed")]
        return len(r) > 0, f"已复古 {len(r)} 条"

    def b3():
        r = [p for p in state["preds"] if isinstance(p, dict)
             and p.get("reviewed") and p.get("hits") is not None]
        if not r:
            return False, "已复古记录缺 hits 命中字段"
        hit = sum(1 for p in r if p.get("hits", 0) > 0)
        return True, f"命中统计 {hit}/{len(r)} 条 ({hit * 100 // len(r)}%)"

    def b4():
        try:
            from engines.strategy_cards import refresh_strategy_cards
            r = refresh_strategy_cards()
            return isinstance(r, dict), f"策略卡敲定: 新建{len(r.get('created', []))} 更新{len(r.get('updated', []))}"
        except Exception as e:
            return False, f"refresh_strategy_cards 异常: {e}"

    def b5():
        try:
            from knowledge.mirofish_db import MiroFishDB
            db = MiroFishDB()
            cards = [c for c in db._data.get("cards", [])
                     if c.get("title", "").startswith("[策略]")]
            if not cards:
                return False, "知识库无策略卡"
            effs = [c.get("effectiveness", 50) for c in cards]
            ok = all(10 <= e <= 90 for e in effs)
            return ok, f"{len(cards)} 张策略卡, eff {min(effs)}~{max(effs)}"
        except Exception as e:
            return False, f"知识库读取异常: {e}"

    return [
        _node("B1", "预测记录", b1, "查 金水谣数据/predictions.json 是否为空"),
        _node("B2", "已复古", b2, "复古入口: gui main_window/scheduler/domain/evolution"),
        _node("B3", "命中统计", b3, "复古数据缺 hits 字段, 复查 guess_vs_outcome"),
        _node("B4", "策略卡敲定", b4, "查 engines/strategy_cards.py"),
        _node("B5", "策略卡入库", b5, "知识库无策略卡 → 跑一次 refresh_strategy_cards"),
    ]


# ===========================================================================
# 链路 C: 智能大脑链路 (串行)
# ===========================================================================
def _build_c():
    from engines.smart_brain import SmartBrain
    brain = SmartBrain()
    state = brain.state or {}

    def _s():
        return brain.state or {}

    def c1():
        st = _s()
        return bool(st), f"total_reviews={st.get('total_reviews', 0)}" if st else "状态空"

    def c2():
        bias = _s().get("digit_bias", {}) or {}
        return len(bias) >= 3, f"号码偏差 {len(bias)} 个彩种"

    def c3():
        ok_m = hasattr(brain, "assess_confidence")
        hist = _s().get("confidence_history", []) or []
        return ok_m or len(hist) > 0, f"能力={'有' if ok_m else '无'} 历史={len(hist)}条"

    def c4():
        ok_m = any(hasattr(brain, m) for m in
                   ("apply_strategy_weights", "_apply_brain_adjustments"))
        weights = _s().get("strategy_weights", {}) or {}
        return ok_m or bool(weights), f"方法={'有' if ok_m else '无'} weights={len(weights)}"

    return [
        _node("C1", "大脑状态", c1, "查 金水谣数据/brain_state.json 是否存在/可读"),
        _node("C2", "号码偏差", c2, "大脑 digit_bias 未积累 → 需更多真实复盘"),
        _node("C3", "置信度能力", c3, "大脑须能给出置信度(assess_confidence)"),
        _node("C4", "策略权重能力", c4, "大脑须具备策略权重(strategy_weights)"),
    ]


# ===========================================================================
# 链路 D: 知识库链路 (串行)
# ===========================================================================
def _build_d():
    def d1():
        p = _data("knowledge") + ".json" if False else None
        # 知识库文件用项目根下 knowledge/mirofish_db.json? 实际上知识库位于仓库根
        p = os.path.join(PROJECT_ROOT, "knowledge", "mirofish_db.json")
        return _file_ok(p), ("知识库文件就位" if os.path.isfile(p) else f"缺 {p}")

    def d2():
        try:
            from knowledge.mirofish_db import MiroFishDB
            cards = MiroFishDB()._data.get("cards", [])
            return len(cards) > 0, f"知识卡片 {len(cards)} 张"
        except Exception as e:
            return False, str(e)

    def d3():
        try:
            from knowledge.mirofish_db import MiroFishDB
            cards = [c for c in MiroFishDB()._data.get("cards", [])
                     if c.get("engine_hook")]
            hooks = {}
            for c in cards:
                hooks[c["engine_hook"]] = hooks.get(c["engine_hook"], 0) + 1
            need = ("kill_strategy", "weight_calibration", "miss_breakthrough")
            ok = all(hooks.get(h, 0) > 0 for h in need)
            return ok, "引擎挂钩卡: " + ", ".join(f"{k}={v}张" for k, v in sorted(hooks.items()))
        except Exception as e:
            return False, str(e)

    def d4():
        try:
            from knowledge.mirofish_db import MiroFishDB
            db = MiroFishDB()
            for hook, dom in (("kill_strategy", "3d"), ("weight_calibration", "3d"),
                              ("miss_breakthrough", "lottery")):
                got = db.get_for_engine(hook, domain=dom, limit=1)
                if not got or not (0 <= got[0].get("effectiveness", 50) <= 100):
                    return False, f"{hook}/{dom} 取不到有效卡"
            return True, "kill/weight/miss 咨询均可取有效系数"
        except Exception as e:
            return False, str(e)

    return [
        _node("D1", "知识库文件", d1, "确认 knowledge/mirofish_db.json 路径"),
        _node("D2", "卡片库", d2, "知识库需要先建卡(用户导入/自动提取)"),
        _node("D3", "引擎挂钩卡", d3, "预测引擎挂钩卡需存在(策略卡, 由复盘敲定)"),
        _node("D4", "咨询系数", d4, "查 get_for_engine 接口与 engine_hook 域映射"),
    ]


# ===========================================================================
# 链路 E: 子系统可用性 (并行)
# ===========================================================================
def _build_e():
    def page(rel, label):
        def inner():
            p = os.path.join(PROJECT_ROOT, rel)
            return _file_ok(p), f"{label}页面就位" if os.path.isfile(p) else f"缺页面 {rel}"
        return inner

    def fund_market():
        import glob
        files = []
        for f in glob.glob(os.path.join(_data("fund_data"), "fund_monitor_*.json")):
            files.append(os.path.basename(f))
        if not files:
            return False, "基金数据缺(fund_data/fund_monitor_*.json)"
        latest = sorted(files)[-1]
        return True, f"基金行情 {latest}"

    def stock_data():
        import glob
        fs = glob.glob(os.path.join(_data("stock"), "**", "*.json"), recursive=True)
        return len(fs) > 0, f"股票数据 {len(fs)} 份" if fs else "股票数据缺"

    def football_hub():
        p = os.path.join(PROJECT_ROOT, "frontend", "football", "football-hub.html")
        return _file_ok(p), "足彩 Hub 页就位" if os.path.isfile(p) else "缺足彩页面"

    def football_data():
        import glob
        fs = glob.glob(os.path.join(_data("football"), "**", "*.json"), recursive=True) \
            if os.path.isdir(_data("football")) else []
        return len(fs) > 0, f"足彩赛事 {len(fs)} 份" if fs else "足彩数据未接入(还在建设中)"

    def lottery_hub():
        p = os.path.join(PROJECT_ROOT, "frontend", "lottery", "lottery-hub.html")
        return os.path.isfile(p), "彩票 Hub 就位" if os.path.isfile(p) else "缺彩票 Hub"

    return [
        _node("E1", "基金页面", page("frontend/fund/dashboard.html", "基金"),
              "frontend/fund/ 下页面丢失"),
        _node("E2", "基金行情", fund_market, "基金行情数据在 金水谣数据/fund_data/"),
        _node("E3", "股票页面", page("frontend/stock/stock-dashboard.html", "股票"),
              "frontend/stock/ 下页面丢失"),
        _node("E4", "股票数据", stock_data, "股票快照在 金水谣数据/stock/cache/"),
        _node("E5", "足彩页面", football_hub, "frontend/football/ 下页面丢失"),
        _node("E6", "足彩数据", football_at, "足彩数据待接入"),
        _node("E7", "彩票 Hub", lottery_hub,
              "frontend/lottery/ 下页面丢失"),
    ]


def football_at():
    import glob
    if not os.path.isdir(_data("football")):
        return False, "足彩数据未接入(目录不存在)"
    fs = glob.glob(os.path.join(_data("football"), "**", "*.json"), recursive=True)
    return len(fs) > 0, f"足彩赛事 {len(fs)} 份" if fs else "足彩数据(空)"


# ===========================================================================
# 链路 F: 审查保障链路 (并行)
# ===========================================================================
def _build_f():
    def one(rel, label):
        def inner():
            p = os.path.join(PROJECT_ROOT, rel)
            return _file_ok(p), f"{label}就位" if os.path.isfile(p) else f"缺 {rel}"
        return inner

    def check():
        p = os.path.join(PROJECT_ROOT, "tools", "check_consistency.py")
        return os.path.isfile(p), "一致性巡检就位"

    def gate():
        p1 = os.path.join(PROJECT_ROOT, "tools", "gate.py")
        p2 = os.path.join(PROJECT_ROOT, "tools", "wrapup_check.py")
        return os.path.isfile(p1) and os.path.isfile(p2), "收工门禁就位"

    def guard():
        p = os.path.join(PROJECT_ROOT, "tools", "ai_guard_rules.md")
        return os.path.isfile(p), "防再犯规则就位"

    def verify():
        return os.path.isfile(os.path.join(PROJECT_ROOT, "tools", "verify_chain.py")), "链路自检器就位"

    def docs():
        need = ["AI协作交接中心.md", "工作留痕总索引.md", "金水谣_纲.md",
                "金水谣_契.md", "金水谣_录.md"]
        missing = [d for d in need if not os.path.isfile(os.path.join(PROJECT_ROOT, d))]
        ok = not missing
        return ok, "文档体系完整" if ok else f"缺: {','.join(missing)}"

    return [
        _node("F1", "一致性巡检", one("tools/check_consistency.py", "check_consistency"),
              "提交前自动检查 路由/静态资源/Git同步/门户链接"),
        _node("F2", "收工门禁", gate, "收工前 gate.py --check + wrapup_check 全绿"),
        _node("F3", "防在犯规则", guard, "tools/ai_guard_rules.md 高频错误清单"),
        _node("F4", "链路自检器", verify, "tools/verify_chain.py 固定回归清单"),
        _node("F5", "文档体系", docs, "交接/总索引/纲/契/录 缺一不可"),
    ]


# ===========================================================================
# 链路构造总表
# ===========================================================================
def build_networks():
    return [
        {"id": "A", "name": "彩票预测全链路 (历史→走势→预测→知识库→大脑→选号)",
         "mode": "sequential", "nodes": _build_a()},
        {"id": "B", "name": "复盘学习闭环 (预测→复盘→命中统计→策略卡→知识库)",
         "mode": "sequential", "nodes": _build_b()},
        {"id": "C", "name": "智能大脑链路 (状态→偏差→置信度→策略权重)",
         "mode": "sequential", "nodes": _build_c()},
        {"id": "D", "name": "知识库链路 (卡片→引擎挂钩卡→咨询系数)",
         "mode": "sequential", "nodes": _build_d()},
        {"id": "E", "name": "子系统可用性 (基金/股票/足彩/彩票)",
         "mode": "parallel", "nodes": _build_e()},
        {"id": "F", "name": "审查保障链路 (一致性/门禁/文档)",
         "mode": "parallel", "nodes": _build_f()},
    ]


# ===========================================================================
# 探路执行
# ===========================================================================
def run_probe(networks=None):
    """执行探测, 返回链路地图结构化数据(可 JSON 序列化)"""
    nets = networks if networks is not None else build_networks()
    chains = []
    ok_chains = 0
    total_nodes = 0
    fail_nodes = 0
    blocked_nodes = 0

    for net in nets:
        mode = net.get("mode", "sequential")
        chain = {"id": net["id"], "name": net["name"], "mode": mode,
                 "nodes": [], "verdict": "ok", "blocks_at": None}
        broken = False
        for node in net["nodes"]:
            total_nodes += 1
            rec = {"id": node["id"], "name": node["name"], "status": "ok",
                   "detail": "", "tip": node.get("tip", ""), "latency_ms": 0}
            if broken and mode == "sequential":
                rec["status"] = "blocked"
                rec["detail"] = "前方节点不可达, 跳过探测"
                rec["tip"] = "修复阻断节点后可达"
                blocked_nodes += 1
                chain["nodes"].append(rec)
                continue
            t0 = time.time()
            try:
                ok, detail = node["probe"]()
            except Exception as e:
                ok, detail = False, f"探测异常: {e}"
            rec["latency_ms"] = int((time.time() - t0) * 1000)
            if ok:
                rec["status"] = "ok"
                rec["detail"] = detail or ""
            else:
                rec["status"] = "fail"
                rec["detail"] = detail or "探测失败"
                fail_nodes += 1
                if mode == "sequential" and chain["blocks_at"] is None:
                    chain["blocks_at"] = node["id"]
                broken = True
            chain["nodes"].append(rec)

        # 判定
        all_ok = all(n["status"] == "ok" for n in chain["nodes"])
        chain["verdict"] = "ok" if all_ok else "fail"
        if all_ok:
            ok_chains += 1
        chains.append(chain)

    summary = {
        "chains": len(chains),
        "ok": ok_chains,
        "broken": len(chains) - ok_chains,
        "nodes": total_nodes,
        "fail_nodes": fail_nodes,
        "blocked_nodes": blocked_nodes,
    }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "chains": chains,
    }


# ===========================================================================
# CLI
# ===========================================================================
def _print_table(payload):
    s = payload["summary"]
    print("=" * 70)
    print(f"金水谣智能探路  {payload['generated_at']}")
    print(f"  链路 {s['chains']} · 通 {s['ok']} 断 {s['broken']}"
          f" · 节点 {s['nodes']} (失败 {s['fail_nodes']}, 不可达 {s['blocked_nodes']})")
    print("=" * 70)
    for ch in payload["chains"]:
        mark = "●" if ch["verdict"] == "ok" else ("○" if ch["blocks_at"] else "✕")
        print(f"\n[{mark}] {ch['id']} {ch['name']}  "
              f"({'串行' if ch['mode'] == 'sequential' else '并行'})"
              + (f"  断点@ {ch['blocks_at']}" if ch["blocks_at"] else ""))
        for n in ch["nodes"]:
            if n["status"] == "ok":
                line = f"   ✓ {n['id']} {n['name']:<6} {n['detail']}"
            elif n["status"] == "blocked":
                line = f"   · {n['id']} {n['name']:<6} (前方不可达)"
            else:
                line = f"   ✕ {n['id']} {n['name']:<6} {n['detail']}  [!] {n['tip']}"
            print(line)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="金水谣智能探路引擎")
    ap.add_argument("--json", metavar="PATH", help="把探路结果导出 JSON(仍打印终端表格)")
    args = ap.parse_args()
    payload = run_probe()
    _print_table(payload)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n已导出地图 JSON → {args.json}")
    sys.exit(0 if payload["summary"]["broken"] == 0 else 1)


if __name__ == "__main__":
    main()