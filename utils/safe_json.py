# -*- coding: utf-8 -*-
"""
金水谣系统 - 数据安全模块

提供JSON文件的原子写入、自动备份、CRC校验和健康检查能力，
确保核心数据文件在任何异常情况下都不会损坏丢失。

功能清单:
    - safe_write_json:  原子写入 + 自动备份 + CRC校验嵌入
    - safe_load_json:   安全加载 + 自动校验 + 损坏恢复
    - auto_backup:      滚动备份（最多保留3个版本）
    - compute_checksum: 计算JSON内容的SHA256哈希
    - verify_checksum:  验证数据的校验和
    - check_file_health: 文件健康状态诊断
"""

import json
import os
import sys
import tempfile
import hashlib
import shutil
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("jinshuiyao.safe_json")


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _ensure_parent_dir(filepath: str) -> None:
    """确保文件所在目录存在，不存在则自动创建。"""
    parent = os.path.dirname(filepath)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
        logger.debug("自动创建目录: %s", parent)


def _file_size(filepath: str) -> int:
    """安全获取文件大小，文件不存在返回0。"""
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


def _file_mtime(filepath: str) -> Optional[str]:
    """安全获取文件最后修改时间，返回可读字符串。"""
    try:
        ts = os.path.getmtime(filepath)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return None


def _count_backups(filepath: str) -> int:
    """统计指定文件的备份数量。"""
    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    if not parent:
        parent = "."
    try:
        entries = os.listdir(parent)
    except OSError:
        return 0
    return sum(1 for e in entries if e.startswith(basename + ".bak."))



def _get_backup_files(filepath: str) -> list:
    """
    获取指定文件的所有备份文件路径，按序号从大到小排序（最新的在前）。
    备份文件名格式: {原文件名}.bak.{序号}
    """
    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    if not parent:
        parent = "."
    backup_files = []
    try:
        entries = os.listdir(parent)
    except OSError:
        return backup_files
    for entry in entries:
        if entry.startswith(basename + ".bak."):
            full_path = os.path.join(parent, entry)
            # 提取序号
            try:
                seq = int(entry[len(basename) + 5:])
            except ValueError:
                continue
            backup_files.append((seq, full_path))
    # 按序号从大到小排序，最新备份序号最大
    backup_files.sort(key=lambda x: x[0], reverse=True)
    return [path for _, path in backup_files]


def _strip_metadata_for_checksum(data: Any) -> Any:
    """
    去除数据中的 _metadata.checksum 字段，用于计算校验和。
    避免循环依赖：校验和不包含自身。

    如果去除 checksum 后 _metadata 变为空字典，也一并移除 _metadata 键，
    确保写入前（可能没有 _metadata 键）和验证时（有 _metadata 键）的计算结果一致。
    """
    if isinstance(data, dict):
        cleaned = {k: _strip_metadata_for_checksum(v) for k, v in data.items()}
        # 移除 _metadata 中的 checksum 字段
        if "_metadata" in cleaned and isinstance(cleaned["_metadata"], dict):
            remaining = {
                k: v for k, v in cleaned["_metadata"].items() if k != "checksum"
            }
            if remaining:
                cleaned["_metadata"] = remaining
            else:
                # _metadata 中只有 checksum，整个移除
                del cleaned["_metadata"]
        return cleaned
    elif isinstance(data, list):
        return [_strip_metadata_for_checksum(item) for item in data]
    else:
        return data


# ---------------------------------------------------------------------------
# CRC / SHA256 校验
# ---------------------------------------------------------------------------

def compute_checksum(data: Any) -> str:
    """
    计算JSON数据的SHA256哈希值。

    计算前会先去除 _metadata.checksum 字段，避免循环依赖。

    参数:
        data: 要计算哈希的Python对象（字典、列表等）

    返回:
        SHA256哈希字符串（十六进制，小写）
    """
    cleaned = _strip_metadata_for_checksum(data)
    content = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def verify_checksum(data: Any) -> bool:
    """
    验证数据中的校验和是否与内容匹配。

    检查 data["_metadata"]["checksum"] 字段，重新计算内容的哈希值进行比较。
    兼容旧格式：如果数据没有 _metadata.checksum 字段，视为通过（旧数据不强制校验）。

    参数:
        data: 已加载的Python对象

    返回:
        True - 校验通过或无校验和（旧格式兼容）
        False - 校验和不匹配
    """
    if not isinstance(data, dict):
        # 非dict类型（list/str等）不会嵌入checksum，直接通过
        return True
    metadata = data.get("_metadata")
    if not isinstance(metadata, dict):
        # 旧格式文件没有 _metadata 字段，视为通过（向后兼容）
        logger.debug("无 _metadata 字段，跳过校验（旧格式兼容）")
        return True
    stored_checksum = metadata.get("checksum")
    if not stored_checksum:
        # 有 _metadata 但没有 checksum，也视为通过
        logger.debug("无 checksum 字段，跳过校验（旧格式兼容）")
        return True
    actual_checksum = compute_checksum(data)
    if actual_checksum != stored_checksum:
        logger.warning(
            "校验失败: 校验和不匹配 (存储=%s, 实际=%s)",
            stored_checksum[:16],
            actual_checksum[:16],
        )
        return False
    logger.debug("校验通过: %s", stored_checksum[:16])
    return True


# ---------------------------------------------------------------------------
# 自动备份
# ---------------------------------------------------------------------------

def auto_backup(filepath: str, max_backups: int = 3) -> None:
    """
    自动备份文件，采用滚动策略保留最近若干个版本。

    备份文件名格式: {原文件名}.bak.{序号}
    序号从0开始，0为最新备份。每次备份时，旧备份序号递增，超出上限的删除。

    参数:
        filepath:     要备份的文件路径
        max_backups:  最多保留的备份数量，默认为3

    异常:
        如果原文件不存在或备份过程出错，记录日志但不抛出异常
    """
    if not os.path.isfile(filepath):
        logger.debug("跳过备份: 文件不存在 (%s)", filepath)
        return

    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    # 收集现有备份并按序号降序排列
    existing = []
    try:
        entries = os.listdir(parent if parent else ".")
    except OSError as e:
        logger.error("备份失败: 无法列出目录 %s (%s)", parent or ".", e)
        return

    prefix = basename + ".bak."
    for entry in entries:
        if entry.startswith(prefix):
            try:
                seq = int(entry[len(prefix):])
                existing.append((seq, entry))
            except ValueError:
                continue

    existing.sort(key=lambda x: x[0], reverse=True)

    # 滚动：旧备份序号 +1，超出上限的删除
    for seq, name in existing:
        if seq + 1 >= max_backups:
            # 删除超出上限的备份
            old_path = os.path.join(parent if parent else ".", name)
            try:
                os.remove(old_path)
                logger.debug("删除旧备份: %s", name)
            except OSError as e:
                logger.warning("删除备份失败: %s (%s)", name, e)
        else:
            # 序号递增
            old_path = os.path.join(parent if parent else ".", name)
            new_name = f"{basename}.bak.{seq + 1}"
            new_path = os.path.join(parent if parent else ".", new_name)
            try:
                os.replace(old_path, new_path)
            except OSError as e:
                logger.warning("重命名备份失败: %s -> %s (%s)", name, new_name, e)

    # 创建序号为0的最新备份
    backup_name = f"{basename}.bak.0"
    backup_path = os.path.join(parent if parent else ".", backup_name)
    try:
        shutil.copy2(filepath, backup_path)
        logger.info("已创建备份: %s", backup_path)
    except OSError as e:
        logger.error("创建备份失败: %s (%s)", backup_path, e)


# ---------------------------------------------------------------------------
# JSON Schema 基础验证
# ---------------------------------------------------------------------------

def _validate_schema(data: Any, required_keys: Optional[list] = None) -> bool:
    """
    基础JSON Schema结构验证：检查数据是否为字典且包含指定的顶层key。

    参数:
        data:          已加载的Python对象
        required_keys: 必须存在的顶层key列表，为None则跳过验证

    返回:
        True - 验证通过
        False - 验证失败
    """
    if required_keys is None:
        return True
    if not isinstance(data, dict):
        logger.warning("结构验证失败: 数据不是字典类型")
        return False
    missing = [k for k in required_keys if k not in data]
    if missing:
        logger.warning("结构验证失败: 缺少必要的顶层key: %s", missing)
        return False
    logger.debug("结构验证通过: 所有必要的key均存在")
    return True


# ---------------------------------------------------------------------------
# 原子写入
# ---------------------------------------------------------------------------

def safe_write_json(
    filepath: str,
    data: Any,
    embed_checksum: bool = False,
    backup: bool = True,
) -> bool:
    """
    安全写入JSON文件（原子操作 + 自动备份 + CRC校验嵌入）。

    写入流程:
        1. 确保目标目录存在
        2. 自动备份原文件（可选）
        3. 嵌入SHA256校验和到 _metadata.checksum（可选）
        4. 写入同目录临时文件
        5. 写入成功后用 os.replace() 原子替换原文件
        6. 写入失败则删除临时文件，原文件保持不变

    参数:
        filepath:         目标文件路径
        data:             要写入的Python对象（字典、列表等）
        embed_checksum:   是否嵌入SHA256校验和，默认False（契/交接中心铁律：业务数据禁注入 _metadata）
        backup:           是否在写入前自动备份，默认True

    返回:
        True - 写入成功
        False - 写入失败
    """
    try:
        _ensure_parent_dir(filepath)

        # 自动备份
        if backup and os.path.isfile(filepath):
            auto_backup(filepath)

        # 嵌入校验和（使用 sort_keys=True 的紧凑格式来保证计算一致性）
        write_data = data
        if embed_checksum:
            if isinstance(data, dict):
                write_data = dict(data)  # 浅拷贝，不修改原始数据
                if "_metadata" not in write_data or not isinstance(write_data["_metadata"], dict):
                    write_data["_metadata"] = {}
                # compute_checksum 已正确排除 _metadata.checksum 字段，
                # 并使用 sort_keys=True + 紧凑分隔符来保证序列化结果确定性
                write_data["_metadata"]["checksum"] = compute_checksum(data)
                logger.debug("已嵌入校验和: %s", write_data["_metadata"]["checksum"][:16])
            else:
                logger.debug("数据非字典类型，跳过校验和嵌入")

        # 写入临时文件（同目录，确保同一文件系统以支持原子替换）
        parent = os.path.dirname(filepath) or "."
        try:
            fd_num, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix=".safe_json_",
                dir=parent,
            )
        except OSError as e:
            logger.error("创建临时文件失败: %s (%s)", filepath, e)
            return False

        write_ok = False
        try:
            with os.fdopen(fd_num, "w", encoding="utf-8") as f:
                json.dump(write_data, f, ensure_ascii=False, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            write_ok = True
        except (OSError, TypeError) as e:
            logger.error("写入临时文件失败: %s (%s)", tmp_path, e)
            try:
                os.close(fd_num)
            except OSError:
                pass
            # 删除失败的临时文件
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False

        # 原子替换
        try:
            os.replace(tmp_path, filepath)
        except OSError as e:
            logger.error("原子替换失败: %s -> %s (%s)", tmp_path, filepath, e)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False

        logger.info("安全写入成功: %s (%d字节)", filepath, _file_size(filepath))
        return True

    except Exception as e:
        logger.error("safe_write_json 未知异常: %s (%s)", filepath, e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# 安全加载
# ---------------------------------------------------------------------------

def safe_load_json(
    filepath: str,
    default: Any = None,
    verify_checksum_flag: bool = True,
    required_keys: Optional[list] = None,
) -> Any:
    """
    安全加载JSON文件（自动校验 + 损坏自动恢复）。

    加载流程:
        1. 检查文件是否存在
        2. 读取并解析JSON
        3. 校验SHA256（可选）
        4. 验证结构（可选）
        5. 如果解析失败，自动从最新备份恢复
        6. 如果所有备份都损坏，返回默认值

    参数:
        filepath:             文件路径
        default:              文件不存在或所有备份都损坏时返回的默认值
        verify_checksum_flag: 是否校验SHA256，默认True
        required_keys:        必须存在的顶层key列表（基础结构验证），为None则跳过

    返回:
        加载成功的Python对象，或 default
    """
    # 文件不存在，直接返回默认值
    if not os.path.isfile(filepath):
        logger.warning("文件不存在: %s，返回默认值", filepath)
        return default

    # --- 尝试正常加载 ---
    data = _try_load(filepath, verify_checksum_flag, required_keys)
    if data is not None:
        return data

    # --- 正常加载失败，尝试从备份恢复 ---
    backup_files = _get_backup_files(filepath)
    if not backup_files:
        logger.warning("无可用备份，返回默认值: %s", filepath)
        return default

    logger.warning(
        "主文件损坏，尝试从备份恢复: %s (可用备份: %d个)",
        filepath,
        len(backup_files),
    )

    for backup_path in backup_files:
        logger.info("尝试恢复: %s", backup_path)
        data = _try_load(backup_path, verify_checksum_flag=False, required_keys=required_keys)
        if data is not None:
            logger.info("备份恢复成功: %s -> %s", backup_path, filepath)
            # 将恢复的数据重新写入主文件
            safe_write_json(filepath, data, embed_checksum=verify_checksum_flag, backup=False)
            return data
        else:
            logger.warning("备份也损坏: %s", backup_path)

    logger.error("所有备份均损坏，返回默认值: %s", filepath)
    return default


def _try_load(
    filepath: str,
    verify_checksum_flag: bool,
    required_keys: Optional[list],
) -> Any:
    """
    尝试从指定文件加载JSON数据（内部函数）。

    返回:
        成功 - 解析后的Python对象
        失败 - None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 校验SHA256
        if verify_checksum_flag:
            if not verify_checksum(data):
                logger.warning("校验和不通过: %s", filepath)
                return None

        # 结构验证
        if not _validate_schema(data, required_keys):
            return None

        logger.debug("安全加载成功: %s", filepath)
        return data

    except json.JSONDecodeError as e:
        logger.error("JSON解析失败: %s (%s)", filepath, e)
        return None
    except OSError as e:
        logger.error("读取文件失败: %s (%s)", filepath, e)
        return None
    except Exception as e:
        logger.error("加载异常: %s (%s)", filepath, e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 文件健康检查
# ---------------------------------------------------------------------------

def check_file_health(filepath: str) -> dict:
    """
    检查JSON文件的健康状态，返回详细诊断信息。

    返回字典包含:
        - status:     健康状态 (healthy / corrupted / missing / backup_available)
        - file_size:  文件大小（字节）
        - backup_count: 备份文件数量
        - last_modified: 最后修改时间
        - checksum_valid: 校验和是否有效（None表示无法校验）
        - backups:    备份文件列表
        - details:    附加说明

    参数:
        filepath: 要检查的文件路径

    返回:
        包含健康诊断信息的字典
    """
    result = {
        "status": "missing",
        "file_size": 0,
        "backup_count": 0,
        "last_modified": None,
        "checksum_valid": None,
        "backups": [],
        "details": "",
    }

    if not os.path.isfile(filepath):
        result["status"] = "missing"
        result["details"] = "文件不存在"
        result["backup_count"] = _count_backups(filepath)
        if result["backup_count"] > 0:
            result["status"] = "backup_available"
            result["details"] = f"文件不存在，但有 {result['backup_count']} 个备份可用"
        return result

    result["file_size"] = _file_size(filepath)
    result["last_modified"] = _file_mtime(filepath)
    result["backup_count"] = _count_backups(filepath)

    # 尝试解析JSON
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result["status"] = "corrupted"
        result["details"] = f"JSON解析失败: {e}"
        result["checksum_valid"] = False
        return result
    except OSError as e:
        result["status"] = "corrupted"
        result["details"] = f"读取失败: {e}"
        result["checksum_valid"] = None
        return result

    # 校验和验证
    result["checksum_valid"] = verify_checksum(data)

    if result["checksum_valid"]:
        result["status"] = "healthy"
        result["details"] = "文件正常"
    else:
        result["status"] = "corrupted"
        result["details"] = "校验和不匹配，文件可能被篡改或损坏"

    # 收集备份文件信息
    backup_files = _get_backup_files(filepath)
    for bp in backup_files:
        result["backups"].append({
            "path": bp,
            "size": _file_size(bp),
            "last_modified": _file_mtime(bp),
        })

    return result


# ---------------------------------------------------------------------------
# 模块自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 配置日志输出到控制台
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    test_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "_safe_json_test_",
    )
    os.makedirs(test_dir, exist_ok=True)
    test_file = os.path.join(test_dir, "test_data.json")

    print("=" * 60)
    print("金水谣 safe_json 模块自测")
    print("=" * 60)

    # 测试1: 基本写入和读取
    print("\n--- 测试1: 基本写入和读取 ---")
    test_data = {"version": 1, "name": "金水谣", "items": [1, 2, 3]}
    ok = safe_write_json(test_file, test_data)
    print(f"写入结果: {'成功' if ok else '失败'}")

    loaded = safe_load_json(test_file, default={})
    print(f"读取数据: {loaded}")
    print(f"数据一致: {loaded is not None and loaded.get('version') == 1}")

    # 测试2: 备份机制
    print("\n--- 测试2: 备份机制 ---")
    for i in range(4):
        test_data["version"] = i + 2
        test_data["name"] = f"金水谣_v{i + 2}"
        safe_write_json(test_file, test_data)

    backup_files = _get_backup_files(test_file)
    print(f"备份数量: {len(backup_files)} (应保留3个)")
    for bf in backup_files:
        with open(bf, "r", encoding="utf-8") as f:
            bd = json.load(f)
        print(f"  {os.path.basename(bf)}: version={bd.get('version')}")

    # 测试3: 损坏恢复
    print("\n--- 测试3: 损坏恢复 ---")
    # 篡改主文件
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("{损坏的JSON内容!!!")
    print("已手动损坏主文件")

    recovered = safe_load_json(test_file, default={"error": True})
    print(f"恢复结果: {recovered}")
    print(f"恢复成功: {not recovered.get('error', False)}")

    # 测试4: 健康检查
    print("\n--- 测试4: 健康检查 ---")
    health = check_file_health(test_file)
    print(f"健康状态: {health['status']}")
    print(f"文件大小: {health['file_size']} 字节")
    print(f"备份数量: {health['backup_count']}")
    print(f"校验有效: {health['checksum_valid']}")

    # 测试5: 不存在的文件
    print("\n--- 测试5: 不存在的文件 ---")
    missing_file = os.path.join(test_dir, "nonexistent.json")
    health2 = check_file_health(missing_file)
    print(f"状态: {health2['status']} - {health2['details']}")
    data2 = safe_load_json(missing_file, default={"fallback": True})
    print(f"默认值: {data2}")

    # 清理测试文件
    shutil.rmtree(test_dir, ignore_errors=True)
    print(f"\n已清理测试目录: {test_dir}")

    print("\n" + "=" * 60)
    print("自测完成")
    print("=" * 60)
