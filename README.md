# 金水谣万物引擎

> 多领域预测分析平台 · 覆盖彩票、股票、基金、足球、音乐、视频创作 6 大业务域

## 功能概览

金水谣万物引擎是一个集成多种预测引擎、AI 智能分析和数据管理的综合平台，主要能力包括：

- **彩票分析**：支持双色球、大乐透、福彩3D、排列三、七乐彩、七星彩、快乐8 共 7 个彩种，提供 14 种预测引擎（趋势惯性、拐点突变、遗漏极值、冷热轮回、反杀纠错、形态引擎、关联矩阵等）
- **股票分析**：A 股行情获取、技术指标计算、趋势分析、量化仪表板
- **基金监控**：多基金每日净值监控、HTML 报告生成
- **足球预测**：泊松模型、赔率分析、赛事数据仪表板
- **AI 智能助手**：DeepSeek 大模型集成、自然语言交互、知识库闭环
- **知识库管理**：MiroFishDB + 用户知识库（Karpathy 三层模型）、视频转知识卡片
- **跨设备同步**：基于坚果云的跨设备任务同步与状态管理
- **Web 导航**：内置 HTTP 服务器（端口 18888），提供 14 个 HTML 导航页面

## 系统要求

- **Python**：3.14（项目使用 `%LOCALAPPDATA%\Jinshuiyao\venv` 独立 venv，首次启动自动创建）
- **操作系统**：Windows（主要）、macOS/Linux（部分功能受限）
- **内存**：4GB+
- **网络**：在线模式需要网络（调用 DeepSeek API），离线模式无需网络

## 快速开始

### 1. 安装依赖

```bash
cd Jinshuiyao_Fixed
pip install -r requirements.txt
```

### 2. 配置 API 密钥（可选，在线模式需要）

```bash
# 创建密钥目录（不要放在项目同步目录中）
mkdir %USERPROFILE%\.jinshuiyao-secrets

# 将 DeepSeek API 密钥写入文件
echo sk-your-api-key > %USERPROFILE%\.jinshuiyao-secrets\deepseek_key.txt
```

### 3. 启动系统

**方式一：一键启动（推荐）**

双击 `启动金水谣助手.bat`（在 `模型/` 根目录下），系统将自动：
1. 查找可用的 Python 解释器
2. 启动 Web 导航服务器（端口 18888）
3. 打开浏览器访问门户页面

**方式二：命令行启动**

```bash
cd Jinshuiyao_Fixed

# 启动导航服务器（自动自愈 venv + 预检 + 后台调度器）
python launch_jinshuiyao.py

# 等价于直接调用服务器入口
python -c "from server import main; main()"

# 启用预加载（启动时自动获取最新数据）
set TIANSHU_PRELOAD=1 && python launch_jinshuiyao.py
```

> 启动链路：`启动金水谣助手.bat` → `Jinshuiyao_Fixed/launch.bat`（自动查找 Python 3.14）
> → `launch_jinshuiyao.py`（自愈 venv + 预检）→ `server.main()`（绑定 18888 端口）。

### 4. 访问导航

启动后打开浏览器访问：`http://localhost:18888`

### 5. 运行测试

```bash
# 必须使用项目 venv（否则依赖不全）
%LOCALAPPDATA%\Jinshuiyao\venv\Scripts\python.exe -m pytest tests/ -q

# 或通过工具脚本
python tools/run_tests.py
```

测试规模约 900 项（以实际 pytest 输出为准），覆盖单元/集成/子系统隔离。

## 目录结构

```
Jinshuiyao_Fixed/
├── launch_jinshuiyao.py     # 启动器入口（自愈 venv + 预检 + 调 server.main）
├── server/                  # Web 导航服务器包（server/__init__.py::main，端口 18888）
│   ├── router.py            #   GuideHandler 路由调度
│   └── handlers/            #   21 个功能处理器（ai/lottery/fund/stock/football/...）
├── config.py                # 全局配置常量（彩种规则、引擎名、降级彩种）
├── jinshuiyao_router.py     # 任务路由（免费抓取/知识库/本地 vs 付费 DeepSeek 分流）
├── core/                    # 核心内核（~59 个模块：AI服务、调度、知识网关、安全、分发）
├── engines/                 # 预测引擎群（趋势/形态/杀号/赫斯特/多维共识/数学选号等）
├── domains/                 # 业务域实现（均继承 domains/base.py::DomainBase）
│   ├── creator/             #   视频创作（TTS、OCR、水印去除）
│   ├── football/            #   足球预测
│   ├── fund/                #   基金分析
│   ├── lottery/             #   彩票（7 彩种 + 14 引擎）
│   ├── music/               #   音乐生成
│   └── stock/               #   股票分析
├── jinshuiyao/              # 足球子系统（泊松模型、决策引擎、回测器）
├── knowledge/               # 双知识库（MiroFishDB + 知识图谱 + 向量索引）
├── controllers/             # 业务控制器（预算、方案）
├── fetchers/                # 数据获取层
├── filters/                 # 数据过滤器
├── importers/               # 数据导入（彩票数据、网页抓取）
├── gui/                     # Tkinter 主窗口 GUI
├── smart-coder/             # 智能代码助手（问答引擎、代码检索）
├── backtesting/             # 回测引擎
├── utils/                   # 工具库（安全JSON、号码工具、锁、备份等 18 个）
├── frontend/                # Web 前端页面（lottery/fund/stock/football/dashboard/trend/quant）
├── jinshuiyao-guide/        # Web 导航页面（控制中心等）
├── config/                  # JSON 配置（ai_mode、model_router、llm_budget、scheduler）
├── tools/                   # 运维/开发工具（ops、gate、compliance、run_review 等 ~50 个）
├── tests/                   # 测试套件（~50 文件，约 900 用例）
└── docs/                    # 文档（架构设计、PRD、Code Wiki）
```

## 运行模式

系统支持两种 AI 运行模式：

| 模式 | 说明 | 网络需求 |
|------|------|----------|
| **online** | 调用 DeepSeek API 进行智能分析 | 需要网络 + API 密钥 |
| **offline** | 纯本地算法运行，不调用外部 API | 无需网络 |

模式配置文件：`config/ai_mode.json`

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TIANSHU_PRELOAD` | 启用启动预加载 | 未设置=关闭 |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（可选，优先于文件读取） | - |

## 常见问题

**Q: 启动时提示端口被占用怎么办？**
A: 系统会自动尝试 18888–18893 的备用端口。如果全部被占用，可以在 server 包（server/__init__.py）中修改 `DEFAULT_PORT`。

**Q: 离线模式和在线模式如何切换？**
A: 修改 `config/ai_mode.json` 中的 `mode` 字段为 `online` 或 `offline`，重启生效。

**Q: 如何添加新的预测引擎？**
A: 在 `engines/` 目录下创建新引擎文件，实现标准的引擎接口，然后在 `engines/__init__.py` 中注册。

**Q: 知识库数据放在哪里？**
A: 主知识库 `knowledge/mirofish_db.json`，用户知识库 `knowledge/用户知识库/`。运行时数据在 `金水谣数据/` 目录中。

## 技术栈

- **后端**：Python 3.8+、标准库 HTTP 服务器（ThreadingHTTPServer）
- **前端**：原生 HTML/CSS/JS、ECharts
- **GUI**：Tkinter / CustomTkinter
- **AI**：DeepSeek API（在线）、本地算法（离线）
- **数据**：akshare（股票/基金）、requests（彩票数据）
- **同步**：坚果云共享文件夹

## 许可证

本项目为个人学习研究项目，仅供个人使用。
