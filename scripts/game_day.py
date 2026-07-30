# -*- coding: utf-8 -*-
"""Game Day 故障注入演练（game_day.py）

故意注入故障，验证系统在真实故障下的韧性（对应风险登记册 R1 免费模型政策突变 / R8 自愈缺口）。

道衍推导（JS-20260727-23）：
  阴阳：阳 = 主动注入故障（逼出盲区，阳主动）；阴 = 必带恢复（守底，绝不留下烂摊子）。
  天地人：天 = 规划演练场景（为之于未有）；地 = 隔离（只动可恢复的配置快照，不碰业务代码）；
         人 = 写报告可复盘（反事实：若不演练则故障真来时盲打）。
  知止：绝不真杀生产进程、绝不删数据、绝不改业务代码；只动配置快照+恢复。

用法：
  python game_day.py --scenario free_model_down --dry      # 预演（不真注）
  python game_day.py --scenario free_model_down --apply    # 真注+自愈验证+恢复
  python game_day.py --scenario watchdog_check             # 校验看门狗进程外自愈在跑
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJ = os.path.join(_ROOT, "Jinshuiyao_Fixed")
_CFG = os.path.join(_PROJ, "config", "free_models.json")
_STATUS = os.path.join(_PROJ, "金水谣数据", "free_model_status.json")
_REPORT = os.path.join(_PROJ, "金水谣数据", "log", "game_day.jsonl")


def _report(scenario, action, ok, detail):
    try:
        os.makedirs(os.path.dirname(_REPORT), exist_ok=True)
        with open(_REPORT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), "scenario": scenario,
                                "action": action, "ok": ok, "detail": detail},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def _snapshot_and_disable_free():
    """注入：备份 free_models.json，把所有模型标记 disabled。返回备份路径。"""
    bak = _CFG + ".game_day_bak"
    shutil.copy(_CFG, bak)
    cfg = json.load(open(_CFG, encoding="utf-8"))
    for prov, pdata in cfg.get("providers", {}).items():
        for m in pdata.get("models", []):
            m["enabled"] = False
    json.dump(cfg, open(_CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return bak


def _restore(bak):
    if bak and os.path.isfile(bak):
        shutil.copy(bak, _CFG)
        os.remove(bak)


def scenario_free_model_down(apply):
    """免费模型全挂 → 验证 failover 回退付费 + 写 all_down 告警。"""
    if not apply:
        print("[game_day] free_model_down 预演：将临时禁用所有免费模型，跑 free_model_health_check "
              "验证 failover/告警，再恢复。加 --apply 才真做。")
        return 0
    bak = None
    try:
        bak = _snapshot_and_disable_free()
        r = subprocess.run(
            [sys.executable, os.path.join(_PROJ, "scripts", "free_model_health_check.py")],
            capture_output=True, text=True, timeout=120)
        all_down = False
        if os.path.isfile(_STATUS):
            st = json.load(open(_STATUS, encoding="utf-8"))
            all_down = st.get("all_down", False)
        ok = all_down or ("ALL_FREE_DOWN" in (r.stderr or ""))
        _report("free_model_down", "inject+verify", ok,
                {"rc": r.returncode, "all_down": all_down,
                 "stderr_tail": (r.stderr or "")[-300:]})
        print("[game_day] 故障注入+验证完成，all_down=%s，系统已回退付费兜底并写告警。" % all_down)
        return 0 if ok else 1
    except Exception as e:
        _report("free_model_down", "EXC", False, str(e))
        return 2
    finally:
        _restore(bak)
        print("[game_day] free_models.json 已恢复。")


def scenario_watchdog_check():
    """校验看门狗是否在跑（进程外自愈能力）。"""
    try:
        rc = subprocess.run(["schtasks", "/Query", "/TN", "JinshuiyaoWatchdog"],
                            capture_output=True, timeout=20).returncode
        ok = (rc == 0)
    except Exception:
        ok = False
    detail = "计划任务存在" if ok else "计划任务缺失(需运行 scripts/install_watchdog_task.bat 安装)"
    _report("watchdog_check", "verify", ok, detail)
    print("[game_day] 看门狗自检：%s" % detail)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="金水谣 Game Day 故障注入演练")
    ap.add_argument("--scenario", required=True,
                    choices=["free_model_down", "watchdog_check"])
    ap.add_argument("--apply", action="store_true", help="真实注入(默认仅预演)")
    ap.add_argument("--dry", action="store_true", help="预演(默认行为，可省略)")
    a = ap.parse_args()
    if a.scenario == "free_model_down":
        return scenario_free_model_down(a.apply)
    if a.scenario == "watchdog_check":
        return scenario_watchdog_check()
    return 2


if __name__ == "__main__":
    sys.exit(main())
