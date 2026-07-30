# -*- coding: utf-8 -*-
"""金水谣系统 - 文件变更自动监控守护进程

功能：
  - 监控项目目录下所有 .py/.html/.bat/.js/.css 文件
  - 文件被修改时自动将修改前版本备份到 金水谣数据/backups/
  - 每次变更自动记录到 change_audit.logl
  - 启动时扫描一次当前文件状态作为基线（快照缓存）
  - 后台线程运行，不阻塞主程序

核心原理：
  在内存中维护每个文件的最新内容副本（_last_content）。
  每次轮询时将当前文件内容与缓存对比，若不同则说明文件被修改。
  此时缓存中的旧内容即为修改前版本，将其保存为备份，完美解决了
  "检测到变更时文件已被改写、无法恢复修改前版本"的固有问题。

内存开销估算：~120个Python文件 * 平均30KB ≈ 3.6MB，完全可接受。

使用方式：
    from core.file_watcher import FileWatcher
    watcher = FileWatcher()       # 默认使用本项目目录
    watcher.start()                # 启动后台监控
    watcher.stop()                 # 停止监控
    print(watcher.status())         # 查看状态
"""
import os
import sys
import time
import threading
import hashlib
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

logger = logging.getLogger("jinshuiyao.file_watcher")


class FileWatcher:
    """文件变更自动监控守护进程

    监控项目目录下的指定扩展名文件，在检测到内容变化时自动备份修改前版本
    并记录审计日志。采用 threading + os.walk 轮询方式，仅使用 Python 标准库。

    Attributes:
        WATCHED_EXTS: 需要监控的文件扩展名元组
        BACKUP_DIR: 备份目录的相对路径
        POLL_INTERVAL: 轮询间隔（秒）
    """

    WATCHED_EXTS = ('.py', '.html', '.bat', '.js', '.css')
    # 类属性存储相对路径部分，实际路径在 _write_audit_directly 中基于 _project_dir 拼接
    BACKUP_DIR = os.path.join('金水谣数据', 'backups')
    AUDIT_DIR = os.path.join('金水谣数据', 'log')
    AUDIT_FILE = os.path.join('金水谣数据', 'log', 'change_audit.logl')
    POLL_INTERVAL = 3  # 秒

    def __init__(self, project_dir: Optional[str] = None):
        """初始化文件监控器

        Args:
            project_dir: 项目根目录。默认自动推断为本文件所在目录的上一级。
        """
        if project_dir is None:
            # 自动推断：本文件位于 core/file_watcher.py，项目根在上一级
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._project_dir = os.path.abspath(project_dir)

        # 内存中的文件内容缓存 —— 保存每个文件的"上一次poll时的内容"
        # 当文件被修改后，缓存中的旧内容就是修改前版本
        self._last_content: Dict[str, bytes] = {}
        # SHA256 前16位哈希，用于快速比较（避免每次都读整个文件内容做对比）
        # 但最终确认变化时仍需对比内容
        self._last_hash: Dict[str, str] = {}

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 统计信息
        self._backup_count = 0
        self._change_count = 0
        self._scan_count = 0
        self._start_time: Optional[str] = None
        self._file_count = 0

        # 排除目录 —— 这些目录下的文件不需要监控
        self._exclude_dirs = {
            '__pycache__',
            os.path.join('金水谣数据', 'backups'),
            os.path.join('金水谣数据', 'log'),
            '.git',
            'archive',
            'node_modules',
            '.trae-cn',
            'env',
            'venv',
            '.venv',
        }

        logger.info("FileWatcher 初始化完成，监控目录: %s", self._project_dir)

    def _is_excluded(self, dir_name: str) -> bool:
        """检查目录是否在排除列表中"""
        # 标准化路径比较：同时检查简单名称和路径组成部分
        return dir_name in self._exclude_dirs or '金水谣数据' in dir_name

    def _scan_and_cache(self) -> None:
        """扫描所有监控文件，建立基线缓存

        启动时调用，遍历项目目录中所有需要监控的文件，
        将每个文件的完整内容读取到内存中作为初始基线。
        """
        with self._lock:
            self._last_content.clear()
            self._last_hash.clear()

            for root, dirs, files in os.walk(self._project_dir):
                # 过滤排除目录（原地修改 dirs 列表，os.walk 会跳过被移除的目录）
                dirs[:] = [d for d in dirs if not self._is_excluded(d)]

                for filename in files:
                    if filename.endswith(self.WATCHED_EXTS):
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, 'rb') as fh:
                                content = fh.read()
                            h = hashlib.sha256(content).hexdigest()[:16]
                            self._last_content[filepath] = content
                            self._last_hash[filepath] = h
                        except (OSError, IOError):
                            # 跳过无法读取的文件（可能被锁定或权限不足）
                            pass

            self._file_count = len(self._last_content)
            logger.info("基线扫描完成：共 %d 个文件，内存占用约 %.1f MB",
                        self._file_count,
                        sum(len(v) for v in self._last_content.values()) / (1024 * 1024))

    def _poll(self) -> None:
        """执行一轮轮询：检测文件变更并备份修改前版本

        核心逻辑：
        1. 遍历所有监控文件，读取当前内容并计算哈希
        2. 与缓存中的哈希对比
        3. 哈希不同 → 文件被修改 → 将缓存中的旧版本保存为备份
        4. 更新缓存为当前内容
        """
        changes_in_this_poll = []

        for root, dirs, files in os.walk(self._project_dir):
            dirs[:] = [d for d in dirs if not self._is_excluded(d)]

            for filename in files:
                if filename.endswith(self.WATCHED_EXTS):
                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'rb') as fh:
                            content = fh.read()
                    except (OSError, IOError):
                        continue

                    h = hashlib.sha256(content).hexdigest()[:16]
                    old_h = self._last_hash.get(filepath)

                    if old_h is not None and old_h != h:
                        # 文件内容发生了变化！
                        # 缓存中保存的是修改前的版本，先备份旧版本
                        old_content = self._last_content[filepath]
                        rel_path = os.path.relpath(filepath, self._project_dir)
                        self._save_backup(rel_path, old_content)
                        self._record_change(rel_path, 'MODIFIED')
                        self._change_count += 1
                        changes_in_this_poll.append(rel_path)

                    # 无论是否变化，都更新缓存（新文件也会在这里加入）
                    self._last_content[filepath] = content
                    self._last_hash[filepath] = h

        self._scan_count += 1
        if changes_in_this_poll:
            logger.info("第 %d 轮扫描检测到 %d 个文件变更: %s",
                        self._scan_count, len(changes_in_this_poll),
                        ', '.join(changes_in_this_poll))

    def _save_backup(self, rel_path: str, content_bytes: bytes) -> str:
        """将修改前的文件内容保存到备份目录

        备份路径结构：
          金水谣数据/backups/<相对路径用_替换分隔符>/<文件名_时间戳.扩展名>

        例如：
          金水谣数据/backups/gui_main_window.py/main_window_20260716_143022.py

        Args:
            rel_path: 文件相对于项目根目录的路径
            content_bytes: 要备份的文件内容（二进制）

        Returns:
            备份文件的绝对路径
        """
        # 将相对路径中的分隔符替换为下划线，作为备份子目录名
        dir_part = rel_path.replace(os.sep, '_').replace('/', '_')
        backup_subdir = os.path.join(self._project_dir, self.BACKUP_DIR, dir_part)
        os.makedirs(backup_subdir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        basename = os.path.basename(rel_path)
        name, ext = os.path.splitext(basename)
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = os.path.join(backup_subdir, backup_name)

        # 如果同名备份文件已存在（同一秒内多次修改），添加序号后缀
        if os.path.exists(backup_path):
            counter = 1
            while True:
                backup_name = f"{name}_{timestamp}_{counter}{ext}"
                backup_path = os.path.join(backup_subdir, backup_name)
                if not os.path.exists(backup_path):
                    break
                counter += 1

        try:
            with open(backup_path, 'wb') as f:
                f.write(content_bytes)
            self._backup_count += 1
            logger.info("已备份旧版本: %s (%d 字节) → %s",
                        rel_path, len(content_bytes), backup_name)
            return backup_path
        except (OSError, IOError) as e:
            logger.error("备份失败 %s: %s", rel_path, e)
            return ""

    def _record_change(self, rel_path: str, event_type: str = 'MODIFIED') -> None:
        """记录变更事件到审计日志

        直接写入 self._project_dir 下的审计日志文件。
        同时尝试调用 utils.change_audit._write_entry 写入项目统一审计日志。

        Args:
            rel_path: 文件相对于项目根目录的路径
            event_type: 事件类型（MODIFIED/CREATED/DELETED）
        """
        # 始终写入 FileWatcher 自己项目目录下的审计日志（备份专用文件）
        self._write_audit_directly(rel_path, event_type)

        # 尝试同时写入项目统一备份审计日志（backup_audit.logl，与手动操作分离）
        try:
            from utils.change_audit import _write_entry
            _write_entry(
                "BACKUP",
                rel_path,
                "自动检测到文件变更，修改前版本已备份",
                "由FileWatcher自动监控"
            )
        except Exception:
            pass

    def _write_audit_directly(self, rel_path: str, event_type: str) -> None:
        """直接写入备份审计日志文件（backup_audit.logl，与手动操作日志分离）

        当 change_audit 模块不可用时作为后备。
        """
        import json
        audit_path = os.path.join(self._project_dir, '金水谣数据', 'log', 'backup_audit.logl')
        os.makedirs(os.path.dirname(audit_path), exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = json.dumps({
            "ts": timestamp,
            "type": event_type,
            "file": rel_path,
            "summary": "自动检测到文件变更，修改前版本已备份",
            "detail": "由FileWatcher自动监控",
        }, ensure_ascii=False)

        try:
            with open(audit_path, 'a', encoding='utf-8') as f:
                f.write(entry + "\n")
        except (OSError, IOError) as e:
            logger.error("直接写入审计日志失败: %s", e)

    def start(self) -> None:
        """启动文件变更监控

        在后台线程中运行轮询循环，不阻塞主程序。
        启动时会先执行一次全量扫描建立基线缓存。
        """
        if self._running:
            logger.warning("FileWatcher 已在运行中")
            return

        self._running = True
        self._start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 先扫描建立基线（必须在线程启动前完成）
        self._scan_and_cache()

        # 启动轮询线程
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="file-watcher"
        )
        self._thread.start()
        logger.info("FileWatcher 已启动，轮询间隔: %d秒，监控 %d 个文件",
                     self.POLL_INTERVAL, self._file_count)

    def _poll_loop(self) -> None:
        """后台轮询循环

        以 POLL_INTERVAL 为间隔持续运行，直到 _running 被设为 False。
        捕获所有异常以保证线程不会意外退出。
        """
        while self._running:
            try:
                self._poll()
            except Exception as e:
                logger.error("轮询异常: %s", e, exc_info=True)
            time.sleep(self.POLL_INTERVAL)

    def stop(self) -> None:
        """停止文件变更监控

        设置运行标志为 False，并等待后台线程结束（最多等待 POLL_INTERVAL*2 秒）。
        """
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.POLL_INTERVAL * 2)
            if self._thread.is_alive():
                logger.warning("FileWatcher 线程未能及时停止")
        logger.info("FileWatcher 已停止（运行期间共 %d 次变更，%d 次备份，%d 轮扫描）",
                     self._change_count, self._backup_count, self._scan_count)

    def status(self) -> dict:
        """返回监控器的当前状态信息

        Returns:
            dict: 包含以下信息的字典:
                - running: 是否正在运行
                - project_dir: 监控的项目目录
                - file_count: 当前监控的文件数
                - change_count: 累计检测到的变更数
                - backup_count: 累计备份次数
                - scan_count: 累计扫描轮数
                - poll_interval: 轮询间隔（秒）
                - start_time: 启动时间
                - memory_mb: 当前内存缓存占用（MB）
        """
        memory_bytes = sum(len(v) for v in self._last_content.values())
        return {
            'running': self._running,
            'project_dir': self._project_dir,
            'file_count': len(self._last_content),
            'change_count': self._change_count,
            'backup_count': self._backup_count,
            'scan_count': self._scan_count,
            'poll_interval': self.POLL_INTERVAL,
            'start_time': self._start_time,
            'memory_mb': round(memory_bytes / (1024 * 1024), 2),
        }
