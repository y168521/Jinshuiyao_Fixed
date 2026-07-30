#!/usr/bin/env python3
"""
金水谣 AST 自定义扫描器 — 代码审查 Pipeline 第二层
=================================================
扫描项目特有的问题模式，ruff 不覆盖的领域级规则：
  1. 天枢残留引用（TianShu/Tianshuiyao 悬空）
  2. 裸 except / except Exception 过宽捕获
  3. 模块边界违反（跨域直接 import）
  4. 共享资源无锁（全局 dict/set 读-改-写未加锁）
  5. 状态恢复缺失（try 内改状态无 finally 恢复）
  6. 硬编码密钥/路径
  7. 线程安全隐患（非线程安全容器 + 全局单例无保护）

用法:
  py -3 tools/ast_checker.py                  # 全量扫描
  py -3 tools/ast_checker.py --quick          # 快速扫描（仅致命项）
  py -3 tools/ast_checker.py --diff           # 仅扫描 git 改动文件
  py -3 tools/ast_checker.py --json           # JSON 输出（CI/CD 用）
  py -3 tools/ast_checker.py --severity P0    # 仅显示 P0 级问题

输出:
  🔴 P0 = 必须立即修复（安全/并发/数据完整性）
  🟡 P1 = 本周修复（可维护性/命名/规范）
  🟢 P2 = 有空再修（风格/优化建议）
"""

import ast
import os
import re
import sys
import json
import pathlib
import argparse
import importlib.util
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

# ─── 项目根目录 ───
ROOT = pathlib.Path(__file__).resolve().parent.parent

# ─── 扫描目录（按模块域划分）───
SCAN_DIRS = [
    "core", "engines", "domains", "controllers", "fetchers",
    "filters", "gui", "knowledge", "utils", "backtesting",
    "sync", "server", "smart_coder", "importers", "models",
]

# ─── 模块边界规则：哪些域可以 import 哪些域 ───
# 规则：上游域只能 import 下游域，不能反向
DOMAIN_HIERARCHY = {
    "utils":     [],                           # 最底层，不 import 任何域
    "core":      ["utils"],                    # 只依赖 utils
    "fetchers":  ["core", "utils"],            # 数据获取层
    "filters":   ["core", "utils"],            # 数据过滤层
    "engines":   ["core", "utils", "filters"],  # 引擎层
    "domains":   ["core", "engines", "utils", "fetchers", "filters"],  # 业务域
    "controllers": ["domains", "core", "utils"],  # 控制层
    "knowledge": ["core", "utils"],            # 知识层
    "gui":       ["controllers", "domains", "core", "utils"],  # GUI层
    "server":    ["controllers", "domains", "core", "utils", "knowledge"],  # 服务层
    "backtesting": ["domains", "core", "utils", "engines"],
    "sync":      ["core", "utils"],
    "smart_coder": ["core", "utils"],
    "importers": ["core", "utils"],
    "models":    ["utils"],
}

# ─── 天枢残留关键词 ───
TIANSHU_KEYWORDS = [
    "TianShu", "Tianshuiyao", "tianshu", "tianshuiyao",
    "天枢", "guide_server", "GuideServer",
]

# ─── 硬编码密钥/路径模式 ───
HARDCODED_SECRET_PATTERNS = [
    re.compile(r'(?:api_key|secret|token|password|passwd)\s*=\s*["\'][^"\']+["\']', re.I),
    re.compile(r'sk-[a-f0-9]{20,}', re.I),  # DeepSeek key pattern
    re.compile(r'C:\\Users\\[^\\]+\\'),       # 硬编码用户路径
    re.compile(r'/home/[a-z]+/'),              # Linux 硬编码路径
]

# ─── 非线程安全容器 ───
# 只读常量（__all__, 规则表, 映射表等）不报 P0，仅可变的共享状态才报
NON_THREADSAFE_TYPES = {"set", "dict", "list"}

# ─── 只读常量白名单（不会被读-改-写，无需锁）───
READONLY_CONST_NAMES = {
    "__all__",  # 模块公开列表，只读
    "LOTTERY_RULES", "ENGINE_NAMES", "FORMAT_MAP", "SYMBOL_NAMES",
    "SOURCE_LABELS", "SOURCE_COLORS", "POS_NAMES", "DEFAULT_KEEP",
    "VIDEO_EXTS", "AUDIO_EXTS", "FILE_EXTS", "SKIP_DIRS", "SKIP_FILE_EXTS",
    "VIDEO_PLATFORM_KEYWORDS", "COPY_STYLES", "TTS_VOICES", "TOOL_DEFS",
    "PLATFORM_PATTERNS", "PLATFORM_NAMES", "EXCLUDED_LOTS",
    "_EMPTY_PREDICTIONS", "_EMPTY_BRAIN_STATE", "_EMPTY_MIROFISH_DB",
    "_DEFAULT_KEEP", "_POS_NAMES", "_FILE_EXTS",
    "FORMATS", "_default_keys", "CONFIG_",  # 只读配置
}

# ─── 可变共享状态标记（必须加锁）───
MUTABLE_STATE_NAMES = [
    "_registered_domains", "_ENGINE_REGISTRY", "_ENGINE_CACHE",
    "_ai_service", "_kb_engine", "_scheduler", "_task_store",
    "_FETCHERS", "_BREAKERS",  # circuit breaker registry
]

# ─── 全局单例标记 ───
GLOBAL_SINGLETON_NAMES = ["_ai_service", "_kb_engine", "_scheduler", "_task_store"]


class Issue:
    """扫描结果条目"""
    __slots__ = ("file", "line", "col", "severity", "rule", "message", "snippet")

    def __init__(self, file: str, line: int, col: int, severity: str,
                 rule: str, message: str, snippet: str = ""):
        self.file = file
        self.line = line
        self.col = col
        self.severity = severity   # P0 / P1 / P2
        self.rule = rule           # AST-xxx
        self.message = message
        self.snippet = snippet

    def to_dict(self):
        return {
            "file": self.file, "line": self.line, "col": self.col,
            "severity": self.severity, "rule": self.rule,
            "message": self.message, "snippet": self.snippet,
        }

    def __str__(self):
        icon = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}[self.severity]
        return f"{icon} {self.severity} | {self.rule} | {self.file}:{self.line} | {self.message}"


class ASTChecker(ast.NodeVisitor):
    """AST 级别扫描器（单文件）"""

    def __init__(self, filepath: str, source: str, quick: bool = False):
        self.filepath = filepath
        self.source = source
        self.source_lines = source.splitlines()
        self.quick = quick  # quick 模式仅扫 P0
        self.issues: List[Issue] = []
        self.imports: List[Tuple[str, int]] = []  # (module_name, line)
        self._func_depth = 0
        self._class_depth = 0

    # ─── 规则 AST-001: 天枢残留引用 ───
    def _check_tianshu(self, node, text_attr):
        if self.quick:
            return
        for kw in TIANSHU_KEYWORDS:
            if kw in text_attr:
                self.issues.append(Issue(
                    self.filepath, node.lineno if hasattr(node, 'lineno') else 0, 0,
                    "P1", "AST-001",
                    f"天枢残留引用: '{kw}' — 应替换为金水谣命名",
                    text_attr[:80],
                ))

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))
            self._check_tianshu(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append((node.module, node.lineno))
            self._check_tianshu(node, node.module)
        for alias in node.names:
            self._check_tianshu(node, alias.name)
        self.generic_visit(node)

    # ─── 规则 AST-002: 裸 except / 过宽捕获 ───
    def visit_ExceptHandler(self, node):
        if node.type is None:
            # 裸 except: pass
            self.issues.append(Issue(
                self.filepath, node.lineno, node.col_offset if hasattr(node, 'col_offset') else 0,
                "P0", "AST-002",
                "裸 except（无异常类型）— 吞掉所有异常无法定位问题",
                self._snippet(node.lineno),
            ))
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
            # except Exception: pass（过宽）
            # 检查是否只是 pass 或 logging
            body_is_simple = all(
                isinstance(n, ast.Pass) or
                (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and
                 isinstance(n.value.func, ast.Attribute) and
                 n.value.func.attr in ("log", "warning", "error", "debug", "exception", "info"))
                for n in node.body
            ) if node.body else True

            if body_is_simple and not self.quick:
                self.issues.append(Issue(
                    self.filepath, node.lineno, 0,
                    "P1", "AST-002",
                    "except Exception 过宽捕获 — 应缩小到具体异常类型",
                    self._snippet(node.lineno),
                ))
        self.generic_visit(node)

    # ─── 规则 AST-003: 状态恢复缺失（try 内改状态无 finally）───
    def visit_Try(self, node):
        # 检查 try 块内是否有赋值改全局/实例状态，但无 finally 恢复
        assignments_in_try = []
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id.startswith("_"):
                        assignments_in_try.append(target.id)

        if assignments_in_try and not node.finalbody:
            # quick 模式下，只有涉及已知全局单例才报 P0
            critical = any(a in GLOBAL_SINGLETON_NAMES for a in assignments_in_try)
            if self.quick and not critical:
                return
            sev = "P0" if critical else "P1"
            self.issues.append(Issue(
                self.filepath, node.lineno, 0,
                sev, "AST-003",
                f"try 内修改状态 {assignments_in_try} 但无 finally 恢复 — 异常后状态损坏",
                self._snippet(node.lineno),
            ))
        self.generic_visit(node)

    # ─── 规则 AST-004: 可变默认参数 ───
    def visit_FunctionDef(self, node):
        self._func_depth += 1
        for default in node.args.defaults + node.args.kw_defaults:
            if default and isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.issues.append(Issue(
                    self.filepath, node.lineno, 0,
                    "P1", "AST-004",
                    f"函数 {node.name} 使用可变默认参数 — 每次调用共享同一对象",
                    self._snippet(node.lineno),
                ))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)  # 同样规则

    # ─── 规则 AST-005: 线程安全隐患 ───
    def visit_Assign(self, node):
        # 检查全局赋值非线程安全容器
        if self._func_depth == 0 and self._class_depth == 0:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    # 只读常量白名单 → 降级为 P2 建议
                    value_type = self._get_container_type(node.value)
                    if value_type in NON_THREADSAFE_TYPES:
                        if name in MUTABLE_STATE_NAMES:
                            # 真正的可变共享状态 → P0
                            self.issues.append(Issue(
                                self.filepath, node.lineno, 0,
                                "P0", "AST-005",
                                f"全局可变 {value_type} {name} — 多线程共享须加锁保护",
                                self._snippet(node.lineno),
                            ))
                        elif name in READONLY_CONST_NAMES or name.isupper() or name.startswith("__"):
                            # 只读常量 → P2 建议（不影响功能）
                            if not self.quick:
                                self.issues.append(Issue(
                                    self.filepath, node.lineno, 0,
                                    "P2", "AST-005",
                                    f"全局 {value_type} {name} — 只读常量，加锁为可选最佳实践",
                                    self._snippet(node.lineno),
                                ))
                        else:
                            # 其他全局容器 → P1 需评估
                            if not self.quick:
                                self.issues.append(Issue(
                                    self.filepath, node.lineno, 0,
                                    "P1", "AST-005",
                                    f"全局 {value_type} {name} — 请确认是否只读；若会修改须加锁",
                                    self._snippet(node.lineno),
                                ))
        self.generic_visit(node)

    # ─── 规则 AST-006: 硬编码密钥/路径 ───
    def visit_Constant(self, node):
        if not isinstance(node.value, str):
            return
        if self.quick:
            return
        for pattern in HARDCODED_SECRET_PATTERNS:
            if pattern.search(node.value):
                self.issues.append(Issue(
                    self.filepath, node.lineno, node.col_offset if hasattr(node, 'col_offset') else 0,
                    "P0", "AST-006",
                    f"硬编码密钥或路径 — 应存入 ~/.jinshuiyao-secrets/ 或 paths.json",
                    node.value[:60],
                ))
                break
        self.generic_visit(node)

    # ─── 规则 AST-007: set/dict 切片越界 ───
    def visit_Subscript(self, node):
        # set 不支持切片/索引; dict 索引是合法但切片不是
        if isinstance(node.value, ast.Name):
            # 需要运行时类型信息，AST 无法完全确定
            # 仅标记可疑的切片操作
            if isinstance(node.slice, ast.Slice) and not self.quick:
                self.issues.append(Issue(
                    self.filepath, node.lineno, 0,
                    "P1", "AST-007",
                    f"对 {node.value.id} 使用切片 — 若是 set/dict 类型将崩溃",
                    self._snippet(node.lineno),
                ))
        self.generic_visit(node)

    # ─── 规则 AST-008: 函数复杂度估算 ───
    def _count_branches(self, node):
        count = 0
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                                  ast.With, ast.AsyncFor, ast.AsyncWith)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
            elif isinstance(child, ast.IfExp):
                count += 1
        return count

    def visit_FunctionDef(self, node):
        self._func_depth += 1
        # 复杂度（与上面重复定义，合并）
        if not self.quick:
            branches = self._count_branches(node)
            if branches > 15:
                self.issues.append(Issue(
                    self.filepath, node.lineno, 0,
                    "P1", "AST-008",
                    f"函数 {node.name} 估算复杂度 {branches} > 15 — 应拆分",
                    self._snippet(node.lineno),
                ))
        # 可变默认参数检查（上面已写，此处跳过避免重复）
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._class_depth += 1
        self.generic_visit(node)

    def leave_FunctionDef(self, node):
        self._func_depth -= 1

    def leave_ClassDef(self, node):
        self._class_depth -= 1

    # ─── 辅助 ───
    def _snippet(self, line: int) -> str:
        if 0 < line <= len(self.source_lines):
            return self.source_lines[line - 1].strip()[:120]
        return ""

    def _get_container_type(self, node) -> Optional[str]:
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.Set):
            return "set"
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id.lower() if node.func.id in {"Dict", "Set", "List", "dict", "set", "list"} else None
        return None


class ModuleBoundaryChecker:
    """模块边界违反检查（第三层）"""

    def check_file(self, filepath: str) -> List[Issue]:
        issues = []
        # 确定文件属于哪个域
        rel_path = pathlib.Path(filepath).relative_to(ROOT)
        parts = rel_path.parts
        if not parts:
            return issues
        domain = parts[0]
        if domain not in DOMAIN_HIERARCHY:
            return issues  # 不在扫描范围内的文件

        allowed_domains = DOMAIN_HIERARCHY[domain]
        allowed_domains.append(domain)  # 允许 import 自己域

        # 解析文件找 import
        try:
            source = open(filepath, encoding="utf-8", errors="ignore").read()
            tree = ast.parse(source, filepath)
        except (SyntaxError, OSError):
            return issues

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_domain = alias.name.split(".")[0]
                    if imported_domain in DOMAIN_HIERARCHY and imported_domain not in allowed_domains:
                        issues.append(Issue(
                            str(rel_path), node.lineno, 0,
                            "P1", "AST-009",
                            f"模块边界违反: {domain} import {imported_domain} — 仅允许 import {allowed_domains}",
                        ))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_domain = node.module.split(".")[0]
                    if imported_domain in DOMAIN_HIERARCHY and imported_domain not in allowed_domains:
                        issues.append(Issue(
                            str(rel_path), node.lineno, 0,
                            "P1", "AST-009",
                            f"模块边界违反: {domain} from {imported_domain} — 仅允许 import {allowed_domains}",
                        ))
        return issues


def scan_all(quick: bool = False) -> List[Issue]:
    """全量扫描"""
    all_issues = []
    py_files = []
    for d in SCAN_DIRS:
        dir_path = ROOT / d
        if dir_path.exists():
            for f in dir_path.rglob("*.py"):
                if "__pycache__" in f.parts or "_old_" in f.parts:
                    continue
                py_files.append(str(f))

    # 也扫描根目录 .py
    for f in ROOT.glob("*.py"):
        py_files.append(str(f))

    boundary_checker = ModuleBoundaryChecker()

    for filepath in py_files:
        try:
            source = open(filepath, encoding="utf-8", errors="ignore").read()
            tree = ast.parse(source, filepath)
        except (SyntaxError, OSError):
            continue

        checker = ASTChecker(filepath, source, quick)
        checker.visit(tree)
        all_issues.extend(checker.issues)

        # 模块边界检查（quick 模式跳过）
        if not quick:
            all_issues.extend(boundary_checker.check_file(filepath))

    # 源码级扫描（AST 无法做的）
    all_issues.extend(_text_level_scan(py_files, quick))

    return all_issues


def scan_diff(quick: bool = False) -> List[Issue]:
    """仅扫描 git 改动的文件"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        )
        changed = [f.strip() for f in result.stdout.splitlines() if f.strip().endswith(".py")]
    except Exception:
        # git 不可用时退回全量扫描
        print("[WARN] git 不可用，退回全量扫描")
        return scan_all(quick)

    if not changed:
        print("[INFO] 无改动文件，扫描跳过")
        return []

    all_issues = []
    boundary_checker = ModuleBoundaryChecker()

    for filepath in changed:
        full_path = str(ROOT / filepath)
        if not os.path.exists(full_path):
            continue
        try:
            source = open(full_path, encoding="utf-8", errors="ignore").read()
            tree = ast.parse(source, full_path)
        except (SyntaxError, OSError):
            continue

        checker = ASTChecker(full_path, source, quick)
        checker.visit(tree)
        all_issues.extend(checker.issues)

        if not quick:
            all_issues.extend(boundary_checker.check_file(full_path))

    all_issues.extend(_text_level_scan([str(ROOT / f) for f in changed if (ROOT / f).exists()], quick))
    return all_issues


def _text_level_scan(files: List[str], quick: bool) -> List[Issue]:
    """源码级扫描（AST 无法捕获的模式）"""
    issues = []
    for filepath in files:
        try:
            source = open(filepath, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        lines = source.splitlines()

        # AST-010: print() 残留（非 GUI/测试文件）
        if "gui/" not in filepath and "tests/" not in filepath and "tools/" not in filepath:
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if re.match(r'^print\s*\(', stripped) and not stripped.startswith("#"):
                    if quick:
                        continue
                    issues.append(Issue(
                        filepath, i, 0,
                        "P2", "AST-010",
                        "print() 残留 — 应改用 _safe_icon() 或 logging",
                        stripped[:80],
                    ))

        # AST-011: import *（星号导入）
        for i, line in enumerate(lines, 1):
            if re.search(r'from\s+\S+\s+import\s+\*', line):
                issues.append(Issue(
                    filepath, i, 0,
                    "P1", "AST-011",
                    "import * 星号导入 — 污染命名空间，难以追踪来源",
                    line.strip()[:80],
                ))

        # AST-012: 天枢残留文件名
        rel = filepath.replace(str(ROOT), "").lstrip("\\/").lstrip("/")
        for kw in ["tianshu", "tianshuiyao"]:
            if kw in rel.lower() and "jinshuiyao-secrets" not in rel:
                issues.append(Issue(
                    filepath, 0, 0,
                    "P1", "AST-012",
                    f"文件名含天枢残留 '{kw}' — 应改名",
                    rel,
                ))

    return issues


def main():
    parser = argparse.ArgumentParser(description="金水谣 AST 自定义扫描器")
    parser.add_argument("--quick", action="store_true", help="快速模式，仅扫 P0 级问题")
    parser.add_argument("--diff", action="store_true", help="仅扫描 git 改动文件")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--severity", choices=["P0", "P1", "P2"], help="仅显示指定级别")
    args = parser.parse_args()

    print("=" * 60)
    print("金水谣 AST 自定义扫描器 v1.0")
    print("=" * 60)

    if args.diff:
        issues = scan_diff(quick=args.quick)
    else:
        issues = scan_all(quick=args.quick)

    # 过滤级别
    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]

    # 按级别排序
    order = {"P0": 0, "P1": 1, "P2": 2}
    issues.sort(key=lambda i: (order.get(i.severity, 3), i.file, i.line))

    # 统计
    counts = defaultdict(int)
    for i in issues:
        counts[i.severity] += 1

    if args.json:
        print(json.dumps({
            "total": len(issues),
            "p0": counts["P0"],
            "p1": counts["P1"],
            "p2": counts["P2"],
            "issues": [i.to_dict() for i in issues],
        }, indent=2))
    else:
        print(f"\n扫描结果: {len(issues)} 个问题")
        print(f"  🔴 P0 (必须立即修): {counts['P0']}")
        print(f"  🟡 P1 (本周修):     {counts['P1']}")
        print(f"  🟢 P2 (有空再修):   {counts['P2']}")
        print()

        for i in issues[:100]:  # 最多显示100条
            print(str(i))

        if len(issues) > 100:
            print(f"\n... 还有 {len(issues) - 100} 条问题未显示（用 --json 查看全部）")

        # 规则分布
        rule_counts = defaultdict(int)
        for i in issues:
            rule_counts[i.rule] += 1
        print(f"\n规则分布:")
        for rule, cnt in sorted(rule_counts.items(), key=lambda x: -x[1]):
            print(f"  {rule}: {cnt}")

    # 返回码: P0 > 0 = 1, 否则 0
    return 1 if counts["P0"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
