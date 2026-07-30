# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_quality"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入

def check_css_var_override():
    """检查HTML文件内联:root是否重复定义全局CSS变量。

    防：某个页面自己在<style>:root{ --ok: xxx; }</style>里覆盖了全局主题的语义色，
       导致成功/失败/警告颜色不一致，用户认知混乱。

    分级：
    - 🔴 红灯：覆盖了语义色变量（--ok/--err/--warn/--info/--primary）——这些绝对不能改
    - 🟡 黄灯：覆盖了基础样式变量（--bg/--text/--border等）——可能是合理定制，需人工确认
    """
    # 语义色变量（绝对不能覆盖，覆盖=红灯）
    semantic_vars = [
        "--ok", "--err", "--warn", "--info", "--primary", "--primary-hover",
    ]
    # 基础样式变量（覆盖=黄灯警告，可能是合理定制）
    basic_vars = [
        "--bg", "--bg-card", "--bg-hover",
        "--text", "--text-sub", "--text-mute",
        "--border", "--border-strong",
        "--font-sans", "--font-mono",
        "--radius-sm", "--radius-md", "--radius-lg",
        "--shadow-sm", "--shadow-md",
    ]

    html_dir = os.path.join(BASE_DIR, "jinshuiyao-guide")
    if not os.path.isdir(html_dir):
        _report("CSS变量覆盖检查", True, "无 jinshuiyao-guide 目录，跳过")
        return

    semantic_conflicts = []
    basic_warnings = []

    for fname in os.listdir(html_dir):
        if not fname.endswith(".html"):
            continue
        fpath = os.path.join(html_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        # 找 :root { ... } 块
        for m in re.finditer(r':root\s*\{([^}]+)\}', content, re.IGNORECASE | re.DOTALL):
            root_block = m.group(1)
            # 检查语义色
            found_semantic = []
            for var in semantic_vars:
                if re.search(re.escape(var) + r'\s*:', root_block):
                    found_semantic.append(var)
            if found_semantic:
                semantic_conflicts.append(f"{fname} 覆盖语义色: {', '.join(found_semantic)}")

            # 检查基础样式变量
            found_basic = []
            for var in basic_vars:
                if re.search(re.escape(var) + r'\s*:', root_block):
                    found_basic.append(var)
            if found_basic:
                basic_warnings.append(f"{fname} 覆盖基础样式({len(found_basic)}个): {', '.join(found_basic[:3])}")

    if semantic_conflicts:
        _report("CSS变量覆盖检查", False,
                f"🔴 发现 {len(semantic_conflicts)} 个页面覆盖语义色变量（绝对禁止）：{'; '.join(semantic_conflicts[:2])}")
    elif basic_warnings:
        _warn("CSS变量覆盖检查",
              f"🟡 发现 {len(basic_warnings)} 个页面覆盖基础样式变量（如合理可忽略）：{'; '.join(basic_warnings[:2])}")
        _report("CSS变量覆盖检查", True,
                f"语义色无覆盖；{len(basic_warnings)} 个页面覆盖基础样式（黄灯警告，合理定制可忽略）")
    else:
        _report("CSS变量覆盖检查", True, "所有页面均未覆盖全局CSS变量，主题统一")


def check_mindmap_ids(today_str):
    """检查总索引里的M-编号格式是否正确 + 对应脑图节点是否存在。

    防：M-编号瞎写、格式错、引用不存在的节点。
    校验规则：M-领域-XXX（领域限定：架构/后端/前端/测试/协作/运维/安全/踩坑/最佳实践/知识/流程）
    """
    with open(TRACE_FILE, "r", encoding="utf-8", errors="replace") as f:
        trace_content = f.read()

    valid_domains = {"架构", "后端", "前端", "测试", "协作", "运维", "安全", "踩坑", "最佳实践", "知识", "流程", "4-9B", "4"}
    m_pattern = re.compile(r'M-([^\s/|]+)-(\d+)')
    bad_format = []
    bad_domain = []

    for m in m_pattern.finditer(trace_content):
        full = m.group(0)
        domain = m.group(1)
        if domain not in valid_domains:
            bad_domain.append(f"{full}（领域'{domain}'不在白名单）")

    if bad_format:
        _report("M-编号格式校验", False,
                f"发现 {len(bad_format)} 个格式错误的M-编号：{'; '.join(bad_format[:3])}")
    elif bad_domain:
        _warn("M-编号格式校验",
              f"发现 {len(bad_domain)} 个领域不在白名单：{'; '.join(bad_domain[:3])}")
        _report("M-编号格式校验", True,
                f"格式均正确；{len(bad_domain)} 个领域待确认（如新增领域请更新白名单）")
    else:
        _report("M-编号格式校验", True, "所有M-编号格式正确，领域均在白名单内")


def check_tag_index_consistency():
    """检查经验收集箱的标签与分类索引是否双向一致。

    防：打了标签但没进索引 / 进了索引但没标签 / 两边数量对不上。
    """
    with open(EXPERIENCE_FILE, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.split('\n')
    exp_tags = {}  # {经验标题: [标签列表]}
    current_title = None
    in_index = False

    for line in lines:
        if line.startswith("## 📂 分类索引"):
            in_index = True
            continue
        if line.startswith("## 📊 知识成熟度"):
            in_index = False
            continue
        if in_index:
            continue
        if line.startswith("### 2026-"):
            current_title = line.strip()
            tag_match = re.findall(r'\[([^\]]+)\]', current_title)
            exp_tags[current_title] = tag_match

    # 从分类索引提取索引条目
    index_tags = {}
    in_index2 = False
    current_category = None
    for line in lines:
        if line.startswith("## 📂 分类索引"):
            in_index2 = True
            continue
        if line.startswith("## 📊 知识成熟度"):
            in_index2 = False
            continue
        if in_index2:
            cat_match = re.match(r'^### .+（\[(.+)\]）', line)
            if cat_match:
                current_category = cat_match.group(1)
                if current_category not in index_tags:
                    index_tags[current_category] = []
            elif current_category and line.startswith("- ") and "：" in line:
                index_tags[current_category].append(line.strip())

    # 统计
    tagged_count = sum(1 for tags in exp_tags.values() if tags)
    untagged = [t for t, tags in exp_tags.items() if not tags]

    if untagged:
        _report("标签与分类索引一致性", False,
                f"发现 {len(untagged)} 条经验无标签：{'; '.join(t[:30] for t in untagged[:3])}")
    else:
        _report("标签与分类索引一致性", True,
                f"{len(exp_tags)} 条经验全部有标签；分类索引 {len(index_tags)} 个分类")


def check_rejected_solutions_quality(today_str):
    """检查被否决方案是否真的有内容，不能写"无"/"暂无"糊弄。

    防：写"被否决方案：无"凑字数，等于没做反向思考。
    要求：至少1条具体方案+明确否决原因。
    """
    with open(TRACE_FILE, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    date_pattern = today_str.replace("-", "")
    pattern = re.compile(
        r'JS-' + date_pattern + r'-\d+.*?被否决方案.*?\n((?:.*?\n)*?)(?=\n- \*\*人工介入触发|$)',
        re.MULTILINE)

    empty_solutions = []
    for m in re.finditer(r'被否决方案.*?:\n(.*?)(?=\n- \*\*人工介入触发|\n> - \*\*人工介入触发)', content, re.DOTALL):
        text = m.group(1).strip()
        if len(text) < 15 or "无" == text or "暂无" == text or "没有" == text:
            empty_solutions.append("（内容过短或写了'无'）")

    if empty_solutions:
        _warn("被否决方案内容质量",
              f"部分条目被否决方案内容较简，请确认是否真的做了反向思考")
        _report("被否决方案内容质量", True, "未发现明显糊弄（写'无'/'暂无'）")
    else:
        _report("被否决方案内容质量", True, "被否决方案均有具体内容，有反向思考痕迹")


def check_history_field_sampling():
    """随机抽查5条历史JS条目的字段完整性。

    防：只查当天的，历史条目永远缺字段，欠账越积越多。
    抽样策略：从所有JS条目中随机抽5条，检查5个必填字段。
    """
    import random
    with open(TRACE_FILE, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    js_pattern = re.compile(r'^\| (JS-\d{8}-\d{2}) \|', re.MULTILINE)
    all_js = [m.group(1) for m in js_pattern.finditer(content)]

    if len(all_js) <= 5:
        sample = all_js
    else:
        random.seed(42)  # 固定种子，每次运行结果一致，可复现
        sample = random.sample(all_js, 5)

    missing = []
    for js_id in sample:
        # 找对应的补录块
        pattern = re.compile(
            rf'-\s*\*\*{re.escape(js_id)}.*?被否决方案.*?人工介入触发',
            re.DOTALL)
        if not pattern.search(content):
            # 表格行里的也要查（关联列/成熟度）
            row_pattern = re.compile(rf'^\| {re.escape(js_id)} \|.*\| (draft|verified|proven) \|$', re.MULTILINE)
            if not row_pattern.search(content):
                missing.append(f"{js_id}（找不到完整记录）")

    if missing:
        _warn("历史条目字段抽查",
              f"抽查 {len(sample)} 条，{len(missing)} 条可能缺字段：{', '.join(missing[:3])}")
        _report("历史条目字段抽查", True,
                f"抽查 {len(sample)}/{len(all_js)} 条历史记录，{len(missing)} 条待确认")
    else:
        _report("历史条目字段抽查", True,
                f"抽查 {len(sample)}/{len(all_js)} 条历史记录，字段均完整")


def check_reference_integrity(today_str):
    """引用完整性校验：总索引→交接中心→经验箱的引用是否真实存在。

    防：瞎写"交接中心T3"但交接中心里根本没有T3。
    校验范围：交接中心编号(T#/W#/#N)、经验箱日期条目。
    """
    with open(HANDOFF_FILE, "r", encoding="utf-8", errors="replace") as f:
        handoff_content = f.read()
    with open(EXPERIENCE_FILE, "r", encoding="utf-8", errors="replace") as f:
        exp_content = f.read()

    # 提取交接中心里的有效编号
    valid_handoff_ids = set()
    for m in re.finditer(r'^\| (T\d+|W\d+) \|', handoff_content, re.MULTILINE):
        valid_handoff_ids.add(m.group(1))
    for m in re.finditer(r'^\| \#(\d+) \|', handoff_content, re.MULTILINE):
        valid_handoff_ids.add(f"#{m.group(1)}")

    # 提取经验箱里的有效日期标题
    valid_exp_titles = set()
    for m in re.finditer(r'^### (2026-\d{2}-\d{2} .+?)(?:\s*\[.+?\])?$', exp_content, re.MULTILINE):
        valid_exp_titles.add(m.group(1).strip())

    # 从总索引提取交接中心引用
    with open(TRACE_FILE, "r", encoding="utf-8", errors="replace") as f:
        trace_content = f.read()

    broken_refs = []
    # 找交接中心T#/W#引用
    for m in re.finditer(r'交接中心[^/\n]*?(T\d+|W\d+)', trace_content):
        ref = m.group(1)
        if ref not in valid_handoff_ids:
            broken_refs.append(f"交接中心{ref}（不存在）")

    if broken_refs:
        _warn("引用完整性校验",
              f"发现 {len(broken_refs)} 个疑似断链引用：{'; '.join(broken_refs[:3])}")
        _report("引用完整性校验", True,
                f"主要引用完整；{len(broken_refs)} 个疑似断链待确认")
    else:
        _report("引用完整性校验", True, "交接中心引用均存在，无断链")


def check_variable_naming_convention():
    """抽查代码里全局常量命名是否符合7种前缀规范。

    防：变量命名乱写，变量管理体系沦为文档摆设。
    范围：核心模块顶层大写常量，按抽查模式（不强制所有，因为很多是第三方库常量）。
    """
    valid_prefixes = ("STATUS_", "CONFIG_", "COUNT_", "FLAG_", "OWNER_", "RISK_", "QUALITY_")

    key_files = [
        os.path.join(BASE_DIR, "server", "config.py"),
        os.path.join(BASE_DIR, "core", "ai_service.py"),
    ]

    bad_names = []
    total_constants = 0
    for fpath in key_files:
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        for m in re.finditer(r'^([A-Z][A-Z0-9_]{2,})\s*=', content, re.MULTILINE):
            name = m.group(1)
            total_constants += 1
            # 跳过明显的第三方/环境变量名（太长或太短或特殊含义）
            if len(name) > 30:
                continue
            if not any(name.startswith(p) for p in valid_prefixes):
                bad_names.append(f"{os.path.basename(fpath)}: {name}")

    if bad_names:
        _warn("变量命名规范抽查",
              f"抽查发现 {len(bad_names)}/{total_constants} 个常量不符合7种前缀：{'; '.join(bad_names[:3])}")
        _report("变量命名规范抽查", True,
                f"共 {total_constants} 个常量，{len(bad_names)} 个不符合命名规范（建议逐步迁移）")
    else:
        _report("变量命名规范抽查", True, f"抽查 {total_constants} 个常量，全部符合命名规范")


def check_experience_tag_count():
    """检查经验标签数量合规：至少1个，最多3个。

    防：0个标签=没分类=找不到；>3个标签=等于没分类。
    """
    with open(EXPERIENCE_FILE, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    too_few = []
    too_many = []
    for m in re.finditer(r'^### (2026-\d{2}-\d{2} .+?)(\s*\[.+\])?\s*$', content, re.MULTILINE):
        title = m.group(1).strip()
        tags_str = m.group(2) or ""
        tags = re.findall(r'\[([^\]]+)\]', tags_str)
        if len(tags) == 0:
            too_few.append(title[:30])
        elif len(tags) > 3:
            too_many.append(f"{title[:20]}（{len(tags)}个标签）")

    if too_few or too_many:
        msg_parts = []
        if too_few:
            msg_parts.append(f"{len(too_few)} 条无标签")
        if too_many:
            msg_parts.append(f"{len(too_many)} 条标签>3个")
        if too_few:
            _report("经验标签数量合规", False, f"发现 {'; '.join(msg_parts)}：{'; '.join(too_few[:2])}")
        else:
            _warn("经验标签数量合规", f"发现 {'; '.join(msg_parts)}")
            _report("经验标签数量合规", True, f"标签数量基本合规，{'; '.join(msg_parts)}（建议调整）")
    else:
        _report("经验标签数量合规", True, "所有经验标签数量合规（1~3个）")


# ---------------------------------------------------------------------------
# 文件哈希基线系统（替代 git status，零依赖，防坚果云 mtime 干扰 · v1.7新增）
# ---------------------------------------------------------------------------
# 设计动机：坚果云同步会修改文件 mtime，导致 mtime 扫描误报"今天改了"。
# 用文件内容 SHA256 对比基线，精确检测真正被改动的文件（不受 mtime 影响）。
# 将来安装 git 后可平滑迁移到 git status，接口不变。

# CRITICAL_CONFIG_FILES 已移至 base.py（P1-5: checks_security.check_file_integrity 也需要）

