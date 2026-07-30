# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_security"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入
# P1-5: 跨模块依赖 — 文件完整性函数需要哈希工具（定义在 checks_integrity）
from tools.wrapup.checks_integrity import (
    _compute_file_hash, _load_file_hash_baseline,
    _save_file_hash_baseline, _scan_py_files_hashmap,
    get_changed_files_by_hash,
)

def check_time_anomaly(today_str):
    """检测今日JS条目的时间分布异常。
    ① 凌晨0-5点提交>3条=可疑（人在睡觉，机器在跑）
    ② 同一分钟内提交>3条=可疑（批量注水嫌疑）
    """
    text = _read_text(TRACE_FILE)
    if not text:
        _report("时间分布异常检测", False, "总索引无法读取")
        return

    date_num = today_str.replace("-", "")
    date_short = today_str[5:]  # MM-DD

    # 从表格行提取时间戳：| JS-YYYYMMDD-NN | MM-DD HH:MM | ...
    # 兼容两种格式：07-22 21:30 或 2026-07-22
    time_pattern = rf"JS-{date_num}-\d+\s*\|\s*(\d{{2}}-\d{{2}}\s+\d{{2}}:\d{{2}})"
    times = re.findall(time_pattern, text)

    if not times:
        # 没有时间戳的条目，跳过（不报错，历史条目可能没时间）
        _report("时间分布异常检测", True, "今日条目无时间戳，跳过（建议补登完成时刻）")
        return

    # 解析时间
    from datetime import datetime as _dt
    parsed_times = []
    for t in times:
        try:
            # 格式：MM-DD HH:MM → 加上年份
            dt = _dt.strptime(f"{today_str[:4]}-{t.strip()}", "%Y-%m-%d %H:%M")
            parsed_times.append(dt)
        except ValueError:
            continue

    if not parsed_times:
        _report("时间分布异常检测", True, "时间戳解析失败，跳过")
        return

    parsed_times.sort()
    issues = []

    # ① 凌晨0-5点检查
    late_night = [t for t in parsed_times if 0 <= t.hour < 5]
    if len(late_night) > 3:
        issues.append(f"凌晨0-5点提交{len(late_night)}条（疑似无人值守批量运行）")

    # ② 同一分钟内提交检查
    from collections import Counter
    minute_counts = Counter(t.strftime("%Y-%m-%d %H:%M") for t in parsed_times)
    burst_minutes = {m: c for m, c in minute_counts.items() if c > 3}
    if burst_minutes:
        burst_info = "; ".join(f"{m}提交{c}条" for m, c in list(burst_minutes.items())[:2])
        issues.append(f"同一分钟内批量提交：{burst_info}（疑似注水）")

    if issues:
        _warn("时间分布异常检测",
              f"分析{len(parsed_times)}个时间戳，发现{len(issues)}处异常：" + "；".join(issues))
    else:
        hours_span = (parsed_times[-1] - parsed_times[0]).total_seconds() / 3600
        _report("时间分布异常检测", True,
                f"分析{len(parsed_times)}个时间戳，跨度{hours_span:.1f}小时，"
                f"无凌晨批量/同分钟注水异常")


# ---------------------------------------------------------------------------
# 检查 25：GUI变量作用域静态检查（防NameError · v1.6新增）
# ---------------------------------------------------------------------------
GUI_MAIN_WINDOW = os.path.join(BASE_DIR, "gui", "main_window.py")


def check_gui_variable_scope():
    """静态检查 gui/main_window.py 里引用 T.xxx 的方法是否都有 T = ModernTheme 定义。
    根因：Qoder #35 前端UI升级时，refresh_pred_panel 方法引用了 T.BG_CARD 但漏了 T = ModernTheme，
    导致 GUI 启动时 NameError。pytest 测不到（Tkinter 需要显示环境），只能靠静态分析发现。
    """
    text = _read_text(GUI_MAIN_WINDOW)
    if not text:
        _report("GUI变量作用域检查", False, "gui/main_window.py 无法读取")
        return

    # 用正则提取所有方法定义及其方法体
    # 方法定义格式：    def method_name(self, ...):
    # 方法体：从def行后到下一个同级def或文件结束
    lines = text.splitlines()
    methods = []  # [(name, start_line, body_lines)]
    current_method = None
    current_body = []

    for i, line in enumerate(lines, 1):
        # 匹配方法定义（4个空格缩进的def）
        m = re.match(r"^    def (\w+)\(self", line)
        if m:
            if current_method:
                methods.append((current_method, current_body))
            current_method = m.group(1)
            current_body = [line]
        elif current_method:
            # 检查是否是下一个方法/类定义（同级或更高级缩进）
            if re.match(r"^    def \w+\(self", line) or re.match(r"^class \w+", line) or re.match(r"^def \w+", line):
                methods.append((current_method, current_body))
                current_method = None
                current_body = []
            else:
                current_body.append(line)

    if current_method:
        methods.append((current_method, current_body))

    # 检查每个方法
    issues = []
    for name, body_lines in methods:
        body = "\n".join(body_lines)
        # 检查是否引用了 T.xxx（排除 T = ModernTheme 赋值行）
        t_refs = re.findall(r"\bT\.([A-Z_]+)", body)
        if not t_refs:
            continue  # 不引用T.xxx，跳过

        # 检查是否有 T = ModernTheme 定义
        has_t_def = bool(re.search(r"^\s*T\s*=\s*ModernTheme\s*$", body, re.MULTILINE))
        if not has_t_def:
            # 也检查是否在方法参数或类作用域有T定义（兼容其他写法）
            issues.append(f"{name}()引用T.{t_refs[0]}等{len(t_refs)}处但缺'T = ModernTheme'")

    if issues:
        _report("GUI变量作用域检查", False,
                f"发现{len(issues)}个方法有NameError风险：" + "; ".join(issues[:3]))
    else:
        # 统计有多少方法引用了T.xxx（说明检查覆盖了）
        t_methods = sum(1 for _, body in methods
                        if re.search(r"\bT\.[A-Z_]+", "\n".join(body)))
        _report("GUI变量作用域检查", True,
                f"检查{len(methods)}个方法，{t_methods}个引用T.xxx，全部有'T = ModernTheme'定义")


# ---------------------------------------------------------------------------
# 检查 26：开工五算强制检查（孙子兵法·知止原则 · v1.6新增）
# ---------------------------------------------------------------------------
def check_wukaisan(today_str):
    """检查大改动是否做了开工五算（孙子兵法：道/天/地/将/法）。
    规则：今日改动>5个文件（大改动）→ 交接中心或总索引必须提到"五算"。
    小改动（≤5文件）豁免，避免过度官僚化。
    """
    # 先算今天改了多少个.py文件
    import time
    today_start = time.mktime(time.strptime(today_str, "%Y-%m-%d"))
    skip_dirs = {"__pycache__", ".pytest_cache", "tests", "archive", "_old_backups_consolidated"}
    changed_count = 0
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) >= today_start:
                    changed_count += 1
            except OSError:
                pass

    # 小改动豁免
    if changed_count <= 5:
        _report("开工五算检查", True,
                f"今日改动{changed_count}个文件（≤5），小改动豁免五算")
        return

    # 大改动：检查交接中心+总索引是否提到"五算"
    handoff_text = _read_text(HANDOFF_FILE) or ""
    trace_text = _read_text(TRACE_FILE) or ""
    combined = handoff_text + "\n" + trace_text

    # 搜索"五算"关键词
    has_wukaisan = "五算" in combined or "开工五算" in combined

    if has_wukaisan:
        _report("开工五算检查", True,
                f"今日改动{changed_count}个文件（>5），已做开工五算")
    else:
        _warn("开工五算检查",
              f"今日改动{changed_count}个文件（>5）但交接中心/总索引未提到【五算】。"
              f"大改动应先做开工五算（道/天/地/将/法），详见交接中心§六-H")


# ---------------------------------------------------------------------------
# 检查 27：经验质量评分（简化版 · v1.6新增）
# ---------------------------------------------------------------------------
def check_experience_quality():
    """用规则检查经验质量（简化版，不调大模型）。
    评分维度：①长度 ②踩坑描述 ③有效方法 ④代码引用 ⑤具体性
    低分经验=黄灯警告（可能是糊弄）。
    """
    text = _read_text(EXPERIENCE_FILE)
    if not text:
        _report("经验质量评分", False, "经验收集箱无法读取")
        return

    # 提取每条经验的内容
    pattern = r"### (\d{4}-\d{2}-\d{2}).+?的经验[（(](.+?)[)）].*?\n(.*?)(?=\n### |\n## |\Z)"
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        _report("经验质量评分", True, "未找到经验条目，跳过")
        return

    low_quality = []
    for exp_date, topic, content in matches:
        issues = []

        # ① 总长度检查（<100字=可能太短）
        content_clean = re.sub(r"\s+", "", content)
        if len(content_clean) < 80:
            issues.append("内容过短(<80字)")

        # ② 踩过的坑检查（找到"踩过的坑"部分，检查长度）
        pitfall_match = re.search(r"踩过的坑[：:](.*?)(?=下次注意|有效方法|被否决|人工介入|知识成熟|关联总索引|\Z)",
                                  content, re.DOTALL)
        if pitfall_match:
            pitfall_text = re.sub(r"[\s\*]", "", pitfall_match.group(1))
            if len(pitfall_text) < 20:
                issues.append("踩坑描述过短(<20字)")

        # ③ 有效方法检查
        method_match = re.search(r"有效方法[：:](.*?)(?=被否决|人工介入|知识成熟|关联总索引|\Z)",
                                 content, re.DOTALL)
        if method_match:
            method_text = re.sub(r"[\s\*]", "", method_match.group(1))
            if len(method_text) < 15:
                issues.append("有效方法过短(<15字)")

        # ④ 代码引用统计（仅统计，不算低质量——协作类经验不需要代码）
        has_code = bool(re.search(r"`[^`]+`|```", content))

        if issues:
            low_quality.append(f"{exp_date}「{topic[:15]}」:{'; '.join(issues)}")

    if not low_quality:
        code_count = sum(1 for _, _, c in matches if re.search(r"`[^`]+`|```", c))
        _report("经验质量评分", True,
                f"检查{len(matches)}条经验，全部达标（{code_count}条有代码引用）")
    else:
        quality_rate = (len(matches) - len(low_quality)) / len(matches) * 100
        if quality_rate < 50:
            _report("经验质量评分", False,
                    f"检查{len(matches)}条，{len(low_quality)}条低质量({100-quality_rate:.0f}%)："
                    f"{'; '.join(low_quality[:3])}")
        else:
            _warn("经验质量评分",
                  f"检查{len(matches)}条，{len(low_quality)}条低质量({100-quality_rate:.0f}%)："
                  f"{'; '.join(low_quality[:3])}")


# ---------------------------------------------------------------------------
# 检查 0：自检脚本完整性校验（防篡改，第一道防线 · v1.6新增）
# ---------------------------------------------------------------------------


def _compute_script_hash():
    """计算当前 wrapup_check.py（薄入口）的 SHA256"""
    import hashlib
    # P1-5: 拆包后 __file__ 指向子模块，需定位到 tools/wrapup_check.py
    _tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(_tools_dir, "wrapup_check.py")
    try:
        with open(script_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def check_script_integrity():
    """校验自检脚本是否被篡改（防作弊第一道防线）。
    原理：算当前脚本 SHA256，与 baseline 对比。不一致=被篡改或升级未刷新。
    局限：不能防"同时改脚本+baseline"的攻击，需配合 git 历史校验（#23）。
    """
    current_hash = _compute_script_hash()
    if current_hash is None:
        _report("自检脚本完整性校验", False, "无法计算脚本哈希（文件读取失败）")
        return

    if not os.path.exists(HASH_BASELINE_FILE):
        # 首次运行，自动创建 baseline
        try:
            with open(HASH_BASELINE_FILE, "w", encoding="utf-8") as f:
                f.write(current_hash + "\n")
            _report("自检脚本完整性校验", True,
                    f"首次运行，已创建哈希基线 {current_hash[:12]}…（升级脚本后用 --update-hash 刷新）")
        except Exception as e:
            _report("自检脚本完整性校验", False, f"无法创建哈希基线文件: {e}")
        return

    try:
        with open(HASH_BASELINE_FILE, "r", encoding="utf-8") as f:
            baseline_hash = f.read().strip()
    except Exception:
        _report("自检脚本完整性校验", False, "无法读取哈希基线文件")
        return

    if current_hash == baseline_hash:
        _report("自检脚本完整性校验", True,
                f"脚本哈希匹配 {current_hash[:12]}…（未被篡改）")
    else:
        _report("自检脚本完整性校验", False,
                f"脚本哈希不匹配！基线={baseline_hash[:12]}… 当前={current_hash[:12]}… "
                f"（如为合法升级，请跑 --update-hash 刷新基线并在交接中心登记；否则=被篡改！）")


def update_script_hash():
    """刷新脚本哈希基线（合法升级脚本后用）"""
    current_hash = _compute_script_hash()
    if current_hash is None:
        print(f"{FAIL_ICON} 无法计算脚本哈希")
        return False
    try:
        with open(HASH_BASELINE_FILE, "w", encoding="utf-8") as f:
            f.write(current_hash + "\n")
        print(f"{PASS_ICON} 脚本哈希基线已刷新: {current_hash[:12]}…")
        print(f"    完整哈希: {current_hash}")
        print(f"    ⚠️ 请在交接中心登记本次升级（JS编号 + 升级原因）")
        return True
    except Exception as e:
        print(f"{FAIL_ICON} 无法写入哈希基线文件: {e}")
        return False


# ---------------------------------------------------------------------------
# 检查 24：关键文件完整性校验（替代 git 仓库完整性 · v1.7新增）
# ---------------------------------------------------------------------------
def check_file_integrity():
    """校验关键配置文件的哈希是否与基线一致（替代 git 仓库完整性校验）。

    原理：对关键配置文件（paths.json/scheduler.json/config.py 等）计算 SHA256，
    与文件哈希基线对比。不一致=被意外修改或被坚果云同步篡改。

    与 check_script_integrity 的区别：那个查脚本自身，这个查关键配置文件。
    与 check_trace_coverage 的区别：那个查所有.py改动的留痕覆盖，这个查关键文件是否被非预期修改。
    """
    baseline = _load_file_hash_baseline()
    if baseline is None:
        _report("关键文件完整性校验", True, "首次运行（无基线），已由文件哈希系统覆盖")
        return

    changed_critical = []
    missing_critical = []
    for rel in CRITICAL_CONFIG_FILES:
        fpath = os.path.join(BASE_DIR, rel)
        if not os.path.exists(fpath):
            missing_critical.append(rel)
            continue
        current_h = _compute_file_hash(fpath)
        baseline_h = baseline.get(rel)
        if baseline_h is None:
            continue  # 基线中没有（可能首次扫描后新增），跳过
        if current_h != baseline_h:
            changed_critical.append(rel)

    if not changed_critical:
        detail = f"{len(CRITICAL_CONFIG_FILES)}个关键配置文件哈希均匹配基线"
        if missing_critical:
            detail += f"（{len(missing_critical)}个文件不存在：{', '.join(missing_critical[:2])}）"
        _report("关键文件完整性校验", True, detail)
    else:
        _report("关键文件完整性校验", False,
                f"{len(changed_critical)}个关键文件哈希变化：{', '.join(changed_critical)}"
                f"（如为合法修改，请跑 --update-file-hash 刷新基线并登记）")


def update_file_hash_baseline():
    """刷新文件哈希基线（合法修改文件后用）"""
    hashmap = _scan_py_files_hashmap(BASE_DIR)
    if not hashmap:
        print(f"{FAIL_ICON} 未扫描到任何 .py 文件")
        return False
    if _save_file_hash_baseline(hashmap):
        print(f"{PASS_ICON} 文件哈希基线已刷新: {len(hashmap)} 个文件")
        print(f"    ⚠️ 请在交接中心登记本次刷新原因")
        return True
    else:
        print(f"{FAIL_ICON} 无法写入文件哈希基线")
        return False


# ---------------------------------------------------------------------------
# 检查 25：密钥/敏感信息泄漏扫描（v1.8新增 · 行业SAST标准）
# ---------------------------------------------------------------------------
_SENSITIVE_PATTERNS = [
    # 通用密钥模式
    (r'password\s*[=:]\s*["\']([^"\']{4,})["\']', "硬编码密码"),
    (r'passwd\s*[=:]\s*["\']([^"\']{4,})["\']', "硬编码密码"),
    (r'api[_-]?key\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码API Key"),
    (r'apikey\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码API Key"),
    (r'secret\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码密钥"),
    (r'secret[_-]?key\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码密钥"),
    (r'access[_-]?token\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码Token"),
    (r'auth[_-]?token\s*[=:]\s*["\']([^"\']{8,})["\']', "硬编码Token"),
    (r'bearer\s+([A-Za-z0-9_\-\.]{20,})', "Bearer Token"),

    # 特定服务商Key
    (r'sk-[A-Za-z0-9]{20,}', "OpenAI/DeepSeek API Key (sk-xxx)"),
    (r'AKIA[0-9A-Z]{16}', "AWS Access Key ID"),
    (r'AIza[0-9A-Za-z\-_]{35}', "Google API Key"),
    (r'ghp_[A-Za-z0-9]{36}', "GitHub Personal Token"),
    (r'glpat-[A-Za-z0-9\-_]{20,}', "GitLab Token"),
]

_SENSITIVE_SCAN_EXT = {'.py', '.json', '.yaml', '.yml', '.env', '.ini', '.cfg', '.conf', '.txt', '.md'}
_SENSITIVE_SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env',
    'archive', '备份', 'backups', '.idea', '.vscode',
}
_SENSITIVE_ALLOWLIST_FILES = {
    'pyproject.toml', '.gitignore', 'requirements.txt',
}
# 密钥存储文件名（合法的密钥存储，不是泄漏）- 按文件名前缀/后缀匹配
_SENSITIVE_KEY_STORAGE_PATTERNS = [
    'deepseek_key.txt', 'api_key.txt', 'secret_key.txt',
    '.env', '.env.local', '.env.example',
    'config_secret', 'keys.json', 'credentials',
]
# 测试目录豁免（测试用假值不是真实泄漏）
_SENSITIVE_TEST_DIRS = {'tests', 'test'}


def _is_sensitive_scan_target(rel_path: str) -> bool:
    """判断文件是否需要扫描（基于扩展名和路径）"""
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in _SENSITIVE_SKIP_DIRS:
            return False
    fname = os.path.basename(rel_path).lower()
    if fname in _SENSITIVE_ALLOWLIST_FILES:
        return False
    # 合法密钥存储文件跳过（不是泄漏，是设计如此）
    for pat in _SENSITIVE_KEY_STORAGE_PATTERNS:
        if pat in fname:
            return False
    # 测试目录跳过（测试用假值不是真实泄漏）
    for p in parts:
        if p in _SENSITIVE_TEST_DIRS:
            return False
    _, ext = os.path.splitext(rel_path)
    return ext.lower() in _SENSITIVE_SCAN_EXT


def _value_is_placeholder(val: str) -> bool:
    """判断值是否是占位符（假值，如your_password、xxx、***等）"""
    v = val.strip().lower()
    if not v:
        return True
    placeholders = {
        'your_password', 'your-api-key', 'your_api_key', 'yourkey',
        'password', 'password123', 'changeme', 'change_me',
        'xxx', 'xxxxxx', '***', '*****',
        'example', 'sample', 'test', 'demo',
        'none', 'null', 'false', 'true',
        '请输入', '你的密码', '你的密钥',
    }
    if v in placeholders:
        return True
    if len(set(v)) <= 2:  # 全是同一字符，如aaaaaaaa
        return True
    if v.startswith('${') and v.endswith('}'):  # 变量引用
        return True
    if v.startswith('{{') and v.endswith('}}'):  # 模板变量
        return True
    return False


def check_secrets_leak():
    """扫描代码库中是否存在硬编码的敏感信息（密码、API Key、Token等）。

    原理：对所有 .py/.json/.yaml/.env 等配置和代码文件做正则匹配，
    发现疑似密钥后标记为红灯。符合行业SAST（静态应用安全测试）标准。

    白名单：
      - 占位符/假值自动忽略（your_password、xxx、***等）
      - 示例文件和文档自动跳过
    """
    import re as _re

    findings = []
    scanned = 0

    for root, dirs, files in os.walk(BASE_DIR):
        # 跳过不需要扫描的目录
        dirs[:] = [d for d in dirs if d not in _SENSITIVE_SKIP_DIRS]

        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                rel_path = os.path.relpath(fpath, BASE_DIR)
            except ValueError:
                continue

            if not _is_sensitive_scan_target(rel_path):
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            scanned += 1

            for line_no, line in enumerate(lines, 1):
                # 跳过注释行（降低误报率）
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith(";"):
                    continue

                for pattern, label in _SENSITIVE_PATTERNS:
                    matches = _re.findall(pattern, line, flags=_re.IGNORECASE)
                    for m in matches:
                        # 如果是分组捕获，取第一个匹配的值；否则取完整匹配
                        value = m if isinstance(m, str) else (m[0] if m else "")
                        if value and _value_is_placeholder(value):
                            continue
                        findings.append({
                            "file": rel_path,
                            "line": line_no,
                            "label": label,
                            "snippet": stripped[:100],
                        })

    if not findings:
        _report("密钥泄漏扫描", True,
                f"已扫描 {scanned} 个配置/代码文件，未发现硬编码敏感信息")
    else:
        # 去重（同一行可能匹配多个模式）
        unique = []
        seen = set()
        for f in findings:
            key = (f["file"], f["line"], f["label"])
            if key not in seen:
                seen.add(key)
                unique.append(f)

        detail = (f"发现 {len(unique)} 处疑似敏感信息泄漏："
                  + "; ".join(f"{x['file']}:{x['line']}({x['label']})" for x in unique[:5]))
        if len(unique) > 5:
            detail += f" ...(另{len(unique)-5}处)"
        _report("密钥泄漏扫描", False, detail)


# ---------------------------------------------------------------------------
# 检查 26：前端HTML安全审查（v1.8新增 · 行业XSS/CSP标准）
# ---------------------------------------------------------------------------
_HTML_RISK_PATTERNS = [
    (r'on\w+\s*=\s*["\'][^"\']*["\']', "内联事件处理(onclick/onload等)", "warn"),
    (r'<script[^>]*>(?!.*</script>)', "内联<script>标签", "warn"),
    (r'\.innerHTML\s*=', "innerHTML直接赋值(注意XSS风险)", "warn"),
    (r'document\.write\s*\(', "document.write调用(已废弃)", "warn"),
    (r'eval\s*\(', "eval()调用(高风险)", "high"),
    (r'javascript\s*:', "javascript:伪协议(XSS高风险)", "high"),
]


def check_html_security():
    """扫描所有HTML页面的安全风险（XSS/CSP/内联脚本等）。

    覆盖范围：jinshuiyao-guide/ 下所有 HTML 文件
    检查项：
      - 内联事件处理（onclick/onload等）
      - 内联<script>标签
      - innerHTML直接赋值
      - document.write
      - eval()
      - javascript:伪协议
    """
    import re as _re

    html_dir = os.path.join(BASE_DIR, "jinshuiyao-guide")
    if not os.path.isdir(html_dir):
        _report("前端HTML安全审查", True, "jinshuiyao-guide目录不存在，跳过")
        return

    findings = []
    scanned = 0

    for root, dirs, files in os.walk(html_dir):
        for fname in files:
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(root, fname)
            try:
                rel_path = os.path.relpath(fpath, BASE_DIR)
            except ValueError:
                continue

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    lines = content.splitlines()
            except Exception:
                continue

            scanned += 1

            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()

                for pattern, label, severity in _HTML_RISK_PATTERNS:
                    if _re.search(pattern, line, flags=_re.IGNORECASE):
                        findings.append({
                            "file": rel_path,
                            "line": line_no,
                            "label": label,
                            "severity": severity,
                            "snippet": stripped[:100],
                        })

    high_count = sum(1 for f in findings if f["severity"] == "high")
    warn_count = sum(1 for f in findings if f["severity"] == "warn")

    # 按类型统计警告（便于快速了解分布）
    warn_by_type = {}
    for f in findings:
        if f["severity"] == "warn":
            warn_by_type[f["label"]] = warn_by_type.get(f["label"], 0) + 1
    warn_summary = ", ".join(f"{k}:{v}" for k, v in sorted(warn_by_type.items(), key=lambda x: -x[1]))

    if not findings:
        _report("前端HTML安全审查", True,
                f"已扫描 {scanned} 个HTML页面，未发现XSS/CSP风险")
    elif high_count > 0:
        detail = (f"发现 {high_count} 处高风险："
                  + "; ".join(f"{x['file']}:{x['line']}({x['label']})"
                              for x in findings if x["severity"] == "high")[:5])
        if high_count > 3:
            detail += f" ...(另{high_count - 3}处高风险)"
        _report("前端HTML安全审查", False, detail)
    else:
        if warn_count <= 10:
            detail = (f"发现 {warn_count} 处警告（低风险）："
                      + "; ".join(f"{x['file']}:{x['line']}({x['label']})" for x in findings[:3]))
            if warn_count > 3:
                detail += f" ...(另{warn_count - 3}处)"
        else:
            detail = (f"发现 {warn_count} 处警告（低风险，静态模板可忽略）："
                      + f"分布[{warn_summary}]")
        _report("前端HTML安全审查", True, detail)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 检查 30：改动联动自动检查（防"修A忘改B"·JS-20260723-41新增）
# ---------------------------------------------------------------------------
