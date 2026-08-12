# -*- coding: utf-8 -*-
"""
金水谣系统 - 全能型测试框架入口

一键运行全部测试，内置轻量测试运行器（不依赖pytest）。

使用方式:
    python run_tests.py              # 运行全部测试
    python run_tests.py --category P0  # 只运行数据安全测试
    python run_tests.py --file test_safe_json  # 只运行某个文件
    python run_tests.py --verbose     # 详细输出

测试分类:
    P0 - 数据安全测试 (safe_json)
    P1 - 启动自检测试 (health_check)
    P2 - 运行监控测试 (watchdog)
    P3 - 进化引擎测试 (evolution)
    P4 - 扩展接口测试 (plugin_manager)
    P5 - 同步管理测试 (sync_manager)
    回归 - 审计模块 (audit) + 智能大脑 (smart_brain)
"""

import os
import sys
import time
import importlib
import importlib.util
import traceback
import unittest

# ---------------------------------------------------------------------------
# 确保项目根目录在 sys.path 中
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


# ---------------------------------------------------------------------------
# 测试分类映射
# ---------------------------------------------------------------------------
TEST_CATEGORIES = {
    "P0": "数据安全测试",
    "P1": "启动自检测试",
    "P2": "运行监控测试",
    "P3": "进化引擎测试",
    "P4": "扩展接口测试",
    "P5": "同步管理测试",
}

# 文件 -> 分类映射（基于 tests/ 目录实际文件）
FILE_CATEGORY = {
    # P0 - 数据安全
    "test_safe_json": "P0",
    "test_data_truth_guard": "P0",
    "test_quality_pages": "P0",
    # P1 - 启动自检 / 配置
    "test_health_check": "P1",
    "test_config": "P1",
    "test_number_utils": "P1",
    # P2 - 运行监控 / 基础设施
    "test_watchdog": "P2",
    "test_circuit_breaker": "P2",
    "test_auto_systems": "P2",
    "test_scheduler": "P2",
    "test_file_watcher": "P2",
    "test_drift_detector": "P2",
    # P3 - 引擎测试
    "test_evolution": "P3",
    "test_engines": "P3",
    "test_uncertainty": "P3",
    # P4 - 扩展接口
    "test_plugin_manager": "P4",
    "test_video_extractor": "P4",
    "test_utils_extra": "P4",
    # P5 - 同步管理
    "test_sync_manager": "P5",
    "test_subsystem_isolation": "P5",
    # 回归 - AI / 知识
    "test_audit": "回归测试",
    "test_smart_brain": "回归测试",
    "test_ai_agent": "回归测试",
    "test_ai_service": "回归测试",
    "test_ai_test_generator": "回归测试",
    "test_ai_test_knowledge": "回归测试",
    "test_mirofish_db": "回归测试",
    "test_server_package": "回归测试",
    # 回归 - 预测 / 数据
    "test_prediction_service": "回归测试",
    "test_fetcher": "回归测试",
    "test_lottery_fetcher_cache": "回归测试",
    # 回归 - 业务域
    "test_cross_domain": "回归测试",
    "test_backtesting": "回归测试",
    "test_stock_domain": "回归测试",
    "test_stock_gui": "回归测试",
    "test_fund_domain": "回归测试",
    "test_fund_data_manager": "回归测试",
    "test_creator_domain": "回归测试",
    "test_domain_base": "回归测试",
}


# ===========================================================================
# 测试结果数据结构
# ===========================================================================

class TestResult:
    """单个测试用例的结果"""

    def __init__(self, name, filepath, status, duration=0.0, error_msg=None):
        self.name = name          # 测试函数名
        self.filepath = filepath  # 所在文件
        self.status = status      # "pass" / "fail" / "skip" / "error"
        self.duration = duration  # 耗时（秒）
        self.error_msg = error_msg  # 失败信息


# ===========================================================================
# 轻量级测试运行器
# ===========================================================================

class SimpleTestRunner:
    """轻量级测试运行器 - 不依赖 pytest"""

    def __init__(self):
        self.results = []          # TestResult 列表
        self._verbose = False
        self._total_time = 0.0

    # -------------------------------------------------------------------
    # 发现测试
    # -------------------------------------------------------------------

    def discover_tests(self, test_dir):
        """自动发现 test_*.py 文件（递归搜索子目录）

        参数:
            test_dir: 测试文件所在目录

        返回:
            list[str]: 测试文件路径列表，按名称排序
        """
        if not os.path.isdir(test_dir):
            print(f"[警告] 测试目录不存在: {test_dir}")
            return []

        files = []
        for root, dirs, fnames in os.walk(test_dir):
            for fname in sorted(fnames):
                if fname.startswith("test_") and fname.endswith(".py"):
                    files.append(os.path.join(root, fname))

        return files

    # -------------------------------------------------------------------
    # 运行测试
    # -------------------------------------------------------------------

    def run_test_file(self, filepath):
        """运行单个测试文件中的所有 test_* 函数

        参数:
            filepath: 测试文件路径

        返回:
            list[TestResult]: 该文件中所有测试的结果
        """
        file_results = []
        module_name = os.path.splitext(os.path.basename(filepath))[0]

        # 动态导入模块
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            result = TestResult(
                name=module_name,
                filepath=filepath,
                status="error",
                error_msg="无法加载模块",
            )
            self.results.append(result)
            return [result]

        module = importlib.util.module_from_spec(spec)

        try:
            spec.loader.exec_module(module)
        except SyntaxError as e:
            result = TestResult(
                name=module_name,
                filepath=filepath,
                status="error",
                error_msg=f"语法错误: {e}",
            )
            self.results.append(result)
            return [result]
        except Exception as e:
            result = TestResult(
                name=module_name,
                filepath=filepath,
                status="error",
                error_msg=f"导入失败: {str(e)}",
            )
            self.results.append(result)
            return [result]

        # 收集 test_* 函数（模块级函数）
        test_funcs = []
        for attr_name in sorted(dir(module)):
            if attr_name.startswith("test_") and callable(getattr(module, attr_name)):
                test_funcs.append(getattr(module, attr_name))

        # 收集 unittest.TestCase 子类中的 test_* 方法
        test_case_classes = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and issubclass(attr, unittest.TestCase)
                    and attr is not unittest.TestCase):
                test_case_classes.append(attr)

        for cls in test_case_classes:
            for method_name in sorted(dir(cls)):
                if method_name.startswith("test_") and callable(getattr(cls, method_name)):
                    # 创建包装函数，自动处理 setUp/setUpClass/tearDown/tearDownClass
                    def make_wrapper(cls, method_name):
                        def wrapper():
                            instance = cls()
                            try:
                                instance.setUp()
                                getattr(instance, method_name)()
                            finally:
                                try:
                                    instance.tearDown()
                                except Exception:
                                    pass
                        wrapper.__name__ = method_name
                        wrapper.__doc__ = getattr(cls, method_name).__doc__
                        wrapper._test_cls = cls  # 标记所属类
                        return wrapper
                    test_funcs.append(make_wrapper(cls, method_name))

        if self._verbose:
            print(f"  [发现] {module_name} -> {len(test_funcs)} 个测试函数（含{len(test_case_classes)}个TestCase类）")

        # 调用 setUpClass（每个类只调用一次）
        setupclass_done = set()
        for cls in test_case_classes:
            if hasattr(cls, "setUpClass") and cls not in setupclass_done:
                try:
                    cls.setUpClass()
                    setupclass_done.add(cls)
                except Exception as e:
                    print(f"  [WARN] {cls.__name__}.setUpClass() 失败: {e}")

        # 逐个运行
        try:
            for func in test_funcs:
                result = self._run_single_test(func, filepath)
                file_results.append(result)
                self.results.append(result)
        finally:
            # 调用 tearDownClass（每个类只调用一次）
            for cls in test_case_classes:
                if hasattr(cls, "tearDownClass") and cls in setupclass_done:
                    try:
                        cls.tearDownClass()
                    except Exception as e:
                        print(f"  [WARN] {cls.__name__}.tearDownClass() 失败: {e}")

        return file_results

    def _run_single_test(self, func, filepath):
        """运行单个测试函数"""
        name = func.__name__
        doc = func.__doc__ or ""

        if self._verbose:
            print(f"  [运行] {os.path.basename(filepath)}::{name}")

        start = time.time()
        try:
            func()
            elapsed = time.time() - start
            return TestResult(name, filepath, "pass", elapsed)
        except AssertionError as e:
            elapsed = time.time() - start
            return TestResult(name, filepath, "fail", elapsed, str(e))
        except Exception as e:
            elapsed = time.time() - start
            return TestResult(name, filepath, "error", elapsed, str(e))

    # -------------------------------------------------------------------
    # 运行全部
    # -------------------------------------------------------------------

    def run_all(self, test_dir, filter_category=None, filter_file=None):
        """运行全部测试（可选过滤）

        参数:
            test_dir:          测试目录
            filter_category:    按分类过滤 (如 "P0", "P1")
            filter_file:       按文件名过滤 (如 "test_safe_json")
        """
        files = self.discover_tests(test_dir)

        if not files:
            print("[警告] 未发现任何测试文件")
            return

        # 按过滤条件筛选
        if filter_file:
            files = [f for f in files if filter_file in os.path.basename(f)]

        if filter_category:
            files = [
                f for f in files
                if FILE_CATEGORY.get(
                    os.path.splitext(os.path.basename(f))[0]
                ) == filter_category
                or filter_category == "回归测试"
                and os.path.splitext(os.path.basename(f))[0] in FILE_CATEGORY
                and FILE_CATEGORY[os.path.splitext(os.path.basename(f))[0]] == "回归测试"
            ]

        if not files:
            print("[警告] 过滤后无匹配的测试文件")
            return

        start_total = time.time()

        # 按分类打印分组标题
        print()
        for category_name in ["P0", "P1", "P2", "P3", "P4", "P5"]:
            cat_label = TEST_CATEGORIES.get(category_name, "")
            cat_files = [
                f for f in files
                if FILE_CATEGORY.get(
                    os.path.splitext(os.path.basename(f))[0]
                ) == category_name
            ]
            if cat_files:
                print(f"  [{category_name}] {cat_label}")

        # 回归测试
        regression_files = [
            f for f in files
            if FILE_CATEGORY.get(
                os.path.splitext(os.path.basename(f))[0]
            ) == "回归测试"
        ]
        if regression_files:
            print("  [回归] 审计模块 + 智能大脑")

        print()

        # 运行
        for filepath in files:
            fname = os.path.basename(filepath)
            print(f"  >> {fname}")
            self.run_test_file(filepath)

        self._total_time = time.time() - start_total

    # -------------------------------------------------------------------
    # 报告
    # -------------------------------------------------------------------

    def print_report(self):
        """打印测试报告"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "pass")
        failed = sum(1 for r in self.results if r.status == "fail")
        errors = sum(1 for r in self.results if r.status == "error")
        skipped = sum(1 for r in self.results if r.status == "skip")

        print()
        print("=" * 60)

        # 逐条输出结果
        for r in self.results:
            fname = os.path.basename(r.filepath)
            if r.status == "pass":
                status_str = "[PASS]"
                detail_str = "OK"
            elif r.status == "fail":
                status_str = "[FAIL]"
                detail_str = "FAIL"
            elif r.status == "error":
                status_str = "[ERR!]"
                detail_str = "ERROR"
            else:
                status_str = "[SKIP]"
                detail_str = "SKIP"

            # 格式: [状态] 文件名::函数名 ..... 结果
            display_name = f"{fname}::{r.name}"
            padding = max(1, 50 - len(display_name))
            print(f"  {status_str} {display_name} {'.' * padding}{detail_str}")

            # 失败时打印错误信息
            if r.status in ("fail", "error") and r.error_msg:
                for line in r.error_msg.split("\n"):
                    print(f"         {line}")

        print()
        print("=" * 60)
        print("  金水谣系统 - 全能型测试报告")
        print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print()
        print(f"  总计: {total} 个测试")
        print(f"  通过: {passed}")
        print(f"  失败: {failed}")
        if errors:
            print(f"  错误: {errors}")
        if skipped:
            print(f"  跳过: {skipped}")
        print(f"  耗时: {self._total_time:.2f} 秒")
        print()

        # 按文件分组统计
        file_stats = {}
        for r in self.results:
            fname = os.path.basename(r.filepath)
            if fname not in file_stats:
                file_stats[fname] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
            file_stats[fname][r.status] = file_stats[fname].get(r.status, 0) + 1

        print("  --- 按文件统计 ---")
        for fname, stats in sorted(file_stats.items()):
            cat = FILE_CATEGORY.get(fname.replace(".py", ""), "")
            cat_str = f" [{cat}]" if cat else ""
            p = stats.get("pass", 0)
            f = stats.get("fail", 0)
            e = stats.get("error", 0)
            parts = []
            if p:
                parts.append(f"通过{p}")
            if f:
                parts.append(f"失败{f}")
            if e:
                parts.append(f"错误{e}")
            print(f"  {fname}{cat_str}: {', '.join(parts)}")

        print()
        print("=" * 60)

        # 返回退出码
        if failed > 0 or errors > 0:
            return 1
        return 0


# ===========================================================================
# HTML报告生成
# ===========================================================================

def generate_html_report(results, total_time, file_stats):
    """生成可视化HTML测试报告

    参数:
        results:     TestResult列表
        total_time:  总耗时（秒）
        file_stats:  按文件统计的字典

    返回:
        str: HTML报告文件路径
    """
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    errors = sum(1 for r in results if r.status == "error")
    skipped = sum(1 for r in results if r.status == "skip")

    pass_rate = (passed / total * 100) if total > 0 else 0
    time_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # 生成图表
    chart_data = {
        "total": total, "passed": passed, "failed": failed,
        "errors": errors, "skipped": skipped, "pass_rate": round(pass_rate, 1),
        "total_time": round(total_time, 2),
        "timestamp": time_str,
    }

    # 构建测试用例列表HTML
    test_rows = ""
    for r in results:
        fname = r.filepath.replace("\\", "/")
        status_icon = "✅" if r.status == "pass" else "❌" if r.status == "fail" else "⚠️" if r.status == "error" else "⏭️"
        display_name = f"{os.path.basename(r.filepath)}::{r.name}"
        duration_str = f"{r.duration:.2f}s" if r.duration > 0.01 else "<0.01s"
        error_html = ""
        if r.status in ("fail", "error") and r.error_msg:
            error_html = f'<div class="test-error">{r.error_msg.replace("<", "&lt;").replace(">", "&gt;")}</div>'
        test_rows += f'''
        <div class="test-item {r.status}">
          <div class="test-status">{status_icon}</div>
          <div class="test-name">{display_name}</div>
          <div class="test-duration">{duration_str}</div>{error_html}
        </div>'''

    # 构建文件统计HTML
    file_rows = ""
    for fname, stats in sorted(file_stats.items()):
        cat = FILE_CATEGORY.get(fname.replace(".py", ""), "")
        cat_tag = f'<span class="file-cat">[{cat}]</span>' if cat else ""
        p = stats.get("pass", 0)
        f = stats.get("fail", 0)
        e = stats.get("error", 0)
        parts = []
        if p:
            parts.append(f'<span class="status-pass">\u2713{p}</span>')
        if f:
            parts.append(f'<span class="status-fail">\u2717{f}</span>')
        if e:
            parts.append(f'<span class="status-error">\u26a0{e}</span>')
        file_rows += f'''
        <div class="file-row">
          <span class="file-name">{fname} {cat_tag}</span>
          <span class="file-stats">{", ".join(parts)}</span>
        </div>'''

    pass_color = "high" if pass_rate >= 90 else "medium" if pass_rate >= 70 else "low"
    fail_degree = min(180 * (failed + errors) / max(total, 1) * 2, 180)

    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>\u5929\u67a2\u7cfb\u7edf - \u6d4b\u8bd5\u62a5\u544a</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700;900&display=swap');
    :root {
      --bg: #0a0e17; --bg2: #111827; --bg3: #1f2937;
      --ink: #f9fafb; --muted: #9ca3af; --dim: #6b7280;
      --rule: #374151; --accent: #06b6d4;
      --green: #2D8B7E; --red: #C8755A; --amber: #f59e0b;
      --purple: #C9A96E; --font: 'Noto Sans SC', system-ui, sans-serif;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: var(--font); background: var(--bg); color: var(--ink); line-height: 1.6; }
    body::before {
      content: ''; position: fixed; inset: 0;
      background: radial-gradient(ellipse 800px 600px at 15% 20%, rgba(6,182,212,0.06), transparent),
                  radial-gradient(ellipse 600px 500px at 85% 70%, rgba(201,169,110,0.05), transparent);
      pointer-events: none; z-index: 0;
    }
    .container { position: relative; z-index: 1; max-width: 1000px; margin: 0 auto; padding: 2rem; }

    .hero { text-align: center; padding: 2rem 0 1rem; }
    .hero-badge {
      display: inline-block; background: rgba(45,139,126,0.12);
      border: 1px solid rgba(45,139,126,0.25); border-radius: 20px;
      padding: 0.2rem 1rem; font-size: 0.75rem; color: var(--green); margin-bottom: 0.8rem; font-weight: 500;
    }
    .hero h1 {
      font-size: 2.2rem; font-weight: 900;
      background: linear-gradient(135deg, var(--green), var(--accent), var(--amber));
      -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    }
    .hero-time { color: var(--muted); font-size: 0.85rem; margin-top: 0.3rem; }

    .rate-section { display: flex; align-items: center; justify-content: center; gap: 3rem; margin: 2rem 0; flex-wrap: wrap; }
    .ring-chart { position: relative; width: 180px; height: 180px; }
    .ring-chart svg { transform: rotate(-90deg); }
    .ring-text { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; }
    .ring-percent { font-size: 2.2rem; font-weight: 900; line-height: 1; }
    .ring-percent.high { color: var(--green); }
    .ring-percent.medium { color: var(--amber); }
    .ring-percent.low { color: var(--red); }
    .ring-label { font-size: 0.75rem; color: var(--muted); margin-top: 0.3rem; }

    .stats-box { display: flex; flex-direction: column; gap: 0.8rem; }
    .stat-row { display: flex; align-items: center; gap: 0.6rem; font-size: 1rem; }
    .stat-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
    .stat-dot.pass { background: var(--green); }
    .stat-dot.fail { background: var(--red); }
    .stat-dot.skip { background: var(--dim); }
    .stat-num { font-weight: 700; font-size: 1.3rem; margin-left: auto; min-width: 30px; text-align: right; }
    .stat-num.pass { color: var(--green); }
    .stat-num.fail { color: var(--red); }
    .stat-num.skip { color: var(--dim); }

    .section-title { font-size: 1.1rem; font-weight: 700; margin: 2rem 0 1rem; border-bottom: 1px solid var(--rule); padding-bottom: 0.5rem; }
    .test-item { display: flex; align-items: center; gap: 0.8rem; padding: 0.7rem 1rem; background: var(--bg2); border: 1px solid var(--rule); border-radius: 10px; margin-bottom: 0.4rem; font-size: 0.88rem; flex-wrap: wrap; }
    .test-item:hover { border-color: rgba(6,182,212,0.3); }
    .test-item.pass { border-left: 3px solid var(--green); }
    .test-item.fail { border-left: 3px solid var(--red); }
    .test-item.error { border-left: 3px solid var(--amber); }
    .test-item.skip { border-left: 3px solid var(--dim); }
    .test-status { font-size: 1.1rem; flex-shrink: 0; width: 24px; text-align: center; }
    .test-name { flex: 1; font-family: 'Courier New', monospace; font-size: 0.82rem; color: var(--ink); }
    .test-duration { color: var(--dim); font-size: 0.78rem; flex-shrink: 0; }
    .test-error { width: 100%; color: var(--red); font-size: 0.8rem; padding: 0.5rem; background: rgba(200,117,90,0.08); border-radius: 6px; margin-top: 0.3rem; font-family: 'Courier New', monospace; }

    .file-stats-section { margin: 2rem 0; }
    .file-row { display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 1rem; background: var(--bg2); border: 1px solid var(--rule); border-radius: 8px; margin-bottom: 0.3rem; font-size: 0.85rem; }
    .file-cat { color: var(--accent); font-size: 0.75rem; }
    .status-pass { color: var(--green); }
    .status-fail { color: var(--red); }
    .status-error { color: var(--amber); }

    .action-bar { display: flex; justify-content: center; gap: 1rem; margin: 2rem 0; flex-wrap: wrap; }
    .btn { padding: 0.65rem 1.5rem; border: none; border-radius: 10px; font-family: var(--font); font-size: 0.9rem; font-weight: 600; cursor: pointer; transition: all 0.2s; text-decoration: none; display: inline-flex; align-items: center; gap: 0.4rem; }
    .btn:active { transform: scale(0.97); }
    .btn-primary { background: var(--green); color: var(--bg); }
    .btn-primary:hover { background: #4ade80; }
    .btn-ghost { background: var(--bg3); color: var(--muted); border: 1px solid var(--rule); }
    .btn-ghost:hover { border-color: var(--accent); color: var(--ink); }

    .footer-bar { text-align: center; padding: 2rem 0 1rem; color: var(--dim); font-size: 0.8rem; }
  </style>
</head>
<body>
<div class="container">
  <div class="hero">
    <div class="hero-badge">\u2605 \u5168\u90e8\u6d4b\u8bd5\u5df2\u5b8c\u6210</div>
    <h1>\u5929\u67a2\u7cfb\u7edf \u6d4b\u8bd5\u62a5\u544a</h1>
    <div class="hero-time">%(time_str)s</div>
  </div>

  <div class="rate-section">
    <div class="ring-chart">
      <svg width="180" height="180" viewBox="0 0 180 180">
        <circle cx="90" cy="90" r="78" fill="none" stroke="var(--bg3)" stroke-width="12"/>
        <circle cx="90" cy="90" r="78" fill="none" stroke="%%COLOR%%" stroke-width="12"
          stroke-dasharray="%%DASH%%" stroke-dashoffset="0" stroke-linecap="round"
          style="transition: stroke-dasharray 1s ease;"/>
      </svg>
      <div class="ring-text">
        <div class="ring-percent %(pass_color)s">%(pass_rate)s%</div>
        <div class="ring-label">\u901a\u8fc7\u7387</div>
      </div>
    </div>
    <div class="stats-box">
      <div class="stat-row"><div class="stat-dot pass"></div>\u901a\u8fc7<div class="stat-num pass">%(passed)s</div></div>
      <div class="stat-row"><div class="stat-dot fail"></div>\u5931\u8d25<div class="stat-num fail">%(failed)s</div></div>
      <div class="stat-row"><div class="stat-dot skip"></div>\u9519\u8bef<div class="stat-num fail">%(errors)s</div></div>
      <div class="stat-row" style="color:var(--muted)">\u603b\u8017\u65f6<div class="stat-num" style="color:var(--muted)">%(total_time)s\u79d2</div></div>
    </div>
  </div>

  <div class="section-title">\u6d4b\u8bd5\u7ed3\u679c\u5217\u8868</div>
  %(test_rows)s

  <div class="file-stats-section">
    <div class="section-title">\u6309\u6587\u4ef6\u7edf\u8ba1</div>
    %(file_rows)s
  </div>

  <div class="action-bar">
    <button class="btn btn-primary" onclick="window.location.reload()">\U0001f504 \u91cd\u65b0\u8fd0\u884c</button>
    <button class="btn btn-ghost" onclick="window.print()">\U0001f5a8 \u6253\u5370/\u5bfc\u51faPDF</button>
  </div>

  <div class="footer-bar">
    \u5929\u67a2\u7cfb\u7edf &middot; \u5168\u80fd\u578b\u6d4b\u8bd5\u6846\u67b6 &middot; \u4e0d\u4f9d\u8d56pytest &middot; %(total)d \u4e2a\u6d4b\u8bd5
  </div>
</div>
</body>
</html>'''

    # 替换变量
    total_val = total
    pass_color_val = pass_color
    pass_rate_val = round(pass_rate, 1)
    pass_val = passed
    fail_val = failed
    err_val = errors
    time_str_val = time_str
    total_time_val = round(total_time, 2)

    # SVG颜色和弧线
    if pass_rate >= 90:
        svg_color = "var(--green)"
    elif pass_rate >= 70:
        svg_color = "var(--amber)"
    else:
        svg_color = "var(--red)"

    circumference = 2 * 3.14159 * 78
    dash = circumference * pass_rate / 100
    dash_str = f"{dash} {circumference - dash}"

    substitutions = {
        "%%COLOR%%": svg_color,
        "%%DASH%%": dash_str,
        "%(pass_color)s": pass_color,
        "%(pass_rate)s": pass_rate_val,
        "%(passed)s": pass_val,
        "%(failed)s": fail_val,
        "%(errors)s": err_val,
        "%(total_time)s": total_time_val,
        "%(time_str)s": time_str_val,
        "%(test_rows)s": test_rows,
        "%(file_rows)s": file_rows,
        "%(total)d": total_val,
    }

    for key, value in substitutions.items():
        html = html.replace(key, str(value))

    # 保存HTML（统一放 金水谣数据/log/test_reports/，与运行时日志同处）
    report_dir = os.path.join(os.path.dirname(_SCRIPT_DIR), "金水谣数据", "log", "test_reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"test_report_{time.strftime('%Y%m%d_%H%M%S')}.html")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 同时保存最新版本
    latest_path = os.path.join(report_dir, "test_report_latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)

    print()
    print(f"  [HTML报告] 已生成: {report_path}")
    print()

    return report_path

def parse_args(args):
    """简单的命令行参数解析

    支持:
        --category P0/P1/P2/P3/P4/P5/回归测试
        --file test_safe_json
        --verbose / -v
        --html / --no-html  生成/跳过HTML报告
    """
    options = {
        "category": None,
        "file": None,
        "verbose": False,
        "html": True,
    }

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--category" and i + 1 < len(args):
            options["category"] = args[i + 1]
            i += 2
        elif arg == "--file" and i + 1 < len(args):
            options["file"] = args[i + 1]
            i += 2
        elif arg in ("--verbose", "-v"):
            options["verbose"] = True
            i += 1
        elif arg == "--html":
            options["html"] = True
            i += 1
        elif arg == "--no-html":
            options["html"] = False
            i += 1
        elif arg in ("--help", "-h"):
            print_usage()
            sys.exit(0)
        else:
            i += 1

    return options


def print_usage():
    """打印使用帮助"""
    print("""
金水谣系统 - 全能型测试框架
====================================

使用方式:
    python run_tests.py                          运行全部测试
    python run_tests.py --category P0            只运行数据安全测试
    python run_tests.py --category P1            只运行启动自检测试
    python run_tests.py --category P2            只运行运行监控测试
    python run_tests.py --category P3            只运行进化引擎测试
    python run_tests.py --category P4            只运行扩展接口测试
    python run_tests.py --category P5            只运行同步管理测试
    python run_tests.py --file test_safe_json    只运行 safe_json 测试
    python run_tests.py --verbose                详细输出
    python run_tests.py --no-html                跳过HTML报告生成
    python run_tests.py --help                  显示帮助

测试分类:
    P0 - 数据安全测试 (safe_json原子写入、备份恢复、CRC校验)
    P1 - 启动自检测试 (health_check各项检查)
    P2 - 运行监控测试 (watchdog心跳、异常捕获)
    P3 - 进化引擎测试 (规则升级、经验挖掘)
    P4 - 扩展接口测试 (插件加载/卸载)
    P5 - 同步管理测试 (离线队列、网络检测)
    回归 - 审计模块 (audit) + 智能大脑 (smart_brain)

HTML报告: 默认生成，保存在 金水谣数据/test_reports/ 目录
         --no-html 跳过生成
""")


# ===========================================================================
# 主入口
# ===========================================================================

def main():
    """主入口函数"""
    # 解析命令行参数
    options = parse_args(sys.argv[1:])

    # 横幅
    print()
    print("=" * 60)
    print("  金水谣系统 - 全能型测试框架")
    print("  不依赖 pytest，纯 Python 标准库")
    print("=" * 60)

    if options["verbose"]:
        print("  [模式] 详细输出")
    if options["category"]:
        print(f"  [过滤] 分类: {options['category']} ({TEST_CATEGORIES.get(options['category'], '未知')})")
    if options["file"]:
        print(f"  [过滤] 文件: {options['file']}")
    if options["html"]:
        print("  [模式] 生成HTML报告")
    else:
        print("  [模式] 跳过HTML报告")

    # 测试目录（tools/tests 不存在；真源为仓库根 tests/，pytest 风格。
    # 注：全量测试请优先使用 pytest（gate.py --test 已改走 pytest 轨道））
    test_dir = os.path.join(os.path.dirname(_SCRIPT_DIR), "tests")

    # 创建运行器
    runner = SimpleTestRunner()
    runner._verbose = options["verbose"]

    # 运行测试
    runner.run_all(
        test_dir,
        filter_category=options["category"],
        filter_file=options["file"],
    )

    # 打印报告
    exit_code = runner.print_report()

    # 生成HTML报告
    if options["html"] and runner.results:
        # 构建文件统计
        file_stats = {}
        for r in runner.results:
            fname = os.path.basename(r.filepath)
            if fname not in file_stats:
                file_stats[fname] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
            file_stats[fname][r.status] = file_stats[fname].get(r.status, 0) + 1

        generate_html_report(runner.results, runner._total_time, file_stats)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
