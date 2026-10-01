# -*- coding: utf-8 -*-
"""
金水谣系统 - 文件自动整理模块

提供项目文件的自动整理功能，包括缓存清理、日志归档、
孤立文件检测、目录结构验证和根目录整理。

功能清单:
    - clean_pycache:       递归删除所有 __pycache__ 目录
    - organize_logs:       整理日志文件，旧日志归档
    - check_orphan_files:  检测不在 import 链中的孤立 .py 文件
    - verify_structure:    验证项目目录结构完整性
    - tidy_project_root:   整理项目根目录，非核心文件移到 _archive
    - full_organize:       一键执行所有整理操作

Usage:
    from core.infra.file_organizer import FileOrganizer

    organizer = FileOrganizer()
    report = organizer.full_organize()
    print(report)
"""

import os
import re
import glob
import logging
import shutil
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger("jinshuiyao.file_organizer")


# ---------------------------------------------------------------------------
# 模块级常量（原 FileOrganizer 类常量）
# ---------------------------------------------------------------------------
_ROOT_WHITELIST_FILES = {
    "main.py", "config.py", "run_tests.py", "setup.py", "setup.cfg",
    "pyproject.toml", "requirements.txt", "README.md", ".gitignore", ".git",
}

_ROOT_WHITELIST_DIRS = {
    "core", "utils", "tests", "金水谣数据", "_archive", ".git", "__pycache__",
    ".idea", ".vscode", "venv", ".venv", "env",
}

_ORPHAN_SKIP_PATTERNS = {"__init__.py", "setup.py", "conftest.py"}

_ORPHAN_SKIP_SUFFIXES = (r"_test\.py$", r"test_.*\.py$")

_EXPECTED_STRUCTURE = {
    "core": {"description": "核心逻辑模块", "required": True},
    "utils": {"description": "工具模块", "required": True},
    "金水谣数据": {"description": "数据存储目录", "required": True},
}

_ORPHAN_SKIP_DIRS = {"_archive", "venv", ".venv", "env", "__pycache__",
                     ".git", "node_modules", ".idea", ".vscode", "金水谣数据"}


# ---------------------------------------------------------------------------
# 模块级函数（原 FileOrganizer 方法提取）
# ---------------------------------------------------------------------------
def _fo_get_dir_size_kb(dirpath: str) -> float:
    total = 0.0
    try:
        for root, _dirs, files in os.walk(dirpath):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename)) / 1024.0
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _fo_count_files_recursive(dirpath: str) -> int:
    count = 0
    try:
        for _root, _dirs, files in os.walk(dirpath):
            count += len(files)
    except OSError:
        pass
    return count


def _fo_ensure_archive_dir(project_dir: str) -> str:
    archive_dir = os.path.join(project_dir, "_archive")
    if not os.path.isdir(archive_dir):
        os.makedirs(archive_dir, exist_ok=True)
        logger.info("创建归档目录: %s", archive_dir)
    return archive_dir


def _fo_should_skip_orphan_check(filename: str) -> bool:
    if filename in _ORPHAN_SKIP_PATTERNS:
        return True
    for pattern in _ORPHAN_SKIP_SUFFIXES:
        if re.search(pattern, filename):
            return True
    return False


def _fo_clean_pycache(project_dir: str) -> dict:
    result = {"removed": 0, "freed_kb": 0.0}
    if not os.path.isdir(project_dir):
        logger.warning("项目目录不存在: %s", project_dir)
        return result
    for root, dirs, _files in os.walk(project_dir):
        if "__pycache__" in dirs:
            pycache_path = os.path.join(root, "__pycache__")
            dir_size_kb = _fo_get_dir_size_kb(pycache_path)
            file_count = _fo_count_files_recursive(pycache_path)
            try:
                shutil.rmtree(pycache_path)
                logger.info("删除 __pycache__: %s (%.1f KB, %d 个文件)",
                            pycache_path, dir_size_kb, file_count)
                result["removed"] += 1
                result["freed_kb"] += dir_size_kb
            except OSError as e:
                logger.error("删除 __pycache__ 失败: %s (%s)", pycache_path, e)
    result["freed_kb"] = round(result["freed_kb"], 2)
    logger.info("__pycache__ 清理完成: 删除 %d 个目录，释放 %.2f KB",
                result["removed"], result["freed_kb"])
    return result


def _fo_organize_logs(project_dir: str, max_log_files: int = 10) -> dict:
    result = {"archived": 0, "kept": 0}
    log_dir = os.path.join(project_dir, "金水谣数据", "log")
    archive_dir = os.path.join(log_dir, "archive")
    if not os.path.isdir(log_dir):
        logger.info("日志目录不存在，跳过整理: %s", log_dir)
        return result
    log_files = []
    for entry in os.listdir(log_dir):
        if entry == "archive":
            continue
        full_path = os.path.join(log_dir, entry)
        if os.path.isfile(full_path) and (entry.endswith(".log") or entry.endswith(".jsonl") or "log" in entry.lower()):
            try:
                log_files.append((os.path.getmtime(full_path), entry, full_path))
            except OSError:
                continue
    if not log_files:
        logger.info("未找到日志文件，跳过整理")
        return result
    log_files.sort(key=lambda x: x[0], reverse=True)
    kept_files = log_files[:max_log_files]
    archive_files = log_files[max_log_files:]
    result["kept"] = len(kept_files)
    if not archive_files:
        logger.info("日志文件数量未超限 (%d <= %d)，无需归档", len(log_files), max_log_files)
        return result
    os.makedirs(archive_dir, exist_ok=True)
    for mtime, filename, src_path in archive_files:
        dst_path = os.path.join(archive_dir, filename)
        if os.path.exists(dst_path):
            base, ext = os.path.splitext(filename)
            ts = datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
            dst_path = os.path.join(archive_dir, f"{base}_{ts}{ext}")
        try:
            shutil.move(src_path, dst_path)
            logger.info("归档日志: %s -> %s", src_path, dst_path)
            result["archived"] += 1
        except (OSError, shutil.Error) as e:
            logger.error("归档日志失败: %s (%s)", src_path, e)
    logger.info("日志整理完成: 归档 %d 个，保留 %d 个", result["archived"], result["kept"])
    return result


def _fo_collect_py_files(project_dir: str) -> Dict[str, List[str]]:
    """第一步：收集所有 .py 文件路径和对应的模块名。"""
    py_files: Dict[str, List[str]] = {}
    for root, dirs, files in os.walk(project_dir):
        rel_root = os.path.relpath(root, project_dir)
        first_dir = rel_root.split(os.sep)[0] if rel_root != "." else ""
        if first_dir in _ORPHAN_SKIP_DIRS:
            dirs.clear()
            continue
        for filename in files:
            if not filename.endswith(".py") or _fo_should_skip_orphan_check(filename):
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, project_dir)
            base_name = os.path.splitext(filename)[0]
            parts = rel_path.replace(os.sep, "/").split("/")
            module_name = ".".join(parts[:-1] + [base_name])
            py_files.setdefault(module_name, []).append(rel_path)
    return py_files


def _fo_collect_imported_modules(project_dir: str) -> set:
    """第二步：扫描所有 .py 文件，收集 import 语句引用的模块名集合。"""
    imported = set()
    for root, dirs, files in os.walk(project_dir):
        rel_root = os.path.relpath(root, project_dir)
        first_dir = rel_root.split(os.sep)[0] if rel_root != "." else ""
        if first_dir in _ORPHAN_SKIP_DIRS:
            dirs.clear()
            continue
        for filename in files:
            if not filename.endswith(".py"):
                continue
            try:
                with open(os.path.join(root, filename), "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            for match in re.finditer(r"^\s*import\s+([\w.]+)", content, re.MULTILINE):
                imported.add(match.group(1))
            for match in re.finditer(r"^\s*from\s+([\w.]+)\s+import", content, re.MULTILINE):
                imported.add(match.group(1))
    return imported


def _fo_check_orphan_files(project_dir: str) -> List[dict]:
    orphans: List[dict] = []
    if not os.path.isdir(project_dir):
        logger.warning("项目目录不存在: %s", project_dir)
        return orphans
    py_files = _fo_collect_py_files(project_dir)
    if not py_files:
        logger.info("未找到 Python 源文件")
        return orphans
    imported_modules = _fo_collect_imported_modules(project_dir)
    for module_name, file_paths in py_files.items():
        is_imported = module_name in imported_modules
        if not is_imported:
            parts = module_name.split(".")
            for i in range(1, len(parts)):
                if ".".join(parts[:i]) in imported_modules:
                    is_imported = True
                    break
        if not is_imported:
            for fp in file_paths:
                if fp.endswith("__init__.py"):
                    pkg_name = module_name.rsplit(".", 1)[0] if "." in module_name else None
                    if pkg_name and pkg_name in imported_modules:
                        is_imported = True
                        break
        if not is_imported:
            for fp in file_paths:
                dir_of_file = os.path.dirname(fp).replace(os.sep, "/")
                if dir_of_file == ".":
                    dir_of_file = ""
                if dir_of_file and (dir_of_file in imported_modules or
                                    any(m.startswith(dir_of_file + ".") for m in imported_modules)):
                    is_imported = True
                    break
        if not is_imported:
            for fp in file_paths:
                orphans.append({"file": fp, "reason": "未被任何 import 语句引用"})
    logger.info("孤立文件检测完成: 发现 %d 个孤立文件", len(orphans))
    for orphan in orphans:
        logger.debug("  孤立文件: %s - %s", orphan["file"], orphan["reason"])
    return orphans


def _fo_verify_structure(project_dir: str) -> dict:
    result = {"valid": True, "missing": [], "extra": [], "details": []}
    if not os.path.isdir(project_dir):
        logger.warning("项目目录不存在: %s", project_dir)
        result["valid"] = False
        result["missing"].append(project_dir)
        return result
    actual_entries = set(os.listdir(project_dir))
    expected_dirs = set(_EXPECTED_STRUCTURE.keys())
    for name, config in _EXPECTED_STRUCTURE.items():
        path = os.path.join(project_dir, name)
        exists = os.path.isdir(path) or os.path.isfile(path)
        result["details"].append({"name": name, "type": "dir",
                                  "description": config["description"],
                                  "exists": exists, "required": config["required"]})
        if not exists and config["required"]:
            result["valid"] = False
            result["missing"].append(name)
            logger.warning("缺失关键目录: %s (%s)", name, config["description"])
    all_expected = expected_dirs | _ROOT_WHITELIST_DIRS | _ROOT_WHITELIST_FILES
    extra_entries = sorted(e for e in actual_entries if e not in all_expected)
    if extra_entries:
        result["extra"] = extra_entries
        for entry in extra_entries:
            logger.debug("额外文件/目录: %s", entry)
    for name in expected_dirs:
        dir_path = os.path.join(project_dir, name)
        if os.path.isdir(dir_path) and _fo_count_files_recursive(dir_path) == 0:
            logger.warning("关键目录为空: %s", name)
    logger.info("目录结构验证完成: valid=%s, missing=%d, extra=%d",
                result["valid"], len(result["missing"]), len(result["extra"]))
    return result


def _fo_tidy_project_root(project_dir: str) -> dict:
    result = {"moved": 0, "kept": 0}
    if not os.path.isdir(project_dir):
        logger.warning("项目目录不存在: %s", project_dir)
        return result
    archive_dir = _fo_ensure_archive_dir(project_dir)
    try:
        entries = os.listdir(project_dir)
    except OSError as e:
        logger.error("无法列出项目根目录: %s (%s)", project_dir, e)
        return result
    all_whitelist = _ROOT_WHITELIST_FILES | _ROOT_WHITELIST_DIRS
    for entry in entries:
        if entry in all_whitelist:
            result["kept"] += 1
            continue
        entry_path = os.path.join(project_dir, entry)
        if not os.path.isfile(entry_path):
            result["kept"] += 1
            continue
        dst_path = os.path.join(archive_dir, entry)
        if os.path.exists(dst_path):
            base, ext = os.path.splitext(entry)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dst_path = os.path.join(archive_dir, f"{base}_{ts}{ext}")
        try:
            shutil.move(entry_path, dst_path)
            logger.info("归档根目录文件: %s -> %s", entry_path, dst_path)
            result["moved"] += 1
        except (OSError, shutil.Error) as e:
            logger.error("移动文件失败: %s (%s)", entry_path, e)
            result["kept"] += 1
    logger.info("根目录整理完成: 移动 %d 个文件，保留 %d 个", result["moved"], result["kept"])
    return result


def _fo_run_step(report: dict, step_name: str, fn, summary_map: dict) -> None:
    """执行单个整理步骤，捕获异常并写入 report。"""
    try:
        result = fn()
        report["steps"][step_name] = result
        for skey, rkey in summary_map.items():
            report["summary"][skey] = result[rkey]
    except Exception as e:
        logger.error("%s 异常: %s", step_name, e, exc_info=True)
        report["steps"][step_name] = {"error": str(e)}
        report["summary"]["errors"] += 1


def _fo_full_organize(project_dir: str) -> dict:
    logger.info("=" * 50)
    logger.info("开始执行项目文件全面整理")
    logger.info("项目目录: %s", project_dir)
    logger.info("=" * 50)
    report = {
        "timestamp": datetime.now().isoformat(),
        "project_dir": project_dir,
        "steps": {},
        "summary": {
            "pycache_removed": 0, "pycache_freed_kb": 0.0,
            "logs_archived": 0, "logs_kept": 0,
            "orphan_files": 0, "structure_valid": True,
            "root_files_moved": 0, "root_files_kept": 0, "errors": 0,
        },
    }
    s = report["summary"]
    _fo_run_step(report, "clean_pycache", lambda: _fo_clean_pycache(project_dir),
                 {"pycache_removed": "removed", "pycache_freed_kb": "freed_kb"})
    _fo_run_step(report, "organize_logs", lambda: _fo_organize_logs(project_dir),
                 {"logs_archived": "archived", "logs_kept": "kept"})
    _fo_run_step(report, "check_orphan_files", lambda: _fo_check_orphan_files(project_dir),
                 {})
    if "check_orphan_files" in report["steps"] and isinstance(report["steps"]["check_orphan_files"], list):
        s["orphan_files"] = len(report["steps"]["check_orphan_files"])
    _fo_run_step(report, "verify_structure", lambda: _fo_verify_structure(project_dir),
                 {"structure_valid": "valid"})
    _fo_run_step(report, "tidy_project_root", lambda: _fo_tidy_project_root(project_dir),
                 {"root_files_moved": "moved", "root_files_kept": "kept"})
    logger.info("=" * 50)
    logger.info("项目文件整理完成: __pycache__=%d(%.2fKB) 日志归档=%d 保留=%d 孤立=%d 结构=%s 根移动=%d 保留=%d 错误=%d",
                s["pycache_removed"], s["pycache_freed_kb"], s["logs_archived"],
                s["logs_kept"], s["orphan_files"],
                "通过" if s["structure_valid"] else "不通过",
                s["root_files_moved"], s["root_files_kept"], s["errors"])
    logger.info("=" * 50)
    return report


class FileOrganizer:
    """金水谣项目文件自动整理器（方法委托模块级函数）。"""

    def __init__(self, project_dir: Optional[str] = None):
        if project_dir is None:
            self.project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.project_dir = os.path.abspath(project_dir)

    def clean_pycache(self) -> dict:
        return _fo_clean_pycache(self.project_dir)

    def organize_logs(self, max_log_files: int = 10) -> dict:
        return _fo_organize_logs(self.project_dir, max_log_files)

    def check_orphan_files(self) -> List[dict]:
        return _fo_check_orphan_files(self.project_dir)

    def verify_structure(self) -> dict:
        return _fo_verify_structure(self.project_dir)

    def tidy_project_root(self) -> dict:
        return _fo_tidy_project_root(self.project_dir)

    def full_organize(self) -> dict:
        return _fo_full_organize(self.project_dir)


# ---------------------------------------------------------------------------
# 模块自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("金水谣 file_organizer 模块自测")
    print("=" * 60)

    # 创建临时测试项目目录
    with tempfile.TemporaryDirectory() as tmpdir:
        test_project = tmpdir

        # 创建项目结构
        os.makedirs(os.path.join(test_project, "core"), exist_ok=True)
        os.makedirs(os.path.join(test_project, "utils"), exist_ok=True)
        os.makedirs(os.path.join(test_project, "金水谣数据", "log"), exist_ok=True)

        # 创建 __pycache__
        pycache_dir = os.path.join(test_project, "core", "__pycache__")
        os.makedirs(pycache_dir, exist_ok=True)
        pyc_file = os.path.join(pycache_dir, "test.cpython-39.pyc")
        with open(pyc_file, "wb") as f:
            f.write(b"\x00" * 100)

        # 创建日志文件
        log_dir = os.path.join(test_project, "金水谣数据", "log")
        for i in range(15):
            log_file = os.path.join(log_dir, f"app_{i:03d}.log")
            with open(log_file, "w") as f:
                f.write(f"log entry {i}\n")
            # 设置不同的修改时间
            mtime = datetime(2026, 7, 1, 0, 0, i * 3600).timestamp()
            os.utime(log_file, (mtime, mtime))

        # 创建孤立 .py 文件
        orphan_file = os.path.join(test_project, "core", "orphan_module.py")
        with open(orphan_file, "w") as f:
            f.write("# This file is not imported by anything\nprint('hello')\n")

        # 创建一个被 import 的文件
        used_file = os.path.join(test_project, "core", "used_module.py")
        with open(used_file, "w") as f:
            f.write("# This file is imported\nx = 1\n")

        # 创建一个引用 used_module 的文件
        importer_file = os.path.join(test_project, "core", "importer.py")
        with open(importer_file, "w") as f:
            f.write("from core.used_module import x\n")

        # 创建 __init__.py
        with open(os.path.join(test_project, "core", "__init__.py"), "w") as f:
            f.write("")

        # 创建根目录下的杂散文件
        stray_file = os.path.join(test_project, "notes.txt")
        with open(stray_file, "w") as f:
            f.write("some notes\n")

        # 运行测试
        organizer = FileOrganizer(project_dir=test_project)

        print("\n--- 测试1: 清理 __pycache__ ---")
        r1 = organizer.clean_pycache()
        print(f"  结果: {r1}")
        assert r1["removed"] == 1, "应删除1个 __pycache__ 目录"
        assert not os.path.isdir(pycache_dir), "__pycache__ 应被删除"

        print("\n--- 测试2: 整理日志 ---")
        r2 = organizer.organize_logs(max_log_files=10)
        print(f"  结果: {r2}")
        assert r2["archived"] == 5, "应归档5个旧日志"
        assert r2["kept"] == 10, "应保留10个新日志"

        print("\n--- 测试3: 检测孤立文件 ---")
        r3 = organizer.check_orphan_files()
        print(f"  结果: 发现 {len(r3)} 个孤立文件")
        for o in r3:
            print(f"    {o['file']}: {o['reason']}")

        print("\n--- 测试4: 验证目录结构 ---")
        r4 = organizer.verify_structure()
        print(f"  结果: valid={r4['valid']}, missing={r4['missing']}, extra={r4['extra']}")

        print("\n--- 测试5: 整理根目录 ---")
        r5 = organizer.tidy_project_root()
        print(f"  结果: {r5}")
        assert r5["moved"] >= 1, "应至少移动1个非核心文件"

        print("\n--- 测试6: 一键整理 ---")
        # 重新创建测试数据
        os.makedirs(pycache_dir, exist_ok=True)
        stray_file2 = os.path.join(test_project, "notes2.txt")
        with open(stray_file2, "w") as f:
            f.write("more notes\n")
        r6 = organizer.full_organize()
        print(f"  汇总: {r6['summary']}")

    print("\n" + "=" * 60)
    print("自测完成")
    print("=" * 60)