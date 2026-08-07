#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""金水谣智能探路引擎 - 像导航一样探测功能链路通不通 + 输出链路地图数据

用户心智模型: 导航出发前先探路——系统自动按拓扑逐跳探测每条路线, 哪一跳断了
立即指出断点在哪、给出绕行建议; 探完把结果画成地图(绿=通/红=断/灰=前方断不可达)。

本引擎把项目核心功能定义为"链路拓扑"(节点=数据/引擎/输出, 边=数据流),
逐节点真实探测, 输出结构化地图数据(JSON), 供:
  - 命令行:  py -3.14 tools/route_probe.py            → 终端表格
  - 服务器:   GET /api/chain-map (server/handlers/chainmap.py) → 前端地图页渲染
  - 收工验收: tools/verify_chain.py 保持为固定回归清单(门禁), 本引擎负责动态视野

链路拓扑 (时序)                                    → 分支(并行):
  A 彩票预测全链路                                    E 子系统可用性 (基金/股票/足彩/彩票Hub)
  B 复盘学习闭环链路                                 F 审查保障系统 (dual自检/门禁/文档)
  C 智能大脑链路
  D 知识库链路

启动器语义: sequential(串行) 与 parallel(并行) 两种模式。
  sequential: 靠前节点一旦 FAIL → 后续节点标 blocked(前方道路不可达), 像导航前方塌方
  parallel:   各节点独立探测, 互不阻断(子系统/审查工具互相独立)
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

# 数据目录（相对 PROJECT_ROOT；注意允许子目录挂载时用环境变量覆盖）
_DATA_DIR = os.environ.get(
    "JINSHUIYAO_DATA", os.path.join(PROJECT_ROOT, "金水谣数据"))


# ---------------------------------------------------------------------------
# 通用探测桩
# ---------------------------------------------------------------------------

def _p(count_path):
    """给一个相对数据目录的路径, 返回绝对路径"""
    return os.path.join(_DATA_DIR, count_path)


def _is_file(p):
    return os.path.isfile(_p(p))


def _is_file_abs(p):
    return os.path.isfile(p)


def _read_json(p, default=None):
    try:
        from utils.safe_json import safe_load_json
        return safe_load_json(_p(p), default=default if default is not None else {})
    except Exception:
        return default if default is not None else {}


# ---------------------------------------------------------------------------
# 链路定义
# ---------------------------------------------------------------------------
# 每节点: {id, name, probe(-> (bool, detail)), tip(断点建议), mode 由链路决定}

def _n(id, name, probe, tip):
    return {"id": id, "name": name, "probe": probe, "tip": tip}


def _lottery_with_data():
    """找一个历史数据≥30条的彩种(DATA_LINE: 福彩3D/双色球/快乐8 之一优先)"""
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


def _build_A():
    """链路A 彩票预测全链路: 历史数据 → 走势 → 预测(含知识库/大脑) → 选号输出"""
    from engines.smart_brain import SmartBrain
    from engines.prediction_service import PredictionService
    logs = {}

    def probe_a1():
        n = 0
        for root, _, files in os.walk(_p("Data")):
            for fn in files:
                if fn.endswith(".json"):
                    n += 1
        return n > 0, f"本地历史数据文件 {n} 个"

    def probe_a2():
        lot = _lottery_with_data()
        if not lot:
            return False, "未找到历史数据足量的彩种"
        try:
            from models.lottery_data import Data
            rows = Data.load(lot)
            return len(rows) > 0, f"{lot} 最近{len(rows)}期历史数据"
        except Exception as e:
            return False, str(e)

    def _new_svc(lot):
        caps=[]
        def on_log(msg, level="INFO"):
            caps.append(str(msg))
        return PredictionService(brain=SmartBrain(), on_log=on_log), caps, lot

    def probe3():
        lot = _lottery_with_data()
        if not lot:
            return False, "无彩种数据"
        try:
            svc_cfg = _new_svc(lot)
            svc, caps, lot = svc_cfg[0], svc_cfg[1], svc_cfg[2]
            svc._probe_ctx = caps  # 保存日志收集器供后续节点复用
            result = svc.generate(lot)
            if not result.get("success"):
                return False, f"generate 未成功: {result.get('error', '?')}"
            return True, f"{lot} generate() 成功"
        except Exception as e:
            return False, f"generate() 异常: {e}"

    # 链路对象: 顺序执行为 main 部分; 这里需要共享一次跑出来的 generate 日志，
    # 采用"探测函数共享实例句柄"方式: 一次 generate 里连续检查知识库/大脑/输出三段。
    # 为简单与确定性, 把 知识库咨询/大脑修正/选号输出 合并进一个重节点在探路逻辑中
    # 另行实现(见下), build_A 返回 精简五节点。
    def probe_generated(which):
        """主 generate 由 probe_generate 执行一次; 由 merge_all 节点调用恢复共享"""
        try:
            ctx = _ctx.get(which)
            if ctx is None:
                return False, "未执行真实 generate"
            return ctx
        except Exception as e:
            return False, str(e)

    # 单次真实 generate 跑五个子检验(知识库咨询/大脑置信度/大脑策略权重/选号输出)
    # 存储到共享上下文
    SHARED = {}

    def probe_generate_real():
        """真实跑一次预测, 记录日志与结果供后继节点复用"""
        lot = _lottery_with_data()
        if not lot:
            return False, "无彩种数据"
        try:
            caps = []
            svc = PredictionService(brain=SmartBrain(), on_log=lambda m, lvl="INFO": caps.append(str(m)))
            result = svc.generate(lot)
            joined = "\n".join(caps)
            SHARED.update({
                "ok": bool(result.get("success")),
                "lot": lot,
                "nums": result.get("all_nums", []),
                "msg": "……(见详情)",
                "has_kb": "知识库" in joined,
                "has_conf": "大脑置信度" in joined,
                "has_w": "大脑策略权重" in joined,
                "log": joined[-2000:],
            })
            if not SHARED["ok"]:
                return False, f"{lot} generate() 未成功: {result.get('error', '?')}"
            return True, f"{lot} generate() ok"
        except Exception as e:
            SHARED["ok"] = False
            return False, f"generate() 异常: {e}"

    def probe_nums():
        if not SHARED.get("ok"):
            return False, "未执行真实 generate"
        return len(SHARED.get("nums", [])) > 0, f"选号输出 {len(SHARED.get('nums', []))} 注"

    def probe_kb():
        if not SHARED.get("ok"):
            return False, "未执行真实 generate"
        return bool(SHARED.get("has_kb")), "预测日志含「知识库」咨询记录" if SHARED.get("has_kb") else "日志无知识库咨询(可能知识卡片缺失)"

    def probe_brain():
        if not SHARED.get("ok"):
            return False, "未执行真实 generate"
        detail = []
        if SHARED.get("has_conf"):
            detail.append("置信度")
        if SHARED.get("has_w"):
            detail.append("策略权重")
        ok = bool(SHARED.get("has_conf") and SHARED.get("has_w"))
        return ok, ("日志含大脑" + "+".join(detail) if detail else "日志无大脑输出")

    def probe_nums():
        return probe_num_ok(SHARED)

    def probe_num_ok(sh):
        return sh.get("ok", False) and len(sh.get("nums", [])) > 0

    return [
        _n("A1", "历史数据就位", probe1, "补数据: 运行彩票数据拉取/导入"),
        _n("A2", "走势数据可读", probe2, "检查 Data 加载与历史彩种"),
        _n("A3", "预测引擎跑通", probe_generate_real, "看预测服务/模型/奖号规则配置",
           reduce="A4-A6 依赖本次真实 generate"),
        _n("A4", "知识库咨询注入", probe_kb, "查 `prediction_service._consult_knowledge`(应改 `db._data.get(\"cards\")`)", dep=["A3"]),
        _n("A5", "大脑修正注入", probe_brain, "查 prediction_service 大脑置信度/策略权重接线", dep=["A3"]),
        _n("A6", "选号输出", probe_nums, "查预测结果 all_nums 生成逻辑", dep=["A3"]),
    ]


def build_networks():
    """构建全部探测链路拓扑(顺序执行无副作用); 供 test 与 server 使用"""
    # 链路A 特殊(共享一次真实 generate)
    a_nodes = _build_a_nodes()
    # 链路B 反馈闭环
    b_nodes = _build_b_nodes()
    # 链路C 信号大脑
    c_nodes = _build_c_nodes()
    # 链路D 知识库
    d_nodes = _build_d_nodes()
    # 链路E 子系统(parallel)
    e_nodes = _build_e_nodes()
    # 链路F 审查保障(parallel)
    f_nodes = _build_f_nodes()

    return [
        {"id": "A", "name": "彩票预测全链路（历史→预测→知识库→大脑→选号）", "mode": "sequential", "nodes": a_nodes},
        {"id": "B", "name": "反馈学习闭环（预测→复盘→命中统计→策略卡→知识库）,  sequential, nodes b_nodes},
        {"id": "C", "name": "智能大脑链路（状态→偏差→置信度→策略权重）", "mode": "sequential", "nodes": c_nodes},
        {"id": "D", "name": "知识库链路（卡片→引擎挂钩卡→咨询系数）", "mode": "sequential", "nodes": d_nodes},
        {"id": "E", "name": "子系统可用性（基金/股票/足彩/彩票）", "mode": "parallel", "nodes": e_nodes},
        {"id": "F", "name": "审查保障链路（一致性/门禁/文档）", "mode": "parallel", "nodes": f_nodes},
    ]