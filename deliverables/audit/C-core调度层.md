# C 层审计报告：core/ + 调度/智能体接线（零遗漏深挖）

- 审计日期：2026-08-12
- 审计范围：core/ 全部 .py（63 个）、调度器（core/scheduler.py + core/scheduler_tasks.py + core/automation_mirror.py）、智能体（core/ai_agent.py + core/agent_orchestrator.py + core/agent_hub.py）、审计留痕（tools/audit_trail.py + core/audit_log.py + utils/change_audit.py 系）、域注册（core/registry.py + domains/__init__.py）
- 方法：全仓库 grep 引用统计（含 tools/ scripts/ gui/ server/ tests/）、文件存在性实测、磁盘产物核对（金水谣数据/log/*）、.git/hooks 实测
- 统计：问题 17 项（P0=1，P1=5，P2=10，观察=1）
- 红线说明：本次为研究型审计，未改任何代码。

---

## 摘要（最重要 5 项）

| 编号 | 严重度 | 一句话 |
|------|--------|--------|
| C-004 | P0 | 宣称的"全自动操作留痕"全链断：pre-commit 无审计调用、审计轨迹.jsonl 从未生成、看板永远空 |
| C-001 | P1 | mirror_closeout 调错路径（scripts/closeout_gate.py 不存在，实际在 tools/），每日 23:30 收工门禁静默失效 |
| C-002 | P1 | core/agent_hub.py 全库 0 引用（15 个 agent 注册无任何消费方），"统一 Agent 注册中心"名存实亡 |
| C-003 | P1 | init_domains 0 调用：core/registry.py + domains/__init__.py 生产侧死代码，域注册从未执行 |
| C-007 | P1 | fund 域未接入 AI 派发：intent_rules 无 fund、无 dispatch_fund，聊天入口问基金必落 general |

---

## 1. agent_hub 引用链（检查项 1）

### 1.1 谁 import agent_hub？
**全仓库 0 处 import（含 core/ tools/ scripts/ gui/ server/ tests/）**。
- grep `import agent_hub|from core.agent_hub|from core import agent_hub` → 无匹配。
- grep `agent_hub`（全部文件，排除自身）→ 仅文档/数据文件提及：
  - AGENTS.md:131,132,134（登记表）
  - 模型/AI协作交接中心.md:617,693
  - 金水谣数据/log/经验收集箱.md:2079,2296
  - 金水谣数据/review/review_history.jsonl:51,52（历史 CLI 运行痕迹）
  - 金水谣数据/log/operation_log.jsonl:2860（历史记录）
  - tools/.file_hash_baseline.json:22（基线，非代码）
- 唯一可执行入口：`python -m core.agent_hub --list/--run`（agent_hub.py:260-295），无任何自动化调用它。

### 1.2 agent_orchestrator.py 是否使用 agent_hub？
**不使用**。agent_orchestrator.py（85 行）完全没有 import agent_hub，自己实现了三级流水线：
- RouteAgent（agent_orchestrator.py:12-17）：`classify()` 直接调 `agent._parse_intent(text)[0]`
- WorkerAgent（:20-41）：自行维护 dispatch_map（lottery/stock/football/music/video/creator/knowledge/system/web，9 域，**无 fund**）
- ReviewAgent（:44-48）：调 `agent._review_with_free`
- AgentOrchestrator.process（:64-85）：路由→执行→总结→审查
- 唯一消费方：core/ai_agent.py:463-465（`reason()` 方法内延迟 import，异常时回退 chat）

### 1.3 agent_hub 注册的 15 个 agent（agent_hub.py:146-239）
| 分类 | agent 名 | entrypoint（均为 scheduler 静态方法字符串） |
|------|----------|----------------------------------------------|
| 免费模型 | free_model_sync | core.scheduler.JinshuiyaoScheduler._task_free_model_sync（:157-161） |
| 免费模型 | free_model_health | ..._task_free_model_health（:162-166） |
| 代码质量 | ai_code_review | ..._task_ai_code_review（:169-173） |
| 知识管理 | knowledge_extract | ..._task_knowledge_extract（:176-180） |
| 知识管理 | memory_decay | ..._task_memory_decay（:181-185） |
| 知识管理 | cross_link | ..._task_cross_link（:186-190） |
| 知识管理 | kg_rebuild | ..._task_kg_rebuild（:191-195） |
| 知识管理 | kb_lint | ..._task_kb_lint（:196-200） |
| 知识管理 | vector_index_rebuild | ..._task_vector_index_rebuild（:201-205） |
| 数据复盘 | data_refresh | ..._task_data_refresh（:208-212） |
| 数据复盘 | auto_review | ..._task_auto_review（:213-217） |
| 数据复盘 | data_maintenance | ..._task_data_maintenance（:218-222） |
| 数据复盘 | health_backup | ..._task_health_backup（:223-227） |
| 数据复盘 | file_cleanup | ..._task_file_cleanup（:228-232） |
| 提醒 | proactive_reminder | ..._task_proactive_reminder（:235-239） |

结论：15 个名称与 AGENTS.md"W63补38"登记一致；但**注册后的 _AGENTS 字典没有任何消费者读取**（list_agents/run_agent/run_category 均无外部调用方）。

---

## 2. scheduler 任务 vs agent_hub 对账（检查项 2）

调度器入口：server/__init__.py:258-259 调 `start_background_scheduler()`（唯一生产启动点）；另 core/dispatch_system.py:142-143（聊天"调度器状态"）、server/handlers/scheduler.py:37-38（/api/scheduler/status）共用 get_scheduler() 单例。

### 2.1 调度器全部定时任务（core/scheduler.py:97-289 + automation_mirror）
| 任务名 | 触发间隔 | 执行函数 | 注册行 | 实现行 |
|--------|----------|----------|--------|--------|
| data_refresh | 60min, run_now | _task_data_refresh | scheduler.py:131 | :296 |
| auto_review | 120min, run_now, first_delay=420 | _task_auto_review | :143 | :353 |
| knowledge_extract | 120min | _task_knowledge_extract | :153 | :468 |
| data_maintenance | 1440min | _task_data_maintenance | :161 | :622 |
| health_backup | 1440min | _task_health_backup | :169 | :704 |
| file_cleanup | 1440min | _task_file_cleanup | :177 | :722 |
| memory_decay | 1440min | _task_memory_decay | :185 | :809 |
| cross_link | 1440min | _task_cross_link | :193 | :824 |
| kg_rebuild | 1440min | _task_kg_rebuild | :201 | :838 |
| kb_lint | 1440min（仅每月1号） | _task_kb_lint | :209 | :852 |
| vector_index_rebuild | 1440min | _task_vector_index_rebuild | :218 | :880 |
| ai_code_review | 1440min（配置>0 才注册） | _task_ai_code_review | :228 | :902 |
| free_model_sync | 1440min（配置>0 才注册） | _task_free_model_sync | :240 | :977 |
| free_model_health | 120min（配置>0 才注册, run_now） | _task_free_model_health | :251 | :1008 |
| mirror_closeout 等 13 项 | 15min 巡检 + guard 窗口 | automation_mirror._make_func | :263-267 | automation_mirror.py:118-148 |
| proactive_reminder | 30min | _task_proactive_reminder | :270 | :1035 |
| brain_daily | 1440min | _task_brain_daily | :281 | :1054 |

镜像 13 项（automation_mirror.py:32-60）：mirror_closeout(daily@23:30)、mirror_frontend_probe(daily@09:00)、mirror_graph_reconcile(weekly@SUN@05:30)、mirror_lottery_health(daily@07:00)、mirror_free_model_health(daily@08:30)、mirror_lottery_backtest(daily@06:00)、mirror_fund_daily(daily@18:00)、mirror_fund_nav(daily@18:45)、mirror_ai_fund_daily(daily@08:30)、mirror_memory_distill(weekly@SUN@04:00)、mirror_startup_sync(weekly@MON@08:00)、mirror_ai_diligence(daily@23:45)、mirror_knowledge_refresh(weekly@SUN@06:30)。

### 2.2 同名对账与"绕过"
- agent_hub 的 15 个 agent 与调度器任务**同名 14 个**（hub 无 brain_daily；scheduler 的 13 个 mirror_* 与 proactive_reminder 的调度无 hub 对应）。
- **接线方式：全部为"调度器直接调用实现"**。scheduler._register_default_tasks 直接 `self.register(name=..., func=self._task_xxx)`（scheduler.py:131-289），**从不经过 agent_hub.run_agent**。agent_hub 的 entrypoint 字符串指向的恰好是同一批 `JinshuiyaoScheduler._task_*` 静态方法（agent_hub.py:159,164,...），因此"同名注册"= 同一实现的双重登记，hub 侧纯属清单冗余。
- 差异点：① brain_daily 仅在调度器（hub 无）；② ai_code_review 在 hub 无条件注册（agent_hub.py:169-173），在调度器需 config/scheduler.json 中 ai_code_review>0（scheduler.py:228）；③ hub 的 schedule_minutes 与调度器间隔一致（无冲突）。
- scheduler.py:11-12 自述："scheduler 定时任务直接执行实现（薄包装），agent_hub 仅做清单+手动触发，两者互不嵌套调用" —— 设计如此，但后果是**两套清单需人工同步**，且 hub 对调度零影响。

正向：scheduler.json（config/scheduler.json，14 项）与 scheduler.py:100-117 的 _defaults 完全一致（data_refresh=60/auto_review=120/knowledge_extract=120/其余 1440/free_model_health=120），无配置漂移。
---

## 3. core/registry.py + domains/__init__.py（检查项 3）

### 3.1 init_domains 调用链
- `init_domains` 定义：domains/__init__.py:9（`_init_domains`）、:26（`init_domains = _init_domains`）。
- **生产代码 0 调用**。全仓库 grep `init_domains\(\)` 仅命中定义行自身；`from domains import ...` / `import domains` 全仓库仅 tests/unit/test_prediction_service.py:147（`import domains.lottery.domain as _ld`，且只是取子模块，不触发 __init__ 的注册逻辑）。
- 后果链：domains/__init__.py:18-23 的 6 个 register 调用（lottery/football/stock/music/fund/creator）**永不执行** → core/registry.py 的 `_registered_domains` 恒为空 → `get_domain/list_domains/is_registered` 永远空/None。
- core/registry.py 引用数：生产侧 1 处（domains/__init__.py:11 `from core.registry import register`，而该调用方本身不执行）；测试侧 1 处（tests/isolation/test_subsystem_isolation.py:21）。**结论：生产死代码**。
- 实际域实例化走的是 ai_agent._get_domain 手写 if/elif 链（ai_agent.py:106-140：lottery/stock/football/music/creator 5 域，无 fund）—— 与 registry 完全无关的**重复实现**。

### 3.2 core/ 下注册表/工厂清单（搜 register/REGISTRY/_REGISTRY）
| 模块 | 注册机制 | 消费方（引用数） | 状态 |
|------|----------|------------------|------|
| core/registry.py | register/get_domain/list_domains/is_registered | domains/__init__.py:11（不执行）+ 测试 1 | 死 |
| core/agent_hub.py | register_agent → _AGENTS | 0 | 死 |
| core/gui_registry.py | register/running/status/all_status | domains/creator/creator_gui.py、domains/fund/fund_gui.py、domains/stock/stock_gui.py、jinshuiyao/football_gui.py、knowledge/mirofish_gui.py、server/handlers/static.py（共 6） | 活 |
| core/automation_mirror.py | register_mirrors(scheduler) → scheduler.register | core/scheduler.py:264-265 | 活 |
| core/scheduler_tasks.py | TaskScheduler.register/unregister | core/scheduler.py:33（相对导入）+ tests 8 处 | 活 |
| core/scheduler.py | JinshuiyaoScheduler._register_default_tasks → 16 处 self.register | server/__init__.py:258-259、dispatch_system.py:142-143、server/handlers/scheduler.py:37-38、tests 10 处 | 活 |

---

## 4. core/ 全文件健康度（检查项 4）

方法：对每个 core/*.py 统计 `from core.X import / from core import X / import core.X` 全仓库命中（含 core 内部、tools、scripts、gui、server、tests），再实测文件行数。

### 4.1 幽灵（0 引用，含测试）
| 文件 | 行数 | 证据 |
|------|------|------|
| core/agent_hub.py | 305 | 全仓库 0 import（见第 1 节） |
| knowledge/kb_engine.py | ~800+ | 0 代码引用；仅字符串/注释提及（tools/smoke_test.py:21、tools/ast_checker.py:102,107、scripts/git_commit_gate.py:29） |

### 4.2 仅测试引用（半死）
| 文件 | 行数 | 唯一引用 | 备注 |
|------|------|----------|------|
| core/file_organizer.py | 860 | tests/unit/test_auto_systems.py | 功能与 scheduler._task_file_cleanup 重叠（见 C-009） |
| core/file_watcher.py | 361 | tests/unit/test_file_watcher.py | 磁盘证据：金水谣数据/log/backup_audit.logl 477KB 内 2026-07-31 有"由FileWatcher自动"的 BACKUP 记录 → 历史上被使用过，现无生产接线 |
| core/cross_domain.py | 282 | tests/integration/test_cross_domain.py | - |
| core/drift_detector.py | 296 | tests/unit/test_drift_detector.py | - |

### 4.3 有真实消费（重点核查项）
| 模块 | 消费方（计数） | 证据 |
|------|----------------|------|
| agent_vector_memory | 1 生产 | core/ai_agent.py:176（_get_vector_memory）；**无 agent_hub 依赖**（AGENTS.md 登记失实，见 C-006） |
| gui_registry | 6 | 5 个 GUI 入口 + server/handlers/static.py（automation-status 检测 GUI 心跳） |
| adaptive_models | 2 | server/handlers/keys.py、tests/unit/test_ai_service.py；另 ai_service.py 内联使用 |
| security | 4 生产 | core/ai_service.py、core/free_model_pool.py、core/video_extractor.py、server/router.py（+测试 1）—— SSRF 校验单一真源收口成功 |
| knowledge_gateway | 3 生产 | core/ai_agent.py:569,619、server/handlers/knowledge.py:568（/api/knowledge/gateway）、tools/knowledge_mcp.py（+测试 1） |
| audit_log | 5 生产 | domains/stock/fetcher.py:75-101、domains/lottery/domain.py:361-365、engines/prediction_service.py:554-555、core/data_truth_guard.py:128-129、server/handlers/static.py:253-261（OPEN_FILE） |
| automation_mirror | 1 生产 | core/scheduler.py:264（register_mirrors） |
| circuit_breaker | 6 生产 | fetchers/fetcher.py、domains/stock/fetcher.py、domains/stock/stock_gui.py、domains/fund/fetcher.py、core/data_truth_guard.py、core/free_model_pool.py |
| free_model_pool | 12 生产 | core/ai_service.py、core/model_router.py、core/model_shadow.py、core/scheduler.py:1018、server/handlers/ai.py、scripts/ai_diligence.py、scripts/ai_fund_daily_report.py、scripts/free_model_health_check.py、scripts/knowledge_refresh.py、tools/ai_review_agent.py、AI知识库(DeepSeek助手)/deepseek_coder.py |
| strategy_cards（engines/） | 4 生产 | core/scheduler.py:454、engines/evolution_feedback.py:161、domains/lottery/domain.py:335、gui/main_window.py:2193 |
| dimension_consensus（engines/） | 1 生产 | engines/prediction_service.py:129,490 |
| data_maintenance | 1 生产 | core/dispatch_system.py:125（聊天"数据维护"动作）—— 注意调度器的 data_maintenance 用的是**另一套内联实现**（见 C-009） |
| scheduler_tasks | 1 生产 | core/scheduler.py:33（相对导入） |

---

## 5. audit/留痕接线（检查项 5）

### 5.1 三套并存的审计系统
| 系统 | 模块 | 数据文件 | 状态 |
|------|------|----------|------|
| A. 操作留痕（chain-hash） | tools/audit_trail.py:99 log_event | 金水谣数据/log/审计轨迹.jsonl（audit_trail.py:48） | **文件不存在**（实测 金水谣数据/log 全列表无"审计*"）；回放文件 审计轨迹回放.md（:51）也不存在 |
| B. 事件审计 | core/audit_log.py | 金水谣数据/lot_data/log/change_audit.logl（via config.DATA_SAVE，audit_log.py:46-47） | **活跃**：1,106,612 字节，5 个生产消费者（见 4.3） |
| C. 文件变更审计 | utils/change_audit.py（625行）+ utils/smart_audit.py + core/file_watcher.py | 金水谣数据/log/backup_audit.logl（file_watcher.py:265） | 半活跃：backup_audit.logl 477,981 字节（2026-07-31 后无新写）；scripts/ 下另有 audit_system_monitor.py、audit_tool.py、enhance_audit_system.py、prechange_analyzer.py、process_analysis_manager.py、work_record_validator.py 共 6 个审计脚本 |

### 5.2 谁调用 tools/audit_trail.py（A 系统）
- tools/ops.py:299-300（session_start）、:389-395（session_close + write_replay）
- tools/compliance.py:30,71（compliance_report + log_event("compliance")；--out 追加到模型/AI协作交接中心.md，compliance.py:34-54）
- tools/closeout_gate.py:227-232（gate_pass/gate_fail）
- server/handlers/static.py:304-318（/api/audit-trail 读 get_today_events/verify_chain）
- **没有任何调用方记录 "commit" 事件**；"bypass" 事件只在 audit_trail.py:187,257,297 被读取/显示，**全仓库无生产者**（防绕过检测失效）。

### 5.3 .git/hooks/pre-commit 实测
全文件仅 3 步（shell wrapper，无任何 audit_trail 调用）：
1. tools/check_consistency.py
2. tools/precommit_ai_review.py
3. tools/page_api_lint.py
→ **AGENTS.md「git commit (pre-commit) → 提交事件 + 文件列表 → 同上（自动记录）」的宣称与实现不符**。git log 实测有历史提交（如 52bc7d1, 2026-08-12），但这些提交从未产生审计轨迹记录。

### 5.4 /audit-dashboard 数据链路
- 路由：server/handlers/static.py:69（'/audit-dashboard' → jinshuiyao-guide/audit-dashboard.html，仅 5 行重定向页，:3 跳转到 /lottery/audit-dashboard）与 :91（'/lottery/audit-dashboard' → frontend/lottery/audit-dashboard.html）。
- 前端：frontend/lottery/audit-dashboard.html:113 `fetch('/api/audit-trail')`。
- 后端：server/router.py:434-436 → static.py:304-318 → tools.audit_trail.get_today_events() → 读 审计轨迹.jsonl。
- **由于 A 系统文件从未生成，看板将永远显示空事件列表**（且 verify_chain 对空文件返回 ok，无任何提示）。

### 5.5 写盘路径核对
- 审计轨迹.jsonl：不存在（P0 断链实锤）
- change_audit.logl：存在（lot_data/log/，A/B 系统分开写盘成功，B 系统正常）
- backup_audit.logl：存在但 2026-07-31 后停更
- scheduler_exec.jsonl：存在（732,552 字节，ship 层正常）
- automation_mirror.jsonl：存在（64,336 字节，8/12 仍在写）→ 镜像任务日志正常，唯独 mirror_closeout 写的是"脚本缺失"（见 C-001）
- kb_lint.jsonl：**不存在**（scheduler.py:1074 的写路径）→ 月度体检从未产生日志（或未到 1 号，观察项，见 C-017）

---

## 6. automation_mirror（检查项 6）

- 注册点：core/scheduler.py:263-267（register_mirrors，每 15 分钟巡检窗口）。
- 目标脚本存在性实测（13 项）：
  - **scripts/closeout_gate.py → 不存在（False）**；真实文件在 tools/closeout_gate.py。→ mirror_closeout（daily@23:30 收工五查门禁）自接线之日起每天"脚本缺失"（automation_mirror.py:135-137 写 rc=127 日志），门禁永不执行。
  - 其余 12 项全部存在（scripts/frontend_health_probe.py、graph_triples_reconcile.py、lottery_datasource_health.py、free_model_health_check.py、backtest_lottery_honest.py、daily_fund_monitor.py、fund_nav_daily_refresh.py、ai_fund_daily_report.py、memory_distill.py、startup_prompt_sync.py、ai_diligence.py、knowledge_refresh.py → True）。
- 补充：automation_mirror.jsonl 实测 64KB 且 2026-08-12 09:09 仍在写入 → 其他 12 个镜像在真实运行；guard 机制（_period_key/_guard_open，:67-95）正常。
- 每任务独立异常隔离 + 日志落盘（:98-115, 144-146），结构良好。

---

## 7. ai_agent 域派发（检查项 7）

### 7.1 派发表
| 域 | INTENT_RULES 关键词（intent_rules.py:13-107） | chat() 派发（ai_agent.py:537-556） | dispatch 模块 | _get_domain（ai_agent.py:110-125） |
|----|------|------|------|------|
| lottery | :15-23 | :537-538 | core/dispatch_lottery.py | ✓ |
| stock | :26-32 | :539-540 | core/dispatch_stock.py | ✓ |
| football | :35-38 | :541-542 | core/dispatch_football.py | ✓ |
| music | :41-47 | :543-544 | core/dispatch_music.py | ✓ |
| video | :73-77 | :545-546 | core/dispatch_video.py | ✓ |
| creator | :101-106 | :547-548 | core/dispatch_creator.py | ✓ |
| knowledge | :80-88 | :549-550 | core/dispatch_knowledge.py | ✓ |
| system | :50-70, 96-98 | :551-554 | core/dispatch_system.py | - |
| web | :92-93 | :555-556 | core/agent_web_search.py | - |
| **fund** | **无** | **无** | **无** | **无** |

- 意图识别规则权重：intent_rules.py:325-334（关键词字数加权，长词优先）；无法识别时免费模型分类（ai_agent.py:293-307，域枚举 :302 含 lottery/stock/football/music/system/general/knowledge/video/creator，**无 fund/web**）→ 付费兜底（:342-349，同样无 fund/web）。
- AgentOrchestrator.dispatch_map（agent_orchestrator.py:25-35）：lottery/stock/football/music/video/creator/knowledge/system/web，**无 fund**。
- dispatch_system 的 status/review 循环（dispatch_system.py:30,46）：["lottery","stock","football","music","creator"]，**无 fund**。
- 对照：domains/__init__.py:22 注册了 FundDomain；server/handlers/fund.py:30、server/handlers/backtest.py:30、domains/fund/fund_gui.py:93、scripts/fund_nav_daily_refresh.py:40 都能实例化 FundDomain → **基金功能完备但完全绕开了 AI 聊天入口**。

---

## 8. 其他异常（检查项 8）

### 8.1 错误处理（裸 except / pass 吞错）
全 core/ 统计（含多行 except 的间接 pass）：
- 裸 `except Exception:`（无日志）高频文件：ai_agent.py(7)、knowledge_gateway.py(7)、free_model_pool.py(6)、ai_service.py(6)、model_router.py(5)、model_shadow.py(5)、video_to_kb.py(5)、agent_reminder.py(4)、adaptive_models.py(4)、security.py(4)
- 典型实例：scheduler.py:126-127（scheduler.json 解析失败静默用默认值，可接受）；scheduler_tasks.py:351-352（日志写入失败 pass）；knowledge_gateway.py 7 处（多为检索降级）；gui_registry.py:107-108（pid 判定失败保守返回 True，注释说明）。
- 判定：多数为"降级不阻断"设计，但 free_model_pool/ai_service 的 12 处裸 except 无 logger 输出，故障排查时黑洞（建议至少 logger.debug）。

### 8.2 硬编码密钥/URL
- 密钥：core/ 无硬编码（`sk-`、`api_key="..."`、`Bearer` 全库 0 命中）；密钥统一走 core/security.py:18-57 get_secret（~/.jinshuiyao-secrets 单一真源）。
- URL：均为合法服务端点，无敏感信息：
  - ai_service.py:191-193（连通性探测：deepseek/baidu/google）、:272-301（4 provider chat completions：deepseek/dashscope/bigmodel/moonshot）
  - adaptive_models.py:47-49（dashscope 2 个 URL）
  - free_model_pool.py:168（deepseek base_url —— 与 ai_service.py:272 重复定义，见 C-011）
  - agent_web_search.py:21-22（duckduckgo html + tavily api）
  - video_extractor.py:471,546,594（douyin/bilibili 公开 API）

### 8.3 未使用参数
- agent_hub.run_agent(name, timeout=30*60, **kwargs)（agent_hub.py:101）：函数体内**从未使用 timeout**（:117 直接 fn(**kwargs)）；run_category 同理（:136）。→ C-010。
- dispatch_video/agent_video_handler 的 user_input 传参链正常（有消费）。

### 8.4 大函数清单（>100 行，ast 实测 16 个）
| 函数 | 行数 | 位置 |
|------|------|------|
| chat | 208 | core/ai_agent.py:474 |
| dispatch_system | 285 | core/dispatch_system.py:16 |
| dispatch_knowledge | 207 | core/dispatch_knowledge.py:13 |
| _register_default_tasks | 193 | core/scheduler.py:97 |
| ai_service.chat | 180 | core/ai_service.py:756 |
| check_orphan_files | 158 | core/file_organizer.py:324 |
| _task_knowledge_extract | 152 | core/scheduler.py:468 |
| cleanup_old_predictions | 148 | core/data_maintenance.py:260 |
| apply_dark_style | 138 | core/tk_style.py:35 |
| _run_pipeline | 134 | core/pipeline_state.py:175 |
| extract_triples_from_experience_box | 127 | core/exp_box_extractor.py:320 |
| extract_from_conversation_log | 120 | core/auto_knowledge.py:774 |
| extract_triples_from_ai_decisions | 117 | core/ai_decisions_extractor.py:221 |
| _task_auto_review | 113 | core/scheduler.py:353 |
| full_organize | 111 | core/file_organizer.py:639 |
| vacuum_all | 106 | core/data_maintenance.py:745 |

### 8.5 重复实现
- **数据维护双实现**：scheduler._task_data_maintenance（scheduler.py:622-701，内联"清理预测+错误日志+备份"）vs core/data_maintenance.py DataMaintainer（1108 行，dispatch_system.py:125 用）→ 两套口径，调度任务用的是简化版。
- **文件清理双实现**：scheduler._task_file_cleanup（scheduler.py:722-802）vs core/file_organizer.py（860 行，仅测试引用）。
- **域实例化双实现**：domains/__init__.py 注册式 vs ai_agent._get_domain 手写链（见 C-003）。
- **模型端点重复**：deepseek base_url 出现于 ai_service.py:272 与 free_model_pool.py:168；dashscope URL 出现于 ai_service.py:286 与 adaptive_models.py:47,49。
- **search 助手**：agent_vector_memory.py:90 search 与 knowledge_gateway.py:271 search 语义不同（向量记忆 vs 四源召回），非重复；`def load_json` 全仓库 0 个自定义（统一用 utils.safe_json.safe_load_json），无重复。
- **审计实现重复**：三套系统 + 6 个 scripts 审计脚本（见第 5 节）。

### 8.6 文档漂移
- scheduler.py:10 与 :61-68 docstring 声称"预注册6项默认定时任务"；实际注册 16 原生 + 13 镜像 = 29 项。
- AGENTS.md 登记表：agent_orchestrator 标注"agent_hub 依赖"（实际无）、agent_vector_memory 标注"agent_hub 依赖"（实际无）、"pre-commit 自动记录提交事件"（实际 hook 无审计调用）——三处失实。
- 任务拆分不彻底：scheduler_tasks.py 只拆走了 TaskScheduler 基类（352 行），16 个任务实现仍留在 scheduler.py（1124 行）。

---

## 9. 问题清单（编号+严重度+证据+修复建议）

### C-001 [P1] mirror_closeout 脚本路径错误
- 证据：core/automation_mirror.py:33 `"script": "scripts/closeout_gate.py"`；磁盘实测 scripts/closeout_gate.py 不存在，真实文件为 tools/closeout_gate.py；automation_mirror.jsonl 中 rc=127"脚本缺失"记录。
- 影响：每日 23:30 收工五查门禁自动执行静默失效（手动 tools/gate.py 不受影响）。
- 修复：automation_mirror.py:33 改 `"scripts/closeout_gate.py"` → `"tools/closeout_gate.py"`（或 scripts/ 下建薄 wrapper）。

### C-002 [P1] agent_hub 全库 0 引用（幽灵注册中心）
- 证据：core/agent_hub.py 全文件（305 行）；全仓库 0 处 import（含 tools/scripts/gui/server/tests）；15 个 register_agent 调用（:157-239）的 _AGENTS 无任何读取方。
- 影响：AGENTS.md 宣称的"统一 Agent 注册中心"名存实亡；hub 与 scheduler 双清单漂移风险。
- 修复：二选一——a) 让 scheduler 通过 agent_hub.run_agent 触发（在 _register_default_tasks 中 func=lambda: run_agent("data_refresh")["ok"]），实现"一处注册、处处可跑"；b) 承认 hub 仅为 CLI 工具，删除并更新 AGENTS.md 登记表。

### C-003 [P1] init_domains 0 调用 → core/registry.py 生产死代码
- 证据：domains/__init__.py:9-26（定义即全部）；`init_domains\(\)` 全仓库仅命中定义；core/registry.py:15-58 引用仅 domains/__init__.py:11（不执行）+ tests/isolation/test_subsystem_isolation.py:21；域实例化实际走 ai_agent.py:106-140 手写链。
- 影响：注册表模块与 6 域注册逻辑永远空转；新域必须手写接入 ai_agent，违反"注册即接入"设计。
- 修复：server/__init__.py 或 main 入口调用一次 `domains.init_domains()`，并让 ai_agent._get_domain 改经 registry.get_domain 获取（或删除 registry 模块，二选一）。

### C-004 [P0] 审计留痕全链断（宣称自动留痕，实际零数据）
- 证据：.git/hooks/pre-commit 实测仅 check_consistency / precommit_ai_review / page_api_lint 三步，无 audit_trail 调用（AGENTS.md 宣称"提交事件自动记录"）；金水谣数据/log/ 无 审计轨迹.jsonl 与 审计轨迹回放.md；tools/audit_trail.py:48,51 定义路径；server/handlers/static.py:304-318 读空文件返回空 events；tools/ops.py:299,389 是仅有的写入口（session_start/close）且从未产出文件；"bypass" 事件（:187,257,297）全仓库无生产者。
- 影响：操作留痕系统（chain-hash 防篡改）从未运转，/audit-dashboard 永远空，防 --no-verify 绕过检测失效；合规报告（compliance.py）基于空数据输出"流程不完整"假警报。
- 修复：① pre-commit 增加 `"$PY" "$ROOT/tools/audit_trail.py" --log commit "$(git log -1 --format=%s)"`（或等效 python -c 调用，含文件列表）；② ops.py --start 确认可写审计轨迹.jsonl（人工验证一次）；③ 审计轨迹.jsonl 缺省时 /api/audit-trail 返回显式"留痕未启用"提示而非空数据。

### C-005 [P1] 调度器与 agent_hub 脱钩（双清单漂移）
- 证据：scheduler.py:131-289 直接 self.register(func=self._task_*) 从不经 agent_hub.run_agent；agent_hub.py:157-239 的 15 个 entrypoint 虽指向同一批 _task_* 但零触发；差异实例：brain_daily 仅调度器（scheduler.py:281-289）、ai_code_review 注册条件不一致（hub 无条件 :169-173 vs 调度器需配置>0 :228-234）。
- 修复：与 C-002 合并处理；若保留 hub，由 scheduler 注册处统一经 hub 解析 entrypoint，消除两处手工同步。

### C-006 [P2] AGENTS.md 核心模块登记表三处失实
- 证据：AGENTS.md:131-134（"agent_orchestrator（agent_hub 依赖）"、":131-134 agent_vector_memory（agent_hub 依赖）"）；实测 agent_orchestrator.py 全文无 agent_hub import（自实现 :12-56）；agent_vector_memory 仅被 ai_agent.py:176 消费。
- 修复：修正 AGENTS.md 登记表描述（orchestrator=自实现三 Agent 流水线；vector_memory=ai_agent 记忆依赖）。

### C-007 [P1] fund 域未接入 AI 派发
- 证据：intent_rules.py:13-107 无 fund 关键词；ai_agent.py:537-556 派发链无 fund；ai_agent.py:110-125 _get_domain 无 fund；agent_orchestrator.py:25-35 dispatch_map 无 fund；dispatch_system.py:30,46 状态/复盘循环无 fund；对照 domains/__init__.py:22 注册 FundDomain、server/handlers/fund.py:30 可实例化。
- 影响：用户聊天问基金（净值/持仓/日报）必落 general 纯聊天，基金能力只能经 GUI/HTTP 使用。
- 修复：intent_rules 增 fund 关键词组（净值/基金/持仓/经理/定投）；新增 core/dispatch_fund.py（薄委托 domains/fund/domain.py FundDomain）；_get_domain 补 fund 分支；orchestrator dispatch_map 补 fund。

### C-008 [P2] 半死模块 4 件套
- 证据：core/file_organizer.py（860 行，仅 tests/unit/test_auto_systems.py）；core/file_watcher.py（361 行，仅 tests/unit/test_file_watcher.py；历史产物 backup_audit.logl 2026-07-31 有 BACKUP 记录）；core/cross_domain.py（282 行，仅 tests/integration/test_cross_domain.py）；core/drift_detector.py（296 行，仅 tests/unit/test_drift_detector.py）。
- 修复：file_organizer/file_watcher 接线到调度器对应任务（消除 C-009 双实现）或归档；cross_domain/drift_detector 评估后删除或接入。

### C-009 [P2] 数据维护/文件清理双实现
- 证据：scheduler.py:622-701（_task_data_maintenance 内联简化）vs core/data_maintenance.py DataMaintainer（消费方 dispatch_system.py:125）；scheduler.py:722-802（_task_file_cleanup）vs core/file_organizer.py。
- 修复：调度任务改为调用 DataMaintainer/FileOrganizer 统一实现，删内联版。

### C-010 [P2] agent_hub.run_agent/run_category 的 timeout 参数未使用
- 证据：agent_hub.py:101（签名含 timeout=30*60）、:117（fn(**kwargs) 未传 timeout）、:136（run_category 同样）。
- 修复：实现超时（ThreadPoolExecutor future.timeout）或删除参数。

### C-011 [P2] 模型端点重复定义
- 证据：ai_service.py:272（deepseek base_url）与 free_model_pool.py:168 重复；dashscope URL 分散 ai_service.py:286 与 adaptive_models.py:47,49。
- 修复：收敛到 config/ 或 core/model_endpoints.py 单一常量表。

### C-012 [P2] 大函数 16 个（见 8.4 表）
- 修复：优先拆分 dispatch_system（285 行）、ai_agent.chat（208 行）、_register_default_tasks（193 行）、ai_service.chat（180 行）。

### C-013 [P2] 裸 except 吞错集中在 free_model_pool/ai_service/model_router（合计 17 处无日志）
- 证据：见 8.1；free_model_pool.py:206,259,290 与 llm_budget 交互处、model_router.py:113,180 等。
- 修复：至少加 logger.warning/debug；异常链保留。

### C-014 [P2] 调度器文档漂移 + 拆分不彻底
- 证据：scheduler.py:10,61-68（"6项默认定时任务"）vs 实际 29 项；scheduler.py 1124 行 vs scheduler_tasks.py 仅基类 352 行。
- 修复：更新 docstring；把 16 个 _task_* 迁至 scheduler_tasks.py（或 tasks/ 目录）。

### C-015 [P2] 审计系统三套并存、数据三处落盘
- 证据：tools/audit_trail.py（审计轨迹.jsonl，A 系统）、core/audit_log.py（change_audit.logl，B 系统活跃 1.1MB）、utils/change_audit.py+smart_audit.py+scripts 6 脚本（backup_audit.logl 等，C 系统）。
- 修复：明确各系统边界（A=操作留痕/B=业务事件/C=文件变更），文档化；逐步把 C 系统并入 A 或 B。

### C-016 [P2] "bypass" 防绕过事件零生产者
- 证据：audit_trail.py:187,257,297 仅读取/展示；全仓库无 log_event("bypass")。
- 修复：pre-commit 检测 `git -c ai.review=0` 等绕过参数时写入 bypass 事件（与 C-004 一并实现）。

### C-017 [观察] kb_lint.jsonl 从未生成
- 证据：scheduler.py:1074-1084（_write_kb_lint_log 写 金水谣数据/log/kb_lint.jsonl）；实测文件不存在。可能原因：kb_lint 仅每月 1 号执行（scheduler.py:857-860 日期守卫）且近期未逢 1 号，或从未执行。
- 建议：待 9 月 1 号后复核；若仍无文件则检查调度器是否存活（scheduler_exec.jsonl 存在，调度器本身在跑）。

---

## 10. 正向发现（非问题）
- core/security.py 收口成功：is_safe_http_url/get_secret 被 4 个生产模块复用，无反向依赖（security.py:8 设计达成）。
- config/scheduler.json 与调度器 _defaults 完全一致，无配置漂移。
- 无任何硬编码密钥（sk-*/Bearer 全库 0 命中）。
- automation_mirror 13 项中 12 项脚本存在且日志正常写入；guard 去重机制（_period_key/_state）实现正确。
- free_model_pool（12 消费方）、gui_registry（6）、circuit_breaker（6）、strategy_cards（4）、knowledge_gateway（3 生产+HTTP+MCP 三入口）均为健康链路。
- scheduler_tasks 拆分后 scheduler.py 重导出（:33）保持了 import 兼容，测试 10 处引用无断裂。

（报告完）
