# -*- coding: utf-8 -*-
"""
金水谣系统 - 智能探路引擎单元测试

覆盖 tools/route_probe.py:
- 默认链路结构（6 条链路 / 节点数 / 串并行模式）
- 串行阻断传播（前方失败 → 后续 blocked + blocks_at）
- 并行互不阻断
- 探测异常兜底
- summary 统计与 verdict 语义
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_test_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import tools.route_probe as rp


def _net(nodes_ok, mode="sequential", nid="X", name="测试链路"):
    """构造假网络: nodes_ok=[True, False, ...] 决定各节点探测结果"""
    nodes = []
    for i, ok in enumerate(nodes_ok):
        def _probe(ok=ok, i=i):
            if ok:
                return True, f"节点{i}正常"
            raise AssertionError("fail")
        nodes.append({"id": f"{nid}{i+1}", "name": f"节点{i+1}",
                      "tip": "修复提示", "probe": _probe})
    return [{"id": nid, "name": name, "mode": mode, "nodes": nodes}]


def test_default_network_structure():
    """默认探路图: 6 条链路、串/并行各 3 条、节点数合理"""
    nets = rp.build_networks()
    ids = [n["id"] for n in nets]
    assert ids == ["A", "B", "C", "D", "E", "F"]
    modes = [n["mode"] for n in nets]
    assert modes == ["sequential", "sequential", "sequential",
                     "sequential", "parallel", "parallel"]
    total = sum(len(n["nodes"]) for n in nets)
    assert total >= 24, f"节点数过少: {total}"
    for net in nets:
        for node in net["nodes"]:
            assert callable(node["probe"]), f"{node['id']} 缺可调用 probe"
            assert node.get("tip"), f"{node['id']} 缺修复提示"


def test_sequential_blocked_propagation():
    """串行: 第2节点失败 → 第3/4节点 blocked, blocks_at 定位断点"""
    payload = rp.run_probe(_net([True, False, True, True]))
    s = payload["summary"]
    assert s["chains"] == 1 and s["ok"] == 0 and s["broken"] == 1
    assert s["fail_nodes"] == 1 and s["blocked_nodes"] == 2
    ch = payload["chains"][0]
    assert ch["verdict"] == "fail" and ch["blocks_at"] == "X2"
    st = [n["status"] for n in ch["nodes"]]
    assert st == ["ok", "fail", "blocked", "blocked"]


def test_parallel_independent():
    """并行: 某节点失败不影响其余节点, 无 blocked"""
    payload = rp.run_probe(_net([True, False, True], mode="parallel"))
    s = payload["summary"]
    assert s["ok"] == 0 and s["broken"] == 1
    assert s["fail_nodes"] == 1 and s["blocked_nodes"] == 0
    st = [n["status"] for n in payload["chains"][0]["nodes"]]
    assert st == ["ok", "fail", "ok"]


def test_probe_exception_fallback():
    """probe 抛异常 → 标 fail + detail 含'探测异常', 不中断整体"""
    def boom():
        raise RuntimeError("boom")
    net = [{"id": "Z", "name": "异常链路", "mode": "sequential",
            "nodes": [{"id": "Z1", "name": "Z1", "tip": "t", "probe": boom}]}]
    payload = rp.run_probe(net)
    n = payload["chains"][0]["nodes"][0]
    assert n["status"] == "fail"
    assert "探测异常" in n["detail"] and "boom" in n["detail"]


def test_summary_fields_and_jsonable():
    """payload 关键字段齐全且可 JSON 序列化"""
    import json
    payload = rp.run_probe(_net([True, True]))
    s = payload["summary"]
    for k in ("chains", "ok", "broken", "nodes", "fail_nodes", "blocked_nodes"):
        assert k in s, f"缺 summary.{k}"
    json.dumps(payload, ensure_ascii=False)  # 可序列化 = 可直接喂前端
    assert payload["generated_at"]
    assert payload["chains"][0]["verdict"] == "ok"


def test_all_pass_exit_semantics():
    """全通: broken=0; 有断: broken>0 (对应 CLI exit 0/1)"""
    ok = rp.run_probe(_net([True, True]))
    bad = rp.run_probe(_net([True, False]))
    assert ok["summary"]["broken"] == 0
    assert bad["summary"]["broken"] == 1
