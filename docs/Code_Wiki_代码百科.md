# 金水谣万物引擎 · Code Wiki（代码百科）

> 本文档为「金水谣万物引擎」项目的结构化代码百科，覆盖整体架构、模块职责、关键类与函数、依赖关系、运行方式与测试体系。
> 生成日期：2026-09-24 · 基于仓库 `Jinshuiyao_Fixed/` 实际代码梳理。

---

## 一、项目概述

**金水谣万物引擎**是一个多领域预测分析平台，覆盖 **彩票、股票、基金、足球、音乐、视频创作** 6 大业务域，集成多种预测引擎、AI 智能分析、双知识库与跨设备同步能力。

- **核心定位**：以「预测 + 知识闭环 + AI 辅助」为核心的个人研究工具平台
- **运行形态**：本地 HTTP 服务（端口 18888）+ Web 前端 + Tkinter GUI，Windows 为主平台
- **AI 模式**：在线（DeepSeek / 硅基流动等 API）与离线（纯本地算法）双模式
- **知识体系**：MiroFishDB 知识卡片 + 用户知识库 + 知识图谱 + 向量索引 + 经验收集箱
- **同步机制**：基于坚果云共享文件夹的跨设备任务/状态同步

---

## 二、技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.8+（推荐 3.10+，实际 venv 为 3.14） |
| Web 服务器 | 标准库 `http.server.ThreadingHTTPServer` |
| 前端 | 原生 HTML/CSS/JS + ECharts 图表 |
| GUI | Tkinter / CustomTkinter |
| 数据获取 | akshare（股票/基金）、requests（彩票/足球） |
| AI | DeepSeek API、硅基流动（免费模型优先）、本地算法回退 |
| 数值/统计 | numpy、pandas、scipy、scikit-learn、matplotlib |
| 测试 | pytest（约 900 项测试） |
| 同步 | 坚果云共享文件夹 |
| 部署 | 本地 venv 自愈 + 一键 bat 启动 |

---

## 三、整体架构

> 架构图源文件：[architecture_overview.mermaid](architecture_overview.mermaid)（可在支持 Mermaid 的编辑器/浏览器中渲染）。

```
                        ┌──────────────────────────────────┐
                        │        launch_jinshuiyao.py      │
                        │  （bat 入口 → 自愈 venv → 预检）  │
                        └──────────────┬───────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────┐
                        │         server/__init__.py       │
                        │   main()  绑定 18888 端口         │
                        │   + 后台启动线程（自检/审查/调度） │
                        └──────────────┬───────────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
        ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
        │  server/router  │  │  server/config  │  │ server/handlers │
        │  GuideHandler   │  │  端口/路径/超时  │  │ 21 个功能处理器  │
        └────────┬────────┘  └─────────────────┘  └────────┬────────┘
                 │                                          │
                 ▼                                          ▼
        ┌──────────────────────────────────────────────────────────┐
        │                         core/                            │
        │  ai_agent · ai_service · knowledge_gateway · scheduler    │
        │  model_router · adaptive_models · security · dispatch_*   │
        │  pipeline_state · agent_orchestrator · registry · tk_style│
        └────────┬──────────────────────────────┬──────────────────┘
                 │                              │
                 ▼                              ▼
        ┌─────────────────┐          ┌─────────────────┐
        │   engines/      │          │    domains/     │
        │ 14+ 预测引擎    │          │  6 大业务域     │
        │ trend/morph/    │          │ lottery/fund/   │
        │ killer/hurst/   │          │ stock/football/ │
        │ dimension_      │          │ creator/music   │
        │ consensus/...   │          └─────────────────┘
        └────────┬────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────────────────────┐
        │  jinshuiyao/(足球泊松) · knowledge/(双库) · controllers/   │
        │  fetchers/ · filters/ · importers/ · backtesting/ · utils/│
        └──────────────────────────────────────────────────────────┘
```

**分层说明**：

1. **入口层**：`launch_jinshuiyao.py` → `server.main()`
2. **服务层**：`server/` 包（HTTP 路由 + 处理器）
3. **核心层**：`core/`（AI 服务、知识网关、调度、安全、分发）
4. **引擎层**：`engines/`（预测算法引擎群）
5. **业务域层**：`domains/`（6 大业务域实现 DomainBase 接口）
6. **基础设施层**：`knowledge/`、`jinshuiyao/`、`controllers/`、`utils/`、`fetchers/`、`filters/`

---

## 四、目录结构详解

```
Jinshuiyao_Fixed/
├── launch_jinshuiyao.py     # 启动器（bat 调用，自愈 venv + 预检 + 调 server.main）
├── config.py                # 全局配置：彩种规则、引擎名、路径常量、降级彩种
├── jinshuiyao_router.py     # 任务路由器：免费(抓取/知识库/本地) vs 付费(DeepSeek) 分流
├── startup_selfcheck.py     # 启动自检
├── auto_audit.py            # 自动模型审查
├── operation_log.py         # 操作日志
├── audio_toolkit.py         # 音频工具集
│
├── server/                  # ★ Web 服务器包
│   ├── __init__.py          #   服务器入口 main()，后台启动线程
│   ├── config.py            #   端口(18888)、路径、超时、线程池
│   ├── router.py            #   GuideHandler（GET/POST 路由调度 + 限流 + 异常保护）
│   ├── rate_limiter.py      #   全局限流器
│   ├── utils.py             #   日志、IP 检测、外部调用熔断
│   └── handlers/            #   21 个功能处理器
│       ├── health.py        #     /health /status /api/ip
│       ├── ai.py            #     AI 对话 / 智能代码助手
│       ├── knowledge.py     #     知识库检索
│       ├── prediction.py    #     预测生成
│       ├── lottery.py       #     彩票 API
│       ├── fund.py          #     基金 API
│       ├── stock.py         #     股票 API
│       ├── football.py      #     足球 API
│       ├── filter.py        #     过滤面板
│       ├── trend.py         #     趋势图
│       ├── backtest.py      #     回测
│       ├── quant.py         #     量化
│       ├── keys.py          #     密钥管理
│       ├── chainmap.py      #     链路地图
│       ├── pipeline.py      #     Agent 流水线状态
│       ├── scheduler.py     #     调度器状态
│       ├── sync.py          #     同步状态
│       ├── review.py        #     审查结果
│       ├── static.py        #     页面路由表（/lottery /fund /stock /football 等）
│       └── error_report.py  #     前端错误上报
│
├── core/                    # ★ 核心内核（拆为 3 子包，共 59 个 .py）
│   ├── ai/                  #   AI 与 Agent（22 模块）
│   │   ├── ai_agent.py      #     JinshuiyaoAgent：AI 助手主入口
│   │   ├── ai_service.py    #     AIService 单例 + AI 模式管理
│   │   ├── model_router.py  #     模型路由
│   │   ├── adaptive_models.py #   平台模型智能匹配
│   │   ├── agent_*.py       #     agent_orchestrator/vector_memory/formatters 等
│   │   ├── llm_budget.py    #     LLM 预算管理
│   │   ├── free_model_pool.py #   免费模型池
│   │   └── ...              #     intent_rules/content_refiner/cross_domain 等
│   ├── dispatch/            #   域分发（9 模块）
│   │   └── dispatch_*.py    #     lottery/fund/stock/football/music/creator/video/knowledge/system
│   └── infra/               #   基础设施（28 模块）
│       ├── security.py      #     SSRF 校验单一真源
│       ├── scheduler.py     #     后台调度器
│       ├── knowledge_gateway.py # 知识网关四源召回
│       ├── pipeline_state.py #    Agent 流水线状态
│       ├── gui_registry.py  #     GUI 组件注册表
│       ├── tk_style.py      #     ModernTheme 七色主题
│       └── ...              #     circuit_breaker/audit_log/telemetry 等
│
├── engines/                 # ★ 预测引擎群
│   ├── __init__.py          #   引擎注册表（get_engine / list_engines）
│   ├── trend_generator.py   #   趋势惯性引擎
│   ├── morph.py             #   形态引擎
│   ├── killer.py            #   杀号校验引擎
│   ├── miss_analyzer.py     #   遗漏分析引擎
│   ├── correlation.py       #   关联矩阵引擎
│   ├── cold_tunnel.py       #   冷号突破引擎
│   ├── hurst.py             #   赫斯特指数引擎
│   ├── dimension_consensus.py # 多维度共识引擎（预测融合）
│   ├── lottery_stats.py     #   彩票统计分析（遗漏表/趋势分类/号码跟随）
│   ├── strategy_cards.py    #   策略知识卡提炼引擎
│   ├── brain_daily.py       #   智能大脑每日简报
│   ├── smart_brain.py       #   智能大脑
│   ├── prediction_service.py#   预测服务（方案生成）
│   ├── risk_controller.py   #   风控控制器
│   ├── health_check.py      #   健康检查
│   ├── watchdog.py          #   看门狗
│   ├── evolution*.py        #   L3 自适应进化引擎（4 个子模块）
│   ├── sync_network.py      #   网络状态检测
│   ├── sync_queue.py        #   离线请求队列
│   ├── sync_manager.py      #   同步管理器
│   ├── feature_engine.py    #   特征工程
│   ├── reposition_engine.py #   重定位引擎
│   ├── position_analyzer.py #   位置分析
│   ├── audit.py             #   审计
│   ├── validators.py        #   校验器
│   ├── format_gen.py        #   格式生成
│   ├── evolve.py            #   进化
│   ├── plugin_manager.py    #   插件管理
│   └── math_selector/       #   数学模型选号
│       ├── __init__.py      #     run_math_model() 统一入口
│       ├── combinatorics.py #     组合数学
│       ├── stats.py         #     统计
│       ├── timeseries.py    #     时间序列
│       ├── montecarlo.py    #     蒙特卡洛
│       └── calibration.py   #     校准
│
├── domains/                 # ★ 业务域（均实现 DomainBase 接口）
│   ├── base.py              #   DomainBase：setup/fetch/analyze/generate/review/status
│   ├── lottery/domain.py    #   LotteryDomain：7 彩种 + 14 引擎
│   ├── fund/domain.py       #   FundDomain：净值/持仓/分析
│   ├── stock/domain.py      #   StockDomain：技术指标+趋势+选股
│   ├── football/domain.py   #   FootballDomain：泊松+赔率+比分路径
│   ├── creator/domain.py    #   CreatorDomain：文案/TTS/OCR/去水印
│   └── music/domain.py      #   MusicDomain：音频分析/转换/生成
│
├── jinshuiyao/              # ★ 足球预测子系统（泊松模型）
│   ├── models/              #   base_model.py / poisson_model.py
│   ├── decision_engine.py   #   JinshuiyaoDecisionEngine（EV/Kelly/推荐）
│   ├── backtester.py        #   JinshuiyaoBacktester
│   ├── feature_engine.py    #   特征工程
│   ├── calibrator.py        #   概率校准
│   ├── risk_controller.py   #   风控
│   ├── data_provider.py     #   数据提供
│   ├── team_db.py           #   球队数据库
│   ├── odds_utils.py        #   赔率工具
│   ├── score_path.py        #   比分路径
│   ├── llm_analyzer.py      #   LLM 赛事分析
│   └── ...                  #
│
├── knowledge/               # ★ 双知识库
│   ├── mirofish_db.py       #   MiroFishDB 知识卡片管理
│   ├── knowledge_graph.py   #   知识图谱（实体+共现关系）
│   ├── knowledge_search.py  #   统一检索入口（AI决策/GraphRAG/向量）
│   ├── vector_index.py      #   向量索引
│   ├── triple_store.py      #   三元组存储
│   ├── cross_linker.py      #   交叉链接
│   ├── tag_validator.py     #   标签校验
│   └── 用户知识库/           #   用户知识卡片（Karpathy 三层模型）
│
├── controllers/             # 业务控制器
│   ├── budget_controller.py #   BudgetControllerV2 预算分配
│   └── scheme_manager.py    #   SchemeManager 方案缓存与命中统计
│
├── fetchers/                # 数据获取层
│   ├── data_fetcher.py      #   通用数据抓取
│   └── fetcher.py           #   基础抓取器
│
├── filters/                 # 数据过滤器
│   ├── smart_filter.py      #   智能过滤
│   └── period_normalizer.py #   周期归一化
│
├── importers/               # 数据导入
│   ├── lottery_data_importer.py
│   ├── super_parser.py
│   └── web_scraper.py
│
├── gui/                     # Tkinter GUI
│   ├── main_window.py       #   主窗口
│   ├── data_store.py        #   数据存储
│   ├── play_plans.py        #   投注方案
│   └── ticket_utils.py      #   票据工具
│
├── smart-coder/             # 智能代码助手
│   ├── qa_engine.py         #   问答引擎
│   ├── code_retriever.py    #   代码检索
│   ├── project_loader.py    #   项目加载
│   ├── recommender.py       #   推荐
│   └── extension_registry.py #  扩展注册表
│
├── backtesting/             # 回测引擎
│   ├── engine.py            #   回测引擎
│   └── metrics.py           #   回测指标
│
├── utils/                   # 工具库
│   ├── safe_json.py         #   安全 JSON 读写（原子写+备份恢复）
│   ├── number_utils.py      #   号码工具
│   ├── security_tools.py    #   安全工具
│   ├── locks.py             #   锁
│   ├── shared_write.py      #   共享写入
│   ├── cache_manager.py     #   缓存管理
│   ├── data_backup.py       #   数据备份
│   ├── uncertainty.py       #   不确定性量化
│   ├── prediction_verifier.py # 预测验证
│   ├── ticket_validator.py  #   票据校验
│   ├── notifier.py          #   通知（微信推送）
│   └── ...                  #
│
├── frontend/                # Web 前端页面
│   ├── lottery/             #   彩票 Hub + 16 个子页面
│   ├── fund/                #   基金 Hub + 8 个子页面
│   ├── stock/               #   股票 Hub + 5 个子页面
│   ├── football/            #   足球 Hub + 4 个子页面
│   ├── dashboard/           #   总仪表盘
│   ├── trend/               #   趋势图表
│   ├── quant-dashboard/     #   量化仪表板
│   └── gap-analysis/        #   差距分析
│
├── jinshuiyao-guide/        # Web 导航页面（控制中心等）
├── config/                  # JSON 配置
│   ├── ai_mode.json         #   AI 模式(online/offline)
│   ├── model_router.json    #   模型路由
│   ├── llm_budget.json      #   LLM 预算
│   ├── scheduler.json       #   调度器配置
│   ├── themes.json          #   主题
│   ├── paths.json           #   路径
│   ├── page_registry.json   #   页面注册表
│   └── logging_config.py    #   日志配置
│
├── tests/                   # 测试套件（~50 文件，约 900 用例）
│   ├── unit/                #   单元测试（40+ 文件）
│   ├── integration/         #   集成测试
│   └── isolation/           #   子系统隔离测试
│
├── tools/                   # 运维/开发工具（~50 个脚本）
│   ├── ops.py               #   开工/收工操作
│   ├── gate.py              #   收工门禁检查
│   ├── compliance.py        #   合规督察
│   ├── check_consistency.py #   系统一致性检测
│   ├── run_review.py        #   审查 Pipeline（ruff+AST+smoke+metrics）
│   ├── ai_review_agent.py   #   AI 语义审查
│   ├── auto_backup.py       #   自动备份
│   ├── run_tests.py         #   测试运行
│   ├── knowledge_mcp.py     #   知识 MCP 服务
│   ├── gen_knowledge_index.py # 知识网关索引生成
│   └── ...                  #
│
└── docs/                    # 文档（架构设计、PRD、技术参考）
```

---

## 五、关键类与函数说明

### 5.1 入口与服务器

| 类/函数 | 位置 | 职责 |
|---------|------|------|
| `main()` | `launch_jinshuiyao.py` | 启动器入口：安装日志双写 → `ensure_runtime()` 自愈 venv → `preflight_check()` 预检 → 清理 pyc 缓存 → `server.main()` |
| `ensure_runtime()` | `launch_jinshuiyao.py` | 换电脑自愈：检测 `requests` 哨兵，缺失则在 `%LOCALAPPDATA%\Jinshuiyao\venv` 建 venv 并 pip install |
| `preflight_check()` | `launch_jinshuiyao.py` | 启动前哨：关键文件语法快检、端口占用检测与自动清理、server 包存在性检查 |
| `main(port=None)` | `server/__init__.py` | 服务器主入口：日志配置 → 端口绑定(18888 起顺延 6 个) → 安全绑定校验 → 启动后台线程 → `serve_forever` |
| `GuideHandler` | `server/router.py` | HTTP 请求处理器：限流 → 顶层异常保护 → 分发到各 handler 模块 |
| `_background_startup_tasks()` | `server/__init__.py` | 后台启动任务：审查 Pipeline、AI 语义审查、启动自检、一致性检测、模型审查、AI 模式检测 |

### 5.2 核心层 core/

| 类/函数 | 位置 | 职责 |
|---------|------|------|
| `JinshuiyaoAgent` | `core/ai/ai_agent.py` | AI 助手主类，统一对话入口；惰性加载各子系统(知识库/视频/向量记忆等) |
| `AIService` | `core/ai/ai_service.py` | AI 服务单例；统一 LLM 调用入口；`get_ai_service()` 获取实例 |
| `auto_detect_mode()` | `core/ai/ai_service.py` | 自动检测 AI 模式(在线/离线)：网络+API Key 探测 |
| `get_mode()` / `set_mode()` | `core/ai/ai_service.py` | 读写 AI 运行模式（`config/ai_mode.json`） |
| `search()` / `summarize()` | `core/infra/knowledge_gateway.py` | 知识网关四源召回：BM25 卡片 + 图谱三元组 + 向量 + 经验条目 |
| `start_background_scheduler()` | `core/infra/scheduler.py` | 启动后台调度器：经验收集箱监听 + 定时同步 + 知识维护 |
| `TaskScheduler` | `core/infra/scheduler_tasks.py` | 通用定时任务容器 |
| `is_safe_http_url()` | `core/infra/security.py` | SSRF 校验单一真源（供 router/video_extractor 委托） |
| `find_working_model()` | `core/ai/adaptive_models.py` | 平台模型智能匹配：额度耗尽探测自动切换，持久化到 secrets |
| `AgentOrchestrator` | `core/ai/agent_orchestrator.py` | Agent 编排调度（惰性接线） |

### 5.3 引擎层 engines/

| 类/函数 | 位置 | 职责 |
|---------|------|------|
| `get_engine(code)` / `list_engines()` | `engines/__init__.py` | 引擎注册表：按代码加载引擎类 / 列出全部引擎 |
| `PredictionService` | `engines/prediction_service.py` | 预测服务：多引擎融合 → 方案生成 |
| `DimensionConsensus` | `engines/dimension_consensus.py` | 多维度共识引擎：多引擎预测结果融合 |
| `run_math_model()` | `engines/math_selector/__init__.py` | 数学模型选号统一入口：组合数学+统计+时间序列+蒙特卡洛+校准 |
| `StrategyCards` | `engines/strategy_cards.py` | 策略知识卡提炼：复盘→7彩种×3类引擎挂钩卡 |
| `run_daily()` | `engines/brain_daily.py` | 智能大脑每日简报入口 |

### 5.4 业务域 domains/

| 类 | 位置 | 职责 |
|----|------|------|
| `DomainBase` | `domains/base.py` | 域标准接口：`setup/fetch/analyze/generate/review/status` + `predict_full()` 完整流程 |
| `LotteryDomain` | `domains/lottery/domain.py` | 彩票域：7 彩种 + 14 引擎注册、抓取、多引擎分析、预测方案生成 |
| `FundDomain` | `domains/fund/domain.py` | 基金域：净值/信息/持仓获取、多维度分析 |
| `StockDomain` | `domains/stock/domain.py` | 股票域：技术指标+趋势分析、选股推荐、买卖信号；`screen()` 多因子选股 |
| `FootballDomain` | `domains/football/domain.py` | 足球域：特征工程+泊松模型+概率校准+比分路径 |
| `CreatorDomain` | `domains/creator/domain.py` | 创作域：AI 文案、语音转文字、TTS、OCR、音频提取、去水印 |
| `MusicDomain` | `domains/music/domain.py` | 音乐域：音频扫描、特征分析、转换/标准化/旋律生成 |

### 5.5 足球子系统 jinshuiyao/

| 类 | 位置 | 职责 |
|----|------|------|
| `PoissonModel` | `jinshuiyao/models/poisson_model.py` | 泊松模型：计算主胜/平/客胜概率 |
| `SimpleEnsemble` | `jinshuiyao/models/poisson_model.py` | 多模型加权集成（当前退化为泊松） |
| `JinshuiyaoDecisionEngine` | `jinshuiyao/decision_engine.py` | 决策引擎：候选项→EV/value gap/Kelly→过滤赔率→分级推荐 |
| `JinshuiyaoBacktester` | `jinshuiyao/backtester.py` | 回测器：批量历史比赛回测 |

### 5.6 知识库 knowledge/

| 类 | 位置 | 职责 |
|----|------|------|
| `MiroFishDB` | `knowledge/mirofish_db.py` | 知识卡片管理：`add_card/search/get_for_engine/update_effectiveness/import_from_text/stats` |
| `KnowledgeGraph` | `knowledge/knowledge_graph.py` | 知识图谱：`build/get_neighbors/get_clusters` |
| `KnowledgeSearch` | `knowledge/knowledge_search.py` | 统一检索：AI 决策检索、GraphRAG 三元组、语义向量 |

### 5.7 控制器 controllers/

| 类 | 位置 | 职责 |
|----|------|------|
| `BudgetControllerV2` | `controllers/budget_controller.py` | 预算分配策略（各彩种注型配置） |
| `SchemeManager` | `controllers/scheme_manager.py` | 方案缓存加载/保存、新增方案、命中统计更新 |

### 5.8 任务路由

| 函数 | 位置 | 职责 |
|------|------|------|
| `classify(task_text)` | `jinshuiyao_router.py` | 任务分类：`data_fetch`(免费抓取) / `knowledge`(免费知识库) / `local`(本地) / `deepseek`(付费AI) / `clarify`(含糊) |

---

## 六、依赖关系

### 6.1 运行时依赖（requirements.txt 核心项）

| 依赖 | 版本 | 用途 |
|------|------|------|
| akshare | 1.18.64 | 股票/基金数据获取 |
| requests | 2.34.2 | HTTP 请求（彩票/足球数据） |
| numpy | 2.5.1 | 数值计算 |
| pandas | 3.0.3 | 数据分析 |
| scipy | 1.18.0 | 科学计算（泊松分布等） |
| scikit-learn | 1.9.0 | 机器学习 |
| matplotlib | 3.11.0 | 绘图 |
| plotly | 6.9.0 | 交互式图表 |
| seaborn | 0.13.2 | 统计可视化 |
| customtkinter | 6.0.0 | 现代 Tkinter GUI |
| beautifulsoup4 | 4.15.0 | HTML 解析 |
| lxml | 6.1.1 | XML/HTML 解析 |
| openpyxl | 3.1.5 | Excel 读写 |
| PyYAML | 6.0.3 | YAML 配置 |
| cryptography | 49.0.0 | 加密（密钥存储） |
| psutil | 7.2.2 | 系统监控 |
| pytest | 9.1.1 | 测试 |
| SQLAlchemy | 2.0.51 | ORM |
| PyMySQL | 1.2.0 | MySQL |

### 6.2 模块间依赖关系

```
launch_jinshuiyao ──→ server ──→ server.handlers.*
                              └──→ core ──→ engines
                                       ├──→ domains ──→ jinshuiyao(足球)
                                       ├──→ knowledge
                                       ├──→ controllers
                                       ├──→ fetchers
                                       ├──→ filters
                                       └──→ utils

server ──→ core.scheduler (后台调度)
       ──→ core.security (SSRF 校验)
       ──→ tools (后台审查/自检)

domains.* ──→ DomainBase (接口)
           ──→ engines.* (预测引擎)
           ──→ fetchers (数据)
           ──→ controllers (预算/方案)

core.dispatch_* ──→ domains.* (域分发)
core.ai_agent ──→ core.ai_service / knowledge_gateway / dispatch_*
core.knowledge_gateway ──→ knowledge.*
```

**关键依赖约束**：
- `server/router.py` 是唯一导入所有 handler 的地方
- `core/infra/security.py::is_safe_http_url` 是 SSRF 校验单一真源，router 和 video_extractor 均委托于此
- `domains/*/domain.py` 均继承 `domains/base.py::DomainBase`
- `core/dispatch/dispatch_*.py` 是 core 到 domains 的薄委托层
- `engines/__init__.py` 是引擎注册唯一入口

---

## 七、运行方式

### 7.1 一键启动（推荐）

双击 `模型/启动金水谣助手.bat`，系统自动：
1. 查找可用 Python 解释器
2. 自愈 venv（首次在 `%LOCALAPPDATA%\Jinshuiyao\venv` 建环境并安装依赖）
3. 启动前哨预检（语法+端口+关键文件）
4. 启动 Web 服务器（端口 18888，被占用则顺延至 18889~18893）
5. 自动打开浏览器访问 `http://localhost:18888/`

### 7.2 命令行启动

```bash
cd Jinshuiyao_Fixed

# 启动导航服务器（无 GUI）
python launch_jinshuiyao.py

# 等价于直接调用 server.main()
python -c "from server import main; main()"
```

### 7.3 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `JINSHUIYAO_PORT` | 服务端口 | 18888 |
| `JINSHUIYAO_BIND_HOST` | 绑定地址 | 127.0.0.1 |
| `JINSHUIYAO_ALLOW_LAN` | 允许局域网访问（需先完成认证+限流+TLS） | 空 |
| `JINSHUIYAO_HEADLESS` | 无头模式（禁用自动开浏览器） | 空 |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥（优先于文件读取） | - |
| `TIANSHU_PRELOAD` | 启动预加载 | 未设置=关闭 |

### 7.4 API 密钥配置

在线模式需要在 `%USERPROFILE%\.jinshuiyao-secrets\` 下放置密钥文件：
- `deepseek_key.txt` — DeepSeek API 密钥
- `siliconflow_key.txt` — 硅基流动密钥（免费模型优先）

### 7.5 访问地址

- 本机：`http://localhost:18888/`
- 控制中心：`http://localhost:18888/control-center`
- 彩票：`/lottery`、`/lottery/dashboard`
- 基金：`/fund`、`/fund/dashboard`
- 股票：`/stock`、`/stock/dashboard`
- 足球：`/football`、`/football/dashboard`
- AI 助手：`/ai-agent`
- 健康检查：`/health`

---

## 八、测试体系

### 8.1 测试目录结构

```
tests/
├── unit/          # 单元测试（40+ 文件）
├── integration/   # 集成测试
└── isolation/     # 子系统隔离测试
```

### 8.2 运行测试

```bash
# 使用项目 venv（必须）
%LOCALAPPDATA%\Jinshuiyao\venv\Scripts\python.exe -m pytest tests/ -q

# 或通过工具脚本
python tools/run_tests.py
```

测试规模约 **900 项**（以实际 pytest 输出为准）。

### 8.3 关键测试覆盖

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_ai_agent.py` | AI 助手 |
| `test_ai_service.py` | AI 服务与模式 |
| `test_knowledge_gateway.py` | 知识网关四源召回 |
| `test_domain_base.py` | 域接口 |
| `test_lottery_stats_engine.py` | 彩票统计引擎 |
| `test_prediction_service.py` | 预测服务 |
| `test_fund_domain.py` / `test_fund_data_manager.py` | 基金域 |
| `test_stock_domain.py` | 股票域 |
| `test_jinshuiyao_core.py` | 足球子系统 |
| `test_security_ssrf.py` / `test_cors_ssrf_hardening.py` | 安全（SSRF/CORS） |
| `test_server_package.py` | 服务器包 |
| `test_sync_manager.py` | 同步管理器 |
| `test_evolution.py` | 进化引擎 |
| `test_smart_brain.py` | 智能大脑 |
| `test_circuit_breaker.py` | 熔断器 |

---

## 九、配置说明

| 配置文件 | 说明 |
|----------|------|
| `config.py`（根） | 全局常量：彩种规则 `LOTTERY_RULES`、引擎名 `ENGINE_NAMES`、降级彩种 `DEGRADED_LOTS`、路径 |
| `config/ai_mode.json` | AI 运行模式（online/offline） |
| `config/model_router.json` | 模型路由配置 |
| `config/llm_budget.json` | LLM 预算与定价 |
| `config/scheduler.json` | 调度器配置 |
| `config/themes.json` | 主题配置 |
| `config/paths.json` | 路径配置 |
| `config/page_registry.json` | 页面注册表 |
| `config/logging_config.py` | 日志配置 |
| `server/config.py` | 服务器常量（端口、路径、超时、线程池） |

---

## 十、开发与运维工具

| 工具 | 用途 |
|------|------|
| `tools/ops.py --start` | 开工令：自动体检 + 显示最近工作 |
| `tools/ops.py --close` | 收工：自动记录 + 今日回放 |
| `tools/gate.py --check` | 收工门禁（全绿=完成） |
| `tools/compliance.py --out` | 合规督察，报告追加到交接中心 |
| `tools/check_consistency.py` | 系统一致性检测（路由/静态资源/git同步/门户链接） |
| `tools/run_review.py` | 审查 Pipeline（ruff + AST + smoke + metrics） |
| `tools/ai_review_agent.py` | AI 语义审查（免费模型优先） |
| `tools/auto_backup.py` | 自动快照备份 |
| `tools/knowledge_mcp.py` | 知识 MCP 服务（stdio JSON-RPC） |
| `tools/gen_knowledge_index.py` | 知识网关索引生成 |
| `tools/run_tests.py` | 测试运行 |

---

## 十一、发现的问题与补充建议（审查结果）

> 以下为本次梳理过程中发现的**文档漂移、不一致或可补充项**，按严重程度排列。

### 🔴 错误（已修正 ✅）

1. **README 入口文件不存在** ✅ 已修正
   - ~~`README.md` 第 59 行写 `python main.py`，但仓库中不存在 `main.py`。~~
   - 已修正为 `python launch_jinshuiyao.py`，并补充启动链路说明。
   - ~~`launch_jinshuiyao.py::preflight_check()` 检查不存在的 `main.py`~~ 已从关键文件检查列表中移除。

2. **README 目录结构存在多处与实际不符** ✅ 已修正
   - 已移除 `sync/`、`scripts/`、`plugins/`、`jinshuiyao-dashboard/` 等不存在目录。
   - 已补全 `frontend/`、`importers/`、`config/`、`tools/` 等实际目录，并标注各目录核心职责。
   - 注：`smart-coder/` 确实存在，已保留。

3. **README Python 版本描述过时** ✅ 已修正
   - 已从"Python 3.8+（推荐 3.10+）"修正为"Python 3.14（独立 venv）"。
   - 已补充"运行测试"章节，明确必须使用 `%LOCALAPPDATA%\Jinshuiyao\venv\Scripts\python.exe`。

### 🟡 调整建议

4. ~~**`core/` 模块数量庞大**~~ ✅ 已完成（W64 / JS-20260924-07）
   - `core/` 下约 59 个 .py 文件已按职责拆为三子包：`core/ai/`（22 模块）、`core/dispatch/`（9 模块）、`core/infra/`（28 模块），`core/__init__.py` 保留 re-export 兼容旧引用。

5. **足球子系统存在双份实现**
   - `domains/football/`（DomainBase 风格）与 `jinshuiyao/`（泊松模型等）存在职责重叠。`FootballDomain` 封装了 `jinshuiyao/` 的模型，但两者边界不够清晰，容易造成维护混淆。

6. **引擎数量与命名**
   - `config.py` 的 `ENGINE_NAMES` 列了 14 个引擎名，`engines/` 下实际有 30+ .py 文件（含 L3 进化、同步、健康检查等非预测引擎）。建议区分"预测引擎"与"系统引擎"，避免引擎注册表概念模糊。

7. **入口冗余检查**
   - `launch_jinshuiyao.py::preflight_check()` 检查 `main.py` 和 `server/router.py`，但 `main.py` 不存在、`server/router.py` 存在。建议更新检查列表为实际关键文件。

### 🟢 可补充项

8. **缺少架构总览图的 mermaid 源文件**
   - `docs/` 下有多个 `.mermaid` 类图/时序图（会话租约、数据三层隔离、风险登记册等），但缺少**整体架构图**的 mermaid 源文件。建议补充。

9. **`requirements.txt` 锁定了大量版本**
   - 依赖版本全锁定（如 `akshare==1.18.64`），换机器安装时可能因版本不可用失败。建议保留 `requirements.txt` 锁定版，同时提供 `requirements-minimal.txt` 宽松版作为备选。

10. **测试运行入口未在 README 明确**
    - README 未说明必须用 `%LOCALAPPDATA%\Jinshuiyao\venv\Scripts\python.exe` 跑测试，`AGENTS.md` 有说明但 README 缺失。建议在 README"快速开始"补充测试命令。

11. **`jinshuiyao_router.py` 与 `core/dispatch/dispatch_*.py` 职责边界**
    - `jinshuiyao_router.py` 做任务分类（免费 vs 付费），`core/dispatch/dispatch_*.py` 做域分发。两者都是"路由"概念，建议在文档中明确区分：前者是**成本路由**（花不花钱），后者是**功能路由**（去哪个域）。

---

## 附录：关键常量速查

| 常量 | 值 | 位置 |
|------|-----|------|
| 服务端口 | 18888（顺延至 18893） | `server/config.py::PORT` |
| 彩种数 | 7（双色球/大乐透/福彩3D/排列三/七乐彩/七星彩/快乐8） | `config.py::LOTTERY_RULES` |
| 预测引擎 | 14 种 | `config.py::ENGINE_NAMES` |
| 降级彩种 | 七星彩/双色球/大乐透（诚实回测无预测力） | `config.py::DEGRADED_LOTS` |
| 单注价格 | 2 元 | `config.py::TICKET_PRICE` |
| 默认最大预算 | 149 元 | `config.py::DEFAULT_MAX_BUDGET` |
| POST body 上限 | 1 MB | `server/config.py::MAX_BODY` |
| 外部线程池 | 4 workers | `server/config.py::_EXTERNAL_EXECUTOR` |
| AI 对话超时 | 60s | `server/config.py::_EXT_TIMEOUT["chat"]` |
| 启动日志 | `%LOCALAPPDATA%\Jinshuiyao\launch.log` | `launch_jinshuiyao.py` |
