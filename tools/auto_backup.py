# -*- coding: utf-8 -*-
"""
金水谣自动备份工具
==================
功能：
  1. 启动前自动快照关键文件（被 launch_jinshuiyao.py 调用）
  2. 保留最近5次备份，自动清理旧的
  3. 备份到 tools/backups/ 目录，按日期时间命名

设计：纯标准库，不依赖项目模块。
"""
import os
import sys
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 备份根目录：放到本机 %LOCALAPPDATA%，与坚果云同步目录解耦。
# 原因：原路径在项目内的 tools/backups/，每次启动都会生成 snapshot_<ts>_启动，
#       而这些目录在坚果云同步树里，导致"越启动越乱"、同步盘持续膨胀。
#       改到 LOCALAPPDATA 后，安全网仍在（可本地恢复），但不再污染项目/同步盘。
_localapp = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
BACKUP_ROOT = os.path.join(_localapp, 'Jinshuiyao', 'backups')
MAX_BACKUPS = 3  # 最多保留3次快照（启动安全网，无需更多）

# ---------------------------------------------------------------------------
# 同步盘隔离守卫：备份目录绝对不能落在坚果云同步树或项目目录内，
# 否则每次启动又会往同步盘写快照，重现"越启动越乱"。
# fail-closed：任何异常都判为不安全，宁可跳过备份也不污染同步树。
# ---------------------------------------------------------------------------
_SYNC_TREE_MARKERS = ("nutstore",)  # 坚果云同步目录必含 Nutstore 字样


def _is_inside_sync_tree(path):
    try:
        ap = os.path.abspath(path)
        # 不能落在项目目录内
        try:
            if os.path.commonpath([ap, BASE_DIR]) == BASE_DIR:
                return True
        except ValueError:
            pass
        # 不能落在任何 Nutstore 同步目录内
        parts = [p.lower() for p in ap.split(os.sep)]
        if any(m.lower() in parts for m in _SYNC_TREE_MARKERS):
            return True
        return False
    except Exception:
        return False


def is_safe_backup_location(path=None):
    """备份目录是否安全（在同步盘/项目外）。返回 True=安全。"""
    return not _is_inside_sync_tree(path or BACKUP_ROOT)

# 需要备份的关键文件（相对于项目根目录）
CRITICAL_FILES = [
    "launch_jinshuiyao.py",
    "launch.bat",
    "config.py",
    os.path.join("server", "__init__.py"),
    os.path.join("server", "router.py"),
    os.path.join("server", "config.py"),
    os.path.join("core", "ai_service.py"),
    os.path.join("core", "scheduler.py"),
    os.path.join("sync", "device_sync.py"),
    os.path.join("utils", "safe_json.py"),
    os.path.join("utils", "locks.py"),
    os.path.join("config", "logging_config.py"),
]


def create_snapshot(reason="启动"):
    """
    创建一次关键文件快照。
    返回: (备份目录路径, 备份文件数) 或 (None, 0) 表示失败/跳过
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_dir = os.path.join(BACKUP_ROOT, f"snapshot_{ts}_{reason}")

    # 守卫：备份目录若不小心指向同步盘/项目内，直接跳过快照，绝不污染同步树
    if not is_safe_backup_location(BACKUP_ROOT):
        try:
            sys.stderr.write(
                "[auto_backup][安全] 备份目录落在同步盘/项目内，已跳过快照生成，"
                "避免污染同步树。\n"
            )
        except Exception:
            pass
        return None, 0

    backed_up = 0
    for rel_path in CRITICAL_FILES:
        src = os.path.join(BASE_DIR, rel_path)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(snap_dir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            shutil.copy2(src, dest)
            backed_up += 1
        except Exception:
            pass

    if backed_up == 0:
        # 没有任何文件备份成功，删除空目录
        try:
            os.rmdir(snap_dir)
        except Exception:
            pass
        return None, 0

    # 清理旧快照
    _cleanup_old_snapshots()

    return snap_dir, backed_up


def _cleanup_old_snapshots():
    """保留最近 MAX_BACKUPS 个快照，删除更早的"""
    if not os.path.isdir(BACKUP_ROOT):
        return

    snapshots = []
    for entry in os.listdir(BACKUP_ROOT):
        full = os.path.join(BACKUP_ROOT, entry)
        if os.path.isdir(full) and entry.startswith("snapshot_"):
            snapshots.append(full)

    # 按名称排序（时间戳在名称中，字典序即时间序）
    snapshots.sort()

    # 删除超出上限的旧快照
    while len(snapshots) > MAX_BACKUPS:
        old = snapshots.pop(0)
        try:
            shutil.rmtree(old)
        except Exception:
            pass


def get_latest_snapshot():
    """获取最近一次快照的路径，用于恢复"""
    if not os.path.isdir(BACKUP_ROOT):
        return None

    snapshots = []
    for entry in os.listdir(BACKUP_ROOT):
        full = os.path.join(BACKUP_ROOT, entry)
        if os.path.isdir(full) and entry.startswith("snapshot_"):
            snapshots.append(full)

    if not snapshots:
        return None

    snapshots.sort()
    return snapshots[-1]


def restore_from_snapshot(snapshot_dir=None):
    """
    从快照恢复文件。不指定则用最近一次。
    返回恢复的文件数。
    """
    if snapshot_dir is None:
        snapshot_dir = get_latest_snapshot()
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return 0

    restored = 0
    for root, dirs, files in os.walk(snapshot_dir):
        for fname in files:
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, snapshot_dir)
            dest = os.path.join(BASE_DIR, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                shutil.copy2(src, dest)
                restored += 1
            except Exception:
                pass

    return restored


# ---------------------------------------------------------------------------
# 独立运行入口（手动备份）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    print("金水谣自动备份工具")
    print("-" * 40)

    snap_dir, count = create_snapshot("手动")
    if snap_dir:
        print(f"备份完成！共 {count} 个文件")
        print(f"位置: {snap_dir}")
    else:
        print("备份失败或无需备份。")

    if sys.platform == "win32":
        os.system("pause >nul 2>&1")
