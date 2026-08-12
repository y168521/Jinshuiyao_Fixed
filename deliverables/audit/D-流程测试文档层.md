# D-流程测试文档层 · 全流程深度审计报告

- 审计对象：`C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed`（仓库根，git 分支 master，工作区干净，最新提交 52bc7d1）
- 审计方式：只读取证（glob/grep/read/git 只读命令/Test-Path/AST 静态分析），未运行任何修改系统状态的命令
- 审计日期：2026-08-12
- 问题编号：D-xxx；严重度：P0（数据损坏/密钥泄漏/直接崩溃）/ P1（机制失效/必失败/假绿）/ P2（漂移/死代码/口径不符）
- 说明：本次审计与 2026-08-12 已有登记（W63补69 / JS-20260812-05 全项目盘点）结论相互印证，本报告补充行号级证据并新增若干漂移点；P0 = 0 条（如实报告，最接近 P0 的"假绿门禁"类问题按 P1 计）

---

## 一、统计摘要

| 严重度 | 数量 | 分布 |
|--------|------|------|
| P0 | 0 | — |
| P1 | 11 | D-101, D-201, D-203, D-301, D-401, D-404, D-501, D-502, D-705, D-801, D-802 |
| P2 | 24 | D-102, D-103, D-104, D-202, D-302, D-402, D-403, D-405, D-503, D-504, D-505, D-506, D-601, D-602, D-701, D-702, D-703, D-704, D-706, D-707, D-803, D-804, D-805, D-806 |
| 合计 | 35 | — |

**Top5 摘要**：
1. D-401 计划任务 `\Jinshuiyao自动同步` 跑的是 `同步代码.bat` 而非 `自动同步.ps1` → 蒸馏/数据守卫/知识索引保鲜/vault 刷新四链已断线约 10 天（.distill_seen 最后写入 2026-08-02 18:08，经验收集箱 08-12 仍在增长）
2. D-201/D-203 审计留痕双轨：AGENTS.md 宣称的"操作留痕系统"（审计轨迹.jsonl + /audit-dashboard）从未落盘一行，看板恒空；真实留痕在 core/audit_log.py（operation_log.jsonl，08-12 10:59 活跃）
3. D-301/D-302 GitHub CI 纯装饰：push 分支写 main（实际 master）、全部命令带不存在的 `Jinshuiyao_Fixed/` 前缀、ruff/semgrep/ast/pytest 全 `|| true` 吞错
4. D-501/D-502 测试框架双死引用：gate.py --e2e 与 POST /api/run-tests 都跑不存在的 `scripts/smoke_test.py`；run_tests.py 的 test_dir=tools/tests 目录不存在 → gate --test 实际跑 0 个测试
5. D-101/D-104 三份 pre-commit 规范源互相矛盾且与实际 hook 都不一致：wrapper.sh 缺 page_api_lint 第3步（install_hooks.py 安装会从 3 步降级为 2 步）；实际 hook 标"1/4..3/4"却无第4步、无任何审计留痕调用

---

## 二、第1项 · tools/ 逐一体检

### D-501 P1 · gate.py --e2e 死引用 scripts/smoke_test.py（含 /api/run-tests）
- 证据：`tools/gate.py:37` `"e2e": (os.path.join(SCRIPTS, "smoke_test.py"), "冒烟测试·端到端(12项)")`；`server/handlers/static.py:566-587` `handle_run_tests` → `:574 subprocess.run([SYSTEM_PYTHON, 'scripts/smoke_test.py'], ...)`；`scripts/smoke_test.py` 不存在（Test-Path=False）
- 影响：`gate.py --e2e` 必报文件不存在；控制台/前端"运行测试"按钮 POST /api/run-tests 必 500。真源是 `tools/smoke_test.py`（v1.0 · 15项，存在）
- 建议：两处路径改 `tools/smoke_test.py`；顺手把 smoke 头注释"13个HTML页面"更新为 56 页口径

### D-502 P1 · run_tests.py 的 test_dir 不存在 → gate --test 实际 0 测试
- 证据：`tools/run_tests.py:829` `test_dir = os.path.join(BASE_DIR, "tools/tests")`（目录不存在）；同一文件 FILE_CATEGORY 含 `test_preload.py`（不存在）；HTML 报告写 `tools/金水谣数据/test_reports/`（错位，真日志在 `金水谣数据/log/`）
- 影响：`gate.py --test` 空跑 0 项却可能报"通过"，全量测试框架（零 pytest 依赖轨道）整体失效，属于假绿门禁
- 建议：test_dir 改 `tests/`；FILE_CATEGORY 删 test_preload 或补文件；报告路径改 `金水谣数据/log/test_reports/`

### D-503 P2 · scripts/quality_gate.py 多处死引用
- 证据：`scripts/quality_gate.py:273` 引 `scripts/smoke_test.py`（缺失）；`:285` 在 PROJECT_DIR 根跑 `run_tests.py`（实际只在 tools/）；`:62-69` PROTECTED_VITAL_DOCS 7 个中 3 个不存在（`模型/金水谣数据/启动AI知识库_搭建手册.html`、`对抗AI惰性_五道防线方案.html`、`自动化Skill经验底座_成败案例库.md`）；`scripts/.quality_baseline.json` 缺失（`.gitignore:73` 有忽略规则）
- 影响：--quality 基线校验要么失败要么跳过，输出字符串"726 个测试/10/10 通过"为旧口径
- 建议：引用改 tools/；vital docs 按现状修正清单；补基线文件或移除基线门禁

### D-504 P2 · doctor.py 关键文件清单含 4 个有意删除的文件 → 每次体检恒定假报错
- 证据：`tools/doctor.py:237` `"main.py", ..., "preload.py"`；`:333` `("main.py", "主程序入口")`；`:341` `sync/device_sync.py`；`:344` `("deepseek_key.txt", "AI密钥")` —— 四者均不存在（deepseek_key.txt 系有意删除、密钥已迁 `~/.jinshuiyao-secrets/`）；主流程退出码恒 0
- 影响：体检报告永远有假红灯却仍"通过"（假绿+假红并存），掩盖真实问题
- 建议：从 check_files 剔除并维护"已知删除"白名单（如 extract_browser_cookie 移出仓库的模式）

### D-505 P2 · 门禁数字漂移："36 项"实为 33 项、"7/7"实为 6 项
- 证据：`金水谣_纲.md:49`、`金水谣_录.md:18` 称 `gate.py --check` 为 36 项；`tools/wrapup_check.py:65-98` 顶层 check 调用共 33 个（v1.7）；`金水谣_录.md:64` 称 `--smoke --quick` 为 7/7；`tools/smoke_test.py:503-510` quick 分支只跑 0-5 号共 6 项
- 建议：文档改"33 项（以 wrapup_check 实际输出为准）"、"quick 6/6"；或在 quick 分支补 1 项对齐

### D-506 P2 · gate.py --audit 的 check_1 必 FAIL（4 个孤儿脚本引用）
- 证据：`tools/cross_doc_audit.py:40-57` check_1_script_references 扫 `模型/AI协作交接中心.md` 的 `(tools|scripts)/*.py` 引用；现存 4 个孤儿：`tools/extract_browser_cookie.py`（W63补62 已移出仓库到 %LOCALAPPDATA%/Jinshuiyao/tools_sensitive/）、`tools/jinshuiyao_python310_validator.py`、`tools/reorg.py`、`tools/smoke_mcp.py`（三者已归档到 tools/archive/，W63补55）
- 影响：--audit 红灯常亮（跨文档一致性 6 项中 check_1 必 FAIL；纲:50 声称的 6 项数量本身正确）
- 建议：交接中心 4 处引用更新为实际位置（归档/移出注明"勿再引用"）；cross_doc_audit 增加"归档目录引用豁免"

### D-806 P2 · static.py 的"页面不存在"回退表是死代码
- 证据：`server/handlers/static.py:116-131` `_PAGE_ERROR_MESSAGES` 12 条"X页面不存在"文案；但 `_PAGE_ROUTES`（:32-53）指向的 20 个 HTML 文件在 jinshuiyao-guide/ 全部存在（逐文件 Test-Path 全 True）→ `:149-150` 回退分支永不触发
- 影响：误导性死代码（文案与事实相反），后续真删页面时反而可能掩盖
- 建议：删除该表或改为从文件系统动态判定

---

## 三、第2项 · git hooks 对账

### D-101 P1 · 规范源与已安装 hook 不一致，且安装会"降级"
- 证据：已安装 `.git/hooks/pre-commit`（2041B，2026-08-12）为 3 步：check_consistency.py → precommit_ai_review.py → page_api_lint.py（标"1/4..3/4"但无第4步）；规范源 `tools/pre-commit-hook-wrapper.sh` 只有前 2 步、**无 page_api_lint**（标 1/4、2/4）；`tools/install_hooks.py:50` 无条件复制 wrapper.sh → 重装后 hook 从 3 步变 2 步，丢掉 page_api_lint 死链拦截（W63补67 刚接入的检查）
- 影响：跨机/重装环境丢失 pre-commit 第3步检查；计数器"x/4"与实际步骤不符
- 建议：wrapper.sh 补 page_api_lint 第3步 + 计数器改 1/3..3/3；install_hooks.py 校验已装 hook 与规范源 hash 一致才允许覆盖

### D-102 P2 · tools/pre-commit-hook.sh（遗留）双跳路径 + 想要的留痕反而不在规范源
- 证据：`tools/pre-commit-hook.sh:15,24,33` `$ROOT/Jinshuiyao_Fixed/tools/gate.py`（ROOT 已 git rev-parse 到仓库根，再拼 Jinshuiyao_Fixed 必不存在）；`:40-49` 第4步调 audit_trail.log_event('commit', ...) —— 这是三份源里唯一有 commit 留痕的，但既不在规范源也不在已装 hook
- 建议：删除该遗留文件，或修正路径并把第4步（commit 留痕）并入 wrapper.sh

### D-103 P2 · tools/pre-commit-hook.bat（遗留 Windows 版）同样双跳 + 计数器错位
- 证据：`tools/pre-commit-hook.bat:6-12` `%ROOT%\Jinshuiyao_Fixed\tools\...` 双跳；输出标"1/3..5/5"与实际 5 步不符；chcp 936 下 UTF-8 注释乱码
- 建议：与 D-102 一并清理（Windows 端已由 install_hooks.py 统一）

### D-104 P2 · "git commit → 自动记录提交事件"宣称不成立
- 证据：全库 `log_event('commit', ...)` 仅出现在 `tools/audit_trail.py:24` docstring 与已废弃的 pre-commit-hook.sh/.bat；`.git/hooks/pre-commit` 无 audit_trail 调用；无 post-commit hook → AGENTS.md"操作留痕系统"表"git commit (pre-commit) 提交事件+文件列表"为假
- 建议：在 wrapper.sh 加第4步 commit 留痕（把 D-102 的写法搬过来并修正路径），或删 AGENTS.md 该行

---

## 四、第3项 · GitHub CI

### D-301 P1 · workflow 永不触发且路径全错
- 证据：`.github/workflows/code-review.yml` push 触发器 `branches: [main]`（仓库分支是 master）；全部命令带 `Jinshuiyao_Fixed/` 前缀，但 `git ls-tree HEAD` 证实仓库根下无此子目录（pyproject.toml 实际在仓库根，存在）
- 影响：PR/push 永远不会触发；即使强行触发，cd Jinshuiyao_Fixed 即失败
- 建议：分支改 master；路径去掉 Jinshuiyao_Fixed/ 前缀；或按 2026-08-12 盘点结论直接删除该 workflow

### D-302 P2 · 各步骤 `|| true` 吞错 → 装饰性绿
- 证据：`code-review.yml` ruff/semgrep/ast/pytest 四步均 `|| true`；仅 smoke 步无 `|| true`（会因 cd 失败而红，即"要么不跑、跑了必红"）
- 建议：删除吞错后缀，恢复 fail-fast；引入真实基线（全量 pytest 992 passed 口径）

---

## 五、第4项 · 计划任务 / 自动同步

### D-401 P1 · 计划任务跑错脚本 → 蒸馏/守卫/索引链断线约 10 天
- 证据：`schtasks /query`（V2）`\Jinshuiyao自动同步` 触发 = `PT1H`，动作 = `模型\同步代码.bat`（非 自动同步.ps1）；`自动同步.ps1:1` 头注释自称"called by Windows Task Scheduler every 30 min"（与实际 PT1H 不符）；断线实锤：`金水谣数据/log/.distill_seen` 与 distill.log 最后写入 2026-08-02 18:08，经验收集箱 08-12 11:48 仍在增长（约 10 天未蒸馏）；与 W63补69 记录"自动同步.ps1 已无人调度 10 天"一致
- 影响：经验→知识卡、数据真实性守卫、知识索引保鲜、vault 刷新四项自动化全部失效；同步代码.bat 只做 git add/commit/push
- 建议：计划任务改执行 `自动同步.ps1`（或 bat 内串联 ps1 第 5-8 步）；ps1 头注释改"每小时"；修好后 .distill_seen 恢复更新可作验证指标

### D-402 P2 · 同步代码.bat 全量 add -A 提交运行时数据
- 证据：`同步代码.bat:33-34` `git add -A` + `git commit -m "自动同步 %date% %time%"`
- 影响：金水谣数据/（运行时 json、日报 html、日志）持续入库，仓库膨胀；自动同步.ps1 本有 noise 过滤与白名单，因 D-401 未被执行而整体失效
- 建议：改回 ps1 通道，或 bat 内用 pathspec 白名单提交

### D-403 P2 · 契宣称 D:\Project_Env 已废止，实际仍在三处使用
- 证据：`金水谣_契.md:268`"历史旧路径 D:\Project_Env\jinshuiyao_env 已废止"；但 `自动同步.ps1:16-21` 用 `D:\Project_Env\jinshuiyao_env\Scripts\python.exe`（目录存在）、`knowledge-mcp.md:43` 同路径、计划任务 `\JinshuiyaoWatchdog` 动作含 D:\Project_Env（watchdog_service.py 存在）
- 影响：文档与事实相反，新 AI 按契判断会误以为该环境已不存在
- 建议：契改"D:\Project_Env 仍被 3 处使用，正在迁移，迁移完成前勿删"

### D-404 P1 · automation_mirror 的 mirror_closeout 指向不存在脚本
- 证据：`core/automation_mirror.py:33` `{"name": "mirror_closeout", "script": "scripts/closeout_gate.py", "guard": "daily@23:30"}`；`scripts/closeout_gate.py` 不存在（真源 `tools/closeout_gate.py`）；其余 12 个 mirror 脚本（scripts/frontend_health_probe 等）全部存在
- 影响：每日 23:30 收工自检必 FileNotFoundError；scheduler.py:264 已 import register_mirrors，此链实际在跑（automation_mirror.jsonl 47 行、最后 2026-08-12 09:09）
- 建议：script 改 `tools/closeout_gate.py`

### D-405 P2 · mirror_frontend_probe 因 GBK 打印崩溃（生产实锤）
- 证据：`automation_mirror.jsonl` 最后一条（2026-08-12T09:09:12）：`mirror_frontend_probe rc=1`，`scripts/frontend_health_probe.py:173 print("\u2713 200")` → UnicodeEncodeError 'gbk' codec can't encode '\u2713'
- 影响：每日 09:00 前端健康巡检失败（探测本身可能通过但进程崩溃 rc=1）
- 建议：脚本入口加 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` 或改 ASCII 输出

---

## 六、第5项 · tests/ 体检

### D-601 P2 · 测试总量口径漂移
- 证据：tests/ 共 67 个 .py（根 19 + integration 6 + isolation 1 + unit 39 + __init__ 若干）；AGENTS.md 称"约 900 项"；交接中心各期登记：W63补49"901 passed/9 skipped"、W63补55"987 passed/9 skipped"、W63补58"988 passed 0 skipped"、W63补59"992 passed"、W63补65"991 passed 1 failed(GBK)"——口径随环境（PYTHONUTF8/坚果云锁 lot_data）波动
- 建议：文档统一为"以 pytest 实际输出为准（近期 992 passed）"；已知 GBK 坑（test_quality_gate_data_guard 需 PYTHONUTF8=1）写入 ai_guard_rules

### D-602 P2 · 双轨测试框架一真一假
- 证据：pytest 轨道健康（67 文件，无 assert True 假测试、无整文件 skip、import 引用全部可解析——脚本验证 12 个"疑似缺失"模块全部落在 scripts//tools//三方库，无一真缺失）；但 run_tests.py 轨道因 D-502 跑 0 测试
- 建议：二选一收口（推荐保 pytest 轨道，run_tests.py 废弃或修 test_dir）

---

## 七、第6项 · 文档漂移

### D-701 P2 · 金水谣_契.md 3 处漂移
- 证据：`:31` `tools/reorg.py`（已归档 tools/archive/）；`:284` `page_registry.json | 25 个用户界面页面`（实际 56 页）；`:155` "默认共 15 项原生任务"（config/scheduler.json 仅 14 个任务键 + proactive_reminder 代码内注册，基本吻合但 key 数不符）
- 建议：契改"56 页"、reorg 行注明归档、任务数注明"14 配置键 + 1 代码注册"

### D-702 P2 · 金水谣_录.md 死引用
- 证据：`金水谣_录.md:78` `scripts/closeout_gate.py`（实际 tools/）
- 建议：改 tools/closeout_gate.py

### D-703 P2 · 金水谣_纲.md ruff 命令双跳路径
- 证据：`金水谣_纲.md:46` `ruff check Jinshuiyao_Fixed/ --config Jinshuiyao_Fixed/pyproject.toml`（在仓库根执行会找不到路径，与 CI 同一病根；pyproject.toml 实际在仓库根）
- 建议：去掉 Jinshuiyao_Fixed/ 前缀

### D-704 P2 · 纲引用的 2 个 Skill 不存在
- 证据：`金水谣_纲.md:117-120` 引用 Skill `jinshuiyao-ai-diligence-check`（抽考）与 `jinshuiyao-knowledge-refresh`（联网新知）；`.opencode/skills/` 共 22 个 skill 目录中无此两者（对应脚本 scripts/ai_diligence.py 与 scripts/knowledge_refresh.py 均存在，只是没做成 skill 目录）
- 建议：要么补建 skill 目录（SKILL.md 引用对应脚本），要么纲改引脚本路径

### D-705 P1 · 知识网关索引统计全面过期 + 文内自相矛盾
- 证据：`知识网关索引.md` 生成时间 2026-08-05 20:32:57；实况 vs 表内：经验收集箱 2299 行 vs 表 2074、ai_decisions 940 vs 900、三元组 4143 vs 2191、卡片 256 vs 203、图谱节点 3741 vs 1288（Skill 22=22 未变）；文内自相矛盾：第四节硬编码"图谱(567条)"（`tools/gen_knowledge_index.py:127`）vs 表格 2191（:108-109 动态算）
- 影响：AI 按索引检索会低估知识资产规模；567 与 2191 并存让读者无所适从
- 建议：重跑 `tools/gen_knowledge_index.py` 并删 :127 硬编码；将生成时间戳纳入 wrapup 门禁（超过 7 天 WARN）

### D-706 P2 · tools/agenda.md 14 天未刷新
- 证据：`tools/agenda.md` 生成时间 2026-07-29（ops.py --round 自动生成，最近工作清单仍停留在 JS-20260729）
- 建议：跑一次 ops.py --round；或在启动流程中提示过期

### D-707 P2 · 交接中心残留已删模块声明
- 证据：`模型/AI协作交接中心.md:34` 仍把 `core/agent_tools.py` 列为新增模块（2026-08-10 已删，W63补55 ⑦ 只修了 AGENTS.md 与契，交接中心漏改）
- 建议：删除该行或标"已删除（W63补55）"

---

## 八、第7项 · 知识网关 / 蒸馏链路

- 知识网关四源接口健康：`core/knowledge_gateway.py` search/summarize 函数齐全；HTTP `GET /api/knowledge/gateway` 已注册；`tools/knowledge_mcp.py` 与 `knowledge-mcp.md` 工具清单一致（search_knowledge/get_experience/query_graph/get_index）；运行路径 D:\Project_Env 存在
- 蒸馏链路脚本齐备但停摆：`tools/auto_distill.py`、`tools/auto_data_truth.py`、`tools/gen_knowledge_index.py`、`自动同步.ps1` 引用的 `obsidian-vault/刷新vault.ps1`、`金水谣助手门户.html` 全部存在，唯一缺口 = D-401（没被调度）
- 归档/镜像清理到位：tools/archive/ 6 个文件（jinshuiyao_python310_validator/python_upgrade_assistant/reorg/smoke_mcp/update_deps_for_310/verify_python314_install）；jinshuiyao-guide/fund-dashboard.html 双副本已删；frontend/lottery/sources-health.html 存在、static.py 两条 lottery-sources-health 路由有效

---

## 九、第8项 · 其他异常（注册表/接线/防空壳）

### D-801 P1 · core/agent_hub.py 全库 0 消费方
- 证据：grep 全库 .py（排除 tests/archive）：`agent_hub` 仅 `core/agent_hub.py` 自引用 3 处；scheduler 的 15 个任务（data_refresh/auto_review/...）全部在 core/scheduler_tasks.py 自行实现（`core/scheduler.py:264` 只接 automation_mirror，不接 agent_hub）；与 W63补69"agent_hub 305 行 0 引用"一致
- 影响：AGENTS.md 核心模块登记表将其列为"统一 Agent 注册中心（W63补38）"，名存实亡；`core/agent_orchestrator.py`/`agent_vector_memory.py` 同理待查
- 建议：按 W63补69 决策点"删 vs 接线"请用户拍板后执行（推荐：删除 agent_hub 三件套或让 scheduler 改走 agent_hub）

### D-802 P1 · engines 注册表 audit 键错位必失败
- 证据：`engines/__init__.py:35` `"audit": ("engines.audit", "SchemeAuditor")`；`engines/audit.py` 实际类名 `class Audit` → 按注册表 `"audit"` 取类必 AttributeError
- 影响：任何走注册表的 audit 引擎解析即炸（W63补69 同判"必失败"）
- 建议：注册表改 `"Audit"` 或类名改 SchemeAuditor（二选一），并加注册表消费方测试

### D-803 P2 · knowledge/kb_engine.py 769 行 0 业务消费方
- 证据：grep 全库：仅 scripts/git_commit_gate.py(1)、tools/ast_checker.py(2)、tools/smoke_test.py(1) 三处"存在性/可索引"检查引用，无业务调用（与 W63补69"kb_engine 769行0引用"一致）
- 建议：接线或归档（用户拍板），防"大模块幽灵"

### D-804 P2 · page_api_lint PENDING_APIS 无到期日（永久 WARN）
- 证据：`tools/page_api_lint.py:28-32` PENDING_APIS 四项：`/api/lottery/historical-same-period`、`/api/lottery/number-follow-up`、`/api/lottery/omission-table`、`/api/lottery/trend-classification`（:117 WARN 不阻断）；W63补67 登记"第二批补建引擎"，至今未建且名单无到期日
- 建议：按 W63补69"PENDING 必须带入库日期+到期日"补字段；第二批引擎落地后移除

### D-805 P2 · engines registry init_domains 从未被调用
- 证据：`engines/__init__.py:9,26` 定义 `_init_domains`/`init_domains`，全库 0 调用
- 建议：删或接线（与 D-801/D-802 一并治理注册表层）

---

## 十、已验证无问题（防误报清单）

| 项 | 验证结果 |
|----|----------|
| 4 子系统导航 | /lottery /fund /stock /football 各 Hub+dashboard 8 条路由全部注册（static.py:80-114）；control-center 指向 /ai-agent /scheduler /engine-dashboard 的 3 个链接页面全部真实存在 |
| mirror 脚本 | 13 个 mirror 任务 12/13 脚本存在（唯一缺失 = D-404），15 分钟守卫窗口在跑（automation_mirror.jsonl 47 行 → 08-12 09:09） |
| tests 质量 | 67 文件无 assert True 假测试、无整文件 skip、测试 import 全部可解析（"疑似缺失"均落在 scripts//tools//三方库）；test_stock_gui.py 的 BOM 报错系解析器假警报（utf-8-sig 编译通过） |
| 启动链 | 启动金水谣助手.bat → launch.bat → launch_jinshuiyao.py 链完整；复制启动提示词.bat → .ps1 → 启动提示词.txt 链完整 |
| 蒸馏链资产 | auto_distill / auto_data_truth / gen_knowledge_index / 刷新vault.ps1 / 金水谣助手门户.html 全部存在（只差调度，见 D-401） |
| 密钥安全 | 密钥已统一 ~/.jinshuiyao-secrets/（core/security.py get_secret 单一入口，W63补56 已收口） |
| 文档主链 | 纲/契/录/交接中心/总索引五件套存在且总索引 v1.1 模板合规 |

---

## 十一、修复优先级建议（行动序）

1. **第一波（P1 止血，半天内）**：D-401（任务改 ps1）、D-404（mirror_closeout 路径）、D-501（smoke 路径×2）、D-502（test_dir）、D-301（CI 分支/路径）、D-201/D-203（审计看板接 operation_log）
2. **第二波（P1 结构性）**：D-802（注册表错位）、D-801（agent_hub 删留拍板）、D-705（网关索引重生成）、D-101（hook 规范源三合一）
3. **第三波（P2 清理）**：D-102~104、D-202、D-302、D-402~403、D-405、D-503~506、D-601~602、D-701~707、D-803~806
4. 每波完成后按铁律 0 登记 JS 编号并重跑 `gate.py --check` / `--audit` / 全量 pytest

---
*本报告由 opencode 流程审计生成 · 证据全部来自只读取证（文件:行号可复核）*
