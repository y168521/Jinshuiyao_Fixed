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
    from core.infra.file_watcher import FileWatcher
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


# ===========================================================================
# 模块级函数（从 FileWatcher 抽出，self 作为首参传入）
# ===========================================================================

def _fw_init(self, project_dir: Optional[str] = None):
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    self._project_dir = os.path.abspath(project_dir)
    self._last_content: Dict[str, bytes] = {}
    self._last_hash: Dict[str, str] = {}
    self._running = False
    self._thread: Optional[threading.Thread] = None
    self._lock = threading.Lock()
    self._backup_count = 0
    self._change_count = 0
    self._scan_count = 0
    self._start_time: Optional[str] = None
    self._file_count = 0
    self._exclude_dirs = {
        '__pycache__',
        os.path.join('金水谣数据', 'backups'),
        os.path.join('金水谣数据', 'log'),
        '.git', 'archive', 'node_modules',
        '.trae-cn', 'env', 'venv', '.venv',
    }
    logger.info("FileWatcher 初始化完成，监控目录: %s", self._project_dir)


def _fw_is_excluded(self, dir_name: str) -> bool:
    return dir_name in self._exclude_dirs or '金水谣数据' in dir_name


def _fw_scan_and_cache(self) -> None:
    with self._lock:
        self._last_content.clear()
        self._last_hash.clear()
        for root, dirs, files in os.walk(self._project_dir):
            dirs[:] = [d for d in dirs if not _fw_is_excluded(self, d)]
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
                        pass
        self._file_count = len(self._last_content)
        logger.info("基线扫描完成：共 %d 个文件，内存占用约 %.1f MB",
                    self._file_count,
                    sum(len(v) for v in self._last_content.values()) / (1024 * 1024))


def _fw_poll(self) -> None:
    changes_in_this_poll = []
    for root, dirs, files in os.walk(self._project_dir):
        dirs[:] = [d for d in dirs if not _fw_is_excluded(self, d)]
        for filename in files:
            if not filename.endswith(self.WATCHED_EXTS):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, 'rb') as fh:
                    content = fh.read()
            except (OSError, IOError):
                continue
            h = hashlib.sha256(content).hexdigest()[:16]
            old_h = self._last_hash.get(filepath)
            if old_h is not None and old_h != h:
                old_content = self._last_content[filepath]
                rel_path = os.path.relpath(filepath, self._project_dir)
                _fw_save_backup(self, rel_path, old_content)
                _fw_record_change(self, rel_path, 'MODIFIED')
                self._change_count += 1
                changes_in_this_poll.append(rel_path)
            self._last_content[filepath] = content
            self._last_hash[filepath] = h
    self._scan_count += 1
    if changes_in_this_poll:
        logger.info("第 %d 轮扫描检测到 %d 个文件变更: %s",
                    self._scan_count, len(changes_in_this_poll),
                    ', '.join(changes_in_this_poll))


def _fw_save_backup(self, rel_path: str, content_bytes: bytes) -> str:
    dir_part = rel_path.replace(os.sep, '_').replace('/', '_')
    backup_subdir = os.path.join(self._project_dir, self.BACKUP_DIR, dir_part)
    os.makedirs(backup_subdir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = os.path.basename(rel_path)
    name, ext = os.path.splitext(basename)
    backup_name = f"{name}_{timestamp}{ext}"
    backup_path = os.path.join(backup_subdir, backup_name)
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


def _fw_record_change(self, rel_path: str, event_type: str = 'MODIFIED') -> None:
    _fw_write_audit_directly(self, rel_path, event_type)
    try:
        from utils.change_audit import _write_entry
        _write_entry("BACKUP", rel_path, "自动检测到文件变更，修改前版本已备份", "由FileWatcher自动监控")
    except Exception as e:
        logger.debug("FileWatcher 写入统一审计日志失败(忽略): %s", e)


def _fw_write_audit_directly(self, rel_path: str, event_type: str) -> None:
    import json
    audit_path = os.path.join(self._project_dir, '金水谣数据', 'log', 'backup_audit.logl')
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = json.dumps({
        "ts": timestamp, "type": event_type, "file": rel_path,
        "summary": "自动检测到文件变更，修改前版本已备份",
        "detail": "由FileWatcher自动监控",
    }, ensure_ascii=False)
    try:
        with open(audit_path, 'a', encoding='utf-8') as f:
            f.write(entry + "\n")
    except (OSError, IOError) as e:
        logger.error("直接写入审计日志失败: %s", e)


def _fw_start(self) -> None:
    if self._running:
        logger.warning("FileWatcher 已在运行中")
        return
    self._running = True
    self._start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _fw_scan_and_cache(self)
    self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="file-watcher")
    self._thread.start()
    logger.info("FileWatcher 已启动，轮询间隔: %d秒，监控 %d 个文件",
                self.POLL_INTERVAL, self._file_count)


def _fw_poll_loop(self) -> None:
    while self._running:
        try:
            _fw_poll(self)
        except Exception as e:
            logger.error("轮询异常: %s", e, exc_info=True)
        time.sleep(self.POLL_INTERVAL)


def _fw_stop(self) -> None:
    self._running = False
    if self._thread and self._thread.is_alive():
        self._thread.join(timeout=self.POLL_INTERVAL * 2)
        if self._thread.is_alive():
            logger.warning("FileWatcher 线程未能及时停止")
    logger.info("FileWatcher 已停止（运行期间共 %d 次变更，%d 次备份，%d 轮扫描）",
                self._change_count, self._backup_count, self._scan_count)


def _fw_status(self) -> dict:
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


# ===========================================================================
# 薄包装类
# ===========================================================================

class FileWatcher:
    """文件变更自动监控守护进程（方法委托模块级函数）。"""
    WATCHED_EXTS = ('.py', '.html', '.bat', '.js', '.css')
    BACKUP_DIR = os.path.join('金水谣数据', 'backups')
    AUDIT_DIR = os.path.join('金水谣数据', 'log')
    AUDIT_FILE = os.path.join('金水谣数据', 'log', 'change_audit.logl')
    POLL_INTERVAL = 3

    def __init__(self, project_dir=None): _fw_init(self, project_dir)
    def _is_excluded(self, dir_name): return _fw_is_excluded(self, dir_name)
    def _scan_and_cache(self): return _fw_scan_and_cache(self)
    def _poll(self): return _fw_poll(self)
    def _save_backup(self, rel_path, content_bytes): return _fw_save_backup(self, rel_path, content_bytes)
    def _record_change(self, rel_path, event_type='MODIFIED'): return _fw_record_change(self, rel_path, event_type)
    def _write_audit_directly(self, rel_path, event_type): return _fw_write_audit_directly(self, rel_path, event_type)
    def start(self): return _fw_start(self)
    def _poll_loop(self): return _fw_poll_loop(self)
    def stop(self): return _fw_stop(self)
    def status(self): return _fw_status(self)
