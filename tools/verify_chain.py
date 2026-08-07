#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""金水谣功能链路自检 - 一键验证核心链路真实联通

背景: 历史上"接线了但没真通"的问题反复出现（知识库咨询无卡、大脑能力未调用等），
用户被迫一个个试。本脚本把核心链路固化为可重复验证的检查项：

  链路1 知识库链路:   卡片 → 引擎挂钩卡(kill/weight/miss) → get_for_engine 咨询 → 系数
  链路2 智能大脑链路:  复盘学习(brain_state) → 置信度/策略权重 → 预测时应用
  链路3 预测链路:      真实跑一次 generate → 日志必须含 知识库咨询/大脑置信度/策略权重
  链路4 策略卡链路:    refresh_strategy_cards 提炼 → effectiveness 有效区间
  链路5 复盘回写链路:  复盘数据 predictions.json 可读、已复盘条目存在

用法: py -3.14 tools/verify_chain.py
输出: 每项 PASS/FAIL，任何 FAIL 时 exit 1（供收工门禁/CI 复用）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def main():
    print("=" * 60)
    print("金水谣功能链路自检")
    print("=" * 60)

    # ---------- 链路1: 知识库链路 ----------
    print("[链路1] 知识库 → 引擎挂钩卡 → 咨询系数")
    try:
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        cards = db._data.get("cards", [])
        check("知识库卡片非空", len(cards) > 0, f"{len(cards)} 张")
        hook_cards = [c for c in cards if c.get("engine_hook")]
        check("存在引擎挂钩卡", len(hook_cards) > 0, f"{len(hook_cards)} 张")
        for hook in ("kill_strategy", "weight_calibration", "miss_breakthrough"):
            got = [c for c in hook_cards if c.get("engine_hook") == hook]
            check(f"挂钩卡[{hook}]存在", len(got) > 0, f"{len(got)} 张")
        # 咨询模拟: 每类 hook 至少能取到 1 张并算出有效系数
        from engines.prediction_service import PredictionService
        import inspect
        consult = PredictionService.__dict__.get("_consult_knowledge")
        check("预测引擎已接 _consult_knowledge", consult is not None)
        for hook, dom in (("kill_strategy", "3d"), ("weight_calibration", "3d"),
                          ("miss_breakthrough", "lottery")):
            got = db.get_for_engine(hook, domain=dom, limit=1)
            ok = len(got) > 0 and 0 <= got[0].get("effectiveness", 50) <= 100
            check(f"咨询[{hook}/{dom}]可取卡", ok,
                  f"{len(got)} 张 eff={got[0].get('effectiveness') if got else '-'}")
    except Exception as e:
        check("知识库链路整体", False, str(e))

    # ---------- 链路2: 智能大脑链路 ----------
    print("[链路2] 智能大脑 → 学习状态 → 预测应用")
    try:
        from engines.smart_brain import SmartBrain
        brain = SmartBrain()
        state = brain.state
        check("大脑状态文件存在", bool(state), f"total_reviews={state.get('total_reviews', 0)}")
        check("复盘学习累计>0", state.get("total_reviews", 0) > 0)
        bias_lots = state.get("digit_bias", {})
        check("号码偏差已学习(多彩种)", len(bias_lots) >= 3, f"{len(bias_lots)} 个彩种")
        # 预测时应用函数存在
        from engines.prediction_service import PredictionService
        has_brain_app = any(hasattr(PredictionService, name)
                            for name in ("_apply_brain_adjustments",))
        check("预测引擎已接大脑修正", has_brain_app)
    except Exception as e:
        check("智能大脑链路整体", False, str(e))

    # ---------- 链路3: 预测链路（真实跑一次） ----------
    print("[链路3] 真实预测链路: generate() 日志必须含知识库/大脑输出")
    try:
        from engines.smart_brain import SmartBrain
        from engines.prediction_service import PredictionService
        from config import LOTTERY_RULES

        logs = []

        def on_log(msg, level="INFO"):
            logs.append(str(msg))

        svc = PredictionService(brain=SmartBrain(), on_log=on_log)
        # 选数据最充足的彩种
        lot = None
        for candidate in ("福彩3D", "双色球", "快乐8"):
            try:
                from models.lottery_data import Data
                if len(Data.load(candidate)) > 30:
                    lot = candidate
                    break
            except Exception:
                continue
        check("预测链路: 找到有数据的彩种", lot is not None, str(lot))
        if lot:
            result = svc.generate(lot)
            check("预测链路: 生成成功", result.get("success"), f"{lot} {len(result.get('all_nums', []))} 注")
            joined = "\n".join(logs)
            check("预测日志含 知识库咨询/增强", ("知识库" in joined), "见日志")
            check("预测日志含 大脑置信度", ("大脑置信度" in joined), "见日志")
            check("预测日志含 大脑策略权重", ("大脑策略权重" in joined), "见日志")
            # 置信度落盘检查（依赖链路3刚执行过 generate）
            try:
                from utils.safe_json import safe_load_json
                import os as _os
                bs = safe_load_json(_os.path.join(
                    PROJECT_ROOT, "金水谣数据", "brain_state.json"), default={})
                n_conf = len(bs.get("confidence_history", [])) if bs else 0
                check("大脑置信度记录已持久化", n_conf > 0, f"{n_conf} 条")
            except Exception:
                check("大脑置信度记录已持久化", False, "state 读取失败")
    except Exception as e:
        check("预测链路整体", False, str(e))

    # ---------- 链路4: 策略卡提炼链路 ----------
    print("[链路4] 复盘统计 → 策略卡提炼")
    try:
        from engines.strategy_cards import refresh_strategy_cards
        r = refresh_strategy_cards()
        total = len(r["created"]) + len(r["updated"])
        check("提炼运行无异常", isinstance(r, dict), f"新建{len(r['created'])} 更新{len(r['updated'])}")
        check("策略卡覆盖≥1彩种×3类", total >= 3, f"共 {total} 次创建/更新")
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        strat = [c for c in db._data.get("cards", [])
                 if c.get("title", "").startswith("[策略]")]
        effs = [c.get("effectiveness", 50) for c in strat]
        check("策略卡 effectiveness 均在有效区间(10-90)",
              all(10 <= e <= 90 for e in effs) and len(effs) > 0,
              f"{len(effs)} 张, 范围 {min(effs) if effs else '-'}~{max(effs) if effs else '-'}")
    except Exception as e:
        check("策略卡提炼链路整体", False, str(e))

    # ---------- 链路5: 复盘数据链路 ----------
    print("[链路5] 复盘数据 predictions.json")
    try:
        from utils.safe_json import safe_load_json
        preds = safe_load_json(os.path.join(PROJECT_ROOT, "金水谣数据", "predictions.json"), default=[])
        reviewed = [p for p in preds if isinstance(p, dict) and p.get("reviewed")]
        check("复盘数据可读且有已复盘记录", len(reviewed) > 0, f"{len(reviewed)}/{len(preds)} 条已复盘")
        import re
        bad = [p for p in reviewed if p.get("hits") is None]
        check("已复盘记录均有 hits 字段", len(bad) == 0, f"{len(bad)} 条异常")
    except Exception as e:
        check("复盘数据链路整体", False, str(e))

    # ---------- 汇总 ----------
    print("=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"结果: {passed}/{len(RESULTS)} 项通过")
    if failed:
        print(f"FAIL 项目: {[n for n, ok, _ in RESULTS if not ok]}")
        print("断链说明: 修复后重跑本脚本，全 PASS 才可继续收工。")
        sys.exit(1)
    print("全部链路联通 (PASS)")
    sys.exit(0)


if __name__ == "__main__":
    main()
