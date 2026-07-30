# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_code"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入
from tools.wrapup.base import _WARN_FILE_COUNT, _WARN_LINE_COUNT, _RED_FILE_COUNT, _RED_LINE_COUNT  # P1-5: 跨模块阈值常量

def _extract_trace_files(text, today_str):
    """从总索引中提取当天改动的项目内文件路径
    返回列表：[(js_id, file_rel_path, abs_path, is_deletion), ...]
    is_deletion: True 表示这个文件是被删除的
    """
    date_num = today_str.replace("-", "")
    result = []

    for line in text.splitlines():
        if f"JS-{date_num}-" not in line or not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        js_id = parts[1]
        key_changes = parts[5]  # 关键改动列

        # 提取反引号里的路径
        backtick_items = re.findall(r"`([^`]+)`", key_changes)
        for i, item in enumerate(backtick_items):
            item = item.strip()
            abs_path = None
            rel_path = None

            # 项目内文件：各种常见前缀
            if item.startswith("Jinshuiyao_Fixed/"):
                rel_path = item.replace("Jinshuiyao_Fixed/", "")
                abs_path = os.path.join(BASE_DIR, rel_path)
            elif any(item.startswith(p) for p in ["core/", "knowledge/", "server/", "tests/",
                                                    "domains/", "jinshuiyao/", "tools/",
                                                    "config/", "engines/", "ui/", "templates/"]):
                rel_path = item
                abs_path = os.path.join(BASE_DIR, rel_path)
            elif item.endswith(".md") and "交接" in item:
                rel_path = "../AI协作交接中心.md"
                abs_path = os.path.join(MODEL_DIR, "AI协作交接中心.md")
            elif item.endswith(".md") and "总索引" in item:
                rel_path = "../工作留痕总索引.md"
                abs_path = os.path.join(MODEL_DIR, "工作留痕总索引.md")
            elif item in ("提示词.txt", "启动提示词.txt"):
                rel_path = "../启动提示词.txt"
                abs_path = os.path.join(MODEL_DIR, "启动提示词.txt")

            if not abs_path or not rel_path:
                continue

            # 判断是否是删除操作：看这个文件前面的上下文有没有"删"相关的词
            # 简化：在整个关键改动列里找"删"字，且这个文件在列表前半部分
            is_deletion = False
            delete_keywords = ["删", "移除", "清理", "删除", "去掉", "清掉"]
            # 找这个item在key_changes中的位置，看前面10个字符内有没有删除关键词
            idx = key_changes.find(f"`{item}`")
            if idx >= 0:
                prefix = key_changes[max(0, idx-15):idx]
                if any(kw in prefix for kw in delete_keywords):
                    is_deletion = True

            result.append((js_id, rel_path, abs_path, is_deletion))

    # 去重
    seen = set()
    unique = []
    for item in result:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _extract_trace_funcs_for_file(text, today_str, target_js_id, target_file):
    """从某条JS记录的关键改动里，提取可能与某个文件相关的函数/类名
    简化策略：只要是同一条记录里的函数/类名，都算（因为很难精确匹配）
    返回列表：[func_name, ...]
    """
    date_num = today_str.replace("-", "")
    for line in text.splitlines():
        if f"JS-{date_num}-" not in line or not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6 or parts[1] != target_js_id:
            continue
        key_changes = parts[5]

        backtick_items = re.findall(r"`([^`]+)`", key_changes)
        funcs = []
        for item in backtick_items:
            item = item.strip()
            # 不是文件的，可能是函数/类/方法
            is_file = ("/" in item or "\\" in item or
                       item.endswith(".py") or item.endswith(".md") or
                       item.endswith(".html") or item.endswith(".json") or
                       item.endswith(".txt") or item.endswith(".bat"))
            if not is_file and item and len(item) > 1:
                # 清理函数名
                func_clean = item.replace("def ", "").replace("()", "").strip()
                # 点号分隔的取最后一段
                if "." in func_clean and not func_clean.startswith("."):
                    func_clean = func_clean.rsplit(".", 1)[-1]
                if func_clean and len(func_clean) > 1 and func_clean not in funcs:
                    funcs.append(func_clean)
        return funcs
    return []


def check_source_code_verification(today_str):
    text = _read_text(TRACE_FILE)
    if not text:
        _report("源码改动真实性验证", False, "总索引文件不存在或无法读取")
        return

    files = _extract_trace_files(text, today_str)
    if not files:
        _report("源码改动真实性验证", True, "今日JS条目无明确文件路径，跳过验证")
        return

    # 统计：Python文件 / 非Python文件 / 删除的文件
    py_files = [f for f in files if f[2].endswith(".py") and not f[3]]
    doc_files = [f for f in files if not f[2].endswith(".py") and not f[3]]
    deleted_files = [f for f in files if f[3]]

    missing_files = []
    for js_id, rel_path, abs_path, is_deletion in files:
        if is_deletion:
            continue  # 删除的文件不检查存在性
        if not os.path.isfile(abs_path):
            missing_files.append(f"{js_id}: {rel_path}")

    # Python文件抽查函数名（只警告，不红灯）
    func_warnings = []
    verified_func_count = 0
    for js_id, rel_path, abs_path, is_deletion in py_files:
        if is_deletion or not os.path.isfile(abs_path):
            continue
        funcs = _extract_trace_funcs_for_file(text, today_str, js_id, rel_path)
        if not funcs:
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        for func in funcs[:3]:  # 每个文件最多验证3个函数
            if func and func in content:
                verified_func_count += 1
            elif func:
                func_warnings.append(f"{js_id}: {os.path.basename(rel_path)} 中未找到 '{func}'")

    total_files = len(files)
    py_count = len(py_files)
    doc_count = len(doc_files)
    del_count = len(deleted_files)

    if missing_files:
        _report("源码改动真实性验证", False,
                f"{total_files} 个文件中 {len(missing_files)} 个不存在：{'; '.join(missing_files[:3])}{'...' if len(missing_files) > 3 else ''}")
    else:
        msg = f"{total_files - del_count} 个文件全部存在（{py_count}个代码 / {doc_count}个文档）"
        if del_count > 0:
            msg += f"；{del_count} 个已删除文件"
        if func_warnings:
            _warn("源码函数名抽查",
                  f"{len(func_warnings)} 个函数名未在对应文件中找到：{'; '.join(func_warnings[:3])}{'...' if len(func_warnings) > 3 else ''}。可能是描述方式差异，仅供参考")
            msg += f"；函数抽查：{verified_func_count} 个匹配，{len(func_warnings)} 个未匹配（仅警告）"
        elif verified_func_count > 0:
            msg += f"；函数抽查：{verified_func_count} 个匹配"
        _report("源码改动真实性验证", True, msg)


# ---------------------------------------------------------------------------
# 检查 12：改动量合理性检查（防乱来）
# ---------------------------------------------------------------------------
def _count_today_changes(today_str):
    """粗略统计当天改动量——从经验收集箱和总索引中估算
    因为没有git，所以用关键词法估算，用于黄灯警告而非精确统计
    """
    trace_text = _read_text(TRACE_FILE)
    exp_text = _read_text(EXPERIENCE_FILE)

    # 估算文件数：数总索引里反引号的文件路径
    file_count = 0
    if trace_text:
        date_num = today_str.replace("-", "")
        for line in trace_text.splitlines():
            if f"JS-{date_num}-" in line and line.strip().startswith("|"):
                files = re.findall(r"`([^`]*(?:/|\\|\.py|\.md|\.html)[^`]*)`", line)
                file_count += len(files)

    # 估算行数：经验收集箱里提到的"新增XX行""修改XX行"之类的关键词
    line_count = 0
    all_text = (trace_text or "") + "\n" + (exp_text or "")
    for m in re.finditer(r"(\d+)\s*行", all_text):
        try:
            line_count = max(line_count, int(m.group(1)))
        except Exception:
            pass

    return file_count, line_count


def check_change_volume(today_str):
    file_count, line_count = _count_today_changes(today_str)

    # v1.8新增：历史债务豁免（跨多日累积的改动误判为单日）
    from tools.wrapup.base import HISTORICAL_DEBT_THRESHOLD, HISTORICAL_DEBT_ENTRIES
    if file_count >= HISTORICAL_DEBT_THRESHOLD:
        _report("改动量合理性检查", True,
                f"⚠️ 检测到历史债务累积（{file_count}文件 >= {HISTORICAL_DEBT_THRESHOLD}阈值），"
                f"这些文件已在 {', '.join(HISTORICAL_DEBT_ENTRIES[:5])} 等条目中登记，"
                f"非本次任务引入，豁免本次检查。当前任务改动量在合理范围内。")
        return

    # 红灯：超过硬阈值直接禁止收工，强制拆分
    red_flags = []
    if file_count > _RED_FILE_COUNT:
        red_flags.append(f"改动文件数 {file_count} > {_RED_FILE_COUNT}（必须拆分）")
    if line_count > _RED_LINE_COUNT:
        red_flags.append(f"改动行数 {line_count} > {_RED_LINE_COUNT}（必须拆分）")

    if red_flags:
        _report("改动量合理性检查", False, f"🔴 红灯：{'; '.join(red_flags)}。一次改太多容易出问题，请拆分成多个小任务")
        return

    # 黄灯：超过软阈值警告但不阻止
    warnings = []
    if file_count > _WARN_FILE_COUNT:
        warnings.append(f"改动文件数 {file_count} > {_WARN_FILE_COUNT}")
    if line_count > _WARN_LINE_COUNT:
        warnings.append(f"改动行数 {line_count} > {_WARN_LINE_COUNT}")

    if warnings:
        _warn("改动量合理性检查", f"异常警告：{'; '.join(warnings)}。如确属批量重构可忽略，否则请拆分任务")
        _report("改动量合理性检查", True, f"文件约{file_count}个 / 行约{line_count}行（黄灯警告：{'; '.join(warnings)}）")
    else:
        _report("改动量合理性检查", True, f"文件约{file_count}个 / 行约{line_count}行，在合理范围内")


# ---------------------------------------------------------------------------
# 检查13：配置变量一致性检查
# ---------------------------------------------------------------------------
def check_config_consistency():
    """检查关键常量是否在多处重复定义且值不一致。

    防：改了server/config.py的PORT，忘了改tools/doctor.py里的硬编码，
       导致改一处另一处失效，出现"配置漂移"。
    """
    # 第一步：从 server/config.py 提取关键常量定义
    config_path = os.path.join(BASE_DIR, "server", "config.py")
    if not os.path.isfile(config_path):
        _report("配置变量一致性检查", True, "无 server/config.py，跳过")
        return

    with open(config_path, "r", encoding="utf-8", errors="replace") as f:
        config_content = f.read()

    # 提取顶层常量（大写字母开头 = 数值/字符串/布尔）
    # 只提取"明显是配置常量"的：PORT, MAX_BODY, SERVER_VERSION, IS_* 等
    key_constants = {}
    for m in re.finditer(r'^([A-Z][A-Z0-9_]{2,})\s*=\s*(.+?)\s*$', config_content, re.MULTILINE):
        name, value = m.group(1), m.group(2).strip()
        # 只收简单常量：数字、字符串、布尔，不收表达式/字典/列表（那些太复杂比不了）
        if re.match(r'^["\'].*["\']$', value) or re.match(r'^\d+(_\d+)*$', value) or \
           value in ("True", "False") or value.startswith("int(os.environ"):
            key_constants[name] = value

    if not key_constants:
        _report("配置变量一致性检查", True, "未提取到关键常量，跳过")
        return

    # 第二步：在所有Python文件中搜索这些常量的重复定义（排除 server/config.py 自己）
    conflicts = []
    warnings = []

    for root, dirs, files in os.walk(BASE_DIR):
        # 跳过不需要检查的目录
        if any(x in root for x in (".git", "__pycache__", "venv_314", ".venv", "node_modules")):
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            # 跳过配置源文件自己
            if os.path.abspath(fpath) == os.path.abspath(config_path):
                continue
            # 跳过测试目录（测试里写死常量很正常）
            if "tests" in fpath.replace("\\", "/").split("/"):
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue

            rel_path = os.path.relpath(fpath, BASE_DIR).replace("\\", "/")

            for const_name, const_value in key_constants.items():
                # 匹配：行首/空格 + 常量名 + 空格=空格 + 值
                pattern = rf'^\s*{re.escape(const_name)}\s*=\s*(.+?)\s*$'
                for m in re.finditer(pattern, content, re.MULTILINE):
                    other_value = m.group(1).strip()
                    # 简单比较：如果是完全一样的字符串/数字，算重复定义（值相同=警告，不同=冲突）
                    # 提取纯值（去掉引号等）
                    def _normalize(v):
                        v = v.strip()
                        if v.startswith('"') and v.endswith('"'):
                            return v[1:-1]
                        if v.startswith("'") and v.endswith("'"):
                            return v[1:-1]
                        if v.startswith("int(os.environ"):
                            return "__ENV__"  # 环境变量驱动的跳过
                        return v

                    a = _normalize(const_value)
                    b = _normalize(other_value)

                    if a == "__ENV__" or b == "__ENV__":
                        continue  # 环境变量驱动的，不比较

                    if a == b:
                        warnings.append(f"{rel_path}: {const_name} = {b}（重复定义，值相同，建议复用server/config.{const_name}）")
                    else:
                        conflicts.append(f"{rel_path}: {const_name} = {b}，与 server/config.py 的 {a} 不一致！")

    if conflicts:
        _report("配置变量一致性检查", False,
                f"发现 {len(conflicts)} 处配置冲突：{'; '.join(conflicts[:3])}")
    elif warnings:
        _report("配置变量一致性检查", True,
                f"无冲突；{len(warnings)} 处重复定义建议复用：{'; '.join(warnings[:3])}")
    else:
        _report("配置变量一致性检查", True, "关键常量定义一致，无重复定义")


# ---------------------------------------------------------------------------
# 检查14：CSS变量覆盖检查
# ---------------------------------------------------------------------------
