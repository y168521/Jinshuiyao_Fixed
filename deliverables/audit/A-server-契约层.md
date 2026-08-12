# 审计报告 A：server 层 + 前端契约层（2026-08-12)

> 审计员：explore agent（零遗漏模式）| 结论：路由/文件层基本健康，4 个前端调用无路由、sync 子系统整体缺失、重复注册与代码卫生若干

## 检查方法
- server/router.py（server/ 根，760 行）112 个 handler 函数全部存在性核实
- server/handlers/static.py 全部页面路由 → 文件存在性核实
- frontend/ + jinshuiyao-guide/ 所有页面 fetch('/api/...') 与路由注册表双向 diff
- handlers/ 18 个文件逐一体检

## ✅ 已确认健康（防误伤）
- router.py 引用的 112 个 handler 函数全部存在（handle_error_report 为误报，存在）
- static.py 页面路由 0 死路由（所有文件真实存在）
- /api/lottery/math-model 为 engines/math_selector 包（目录形式），存在且含 run_math_model

## 问题清单

### P1-001 前端调用无路由（4 个，均为 POST）
| 页面 | 调用行 |
|---|---|
| historical-same-period.html:161 → /api/lottery/historical-same-period | 无路由 |
| number-follow-up.html:184 → /api/lottery/number-follow-up | 无路由 |
| omission-table.html:162 → /api/lottery/omission-table | 无路由 |
| trend-classification.html:202 → /api/lottery/trend-classification | 无路由 |

修复建议：PENDING 名单（page_api_lint）已有 4 项 WARN；需建 4 个真实引擎 handler（数据源：fetcher 历史开奖 + 现有分析模块）。

### P1-002 sync 子系统整体缺失
- device_sync 模块不存在，被引用处：sync.py、launch_jinshuiyao.py、startup_selfcheck.py、tools/doctor.py、tools/auto_backup.py
- sync/ 目录不存在（config.py SYNC_DIR 指向它）
- 受影响路由：/sync、/sync-api/state、/sync-api/task、/sync-api/identity（全 500）
- 前端受影响：workbench.html:1418/1762 调用 /sync-api/state

修复建议：三选一——①补 device_sync.py 最小实现（跨设备同步是宣传中的功能）②路由与依赖全删（诚实不宣称）③在 doctor/startup_selfcheck 的引用处 try/except 容错。**先确认引用是否懒加载（server 能启动说明是容错或未执行）再定**。

### P2-003 static.py 重复注册死条目（永远不被命中）
- /sync（router.py:141 先拦截）
- /lottery-sources-health（router.py:293 vs static.py:72）
- /review-dashboard（router.py:328 vs static.py:47）
修复建议：static.py 删除 3 条重复条目。

### P3-004 trend.py log 调用签名错误
- trend.py:48/87/95 log("error", ...) 双参数，utils.log(msg) 单参数 → 出错路径二次抛 TypeError（该 API 前端无调用方，前端趋势图用静态 trend-data.js 219KB）
修复建议：改为 log(单参数) 或修 utils.log 支持双参。

### P3-005 fund.py:12 死文档
docstring 声称 /api/fund/with-benchmark，router 未注册、无实现。修复：更正 docstring 或实现。

### P3-006 fund.py vs backtest.py 重复 6 函数
get_fund_domain / _parse_params / _to_float / _to_int / _parse_codes / handle_backtest。修复：合一，backtest 转发 fund 或反向。

### P3-007 未使用 import（handler 层）
error_report、fund、backtest、review、filter、static、chainmap 相关文件存在未用 import。修复：清理。

### P3-008 try/except pass 吞错 3 处
error_report.py:40、knowledge.py:120、fund.py:43。修复：加日志或降级说明。

### P3-009 页面双副本
- 5 个 meta-refresh 壳（guide 版 322B）：audit-dashboard / filter-panel / head-tail-analysis / prize-calculator / rotation-matrix（真版在 frontend/lottery）
- 3 组双真版：lottery-dashboard、lottery-sources-health（2 行差异）、omission-heatmap（frontend/trend vs frontend/lottery）
修复建议：壳页删除（指向目标已注册）；双真版确认路由指向后删一留一。

## 其他观察
- telemetry 相关内联在 router.py（3 处）
- handler 总体质量良好，无伪造数据