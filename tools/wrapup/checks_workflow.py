# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_workflow"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入

def check_handoff(today_str):
    text = _read_text(HANDOFF_FILE)
    if not text:
        _report("交接中心今日有登记", False, "文件不存在或无法读取")
        return
    short = today_str[5:]  # MM-DD
    found = today_str in text or short in text
    if not found:
        _report("交接中心今日有登记", False,
                f"未找到 {today_str}，请在「已完成的优化」表格新增一行")
        return

    # 内容质量校验：找到日期所在的表格行，检查是否有实质内容
    # 提取今日登记的表格行
    date_num = today_str.replace("-", "")
    # 匹配表格行中包含日期或编号的行
    table_rows = []
    for line in text.splitlines():
        if line.strip().startswith("|") and (today_str in line or short in line or f"JS-{date_num}" in line or f"T" in line and "已完成" in line):
            # 排除表头行
            if "---" not in line and "序号" not in line and "优化项" not in line:
                table_rows.append(line)

    if not table_rows:
        # 可能在其他格式中，降级为只检查日期存在
        _report("交接中心今日有登记", True, f"找到日期 {today_str}（未检测到表格行，已通过最低标准）")
        return

    # 检查每行是否有实质内容（至少有一定长度，且不是只有日期）
    empty_rows = []
    for i, row in enumerate(table_rows):
        # 去掉分隔符和空格，检查有效内容长度
        content = re.sub(r"[|\s]", "", row)
        if len(content) < 20:  # 太短可能是糊弄
            empty_rows.append(f"第{i+1}行")

    if empty_rows:
        _report("交接中心今日有登记", False,
                f"找到 {len(table_rows)} 行登记，但 {len(empty_rows)} 行内容过短（疑似糊弄）：{', '.join(empty_rows[:3])}")
    else:
        _report("交接中心今日有登记", True,
                f"找到 {len(table_rows)} 行登记，内容充实")


# ---------------------------------------------------------------------------
# 检查 2：经验收集箱今日有追加（含内容质量校验）
# ---------------------------------------------------------------------------
_EXP_REQUIRED_FIELDS = ["做了什么", "踩过的坑", "下次注意", "有效方法"]


def _extract_today_experience(text, today_str):
    """从经验收集箱中提取当天的所有经验条目内容"""
    entries = []
    # 匹配 ### YYYY-MM-DD 开头的标题
    pattern = rf"### {re.escape(today_str)}.*?\n(.*?)(?=\n### |\n## |\Z)"
    for m in re.finditer(pattern, text, re.DOTALL):
        entries.append(m.group(1).strip())
    return entries


def check_experience(today_str):
    text = _read_text(EXPERIENCE_FILE)
    if not text:
        _report("经验收集箱今日有追加", False, "文件不存在或无法读取")
        return
    found = today_str in text
    if not found:
        _report("经验收集箱今日有追加", False,
                f"未找到 {today_str}，请按模板追加今日经验条目")
        return

    entries = _extract_today_experience(text, today_str)
    if not entries:
        _report("经验收集箱今日有追加", False, f"找到日期 {today_str} 但无有效条目（空内容糊弄）")
        return

    # 检查每个条目的字段完整性
    incomplete = []
    for i, entry in enumerate(entries):
        missing = [f for f in _EXP_REQUIRED_FIELDS if f not in entry]
        if missing:
            incomplete.append(f"第{i+1}条缺: {','.join(missing)}")

    if incomplete:
        _report("经验收集箱今日有追加", False,
                f"找到 {len(entries)} 条，但字段不完整：{'; '.join(incomplete[:3])}")
    else:
        _report("经验收集箱今日有追加", True,
                f"找到 {len(entries)} 条，4个必填字段全部齐全")


# ---------------------------------------------------------------------------
# 检查 3：工作留痕总索引今日有编号（含内容质量校验）
# ---------------------------------------------------------------------------
_TRACE_REQUIRED_FIELDS = [
    ("改动文件", ["改动文件", "关键改动"]),
    ("验证", ["验证"]),
    ("被否决方案", ["被否决方案"]),
    ("人工介入", ["人工介入触发", "人工介入"]),
    ("成熟度", ["成熟度"]),
]


def check_trace_index(today_str):
    text = _read_text(TRACE_FILE)
    if not text:
        _report("工作留痕总索引今日有编号", False, "文件不存在或无法读取")
        return
    pattern = "JS-" + today_str.replace("-", "")
    if pattern not in text:
        _report("工作留痕总索引今日有编号", False,
                f"未找到 {pattern}-NN 编号，请登记（必含：被否决方案/人工介入/成熟度）")
        return

    count = _extract_today_trace_entries(text, today_str)
    if count == 0:
        _report("工作留痕总索引今日有编号", False, f"找到编号前缀但无有效条目（空内容糊弄）")
        return

    _report("工作留痕总索引今日有编号", True, f"找到 {count} 条 {pattern}-NN 编号")


# ---------------------------------------------------------------------------
# 检查 4：总索引字段完整性校验（防糊弄核心）
# ---------------------------------------------------------------------------
def _extract_today_trace_entries(text, today_str):
    """从总索引中提取当天的所有 JS 条目（表格行 + 下方补录块）"""
    date_short = today_str[5:]  # MM-DD
    date_num = today_str.replace("-", "")  # YYYYMMDD
    pattern = rf"JS-{date_num}-\d+"
    matches = list(re.finditer(pattern, text))
    return len(matches)


def _is_js_in_table(text, js_id):
    """检查某个JS编号是否在表格行中（格式：| JS-XXXXXXX-XX |）"""
    # 匹配表格行：| JS-20260722-01 | ... |
    pattern = rf"\|\s*{re.escape(js_id)}\s*\|"
    return bool(re.search(pattern, text))


def _check_trace_supplement_block(text, js_id):
    """检查某个JS编号是否有补录块（被否决方案 + 人工介入）"""
    has_rejected = False
    has_manual = False

    # 提取所有补录块（以 > **📌 开头，到下一个 ### 或 ## 或空行结束）
    # 补录块格式：> **📌 JS-XXX 补录** 或 > **📌 JS-XXX / YYY 补录**
    supplement_blocks = []
    current_block = []
    in_block = False
    for line in text.splitlines():
        if line.strip().startswith(">") and "📌" in line and "补录" in line:
            if in_block and current_block:
                supplement_blocks.append("\n".join(current_block))
            current_block = [line]
            in_block = True
        elif in_block and line.strip().startswith(">"):
            current_block.append(line)
        elif in_block and not line.strip().startswith(">"):
            if current_block:
                supplement_blocks.append("\n".join(current_block))
            current_block = []
            in_block = False
    if in_block and current_block:
        supplement_blocks.append("\n".join(current_block))

    # 在包含该JS编号的补录块中搜索字段
    for block in supplement_blocks:
        if js_id in block:
            if "被否决方案" in block:
                has_rejected = True
            if "人工介入触发" in block or "人工介入" in block:
                has_manual = True
            # 找到一个包含该编号且有字段的补录块就够了
            if has_rejected and has_manual:
                break

    # 兜底：如果没找到补录块，就在该编号出现位置的上下文里搜（兼容旧格式）
    if not (has_rejected and has_manual):
        m = re.search(re.escape(js_id), text)
        if m:
            start = m.start()
            end_match = re.search(r"\n### |\n## ", text[start + 100:])
            end = start + 100 + end_match.start() if end_match else min(start + 5000, len(text))
            block = text[start:end]

            # 只有在同一个"引用块"（> 开头的连续行）里才算
            in_quote = False
            quote_lines = []
            for line in block.splitlines():
                if line.strip().startswith(">"):
                    in_quote = True
                    quote_lines.append(line)
                elif in_quote and not line.strip().startswith(">"):
                    break
            quote_block = "\n".join(quote_lines)

            if js_id in quote_block:
                if "被否决方案" in quote_block:
                    has_rejected = True
                if "人工介入触发" in quote_block or "人工介入" in quote_block:
                    has_manual = True

    return has_rejected, has_manual


def _extract_js_entry_block(text, js_id):
    """提取含某 JS 编号的整段（### 标题行 + 直到下一个 ###/## 标题前的内容）。

    兼容项目 §二 模板格式：条目以 `### JS-YYYYMMDD-NN | ...` 标题开头，
    其下用 `- **改动文件**：` 等要点子弹记录字段；成熟度常置于标题末管道值。
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("###") and js_id in line:
            start = i
            break
    if start is None:
        return ""
    block = [lines[start]]  # 含标题行（末管道含成熟度）
    for line in lines[start + 1:]:
        if line.startswith("###") or line.startswith("##"):
            break
        block.append(line)
    return "\n".join(block)


def _block_has_field(block, aliases):
    return any(alias in block for alias in aliases)


def check_trace_field_completeness(today_str):
    text = _read_text(TRACE_FILE)
    if not text:
        _report("总索引字段完整性校验", False, "文件不存在或无法读取")
        return

    date_num = today_str.replace("-", "")
    pattern = rf"JS-{date_num}-\d+"
    # 去重，获取唯一编号列表
    js_ids = sorted(set(re.findall(pattern, text)))
    if not js_ids:
        _report("总索引字段完整性校验", True, "今日暂无编号，跳过字段检查")
        return

    # 成熟度兼容：标题行末管道值（verified/draft/open/pending/experimental）
    _MATURITY_TOKENS = ("verified", "draft", "open", "pending", "experimental")

    incomplete_entries = []
    for js_id in js_ids:
        missing = []
        block = _extract_js_entry_block(text, js_id)
        in_table = _is_js_in_table(text, js_id)
        # 表格行存在时，改动文件/验证/成熟度视为已含（旧格式兼容）
        table_covers = ("改动文件", "验证", "成熟度") if in_table else ()

        for label, aliases in _TRACE_REQUIRED_FIELDS:
            if label in table_covers:
                continue
            found = _block_has_field(block, aliases)
            if not found and label == "成熟度":
                head_line = block.splitlines()[0] if block else ""
                if any(tok in head_line for tok in _MATURITY_TOKENS):
                    found = True
            if not found:
                missing.append(label)

        # 被否决方案/人工介入：兼容旧 📌 补录块
        has_rejected, has_manual = _check_trace_supplement_block(text, js_id)
        if "被否决方案" in missing and has_rejected:
            missing.remove("被否决方案")
        if "人工介入" in missing and has_manual:
            missing.remove("人工介入")

        if missing:
            incomplete_entries.append(f"{js_id}缺: {','.join(missing)}")

    if incomplete_entries:
        _report("总索引字段完整性校验", False,
                f"{len(js_ids)} 条中 {len(incomplete_entries)} 条字段不全：{'; '.join(incomplete_entries[:3])}")
    else:
        _report("总索引字段完整性校验", True,
                f"{len(js_ids)} 条 JS 编号，5个必填字段全部齐全")


# ---------------------------------------------------------------------------
# 检查 5：经验收集箱字段完整性校验
# ---------------------------------------------------------------------------
def check_experience_field_completeness(today_str):
    text = _read_text(EXPERIENCE_FILE)
    if not text:
        _report("经验收集箱字段完整性校验", False, "文件不存在或无法读取")
        return

    if today_str not in text:
        _report("经验收集箱字段完整性校验", True, "今日暂无经验，跳过字段检查")
        return

    entries = _extract_today_experience(text, today_str)
    if not entries:
        _report("经验收集箱字段完整性校验", False, "找到日期但无有效经验条目")
        return

    incomplete = []
    for i, entry in enumerate(entries):
        missing = [f for f in _EXP_REQUIRED_FIELDS if f not in entry]
        if missing:
            incomplete.append(f"第{i+1}条缺: {','.join(missing)}")

    if incomplete:
        _report("经验收集箱字段完整性校验", False,
                f"{len(entries)} 条中 {len(incomplete)} 条字段不全：{'; '.join(incomplete[:3])}")
    else:
        _report("经验收集箱字段完整性校验", True,
                f"{len(entries)} 条经验，4个必填字段全部齐全")


# ---------------------------------------------------------------------------
# 检查 6：调度器配置与代码同步
# ---------------------------------------------------------------------------
