---
name: python-data-engineering
description: Python数据工程与部署技能，覆盖Flask后端开发、RAG知识库搭建、数据清洗处理、PyInstaller打包分发、Windows环境部署。使用场景：Web后端开发、本地应用打包、向量库搭建、数据ETL处理、单机软件部署。
---

# Python数据工程与部署技能

## 核心技术栈
- **后端框架**：Flask / FastAPI
- **数据处理**：pandas / numpy
- **向量库**：Chroma / FAISS
- **打包**：PyInstaller / Nuitka
- **部署**：Windows 单机 / 服务器

## Flask 后端开发规范

### 项目结构
```
app/
├── __init__.py      # 工厂函数创建app
├── routes/          # 路由模块
├── models/          # 数据模型
├── services/        # 业务逻辑
├── utils/           # 工具函数
├── static/          # 静态资源
└── templates/       # 模板文件
```

### 最佳实践
- 路由只做参数接收和响应返回
- 业务逻辑放 services 层
- 统一异常处理和响应格式
- 配置文件分离，环境变量读取

## RAG 知识库搭建

### 核心流程
1. 文档加载（PDF/Word/Markdown/HTML）
2. 文本切分（按段落/按token数）
3. 向量化（embedding模型）
4. 存入向量库
5. 检索（相似度匹配）
6. 重排序
7. 生成回答

### 向量库选型
- **Chroma**：轻量、本地、Python友好（推荐）
- **FAISS**：高性能、Facebook出品
- **Milvus**：企业级、分布式

## PyInstaller 打包指南

### 常用参数
```bash
pyinstaller --onefile --windowed --icon=app.ico main.py
```

### 常见坑与解决
1. **缺模块**：--hidden-import=xxx
2. **缺资源文件**：--add-data "xxx;xxx"
3. **路径问题**：用 sys._MEIPASS
4. **体积大**：虚拟环境只装必要包 + UPX压缩

### 打包优化
- 排除不用的库：--exclude-module=xxx
- 不打包为单文件：启动更快
- UPX压缩：体积减少30-50%

## 数据清洗处理

### 常用操作
- 缺失值处理：填充/删除/插值
- 去重：按关键字段去重
- 格式统一：日期、数字、文本规范化
- 异常值处理：3σ原则、箱线图法

### pandas 常用技巧
- 读大文件：chunksize 分块读取
- 加速：用向量化操作，少用for循环
- 内存优化：dtype 指定类型

## Windows 环境部署

### 虚拟环境
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 开机自启
- 注册表方式
- 任务计划程序
- 启动文件夹快捷方式

### 服务化
- NSSM 把程序转成Windows服务
- 自动重启、日志管理

## 参考资料

