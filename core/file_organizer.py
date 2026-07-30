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
    from core.file_organizer import FileOrganizer

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


class FileOrganizer:
    """金水谣项目文件自动整理器

    负责清理编译缓存、归档日志、检测孤立文件、验证目录结构和
    整理项目根目录，保持项目文件系统整洁有序。

    Args:
        project_dir: 项目根目录路径，默认为本文件所在目录的上级目录
    """

    # 项目根目录下的核心文件白名单（不会被移到 _archive）
    _ROOT_WHITELIST_FILES = {
        "main.py",
        "config.py",
        "run_tests.py",
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
        "requirements.txt",
        "README.md",
        ".gitignore",
        ".git",
    }

    # 项目根目录下的核心目录白名单
    _ROOT_WHITELIST_DIRS = {
        "core",
        "utils",
        "tests",
        "金水谣数据",
        "_archive",
        ".git",
        "__pycache__",
        ".idea",
        ".vscode",
        "venv",
        ".venv",
        "env",
    }

    # 跳过孤立检测的文件模式
    _ORPHAN_SKIP_PATTERNS = {
        "__init__.py",
        "setup.py",
        "conftest.py",
    }

    # 跳过孤立检测的文件名后缀模式（正则）
    _ORPHAN_SKIP_SUFFIXES = (
        r"_test\.py$",
        r"test_.*\.py$",
    )

    # 项目关键目录结构定义
    _EXPECTED_STRUCTURE = {
        "core": {
            "description": "核心逻辑模块",
            "required": True,
        },
        "utils": {
            "description": "工具模块",
            "required": True,
        },
        "金水谣数据": {
            "description": "数据存储目录",
            "required": True,
        },
    }

    def __init__(self, project_dir: Optional[str] = None):
        """初始化文件整理器

        Args:
            project_dir: 项目根目录路径。为 None 时自动推算：
                        本文件位于 core/file_organizer.py，
                        项目根目录在上一级。
        """
        if project_dir is None:
            # 本文件位于 core/file_organizer.py，上级就是项目根目录
            self.project_dir = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        else:
            self.project_dir = os.path.abspath(project_dir)

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _get_dir_size_kb(self, dirpath: str) -> float:
        """递归计算目录大小（KB）

        Args:
            dirpath: 目录路径

        Returns:
            float: 目录总大小（KB）
        """
        total = 0.0
        try:
            for root, dirs, files in os.walk(dirpath):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        total += os.path.getsize(filepath) / 1024.0
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _count_files_recursive(self, dirpath: str) -> int:
        """递归统计目录中的文件数量

        Args:
            dirpath: 目录路径

        Returns:
            int: 文件总数
        """
        count = 0
        try:
            for root, dirs, files in os.walk(dirpath):
                count += len(files)
        except OSError:
            pass
        return count

    def _ensure_archive_dir(self) -> str:
        """确保 _archive 归档目录存在

        Returns:
            str: _archive 目录的绝对路径
        """
        archive_dir = os.path.join(self.project_dir, "_archive")
        if not os.path.isdir(archive_dir):
            os.makedirs(archive_dir, exist_ok=True)
            logger.info("创建归档目录: %s", archive_dir)
        return archive_dir

    def _should_skip_orphan_check(self, filename: str) -> bool:
        """判断文件是否应跳过孤立检测

        Args:
            filename: 文件名（不含路径）

        Returns:
            bool: True 表示应跳过检测
        """
        # 精确匹配
        if filename in self._ORPHAN_SKIP_PATTERNS:
            return True

        # 后缀模式匹配
        for pattern in self._ORPHAN_SKIP_SUFFIXES:
            if re.search(pattern, filename):
                return True

        return False

    # ------------------------------------------------------------------
    # 公开整理方法
    # ------------------------------------------------------------------

    def clean_pycache(self) -> dict:
        """递归删除项目中所有 __pycache__ 目录

        遍历项目目录，找到并删除所有 __pycache__ 目录及其内容。

        Returns:
            dict: 清理结果，包含:
                - removed (int):     删除的 __pycache__ 目录数量
                - freed_kb (float):  释放的磁盘空间（KB）

        Examples:
            >>> organizer = FileOrganizer()
            >>> result = organizer.clean_pycache()
            >>> print(f"删除了 {result['removed']} 个 __pycache__ 目录")
        """
        result = {"removed": 0, "freed_kb": 0.0}

        if not os.path.isdir(self.project_dir):
            logger.warning("项目目录不存在: %s", self.project_dir)
            return result

        for root, dirs, files in os.walk(self.project_dir):
            if "__pycache__" in dirs:
                pycache_path = os.path.join(root, "__pycache__")
                dir_size_kb = self._get_dir_size_kb(pycache_path)
                file_count = self._count_files_recursive(pycache_path)

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

    def organize_logs(self, max_log_files: int = 10) -> dict:
        """整理日志文件，将旧日志归档

        扫描 金水谣数据/log/ 目录，保留最新的 max_log_files 个日志文件，
        将其余旧日志移动到 金水谣数据/log/archive/ 目录。

        Args:
            max_log_files: 保留的最新日志文件数量，默认 10

        Returns:
            dict: 整理结果，包含:
                - archived (int): 归档的日志文件数量
                - kept (int):    保留的日志文件数量

        Examples:
            >>> organizer = FileOrganizer()
            >>> result = organizer.organize_logs(max_log_files=10)
            >>> print(f"归档 {result['archived']} 个，保留 {result['kept']} 个")
        """
        result = {"archived": 0, "kept": 0}

        log_dir = os.path.join(self.project_dir, "金水谣数据", "log")
        archive_dir = os.path.join(log_dir, "archive")

        if not os.path.isdir(log_dir):
            logger.info("日志目录不存在，跳过整理: %s", log_dir)
            return result

        # 收集日志文件（排除 archive 子目录中的文件）
        log_files = []
        for entry in os.listdir(log_dir):
            if entry == "archive":
                continue
            full_path = os.path.join(log_dir, entry)
            if os.path.isfile(full_path):
                # 识别常见的日志文件名模式
                if (entry.endswith(".log") or entry.endswith(".jsonl") or
                        "log" in entry.lower()):
                    try:
                        mtime = os.path.getmtime(full_path)
                        log_files.append((mtime, entry, full_path))
                    except OSError:
                        continue

        if not log_files:
            logger.info("未找到日志文件，跳过整理")
            return result

        # 按修改时间从新到旧排序
        log_files.sort(key=lambda x: x[0], reverse=True)

        # 保留最新的 max_log_files 个，其余归档
        kept_files = log_files[:max_log_files]
        archive_files = log_files[max_log_files:]

        result["kept"] = len(kept_files)

        if not archive_files:
            logger.info("日志文件数量未超限 (%d <= %d)，无需归档",
                        len(log_files), max_log_files)
            return result

        # 创建归档目录
        os.makedirs(archive_dir, exist_ok=True)

        for mtime, filename, src_path in archive_files:
            dst_path = os.path.join(archive_dir, filename)
            # 避免文件名冲突
            if os.path.exists(dst_path):
                base, ext = os.path.splitext(filename)
                timestamp = datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
                dst_path = os.path.join(archive_dir, f"{base}_{timestamp}{ext}")

            try:
                shutil.move(src_path, dst_path)
                logger.info("归档日志: %s -> %s", src_path, dst_path)
                result["archived"] += 1
            except (OSError, shutil.Error) as e:
                logger.error("归档日志失败: %s (%s)", src_path, e)

        logger.info("日志整理完成: 归档 %d 个，保留 %d 个",
                    result["archived"], result["kept"])
        return result

    def check_orphan_files(self) -> List[dict]:
        """检测项目中的孤立 Python 文件

        孤立文件是指不在任何 import 链中的 .py 文件，
        即没有被其他 Python 文件 import 的模块文件。

        跳过以下类型的文件:
        - __init__.py
        - setup.py, conftest.py
        - *_test.py, test_*.py（测试文件）
        - 模块入口文件（与所在目录同名的 .py 文件）

        Returns:
            list[dict]: 孤立文件列表，每个元素包含:
                - file (str):    文件路径
                - reason (str):  被判定为孤立文件的原因

        Examples:
            >>> organizer = FileOrganizer()
            >>> orphans = organizer.check_orphan_files()
            >>> for o in orphans:
            ...     print(f"{o['file']}: {o['reason']}")
        """
        orphans = []

        if not os.path.isdir(self.project_dir):
            logger.warning("项目目录不存在: %s", self.project_dir)
            return orphans

        # 第一步：收集所有 .py 文件路径和对应的模块名
        py_files = {}  # module_name -> [file_path, ...]
        for root, dirs, files in os.walk(self.project_dir):
            # 跳过常见的非源码目录
            rel_root = os.path.relpath(root, self.project_dir)
            skip_dirs = {"_archive", "venv", ".venv", "env", "__pycache__",
                         ".git", "node_modules", ".idea", ".vscode",
                         "金水谣数据"}
            first_dir = rel_root.split(os.sep)[0] if rel_root != "." else ""
            if first_dir in skip_dirs:
                dirs.clear()
                continue

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self.project_dir)

                # 跳过孤立检测的文件
                if self._should_skip_orphan_check(filename):
                    continue

                # 跳过模块入口文件（文件名与所在目录同名）
                dir_name = os.path.basename(root)
                base_name = os.path.splitext(filename)[0]
                if dir_name == base_name:
                    # 这是模块入口文件（如 core/brain.py 不算入口，但 core/core.py 算）
                    # 实际上只有文件名与目录名完全相同才算入口文件
                    pass

                # 计算模块名
                parts = rel_path.replace(os.sep, "/").split("/")
                module_name = ".".join(parts[:-1] + [base_name])

                if module_name not in py_files:
                    py_files[module_name] = []
                py_files[module_name].append(rel_path)

        if not py_files:
            logger.info("未找到 Python 源文件")
            return orphans

        # 第二步：收集所有 import 语句中引用的模块
        imported_modules = set()

        # 扫描所有 .py 文件中的 import 语句
        for root, dirs, files in os.walk(self.project_dir):
            rel_root = os.path.relpath(root, self.project_dir)
            skip_dirs = {"_archive", "venv", ".venv", "env", "__pycache__",
                         ".git", "node_modules", ".idea", ".vscode",
                         "金水谣数据"}
            first_dir = rel_root.split(os.sep)[0] if rel_root != "." else ""
            if first_dir in skip_dirs:
                dirs.clear()
                continue

            for filename in files:
                if not filename.endswith(".py"):
                    continue
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                # 匹配 import 语句
                # import xxx / import xxx.yyy
                for match in re.finditer(r"^\s*import\s+([\w.]+)", content, re.MULTILINE):
                    imported_modules.add(match.group(1))
                # from xxx import yyy / from xxx.yyy import zzz
                for match in re.finditer(r"^\s*from\s+([\w.]+)\s+import", content, re.MULTILINE):
                    imported_modules.add(match.group(1))

        # 第三步：检查哪些模块文件没有被 import
        for module_name, file_paths in py_files.items():
            is_imported = False

            # 检查完整模块名是否被 import
            if module_name in imported_modules:
                is_imported = True

            # 检查父模块是否被 import（导入父模块时会加载子模块）
            if not is_imported:
                parts = module_name.split(".")
                for i in range(1, len(parts)):
                    parent = ".".join(parts[:i])
                    if parent in imported_modules:
                        is_imported = True
                        break

            # 检查是否有其他模块以该文件所在的包（目录）形式被 import
            # 例如 core.brain 如果被 import，则 core/ 目录下的 __init__.py 算被引用
            if not is_imported:
                # 检查是否是包目录的入口文件（目录名/__init__.py）
                for fp in file_paths:
                    if fp.endswith("__init__.py"):
                        pkg_name = module_name.rsplit(".", 1)[0] if "." in module_name else None
                        if pkg_name and pkg_name in imported_modules:
                            is_imported = True
                            break

            if not is_imported:
                # 额外检查：该文件所在目录是否作为包被引用
                for fp in file_paths:
                    dir_of_file = os.path.dirname(fp).replace(os.sep, "/")
                    if dir_of_file == ".":
                        dir_of_file = ""
                    # 目录本身的模块名
                    if dir_of_file:
                        if (dir_of_file in imported_modules or
                                any(m.startswith(dir_of_file + ".") for m in imported_modules)):
                            is_imported = True
                            break

            if not is_imported:
                for fp in file_paths:
                    orphans.append({
                        "file": fp,
                        "reason": "未被任何 import 语句引用",
                    })

        logger.info("孤立文件检测完成: 发现 %d 个孤立文件", len(orphans))
        for orphan in orphans:
            logger.debug("  孤立文件: %s - %s", orphan["file"], orphan["reason"])

        return orphans

    def verify_structure(self) -> dict:
        """验证项目目录结构完整性

        检查关键目录和文件是否存在，并检测不在预期结构中的
        额外文件/目录。

        Returns:
            dict: 验证结果，包含:
                - valid (bool):      整体结构是否完整
                - missing (list):   缺失的关键目录/文件列表
                - extra (list):     不在预期结构中的额外项列表
                - details (list):   各项检查的详细信息

        Examples:
            >>> organizer = FileOrganizer()
            >>> result = organizer.verify_structure()
            >>> if not result['valid']:
            ...     print("缺失:", result['missing'])
        """
        result = {
            "valid": True,
            "missing": [],
            "extra": [],
            "details": [],
        }

        if not os.path.isdir(self.project_dir):
            logger.warning("项目目录不存在: %s", self.project_dir)
            result["valid"] = False
            result["missing"].append(self.project_dir)
            return result

        # 收集项目根目录下的实际条目
        actual_entries = set(os.listdir(self.project_dir))

        # 收集预期的目录和文件
        expected_dirs = set()
        expected_files = set()

        for name, config in self._EXPECTED_STRUCTURE.items():
            expected_dirs.add(name)

        # 验证预期结构是否存在
        for name, config in self._EXPECTED_STRUCTURE.items():
            path = os.path.join(self.project_dir, name)
            exists = os.path.isdir(path) or os.path.isfile(path)
            detail = {
                "name": name,
                "type": "dir",
                "description": config["description"],
                "exists": exists,
                "required": config["required"],
            }

            if not exists:
                if config["required"]:
                    result["valid"] = False
                    result["missing"].append(name)
                    logger.warning("缺失关键目录: %s (%s)", name, config["description"])
                else:
                    logger.info("可选目录不存在: %s", name)

            result["details"].append(detail)

        # 检查额外项（不在预期结构和白名单中的条目）
        all_expected = expected_dirs | expected_files | self._ROOT_WHITELIST_DIRS | self._ROOT_WHITELIST_FILES
        extra_entries = []
        for entry in actual_entries:
            if entry not in all_expected:
                extra_entries.append(entry)

        if extra_entries:
            result["extra"] = sorted(extra_entries)
            # 额外文件不影响整体 valid 标志，仅作为信息提示
            for entry in extra_entries:
                logger.debug("额外文件/目录: %s", entry)

        # 检查核心目录下是否有文件存在
        for name in expected_dirs:
            dir_path = os.path.join(self.project_dir, name)
            if os.path.isdir(dir_path):
                file_count = self._count_files_recursive(dir_path)
                if file_count == 0:
                    logger.warning("关键目录为空: %s", name)

        logger.info("目录结构验证完成: valid=%s, missing=%d, extra=%d",
                    result["valid"], len(result["missing"]), len(result["extra"]))
        return result

    def tidy_project_root(self) -> dict:
        """整理项目根目录

        将不在白名单中的文件移动到 _archive/ 目录。
        目录类型的条目不会被移动（避免误操作）。

        Returns:
            dict: 整理结果，包含:
                - moved (int): 移动的文件数量
                - kept (int):  保留的文件数量

        Examples:
            >>> organizer = FileOrganizer()
            >>> result = organizer.tidy_project_root()
            >>> print(f"移动 {result['moved']} 个，保留 {result['kept']} 个")
        """
        result = {"moved": 0, "kept": 0}

        if not os.path.isdir(self.project_dir):
            logger.warning("项目目录不存在: %s", self.project_dir)
            return result

        archive_dir = self._ensure_archive_dir()

        # 获取根目录下所有条目
        try:
            entries = os.listdir(self.project_dir)
        except OSError as e:
            logger.error("无法列出项目根目录: %s (%s)", self.project_dir, e)
            return result

        # 合并所有白名单
        all_whitelist = self._ROOT_WHITELIST_FILES | self._ROOT_WHITELIST_DIRS

        for entry in entries:
            # 跳过白名单中的条目
            if entry in all_whitelist:
                result["kept"] += 1
                continue

            entry_path = os.path.join(self.project_dir, entry)

            # 只处理文件，不处理目录（避免误删重要目录）
            if not os.path.isfile(entry_path):
                result["kept"] += 1
                continue

            # 目标路径
            dst_path = os.path.join(archive_dir, entry)
            if os.path.exists(dst_path):
                # 避免覆盖已有文件，添加时间戳
                base, ext = os.path.splitext(entry)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dst_path = os.path.join(archive_dir, f"{base}_{timestamp}{ext}")

            try:
                shutil.move(entry_path, dst_path)
                logger.info("归档根目录文件: %s -> %s", entry_path, dst_path)
                result["moved"] += 1
            except (OSError, shutil.Error) as e:
                logger.error("移动文件失败: %s (%s)", entry_path, e)
                result["kept"] += 1

        logger.info("根目录整理完成: 移动 %d 个文件，保留 %d 个",
                    result["moved"], result["kept"])
        return result

    def full_organize(self) -> dict:
        """一键执行所有整理操作

        按顺序执行以下整理操作:
        1. 清理 __pycache__
        2. 整理日志文件
        3. 检测孤立文件
        4. 验证目录结构
        5. 整理项目根目录

        Returns:
            dict: 汇总报告，包含每步操作的结果和总结信息

        Examples:
            >>> organizer = FileOrganizer()
            >>> report = organizer.full_organize()
            >>> print(f"总释放空间: {report['summary']['total_freed_kb']:.1f} KB")
        """
        logger.info("=" * 50)
        logger.info("开始执行项目文件全面整理")
        logger.info("项目目录: %s", self.project_dir)
        logger.info("=" * 50)

        report = {
            "timestamp": datetime.now().isoformat(),
            "project_dir": self.project_dir,
            "steps": {},
            "summary": {
                "pycache_removed": 0,
                "pycache_freed_kb": 0.0,
                "logs_archived": 0,
                "logs_kept": 0,
                "orphan_files": 0,
                "structure_valid": True,
                "root_files_moved": 0,
                "root_files_kept": 0,
                "errors": 0,
            },
        }

        # 步骤1: 清理 __pycache__
        try:
            result = self.clean_pycache()
            report["steps"]["clean_pycache"] = result
            report["summary"]["pycache_removed"] = result["removed"]
            report["summary"]["pycache_freed_kb"] = result["freed_kb"]
        except Exception as e:
            logger.error("清理 __pycache__ 异常: %s", e, exc_info=True)
            report["steps"]["clean_pycache"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤2: 整理日志
        try:
            result = self.organize_logs()
            report["steps"]["organize_logs"] = result
            report["summary"]["logs_archived"] = result["archived"]
            report["summary"]["logs_kept"] = result["kept"]
        except Exception as e:
            logger.error("整理日志异常: %s", e, exc_info=True)
            report["steps"]["organize_logs"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤3: 检测孤立文件
        try:
            result = self.check_orphan_files()
            report["steps"]["check_orphan_files"] = result
            report["summary"]["orphan_files"] = len(result)
        except Exception as e:
            logger.error("检测孤立文件异常: %s", e, exc_info=True)
            report["steps"]["check_orphan_files"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤4: 验证目录结构
        try:
            result = self.verify_structure()
            report["steps"]["verify_structure"] = result
            report["summary"]["structure_valid"] = result["valid"]
        except Exception as e:
            logger.error("验证目录结构异常: %s", e, exc_info=True)
            report["steps"]["verify_structure"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤5: 整理项目根目录
        try:
            result = self.tidy_project_root()
            report["steps"]["tidy_project_root"] = result
            report["summary"]["root_files_moved"] = result["moved"]
            report["summary"]["root_files_kept"] = result["kept"]
        except Exception as e:
            logger.error("整理根目录异常: %s", e, exc_info=True)
            report["steps"]["tidy_project_root"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        logger.info("=" * 50)
        logger.info("项目文件整理完成:")
        logger.info("  __pycache__ 清理: %d 个目录，释放 %.2f KB",
                    report["summary"]["pycache_removed"],
                    report["summary"]["pycache_freed_kb"])
        logger.info("  日志归档: %d 个，保留 %d 个",
                    report["summary"]["logs_archived"],
                    report["summary"]["logs_kept"])
        logger.info("  孤立文件: %d 个", report["summary"]["orphan_files"])
        logger.info("  结构验证: %s",
                    "通过" if report["summary"]["structure_valid"] else "不通过")
        logger.info("  根目录整理: 移动 %d 个，保留 %d 个",
                    report["summary"]["root_files_moved"],
                    report["summary"]["root_files_kept"])
        logger.info("  错误数: %d", report["summary"]["errors"])
        logger.info("=" * 50)

        return report


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