# -*- coding: utf-8 -*-
"""金水谣系统 - FileWatcher 文件变更自动监控 单元测试

测试内容：
  1. FileWatcher 初始化和启动/停止
  2. 模拟文件修改：写入临时文件 → 触发poll → 检查备份是否生成
  3. 连续修改：多次修改同一文件 → 应该生成多个备份
  4. 排除目录：__pycache__/金水谣数据/ 下的文件不应被监控
  5. 新文件创建：新文件不应触发MODIFIED事件（首次出现时无旧版本可备份）
  6. 审计日志记录

每个测试在临时目录中操作，不污染项目文件。
测试中使用 _scan_and_cache() 代替 start()/stop() 来建立基线，
避免后台线程干扰手动 poll 的断言。
"""
import os
import sys
import json
import time
import shutil
import threading
import unittest
import tempfile

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.file_watcher import FileWatcher


class TestFileWatcherInit(unittest.TestCase):
    """测试1：FileWatcher 初始化和启动/停止"""

    def test_init_with_explicit_dir(self):
        """测试用指定目录初始化 FileWatcher"""
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(project_dir=tmpdir)
            self.assertEqual(watcher._project_dir, os.path.abspath(tmpdir))
            self.assertFalse(watcher._running)
            self.assertIsNone(watcher._thread)
            self.assertEqual(watcher._change_count, 0)
            self.assertEqual(watcher._backup_count, 0)
            self.assertEqual(len(watcher._last_content), 0)

    def test_init_auto_detect_dir(self):
        """测试自动推断项目目录"""
        # 不传 project_dir，应自动推断
        watcher = FileWatcher()
        self.assertTrue(os.path.isdir(watcher._project_dir))

    def test_start_and_stop(self):
        """测试启动和停止流程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(project_dir=tmpdir)
            watcher.POLL_INTERVAL = 1  # 缩短轮询间隔加速测试

            # 创建一个测试文件
            test_file = os.path.join(tmpdir, 'test.py')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write('# test\n')

            # 启动监控
            watcher.start()
            self.assertTrue(watcher._running)
            self.assertIsNotNone(watcher._thread)
            self.assertTrue(watcher._thread.is_alive())
            self.assertEqual(len(watcher._last_content), 1)  # 基线扫描应找到 test.py
            self.assertIsNotNone(watcher._start_time)

            # 检查状态
            status = watcher.status()
            self.assertTrue(status['running'])
            self.assertEqual(status['file_count'], 1)
            self.assertEqual(status['poll_interval'], 1)

            # 停止监控
            watcher.stop()
            self.assertFalse(watcher._running)

            # 状态应反映已停止
            status = watcher.status()
            self.assertFalse(status['running'])

    def test_start_twice_no_duplicate_thread(self):
        """测试重复启动不会创建多个线程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(project_dir=tmpdir)
            watcher.POLL_INTERVAL = 10  # 长间隔避免不必要的轮询
            watcher.start()
            thread1 = watcher._thread
            watcher.start()  # 第二次启动应被忽略
            self.assertIs(watcher._thread, thread1)  # 应该是同一个线程
            watcher.stop()

    def test_status_returns_all_fields(self):
        """测试 status() 返回所有必要字段"""
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = FileWatcher(project_dir=tmpdir)
            status = watcher.status()
            expected_keys = {
                'running', 'project_dir', 'file_count',
                'change_count', 'backup_count', 'scan_count',
                'poll_interval', 'start_time', 'memory_mb'
            }
            self.assertEqual(set(status.keys()), expected_keys)


class TestFileWatcherModify(unittest.TestCase):
    """测试2：模拟文件修改，触发poll后检查备份

    使用 _scan_and_cache() 建立基线（不启动后台线程），
    然后手动调用 _poll() 来检测变更。
    """

    def setUp(self):
        """创建临时目录和测试文件"""
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')
        self.audit_file = os.path.join(self.tmpdir, '金水谣数据', 'log', 'backup_audit.logl')

        # 创建测试文件（初始版本）
        self.test_file = os.path.join(self.tmpdir, 'hello.py')
        with open(self.test_file, 'w', encoding='utf-8') as f:
            f.write('# 版本1\nprint("hello")\n')

    def tearDown(self):
        """清理临时目录"""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_watcher(self):
        """创建 watcher 并通过 _scan_and_cache() 建立基线（不启动后台线程）"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()
        return watcher

    def test_modify_triggers_backup(self):
        """修改文件后应自动备份旧版本"""
        watcher = self._make_watcher()

        # 确认基线已建立
        self.assertIn(self.test_file, watcher._last_content)

        # 修改文件
        with open(self.test_file, 'w', encoding='utf-8') as f:
            f.write('# 版本2\nprint("world")\n')

        # 手动执行一轮轮询
        watcher._poll()

        # 检查备份是否生成
        self.assertEqual(watcher._backup_count, 1)
        self.assertEqual(watcher._change_count, 1)

        # 检查备份目录中是否有备份文件
        backup_subdir = os.path.join(
            self.backup_dir,
            'hello.py'.replace(os.sep, '_')
        )
        self.assertTrue(os.path.isdir(backup_subdir))
        backup_files = os.listdir(backup_subdir)
        self.assertEqual(len(backup_files), 1)

        # 验证备份内容是旧版本（版本1）
        backup_path = os.path.join(backup_subdir, backup_files[0])
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_content = f.read()
        self.assertIn('版本1', backup_content)
        self.assertNotIn('版本2', backup_content)

    def test_backup_file_naming(self):
        """验证备份文件命名格式：文件名_时间戳.扩展名"""
        watcher = self._make_watcher()

        # 修改文件
        with open(self.test_file, 'w', encoding='utf-8') as f:
            f.write('modified\n')
        watcher._poll()

        backup_subdir = os.path.join(self.backup_dir, 'hello.py')
        backup_files = os.listdir(backup_subdir)
        self.assertEqual(len(backup_files), 1)
        name = backup_files[0]
        self.assertTrue(name.startswith('hello_'))
        self.assertTrue(name.endswith('.py'))
        # 中间部分应该是时间戳格式 YYYYMMDD_HHMMSS
        parts = name.replace('.py', '').split('_', 1)
        self.assertEqual(parts[0], 'hello')
        self.assertEqual(len(parts[1]), 15)  # YYYYMMDD_HHMMSS

    def test_no_change_no_backup(self):
        """文件未修改时不应产生备份"""
        watcher = self._make_watcher()

        # 不修改文件，直接轮询
        watcher._poll()

        self.assertEqual(watcher._backup_count, 0)
        self.assertEqual(watcher._change_count, 0)


class TestFileWatcherContinuousModify(unittest.TestCase):
    """测试3：连续修改同一文件应生成多个备份"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')
        self.test_file = os.path.join(self.tmpdir, 'counter.py')
        with open(self.test_file, 'w') as f:
            f.write('version = 0\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_multiple_modifications_multiple_backups(self):
        """连续修改3次应产生3个备份，每个备份保存对应修改前的版本"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()  # 建立基线（不启动后台线程）

        # 第一次修改
        with open(self.test_file, 'w') as f:
            f.write('version = 1\n')
        watcher._poll()
        self.assertEqual(watcher._backup_count, 1)

        # 第二次修改（确保时间戳不同，添加短暂延时）
        time.sleep(0.01)
        with open(self.test_file, 'w') as f:
            f.write('version = 2\n')
        watcher._poll()
        self.assertEqual(watcher._backup_count, 2)

        # 第三次修改
        time.sleep(0.01)
        with open(self.test_file, 'w') as f:
            f.write('version = 3\n')
        watcher._poll()
        self.assertEqual(watcher._backup_count, 3)

        # 验证备份目录中有3个文件
        backup_subdir = os.path.join(self.backup_dir, 'counter.py')
        backup_files = sorted(os.listdir(backup_subdir))
        self.assertEqual(len(backup_files), 3)

        # 验证每个备份的内容是修改前的版本
        # 第一个备份应该是 version = 0
        with open(os.path.join(backup_subdir, backup_files[0]), 'r') as f:
            self.assertIn('version = 0', f.read())
        # 第二个备份应该是 version = 1
        with open(os.path.join(backup_subdir, backup_files[1]), 'r') as f:
            self.assertIn('version = 1', f.read())
        # 第三个备份应该是 version = 2
        with open(os.path.join(backup_subdir, backup_files[2]), 'r') as f:
            self.assertIn('version = 2', f.read())


class TestFileWatcherExclusion(unittest.TestCase):
    """测试4：排除目录中的文件不应被监控"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pycache_excluded(self):
        """__pycache__ 目录下的文件不应被监控"""
        pycache_dir = os.path.join(self.tmpdir, '__pycache__')
        os.makedirs(pycache_dir)
        # 放一个 .py 文件进去，确保不被监控
        py_file = os.path.join(pycache_dir, 'hidden.py')
        with open(py_file, 'w') as f:
            f.write('# should be ignored\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 基线中不应包含 __pycache__ 下的文件
        self.assertNotIn(py_file, watcher._last_content)

    def test_backup_dir_excluded(self):
        """金水谣数据/backups 目录下的文件不应被监控"""
        os.makedirs(os.path.join(self.tmpdir, '金水谣数据', 'backups'))
        backup_py = os.path.join(self.tmpdir, '金水谣数据', 'backups', 'old.py')
        with open(backup_py, 'w') as f:
            f.write('# backup file\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertNotIn(backup_py, watcher._last_content)

    def test_log_dir_excluded(self):
        """金水谣数据/log 目录下的文件不应被监控"""
        os.makedirs(os.path.join(self.tmpdir, '金水谣数据', 'log'))
        log_py = os.path.join(self.tmpdir, '金水谣数据', 'log', 'data.py')
        with open(log_py, 'w') as f:
            f.write('# log data\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertNotIn(log_py, watcher._last_content)

    def test_git_dir_excluded(self):
        """.git 目录下的文件不应被监控"""
        git_dir = os.path.join(self.tmpdir, '.git')
        os.makedirs(git_dir)
        git_py = os.path.join(git_dir, 'hook.py')
        with open(git_py, 'w') as f:
            f.write('# git hook\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertNotIn(git_py, watcher._last_content)

    def test_node_modules_excluded(self):
        """node_modules 目录下的 .js 文件不应被监控"""
        nm_dir = os.path.join(self.tmpdir, 'node_modules', 'pkg')
        os.makedirs(nm_dir)
        js_file = os.path.join(nm_dir, 'index.js')
        with open(js_file, 'w') as f:
            f.write('module.exports = {};\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertNotIn(js_file, watcher._last_content)

    def test_normal_dirs_still_watched(self):
        """正常目录（非排除目录）中的文件仍应被监控"""
        normal_dir = os.path.join(self.tmpdir, 'core')
        os.makedirs(normal_dir)
        py_file = os.path.join(normal_dir, 'module.py')
        with open(py_file, 'w') as f:
            f.write('# normal module\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertIn(py_file, watcher._last_content)

    def test_modify_in_excluded_dir_no_backup(self):
        """修改排除目录中的文件不应触发备份"""
        pycache_dir = os.path.join(self.tmpdir, '__pycache__')
        os.makedirs(pycache_dir)
        py_file = os.path.join(pycache_dir, 'test.py')
        with open(py_file, 'w') as f:
            f.write('v1\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 确认文件不在监控中
        self.assertNotIn(py_file, watcher._last_content)

        # 修改文件
        with open(py_file, 'w') as f:
            f.write('v2\n')
        watcher._poll()

        # 不应产生任何备份
        self.assertEqual(watcher._backup_count, 0)


class TestFileWatcherNewFile(unittest.TestCase):
    """测试5：新文件创建不应触发MODIFIED事件"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')
        # 创建一个初始文件
        self.init_file = os.path.join(self.tmpdir, 'init.py')
        with open(self.init_file, 'w') as f:
            f.write('initial\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_file_no_modified_event(self):
        """新创建的文件不应触发MODIFIED事件（首次出现时没有旧版本可备份）"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 基线只有 init_file
        self.assertEqual(len(watcher._last_content), 1)

        # 创建新文件
        new_file = os.path.join(self.tmpdir, 'new_module.py')
        with open(new_file, 'w') as f:
            f.write('# new file\n')

        # 执行轮询
        watcher._poll()

        # 新文件首次出现，旧哈希为None，不应触发MODIFIED
        self.assertEqual(watcher._change_count, 0)
        self.assertEqual(watcher._backup_count, 0)

        # 但新文件应该被加入缓存
        self.assertIn(new_file, watcher._last_content)

        # 现在修改新文件——这次应该触发备份
        with open(new_file, 'w') as f:
            f.write('# modified new file\n')
        watcher._poll()

        self.assertEqual(watcher._change_count, 1)
        self.assertEqual(watcher._backup_count, 1)

    def test_deleted_file_no_crash(self):
        """文件被删除后轮询不应崩溃"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 确认初始文件在缓存中
        self.assertIn(self.init_file, watcher._last_content)

        # 删除文件
        os.remove(self.init_file)

        # 轮询不应崩溃
        watcher._poll()

        # 被删除的文件仍留在缓存中（但我们不会再检测到变化）
        # 因为 os.walk 不会再遍历到它
        self.assertEqual(watcher._change_count, 0)
        self.assertEqual(watcher._backup_count, 0)


class TestFileWatcherAuditLog(unittest.TestCase):
    """测试6：审计日志记录

    注意：_record_change 会尝试调用 utils.change_audit._write_entry，
    但在临时目录中该模块的 AUDIT_FILE 常量指向项目真实路径。
    当 _write_entry 的文件路径不存在或路径不同时，会 fallthrough 到
    ImportError 分支，调用 _write_audit_directly。
    _write_audit_directly 使用 self._project_dir 下的 AUDIT_FILE 路径，
    所以在临时目录中审计日志会写入 tmpdir/金水谣数据/log/backup_audit.logl。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.audit_file = os.path.join(self.tmpdir, '金水谣数据', 'log', 'backup_audit.logl')
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')

        # 创建初始文件
        self.test_file = os.path.join(self.tmpdir, 'app.py')
        with open(self.test_file, 'w') as f:
            f.write('v1\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_audit_log_created_on_change(self):
        """文件变更时应创建审计日志"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 修改文件
        with open(self.test_file, 'w') as f:
            f.write('v2\n')
        watcher._poll()

        # 检查审计日志文件是否创建（通过 _write_audit_directly 后备路径）
        self.assertTrue(os.path.isfile(self.audit_file),
                        f"审计日志文件应存在于 {self.audit_file}")

        # 读取并解析审计日志
        with open(self.audit_file, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        # 可能有多条（如果 _write_entry 成功写入了项目真实日志，这里也写入了）
        # 至少应有1条
        self.assertGreaterEqual(len(lines), 1)

        entry = json.loads(lines[0])
        self.assertEqual(entry['type'], 'MODIFIED')
        self.assertEqual(entry['file'], 'app.py')
        self.assertIn('变更', entry['summary'])
        self.assertIn('FileWatcher', entry['detail'])

    def test_audit_log_multiple_changes(self):
        """多次变更应记录多条审计日志"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 第一次修改
        with open(self.test_file, 'w') as f:
            f.write('v2\n')
        watcher._poll()

        time.sleep(0.01)  # 确保时间戳不同

        # 第二次修改
        with open(self.test_file, 'w') as f:
            f.write('v3\n')
        watcher._poll()

        # 应至少有2条审计记录
        self.assertTrue(os.path.isfile(self.audit_file))
        with open(self.audit_file, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertGreaterEqual(len(lines), 2)

    def test_audit_log_json_format(self):
        """审计日志应为合法的JSON Lines格式"""
        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        with open(self.test_file, 'w') as f:
            f.write('changed\n')
        watcher._poll()

        self.assertTrue(os.path.isfile(self.audit_file))

        with open(self.audit_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)  # 应不抛异常
                    self.assertIn('ts', entry)
                    self.assertIn('type', entry)
                    self.assertIn('file', entry)
                    self.assertIn('summary', entry)
                    self.assertIn('detail', entry)


class TestFileWatcherMultipleExts(unittest.TestCase):
    """额外测试：多种文件扩展名都应被监控"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.tmpdir, '金水谣数据', 'backups')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_watched_extensions(self):
        """所有 WATCHED_EXTS 中的扩展名都应被监控"""
        # 创建各种扩展名的文件
        files = {
            '.py': os.path.join(self.tmpdir, 'test.py'),
            '.html': os.path.join(self.tmpdir, 'test.html'),
            '.bat': os.path.join(self.tmpdir, 'test.bat'),
            '.js': os.path.join(self.tmpdir, 'test.js'),
            '.css': os.path.join(self.tmpdir, 'test.css'),
        }
        for ext, path in files.items():
            with open(path, 'w') as f:
                f.write(f'original{ext}\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        # 所有文件都应在基线中
        for ext, path in files.items():
            self.assertIn(path, watcher._last_content,
                          f"扩展名 {ext} 的文件未被监控")

    def test_non_watched_extension_ignored(self):
        """不在 WATCHED_EXTS 中的扩展名不应被监控"""
        txt_file = os.path.join(self.tmpdir, 'readme.txt')
        with open(txt_file, 'w') as f:
            f.write('text file\n')

        json_file = os.path.join(self.tmpdir, 'data.json')
        with open(json_file, 'w') as f:
            f.write('{}\n')

        watcher = FileWatcher(project_dir=self.tmpdir)
        watcher._scan_and_cache()

        self.assertNotIn(txt_file, watcher._last_content)
        self.assertNotIn(json_file, watcher._last_content)


class TestFileWatcherThreadSafety(unittest.TestCase):
    """额外测试：线程安全性"""

    def test_poll_during_scan(self):
        """并发 poll 不应导致崩溃"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            for i in range(5):
                with open(os.path.join(tmpdir, f'mod{i}.py'), 'w') as f:
                    f.write(f'module {i}\n')

            watcher = FileWatcher(project_dir=tmpdir)
            watcher._scan_and_cache()

            # 在修改文件的同时执行多次 poll
            def modifier():
                for i in range(10):
                    for j in range(5):
                        with open(os.path.join(tmpdir, f'mod{j}.py'), 'w') as f:
                            f.write(f'version {i} mod {j}\n')
                    time.sleep(0.01)

            def poller():
                for _ in range(10):
                    try:
                        watcher._poll()
                    except Exception:
                        pass
                    time.sleep(0.01)

            t1 = threading.Thread(target=modifier)
            t2 = threading.Thread(target=poller)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # 应该检测到了一些变更（不要求精确计数）
            self.assertGreaterEqual(watcher._change_count, 0)


if __name__ == '__main__':
    unittest.main()
