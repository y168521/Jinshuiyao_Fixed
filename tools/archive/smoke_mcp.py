# -*- coding: utf-8 -*-
"""MCP 服务器冒烟测试 — 一条命令验证全部握手与 4 个工具

用法: python tools/smoke_mcp.py
退出码: 0=全部通过, 1=有失败
"""
import json
import os
import subprocess
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def call(proc, msg):
    proc.stdin.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None


def main():
    fails = []
    proc = subprocess.Popen(
        [PY, os.path.join(BASE_DIR, 'tools', 'knowledge_mcp.py')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=BASE_DIR)
    try:
        # 1. initialize
        r = call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        name = (r or {}).get('result', {}).get('serverInfo', {}).get('name')
        print('[1/5] initialize      : %s' % ('OK ' + str(name) if name else 'FAIL'))
        if not name:
            fails.append('initialize')

        # 2. tools/list
        r = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = [t['name'] for t in (r or {}).get('result', {}).get('tools', [])]
        expect = ['search_knowledge', 'get_experience', 'query_graph', 'get_index']
        ok = tools == expect
        print('[2/5] tools/list       : %s %s' % ('OK' if ok else 'FAIL', tools))
        if not ok:
            fails.append('tools/list')

        # 3. get_index
        r = call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "get_index", "arguments": {}}})
        txt = (r or {}).get('result', {}).get('content', [{}])[0].get('text', '')
        ok = '知识网关索引' in txt
        print('[3/5] get_index        : %s (%d 字符)' % ('OK' if ok else 'FAIL', len(txt)))
        if not ok:
            fails.append('get_index')

        # 4. get_experience
        r = call(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "get_experience", "arguments": {"query": "知识网关"}}})
        txt = (r or {}).get('result', {}).get('content', [{}])[0].get('text', '')
        n = len(json.loads(txt).get('experiences', [])) if txt else -1
        ok = n > 0
        print('[4/5] get_experience   : %s (%d 条)' % ('OK' if ok else 'FAIL', n))
        if not ok:
            fails.append('get_experience')

        # 5. query_graph
        r = call(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "query_graph", "arguments": {"query": "数据"}}})
        txt = (r or {}).get('result', {}).get('content', [{}])[0].get('text', '')
        n = len(json.loads(txt).get('triples', [])) if txt else -1
        ok = n > 0
        print('[5/5] query_graph      : %s (%d 条)' % ('OK' if ok else 'FAIL', n))
        if not ok:
            fails.append('query_graph')
    finally:
        proc.kill()

    if fails:
        print('结果: %d 项失败 (%s)' % (len(fails), ', '.join(fails)))
        return 1
    print('结果: 全部通过 ✓ 可接入 Claude Code/Cursor')
    return 0


if __name__ == '__main__':
    sys.exit(main())
