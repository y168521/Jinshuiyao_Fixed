# 金水谣知识 MCP 接入说明

金水谣项目知识库已通过 **MCP（Model Context Protocol）** 对标准模型上下文协议工具开放。任何支持 MCP 的 AI 客户端（Claude Code / Cursor / Qoder / 豆包 等）都可以直接查询项目 20 年积累的知识：经验收集箱、知识卡片、图谱三元组、项目文档。

## 服务是什么

- 实现：`tools/knowledge_mcp.py`（纯标准库 stdio JSON-RPC 2.0，零第三方依赖）
- 运行时：`D:\Project_Env\jinshuiyao_env\Scripts\python.exe`
- 工作目录：`C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed`
- 数据全部本地离线，不联网，不依赖服务器 18888 是否启动

## 工具清单

| 工具 | 参数 | 用途 |
|------|------|------|
| `search_knowledge` | query, limit=8 | 四源统一召回：知识卡片+图谱+向量+经验+项目文档 |
| `get_experience` | query, limit=5 | 只查经验收集箱（L1原始层踩坑记录），遇到报错先查它 |
| `query_graph` | query, limit=10 | 只查图谱三元组（实体-关系证据，适合多跳推理） |
| `get_index` | 无 | 知识网关索引：全资产清单+检索入口+知识流向（接入时第一个调用） |

## 接入方式

### Claude Code

```
claude mcp add --scope project jinshuiyao-knowledge -- "D:\Project_Env\jinshuiyao_env\Scripts\python.exe" "C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\knowledge_mcp.py"
```

### Cursor

在项目 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "jinshuiyao-knowledge": {
      "command": "D:\\Project_Env\\jinshuiyao_env\\Scripts\\python.exe",
      "args": ["C:\\Users\\Administrator\\Nutstore\\1\\我的坚果云\\模型\\Jinshuiyao_Fixed\\tools\\knowledge_mcp.py"]
    }
  }
}
```

### 手动冒烟测试

```
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}} | "D:\Project_Env\jinshuiyao_env\Scripts\python.exe" tools\knowledge_mcp.py
```

## 使用建议

1. 接入后第一个动作：调 `get_index` 看知识全景。
2. 任何报错/异常：先 `get_experience`（90% 的坑在经验箱里有记录，搜对词直接定位，省几小时）。
3. 精确事实/关系：`query_graph` 拿证据链。
4. 综合问题：`search_knowledge` 一次四源召回，上下文直接可用。
5. 注意：MiroFish 知识库与图谱为机器学习特化（数据真实性校验/自动蒸馏/经验模型），查询结果只作参考，最终以代码为准。
