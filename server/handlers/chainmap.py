# -*- coding: utf-8 -*-
"""金水谣系统 - 智能探路（链路地图）API

GET /api/chain-map — 跑一次智能探路，返回全链路状态 JSON。
  前端 chain-map.html 使用；探路约 10~30 秒（含一次真实预测）。

JSON 结构（route_probe.run_probe 输出）：
  generated_at  — 生成时间
  summary       — {chains, ok, broken, nodes, fail_nodes, blocked_nodes}
  chains[]      — {id, name, mode, verdict, blocks_at, nodes[]}
    nodes[]     — {id, name, status: ok|fail|blocked, detail, tip, latency_ms}
"""
import json
import os
import subprocess
import sys

from ..config import BASE_DIR, ROOT_DIR, SYSTEM_PYTHON
from ..utils import log


def _run_probe(timeout=180):
    """用独立进程跑探路器（避免阻塞服务器；A3 含一次真实 generate()）"""
    script = os.path.join(BASE_DIR, 'tools', 'route_probe.py')
    out = os.path.join(ROOT_DIR, '金水谣数据', '.tmp_chain_map.json')
    try:
        r = subprocess.run(
            [SYSTEM_PYTHON, script, '--json', out],
            capture_output=True, text=True, encoding='utf-8',
            timeout=timeout, cwd=BASE_DIR,
        )
        if os.path.isfile(out):
            with open(out, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            payload['exit_code'] = r.returncode
            try:
                os.remove(out)
            except OSError:
                pass
            return payload
        log(f"chain-map 探路无输出: rc={r.returncode} stderr={(r.stderr or '')[-500:]}")
        return {
            "generated_at": "", "error": "探路器未产出结果",
            "exit_code": r.returncode,
            "stderr": (r.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"generated_at": "", "error": f"探路超时（>{timeout}s）", "exit_code": 124}
    except Exception as e:
        import traceback
        log(f"chain-map 探路异常: {e}\n{traceback.format_exc()}")
        return {"generated_at": "", "error": f"探路异常: {e}", "exit_code": 1}


def handle_chain_map(handler):
    """GET /api/chain-map — 跑智能探路并返回链路地图 JSON"""
    try:
        payload = _run_probe()
    except Exception as e:
        log(f"chain-map 处理失败: {e}")
        handler._send_json({"ok": False, "error": f"探路失败: {e}"}, 500)
        return
    if "error" in payload and not payload.get("chains"):
        handler._send_json({"ok": False, **payload}, 500)
        return
    payload["ok"] = True
    handler._send_json(payload)
