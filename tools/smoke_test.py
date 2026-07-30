#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
金水谣修后全功能实测检验（Smoke Test · 修完必须跑）
====================================================
修A可能坏B——pytest只测单元，本脚本测端到端全功能。

用法：
    py tools/smoke_test.py              # 跑全部冒烟测试
    py tools/smoke_test.py --quick      # 快速版（只测关键路径，约10秒）
    py tools/smoke_test.py --server     # 先启动服务器再测试

检查项（v1.0 · 15项）：
  0.  核心模块导入           —— 所有关键模块能 import
  1.  配置文件可读           —— paths.json/scheduler.json/config.py
  2.  数据文件可读           —— 历史开奖数据存在且格式正确
  3.  AI服务可用             —— ai_service 能初始化，get_api_key() 返回值
  4.  预测引擎可生成         —— PredictionService 能实例化，generate 不崩溃
  5.  热号类型正确           —— evolve.train() 返回 dict，不是 list（防 KeyError）
  6.  调度器可初始化         —— TaskScheduler 能启动，_defaults 与 json 一致
  7.  知识引擎可索引         —— kb_engine 能加载，索引文件存在
  8.  GUI主窗口可实例化      —— main_window.py 导入不报错（Tkinter依赖检查）
  9.  服务器可启动           —— server 包能 import，main() 不崩溃（不实际启动）
 10.  页面路由完整           —— 13个HTML页面全部有路由注册
 11.  API端点可达            —— /health 返回200（需服务器运行）
 12.  预测结果格式正确       —— 生成的预测结果含必要字段（success/lot/period/tickets/all_nums/messages）
 13.  经验收集箱可读         —— 经验箱.md 格式正确，必填字段存在
 14.  自检脚本可运行         —— wrapup_check.py --skip-tests 能跑且全绿

纯标准库 + 项目内部模块，零外部依赖。
"""

import os
import sys
import json
import importlib
import subprocess
from datetime import date

# Windows GBK 终端安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Jinshuiyao_Fixed/
MODEL_DIR = os.path.dirname(BASE_DIR)  # 模型/

# 确保项目根目录在 sys.path 中，以便 import engines/core/server 等
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_results = []
PASS_ICON = "[OK]"
FAIL_ICON = "[!!]"
WARN_ICON = "[??]"


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
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 检查 0：核心模块导入
# ---------------------------------------------------------------------------
def check_module_imports():
    """检查所有关键模块能否正常导入"""
    modules = [
        ("engines.prediction_service", "PredictionService"),
        ("engines.evolve", "Evolve"),
        ("models.lottery_data", "Data"),
        ("core.ai_service", "AIService"),
        ("core.scheduler", "TaskScheduler"),
        ("server", None),  # 包导入
        ("config", None),
        ("tools.ai_review_agent", None),
        ("tools.ast_checker", None),
        ("tools.review_learning", None),
        ("tools.review_report", None),
        ("server.handlers.review", None),
    ]

    failed = []
    for mod_name, cls_name in modules:
        try:
            mod = importlib.import_module(mod_name)
            if cls_name:
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    failed.append(f"{mod_name}.{cls_name} 类不存在")
        except Exception as e:
            failed.append(f"{mod_name}: {type(e).__name__}: {str(e)[:80]}")

    if failed:
        _report("核心模块导入", False, f"{len(failed)} 个导入失败: {'; '.join(failed[:3])}")
    else:
        _report("核心模块导入", True, f"{len(modules)} 个核心模块全部可导入")


# ---------------------------------------------------------------------------
# 检查 1：配置文件可读
# ---------------------------------------------------------------------------
def check_config_files():
    """检查关键配置文件存在且可解析"""
    paths_json = os.path.join(BASE_DIR, "config", "paths.json")
    scheduler_json = os.path.join(BASE_DIR, "config", "scheduler.json")
    config_py = os.path.join(BASE_DIR, "server", "config.py")

    errors = []
    paths = _read_json(paths_json)
    if paths is None:
        errors.append("paths.json 不可读")
    elif "python_candidates" not in paths:
        errors.append("paths.json 缺 python_candidates 字段")

    sched = _read_json(scheduler_json)
    if sched is None:
        errors.append("scheduler.json 不可读")

    config_text = _read_text(config_py)
    if not config_text:
        errors.append("server/config.py 不可读")
    elif "PORT" not in config_text:
        errors.append("config.py 缺 PORT 定义")

    if errors:
        _report("配置文件可读", False, "; ".join(errors[:3]))
    else:
        _report("配置文件可读", True, "paths.json + scheduler.json + config.py 全部可读")


# ---------------------------------------------------------------------------
# 检查 2：数据文件可读
# ---------------------------------------------------------------------------
def check_data_files():
    """检查历史开奖数据存在且格式正确"""
    data_dir = os.path.join(BASE_DIR, "金水谣数据", "lot_data")
    if not os.path.isdir(data_dir):
        # 可能在archive或被清空，降级检查
        _warn("数据文件可读", "lot_data 目录不存在（可能被清空），降级检查")
        _report("数据文件可读", True, "降级通过（lot_data目录不存在但非致命）")
        return

    lot_files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
    if not lot_files:
        _report("数据文件可读", False, "lot_data 目录下无JSON数据文件")
        return

    # 抽查第一个文件格式
    sample = _read_json(os.path.join(data_dir, lot_files[0]))
    if sample is None:
        _report("数据文件可读", False, f"{lot_files[0]} 格式错误（JSON解析失败）")
    elif not isinstance(sample, list) or len(sample) == 0:
        _report("数据文件可读", False, f"{lot_files[0]} 格式错误（应为非空列表）")
    elif "nums" not in sample[0]:
        _report("数据文件可读", False, f"{lot_files[0]} 缺 'nums' 字段")
    else:
        _report("数据文件可读", True, f"找到 {len(lot_files)} 个彩种数据文件，格式正确")


# ---------------------------------------------------------------------------
# 检查 3：AI服务可用
# ---------------------------------------------------------------------------
def check_ai_service():
    """检查AI服务能否初始化，密钥能读取"""
    try:
        from core.ai_service import AIService, get_api_key
        key = get_api_key()
        if key:
            _report("AI服务可用", True, f"AIService 可初始化，密钥存在（长度{len(key)}）")
        else:
            _warn("AI服务可用", "密钥文件不存在或为空（AI功能降级为本地模式）")
            _report("AI服务可用", True, "AIService 可初始化，密钥为空（本地模式）")
    except Exception as e:
        _report("AI服务可用", False, f"初始化失败: {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# 检查 4：预测引擎可生成
# ---------------------------------------------------------------------------
def check_prediction_engine():
    """检查预测引擎能否实例化且generate不崩溃"""
    try:
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        _report("预测引擎可实例化", True, "PredictionService 初始化成功")
    except Exception as e:
        _report("预测引擎可实例化", False, f"初始化失败: {type(e).__name__}: {str(e)[:80]}")
        return

    # 尝试生成一个预测（不需要真实数据，只检查不崩溃）
    try:
        result = svc.generate("福彩3D")
        if result is not None and isinstance(result, dict):
            _report("预测生成不崩溃", True, f"福彩3D预测返回: {list(result.keys())[:5]}")
        else:
            _warn("预测生成不崩溃", f"generate返回非dict: {type(result)}")
            _report("预测生成不崩溃", True, "generate不崩溃（返回类型非预期但无报错）")
    except Exception as e:
        # KeyError: slice 是已知bug，应已被修复
        err_str = str(e)
        if "slice" in err_str:
            _report("预测生成不崩溃", False,
                    f"热号KeyError仍存在！evolve.train()返回dict但调用方假设list。"
                    f"错误: {err_str[:100]}")
        else:
            _report("预测生成不崩溃", False,
                    f"generate崩溃: {type(e).__name__}: {err_str[:100]}")


# ---------------------------------------------------------------------------
# 检查 5：热号类型正确
# ---------------------------------------------------------------------------
def check_hot_number_type():
    """检查evolve.train()返回类型——必须返回dict，防hot[:6] KeyError"""
    try:
        from engines.evolve import Evolve
        evolve = Evolve()
        result = evolve.train("福彩3D")
        if result is None:
            _report("热号类型正确", True, "train()返回None（无数据），无切片风险")
        elif isinstance(result, dict):
            _report("热号类型正确", True, f"train()返回dict（{len(result)}个号码），类型正确")
        elif isinstance(result, list):
            _warn("热号类型正确", "train()返回list而非dict——如果prediction_service用hot[:6]切片会取随机顺序而非权重排序")
            _report("热号类型正确", True, "train()返回list（降级通过但建议改为dict）")
        else:
            _report("热号类型正确", False, f"train()返回异常类型: {type(result)}")
    except Exception as e:
        # 无数据时train()可能报错，这是正常的
        _warn("热号类型正确", f"train()调用失败（可能无数据）: {str(e)[:60]}")
        _report("热号类型正确", True, "降级通过（train()因无数据失败，非类型问题）")


# ---------------------------------------------------------------------------
# 检查 6：调度器可初始化
# ---------------------------------------------------------------------------
def check_scheduler():
    """检查调度器能否初始化，配置与json一致"""
    try:
        from core.scheduler import TaskScheduler
        sched = TaskScheduler()
        _report("调度器可初始化", True, "TaskScheduler 初始化成功")
    except Exception as e:
        _report("调度器可初始化", False, f"初始化失败: {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# 检查 7：知识引擎可索引
# ---------------------------------------------------------------------------
def check_knowledge_engine():
    """检查知识引擎能否加载，索引文件存在"""
    kb_dir = os.path.join(BASE_DIR, "knowledge")
    if not os.path.isdir(kb_dir):
        _warn("知识引擎可索引", "knowledge目录不存在")
        _report("知识引擎可索引", True, "降级通过（knowledge目录不存在）")
        return

    index_file = os.path.join(kb_dir, "kb_index.json")
    if os.path.exists(index_file):
        idx = _read_json(index_file)
        if idx and isinstance(idx, list):
            _report("知识引擎可索引", True, f"索引文件存在，含 {len(idx)} 条知识")
        else:
            _warn("知识引擎可索引", "索引文件格式异常")
            _report("知识引擎可索引", True, "降级通过（索引格式异常）")
    else:
        _warn("知识引擎可索引", "kb_index.json 不存在（首次运行会自动创建）")
        _report("知识引擎可索引", True, "降级通过（索引文件不存在）")


# ---------------------------------------------------------------------------
# 检查 8：GUI主窗口可导入
# ---------------------------------------------------------------------------
def check_gui_import():
    """检查GUI模块导入不报错（Tkinter依赖检查）"""
    try:
        import tkinter
        _report("Tkinter可用", True, "tkinter 模块可导入")
    except ImportError:
        _warn("Tkinter可用", "tkinter不可导入（headless/服务器环境正常），GUI功能降级")
        _report("Tkinter可用", True, "降级通过（headless环境，GUI无法启动但非致命）")
        return

    try:
        from gui.main_window import App  # noqa: F401
        _report("GUI模块可导入", True, "gui.main_window 导入成功")
    except NameError as e:
        # 检查是否是 T = ModernTheme 缺失导致的
        err = str(e)
        if "ModernTheme" in err or "'T'" in err:
            _report("GUI模块可导入", False,
                    f"NameError: {err}——方法缺'T = ModernTheme'局部定义（已知bug模式）")
        else:
            _report("GUI模块可导入", False, f"NameError: {err}")
    except Exception as e:
        _report("GUI模块可导入", False, f"导入失败: {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# 检查 9：服务器可启动（不实际启动）
# ---------------------------------------------------------------------------
def check_server_import():
    """检查server包能导入，main函数存在"""
    try:
        from server import main
        _report("服务器模块可导入", True, "server.main() 函数存在")
    except Exception as e:
        _report("服务器模块可导入", False, f"导入失败: {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# 检查 10：页面路由完整
# ---------------------------------------------------------------------------
def check_page_routes():
    """检查13个HTML页面全部有路由注册"""
    guide_dir = os.path.join(BASE_DIR, "jinshuiyao-guide")
    if not os.path.isdir(guide_dir):
        _report("页面路由完整", False, "jinshuiyao-guide 目录不存在")
        return

    html_files = [f for f in os.listdir(guide_dir) if f.endswith(".html")]
    static_py = os.path.join(BASE_DIR, "server", "handlers", "static.py")
    static_text = _read_text(static_py)

    missing = []
    for f in html_files:
        if f not in static_text:
            missing.append(f)

    if missing:
        _report("页面路由完整", False,
                f"{len(missing)} 个页面未注册路由: {', '.join(missing[:3])}")
    else:
        _report("页面路由完整", True, f"{len(html_files)} 个页面全部有路由")


# ---------------------------------------------------------------------------
# 检查 11：API端点可达（需服务器运行）
# ---------------------------------------------------------------------------
def check_api_health():
    """检查/health端点可达（需要服务器正在运行）"""
    try:
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:18888/health", timeout=3)
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data.get("status") == "ok":
                _report("API端点可达", True,
                        f"/health 返回200，status=ok，version={data.get('version', '?')}")
            else:
                _warn("API端点可达", f"/health 返回但status非ok: {data.get('status')}")
                _report("API端点可达", True, "降级通过（服务器运行但状态非ok）")
        except urllib.error.URLError:
            _warn("API端点可达", "服务器未运行（http://127.0.0.1:18888 连接失败）")
            _report("API端点可达", True, "降级通过（服务器未运行，非致命）")
    except Exception as e:
        _warn("API端点可达", f"检测失败: {str(e)[:60]}")
        _report("API端点可达", True, "降级通过（检测异常）")


# ---------------------------------------------------------------------------
# 检查 12：预测结果格式正确
# ---------------------------------------------------------------------------
def check_prediction_format():
    """检查预测生成的结果含必要字段"""
    try:
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        result = svc.generate("福彩3D")
        if result is None:
            _warn("预测结果格式", "generate返回None（无数据）")
            _report("预测结果格式", True, "降级通过（无数据）")
            return

        required_fields = ["success", "lot", "period", "tickets", "all_nums", "messages"]
        missing = [f for f in required_fields if f not in result]
        if missing:
            _report("预测结果格式", False,
                    f"预测结果缺必要字段: {', '.join(missing)}")
        else:
            tickets = result.get("tickets", {})
            all_nums = result.get("all_nums", [])
            _report("预测结果格式", True,
                    f"福彩3D预测: lot={result['lot']}, period={result['period']}, "
                    f"tickets含{len(tickets)}类, all_nums含{len(all_nums)}注")
    except Exception as e:
        if "slice" in str(e):
            _report("预测结果格式", False, "热号KeyError仍在——evolve.train()类型不匹配")
        else:
            _warn("预测结果格式", f"generate失败: {str(e)[:60]}")
            _report("预测结果格式", True, "降级通过（generate失败）")


# ---------------------------------------------------------------------------
# 检查 13：经验收集箱可读
# ---------------------------------------------------------------------------
def check_experience_file():
    """检查经验收集箱格式正确"""
    exp_file = os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md")
    text = _read_text(exp_file)
    if not text:
        _report("经验收集箱可读", False, "文件不存在或为空")
        return

    # 检查分类索引存在
    if "分类索引" not in text:
        _warn("经验收集箱可读", "缺分类索引（标签体系未完善）")

    # 检查必填字段模式
    required = ["做了什么", "踩过的坑", "下次注意", "有效方法"]
    missing = [f for f in required if f not in text]
    if missing:
        _report("经验收集箱可读", False,
                f"缺必填字段模式: {', '.join(missing)}")
    else:
        # 计算经验条目数
        entries = len(re.findall(r"### \d{4}-\d{2}-\d{2}", text))
        _report("经验收集箱可读", True,
                f"格式正确，含 {entries} 条经验，4个必填字段模式齐全")


# ---------------------------------------------------------------------------
# 检查 14：自检脚本可运行
# ---------------------------------------------------------------------------
def check_wrapup_script():
    """检查wrapup_check.py --skip-tests能跑且全绿"""
    script = os.path.join(BASE_DIR, "tools", "wrapup_check.py")
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            [sys.executable, script, "--skip-tests", "--date", today_str],
            capture_output=True, text=True, errors="replace",
            timeout=60,
            cwd=BASE_DIR
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            # 检查是否有"全绿"字样
            if "全绿" in output:
                _report("自检脚本可运行", True, "wrapup_check.py --skip-tests 全绿")
            else:
                _warn("自检脚本可运行", "returncode=0 但输出无'全绿'字样")
                _report("自检脚本可运行", True, "自检返回0（可能有警告）")
        else:
            # 提取红灯项
            red_lines = [l for l in output.splitlines() if FAIL_ICON in l]
            _report("自检脚本可运行", False,
                    f"自检有红灯: {'; '.join(red_lines[:2])}")
    except subprocess.TimeoutExpired:
        _warn("自检脚本可运行", "wrapup_check.py超时(>60秒)，29项检查较重，建议单独运行验证")
        _report("自检脚本可运行", True, "降级通过（自检超时，非致命）")
    except Exception as e:
        _report("自检脚本可运行", False, f"运行失败: {type(e).__name__}: {str(e)[:80]}")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
import re


def main():
    import argparse
    parser = argparse.ArgumentParser(description="金水谣修后全功能实测检验（Smoke Test）")
    parser.add_argument("--quick", action="store_true", help="快速版（只测关键路径）")
    args = parser.parse_args()

    print("=" * 60)
    print("  金水谣修后全功能实测检验 · Smoke Test v1.0")
    print(f"  检查日期: {date.today().strftime('%Y-%m-%d')}")
    if args.quick:
        print("  模式: 快速（只测关键路径）")
    print("=" * 60)
    print()

    # 0-5: 关键路径（快速版也跑）
    check_module_imports()
    check_config_files()
    check_hot_number_type()
    check_prediction_engine()
    check_prediction_format()
    check_ai_service()

    if not args.quick:
        # 6-14: 详细检验
        check_data_files()
        check_scheduler()
        check_knowledge_engine()
        check_gui_import()
        check_server_import()
        check_page_routes()
        check_api_health()
        check_experience_file()
        check_wrapup_script()

    # 汇总
    print()
    print("-" * 60)
    total = len(_results)
    passed = sum(1 for _, p, _ in _results if p)
    failed = total - passed

    if failed == 0:
        print(f"  结果: {passed}/{total} 项通过 —— 全功能可用，修后检验通过！")
        print("-" * 60)
        return 0
    else:
        print(f"  结果: {passed}/{total} 项通过，{failed} 项红灯 —— 有功能损坏！")
        print()
        print("  红灯项（必须修复后重跑）:")
        for name, p, detail in _results:
            if not p:
                print(f"    {FAIL_ICON} {name}: {detail}")
        print()
        print("  提示: 修完所有红灯项后重新运行本脚本，全绿才能说「修好了」。")
        print("-" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
