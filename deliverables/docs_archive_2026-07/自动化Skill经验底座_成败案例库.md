# 自动化 Skill 经验底座 · 五维作战手册

> **用途**：开发「金水谣」自动化 Skill 前的必读参考。把成功做法、失败教训、关联工具、设计模式、流程规范固化成可检索底座，让每一次新 Skill 开发都有据可依，少踩坑。
>
> **来源诚实标注**：
> - 外部理论/案例：引自 2026-07-26 两轮 WebSearch 调研（自愈架构 Zylos/penchan/antigravity、Anthropic Skill 开放标准、pre-commit 企业实践、GraphRAG 衰减修复 Neo4j/arXiv）；**第三轮 WebSearch（JS-20260726-46）聚焦 API 密钥安全管理**：GitHub/Claude 官方/DEV Community/PowerShell Security 等 5+ 来源，提炼"分服务隔离 + 文件存储 + 剪贴板残留风险 + ACL 收紧"等范式。
> - 失败案例主体：来自本项目「服务存活看门狗」(JS-20260726-14) 开发过程的**亲历真实踩坑**。
> - 行业公认模式：agent / 运维自动化领域经典故障画像（结合领域知识归纳）。
> - 本手册本身 = 记忆蒸馏(S1) + Skill 结构(S4) 的落地产物。

---

## 维度一 · 案例层（成败）

### ✅ 成功案例（照着做）

- **S1. 三层经验管线**（hotmolts）：日更日志(L1) → MEMORY 规则(L2) → Skill(L3)，蒸馏比约 40×；L1 >30 天必须归档删。对应落地：`jinshuiyao-memory-distill` + 本手册。
- **S2. 主动遗忘 > 被动保留**（botlearn）：记忆管理好的 agent 是遗忘得最聪明的；按「决策价值」而非时间组织。对应：蒸馏按价值提取，近 30 天绝不碰。
- **S3. 双层级探活看门狗**（lobehub / php.cn / penchan）：只看 `/health` 会漏「假死」（进程在、HTTP 正常、但已 20 分钟无输出）。必须 + 功能端点 + 超时。对应：看门狗两层级探活。
- **S4. Skill 结构 + 安全边界**（command-creator / Anthropic 规范）：frontmatter(name+description) + 步骤；不可逆操作须显式授权。对应：每个 SKILL.md 写铁律+验证+安全边界。
- **S5. 看门狗三道安全闸**（本项目亲历验证）：10 分钟冷却 + 连败 3 次熔断 + 全程留痕。**外部佐证(antigravity)**：追逐 100% 自动恢复会让看门狗逻辑膨胀并引入自身 bug，建议在 ~87% 覆盖率处划线，剩余交人工。
- **S6. 混合自愈架构**（Zylos）：进程监督层(systemd/PM2) + 应用自愈层(检查点/熔断/重试) + 健康监控层。进程监督处理灾难性故障，应用层处理逻辑故障。→ 我们的看门狗是「进程监督层」，已对齐业界主流。
- **S7. 三级升级 + 重启防循环**（Datadog/cloudnative）：auto-heal(重启/回滚) → alert-and-propose(人批) → escalate(呼起 on-call)。**关键安全机制：若进程震荡快于冷却窗口，必须升级而非继续重启**。→ 直接验证 S5 冷却+熔断设计。
- **S8. 有界自主权三阶段**（AWS）：①只读 → ②建议(人批) → ③受管自主权(策略围栏内)。多数团队应长期待在 ① ②。→ 验证 F10 安全边界 + S4。
- **S9. 三层监控频率递增**（penchan）：L1 每 5 分钟 Shell(进程/HTTP/心跳) → L2 每 15 分钟廉价 LLM(Session 死活) → L3 每 60 分钟(检查点孤儿/上下文溢出)。**L1 负责监控 L2**——监控系统的监控必须零成本，否则 L2 自己挂了没人接得住。→ 对应我们的健康巡检(L1)+决策卡巡检(L2) 频率设计。
- **S10. 密钥分服务隔离 + 文件存储**（2026-07-26 WebSearch 印证）：不同服务商用**不同密钥**（DeepSeek 付费核心 / 硅基流动免费模型省费审查），绝不混用；密钥存仓库外 `~/.jinshuiyao-secrets/` + `.gitignore` 兜底屏蔽，代码侧 `open().read()` 读取。外部同一结论：Separate API keys per service + never hardcode in source。对应落地：`set_api_keys.ps1` / `set_api_keys.bat`（JS-20260726-46）。
- **S11. 密钥写入七项安全加固范式**（本项目亲历提炼）：①剪贴板容错读取(try/catch 回退手动粘贴) ②`sk-` 形态校验(非前缀警告+`y`确认) ③覆盖前确认 ④写前脱敏预览 ⑤ACL 600 仅当前用户可读写 ⑥写后回读校验一致才报 OK ⑦立即清空剪贴板。外部佐证(Claude 官方/DEV Community)：剪贴板残留会被 AI 编程助手发往外部服务器——印证 ⑦ 必要。对应落地：`set_api_keys.ps1`。

### ❌ 失败案例（绝不做）

| 编号 | 坑 | 红线 |
|---|---|---|
| F1 | netstat 中文代码页解码崩溃 `0xbb` | 解析系统命令输出一律 `errors='ignore'`（或 `encoding='mbcs'`），绝不裸 `text=True` |
| F2 | PID 识别失败 → 重启靠别人兜底 | 看门狗必须**自己**完成 识别→kill→拉起→验证 闭环，不外包给被重启对象 |
| F3 | 误把 5 个历史遗留文件卷进提交 | 提交前 `git status` 核对 + 精确 `git add`，不卷无关文件 |
| F4 | 总索引编号冲突（12/13 被占） | 登记前 `grep` 最新编号，留安全空位 |
| F5 | pre-commit 拦纯文档提交（历史 P0） | 铁律⑥：非用户授权不 `--no-verify`；P0 单独排期修 |
| F6 | 单点探活漏掉假死 | 功能端点 + 超时双重探活；超时即不健康 |
| F7 | cron 自动删除误删根目录 | 白名单 + `--dry-run` 先打印待删清单；绝不 `rm -rf` 含变量路径 |
| F8 | 重启循环/看门狗自噬 | 冷却 + 熔断，熔断后告警非死循环 |
| F9 | 知识库清理致不一致（sources 失配） | 写共享 JSON 先重算派生字段；加锁（RLock 防重入死锁） |
| F10 | 自动化权限过大越权 | 最小权限；外部动作只读+告警，不可逆显式授权 |
| F11 | 监控 LLM 幻觉工具调用反噬（penchan Prohibition-First） | 监控链路禁用自主工具调用，只读探测；告警不自动执行修复 |
| F12 | 心跳文件半写导致幽灵恢复（antigravity） | 状态文件用 tmp-then-rename 原子写；读方对部分写入做重试/容错 |
| F13 | 告警重入轰炸（antigravity） | 同类告警限流（如 10 分钟内至多 1 次），避免一次性刷屏 |
| F14 | 把说明文字当密钥写入（JS-20260726-45 亲历） | 用户双击时剪贴板里是中文说明而非 `sk-` 密钥，写出 1058 字符错误内容；**必须 `sk-` 形态校验 + 覆盖前确认**，写前预览脱敏 |
| F15 | 剪贴板残留泄密（外部 WebSearch 点名） | 写后立即清空剪贴板；密钥绝不长期驻留剪贴板 |
| F16 | PowerShell 无 BOM → GBK 中文乱码崩（老坑复发 JS-20260726-46） | `.ps1` 强制 UTF-8 BOM(EF BB BF)，Write 工具默认无 BOM 须手动加 |
| F17 | `Get-Clipboard` 无头/自动化环境抛异常致脚本崩 | 剪贴板读取包 try/catch 回退到交互输入，绝不裸调用 |

### 🔧 开发自动化 Skill 七条铁律

1. 先摸现状再写码（环境/端口/路径）。
2. 探活双层级（`/health` + 功能端点 + 超时）。
3. 自愈会认怂（冷却 + 熔断 + 留痕，~87% 划线）。
4. 删除白名单 + dry-run。
5. 闭环自己完成（不依赖被操作对象兜底）。
6. 提交要精确（`git status` + 精确 `git add` + 写实 commit）。
7. 登记要查重（总索引先 `grep` 最新编号）。

---

## 维度二 · 工具层（关联技能 / 框架）

### 本机已装、可直接借力的 skills
| 技能 | 怎么用上 |
|---|---|
| **skill-creator** | 创建 Skill 的标准指南（Anthropic 官方「创建 Skill 的 Skill」）。下次说"开发一个 Skill"会被触发，必读 |
| **skill-scanner / skill-vetter** | 技能安全扫描/审查，对应 F10 安全边界，建 Skill 前过一遍防越权 |
| **github** | GitHub CLI，直接支撑「收工 git 门禁」① |
| **macro-monitor** | 每日定时推送范式，cron 写法参考（照搬调度结构） |
| **diagnose** | 诊断循环（复现→最小化→假设→插桩→修复→回归），开发踩坑时的方法论 |
| **tencentos-expert** | 运维诊断，关联看门狗/巡检 |
| **web-access / tencent-docs** | 若 Skill 需抓网页 / 把日报推送到云文档 |

### 外部框架 / 工具（按用途）
- **调度层**：cron / Windows 任务计划 / systemd timers / supervisor / K8s CronJob。
- **自愈层**：Circuit Breaker（本项目已有 `CircuitBreakerRegistry`）、Retry with backoff（wait = base×2^n + jitter）、Bulkhead 隔离。
- **可观测**：liveness/readiness 探针、Prometheus 指标、alerting 限流。
- **安全围栏**：OPA/Kyverno 策略即硬停止、AWS Cedar、最小权限身份、审计全留痕。
- **版本/质量门**：pre-commit 框架（detect-private-key / check-added-large-files / detect-secrets）、Husky、Lefthook。
- **Skill 生态**：Anthropic Skill 规范（2025-12 开放标准，33+ 产品采纳：Claude Code/Codex/Copilot/Cursor/Kiro…）。

### Skill 开发四层结构（Anthropic 规范，直接套用）
1. **Trigger 层**：name + description（模型驱动激活，description 写祈使句 + 触发关键词，≤1024 字）。
2. **Instruction 层**：写**序列**而非人设；用「第一步…第二步…」而非「请认真分析」。
3. **Resource 层**：重内容放 `references/` `scripts/` `templates/`，SKILL.md 主体 ≤500 行（三层渐进加载：L1 name+desc ~50-100 tok，L2 body <5000 tok，L3 资源按需 → 省 ~90% 上下文）。
4. **Validation 层**：边界情况处理 + Few-shot 示例 + 可机器校验的输出契约。
> **Skill-Creator 哲学**：①泛化而非过拟合；②解释「为什么」而非堆砌 ALWAYS/NEVER；③重复出现的辅助脚本抽到 `scripts/`。

---

## 维度三 · 模式层

### 触发与调度模式库
| 模式 | 适用 | 雷区 |
|---|---|---|
| 周期(cron) | 日报/巡检/蒸馏 | 最短粒度受框架限制（automation 最小 HOURLY，更密需 Windows 计划任务兜底） |
| 事件 | 文件变更/请求到达 | 事件丢失 → 漏触发，需兜底周期扫 |
| 变更后 | 改码/改提示词 | 误触发（无关改动），需白名单路径 |
| 手动 | 紧急恢复/诊断 | 忘了跑 → 留痕缺失 |

### 安全模型矩阵（动作 → 权限 → 是否需显式授权）
| 动作类型 | 权限等级 | 授权要求 |
|---|---|---|
| 只读探测（探活/读日志/查状态） | 低 | 无需授权，默认可跑 |
| 生成报告/推送通知 | 低 | 无需授权 |
| 重启服务/拉起进程 | 中 | 冷却+熔断内自动；越界暂停告警 |
| 写文件/改配置（非入口） | 中 | 白名单路径 + dry-run |
| 改启动入口/删旧日志/下单/发信 | 高 | **必须显式授权**（人批一次） |
| 改业务代码/删库 | 禁止 | 绝不自动，走人工 PR |

### 可观测性 / 健康度度量（怎么判断一个 Skill 是否健康）
- **恢复成功率**：无人工介入恢复比例（目标 ~87%，不追 100%）。
- **检测时延(time-to-detection)**：从故障到告警的时长。
- **优雅降级率**：部分失败不整崩的比例。
- **误报/漏报**：假阳性（幽灵恢复 F12）、假阴性（假死漏检 F6）。
- **审计完整性**：每次动作留痕（谁/何时/为什么/结果）。

### 三层级升级与重启防循环（S7 + S5）
auto-heal → alert-and-propose → escalate。**震荡快于冷却窗口即升级，不硬重启**。

---

## 维度四 · 骨架层（可复用代码模板）

### 骨架 A · 看门狗探活/重启（已落地 `scripts/watchdog_service.py`）
- 双层级探活：`/health` + 功能端点，均设超时。
- 安全重启：识别 PID → `taskkill` → `py -3.14` DETACHED 拉起 → 验证恢复（≤40s）。
- 安全闸：冷却期(600s) + 连败 3 次熔断 + 限流告警(10min/类) + 状态文件**原子写**(tmp→rename)。

### 骨架 B · 记忆蒸馏（待落地 `jinshuiyao-memory-distill`）
- 扫描 `.workbuddy/memory/YYYY-MM-DD.md`，算距今天数。
- `>30` 天：按「决策价值」提取增量 → 合并进 MEMORY.md（尊重既有章节，只补不重写）。
- **安全闸**：近 30 天绝不碰；提取后先 dry-run 列清单，确认才删；绝不删 MEMORY.md。

### 骨架 C · 端点巡检（已落地 `jinshuiyao-frontend-health-probe`）
- `netstat` 查 LISTENING + `GET /health` 须 200，否则报「server 未跑，跳过」。
- urllib 批量打路由表全部端点，抓 HTTP 码 + 响应片段。
- 分类：500+AttributeError → GuideHandler 缺方法；无响应 → 死锁改 RLock。只读，绝不改码。

### 骨架 D · git 门禁 dry-run（待建 ①）
- 到点检查 `git status --short` 是否非空且今日无 commit。
- 非空 → 生成「待提交清单 + 精确 git add 命令 + 写实 commit 模板」，**只提醒不自动提交**。
- 顺带跑 `detect-secrets` 类检查（F5/P0 隔离：历史 P0 单独列，不阻断提醒）。

### 骨架 E · 多密钥一键写入（已落地 `set_api_keys.ps1` / `set_api_keys.bat`，JS-20260726-46）
- 菜单式 `-Target` 预选（deepseek / siliconflow），小白双击 bat → 选 1/2 → 粘贴密钥回车；硅基流动标注「免费模型·省费审查」用途。
- 七项加固落地：剪贴板容错 / `sk-` 形态校验 / 覆盖确认 / 脱敏预览 / ACL 600 / 回读校验 / 清空剪贴板。
- 安全闸：写前确认 + 脱敏预览防误写(F14)；ACL 仅当前用户可读写；绝不碰其他文件。
- 编码：UTF-8 BOM 强制（防 F16）；bat 为薄壳 `powershell -File`，不绕过加固。

---

## 维度五 · 流程层

### 开发前 Checklist
- [ ] 确认触发源（周期/事件/变更后/手动）与运行环境（`py -3.14` vs venv）。
- [ ] 确认端口/路径/权限，读回现有相关脚本与 MEMORY 铁律。
- [ ] 判定是否值得做 Skill：≥3 条为真才做——重复出现 / 稳定流程 / 做坏代价大 / 可验证。
- [ ] 列安全边界：哪些动作只读、哪些需授权、熔断/冷却阈值。

### 九步元流程（详见 `jinshuiyao-skill-dev` Skill）
摸现状 → 评价值 → 写 SKILL.md(四层结构) → 落脚本骨架 → 自测(含真实重启/误删演练) → 接 automation 调度 → 登记总索引 → 更新 MEMORY §12 → 写当日 memory + git commit。

### 回滚与应急手册
- 看门狗误重启：手动 `py -3.14 scripts/watchdog_service.py --check-only` 确认；暂停用 `automation_update(mode=update,status=PAUSED)`。
- 蒸馏误删：MEMORY.md 有备份章节；暂停蒸馏 Skill，从 git 历史找回日更文件。
- 提交失控：立即 `git reset --soft HEAD~1` 撤销，重新精确 `git add`。

---

## 与本项目的映射（更新版）

| 已有/待建 Skill | 直接消化的教训 / 模式 |
|---|---|
| 看门狗 (已建) | S3/S5/S6/S7/S8/F1/F2/F6/F8/F11/F12/F13 |
| 记忆蒸馏 (已建) | S1/S2/F7（>30天才删，安全闸） |
| 启动提示词同步 (已建) | F10/S8（只读 diff，绝不改入口） |
| 决策卡巡检 (已建) | F9（一致性校验）+ S9(L2 频率) |
| 健康巡检 (已建) | S3/S9/F6/F11 |
| **密钥管理脚本 (已建, 非 Skill 工具)** | **S10/S11 + F14/F15/F16/F17 + 骨架 E**（双击 bat 写 DeepSeek/硅基流动密钥，集思广益范式落地） |
| **① 收工 git 门禁 (待建)** | **F3/F5 + 维度二 pre-commit + 骨架 D** |
| **② 彩票数据源健康日报 (待建)** | S3/S9（复用 sources-health 面板）/ F6 |
| **③ GraphRAG 三元组修复 (待建)** | **F9 + 维度二 GraphRAG 衰减修复（定期调和/重算派生/加锁）** |

> 待建项按推荐顺序：① git 门禁（消化你亲历的 F3/F5 痛点，低风险高回报）→ ② 数据源日报（复用已建面板）→ ③ 三元组修复（底层一致性，等服务稳定后做）。
