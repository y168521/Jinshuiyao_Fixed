---
name: api-design
description: RESTful API接口设计技能，FastAPI开发、参数校验、统一错误处理、接口文档、性能测试。使用场景：后端接口设计、FastAPI开发、接口参数校验、统一错误处理、接口文档生成、接口压力测试。
---

# API 接口设计技能

## RESTful 设计规范

### 核心原则
1. **资源导向**：URL 用名词，不用动词
2. **HTTP 方法对应操作**：GET查、POST增、PUT改、DELETE删
3. **版本控制**：URL 带版本号 /api/v1/...
4. **无状态**：每次请求包含所有信息

### URL 命名规范
- 全部小写，单词用连字符 -
- 复数形式表示集合：/users、/matches
- 层级关系：/leagues/{league_id}/teams/{team_id}

### 统一响应格式
```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

### 状态码规范
| code | 含义 |
|------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未授权 |
| 403 | 无权限 |
| 404 | 不存在 |
| 500 | 服务器错误 |

## FastAPI 开发

### 为什么选 FastAPI
- 自动生成 API 文档（Swagger UI）
- 自动参数校验（Pydantic）
- 异步支持，性能好
- 类型提示，代码提示友好

### 基础示例
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="彩票数据API", version="1.0.0")

# 请求模型
class RecordQuery(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    morphology: Optional[str] = None
    page: int = 1
    page_size: int = 20

# 响应模型
class RecordItem(BaseModel):
    period: str
    draw_date: str
    num1: int
    num2: int
    num3: int
    morphology: str

@app.get("/api/v1/lottery/3d")
def get_3d_records(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    morphology: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """获取福彩3D开奖记录"""
    if page < 1:
        raise HTTPException(status_code=400, detail="页码不能小于1")
    
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total": 100,
            "page": page,
            "page_size": page_size,
            "list": []
        }
    }
```

### 参数校验（Pydantic）
```python
from pydantic import BaseModel, Field, validator

class PredictRequest(BaseModel):
    match_id: int = Field(..., gt=0, description="赛事ID")
    model_type: str = Field(..., pattern="^(poisson|elo)$")
    history_days: int = Field(30, ge=7, le=365)
```

### 全局异常处理
```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": f"服务器内部错误: {str(exc)}"}
    )
```

## 分页规范

### 请求参数
- page: 页码，从1开始，默认1
- page_size: 每页数量，默认20，最大100

### 响应结构
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "total": 1560,
    "page": 1,
    "page_size": 20,
    "total_pages": 78,
    "list": []
  }
}
```

## 接口安全

### 基础认证
- API Key：请求头 X-API-Key
- JWT Token：Authorization: Bearer xxx

### 限流
- 按 IP 限流
- 按用户限流

### 输入校验
- 所有入参必须校验
- SQL 注入防护：参数化查询
- XSS 防护：输出转义

## 性能测试

### 工具：httpx / locust
```python
import httpx
import time

def benchmark():
    start = time.time()
    with httpx.Client() as client:
        for i in range(100):
            r = client.get("http://localhost:8000/api/v1/lottery/3d")
            assert r.status_code == 200
    elapsed = time.time() - start
    print(f"100次请求耗时: {elapsed:.2f}s, QPS: {100/elapsed:.1f}")
```

### 优化方向
1. 数据库加索引
2. 热点数据加缓存
3. 慢查询优化
4. 批量接口替代循环调用

## 参考资料

