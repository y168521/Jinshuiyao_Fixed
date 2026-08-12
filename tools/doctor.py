# -*- coding: utf-8 -*-
"""
金水谣体检医生 - 一键诊断 + 自动修复
======================================
双击「体检修复.bat」即可运行，无需任何技术知识。

设计原则：
  - 纯标准库，不依赖项目任何模块（项目坏了也能跑）
  - 全中文输出，非技术用户看得懂
  - 先诊断后修复，修复前自动备份
  - 参考业界"监测-诊断-修复"闭环 + 360体检式评分

三层防护体系中的第二层（独立体检），第一层是启动前哨，第三层是运行守护。
"""
import os
import sys
import json
import time
import shutil
import socket
import py_compile
import subprocess
import importlib.util
from datetime import datetime

# ---------------------------------------------------------------------------
# Windows GBK 编码安全：确保任何字符都不会导致输出崩溃
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass  # 如果重配置失败，后续用 _enc_ok() 降级

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_DIR = os.path.join(os.path.dirname(BASE_DIR), "venv_314")
DATA_DIR = os.path.join(BASE_DIR, "金水谣数据")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SERVER_DIR = os.path.join(BASE_DIR, "server")
CORE_DIR = os.path.join(BASE_DIR, "core")
SYNC_DIR = os.path.join(BASE_DIR, "sync")
GUIDE_DIR = os.path.join(BASE_DIR, "jinshuiyao-guide")
BACKUP_DIR = os.path.join(BASE_DIR, "tools", "backups")

PORT = 18888

# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------
_WIDTH = 56

def _enc_ok():
    enc = (getattr(sys.stdout, 'encoding', '') or '').lower()
    return 'utf' in enc

def icon_ok():
    return "✅" if _enc_ok() else "[OK]"

def icon_warn():
    return "⚠️" if _enc_ok() else "[!!]"

def icon_err():
    return "❌" if _enc_ok() else "[XX]"

def icon_fix():
    return "🔧" if _enc_ok() else "[FIX]"

def print_header(title):
    print()
    print("=" * _WIDTH)
    print(f"  {title}")
    print("=" * _WIDTH)

def print_section(title):
    print()
    print(f"-- {title} " + "-" * max(0, _WIDTH - len(title) * 2 - 4))

def print_item(status, name, detail=""):
    if status == "ok":
        ic = icon_ok()
    elif status == "warn":
        ic = icon_warn()
    elif status == "err":
        ic = icon_err()
    else:
        ic = icon_fix()
    line = f"  {ic} {name}"
    if detail:
        line += f"  ←  {detail}"
    print(line)


# ---------------------------------------------------------------------------
# 备份工具（修复前自动备份）
# ---------------------------------------------------------------------------
def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)

def backup_file(filepath):
    """备份单个文件到 tools/backups/时间戳_文件名"""
    if not os.path.isfile(filepath):
        return None
    ensure_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.basename(filepath)
    dest = os.path.join(BACKUP_DIR, f"{ts}_{fname}")
    try:
        shutil.copy2(filepath, dest)
        return dest
    except Exception:
        return None

def backup_files(file_list):
    """批量备份，返回备份成功的文件数"""
    count = 0
    for f in file_list:
        if backup_file(f):
            count += 1
    return count


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------
class DoctorReport:
    def __init__(self):
        self.items = []  # [(status, name, detail)]
        self.fixes = []  # [描述]
        self.score = 100

    def add(self, status, name, detail=""):
        self.items.append((status, name, detail))
        if status == "err":
            self.score -= 15
        elif status == "warn":
            self.score -= 5

    def add_fix(self, desc):
        self.fixes.append(desc)

    def grade(self):
        s = max(0, self.score)
        if s >= 90:
            return s, "健康"
        elif s >= 70:
            return s, "小恙"
        elif s >= 50:
            return s, "亚健康"
        else:
            return s, "需要治疗"


# ===== 1. Python 环境检查 =====
def check_python_env(report):
    print_section("Python 运行环境")

    # 当前Python版本
    ver = sys.version_info
    ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver >= (3, 10):
        report.add("ok", "Python版本", f"{ver_str}（良好）")
    elif ver >= (3, 8):
        report.add("warn", "Python版本", f"{ver_str}（能用，推荐3.14）")
    else:
        report.add("err", "Python版本", f"{ver_str}（太低，需3.8+）")

    # venv 检查
    venv_py = os.path.join(VENV_DIR, "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        report.add("ok", "虚拟环境", "venv_314 存在")
        # 检查 pyvenv.cfg 路径是否正确
        cfg_path = os.path.join(VENV_DIR, "pyvenv.cfg")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_text = f.read()
                # 提取 home = 行
                for line in cfg_text.splitlines():
                    if line.strip().startswith("home"):
                        home_val = line.split("=", 1)[1].strip()
                        if os.path.isdir(home_val):
                            report.add("ok", "venv路径指向", home_val)
                        else:
                            report.add("err", "venv路径指向",
                                       f"{home_val}（目录不存在！）")
                            # 自动修复：尝试找到实际python所在目录
                            fixed = _try_fix_venv_cfg(cfg_path, home_val)
                            if fixed:
                                report.add_fix(f"已修正 pyvenv.cfg 路径 → {fixed}")
                        break
            except Exception as e:
                report.add("warn", "venv配置", f"读取失败: {e}")
        else:
            report.add("warn", "venv配置", "pyvenv.cfg 不存在")
    else:
        report.add("warn", "虚拟环境", "venv_314 不存在（将使用系统Python）")


def _try_fix_venv_cfg(cfg_path, bad_home):
    """尝试修正 pyvenv.cfg 中的 home 路径"""
    # 候选路径
    candidates = [
        r"E:\下载",
        r"D:\下载",
        os.path.dirname(sys.executable),
    ]
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "python.exe")):
            backup_file(cfg_path)
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(cfg_path, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip().startswith("home"):
                            f.write(f"home = {cand}\n")
                        else:
                            f.write(line)
                return cand
            except Exception:
                return None
    return None


# ===== 2. 语法检查（核心py文件） =====
def check_syntax(report):
    print_section("核心文件语法检查")

    # 要检查的关键文件/目录
    targets = []
    # 根目录关键文件
    root_files = [
        "main.py", "launch_jinshuiyao.py", "config.py", "preload.py",
        "startup_selfcheck.py", "jinshuiyao_router.py",
    ]
    for f in root_files:
        fp = os.path.join(BASE_DIR, f)
        if os.path.isfile(fp):
            targets.append(fp)

    # 核心目录
    for d in [SERVER_DIR, CORE_DIR, os.path.join(BASE_DIR, "utils"),
              CONFIG_DIR, SYNC_DIR]:
        if os.path.isdir(d):
            for entry in os.listdir(d):
                if entry.endswith(".py"):
                    targets.append(os.path.join(d, entry))
            # server/handlers 子目录
            handlers = os.path.join(d, "handlers")
            if os.path.isdir(handlers):
                for entry in os.listdir(handlers):
                    if entry.endswith(".py"):
                        targets.append(os.path.join(handlers, entry))

    err_count = 0
    checked = 0
    for fp in targets:
        checked += 1
        try:
            py_compile.compile(fp, doraise=True)
        except py_compile.PyCompileError as e:
            err_count += 1
            fname = os.path.relpath(fp, BASE_DIR)
            # 提取行号
            err_msg = str(e)
            report.add("err", f"语法错误: {fname}", _extract_syntax_hint(err_msg))

    if err_count == 0:
        report.add("ok", f"语法检查", f"{checked} 个核心文件全部通过")
    else:
        report.add("err", "语法检查汇总", f"{err_count}/{checked} 个文件有语法错误")


def _extract_syntax_hint(err_msg):
    """从编译错误中提取友好提示"""
    if "U+201C" in err_msg or "U+201D" in err_msg or "U+2018" in err_msg or "U+2019" in err_msg:
        return "有中文弯引号混入代码，需替换为英文直引号"
    if "invalid syntax" in err_msg:
        # 尝试提取行号
        for part in err_msg.split("\n"):
            if "line" in part:
                return part.strip()
        return "语法不合法，请检查最近修改"
    return err_msg[:80]


# ===== 3. 端口检查 =====
def check_port(report):
    print_section("端口占用检查")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(("127.0.0.1", PORT))
    sock.close()

    if result == 0:
        report.add("warn", f"端口 {PORT}", "被占用（可能有旧进程残留）")
        # 尝试找到占用进程
        pid = _find_port_pid(PORT)
        if pid:
            report.add("warn", "占用进程", f"PID={pid}")
            # 提供修复建议但不自动杀（体检模式下询问）
            report.add_fix(f"建议：关闭旧的金水谣窗口，或任务管理器结束 PID {pid}")
    else:
        report.add("ok", f"端口 {PORT}", "空闲，可正常启动")


def _find_port_pid(port):
    """通过 netstat 找占用端口的 PID"""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL, text=True
        )
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    return parts[-1]
    except Exception:
        pass
    return None


# ===== 4. 关键文件完整性 =====
def check_files(report):
    print_section("关键文件完整性")

    critical_files = [
        ("launch_jinshuiyao.py", "启动器"),
        ("launch.bat", "启动脚本"),
        ("config.py", "全局配置"),
        (os.path.join("server", "__init__.py"), "服务器包"),
        (os.path.join("server", "router.py"), "路由"),
        (os.path.join("core", "ai_service.py"), "AI服务"),
        (os.path.join("core", "scheduler.py"), "定时调度"),
        (os.path.join("utils", "safe_json.py"), "安全JSON"),
        (os.path.join("config", "logging_config.py"), "日志配置"),
        # 以下为"已知删除/可选"，不再计入缺失（避免恒定假红）：
        # main.py        → 已迁移为 launch_jinshuiyao.py（2026-07 重构）
        # sync/device_sync.py → 跨设备同步为可选功能，本机未启用（sync.py 已诚实降级）
        # deepseek_key.txt   → 密钥已收口到 ~/.jinshuiyao-secrets/（core/security.py 单一入口）
    ]

    missing = []
    for rel_path, label in critical_files:
        fp = os.path.join(BASE_DIR, rel_path)
        if os.path.isfile(fp):
            # 检查文件是否为空
            if os.path.getsize(fp) == 0:
                report.add("warn", label, f"{rel_path}（文件为空！）")
            # 不逐个打印正常的，太多了
        else:
            missing.append((rel_path, label))
            report.add("err", label, f"{rel_path} 不存在")

    if not missing:
        report.add("ok", "关键文件", f"{len(critical_files)} 个核心文件齐全")


# ===== 5. 数据目录检查 =====
def check_data_dirs(report):
    print_section("数据目录")

    dirs_needed = [
        (DATA_DIR, "金水谣数据"),
        (os.path.join(DATA_DIR, "log"), "日志目录"),
        (os.path.join(BASE_DIR, "knowledge", "用户知识库"), "知识库"),
        (os.path.join(BASE_DIR, "predictions"), "预测数据"),
        (CONFIG_DIR, "配置目录"),
    ]

    created = []
    for d, label in dirs_needed:
        if os.path.isdir(d):
            pass  # 正常不打印
        else:
            try:
                os.makedirs(d, exist_ok=True)
                created.append(label)
            except Exception as e:
                report.add("err", label, f"创建失败: {e}")

    if created:
        report.add("fix", "自动创建目录", "、".join(created))
        report.add_fix(f"已自动创建缺失目录: {'、'.join(created)}")
    else:
        report.add("ok", "数据目录", "全部存在")


# ===== 6. 核心模块可导入性 =====
def check_imports(report):
    print_section("核心模块加载测试")

    modules = [
        ("server", BASE_DIR, "服务器"),
        ("config", BASE_DIR, "配置"),
        ("utils.safe_json", BASE_DIR, "安全JSON"),
        ("utils.locks", BASE_DIR, "锁管理"),
        ("core.ai_service", BASE_DIR, "AI服务"),
        ("core.scheduler", BASE_DIR, "调度器"),
        # sync.device_sync 为可选功能（本机未启用），不计入核心模块
    ]

    fail_count = 0
    for mod_name, path, label in modules:
        saved = list(sys.path)
        try:
            if path not in sys.path:
                sys.path.insert(0, path)
            spec = importlib.util.find_spec(mod_name)
            if spec is None:
                report.add("err", label, f"找不到模块 {mod_name}")
                fail_count += 1
        except SyntaxError as e:
            report.add("err", label, f"语法错误导致无法加载（第{e.lineno}行）")
            fail_count += 1
        except Exception as e:
            report.add("warn", label, f"加载异常: {str(e)[:60]}")
            fail_count += 1
        finally:
            sys.path[:] = saved

    if fail_count == 0:
        report.add("ok", "模块加载", f"{len(modules)} 个核心模块均可正常找到")


# ===== 7. 配置文件有效性 =====
def check_configs(report):
    print_section("配置文件")

    json_configs = [
        (os.path.join(CONFIG_DIR, "scheduler.json"), "调度器配置"),
        (os.path.join(CONFIG_DIR, "ai_mode.json"), "AI模式配置"),
        (os.path.join(CONFIG_DIR, "paths.json"), "路径配置"),
        (os.path.join(SYNC_DIR, "sync_state.json"), "同步台账"),
    ]

    bad = []
    for fp, label in json_configs:
        if not os.path.isfile(fp):
            continue  # 可选配置不存在不算错
        try:
            with open(fp, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            bad.append(label)
            report.add("err", label, f"JSON格式损坏: 第{e.lineno}行")
            # 尝试备份损坏文件
            backup_file(fp)
            report.add_fix(f"已备份损坏的 {label}，请让AI助手修复内容")
        except Exception as e:
            bad.append(label)
            report.add("warn", label, f"读取异常: {e}")

    if not bad:
        report.add("ok", "配置文件", "所有JSON配置格式正确")


# ===== 8. 磁盘空间 =====
def check_disk(report):
    print_section("磁盘空间")

    try:
        drive = os.path.splitdrive(BASE_DIR)[0] or "C:"
        usage = shutil.disk_usage(drive + "\\")
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct = (usage.free / usage.total) * 100

        if free_gb < 1:
            report.add("err", "剩余空间", f"{free_gb:.1f}GB（严重不足！）")
        elif free_gb < 5:
            report.add("warn", "剩余空间", f"{free_gb:.1f}GB / {total_gb:.0f}GB（偏少）")
        else:
            report.add("ok", "剩余空间", f"{free_gb:.1f}GB / {total_gb:.0f}GB")
    except Exception as e:
        report.add("warn", "磁盘检查", f"无法检测: {e}")


# ===== 9. 前端页面完整性 =====
def check_frontend(report):
    print_section("前端页面")

    if not os.path.isdir(GUIDE_DIR):
        report.add("warn", "前端目录", "jinshuiyao-guide 不存在")
        return

    html_files = [f for f in os.listdir(GUIDE_DIR) if f.endswith(".html")]
    theme_css = os.path.join(GUIDE_DIR, "_shared", "css", "theme.css")

    if os.path.isfile(theme_css):
        report.add("ok", "主题样式", "theme.css 存在")
    else:
        report.add("err", "主题样式", "theme.css 缺失（页面会没有统一样式）")

    # 检查HTML是否引用了theme.css
    no_theme = []
    for hf in html_files:
        fp = os.path.join(GUIDE_DIR, hf)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read(2000)  # 只读前2000字符
            if "theme.css" not in content:
                no_theme.append(hf)
        except Exception:
            pass

    if no_theme:
        report.add("warn", "主题引用", f"{len(no_theme)}个页面未引用theme.css")
    else:
        report.add("ok", "页面完整性", f"{len(html_files)} 个页面均正常")


# ===== 10. 弯引号/特殊字符扫描 =====
def check_curly_quotes(report):
    print_section("代码污染扫描（弯引号/乱码）")

    # 扫描所有核心py文件中的Unicode弯引号
    bad_chars = {
        '\u201c': '左双弯引号(U+201C)',
        '\u201d': '右双弯引号(U+201D)',
        '\u2018': '左单弯引号(U+2018)',
        '\u2019': '右单弯引号(U+2019)',
        '\u3000': '全角空格',
    }

    infected = []  # 含弯引号的文件
    scan_dirs = [BASE_DIR, SERVER_DIR, CORE_DIR,
                 os.path.join(BASE_DIR, "utils"), CONFIG_DIR, SYNC_DIR]

    for d in scan_dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            if not entry.endswith(".py"):
                continue
            fp = os.path.join(d, entry)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()
                found = []
                for char, name in bad_chars.items():
                    if char in content:
                        found.append(name)
                if found:
                    rel = os.path.relpath(fp, BASE_DIR)
                    infected.append((fp, rel, found))
            except Exception:
                pass

    if not infected:
        report.add("ok", "代码纯净度", "未发现弯引号或全角字符污染")
        return

    # 关键区分：弯引号在字符串内是合法中文标点，只有导致语法错误才是"污染"
    broken = []   # 编译失败（弯引号用作了代码引号）
    healthy = []  # 编译通过（弯引号只是字符串内的中文标点）

    for fp, rel, found in infected:
        try:
            py_compile.compile(fp, doraise=True)
            healthy.append(rel)
        except py_compile.PyCompileError:
            broken.append((fp, rel, found))

    if healthy:
        report.add("ok", "中文标点",
                   f"{len(healthy)}个文件含弯引号但属正常中文标点，无需处理")

    if broken:
        for fp, rel, found in broken:
            report.add("err", f"污染: {rel}",
                       "弯引号混入代码导致语法错误（" + "、".join(found) + "）")
        # 只修复真正坏掉的文件
        fixed_count = _fix_curly_quotes(broken)
        if fixed_count:
            report.add_fix(f"已自动修复 {fixed_count} 个文件的弯引号污染")


def _fix_curly_quotes(infected_files):
    """自动替换弯引号为直引号（仅针对编译失败的文件）"""
    replacements = {
        '\u201c': '"', '\u201d': '"',
        '\u2018': "'", '\u2019': "'",
    }
    fixed = 0
    for fp, rel, found in infected_files:
        # 先备份
        backup_file(fp)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
            for old, new in replacements.items():
                content = content.replace(old, new)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            fixed += 1
        except Exception:
            pass
    return fixed


# ===== 11. 坚果云同步状态 =====
def check_nutstore(report):
    print_section("坚果云同步")

    # 检查是否在坚果云目录下
    if "Nutstore" in BASE_DIR or "nutstore" in BASE_DIR.lower():
        report.add("ok", "同步目录", "项目位于坚果云同步路径内")
    else:
        report.add("warn", "同步目录", "项目不在坚果云路径，跨设备同步可能失效")

    # 检查坚果云进程
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq NutstoreGUI.exe"],
            stderr=subprocess.DEVNULL, text=True
        )
        if "NutstoreGUI" in out:
            report.add("ok", "坚果云进程", "正在运行")
        else:
            report.add("warn", "坚果云进程", "未运行（文件不会自动同步）")
    except Exception:
        report.add("warn", "坚果云进程", "无法检测")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_doctor():
    print_header("金水谣体检医生 v1.0")
    print(f"  检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  项目路径: {BASE_DIR}")
    print(f"  Python:   {sys.executable}")

    report = DoctorReport()

    # 执行所有检查
    check_python_env(report)
    check_syntax(report)
    check_port(report)
    check_files(report)
    check_data_dirs(report)
    check_imports(report)
    check_configs(report)
    check_disk(report)
    check_frontend(report)
    check_curly_quotes(report)
    check_nutstore(report)

    # 输出汇总
    print_header("体检报告")

    score, grade = report.grade()
    print(f"\n  健康评分: {score} 分  【{grade}】\n")

    # 统计
    ok_count = sum(1 for s, _, _ in report.items if s == "ok")
    warn_count = sum(1 for s, _, _ in report.items if s == "warn")
    err_count = sum(1 for s, _, _ in report.items if s == "err")
    fix_count = sum(1 for s, _, _ in report.items if s == "fix")

    print(f"  通过: {ok_count} 项 | 警告: {warn_count} 项 | 异常: {err_count} 项")

    # 只打印有问题的项
    problems = [(s, n, d) for s, n, d in report.items if s in ("err", "warn")]
    if problems:
        print(f"\n  {'-' * 48}")
        print("  需要关注的问题：")
        for s, n, d in problems:
            ic = icon_err() if s == "err" else icon_warn()
            print(f"    {ic} {n}: {d}")

    # 打印已执行的修复
    if report.fixes:
        print(f"\n  {'-' * 48}")
        print(f"  {icon_fix()} 已自动修复 {len(report.fixes)} 项：")
        for fix in report.fixes:
            print(f"    * {fix}")

    # 最终建议
    print(f"\n  {'-' * 48}")
    if err_count == 0 and warn_count == 0:
        print(f"  {icon_ok()} 一切正常，放心使用！")
    elif err_count == 0:
        print(f"  {icon_warn()} 有小问题但不影响使用，留意上方警告即可。")
    else:
        print(f"  {icon_err()} 有 {err_count} 项异常需要处理。")
        print(f"  建议：把上面的红色项目截图发给AI助手，让它帮你修。")

    print()
    print("=" * _WIDTH)
    print("  体检完毕。按任意键关闭窗口。")
    print("=" * _WIDTH)

    return report


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        run_doctor()
    except Exception as e:
        print(f"\n{icon_err()} 体检过程本身出错了: {e}")
        import traceback
        traceback.print_exc()
    # Windows下暂停，让用户看到结果
    if sys.platform == "win32":
        os.system("pause >nul 2>&1")
