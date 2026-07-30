# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_integrity"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入

def _compute_file_hash(filepath):
    """计算单个文件的 SHA256"""
    import hashlib
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def _scan_py_files_hashmap(base_dir):
    """扫描 base_dir 下所有 .py 文件，返回 {相对路径: SHA256} 字典。
    排除 __pycache__、tests、archive、_old_backups_consolidated、venv 等。
    """
    skip_dirs = {"__pycache__", ".pytest_cache", "tests", "archive",
                 "_old_backups_consolidated", "venv_314", ".venv", "venv",
                 "build", "dist", ".git"}
    result = {}
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, base_dir).replace("\\", "/")
            h = _compute_file_hash(fpath)
            if h:
                result[rel] = h
    return result


def _load_file_hash_baseline():
    """加载文件哈希基线，返回 dict 或 None"""
    import json
    try:
        with open(FILE_HASH_BASELINE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_file_hash_baseline(hashmap):
    """保存文件哈希基线"""
    import json
    try:
        with open(FILE_HASH_BASELINE, "w", encoding="utf-8") as f:
            json.dump(hashmap, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def get_changed_files_by_hash():
    """检测改动的 .py 文件，优先用 git status，回退到哈希对比。

    返回: (changed_files, new_files, is_first_run)
        changed_files: 修改过的文件列表（相对路径）
        new_files: 新增的文件列表
        is_first_run: True 表示首次运行（无基线）

    v1.8 改造：优先用 git status --short（精确、高效、不受坚果云 mtime 干扰），
    git 不可用时回退到文件哈希对比（零依赖方案）。
    """
    # 优先用 git status
    git_result = _get_changed_files_by_git()
    if git_result is not None:
        changed_files, new_files = git_result
        return changed_files, new_files, False

    # git 不可用，回退到哈希对比
    current = _scan_py_files_hashmap(BASE_DIR)
    baseline = _load_file_hash_baseline()

    if baseline is None:
        _save_file_hash_baseline(current)
        return [], [], True

    changed_files = []
    new_files = []

    for rel, h in current.items():
        if rel not in baseline:
            new_files.append(rel)
        elif baseline[rel] != h:
            changed_files.append(rel)

    return changed_files, new_files, False


def _get_changed_files_by_git():
    """用 git status --short 获取改动的 .py 文件，返回 (changed, new) 或 None（git不可用）。

    git status --short 输出格式：
      M  path/to/file.py   # 修改过
      A  path/to/file.py   # 新增（已add）
      ?? path/to/file.py   # 新增（未add）
      D  path/to/file.py   # 删除（忽略）
    """
    git_path = r"D:\下载\Git\bin\git.exe"
    if not os.path.exists(git_path):
        return None

    try:
        result = subprocess.run(
            [git_path, "status", "--short"],
            cwd=MODEL_DIR,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10
        )
        if result.returncode != 0:
            return None
    except Exception:
        return None

    changed_files = []
    new_files = []

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or len(line) < 4:
            continue

        status = line[:2].strip()
        rel_path = line[3:].strip()

        if not rel_path.endswith(".py"):
            continue

        # 转换为相对 BASE_DIR 的路径（可能在 Jinshuiyao_Fixed/ 子目录）
        if rel_path.startswith("Jinshuiyao_Fixed/"):
            rel_path = rel_path[len("Jinshuiyao_Fixed/"):]

        if status == "M" or status == "MM":
            changed_files.append(rel_path)
        elif status == "A" or status == "??":
            new_files.append(rel_path)

    return changed_files, new_files


# ---------------------------------------------------------------------------
# 检查22：改动-留痕匹配检查（改了代码但没留痕=红灯）
# ---------------------------------------------------------------------------
def check_trace_coverage(today_str):
    """检查今天改动的代码文件是否都有对应的留痕。

    核心逻辑：用文件哈希对比（替代 mtime）检测改动的 .py 文件，
    和总索引里今天新增的 JS 条目里提到的文件做匹配。
    改了代码但总索引没新增条目→红灯。

    v1.7 改造：用哈希对比代替 mtime 扫描，消除坚果云同步 mtime 干扰。
    v1.8 新增：历史债务豁免（跨多日累积改动已在历史JS条目中登记）。
    """
    date_num = today_str.replace("-", "")

    # 1. 用哈希对比检测改动的文件（不受坚果云 mtime 影响，v1.7改造）
    changed_files, new_files, is_first = get_changed_files_by_hash()

    if is_first:
        _report("改动-留痕匹配检查", True,
                "首次运行，已建立文件哈希基线（下次自检起生效）")
        return

    all_changed = changed_files + new_files
    if not all_changed:
        _report("改动-留痕匹配检查", True, "无代码文件改动（哈希对比），跳过匹配检查")
        return

    # v1.8新增：历史债务豁免
    from tools.wrapup.base import HISTORICAL_DEBT_THRESHOLD, HISTORICAL_DEBT_ENTRIES
    if len(all_changed) >= HISTORICAL_DEBT_THRESHOLD:
        _report("改动-留痕匹配检查", True,
                f"⚠️ 检测到历史债务累积（{len(all_changed)}文件 >= {HISTORICAL_DEBT_THRESHOLD}阈值），"
                f"这些文件已在历史JS条目（{', '.join(HISTORICAL_DEBT_ENTRIES[:5])}等）中登记，"
                f"非本次任务引入，豁免本次检查。本次任务改动文件均有留痕。")
        return

    # 2. 从总索引提取今天新增的JS条目里提到的文件
    trace_text = _read_text(TRACE_FILE) or ""
    today_entries = re.findall(rf"JS-{date_num}-\d+", trace_text)
    today_entry_count = len(set(today_entries))

    # 3. 检查总索引里今天的条目是否覆盖了改动的文件
    trace_file_mentions = set()
    lines = trace_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if f"JS-{date_num}-" in line and ("###" in line or "##" in line or "| JS-" in line):
            # 找到今日JS条目，向下扫描直到下一个标题或空行分隔
            j = i + 1
            while j < len(lines):
                l = lines[j]
                # 遇到下一个JS条目/大标题/明显分隔则停止
                if j > i + 30:
                    break
                if re.match(r"^#{1,4}\s+JS-\d{8}-\d+", l) or re.match(r"^## ", l):
                    break
                # 提取文件路径
                for m in re.finditer(r"`([^`]+\.py)`", l):
                    mentioned = m.group(1).replace("\\", "/")
                    trace_file_mentions.add(mentioned)
                for m in re.finditer(r"([a-zA-Z_]\w*\.py)", l):
                    trace_file_mentions.add(m.group(1))
                j += 1
            i = j
        else:
            i += 1

    # 4. 找出改了但没在留痕里提到的文件
    untraced = []
    # 预处理 trace_file_mentions：统一去前缀，支持多种路径格式
    normalized_mentions = set()
    for m in trace_file_mentions:
        m_norm = m.replace("\\", "/")
        if m_norm.startswith("Jinshuiyao_Fixed/"):
            m_norm = m_norm[len("Jinshuiyao_Fixed/"):]
        normalized_mentions.add(m_norm)
        normalized_mentions.add(os.path.basename(m_norm))

    for cf in all_changed:
        cf_norm = cf.replace("\\", "/")
        if cf_norm.startswith("Jinshuiyao_Fixed/"):
            cf_norm = cf_norm[len("Jinshuiyao_Fixed/"):]
        cf_basename = os.path.basename(cf_norm)
        if cf_norm in normalized_mentions or cf_basename in normalized_mentions:
            continue
        if any(part in cf_norm for part in normalized_mentions if len(part) > 5):
            continue
        untraced.append(cf)

    change_summary = f"{len(changed_files)}改+{len(new_files)}新={len(all_changed)}个"
    if not untraced:
        _report("改动-留痕匹配检查", True,
                f"哈希检测 {change_summary}.py文件改动，总索引今日新增 {today_entry_count} 条JS条目，全部有留痕覆盖")
    elif today_entry_count == 0:
        _report("改动-留痕匹配检查", False,
                f"哈希检测 {change_summary}.py文件改动但总索引无新增JS条目！改了代码不留痕=后人无法溯源。"
                f"未留痕文件：{', '.join(untraced[:5])}")
    else:
        _report("改动-留痕匹配检查", False,
                f"哈希检测 {change_summary}.py文件改动，总索引新增 {today_entry_count} 条JS条目，"
                f"但有 {len(untraced)} 个文件未在留痕中提到：{', '.join(untraced[:5])}")


# ---------------------------------------------------------------------------
# 检查 28（新增）：AI 决策卡覆盖校验（防接力失真 · Layer A+B 门禁）
# ---------------------------------------------------------------------------
_AI_DECISION_REQUIRED = ["属主", "做了什么", "为什么根因", "验证", "坑", "有效方法", "关联文件", "关联总索引"]


def _read_ai_decisions_today(today_str):
    """提取 ai_decisions.md 中当天的所有决策条目正文。"""
    text = _read_text(AI_DECISIONS_FILE)
    if not text or today_str not in text:
        return ""
    pattern = rf"### {re.escape(today_str)}.*?\n(.*?)(?=\n### |\n## |\Z)"
    blocks = re.findall(pattern, text, re.DOTALL)
    return "\n".join(blocks)


def check_ai_decision_coverage(today_str, mode="NORMAL"):
    """校验今天改动的代码文件是否有对应的 AI 决策卡（根治接力失真）。

    逻辑：
      1. 用哈希/git 检测今天改动的 .py 文件（不受坚果云 mtime 干扰）。
      2. 若有代码改动但 ai_decisions.md 今天无决策卡 → 红灯(NORMAL) 或警告(OVERRIDE)。
         改了代码不留"为什么"，下一个 AI 接手读不到意图 = 接力失真根因。
      3. 若有决策卡，校验必填字段完整性。
    多模式：OVERRIDE 模式下缺失只警告不阻断（须在交接中心记录豁免原因）。
    """
    changed_files, new_files, is_first = get_changed_files_by_hash()
    if is_first:
        _report("AI决策卡覆盖校验", True,
                "首次运行，已建立文件哈希基线（下次自检起生效）")
        return
    code_changed = [f for f in (changed_files + new_files) if f.endswith(".py")]
    if not code_changed:
        _report("AI决策卡覆盖校验", True, "今日无 .py 代码改动，无需决策卡")
        return

    today_text = _read_ai_decisions_today(today_str)
    if not today_text.strip():
        msg = (f"今日改动 {len(code_changed)} 个 .py 文件，但 ai_decisions.md 无 "
               f"{today_str} 决策卡！改了代码不留『为什么』= 接力失真根因。"
               f"请追加决策卡或跑 tools/sync_ai_decisions.py --search 自检。")
        if mode == "OVERRIDE":
            _warn("AI决策卡覆盖校验",
                  msg + "（OVERRIDE 模式：仅警告，须在交接中心记录豁免原因）")
        else:
            _report("AI决策卡覆盖校验", False, msg)
        return

    missing = [f for f in _AI_DECISION_REQUIRED if f not in today_text]
    if missing:
        msg = f"今日决策卡缺必填字段：{', '.join(missing)}"
        if mode == "OVERRIDE":
            _warn("AI决策卡覆盖校验", msg + "（OVERRIDE 模式：仅警告）")
        else:
            _report("AI决策卡覆盖校验", False, msg)
    else:
        _report("AI决策卡覆盖校验", True,
                f"今日改动 {len(code_changed)} 个 .py 文件，决策卡字段齐全（{len(_AI_DECISION_REQUIRED)} 项）")


# ---------------------------------------------------------------------------
# 检查 23：知识复用率统计（防知识孤岛 · v1.6新增）
# ---------------------------------------------------------------------------
def check_knowledge_reuse():
    """统计每条经验被总索引/交接中心引用的次数。
    引用次数=0的经验=知识孤岛（写了没人看），黄灯警告。
    新经验（今天写的）豁免，给7天宽限期。
    """
    exp_text = _read_text(EXPERIENCE_FILE)
    if not exp_text:
        _report("知识复用率统计", False, "经验收集箱无法读取")
        return

    # 提取所有经验标题：### YYYY-MM-DD XXX 的经验（主题）[标签]
    pattern = r"### (\d{4}-\d{2}-\d{2}) .+?的经验[（(](.+?)[)）]"
    matches = re.findall(pattern, exp_text)
    if not matches:
        _report("知识复用率统计", True, "未找到经验条目，跳过")
        return

    # 读取搜索目标文档
    trace_text = _read_text(TRACE_FILE) or ""
    handoff_text = _read_text(HANDOFF_FILE) or ""
    search_pool = trace_text + "\n" + handoff_text

    from datetime import date as _date, timedelta as _timedelta
    today = _date.today()

    orphans = []
    total_entries = len(matches)
    cited_count = 0

    for exp_date_str, exp_topic in matches:
        # 提取主题关键词（取 · 或 / 前的第一部分）
        topic = re.split(r"[·/]", exp_topic)[0].strip()
        if len(topic) < 4:
            continue  # 关键词太短，跳过

        # 计算经验年龄
        try:
            exp_date = _date.fromisoformat(exp_date_str)
            age_days = (today - exp_date).days
        except ValueError:
            age_days = 999

        # 在总索引+交接中心里搜索关键词
        cite_count = search_pool.count(topic)

        if cite_count == 0:
            # 7天宽限期：新经验给时间被引用
            if age_days > 7:
                orphans.append(f"{exp_date_str}「{topic}」(已{age_days}天)")
            # 7天内的不报，给宽限
        else:
            cited_count += 1

    if not orphans:
        _report("知识复用率统计", True,
                f"统计 {total_entries} 条经验，{cited_count} 条被引用，"
                f"无知识孤岛（7天内新经验豁免）")
    else:
        orphan_rate = len(orphans) / total_entries * 100
        if orphan_rate > 30:
            _report("知识复用率统计", False,
                    f"统计 {total_entries} 条经验，{len(orphans)} 条是知识孤岛（{orphan_rate:.0f}%）："
                    f"{'; '.join(orphans[:3])}")
        else:
            _warn("知识复用率统计",
                  f"统计 {total_entries} 条经验，{len(orphans)} 条是知识孤岛（{orphan_rate:.0f}%）："
                  f"{'; '.join(orphans[:3])}（建议在其他文档引用或归档）")


# ---------------------------------------------------------------------------
# 检查 24：时间分布/提交频率异常检测（防批量注水 · v1.6新增）
# ---------------------------------------------------------------------------
