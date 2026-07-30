# 金水谣系统变更日志

本文件记录所有对金水谣系统的**手动修改**（新增、修复、优化、删除）。
自动备份等机器行为记录在 `backup_audit.logl`，不在此处。

格式：`[日期] [类型] 文件路径 — 修改说明`

---

## 2026-07-19（续4）安全/稳定加固：P0–P3 全量修复 + 优化审查

**背景**：全项目系统性审查（见 `docs/项目系统审查报告_2026-07-19.html`）发现 15 项问题（双库不连通 / 明文密钥落同步目录 / SSRF / 线程化缺失 / 路径穿越 / 无 body 上限 / 日志放大 / 记忆整行匹配等）。按优先级逐项修复并实测验证。

### 修复清单
- **[P0] 双知识库连通**：`core/video_to_kb.py` 归档时向 MiroFishDB 同步摘要卡（`_sync_to_mirofish`，失败不影响主闭环）。
- **[P1] 明文密钥移出同步目录**：迁至 `~/.jinshuiyao-secrets/`；`core/ai_service.py`、`core/video_extractor.py`、`jinshuiyao/football_gui.py`、`guide_server.py` 四读取器改"新位置优先+旧位置回退"；模型根新增 `.nutstoreignore`。
- **[P1] extract-archive SSRF**：加 `_is_local()` 守卫 + `_is_safe_http_url`（禁内网/环回/云元数据/非 http）。
- **[P2] 线程化+穿越+上限+锁**：`ThreadingHTTPServer`；`open_local_file` commonpath 防穿越；POST 统一 1MB 上限；`MiroFishDB` 与 `predictions.json` 加写锁 + 原子写。
- **[P3] 日志/记忆id/依赖**：`log()` 改 `logging`；记忆增删改用稳定 id；补 `requirements.txt`。
- **优化审查报告**：`docs/优化审查与改进建议_2026-07-19.html`（5 维 11 条建议，按优先级排序 + 预期影响）。

### 验证
19021 单一进程：首页200、/health configured(0错误)、extract-archive 内网拒、路径穿越拒、>1MB 拒、记忆 id 增删回环通过；py_compile ✅ + node --check ✅。

---

## 2026-07-19（续3）功能稳定性加固：根因修复 + 错误监控 + 健康检查

**背景**：用户反馈"功能频繁无法正常打开，且多次反复发生"，要求根因分析 + 监控恢复机制 + 健康检查 + 可扩展方案。

### 根因诊断（5 层）

| 层级 | 问题 | 影响 |
|------|------|------|
| **P0 门户断链** | 门户 6 个 href 指向错误路径（文件搬迁后链接未更新） | 点按钮就 404 |
| **P1 无顶层异常保护** | do_GET/do_POST 外层无 try/except，未捕获异常导致请求崩溃挂起 | 连接卡死 |
| **P2 日志静默** | log_message 写成 pass，所有 HTTP 错误被吞掉 | 出问题无迹可查 |
| **P3 无健康检查** | 没有 /health 端点 | 无法提前发现异常 |
| **P4 无自动恢复** | API 连续失败时无熔断或降级 | 反复撞同一个错 |

### 修复内容

**Phase 1 — P0 断链修复（金水谣助手门户.html）**
- `金水谣助手使用说明.html` → 加 `/` 前缀（绝对路径）
- `/ai-test` → `/workbench#aiTest`（归入工作台 SPA 标签）
- `/route` → `/workbench#dashboard`（归入工作台标签）
- `Jinshuiyao_Fixed/control-center.html` → 补全 `/jinshuiyao-guide/` 路径段
- 系统架构/总体规划 → 统一指向 `/workbench#docs`
- 中文文件名在浏览器中自动 URL 编码可正常访问（curl 原始中文 404 为假阴性）

**Phase 2 — 后端稳定性加固（guide_server.py）**

1. **顶层异常保护**：
   - `do_GET()` → 包装为 try→`_do_GET_impl()`，任何未捕获异常返回 500 JSON（不再挂起）
   - `do_POST()` → 同理包装为 `_do_POST_impl()`
   - 类级别计数器：`_request_count` / `_error_count` / `_errors_recent[]`（最近 20 条）

2. **健康检查端点 `/health`**（GET）：
   - 返回 status/uptime/port/request_count/error_count/error_rate/recent_errors(5条)/ai_mode/knowledge_cards/timestamp
   - AI 状态仅查密钥文件是否存在（不发起网络请求避免卡住）
   - 知识库卡片数实时统计
   - 响应时间 < 50ms（纯本地操作）

3. **日志恢复**：log_message 从 `pass` 改为仅记录异常状态码（4xx/5xx），正常请求静默避免膨胀

**Phase 3 — 前端健康指示器（topnav.js 升级）**
- 新增健康状态灯（绿=正常/黄=降级/红=错误/灰=未知），显示在顶栏品牌名左侧
- 每 30 秒自动轮询 `/health`，状态变化时平滑过渡颜色
- 鼠标悬停显示详情（错误率、最近错误摘要）
- 新增全局 `safeFetch(url, opts)` 工具函数：带自动重试（默认 2 次）、指数退避延迟、超时控制（默认 15 秒）

### 验证
- Python py_compile ✅ | Node --check(topnav) ✅
- 19021 测试端口核心页面 6/6 = 200 | API 接口 4/5 = 200（1 个非回归 404）| 中文文件编码后 3/3 = 200
- `/health` 返回完整状态 JSON（uptime/计数/AI=configured/知识库=10卡/0 错误）
- 旧代码触发 UnboundLocalError 被 500 兜住（不再崩溃），错误记入 recent_errors

### 设计原则（防复发）
- 所有新增后端路由/改动均在 `_do_GET_impl`/`_do_POST_impl` 内层，外层 try/except 永远兜底
- 健康检查只做本地文件 I/O，不发外部网络请求
- safeFetch 重试不依赖任何库（纯 XMLHttpRequest），所有页面引用 topnav 即可用
- 错误计数器是类变量（进程内共享），无需额外存储

---

## 2026-07-19（续2）工作台新增「视频文案提取」页 + 「AI 记忆」面板

**背景**：用户要求（1）把"用模型完整提取视频文案"做成工作台里清晰可用的独立功能；（2）补上对标 ChatGPT Memory 的"AI 记忆/上下文面板"，让 AI 记住的用户偏好可见、可改、可删；（3）抖音养龙虾 skill 视频要提取并经模型学习后归档到知识库。

**后端（guide_server.py）**
- 新增 `GET /api/memory`：读取**项目级**记忆（`.workbuddy/memory/MEMORY.md`）与**用户级**记忆（`~/.workbuddy/MEMORY.md`），解析为 `{scope, text}` 条目数组返回，前端展示 AI 当前记住的内容。
- 新增 `POST /api/video/ingest`：接收 `{url}` → 调 `core.video_to_kb.run()` 跑"提取→提炼→写 raw 证据→生成摘要卡→Lint 体检→重建索引"完整闭环，返回标题/作者/文案/标签/互动数据（解决"模型也学习归档"）。写操作限本机 `_is_local()`。
- 新增 `POST /api/memory`：支持 `add` / `delete` / `edit` 三种 action（scope=project|user），安全写回对应 MEMORY.md（仅本机调用）；`edit` 用 old_text→new_text 整行替换。
- 写操作（视频归档、记忆增删改）均挂 `_is_local()` 护栏，非本机 403；静态页面仍对局域网开放。

**core/video_to_kb.py**
- `run()` 返回值新增 `meta` 字段（title/author/desc/tags/likes/comments/favorites），前端可完整展示提取到的"视频文案"（抖音不提供语音字幕，文案指作者写的标题+描述文本，符合轻抖类工具定义）。

**前端（jinshuiyao-guide/workbench.html）**
- 导航新增「💡 AI 记忆」与「🎬 视频文案提取」两个入口（归入"智能协作/工作管理"分组）。
- 新增视图 `viewMemory`：展示 AI 记住的用户偏好（项目级 + 用户级双栏），支持查看/新增/编辑/删除记忆（即时回写后端）。
- 新增视图 `viewVideo`：粘贴视频链接 → 一键提取文案 → 预览提取结果（标题/作者/文案/标签/数据）→ 一键"归档到知识库"（调 `/api/video/ingest`）。
- 全局搜索 `GS_ENTRIES` 补入两个新功能入口；`switchView` 标题与导航映射同步更新。

**验证**：19021 测试端口全链路通过——
- `GET /api/memory` 正确解析出项目级记忆（AI 记忆面板有内容）；
- `POST /api/video/ingest`（假链接走空路径）正确返回结构、未污染真实库；
- 记忆 add→delete 回环成功、测试条目已干净移除、`MEMORY.md` 复原；
- 页面 grep 确认含「AI 记忆/视频文案提取/ingestVideo/loadMemory」；
- 内联 JS 经 `node --check` 语法校验通过（修复 `editMemory` catch 行括号配对错误一处）。

**真实归档**：抖音极速版养龙虾 skill 视频 `https://v.douyin.com/j6Dm7pQSnyA/`（作者 子栩Skill）已实跑闭环，生成卡片 `knowledge/用户知识库/20260719_视频内容：和同学没事养龙虾玩，做了skill，比较实用。分享给大家，可以找我要s.md` + raw 证据，Lint 通过、索引更新。

---

## 2026-07-19（续）工作台「取长补短」优化 + 两处致命语法修复

**背景**：用户要求对照成熟产品（ChatGPT / DeepSeek / Coze / 飞书 / Notion）取长补短，且"优化只能越来越好、不能倒退"。经 Web 研究提炼 2026 主流范式后，对 workbench.html 做增强（全部为新增，未删任何现有功能）：

**增强项（对照范式）**：
1. 视觉克制化：移除首页 hero 的 radial 光晕球（去"科技展板感"，保留秩序），符合"低干扰、高秩序、可持续阅读"原则。
2. 导航分组：沿用既有 `.nav-section` 骨架，重排为「智能协作 / 工作管理 / 系统与文档」三组（贴合 Coze 核心-资源-支持逻辑）。
3. 生成式摘要卡片（AYDesign 核心范式）：首页 hero 新增 `homeSummary` 动态状态句，基于真实数据（待跟进任务数 / 预测数 / 已复盘 / 知识库卡片数 / AI 在线）生成"当前你…"一句话，由 `updateHomeSummary()` 驱动。
4. Agent 透明度：`addTyping()` 改为「理解→检索→生成」三步指示（带点亮动画），替代原"三个点"黑箱等待，提升信任与"值得等待"感。
5. 全局搜索：顶栏新增 `global-search`，输入时下拉展示「功能入口」+「知识库匹配卡片」（复用全局 `knowledgeCards`），点击直达对应标签页/卡片，由 `runGlobalSearch()` 驱动。
6. 视图自选：知识库 header 新增网格/列表切换（`setKbView()` + `.card-grid.list-mode`），用户可按习惯选密度。

**关键修复（实为防倒退）**：
- 修复 `sampleKnowledge` 数组第 8 项 `{id:8:title:...}` 缺逗号（应为 `{id:8,title:...}`）——该语法错误会导致**整个内联脚本无法执行、所有交互失效**，此前仅验证 HTTP 标记未跑 JS 故未暴露。
- 修复 AI 用例生成函数三元表达式 `(extra?\n补充信息：'+extra:'')` 缺引号（应为 `(extra ? '\n补充信息：' + extra : '')`），同类致命语法错误。
- 验证手段升级：用 `node --check` 对内联脚本做语法校验，确保每一轮改动不破脚本。

**验证**：18950 端口测试服务器全链路通过；node 语法检查 JS SYNTAX OK；8 视图标记齐全；三个数据接口（AI status / prediction list / knowledge stats=90 卡）正常。

---

## 2026-07-19（统一主界面 SPA：全部功能集成到工作台）

**背景**：用户反馈 control-center 总控台的「启动窗口」按钮全部不可用（调用 `subprocess.Popen` 启动桌面 GUI，浏览器环境不适用），且功能散落在 6+ 个 URL 里找不到。

**方案**：将 workbench.html 重写为完整的 SPA 单页应用（Single Page Application），8 个标签页覆盖所有功能：

1. **首页概览**：四步流程实时数据卡 + 快捷入口 + AI 状态灯
2. **AI 对话**：从 ai-agent.html 完整迁移聊天视图（消息列表/输入区/快捷按钮/视频提取/URL检测）
3. **知识库**：完整迁移升级版知识库（统计卡图标+色彩/领域色标签/筛选计数/空状态/弹窗详情）
4. **预测管理**：迁移预测闭环（历史记录/命中标注/复盘报告生成/复制）
5. **系统总控**：control-center 7 张子系统卡片改为 **Web 友好版**——去掉 `openSubsystem('xxx.py','run')` GUI 启动按钮，替换为「AI 预测对话」「历史预测」「打开知识库」等可用的 Web 功能入口；桌面程序标记为「本地程序」灰色提示
6. **任务看板**：嵌入 sync_dashboard 核心视图（任务列表/状态筛选/搜索/优先级标签）
7. **AI 用例**：嵌入 ai-test 核心功能（需求输入→API 调用→格式化输出）
8. **文档中心**：新建统一导航页（架构说明/总体规划/API文档/体检报告/测试报告/SOTA分析/使用教程）

**关键改动文件**：
- `jinshuiyao-guide/workbench.html` — **重写**（185 行 → ~2100 行完整 SPA）
- control-center 的「启动窗口」按钮不再出现在用户操作路径

**验证**：18950 端口测试服务器全链路通过——8 视图切换正常、AI 在线、预测接口 OK、知识库渲染正常。旧版分散页面（ai-agent/control-center/sync_dashboard 等）保留不变，作为独立快捷入口备用。

---

## 2026-07-19（金水谣工作台：统一总入口 + 全局顶栏导航）

依用户「建正式工作台」的选择，把分散的页面收拢成一个真正的总入口，并给所有子页面加统一顶栏，解决「迷路 / 不知道进度」问题。

- **[新增] `jinshuiyao-guide/workbench.html`** — 金水谣工作台（总入口）：一屏展示「①制定计划 → ②运行预测 → ③审查记录 → ④生成报告」四步实时进度（数据来自跨设备任务台账 `/sync-api/state`、预测记录 `/api/prediction/list`、AI 状态 `/api/ai/status`、知识库 `/api/knowledge/stats`），并集中 AI助手 / 看板 / 知识库 / 架构页 / 总规划 等快捷入口；顶部显示 AI 助手在线状态。
- **[新增路由] `guide_server.py` `/workbench`** — 返回工作台页面。
- **[新增] `jinshuiyao-guide/_shared/js/topnav.js`** — 共享统一顶栏：被所有子页面与门户引用。文档页用通栏吸顶，AI助手 / 用例生成这类全屏应用自动改用右上角悬浮胶囊（按网址识别，不破坏布局）；提供「🏠工作台 / ←返回门户 / 💬AI助手 / 📋看板」随时导航。
- **[修改] 12 个页面（门户 + 11 个子页）** — 挂上统一顶栏，移除旧的底部「返回门户」悬浮按钮（去重）；门户行动区新增「🚀 进入金水谣工作台（总入口）」按钮。顶栏脚本引用用完整服务器路径 `/Jinshuiyao_Fixed/jinshuiyao-guide/_shared/js/topnav.js`，使自动审查（按根目录解析）不再误报死链（13 处 → 0）。
- **验证**：18950 端口测试服务器全链路通过——`/workbench` 200、顶栏脚本 200、四状态接口 200、AI 状态 online；auto_audit 0 个 html_dead_link（原 13 处已清零）。旧端口 18888–18893 被历史服务占用，新功能在重启 `.bat` 后于 18888 生效。

---

## 2026-07-19（知识库排版升级 + 全站细节优化）

用户反馈知识库"差点意思"，要求全面审查并优化所有页面细节。

- **[重构] `jinshuiyao-guide/ai-agent.html` 知识库视图** — 全面升级：
  - **统计卡**：从 4 个素白卡片改为带图标 + 左侧彩色渐变条 + 悬停动效（蓝/绿/紫/金四色区分），数字加粗上色，一眼可辨。
  - **搜索栏**：加大圆角(12px)、加粗边框、focus 时蓝色光晕；placeholder 改为「搜索知识卡片（支持标题、摘要、标签）」。
  - **筛选标签**：价值筛选（数据/信息/知识/智慧）选中态改为实心蓝底白字+投影；领域筛选（彩票/股票/足彩/通用）各配独立渐变色激活态。
  - **知识卡片**：最小宽度 280→310px、左侧 3px 领域色条(hover 显示)、标题字号 0.95→1rem/字重 650、摘要行高 1.6→1.7 + 渐变遮罩省略号、标签按领域上色（彩票红/股票蓝/足彩绿/通用紫）、meta 区域名用彩色胶囊。
  - **结果计数**：标题旁新增「共 N 张（已筛选）」实时计数标签。
  - **空状态**：从一行灰字升级为 emoji + 友好提示文案（区分"无匹配结果"和"库为空"两种情况）。
  - **价值 tab 加 emoji 前缀**（📊数据 / ℹ️信息 / 📚知识 / 🧠智慧）；领域 tag 同理。
  - **清理旧 CSS**：删除约 150 行重复/过时的知识库样式代码，统一为一套升级版。
- **[新增] URL 哈希路由** — ai-agent 支持 `#knowledge` / `#predictions` 直接切到对应标签页。
- **[修改] `金水谣助手门户.html`** — 行动按钮从 11 个平铺改为三排分组：①核心入口（工作台/AI/看板）②常用功能（说明/用例/代码/调度）③参考资料（提示词/架构/规划/报告/总控台/备用）。
- **[修改] `_shared/js/topnav.js`** — 通栏顶栏新增「📚 知识库」快捷入口（链接到 `/ai-agent#knowledge`）。
- **[修改] `workbench.html`** — 知识库入口链接更新为 `/ai-agent#knowledge`（点击直达知识库标签页）。
- **[增强] 响应式适配** — 新增统计卡内布局纵向居中(≤900px)、标签栏横滚(≤600px)、标题栏换行等规则。

---

## 2026-07-18（视频提取 → 知识库闭环 + cookie 支撑的登录态提取）

依用户需求：把项目自带的轻抖式视频文案提取（core/video_extractor.py）接入知识库，并支持 cookie 带登录态提取（抖音等需登录平台）。

- **[新增] `core/video_to_kb.py`** — 视频提取→知识库一键闭环：`VideoExtractor` 提取 → `ContentRefiner` 提炼 → 写入 `raw/` 原始证据层 → 生成 schema 合规摘要页卡片（复用 `archive_knowledge.archive`）→ 自动跑 `lint_knowledge.py` 体检 → 重建 `INDEX.json`。与知识库现有存储/检索接口无缝衔接。`--self-test` 在临时目录跑通全链路（不污染真实库）。
- **[修改] `core/video_extractor.py`** — 新增 cookie 支持：`__init__(cookie=)` 与 `extract(cookie=)`；cookie 注入到 session 请求头（带登录态）。cookie 来源顺序：参数 → 环境变量 `TIANSHU_DOUYIN_COOKIE` → 本地文件 `config/douyin_cookie.txt`。**安全边界：绝不自动从浏览器窃取 cookie**（高危操作），仅接受用户手动提供的登录态字符串。
- **[新增] `config/douyin_cookie.txt.example`** — cookie 获取教程与安全提醒示例（真实文件需用户自行粘贴，勿入库/云同步）。
- **验证**：`video_to_kb --self-test` 全过（cookie 注入✓、B站真实提取成功、raw+卡片+Lint+索引 全链路✓）；auto_audit 465 文件 0 错 0 警；真实知识库零污染（3 卡片/2 raw/0 错）。

---

## 2026-07-18（知识库按 Karpathy 三层范式升级：raw 层 / schema 规则 / Lint 体检）

依用户「对比我的知识库 vs Karpathy LLM Wiki」的需求，把知识库从「自动记账机」升级为可长期复利的「知识编译厂」。纯标准库、零外部依赖。

- **清理污染**：删除上一轮「有密钥拦截验证」误写进真实库的 3 张测试卡（正文为 `DEEPSEEK_WAS_CALLED` / 改写残留），重建 `INDEX.json`（根因：验证应在临时库跑，已写进 schema.md「验证纪律」防复发）。
- **新建 `knowledge/用户知识库/raw/`**：原始证据层（事实源头），含 `README.md` 与一份 Karpathy LLM Wiki 证据样本。
- **新建 `knowledge/用户知识库/schema.md`**：配置层规则——卡片分概念页/实体页/摘要页，定义 frontmatter 规范、命名、禁止项、互链/raw 引用、验证纪律。
- **新建 `knowledge/用户知识库/lint_knowledge.py`**：Lint 体检，抓占位符/空正文/缺 frontmatter/断链/孤儿索引/空 raw；含 `--self-test`。
- **升级现有卡**：`共形预测是什么`→概念页；新增 `Karpathy_LLM_Wiki方法论要点`→摘要页（互链 + 引用 raw 证据）。
- **扩展 `archive_knowledge.py`**：`archive()` 支持 `--type` 类型字段；`rebuild_index()` 跳过 `schema.md`。
- **接入 `auto_audit.py`**：新增 `_check_kb()`，全量审查时一并体检知识库，污染卡直接进入审查 error。
- 验证：`auto_audit` 451 文件 0 错 0 警告、知识库 Lint 0/0；`lint_knowledge --self-test`、`archive_knowledge --self-test`、`qa_engine/kb_bridge/deepseek_coder` 自测全过。

---

## 2026-07-18（坐实防烧钱 + 闭环可见：路由器真正接管 DeepSeek 流程）

把「不乱花 DeepSeek」与「自完善闭环看得见」两项核心诉求从「建议/后台」升级为「强制/可见」。纯标准库、零外部依赖、不破坏既有功能。

### 🔒 路由器真正接管 DeepSeek 实际流程（防烧钱坐实）
- 改 `deepseek_coder.py`：新增 `classify_cost(task)`（基于 `jinshuiyao_router.classify`），在 `do_qa` / `do_fix` **入口**就把免费类任务就地拦下：
  - `local`（重命名/列出/统计/格式化）、`data_fetch`（联网抓取）→ 免费本地处理，绝不动用 DeepSeek；
  - `knowledge` 类问题若本地知识库已有答案 → 直接免费返回，不花钱；
  - 「定位 / 查结构」类问题（含定位关键词且无写代码意图）→ 判为免费本地任务。
  - **关键**：即便用户已配置 DeepSeek 密钥，免费类任务也绝不调用付费接口。
- 改 `smart-coder/qa_engine.py`：即便已配密钥，免费类问题仍走「本地免费定位」作答（不调 DeepSeek）。仅真正需深度讲解/改逻辑才走付费。
- `do_fix` 重排顺序：本地纯格式化最先（真实改动免费做）→ 路由器拦截免费任务 → 才进入预算/字数/去重/DeepSeek，确保免费任务不计入额度。

### 👁 知识闭环对用户可见（自完善坐实）
- 改 `kb_bridge.py`：新增 `kb_card_count()`，统计知识库已沉淀卡片数（不含索引/README）。
- `do_qa` / `do_fix` 付费路径返回 `kb_count`；`assistant.html` 结果区显示「✅ 已沉淀到知识库（累计第 N 条）」；DeepSeek 独立页状态同步显示。
- 免费任务不沉淀（避免堆垃圾），但明确提示「本次未花 DeepSeek」——诚实区分。

### 🧹 清理与文档
- 修 `guide_server.py`：`/api/ask` 段 `return` 之后残留的不可达重复代码已删除。
- 新文档 `金水谣系统架构说明.html`：中文闭环图，讲清「门户→路由器→智能助手→DeepSeek(仅付费)→知识库自动调度→扩展接口」，重点标注防烧钱与闭环可见；门户已加入口按钮。

### ✅ 验证
- `kb_bridge`/`deepseek_coder`(`--self-test`)/`qa_engine`/`jinshuiyao_router` 自测全过；`auto_audit` 全量扫描 0 错 0 警。

---

## 2026-07-18（智能代码助手：自动识别加载 / 上下文问答 / 四维推荐 / 知识闭环 / 扩展接口）

面向新手，把「金水谣·DeepSeek 备用代码助手」与「主功能入口」升级为统一的智能代码助手（对应优化需求 1~7）。全部纯标准库、零外部依赖、不破坏既有功能。

### 🆕 自动识别与加载（需求1）
- 新目录 `Jinshuiyao_Fixed/smart-coder/`，含 5 个模块：
  - `project_loader.py`：给一个目录即自动解析结构、生成可视化目录树，识别**入口/配置/核心/模块/文档/测试/数据/资源**并标注**重要性（高/中/低）**与中文用途；不要求手动指定路径。
  - `code_retriever.py`：中文 2-gram + 英文分词，按自然语言问题自动定位最相关文件并抽取命中行片段。
  - `recommender.py`：四维智能推荐——常见预设问题 / 代码风格 / 隐患预警（密钥、硬编码路径、eval 等）/ 性能建议，随加载内容动态生成。
  - `extension_registry.py`：标准化能力注册表（register/list/dispatch），新功能即插即用、无需重构（需求7）。
  - `qa_engine.py`：编排「扫描→定位→检索知识库→（有密钥）DeepSeek 三段式 /（无密钥）本地免费定位」，形成自完善闭环（需求2/5）。

### 🆕 上下文感知问答（需求2）+ 三步交互（需求3）
- 改 `deepseek_coder.py`：新增 `answer_question()` / `do_qa()`，强制**三段式输出（问题定位 / 原因分析 / 修改建议）**，全程大白话、避术语；复用既有**预算上限 / 会话去重 / 本地优先 / 提交确认**防浪费，并沉淀问答到知识库（需求5 闭环）。
- 顺带修复 `deepseek_coder` 自测会误删用户真实配置的安全隐患（改为测试后还原原配置）。
- 改 `kb_bridge.py`：新增 `archive_knowledge_qa()`，把有价值问答沉淀为知识卡（去重、不堆垃圾）。
- 新页面 `jinshuiyao-guide/assistant.html`：**加载项目 → 提问 → 获取解答** 三步；目录树可视化（颜色标重要性）、推荐问题气泡、三段式答案卡片，全程新手引导。

### 🆕 知识库与数据库自动调度（需求5）+ 测试工程（需求6）+ 扩展接口（需求7）
- 问答流程自动检索 `金水谣助手提示词库.html` 与 `knowledge/用户知识库/`，并自动沉淀价值；全部由 `qa_engine` 统一调度。
- 各模块自带 `_self_test()`（项目加载/检索/推荐/注册表/问答/Q&A 共 7+ 项全过）；接 `guide_server` 端点经真实启动端口探测实测通过。
- `extension_registry.REGISTRY` 预留即插即用能力注册，后续新分析器/新后端直接 register 即可被统一调度，无需改动 `guide_server`。

### 🆕 服务端接线（guide_server.py）
- 新增只读接口 `/api/project/scan`、`/api/project/recommend`（对局域网开放）与执行接口 `/api/ask`（POST，**仅本机**调用，因可能消耗 DeepSeek）。
- 新增页面路由 `/smart-coder`。
- 修复一处影响面较广的潜伏 bug：`do_POST` 内多处 `import json` 使 `json` 成为函数局部变量，导致本函数内其他分支 `json.loads` 抛 `UnboundLocalError`；已统一移除，改由模块顶部 `import json` 覆盖。
- 门户 `金水谣助手门户.html` 增加「🤖 智能代码助手」入口与文件地图说明。

### ✅ 实测
- 各模块 `_self_test` 全过；`deepseek_coder --self-test` 含问答共 7 例全过。
- 真实启动服务器：`/api/project/scan`(433 文件/树/推荐)、`/api/project/recommend`、`/api/ask`(POST，无密钥→本地免费定位命中相关文件)、`/smart-coder` 页面均 200；`auto_audit` 全量 443 文件 **0 错误 0 警告**。

---

## 2026-07-18（DeepSeek 助手：智能防浪费 + 知识闭环；全局调度中枢起步）

### 🆕 升级：DeepSeek 代码助手防浪费 + 知识闭环
- 新文件 `AI代码助手(DeepSeek备用)/kb_bridge.py`（纯stdlib）：改代码【前】检索 `金水谣助手提示词库.html` 与 `knowledge/用户知识库/` 卡片，按相关性注入上下文（让 DeepSeek 一次改对、少来回=省钱）；改代码【后】把有价值经验自动沉淀回知识库（`archive_value`），并做去重、无变化不沉淀（不堆垃圾）。
- 改 `deepseek_coder.py`：
  - **预算硬上限**：`daily_api_budget`（默认 50/天），用完即停并明确提示，绝不失控。
  - **会话去重**：同代码+要求本次会话内重复提交，直接返回缓存、不花第二次。
  - **本地优先**：纯格式化（去尾随/统一换行）本地免费做，不调 DeepSeek。
  - **提交前确认 + 字数预估 + 防连点**：点提交弹“约 N 字符，确定？”并禁用按钮防重复点击。
  - **单次字数上限** `per_call_max_chars`（默认 20000），过大内容被拦下。
  - **改前查知识库开关**（网页勾选，默认开）、**今日额度显示**。
  - 重试默认降到 3 次（原 5）。
- **实测**：`--self-test` 覆盖 正常修改/会话去重/本地优先/预算上限/字数上限/网络失败入队，全过；真实启动服务器 `/`、`/api/config`、`/api/usage`、`/api/queue` 均 200；桩测试确认 `handle_fix` 正确返回“已沉淀知识库”且不污染真实知识库；`auto_audit` 全量扫描 error_count=0。

### 🆕 起步：全局智能调度中枢（任务路由器）
- 新文件 `Jinshuiyao_Fixed/jinshuiyao_router.py`（纯stdlib）：`classify(任务)` 判断最省路径 `data_fetch`(免费联网抓数) / `knowledge`(免费查知识库) / `local`(本地琐事) / `deepseek`(才花 AI) / `clarify`(含糊先问)。只做判断、不执行。自测 8 例全对。
- **已接入 guide_server**（块2 落地）：新增只读接口 `/api/route`（GET `?task=` 与 POST JSON 均支持），调用 `jinshuiyao_router.classify()` 并返回 `{path, reason, scores, cost}`；`cost=paid` 才走 DeepSeek（花钱），其余一律 `free`。接口只读、不执行，故对局域网开放（与 `/status` 同级别）。
- **新增「任务调度中枢」页面** `jinshuiyao-guide/route.html`：用户输入任务即可看到会走哪条路、是否花钱（免费绿色 / 付费红色）、原因与各路径命中数；并附五条路径图例。门户 `金水谣助手门户.html` 已加「🧭 任务调度中枢（先看是否花钱）」入口。直接正面回应“AI 助手会不会乱调 DeepSeek 烧钱”的担忧——先在中枢看一眼，免费路径绝不碰 DeepSeek。
- **实测**：`/api/route` 对付费/免费/含糊三类任务 GET+POST 共 5 例均 200 且结论正确；`/route` 页面 200 且含「任务调度中枢」标题；`auto_audit` 全量扫描 error_count=0。`/api/route` 的 POST 分支初版漏接 `do_POST` 已修复（抽成 `_handle_route` 同时服务 GET/POST）。
- 下一步：把“改前先过路由器”接进 DeepSeek 助手实际流程，让免费类任务直接拦下并提示免费路径（待续，用户“按顺序落地”推进中）。

---

## 2026-07-18（guide_server 404 修复 + 自动审查与操作留痕）

### 🔧 修复：门户链接全部 404
- **现象（用户反馈）**：浏览器打开 guide_server 门户后，页面下方展开的链接全部返回 404，功能不可用。
- **根因**：`GuideHandler` 的静态文件根被设为 `HTML_DIR = Jinshuiyao_Fixed/jinshuiyao-guide/`；而门户 `金水谣助手门户.html`（位于模型根目录）的链接（如 `启动金水谣助手.bat`、`Jinshuiyao_Fixed/...`）相对的是**模型根目录**，浏览器请求时服务器去 `jinshuiyao-guide/` 里找 → 全部 404。
- **修复**：新增 `ROOT_DIR = 模型根目录`；静态根改指向 `ROOT_DIR`，并新增 `_serve_static()`——优先 `ROOT_DIR`、回退 `jinshuiyao-guide`，正确 MIME，禁止 `..` 目录穿越；新增 `/api/audit` 接口返回最新审查报告。
- **实测**：启动服务器后，门户(`/`) + 6 个门户链接（`金水谣助手使用说明.html`、`金水谣助手提示词库.html`、`Jinshuiyao_Fixed/启动金水谣助手.bat`、`Jinshuiyao_Fixed/AI代码助手(DeepSeek备用)/启动DeepSeek助手.bat`、`使用说明.html`、`金水谣助手多维分析与验证报告.html`）均返回 200；不存在文件正确返回 404 ✅。

### 🆕 新增：自动模型审查 + 操作留痕（防同类错误复发）
- `Jinshuiyao_Fixed/auto_audit.py`（纯stdlib）：每次启动自动全量扫描模型目录（439 文件），逐一检查 `.bat` 是否带 UTF-8 BOM（正是此前“双击打不开”的同类错误）、`.py` 语法（py_compile）、`.html` 死链；维护 manifest 并与上次 diff，自动记录 新增/修改/删除 到 `operation_log.jsonl`。报告写 `金水谣数据/log/auto_audit_report.json` + 追加 `auto_audit.log`。
- `Jinshuiyao_Fixed/operation_log.py`：统一记录 新增/修改/删除/打开/运行 操作到 `金水谣数据/log/operation_log.jsonl`；已接入 guide_server 的 `/open` 接口。
- **接入启动流程**：`guide_server.main()` 在启动自检后自动调用 `auto_audit.run_audit()`，每次开助手都做一次模型体检并留痕（已实测：真实启动后 `auto_audit.log` 新增一条审查记录）。
- **实测**：`auto_audit.py` 跑通，439 文件 0 错误 0 警告；两次连跑 新增/修改/删除 均为 0（无自噪声）；`operation_log.jsonl` 已累计增删改留痕。
- **🔧 再加固（审计噪声消除）**：运行时动态日志（如 `jinshuiyao-guide/server.log`、`.log/.logl`）每次启动都会变，会污染“修改”diff、掩盖真实代码变更。已在 `_collect_files()` 中排除 `*.log/*.logl`（并据 LOG_DIR 已排除报告/清单自身），并把旧 manifest 中 8 个日志项重新基线化。现审计基线 431 文件，连跑 新增/删除/修改 稳定为 0；我自身对 `auto_audit.py` 的改动会被正确标记一次“修改=1”，复跑即归零——证明真实代码变更可检出、运行时日志不再干扰。
- **顺手修复**：`金水谣助手多维分析与验证报告.html` 中一条指向 `金水谣助手门户.html` 的死链（报告在 Jinshuiyao_Fixed/，门户在模型根目录），改为 `/金水谣助手门户.html`。

---

## 2026-07-18（DeepSeek 备用代码助手）

### 🆕 新增（TRAE/WorkBuddy 不可用时的代码修改备胎）
| 文件 | 说明 |
|------|------|
| `Jinshuiyao_Fixed/AI代码助手(DeepSeek备用)/deepseek_coder.py` | **DeepSeek 代码助手核心** — 纯标准库（无需 pip 安装）；OpenAI 兼容接口；指数退避重试（最多5次，间隔 1→2→4…秒）+ 双端点切换；401/429/5xx/网络异常分级处理；断网自动进「待重试队列」，恢复后一键补跑；网页界面（仅本机 127.0.0.1）+ 命令行两种入口；`--self-test` 离线自测 |
| `Jinshuiyao_Fixed/AI代码助手(DeepSeek备用)/启动DeepSeek助手.bat` | **双击启动器** — UTF-8 **无 BOM** + `chcp 65001` + 全 ASCII 安全探测链（py 优先），`cd /d "%~dp0"` 运行同目录 py，失败 pause（实测中文文件夹下执行正常） |
| `Jinshuiyao_Fixed/AI代码助手(DeepSeek备用)/使用说明.html` | **图文使用说明** — 浅色中文：获取 Key / 双击启动 / 填 Key / 粘贴代码提交 / 复制下载 / 断网排队 / 命令行进阶 / 常见问题 |
| `金水谣助手门户.html` | 文件地图与底部按钮新增 DeepSeek 备用助手入口 |

### 📌 设计要点
- 面向小白：双击即用、全中文网页、无需装包；密钥仅存本机 `config.json`，只发 DeepSeek。
- 网络容错：每个请求自动重试 + 端点切换；全部失败则入队不丢活；提交成功后顺手补跑积压队列。
- 实测：`--self-test` 通过；HTTP 全部接口 200；断网→排队→恢复补跑 全链路验证通过。

### 🔧 修正（2026-07-18 当晚）：.bat 编码 BOM 导致「无法打开」
- **现象**（用户反馈）：双击 `启动DeepSeek助手.bat` 报错 `'锘緻echo' 不是内部或外部命令`，整段 `if exist` / `set` 全部变成乱码命令。
- **根因**：三个 `.bat`（DeepSeek 启动器、模型文件夹主启动器、根目录委托启动器）在上一轮被错误地存成了 **UTF-8 带 BOM**。Windows 的 `cmd.exe` **不会**自动剥离 UTF-8 BOM，开头 3 字节 `EF BB BF` 被当成 GBK 当成 `锘緻` 拼到第一行 `@echo off` 上，使首行变成无效命令，后续 `echo off` 未生效、所有中文行被当作命令回显并失败。
- **正确做法**：`.bat` 必须用 **UTF-8 无 BOM**（或 GBK/ANSI 无 BOM），**绝不可带 BOM**；中文显示靠第 2 行 `chcp 65001 >nul` 切到 UTF-8 代码页（首行 `@echo off` 是纯 ASCII，无 BOM 时解析正常）。
- **修复**：用 Python 以 `utf-8-sig` 读取、以 `utf-8` 写回，剥离三个 bat 的 BOM；保留 `chcp 65001`。
- **验证**：在中文文件夹内放同编码结构测试 bat，实测首行 `@echo off`/`chcp`/`cd /d "%~dp0"` 正常解析，Python 探测命中 `E:\下载\python.exe`(3.14.6) 并成功 `call "%PY%" -c ...` 拉起 Python 写出版本 → 真实启动器逻辑（探测+启动 `deepseek_coder.py`）等价，已可正常工作 ✅。

---

## 2026-07-18（启动器修复与项目清理）

### 🔧 修复
| 文件 | 说明 |
|------|------|
| `Jinshuiyao_Fixed/启动金水谣助手.bat` | **新增主启动器（主要打开方式）** — UTF-8 **无 BOM** + `chcp 65001` 编码；Python 探测优先级：py 启动器 → `where python`(排除 WindowsApps) → AppData Python314/38 → 管理版 3.13；全程避开 bat 内中文字面量路径（实测会导致整行执行异常）；运行同目录 `guide_server.py` |
| `启动金水谣助手.bat`（根目录） | 改为委托启动器，UTF-8 **无 BOM** + `chcp 65001`，调用模型文件夹内主启动器，逻辑单一来源 |

### 🧹 清理
- `Jinshuiyao_Fixed/启动导航.bat`、`run.bat`、`backup_python_environment.bat`（硬编码已不存在的 `D:\python38`）移入 `Jinshuiyao_Fixed/工具与诊断/`
- 一次性诊断脚本（`check_*`、`setup_jinshuiyao_python314`、`startup_selfcheck`、`test_compare_references`、`test_python314_environment`）与 CHANGELOG 历史备份移入 `Jinshuiyao_Fixed/工具与诊断/`
- 根目录旧版乱码日志（`error.txt`/`output.txt`/`stderr.txt`/`stdout.txt`/`!LOG_FILE!`/`%~dp0启动导航.log`）移入 `运行日志与临时文件/`
- 根目录 `启动导航.bat.backup` 移入 `旧版启动脚本/`

### 📌 诊断结论
- 原 bat「无法打开」主因（**修正**）：上一轮误将三个 `.bat` 存为 UTF-8 **带 BOM**，`cmd.exe` 不剥 BOM，开头 3 字节被当成 GBK 乱码 `锘緻` 污染首行 `@echo off`，致整段崩溃（详见上方 DeepSeek 条目下的「修正」小节）。早期判断的「无 BOM 导致失败」不准确——实际是 **BOM 导致**；另外内含 `if exist "E:\下载\python.exe"` 中文字面量路径确实也会导致整行执行异常（已规避：探测链改全 ASCII）。
- 修复：UTF-8 **无 BOM** + `chcp 65001` + 全 ASCII 安全探测链（`py` 优先），已端到端验证可在 18888 起服务并返回门户页。

---

## 2026-07-18

### 🆕 新增

| 文件 | 说明 |
|------|------|
| `engines/killer_fixed.py` | **杀号引擎V2.0** — 完全向后兼容，支持旧式/混合/新式三种calc()调用模式，含calc_advanced()三维度杀号 |
| `utils/api_compat.py` | **API兼容层** — API调用追踪器、智能代理、版本兼容适配器、兼容性报告生成 |
| `utils/simple_security.py` | **简化安全存储** — 零外部依赖的敏感数据保护，纯Python标准库实现 |
| `utils/security_tools.py` | **高级安全工具** — AES-GCM加密系统、密钥管理器、安全扫描器（依赖cryptography） |
| `scripts/validate_phase1.py` | **第一阶段验证套件** — 5项测试：killer兼容性、API兼容层、安全系统、迁移能力、错误日志一致性 |
| `test_python314_environment.py` | **Python 3.14环境验证脚本** — 检测虚拟环境、核心库、金水谣模块导入兼容性 |
| `setup_jinshuiyao_python314.py` | **Python 3.14环境配置工具** — 自动创建虚拟环境、安装依赖、配置项目结构 |
| `utils/cache_manager.py` | **统一缓存层** — L1内存TTL+L2磁盘safe_json持久化，装饰器一行接入，自动过期与命中统计 |
| `utils/pipeline.py` | **数据管道抽象基类** — Pipeline Pattern实现：DataContext/DataPipeline/PipelineStep，步骤编排与失败恢复 |
| `utils/prediction_verifier.py` | **预测验证闭环** — 自动回测校验，命中率计算与评级，结果归档至金水谣数据/verification/ |
| `utils/uncertainty.py` | **共形预测不确定性量化** — 模型无关、纯stdlib：Split/Normalized(交叉拟合)/Adaptive-Online 三种区间 + ConformalClassifier 预测集合 + coverage/MPIW/Winkler 指标（补齐 SOTA 不确定性缺口） |
| `core/drift_detector.py` | **概念漂移检测** — 纯stdlib：PSI / 两样本 KS(含渐近p值) / CUSUM 在线残流检测 / 汇总评级（补齐 SOTA 分布漂移监控缺口，与 data_truth_guard 互补） |
| `tests/unit/test_uncertainty.py` | **共形预测单元测试** — 8 用例（分位/同方差覆盖/异方差覆盖/在线误覆盖/分类集/指标） |
| `tests/unit/test_drift_detector.py` | **漂移检测单元测试** — 7 用例（PSI/KS/CUSUM/汇总评级） |

### 🆕 零基础中文交互环境（面向不懂代码/英文的新手）

| 文件 | 说明 |
|------|------|
| `金水谣助手门户.html`（根目录） | **统一主功能入口** — 全中文、浅色简洁，含三角色（工具使用/AI知识库/数据库）、三步上手、常见问题、文件地图；双击即开 |
| `金水谣助手使用说明.html`（根目录） | **新手图文教程** — 怎么对话、三角色详解、示例需求、闭环成长、诚实说明，全中文无代码 |
| `启动金水谣助手.bat`（根目录） | **一键启动器** — 自动探测本机 Python（系统3.8/管理版3.13/py/PATH），启动服务器并打开浏览器；修复原写死 `D:\python38` 导致无法启动的问题 |
| `Jinshuiyao_Fixed/guide_server.py` | **服务器修复** — Python 探测改为多候选真实路径；根路径 `/` 直接返回中文门户；启动检查指向新启动器 |
| `start_server.py`（根目录） | **次级启动器修复** — Python 路径改为自动探测，不再写死 D 盘 |
| `旧版启动脚本/`、`Jinshuiyao_Fixed/docs/旧版总导航.html`、`Jinshuiyao_Fixed/docs/旧版使用说明.txt`、`运行日志与临时文件/` | **文件整理** — 旧版启动脚本、旧版总导航(93KB)、旧说明、运行日志归入对应子文件夹，根目录仅留入口三件套+大目录 |
| `~/.workbuddy/MEMORY.md` | **助手配置（跨项目）** — 零基础用户画像、纯中文协作规则、三角色、闭环成长、诚实原则 |
| `~/.workbuddy/skills/jinshuiyao-beginner-assistant/SKILL.md` | **可复用技能** — 固化零基础中文协作模式：自然语言理解+逐步讲解+自动归档知识+闭环成长 |

> 说明：根目录尚有 7 个被坚果云同步锁定的临时文件（error.txt 等）移动报「资源忙」，锁释放后可再归入 `运行日志与临时文件/`。

### 🛡️ 多维改进（安全/提示词/知识库，均已实测）

| 文件 | 说明 |
|------|------|
| `Jinshuiyao_Fixed/guide_server.py` | **安全加固** — 新增 `_is_local()`；`/open` 与 `/api/run-tests` 执行类接口仅允许本机(127.0.0.1/::1)调用，非本机返回403；静态页面仍对局域网开放。实测：本机放行、`_is_local` 单元4/4通过(远程IP拦截)、页面正常服务 |
| `金水谣助手提示词库.html`（根目录） | **提示词库** — 依据全网最佳实践(角色+背景+格式+约束+分步)编写，覆盖彩票/股票基金/知识管理/解释通用四类，每条含目标+可复制模板+一键复制；门户新增入口 |
| `Jinshuiyao_Fixed/knowledge/用户知识库/archive_knowledge.py` | **知识归档工具** — 纯stdlib：archive/list_cards/rebuild_index + 命令行 + 自测；把有价值内容写成带时间戳中文卡片并维护索引。实测：自测(临时目录)通过、已归档真实卡片、Python3.8/3.13兼容 |
| `Jinshuiyao_Fixed/knowledge/用户知识库/README.md` | 用户知识库使用说明 |
| `Jinshuiyao_Fixed/金水谣助手多维分析与验证报告.html` | **多维分析与验证报告** — 功能/体验/性能/安全四维评估+本轮已实测改进+后续路线，全中文 |

### 🐍 Python 3.14.6 兼容性与“黑框一闪”修复

用户已将 Python 升级到 3.14.6（台式机与笔记本均安装）。实测结论与修复：

| 文件 | 说明 |
|------|------|
| `Jinshuiyao_Fixed/guide_server.py` | **端口自动顺延** — `main()` 绑定端口由单次 `TCPServer(("", PORT))` 改为尝试 18888→18889→…→18893；某端口被占用（旧实例未关、其它程序占用）时自动改用下一空闲端口，并在控制台提示「端口 X 被占用，尝试下一个…」「已改用 Y」，避免启动即崩溃 |
| `启动金水谣助手.bat` | **检测顺序改为 3.14 优先** — 依次优先：Python314 默认路径 → `py` 启动器(指向3.14.6) → Python38(兜底) → 管理版3.13 → PATH中python(排除 Windows 应用商店占位程序)；**退出即停留**：服务器启动成功后前台常驻，退出或崩溃后均 `pause` 显示原因，不再“一闪而过” |
| `Jinshuiyao_Fixed/guide_server.py` | **3.14.6 兼容性实测通过** — 用 `E:\下载\python.exe`(3.14.6) 与 `py` 启动器启动，自检/AI检测/页面服务(Http 200, 含中文门户)/端口顺延均正常；`py_compile` 在 3.14.6 下通过 |

> 诊断：笔记本“黑框一闪”的根因是**服务器启动即崩溃且原 bat 无 `pause`**——最常见为端口 18888 被上一回没关干净的实例占用（`OSError WinError 10048`），窗口瞬间关闭看不到报错。现端口自动顺延 + 退出停留，问题已消除。Windows 应用商店的“假 python”占位程序也会闪一下跳去商店，bat 已排除该路径。

### 🚀 升级

| 文件 | 说明 |
|------|------|
| `core/ai_service.py` | **AI通信层全面升级** — urllib→requests连接池+自动重试；新增`chat_stream()`流式响应(SSE)；模型fallback链(deepseek→reasoner→ollama)；Ollama本地模型自动检测与自动切换；Token用量追踪(prompt/completion/total)；离线模式下自动使用Ollama |

### 🛠️ 修复

| 文件 | 说明 |
|------|------|
| `engines/killer.py` | **恢复为可用Python模块** — 原文件被文档覆盖，现改为引用 killer_fixed.Killer 的兼容转发层 |
| `utils/api_compat.py` | **补全KNOWN_COMPATIBILITY_ISSUES** — `prediction_service.get_kill_numbers` 条目增加 `solution` 和 `fixed_in` 字段 |
| `utils/security_tools.py` | **兼容cryptography 49.0** — `PBKDF2` 改为 `PBKDF2HMAC`，`hashlib.sha256()` 改为 `hashes.SHA256()` |

### ⚡ 优化

| 文件 | 说明 |
|------|------|
| `venv_314/` | **创建Python 3.14.6虚拟环境** — 已安装全部金水谣依赖包（numpy 2.5.1, pandas 3.0.3, matplotlib 3.11.0, scipy 1.18.0, akshare 1.18.64等） |

### 🎨 恢复

| 文件 | 说明 |
|------|------|
| `gui/main_window.py` | **P6 按钮配色恢复** — 从硬编码十六进制颜色恢复为 `ModernTheme` 类主题变量 `T.COLOR_*` |

### 🧹 清理

| 项目 | 说明 |
|------|------|
| `金水谣数据/log/change_audit.logl` | **P7 审计日志清理** — 删除 806 条 FileWatcher 备份垃圾记录，保留 98 条有效记录 |

### ⚠️ 阶段3 状态说明（待闭环，非全部完成）

| 项 | 说明 |
|----|------|
| `venv_314/` | 实际位于**工作区根目录 `模型/venv_314/`**，并非项目内目录；Python 3.14 环境已就绪，但**尚未接入启动链路**（`main.py` / `启动导航.bat` 仍用系统 Python），属"环境就绪、待切换"状态 |
| 安全/缓存/管道模块 | `utils/simple_security.py`、`utils/security_tools.py`、`utils/prediction_verifier.py`、`utils/api_compat.py`、`utils/cache_manager.py`、`utils/pipeline.py` 已通过 `scripts/validate_phase1.py` 验证，但**尚未接入生产路径**（仅测试引用），当前为预留/未启用状态 |
| 测试基线 | 当前全量测试 **726 个**（与 `PROBLEMS.md` 一致）；历史条目中的 171/195 为早期规模，勿与现状混用 |

### 📊 全网 SOTA 差距分析（本轮背景）

| 项 | 说明 |
|----|------|
| 参照基准 | 2026 年生产级时序/预测系统：Chronos-2、TimesFM 2.5、Moirai 2.0、Time-MoE、Granite TTM、共形预测、MLOps、LLM 智能体预测 |
| 关键结论 | 金水谣工程治理成熟，但建模方法论处「手工启发式+遗传规则进化」阶段，缺预训练基础模型/校准不确定性/漂移检测/集成/特征仓库/AutoML/MLOps |
| 诚实声明 | 彩票为近似随机过程，任何模型无法系统性战胜随机基线；优化聚焦诚实不确定性、漂移监控、可复现 MLOps、确有信号域（股票/赛事）的集成 |
| 本轮补齐 | `utils/uncertainty.py` + `core/drift_detector.py`（均通过单测，预留/验证态，待接入生产路径） |
| 报告 | `金水谣模型对比全网SOTA_差距分析与补充方案.html`（对比矩阵 + P0/P1/P2 路线图） |

---

## 2026-07-17

### 🆕 新增

| 文件 | 说明 |
|------|------|
| `utils/notifier.py` | **Server酱微信推送模块** — 支持基金日报、系统启动、异常告警推送微信。配置 `sendkey.txt` 后自动生效，无 Key 时静默跳过 |
| `sendkey.txt` | **微信推送配置文件** — 填写 Server酱 SendKey 后启用推送，空文件不影响系统运行 |

### 🛠️ 修复

| 文件 | 说明 |
|------|------|
| `guide_server.py` | **P5 GUI窗口被隐藏** — `open_local_file()` 中 GUI 文件不再使用 `CREATE_NO_WINDOW` 标志，普通脚本仍保留 |
| `control-center.html` | **审计日志链接校正** — 真实审计文件名为 `change_audit.logl`，导航链接统一指向 `.logl`（曾误写为 `.log` 导致打不开，本次校正） |
| `utils/notifier.py` | **缺少 import urllib.parse** — `_send_serverchan()` 中 `urllib.parse` 未导入导致 AttributeError |

### ⚡ 优化

| 文件 | 说明 |
|------|------|
| `utils/change_audit.py` | **日志分文件存储** — BACKUP 类型写入独立 `backup_audit.logl`，不再污染 `change_audit.logl`。`query()` 和 `get_recent()` 新增 `include_backups` 参数 |
| `core/file_watcher.py` | **备份日志定向写入** — FileWatcher 的审计记录统一写入 `backup_audit.logl`，与手动操作完全分离 |
| `guide_server.py` | **局域网IP显示 + 启动推送** — 启动时显示本机IP（手机访问地址），增加 `/api/ip` 接口 |
| `control-center.html` | **手机端适配CSS** — 新增 `@media (max-width: 480px)` 断点，手机浏览全屏适配 |
| `PROBLEMS.md` | **完整问题追踪体系** — 新增 P5/P6/P7 记录、8项检查清单、修复历史存档、系统功能清单 |

---

## 2026-07-15

### 🆕 新增

| 文件 | 说明 |
|------|------|
| `scripts/preflight_check.py` | **前置检查脚本** — 9 项启动前自动检查（GUI sys.path、注册表、按钮指向等） |
| `scripts/smoke_test.py` | **冒烟测试脚本** — 10 项实测验证（服务器、GUI、AI服务等） |
| `startup_selfcheck.py` | **启动自检模块** — 每次启动自动跑 24 项生命线检查 |

### 🛠️ 修复

| 文件 | 说明 |
|------|------|
| `启动导航.bat` | **P1 端口冲突 + 编码问题** — 增加端口 18888 自动检测清理逻辑，增加 `chcp 65001` 编码声明 |
| 多个 GUI 文件 | **P2 GUI打不开** — 统一添加 `sys.path.insert(0, _PROJECT_DIR)` 路径设置 |
| `guide_server.py` | **GUI启动支持** — 添加 `PYTHONPATH` 环境变量设置，统一使用 `python.exe`（禁用 `pythonw.exe`） |
| `control-center.html` | **P3 弹确认窗口** — 从 `window.open` 改为 `fetch + showToast` 静默调用 |
| `guide_server.py` | **/open路由返回JSON** — 后端 `/open` 接口改为返回 `{"ok": true/false}` JSON 格式 |

---

## 2026-07-14

### 🛠️修复

| 文件 | 变更说明 | 审计日志引用 |
|------|----------|--------------|
| `core/audit_log.py + 导航.html + 审计日志` | 全面审查修复：多线程安全+死链接+重复日志 — ①audit_log.py: _ensure_path()添加双重检查锁定（DCL），消除多线程竞争条件。②导航: core/domain_base.py死链接修复为domains/base.py，core/文件数统一为5个。③审计日志: 去重处理（74行→71行）。④全套171个测试通过验证。 | [#L141](file:///金水谣数据/log/change_audit.logl#L141) |
| `core/audit_log.py + 导航.html + 审计日志` | 全面审查修复：多线程安全+死链接+重复日志 — ①audit_log.py: _ensure_path()添加双重检查锁定（DCL），消除多线程竞争条件。②导航: core/domain_base.py死链接修复为domains/base.py，core/文件数统一为5个。③审计日志: 去重处理（74行→71行）。④全套171个测试通过验证。 | [#L142](file:///金水谣数据/log/change_audit.logl#L142) |
| `core/audit_log.py + 导航.html + 审计日志` | 全面审查修复：多线程安全+死链接+重复日志 — audit_log.py添加DCL锁消除竞争条件；导航死链接修复为domains/base.py；审计日志去重74->71行；171个测试全部通过。 | [#L143](file:///金水谣数据/log/change_audit.logl#L143) |
| `core/audit_log.py + 导航.html + 审计日志` | 全面审查修复：多线程安全+死链接+重复日志 — audit_log.py添加DCL锁消除竞争条件；导航死链接修复为domains/base.py；审计日志去重74->71行；171个测试全部通过。 | [#L144](file:///金水谣数据/log/change_audit.logl#L144) |
| `run_tests.py + prediction_service.py + domain.py + fetcher.py + guide_server.py + 导航.html` | 修复8个缺口：测试发现+审计集成+导航双版本+项目状态链接 — ①run_tests.py: 修复子目录递归发现+unittest.TestCase支持+新增16个测试文件映射，跑通171个测试。②audit_log: 接入prediction_service(log_predict)、lottery domain(log_review)、stock fetcher(log_fetch)。③guide_server: 指向新版导航文件。④导航: 新增项目状态.md链接。⑤core/circuit_breaker: 新增熔断器文档。⑥core/audit_log: 新增审计日志文档。171个测试全部通过。 | [#L139](file:///金水谣数据/log/change_audit.logl#L139) |
| `run_tests.py + prediction_service.py + domain.py + fetcher.py + guide_server.py + 导航.html` | 修复8个缺口：测试发现+审计集成+导航双版本+项目状态链接 — ①run_tests.py: 修复子目录递归发现+unittest.TestCase支持+新增16个测试文件映射，跑通171个测试。②audit_log: 接入prediction_service(log_predict)、lottery domain(log_review)、stock fetcher(log_fetch)。③guide_server: 指向新版导航文件。④导航: 新增项目状态.md链接。⑤core/circuit_breaker: 新增熔断器文档。⑥core/audit_log: 新增审计日志文档。171个测试全部通过。 | [#L140](file:///金水谣数据/log/change_audit.logl#L140) |
| `jinshuiyao/data/matches.csv + jinshuiyao/data_fetcher.py + jinshuiyao/football_gui.py` | 足彩数据时效性修复+联赛筛选更新 — ①data_fetcher.py: 72场硬编码小组赛替换为当前日期动态赛事(欧冠资格赛+世界杯半决赛)。②matches.csv: 15条过期数据替换为3条当前赛事(match_time补充完整日期)。③odds.csv: 同步更新3组赔率。④football_gui.py: _generate_fallback_matches更新为4场当前赛事+联赛筛选栏更新(新增欧冠资格赛/世界杯半决赛)。195个测试全部通过。 | [#L149](file:///金水谣数据/log/change_audit.logl#L149) |
| `jinshuiyao/data/matches.csv + jinshuiyao/data_fetcher.py + jinshuiyao/football_gui.py` | 足彩数据时效性修复+联赛筛选更新 — ①data_fetcher.py: 72场硬编码小组赛替换为当前日期动态赛事(欧冠资格赛+世界杯半决赛)。②matches.csv: 15条过期数据替换为3条当前赛事(match_time补充完整日期)。③odds.csv: 同步更新3组赔率。④football_gui.py: _generate_fallback_matches更新为4场当前赛事+联赛筛选栏更新(新增欧冠资格赛/世界杯半决赛)。195个测试全部通过。 | [#L150](file:///金水谣数据/log/change_audit.logl#L150) |

### 🆕新增

| 文件 | 变更说明 | 审计日志引用 |
|------|----------|--------------|
| `core/circuit_breaker.py + core/audit_log.py` | 自动闭环：熔断器+审计日志 — 新增CircuitBreaker熔断器模式（连续失败自动熔断+半开探测恢复）和统一审计日志模块。股票akshare已接入熔断器，连续3次失败自动熔断60秒。审计日志支持PREDICT/REVIEW/FETCH/CIRCUIT_BREAKER/SYSTEM五大类事件。23个专用测试+37个回归测试全部通过。 | [#L137](file:///金水谣数据/log/change_audit.logl#L137) |
| `core/circuit_breaker.py + core/audit_log.py` | 自动闭环：熔断器+审计日志 — 新增CircuitBreaker熔断器模式（连续失败自动熔断+半开探测恢复）和统一审计日志模块。股票akshare已接入熔断器，连续3次失败自动熔断60秒。审计日志支持PREDICT/REVIEW/FETCH/CIRCUIT_BREAKER/SYSTEM五大类事件。23个专用测试+37个回归测试全部通过。 | [#L138](file:///金水谣数据/log/change_audit.logl#L138) |
| `core/data_truth_guard.py` | 全局数据真实性守卫模块 — 检测足彩/股票/彩票三大子系统的数据来源标识(CSV时效性+赔率合理性+硬编码检测+akshare可用性+缓存时效性+熔断器状态+彩票文件新鲜度+predictions.json有效性)。5种来源等级(real_api/cache/fallback/hardcoded/unknown)。输出结构化报告+可读文本+审计日志。24个单元测试覆盖全部检测路径。 | [#L145](file:///金水谣数据/log/change_audit.logl#L145) |
| `core/data_truth_guard.py` | 全局数据真实性守卫模块 — 检测足彩/股票/彩票三大子系统的数据来源标识(CSV时效性+赔率合理性+硬编码检测+akshare可用性+缓存时效性+熔断器状态+彩票文件新鲜度+predictions.json有效性)。5种来源等级(real_api/cache/fallback/hardcoded/unknown)。输出结构化报告+可读文本+审计日志。24个单元测试覆盖全部检测路径。 | [#L146](file:///金水谣数据/log/change_audit.logl#L146) |

---

## 2026-07-13

### 🛠️修复

| 文件 | 变更说明 | 审计日志引用 |
|------|----------|--------------|
| `engines/smart_brain.py` | confidence_history KeyError — 加载后自动补全缺失字段 | [#L3](file:///金水谣数据/log/change_audit.logl#L3) |
| `engines/smart_brain.py` | confidence_history KeyError — 加载后自动补全缺失字段 | [#L4](file:///金水谣数据/log/change_audit.logl#L4) |
| `engines/watchdog.py` | _extract_error_signature静默 — 改为logger.debug | [#L19](file:///金水谣数据/log/change_audit.logl#L19) |
| `engines/watchdog.py` | _extract_error_signature静默 — 改为logger.debug | [#L20](file:///金水谣数据/log/change_audit.logl#L20) |
| `engines/watchdog.py` | error_monitor读历史日志 — 只监控当天日志文件 | [#L25](file:///金水谣数据/log/change_audit.logl#L25) |
| `engines/watchdog.py` | error_monitor读历史日志 — 只监控当天日志文件 | [#L26](file:///金水谣数据/log/change_audit.logl#L26) |
| `engines/evolution.py` | check_new_rule锁外读共享数据 — for循环移入with self._lock块内 | [#L1](file:///金水谣数据/log/change_audit.logl#L1) |
| `engines/evolution.py` | check_new_rule锁外读共享数据 — for循环移入with self._lock块内 | [#L2](file:///金水谣数据/log/change_audit.logl#L2) |
| `engines/smart_brain.py` | 降级写入非原子 — tempfile+os.replace原子写入 | [#L5](file:///金水谣数据/log/change_audit.logl#L5) |
| `engines/smart_brain.py` | 降级写入非原子 — tempfile+os.replace原子写入 | [#L6](file:///金水谣数据/log/change_audit.logl#L6) |
| `engines/smart_brain.py` | confidence_history缺actual_hits字段 — append时添加actual_hits:None | [#L7](file:///金水谣数据/log/change_audit.logl#L7) |
| `engines/smart_brain.py` | confidence_history缺actual_hits字段 — append时添加actual_hits:None | [#L8](file:///金水谣数据/log/change_audit.logl#L8) |
| `engines/sync_manager.py` | peek_unlocked方法名错误 — peek_unlocked->_peek_unlocked | [#L9](file:///金水谣数据/log/change_audit.logl#L9) |
| `engines/sync_manager.py` | peek_unlocked方法名错误 — peek_unlocked->_peek_unlocked | [#L10](file:///金水谣数据/log/change_audit.logl#L10) |
| `engines/sync_manager.py` | NetworkDetector._last_latency未初始化 — __init__中初始化为-1.0 | [#L11](file:///金水谣数据/log/change_audit.logl#L11) |
| `engines/sync_manager.py` | NetworkDetector._last_latency未初始化 — __init__中初始化为-1.0 | [#L12](file:///金水谣数据/log/change_audit.logl#L12) |
| `engines/reposition_engine.py` | _get_last_nums永远返回None — 从meta.last_draw提取上期号码 | [#L13](file:///金水谣数据/log/change_audit.logl#L13) |
| `engines/reposition_engine.py` | _get_last_nums永远返回None — 从meta.last_draw提取上期号码 | [#L14](file:///金水谣数据/log/change_audit.logl#L14) |
| `engines/format_gen.py` | _used_reds类变量共享 — 改为实例变量self._my_used_reds | [#L15](file:///金水谣数据/log/change_audit.logl#L15) |
| `engines/format_gen.py` | _used_reds类变量共享 — 改为实例变量self._my_used_reds | [#L16](file:///金水谣数据/log/change_audit.logl#L16) |

### 🆕新增

| 文件 | 变更说明 | 审计日志引用 |
|------|----------|--------------|
| `utils/ticket_validator.py` | 号码验证工具模块 — 从App._validate_ticket迁出validate_ticket和is_valid_period，无GUI依赖 | [#L109](file:///金水谣数据/log/change_audit.logl#L109) |
| `utils/ticket_validator.py` | 号码验证工具模块 — 从App._validate_ticket迁出validate_ticket和is_valid_period，无GUI依赖 | [#L110](file:///金水谣数据/log/change_audit.logl#L110) |
| `engines/prediction_service.py` | 预测服务化模块 — 从App.gen_one核心逻辑提取，无GUI依赖，支持日志回调和独立调用 | [#L111](file:///金水谣数据/log/change_audit.logl#L111) |
| `engines/prediction_service.py` | 预测服务化模块 — 从App.gen_one核心逻辑提取，无GUI依赖，支持日志回调和独立调用 | [#L112](file:///金水谣数据/log/change_audit.logl#L112) |
| `core/context.py` | 新增金水谣内核contextvars子系统上下文隔离模块 | [#L71](file:///金水谣数据/log/change_audit.logl#L71) |
| `core/context.py` | 新增金水谣内核contextvars子系统上下文隔离模块 | [#L72](file:///金水谣数据/log/change_audit.logl#L72) |
| `core/registry.py` | 新增金水谣内核域注册表模块 | [#L73](file:///金水谣数据/log/change_audit.logl#L73) |
| `core/registry.py` | 新增金水谣内核域注册表模块 | [#L74](file:///金水谣数据/log/change_audit.logl#L74) |
| `domains/stock/` | 股票子系统骨架 — StockDomain+StockFetcher+TechnicalEngine+TrendEngine，支持akshare/模拟数据双模式 | [#L93](file:///金水谣数据/log/change_audit.logl#L93) |
| `domains/stock/` | 股票子系统骨架 — StockDomain+StockFetcher+TechnicalEngine+TrendEngine，支持akshare/模拟数据双模式 | [#L94](file:///金水谣数据/log/change_audit.logl#L94) |
| `tests/integration/test_stock_domain.py` | 股票子系统测试 — 16个集成测试覆盖生命周期/fetch/analyze/generate/review/隔离性 | [#L97](file:///金水谣数据/log/change_audit.logl#L97) |
| `tests/integration/test_stock_domain.py` | 股票子系统测试 — 16个集成测试覆盖生命周期/fetch/analyze/generate/review/隔离性 | [#L98](file:///金水谣数据/log/change_audit.logl#L98) |
| `tests/integration/test_backtesting.py` | 回测框架测试 — 15个测试覆盖股票回测/彩票回测/指标计算/A-B对比 | [#L99](file:///金水谣数据/log/change_audit.logl#L99) |
| `tests/integration/test_backtesting.py` | 回测框架测试 — 15个测试覆盖股票回测/彩票回测/指标计算/A-B对比 | [#L100](file:///金水谣数据/log/change_audit.logl#L100) |

---

## 2026-07-18 晚 · B站（非抖音）闭环真实落地验证

**背景**：按用户「先其他（非抖音平台），抖音后续补充」的指令，验证"视频提取 → 知识库沉淀"闭环对**不需要 cookie 的平台（B站/快手/小红书/视频号）**真实可用。

**已验证（真实写入知识库，非临时目录）**：
- 用 B站视频 `BV1otokBpENn`（《2026年B站最全最细的RAG知识库搭建系统教程》）走完整闭环：
  提取(VideoExtractor) → 提炼(ContentRefiner) → 写 raw 证据 → 生成 schema 摘要卡 → Lint 体检 → 重建索引(archive)。
- 结果：卡片 `20260718_视频内容：【大模型RAG】…手把.md` + 证据 `20260718_evidence_…BV1otokBpEN.md` 真实入库；Lint **无错误、无警告**；索引 3 → 5 条；新卡自动互链《Karpathy LLM Wiki 方法论要点》。
- 另落地 `BV1TiWQeCEmh`（Notion+Obsidian 个人成长管理）一张卡，Lint 同样通过。
- 自测 `video_to_kb.py --self-test` 全过（B站真实提取成功，临时目录不污染真实库）。

**修复的 bug**：
- `lint_knowledge.py` raw 引用检查正则 `raw/([^\s)\]]+)` 未排除全角括号 `（）`，导致卡片里 `raw/文件名.md（点击可溯源）` 被误判"证据不存在"。已加入 `（）` 到排除字符类。
- `video_to_kb.py` 写卡片时 raw 链接与"（点击可溯源）"紧贴，已加空格分隔（双保险）。
- `video_to_kb.py` 顶部未把项目根 `Jinshuiyao_Fixed` 加入 sys.path，直接运行脚本时 `content_refiner` 因 `import core` 失败打印无害提示；已加入项目根路径，提示消除（AI 服务无 DeepSeek Key 时为 offline，不烧钱）。

**质量说明**：本次 RAG 视频仅向公开接口暴露标题、无字幕，故规则提炼以标题为主（B站描述即标题复制）；换成有字幕/简介的视频提炼更丰富。此为源数据限制，非工具缺陷。

---

### 晚 · 抖音闭环打通（cookie 自动读取 + 官方详情接口）
- 用户授权在本机读取 QQ 浏览器已登录的抖音 cookie（仅手动授权、绝不自动窃取浏览器），写入 `config/douyin_cookie.txt`（46 条、5381 字符）。读取需浏览器完全退出释放文件锁，用底层共享模式复制 Cookies SQLite + DPAPI 解密（`tools/extract_browser_cookie.py`）。
- 修复 `video_extractor._apply_cookie`：cookie 注入由 `headers['Cookie']` 改为 `session.cookies`（jar）。原因：抖音短链 `v.douyin.com` 经 `iesdouyin.com` 中转 302，headers 方式会把登录态 cookie 带去中转域，触发风控返回「验证码中间页」；jar 方式跨域按域过滤，仅 douyin.com 域发送，成功拿到真实页。
- 关键发现：抖音 PC/移动分享页均为 CSR 空壳，初始 HTML（含 RENDER_DATA）只有配置/AB 数据，**视频文案不在 HTML**，由前端签名 API 异步加载。
- 改用官方详情接口 `https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={vid}`（带登录 cookie 直接返回结构化 JSON，含 desc 文案/作者/统计/标签），新增 `_parse_douyin_vid` 解析短链 video id。
- 真实落地：抖音极速版链接 `https://v.douyin.com/PmABdRMBXEI/`（「左脑知识库」视频，作者 子栩Skill）→ 卡 `20260718_视频内容：首发_左脑知识库…md` + 证据 `20260718_evidence_https_v.douyin.com_PmABdRMBXEI.md`。索引 5 → 6；Lint 无错无警告。
- 全平台闭环已通：B站/快手/小红书/视频号（无需 cookie）+ 抖音（需 cookie）。

---

## 待完成项审查与收尾（2026-07-18 晚）

用户要求通查聊天记录中的"待完整"项一并收尾。逐项审查并处置：

- **根目录遗留临时文件**：确认 7 个旧日志（error.txt/output.txt/stdout.txt/stderr.txt/`!LOG_FILE!`/`~%dp0启动导航.log`/启动导航.bat.backup）已全部清理，无残留。
- **`scripts/check_env.py` 无效转义**：第 6 行 docstring `D:\python38` 触发 `invalid escape sequence '\p'` 警告 → 改为 `D:/python38`，复验 `python -W error::SyntaxWarning` 无警告。
- **`video_to_kb --self-test` 回归修复（真实 bug）**：今日将 cookie 注入从 `headers['Cookie']` 改为更安全的 cookie jar（跨域按域过滤，避免抖音登录态泄露给中转域触发风控）后，自测断言仍停留在旧写法 `assert "Cookie" in session.headers`，导致自测误报失败。已更新断言校验 jar 注入且确认不再用 headers；复验 `video_to_kb --self-test` 全过（cookie jar 注入 ✓ / 全链路 ✓ / 与知识库接口无缝衔接 ✓）。
- **全量 `auto_audit`**：476 文件 错误 0、警告 0，知识库体检 0/0（含今日新增抖音闭环/视频闭环/cookie 提取，确认无回归）。
- **`engines/sync_manager.py` 4 处 TODO**：读源码确认是"远程同步/上报预留接口"（无服务端时 `_record_sync(True,"完成（预留接口）")` 假装成功），依赖本环境未部署的远程服务端，属已知遗留、非本轮收尾范围；不影响本地任何功能，auto_audit 0 错。
- **金水谣数据去重（已完成）**：根 `金水谣数据/`（8 项，3.7M）是过时旧副本，全部被 `Jinshuiyao_Fixed/金水谣数据/`（39 项，更新版）覆盖。已完整备份至 `运行日志与临时文件/金水谣数据_旧副本备份_20260718`，用户确认后删除根目录那份；Jinshuiyao_Fixed 版完好、备份副本完好、auto_audit 476 文件 0 错 0 警无回归。去重完成 ✅。

## 第二十章 · 跨设备任务同步看板（台式/笔记本进度互看）

**需求**：用户用笔记本电脑，台式电脑的任务进度看不到；要求跨设备同步聊天/任务状态、离线缓存、切设备自动加载、清晰同步状态指示。

**诚实前提（关键）**：两台物理机器之间我没有"直连"通道，也连不上台式电脑去查它做了什么。但整个项目放在**坚果云**云盘里——本机写文件会被坚果云自动同步到另一台。因此用「坚果云共享目录里的 `sync/sync_state.json`」作为同步通道，而非假装实时双机直连。同步时延=坚果云同步时延（通常几秒~几十秒）。

**新增**：
- `sync/device_sync.py`（纯标准库）：设备身份识别、任务状态读写、心跳、同步状态检测、离线缓存、冲突提示、本机任务小结。
- `sync/sync_dashboard.html`：中文看板——同步状态指示器（已同步/同步中/离线）、两台设备在线状态、任务总表（另一台设备完成的任务用蓝色左边框高亮）、标记完成表单、设备改名、每5秒自动刷新。
- `guide_server.py` 接入：`GET /sync`（看板页）、`GET /sync-api/state`（状态+总账）、`POST /sync-api/task`（记录任务，限本机）、`POST /sync-api/identity`（改设备名，限本机），沿用 `_is_local()` 安全护栏。
- `金水谣助手门户.html` 新增入口「🔗 跨设备任务同步看板」。
- 已在本机（笔记本电脑）播种 5 条今日已完成任务（TS-001~TS-005），坚果云同步后台式电脑打开看板即可看到。

**验证**：启动总控台实测 `/sync-api/state`（device=笔记本电脑, 5任务, synced=True）、`/sync`（HTML正常）、POST 写入均通过；`auto_audit` 0 错 0 警。

**已知边界**：
- 台式电脑的进度需它**打开一次看板**才会上报（写心跳+任务）；在此之前看板显示「另一台设备尚未上报」。
- 原始「聊天记录」文本不在本项目内，跨设备可见的是**任务进度小结**（这是用户真正关心的"任务完成了吗"）。WorkBuddy 对话本身由账号云端管理，可经会话检索查历史。

## 2026-07-18 晚 · 应用功能修复 + 跨设备看板增强（截图反馈的 10 项需求）

依用户截图反馈（双击 bat 报乱码 `'瀬橧閖汲'不是内部或外部命令`、门户部分功能打不开），整理 10 条需求逐一落地。纯标准库、零外部依赖。

### 🔧 功能异常修复（需求1/2/3）
- **bat 乱码根因彻底解决**：原启动脚本 UTF-8 无 BOM，cmd 按 GBK 读中文→乱码命令。先试加 BOM 失败（BOM 字节被当成命令名），最终改为**纯 ASCII 无 BOM bat + Python 启动器**架构根除编码问题。
  - `启动金水谣助手.bat`（根目录）：纯 ASCII，委托 `Jinshuiyao_Fixed\launch.bat`。
  - 新增 `Jinshuiyao_Fixed/launch.bat`（纯 ASCII 探测链）+ `Jinshuiyao_Fixed/launch_jinshuiyao.py`（Python 启动器，替代 bat 的中文提示与服务器启动，并每日首次启动自动记「助手已就绪」任务）。
- **门户断链修复**：原「启动网页版总控台」指向已改名的 `Jinshuiyao_Fixed/启动金水谣助手.bat` 返回 404 → 改指向 `/control-center.html`（`auto_audit` 误判死链，已改相对路径 `Jinshuiyao_Fixed/jinshuiyao-guide/control-center.html` 实测 200）；去掉不可用的 .bat 下载链接。
- **隐藏功能异常修复**：`/api/selfcheck` 一直报 `No module named 'startup_selfcheck'`（模块根本不存在）→ 新增 `Jinshuiyao_Fixed/startup_selfcheck.py`，检查 7 核心模块导入 + 启动脚本存在 + 同步台账 + 知识库目录，11 项全过，`all_passed:true`。

### 🆕 任务看板增强（需求4/5/6/9）
- **自动记录**：`launch_jinshuiyao.py` 每日首次启动自动记「金水谣助手已启动并就绪」任务（TS-DAILY-YYYYMMDD），无需手动操作即同步状态。
- **任务报告视图**：`sync/sync_dashboard.html` 新增 `renderReport()`，未完成/受阻任务优先置顶，一眼看清哪些没做完。
- **看板内下达指令**：新增 `issueCommand()` 指令框，可在看板直接下发任务并记录。
- **一键功能自检**：新增 `selfCheck()` 按钮，调用 `/api/selfcheck` 反馈各功能正常/异常。

### 🆕 交互体验（需求7/8/9）
- **独立窗口 + 返回入口**：门户所有按钮加 `target="_blank"`（新窗口打开，不丢聊天）；11 个子页面注入 `position:fixed` 浮动「← 返回门户」按钮（看板/调度中枢/助手/AI用例/总控台/架构说明/报告/使用说明/提示词库/DeepSeek说明）。
- **AI 助手直接打开**：门户加「💬 AI助手（直接对话）」「🧪 AI用例生成」入口（`/ai-agent`、`/ai-test`），支持接收任务报告、直接下达指令、自然语言做功能测试并反馈正常/异常。

### ✅ 验证
- 全量 `auto_audit`：477 文件 错误 0、警告 0，知识库体检 0/0。
- 端到端：门户 11 个按钮全部可打开（含 `/sync` 200、两个接口 200）；`/api/selfcheck` 返回 `all_passed:true`。10 条需求全部映射落地并实测。

## 2026-07-18（界面统一浅色 + AI 助手/用例功能做实）

依用户「把画面做好、功能做实，参考成功案例」的指示，参考 ChatGPT / DeepSeek 浅色范式，把整套网页助手界面统一为浅色（与门户/看板一致），并做实 AI 助手与 AI 用例的真实功能。

### 🎨 界面主题统一（浅色，对齐 ChatGPT/DeepSeek 范式）
- 原 AI 助手 / AI 用例 / 总控台 / 接口文档 为深色主题，与浅色门户/看板割裂。现已统一为浅色：浅底 `#f5f7fb`、面板 `#ffffff/#f0f3f9`、圆角、蓝色强调 `#2f6df0`、消息用色块区分（不再用气泡）、150–200ms 过渡动画。
- 覆盖页面：`ai-agent.html`、`ai-test.html`、`control-center.html`、`api-docs.html`、`health-check.html`、`test-report.html`、`jinshuiyao-architecture.html`、`jinshuiyao-global-plan.html`（含 `body::before` 装饰渐变、深色实心渐变块改为浅色）。
- 修复深色残留：`.dept-card.active` 等实心深色渐变改为浅色，避免深色文字在深色块上不可见；架构页品牌色（青/琥珀/靛）适度压深以保证浅底可读性。

### 🔧 功能做实（真实接口，杜绝假数据）
- **AI 助手知识库接入真实数据**：原 `loadKnowledge()` 调不存在的 `/api/knowledge` 路由 → 静默回退 8 张写死假卡。改为调真实 `POST /api/knowledge/list?limit=200`，并加 `normalizeCard()` 字段映射（价值等级 数据/信息/知识/智慧、域、标签）。实测返回真实卡片（如「量化分析仪表盘技术评审提示词」）。
- **AI 对话后端验证正常**：`/api/chat` → `core.ai_agent.JinshuiyaoAgent.chat()`；工具类问题（双色球/股票）返回真实分析，无密钥的自由对话返回诚实的系统介绍，不答非所问。
- **修复聊天接口崩溃 bug（重要）**：`guide_server.py` 各 `do_POST` 的 `body.decode('utf-8')` 在请求体含非 UTF-8 字节时会抛 `UnicodeDecodeError` 且不在 try/except 内 → 整个 handler 崩溃、前端收到「空回复/连接重置」。已改为 `decode('utf-8', errors='replace')`，并对全部 6 处 POST 读取统一加固，避免畸形请求拖垮接口。

### ✅ 验证
- 启动最新 `guide_server.py` 实测：`POST /api/knowledge/list` 返回 `{"ok":true,"cards":[...]}` 真实卡片；`POST /api/chat`（UTF-8）双色球返回真实预测、问候返回系统介绍，均 HTTP 200。
- 全部 guide 页面 `:root` 与深色实心背景已清零，浅色主题一致。

## 2026-07-19（跨设备看板全面体验升级：8 项改进）

**背景**：用户从非技术角度反馈看板操作门槛偏高，提出 4 个改进方向。

### 改动清单

| # | 改进项 | 文件 | 说明 |
|---|--------|------|------|
| 1 | 友好提示条 | `sync/sync_dashboard.html` | 替代技术化断连警告，用自然语言说明当前状态 |
| 2 | 隐藏任务编号 | 同上 | 用户不再看到/填写 TS-xxx，系统自动生成 |
| 3 | 纯中文状态 | 同上 | 状态选项改为 `✅ 已完成 / 🔄 进行中 / 📋 待办 / ⛔ 受阻` |
| 4 | 合并输入入口 | 同上 | 「下达指令」+「详细记录」合并为「新建/更新任务」智能表单 |
| 5 | 进度可视化 | 同上 | 新增环形完成率图 + 四色指标卡片（已完成/进行中/待处理/全部） |
| 6 | 彩色卡片列表 | 同上 | 未完成任务从纯文字改为彩色卡片（红=受阻/橙=进行中/灰=待办） |
| 7 | 搜索与筛选 | 同上 | 新增搜索框 + 筛选标签（全部/未完成/本机/另一台） |
| 8 | 周报导出 | 同上 | 新增「导出周报」按钮 → 页面内生成格式化报告 + 复制到剪贴板 |

### 额外优化
- 新增优先级字段（🔴紧急 / 🟡一般 / 🟢不急），可选填
- 任务卡片增加「编辑」按钮（✎），点击自动回填表单
- 标题框支持回车快捷提交
- 刷新间隔从 5 秒改为 8 秒（减少请求压力）
- 自动滚动到报告区域

### 技术说明
- 所有改动为纯前端（HTML/CSS/JS），不修改后端接口或数据结构
- priority 字段通过现有 `/sync-api/task` 接口透传保存（后端会存入 JSON）
- 新增 `genId()`、`editTask()`、`generateReport()`、`copyReport()`、`setFilter()` 函数

## 文件状态总览

### 当前存在的文件（新增未删除）
| 文件 | 用途 |
|------|------|
| `utils/notifier.py` | Server酱微信推送模块 |
| `sendkey.txt` | 微信推送 SendKey 配置 |
| `PROBLEMS.md` | 问题追踪 + 系统功能清单 |

### 已删除的文件
| 文件 | 删除原因 |
|------|---------|
| (无) | — |

## 2026-07-19（预测闭环：历史预测沉淀 + 复盘报告 + 离线提示改准）

**背景**：用户希望补上「计划→预测→审查→报告」闭环中缺失的一环——预测结果答完即丢、无法回看与复盘；同时修正离线提示文案（密钥已配好，不应再说"没配置"）。

**后端（guide_server.py）**
- 新增预测记录存储：`Jinshuiyao_Fixed/predictions/predictions.json`（字段 id/时间/领域/问题/回答/结果标注），纯标准库。
- 新增接口：`POST /api/prediction/record`（写）、`POST /api/prediction/list`（读，最新在前）、`POST /api/prediction/outcome`（标注 hit/miss/null）。
- `/api/chat` 处理完后，对彩票/股票/足球/音乐/视频类问题**自动写一条预测记录**（try/except 包裹，失败不影响聊天）。

**前端（jinshuiyao-guide/ai-agent.html）**
- 侧边栏新增「历史预测」入口；新增历史预测视图：统计卡（总数/已评/命中/命中率）+ 预测卡片列表（问题·领域·摘要·时间 + 「命中/未中/重置」标注按钮）。
- 新增「生成预测复盘报告」按钮：按领域统计次数、命中率、最近 5 条、智能建议，可一键复制。
- 修正 humanizeReply：后端离线提示现区分「密钥未配置」与「网络断开/接口限流（熔断）」两种真实原因（core/ai_agent.py 第 1582 行返回文案同步区分）。

**验证**：启动最新服务器实测——`/api/chat` 双色球问题自动沉淀记录；`/api/prediction/list` 返回记录；`/api/prediction/outcome` 标注命中后 list 同步。测试数据已清理。

> 每次修改后，请将变更按格式追加到本文件。
> 记录能帮助追溯问题根因，避免反复修复同一问题。
