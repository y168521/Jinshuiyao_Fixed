# 审计报告 B：业务层 domains/engines/fetchers/knowledge（2026-08-12）

> 审计员：explore agent（零遗漏模式）| 结论：主链路健康无伪造数据，1 个架构缺口 + 1 个关键空壳 + 假注册 2 处 + 死代码 6 模块

## 总体结论
- 数据真实性：✅ 无伪造。彩票多源抓取（CWL/500/凤凰/乐彩）真 HTTP；足彩 33.3% 降级概率为真（football.py:139，ML 不可用降级本地模型，非造假）
- 主链路健康：lottery/fund/stock/football/music/creator 六域真实现；预测流水线（杀号→热号→赫斯特→遗漏→形态→关联→FormatGen）真实串联

## 问题清单

### P1-101 fund 子系统未接入 AI 域调度与定时任务
core/ai_agent.py _get_domain 只支持 5 域（lottery/stock/football/music/creator，**无 fund**）；core/scheduler.py 无 fund 定时任务。fund 只能 Web API + GUI 触达。
修复：ai_agent._dispatch_map/_get_domain 补 fund；intent_rules 补基金关键词；scheduler 补 fund 每日任务。

### P1-102 lottery domain analyze() 是占位壳
domains/lottery/domain.py:106-133：不调用任何引擎，只返回 {"status":"ready","engine_count":N}；真正预测在 generate()（数据新鲜度门禁+完整流水线）。依赖 analyze() 的调用方拿到空数据。
修复：analyze() 改为真实调用预测流水线，或调用方改走 generate()。

### P2-103 engines/__init__.py:35 audit 假注册
注册 audit→SchemeAuditor，但 from .audit import Audit 不存在（模块级 import 失败被吞/惰性）。类 Audit（engines/audit.py:15）从未实例化。
修复：补正确 import 或删除假注册。

### P2-104 domains/__init__.py:9-26 init_domains() 全库 0 调用
修复：接线（ai_agent 改走注册表）或删除死注册。

### P2-105 半死模块（被加载无业务调用）
- knowledge/ai_test_knowledge.py：AITestKnowledge 0 业务调用
- engines/prediction_service.py:51 schemes 死字段（多写内存无人读）
- engines/brain_daily.py:29 _PLAY_EXPECTED 与 prediction_service.py:64 重复定义、自身 0 引用
- fetchers/stock_fetcher.py:216-220 缓存 TTL 60 秒写死不强制执行，全靠调用方自觉传参

### P2-106 fund_fetcher.py:367 字段映射疑点
"基金公司"映射位置疑似错位，需人工复核该行含义。

## 死代码确认（0 引用含测试）
- 6 死模块：core/brain_engine.py、engines/ai_test_brain.py、engines/ai_commentary.py、engines/ai_analysis_engine.py、engines/spotlight_engine.py、engines/sync_network.py（+engines/sync_queue.py）
- 孤儿类：engines/audit.py:15 Audit（唯一引用是 __init__ 字符串假注册）
- 37 个纯测试类死测试（如 killer.TestKiller、sync_manager.TestSyncManager 等，测试文件内自带测试类）
- 空包：domains/music/engines/__init__.py、domains/stock/engines/__init__.py

## 真活清单（防误伤）
killer/format_gen/hurst/correlation/morph/dimension_consensus 全真活（prediction_service 真实调用）；fund/stock/football/music/creator analyze/generate 真实现；fetchers/fetcher.py 7 抓取方法 6 处真调用；knowledge/mirofish_db.py、kb_engine.py（spaced_repetition 5 调用方）、init_knowledge.py、ai_test_generator.py（main_window 生成按钮+enhanced 引用）真活；用户知识库 lint/archive 被 server 路由调用