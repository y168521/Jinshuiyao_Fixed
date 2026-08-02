# -*- coding: utf-8 -*-
"""金水谣知识 MCP 服务器（stdio / JSON-RPC 2.0，零依赖）

MCP (Model Context Protocol) 标准接入：Claude Code / Cursor / Qoder / 豆包
等外部 AI 通过本服务直接查询金水谣项目知识库（经验箱/知识卡片/图谱三元组）。

协议：stdio 逐行 JSON-RPC 2.0（initialize → tools/list → tools/call）。
无任何第三方依赖，纯标准库。

接入方式（任选其一）：
  - Claude Code:   claude mcp add --scope project jinshuiyao-knowledge -- "D:\\Project_Env\\jinshuiyao_env\\Scripts\\python.exe" "Jinshuiyao_Fixed\\tools\\knowledge_mcp.py"
  - Cursor:        .cursor/mcp.json 加入 servers 配置（见 knowledge-mcp.md）
  - 手动测试:      echo "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"search_knowledge\",\"arguments\":{\"query\":\"数据真实性\"}}}" \| python tools\knowledge_mcp.py

工具清单：
  - search_knowledge(query, limit)  四源召回：知识卡片+图谱+向量+经验+项目文档
  - get_experience(query, limit)    经验收集箱（L1原始层，踩坑记录）专查
  - query_graph(query, limit)       图谱三元组专查（实体-关系证据，多跳）
  - get_index()                     知识网关索引（规模+入口，外部AI第一读）
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NAME = 'jinshuiyao-knowledge'
VERSION = '0.1.0'


def _tools():
    return [
        {
            "name": "search_knowledge",
            "description": "四源知识召回：从知识卡片+图谱三元组+向量+经验条目+项目文档一次检索与 query 相关的知识。适合任何问题（经验/成败/方法/交接），返回带来源。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，如 '基金弹窗未初始化'"},
                    "limit": {"type": "integer", "description": "每源最多返回条数（默认8）"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_experience",
            "description": "只查经验收集箱（L1原始层）：项目踩坑/教训/方案的原始记录，跨AI共享。遇到任何报错/异常行为先查它，大概率已有记录。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，如 '相对路径'"},
                    "limit": {"type": "integer", "description": "最多返回条数（默认5）"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "query_graph",
            "description": "只查图谱三元组：实体-关系-实体证据链，适合需要精确事实/关系/多跳推理的问题（如 '谁依赖数据真实性守卫'）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，如 '数据真实性'" },
                    "limit": {"type": "integer", "description": "最多返回条数（默认10）"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "get_index",
            "description": "获取知识网关索引：项目知识资产全貌（各文档位置+规模+检索入口+知识流向）。接入项目时第一个调用。",
            "inputSchema": {"type": "object", "properties": {}}
        },
    ]


def _call(name, arguments):
    args = arguments or {}
    if name == 'get_index':
        from core.knowledge_gateway import BASE_DIR as gw_base
        idx = os.path.join(gw_base, '知识网关索引.md')
        if os.path.isfile(idx):
            with open(idx, encoding='utf-8') as f:
                return {"index": f.read()[:12000], "path": idx}
        return {"index": "索引未生成，请运行 tools/gen_knowledge_index.py", "path": idx}
    if name == 'search_knowledge':
        from core.knowledge_gateway import search
        return search(args.get('query', ''), limit=int(args.get('limit', 8)))
    if name == 'get_experience':
        from core.knowledge_gateway import _recall_experiences
        return {"experiences": _recall_experiences(args.get('query', ''), limit=int(args.get('limit', 5)))}
    if name == 'query_graph':
        from core.knowledge_gateway import _recall_triples
        return {"triples": _recall_triples(args.get('query', ''), limit=int(args.get('limit', 10)))}
    raise ValueError(f'未知工具: {name}')


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        rid = req.get('id')
        method = req.get('method', '')
        result = None
        error = None
        try:
            if method == 'initialize':
                result = {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": NAME, "version": VERSION},
                }
            elif method == 'notifications/initialized':
                result = {}
            elif method == 'tools/list':
                result = {"tools": _tools()}
            elif method == 'tools/call':
                result = {"content": [{"type": "text", "text": json.dumps(
                    _call(req.get('params', {}).get('name', ''),
                          req.get('params', {}).get('arguments', {})),
                    ensure_ascii=False)}]}
            elif method == 'ping':
                result = {}
            else:
                error = {"code": -32601, "message": f'未知方法: {method}'}
        except Exception as e:
            error = {"code": -32603, "message": str(e)}
        if rid is not None:
            resp = {"jsonrpc": "2.0", "id": rid}
            if error is not None:
                resp["error"] = error
            else:
                resp["result"] = result
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
