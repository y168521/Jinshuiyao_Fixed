# -*- coding: utf-8 -*-
"""
金水谣系统 - 全量数据备份/恢复工具

提供金水谣数据目录的打包备份、恢复和备份列表查询功能。
使用 Python 标准库 zipfile，不引入额外依赖。

Usage:
    from utils.data_backup import backup_all, restore_all, list_backups

    # 创建备份
    backup_path = backup_all()

    # 列出备份
    backups = list_backups()
    for b in backups:
        print(b)

    # 从备份恢复
    success = restore_all(backup_path)
"""

import os
import zipfile
import logging
import shutil
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# 默认数据目录（金水谣数据/）
_DEFAULT_DATA_DIR = None
_DEFAULT_BACKUP_SUBDIR = "backups"


def _get_default_data_dir() -> str:
    """获取默认的金水谣数据目录路径

    基于本文件位置推算项目根目录下的 金水谣数据/ 目录。

    Returns:
        str: 金水谣数据目录的绝对路径
    """
    global _DEFAULT_DATA_DIR
    if _DEFAULT_DATA_DIR is not None:
        return _DEFAULT_DATA_DIR
    # 本文件位于 utils/data_backup.py，项目根目录在上一级
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _DEFAULT_DATA_DIR = os.path.join(project_root, "金水谣数据")
    return _DEFAULT_DATA_DIR


def backup_all(data_dir: Optional[str] = None, output_dir: Optional[str] = None) -> str:
    """将金水谣数据目录打包为带时间戳的 zip 备份文件

    遍历 data_dir 下所有文件和子目录，打包为单个 zip 文件。
    默认保存到 金水谣数据/backups/ 目录。

    Args:
        data_dir: 要备份的数据目录路径，默认为项目根目录下的 金水谣数据/
        output_dir: 备份文件输出目录，默认为 data_dir/backups/

    Returns:
        str: 备份文件的绝对路径

    Raises:
        FileNotFoundError: 当 data_dir 不存在时抛出
        RuntimeError: 当备份创建失败时抛出

    Examples:
        >>> path = backup_all()
        >>> print(f"备份已保存到: {path}")
    """
    # 确定数据目录
    if data_dir is None:
        data_dir = _get_default_data_dir()

    data_dir = os.path.abspath(data_dir)

    # 校验数据目录
    if not os.path.isdir(data_dir):
        raise FileNotFoundError("数据目录不存在: {}".format(data_dir))

    # 确定输出目录
    if output_dir is None:
        output_dir = os.path.join(data_dir, _DEFAULT_BACKUP_SUBDIR)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 生成带时间戳的备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = "jinshuiyao_backup_{}.zip".format(timestamp)
    zip_path = os.path.join(output_dir, zip_filename)

    # 收集要备份的文件列表
    files_to_backup = []
    dir_name = os.path.basename(data_dir)

    for root, dirs, files in os.walk(data_dir):
        # 跳过 backups 子目录自身，避免递归备份
        if os.path.basename(root) == _DEFAULT_BACKUP_SUBDIR and root != data_dir:
            dirs.clear()
            continue

        for filename in files:
            abs_filepath = os.path.join(root, filename)
            # 在 zip 中的相对路径
            rel_path = os.path.relpath(abs_filepath, os.path.dirname(data_dir))
            files_to_backup.append((abs_filepath, rel_path))

    if not files_to_backup:
        logger.warning("数据目录为空，没有文件可备份: %s", data_dir)
        # 仍然创建空备份
        pass

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for abs_filepath, rel_path in files_to_backup:
                zf.write(abs_filepath, rel_path)

        file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        logger.info("全量备份完成: %s (共 %d 个文件, 大小: %.2f MB)",
                    zip_path, len(files_to_backup), file_size_mb)

        return zip_path

    except Exception as e:
        logger.error("创建备份失败: %s", e, exc_info=True)
        # 清理可能已创建的不完整文件
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        raise RuntimeError("创建备份失败: {}".format(e)) from e


def restore_all(backup_path: str, data_dir: Optional[str] = None) -> bool:
    """从 zip 备份文件恢复金水谣数据目录

    恢复前会先将当前数据目录备份到 backups/ 子目录中，
    然后清空目标目录并解压备份内容。

    Args:
        backup_path: 备份 zip 文件的路径
        data_dir: 要恢复到的目标数据目录，默认为项目根目录下的 金水谣数据/

    Returns:
        bool: 是否恢复成功

    Raises:
        FileNotFoundError: 当 backup_path 不存在时抛出
        RuntimeError: 当恢复过程中发生严重错误时抛出

    Examples:
        >>> success = restore_all("金水谣数据/backups/jinshuiyao_backup_20260714_120000.zip")
        >>> if success:
        ...     print("数据已成功恢复")
    """
    # 校验备份文件
    if not os.path.isfile(backup_path):
        raise FileNotFoundError("备份文件不存在: {}".format(backup_path))

    # 校验 zip 文件完整性
    try:
        with zipfile.ZipFile(backup_path, 'r') as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                raise RuntimeError("备份文件包含损坏的条目: {}".format(bad_file))
    except zipfile.BadZipFile as e:
        raise RuntimeError("备份文件不是有效的 zip 格式: {}".format(e)) from e

    # 确定目标目录
    if data_dir is None:
        data_dir = _get_default_data_dir()

    data_dir = os.path.abspath(data_dir)

    # 备份当前数据（在恢复之前）
    try:
        if os.path.isdir(data_dir) and os.listdir(data_dir):
            logger.info("恢复前备份当前数据...")
            _backup_current_data(data_dir)
    except Exception as e:
        logger.warning("恢复前备份当前数据失败（继续恢复）: %s", e)

    try:
        # 清空目标目录
        if os.path.isdir(data_dir):
            for item in os.listdir(data_dir):
                item_path = os.path.join(data_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                except OSError as e:
                    logger.warning("清空目标目录时删除失败: %s, 错误: %s", item_path, e)

        # 解压备份
        with zipfile.ZipFile(backup_path, 'r') as zf:
            # 获取 zip 中顶级目录名
            namelist = zf.namelist()

            # 检测 zip 内文件是否包含顶级目录前缀
            top_dirs = set()
            for name in namelist:
                parts = name.split('/')
                if parts[0]:
                    top_dirs.add(parts[0])

            extract_to = os.path.dirname(data_dir)

            # 解压所有文件
            for name in namelist:
                # 跳过目录条目
                if name.endswith('/'):
                    continue

                # 计算目标路径
                target_path = os.path.join(extract_to, name)

                # 确保目标路径在安全范围内（防止 zip 路径穿越）
                target_path = os.path.abspath(target_path)
                if not target_path.startswith(os.path.abspath(extract_to)):
                    logger.warning("跳过潜在路径穿越条目: %s", name)
                    continue

                # 创建必要的父目录
                os.makedirs(os.path.dirname(target_path), exist_ok=True)

                # 解压文件
                with zf.open(name) as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

        file_count = len([n for n in namelist if not n.endswith('/')])
        logger.info("数据恢复完成: 从 %s 恢复到 %s (共 %d 个文件)",
                    backup_path, data_dir, file_count)
        return True

    except Exception as e:
        logger.error("数据恢复失败: %s", e, exc_info=True)
        raise RuntimeError("数据恢复失败: {}".format(e)) from e


def list_backups(backup_dir: Optional[str] = None) -> List[Dict]:
    """列出所有可用的备份文件

    扫描备份目录，收集所有 jinshuiyao_backup_*.zip 文件的信息。

    Args:
        backup_dir: 备份文件目录路径，默认为 金水谣数据/backups/

    Returns:
        list[dict]: 备份信息列表，每个元素包含:
            - filename: 文件名
            - path: 完整路径
            - size_mb: 文件大小（MB）
            - created: 文件创建时间（从文件名解析或文件系统获取）

    Examples:
        >>> backups = list_backups()
        >>> for b in sorted(backups, key=lambda x: x['filename'], reverse=True):
        ...     print(f"{b['filename']} ({b['size_mb']:.2f} MB)")
    """
    if backup_dir is None:
        backup_dir = os.path.join(_get_default_data_dir(), _DEFAULT_BACKUP_SUBDIR)

    backup_dir = os.path.abspath(backup_dir)

    if not os.path.isdir(backup_dir):
        logger.debug("备份目录不存在: %s", backup_dir)
        return []

    backups = []
    for filename in os.listdir(backup_dir):
        if not filename.startswith("jinshuiyao_backup_") or not filename.endswith(".zip"):
            continue

        filepath = os.path.join(backup_dir, filename)

        try:
            size_bytes = os.path.getsize(filepath)
            size_mb = size_bytes / (1024 * 1024)

            # 尝试从文件名解析时间戳: jinshuiyao_backup_20260714_120000.zip
            created = None
            try:
                time_str = filename.replace("jinshuiyao_backup_", "").replace(".zip", "")
                created = datetime.strptime(time_str, "%Y%m%d_%H%M%S").isoformat()
            except ValueError:
                # 无法从文件名解析，使用文件系统修改时间
                created = datetime.fromtimestamp(
                    os.path.getmtime(filepath)
                ).isoformat()

            backups.append({
                "filename": filename,
                "path": filepath,
                "size_mb": round(size_mb, 2),
                "created": created,
            })
        except OSError as e:
            logger.warning("读取备份文件信息失败: %s, 错误: %s", filepath, e)
            continue

    return backups


def _backup_current_data(data_dir: str) -> str:
    """在恢复前备份当前数据目录（内部使用）

    将当前数据目录快速打包为安全备份，用于恢复失败时的回滚。

    Args:
        data_dir: 当前数据目录路径

    Returns:
        str: 安全备份的 zip 文件路径

    Raises:
        Exception: 备份失败时抛出
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(data_dir, _DEFAULT_BACKUP_SUBDIR)
    os.makedirs(backup_dir, exist_ok=True)

    zip_filename = "pre_restore_safe_{}.zip".format(timestamp)
    zip_path = os.path.join(backup_dir, zip_filename)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        dir_name = os.path.basename(data_dir)
        for root, dirs, files in os.walk(data_dir):
            # 跳过 backups 子目录
            if os.path.basename(root) == _DEFAULT_BACKUP_SUBDIR:
                dirs.clear()
                continue

            for filename in files:
                abs_filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_filepath, os.path.dirname(data_dir))
                zf.write(abs_filepath, rel_path)

    logger.info("恢复前安全备份已创建: %s", zip_path)
    return zip_path
