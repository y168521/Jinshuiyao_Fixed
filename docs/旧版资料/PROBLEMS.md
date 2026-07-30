# 金水谣引擎 - 问题追踪与系统功能清单

## 第一部分：反复出现的问题清单

### P1: 端口18888被占用导致服务器启动失败（发生 >=8次）
- **表现**: 双击启动导航.bat后，黑色窗口一闪而过，浏览器没有打开
- **根因**: 上次关闭时系统没有及时释放端口（TIME_WAIT状态），再次启动时端口冲突
- **修复时间**: 2026-07-15
- **修复方案**: 启动导航.bat增加端口检查和自动清理逻辑
- **预防措施**: 每次双击启动导航.bat前，先关闭旧的黑色窗口

### P2: GUI窗口打不开（发生 >=10次）
- **表现**: 双击run.bat或点击总控台按钮，窗口一闪而过或完全没反应
- **根因**:
  1. GUI文件缺少sys.path设置，直接运行时报ImportError
  2. 按钮指向domain.py（非GUI文件）而非xxx_gui.py
  3. guide_server.py未设置PYTHONPATH环境变量
  4. 使用pythonw.exe（无控制台）导致错误不可见
- **修复时间**: 2026-07-15
- **预防措施**:
  - preflight_check.py 自动检查所有GUI文件的sys.path
  - 所有GUI文件必须用统一的_this_dir/_project_dir模式
  - guide_server.py必须用python.exe+PYTHONPATH
- **验证结果**: 已通过preflight_check.py 9/9验证

### P3: 单元测试通过但实际打不开（发生 >=10次）
- **表现**: run_tests.py全部通过，但用户双击打不开
- **根因**: 单元测试用mock假tkinter，不测试实际GUI启动
- **修复时间**: 2026-07-15
- **预防措施**:
  - 修改GUI/启动文件后必须跑preflight_check.py + smoke_test.py
  - 不再以"单元测试全过"作为"功能可用"的唯一依据
- **验证结果**: 已记录到检查清单

### P4: 弹出"正在打开..."确认窗口
- **表现**: 点击按钮后弹浏览器确认页，显得不专业
- **根因**: guide_server返回HTML页面而非JSON，前端用window.open
- **修复时间**: 2026-07-15
- **预防措施**: 前端改用fetch+toast，后端返回JSON
- **验证结果**: 已验证（control-center.html中openSubsystem使用fetch+showToast，guide_server的/open路由返回JSON）

### P5: GUI窗口被CREATE_NO_WINDOW隐藏（本次修复，发生 >=3次）
- **表现**: 点击"彩票预测系统"按钮后，Python进程启动成功（能看到PID），但GUI窗口没有弹出显示
- **根因**: guide_server.py的open_local_file函数对所有.py文件统一使用subprocess.CREATE_NO_WINDOW标志，导致GUI窗口被隐藏
- **修复时间**: 2026-07-17
- **修改文件**: guide_server.py (open_local_file函数)
- **修复方案**: 对GUI文件（main_window.py和所有*_gui.py）不使用CREATE_NO_WINDOW标志，普通脚本文件仍然使用
- **验证结果**: 已通过 e2e 测试验证（服务器日志明确显示"[运行模式-GUI] ... (窗口显示)"）
- **预防措施**:
  1. 新增GUI文件时必须加入guide_server.py的gui_files列表
  2. preflight_check.py应检查gui_files列表是否完整

### P6: 配色优化后按钮颜色失真（本次对话中修复）
- **表现**: 优化后的系统按钮颜色从科技风变得刺眼难看
- **根因**: 按钮配色从和谐的主题变量T.COLOR_*改为了硬编码的十六进制颜色值
- **修复时间**: 2026-07-16
- **修改文件**: gui/main_window.py (btn_defs部分)
- **修复方案**: 恢复使用ModernTheme类定义的统一颜色变量

### P7: 审计日志被FileWatcher垃圾记录淹没
- **表现**: change_audit.logl文件被806条无效的FileWatcher自动备份记录填满，真实操作记录难以查找
- **根因**: FileWatcher自动监控对所有文件变更生成审计日志，且无去重逻辑
- **修复时间**: 2026-07-16
- **修改文件**: 清理日志文件，保留98条有效记录
- **预防措施**: FileWatcher备份操作应该使用独立的日志级别，不混入用户操作审计日志

## 第二部分：工作流程规范（每次操作前必须遵守）

### 操作原则（之前反复出问题的根因）

```
[核心原则] 先搜索 → 再思考 → 最后动手
           没有搜索过最佳实践就直接修改，是之前所有问题的根源
```

### 检查清单

```
[ ] 0. 每次修改前           -> 先搜索：有没有成熟的方案/最佳实践？
[ ] 1. 修改了GUI/启动文件     -> 跑 preflight_check.py
[ ] 2. 修改了子系统           -> 确认 domains/__init__.py 已注册
[ ] 3. 修改了HTML             -> 确认按钮指向GUI文件而非domain.py
[ ] 4. 所有代码修改           -> 跑 run_tests.py（726个）
[ ] 5. 所有功能修改           -> 跑 smoke_test.py（10项）
[ ] 6. 新增GUI文件            -> 加入 guide_server.py 的 gui_files 列表
[ ] 7. 修改了配色/主题         -> 确认使用T.COLOR_*主题变量而非硬编码颜色
[ ] 8. 修改了端口/启动逻辑     -> 确认不影响端口检查和GUI窗口显示
```

## 第三部分：修复历史存档（防止重复修复）

| 日期 | 问题 | 修改文件 | 根因 |
|------|------|---------|------|
| 2026-07-17 | GUI窗口被隐藏 | guide_server.py | CREATE_NO_WINDOW标志 |
| 2026-07-16 | 按钮颜色失真 | main_window.py | 硬编码颜色值替代主题变量 |
| 2026-07-16 | 审计日志被淹没 | 日志清理 | FileWatcher无去重逻辑 |
| 2026-07-15 | 端口冲突 | 启动导航.bat | 端口未释放导致冲突 |
| 2026-07-15 | GUI打不开 | 多个文件 | sys.path缺失/PYTHONPATH未设置 |
| 2026-07-15 | 弹确认窗口 | control-center.html | 后端返回HTML而非JSON |
| 2026-07-15 | 编码问题 | 启动导航.bat | 缺少chcp 65001，中文乱码 |

## 第四部分：系统功能清单（全部功能一览）

### 子系统（6个）
- lottery  - 彩票预测系统     [gui/main_window.py]  - 状态：正常
- football - 足彩分析系统     [jinshuiyao/football_gui.py] - 状态：正常
- stock    - 股票分析系统     [domains/stock/stock_gui.py] - 状态：正常
- fund     - 基金分析系统     [domains/fund/fund_gui.py] - 状态：正常
- music    - 音频处理系统     [audio_toolkit.py] - 状态：正常
- creator  - 创作者工具箱     [domains/creator/creator_gui.py] - 状态：正常

### 非域独立模块
- mirofish_gui - 知识库管理系统  [knowledge/mirofish_gui.py] - 状态：正常

### GUI文件（共7个）
| 文件 | 功能说明 | 位置 |
|------|---------|------|
| main_window.py | 彩票主GUI：彩种/引擎/预测/复盘/热度/走势图/足彩入口 | gui/ |
| stock_gui.py | 股票分析GUI：三大指数/K线/指标/选股/数据检测 | domains/stock/ |
| fund_gui.py | 基金分析GUI：净值/指标/推荐/数据检测 | domains/fund/ |
| football_gui.py | 足彩GUI：比赛/预测/AI分析/赔率/Kelly | jinshuiyao/ |
| creator_gui.py | 创作者GUI：6种创作工具统一入口 | domains/creator/ |
| mirofish_gui.py | 知识库GUI：知识卡片/PARA分类/搜索/导入 | knowledge/ |
| audio_toolkit.py | 音频工具箱GUI：转格式/编辑/标准化/裁剪/优化 | 根目录 |

### scripts脚本（共5个）
| 脚本 | 用途 |
|------|------|
| preflight_check.py | 代码修改前前置检查（9项） |
| smoke_test.py | 冒烟测试（10项实测验证） |
| check_env.py | 环境检测/依赖自动安装 |
| daily_fund_monitor.py | 每日基金监控（HTML日报+系统通知） |
| run_football.py | 足彩启动诊断 |

### 测试（共38个文件，726个测试）
| 分类 | 数量 | 说明 |
|------|------|------|
| 根目录测试 | 8 | audit/evolution/health/plugin/safe_json/smart_brain/sync/watchdog |
| unit/单元测试 | 26 | 各模块独立单元测试 |
| integration/集成测试 | 3 | 回测/跨域/股票域 |
| isolation/隔离测试 | 1 | 子系统隔离性 |

### 入口点（共3个）
| 入口 | 启动内容 |
|------|---------|
| main.py | 预加载+调度器+文件监控+导航服务器+彩票GUI |
| 启动导航.bat | 端口检查+导航服务器（guide_server.py）+浏览器控制台 |
| guide_server.py | HTTP导航服务器（端口18888）+所有子系统启动按钮 |

### 审计日志与监控
- change_audit.log - 变更审计日志
- smoke_test.log - 烟雾测试结果日志
- selfcheck.log - 启动自检日志
- err_log/ - 错误日志目录
- fund_reports/ - 基金日报HTML文件
- test_reports/ - 测试报告HTML文件

### 已知问题
- [ ] control-center.html底部"变更审计日志"链接指向change_audit.log（已修复）
- [ ] 无 - 目前无已知未修复问题
