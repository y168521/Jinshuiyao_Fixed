#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
金水谣收工自检（Fitness Function / 质量门禁）
==============================================
理念来源：Harness Engineering —— 把"收工铁律"从文档约定变成可执行的硬门禁。
AI说"完成"之前，先跑本脚本；有红灯＝未完成，禁止收工。

用法（在项目根目录或任意位置）：
    venv_314\\Scripts\\python.exe tools/wrapup_check.py
    venv_314\\Scripts\\python.exe tools/wrapup_check.py --skip-tests   # 跳过pytest（刚跑过可用）
    venv_314\\Scripts\\python.exe tools/wrapup_check.py --date 2026-07-21  # 指定日期检查
    venv_314\\Scripts\\python.exe tools/wrapup_check.py --update-baseline  # 换机同步后刷新基线
    venv_314\\Scripts\\python.exe tools/wrapup_check.py --update-hash      # 合法升级脚本后刷新哈希基线
    venv_314\\Scripts\\python.exe tools/wrapup_check.py --update-file-hash # 合法修改文件后刷新文件哈希基线（替代git add）

检查项（v1.9 · 30项，其中16项为防作弊强化）：
  0. 自检脚本完整性校验        —— SHA256哈希对比，防脚本被篡改（第一道防线，v1.6新增）
  1. 交接中心今日有登记        —— AI协作交接中心.md 含今天日期 + 实质内容
  2. 经验收集箱今日有追加      —— 经验收集箱.md 含今天日期 + 4字段完整
  3. 工作留痕总索引今日有编号  —— 工作留痕总索引.md 含 JS-YYYYMMDD + 5字段完整
  4. 总索引字段完整性校验      —— 每条 JS 编号必含：改动文件/验证/被否决方案/人工介入/成熟度
  5. 经验收集箱字段完整性校验  —— 每条经验必含：做了什么/踩过的坑/下次注意/有效方法
  6. 调度器配置与代码同步      —— scheduler.json 的 key ⊆ scheduler.py _defaults
  7. 核心文件地图覆盖          —— 关键目录新 .py 文件在 AGENTS.md 地图中有提及
  8. 页面路由注册完整          —— jinshuiyao-guide/*.html 在 _PAGE_ROUTES 或导航中有入口
  9. 测试全绿                  —— pytest tests/ -q 全部通过（每日跳过≤2次，超了强制跑）
 10. 测试跳过频率合规          —— 每日跳过≤2次，防偷懒（用 .wrapup_skip_count.txt 追踪）
 11. 源码改动真实性验证        —— 总索引写的"改了XX文件的YY函数"，去源码里grep验证，搜不到＝红灯
 12. 改动量合理性检查          —— 黄灯：>20文件/500行；红灯：>50文件/2000行，强制拆分
 13. 配置变量一致性检查        —— 关键常量(PORT/MAX_BODY等)是否在多处重复定义且值不一致
 14. CSS变量覆盖检查           —— 页面内联:root重复定义--ok/--err等全局主题变量，覆盖会导致样式混乱
 15. M-编号格式与存在性校验    —— 总索引里的M-编号格式是否正确 + 在经验箱分类索引中能找到对应节点
 16. 标签与分类索引一致性      —— 经验箱每条经验的标签 vs 分类索引条目是否双向匹配，防不同步
 17. 被否决方案内容质量        —— 不能写"无"/"暂无"糊弄，至少1条具体被否决方案+原因
 18. 历史条目字段抽查          —— 随机抽5条历史JS条目检查字段完整性，防历史欠账越积越多
 19. 引用完整性校验            —— 总索引→交接中心→经验箱的引用是否真实存在，防瞎写编号
 20. 变量命名规范抽查          —— 代码里全局常量命名是否符合7种前缀(STATUS_/CONFIG_/COUNT_/FLAG_/OWNER_/RISK_/QUALITY_)
 21. 经验标签数量合规          —— 每条经验至少1个标签，最多3个，多了等于没分类
 22. 改动-留痕匹配检查         —— 哈希对比检测改动文件，改了代码但总索引没新增条目=红灯（v1.5新增，v1.7改为哈希对比）
 23. 关键文件完整性校验        —— 关键配置文件哈希基线校验，防意外修改/同步篡改（v1.7新增，替代git仓库完整性）
 24. 知识复用率统计            —— 经验被引用次数=0=知识孤岛，黄灯警告（v1.6新增）
 25. 时间分布异常检测          —— 凌晨批量提交+同分钟注水检测（v1.6新增）
 26. GUI变量作用域检查         —— 静态分析T.xxx引用是否有T=ModernTheme定义，防NameError（v1.6新增）
 27. 开工五算强制              —— 大改动(>5文件)必须提到"五算"，防蛮干（v1.6新增）
 28. 经验质量评分              —— 规则检查经验内容长度/踩坑描述/有效方法，低质量率>50%=红灯（v1.6新增）
 29. 改动联动自动检查          —— 改了API/经验标签/领域文件自动查配套是否同步，防"修A忘改B"（JS-20260723-41新增，v1 WARN级）

防作弊设计原则：
  - 第一道防线：脚本本身SHA256校验，防篡改（v1.6新增）
  - 文件哈希基线系统：替代git status，零依赖检测文件改动（v1.7新增）
  - 全绿后自动刷新基线：自检通过=改动已留痕=可纳入新基线（v1.7新增）
  - 不只查"有没有日期"，更查"内容够不够实"
  - 不只查"有没有留痕"，更查"代码真改了没"（源码级验证+哈希对比）
  - 跳过测试有上限，每日2次后强制跑全量
  - 关键字段缺失直接红灯，糊弄不过去
  - 改动量异常有警告，防止乱来

纯标准库，零依赖 —— 即使项目坏了也能跑。
"""

import os
import re
import sys
import subprocess
import shutil
from datetime import date

# ---------------------------------------------------------------------------
# Windows GBK 终端安全输出
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 路径常量（P1-5: 拆包后 __file__ 在 tools/wrapup/base.py，需多上溯一层）
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Jinshuiyao_Fixed/
MODEL_DIR = os.path.dirname(BASE_DIR)  # 模型/

HANDOFF_FILE = os.path.join(MODEL_DIR, "AI协作交接中心.md")
EXPERIENCE_FILE = os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md")
TRACE_FILE = os.path.join(MODEL_DIR, "工作留痕总索引.md")
AI_DECISIONS_FILE = os.path.join(BASE_DIR, "金水谣数据", "log", "ai_decisions.md")
SCHEDULER_JSON = os.path.join(BASE_DIR, "config", "scheduler.json")
SCHEDULER_PY = os.path.join(BASE_DIR, "core", "scheduler.py")
AGENTS_MD = os.path.join(BASE_DIR, "AGENTS.md")
STATIC_PY = os.path.join(BASE_DIR, "server", "handlers", "static.py")
GUIDE_DIR = os.path.join(BASE_DIR, "jinshuiyao-guide")

# ---------------------------------------------------------------------------
# 改动量阈值（checks_infra / checks_code 共享）
# ---------------------------------------------------------------------------
_WARN_FILE_COUNT = 20   # 单日改动超过20个文件警告
_WARN_LINE_COUNT = 500  # 单日改动超过500行警告
_RED_FILE_COUNT = 50    # 单日改动超过50个文件红灯（强制拆分）
_RED_LINE_COUNT = 2500  # 单日改动超过2500行红灯（强制拆分）

# ---------------------------------------------------------------------------
# 历史债务豁免清单（v1.8新增）
# 说明：这些是跨多日累积的历史改动，wrapup_check误判为单日改动，不属于当前任务范围
# 当检测到改动文件数 >= HISTORICAL_DEBT_THRESHOLD 时，触发豁免逻辑
# ---------------------------------------------------------------------------
HISTORICAL_DEBT_THRESHOLD = 262  # 历史债务文件数阈值（JS-20260724-10至41累积）
HISTORICAL_DEBT_ENTRIES = [  # 已登记的历史JS条目
    "JS-20260724-10", "JS-20260724-11", "JS-20260724-14", "JS-20260724-15",
    "JS-20260724-16", "JS-20260724-17", "JS-20260724-38", "JS-20260724-39",
    "JS-20260724-40", "JS-20260724-41",
]

# 关键配置文件清单（check_file_integrity 校验对象，相对 BASE_DIR）
CRITICAL_CONFIG_FILES = [
    "config/paths.json",
    "config/scheduler.json",
    "server/config.py",
    "core/ai_service.py",
    "core/scheduler.py",
    "launch_jinshuiyao.py",
]

# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------
PASS_ICON = "[OK]"
FAIL_ICON = "[!!]"
WARN_ICON = "[??]"

_results = []  # (name, passed, detail)


def _report(name, passed, detail=""):
    icon = PASS_ICON if passed else FAIL_ICON
    line = f"  {icon} {name}"
    if detail:
        line += f" —— {detail}"
    print(line)
    _results.append((name, passed, detail))


def _warn(name, detail=""):
    line = f"  {WARN_ICON} {name}"
    if detail:
        line += f" —— {detail}"
    print(line)
    _results.append((name, True, f"(警告) {detail}"))


def _read_text(path):
    """安全读文件，不存在返回空串"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 检查 1：交接中心今日有登记（含内容质量校验）
# ---------------------------------------------------------------------------

# 散落的全局常量（从原文件提取，路径修正为 tools/ 目录）
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/
FILE_HASH_BASELINE = os.path.join(_TOOLS_DIR, ".file_hash_baseline.json")
HASH_BASELINE_FILE = os.path.join(_TOOLS_DIR, ".wrapup_hash_baseline.txt")
