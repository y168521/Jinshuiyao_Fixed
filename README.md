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

- **Python**：3.8+（推荐 3.10+）
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

# 完整启动（GUI + 导航 + 调度器）
python main.py

# 仅启动导航服务器（无 GUI）
python main.py --no-gui

# 启用预加载（启动时自动获取最新数据）
set TIANSHU_PRELOAD=1 && python main.py
```

### 4. 访问导航

启动后打开浏览器访问：`http://localhost:18888`

## 目录结构

```
Jinshuiyao_Fixed/
├── main.py                  # 主入口（GUI + 服务器 + 调度器）
├── server/                  # Web 导航服务器包（server/__init__.py）（端口 18888）
├── config.py                # 全局配置常量
├── jinshuiyao_router.py     # 任务路由（免费 vs 付费 AI 分流）
├── core/                    # 核心内核（AI服务、调度、知识库等）
├── engines/                 # 预测引擎群（14 种引擎）
├── domains/                 # 业务域实现
│   ├── creator/             #   视频创作（TTS、OCR、水印去除）
│   ├── football/            #   足球预测
│   ├── fund/                #   基金分析
│   ├── lottery/             #   彩票基础
│   ├── music/               #   音乐生成
│   └── stock/               #   股票分析
├── controllers/             # 业务控制器（预算、方案）
├── fetchers/                # 数据获取层
├── filters/                 # 数据过滤器
├── gui/                     # 主窗口 GUI
├── jinshuiyao/              # 足球子系统（泊松模型等）
├── knowledge/               # 双知识库
├── utils/                   # 工具库（安全JSON、缓存等）
├── backtesting/             # 回测引擎
├── sync/                    # 跨设备同步
├── smart-coder/             # 智能代码助手
├── scripts/                 # 工具/运维脚本
├── tests/                   # 测试套件
├── docs/                    # 文档
├── plugins/                 # 插件目录
├── jinshuiyao-guide/        # Web 导航页面
├── jinshuiyao-dashboard/    # 足球预测仪表板
├── jinshuiyao-quant-dashboard/ # 量化分析仪表板
└── jinshuiyao-trend/        # 趋势图表
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
