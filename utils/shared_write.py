# -*- coding: utf-8 -*-
"""共享文件受保护写助手（第二刀 JS-20260806-02）

把既有的 session_coordinator 全局 advisory 租约 + safe_write_json 原子写
封装成业务无侵入的助手，专治「多 AI 互覆盖」与「崩溃/并发丢数据」。

铁律（与 金水谣_契.md / AI协作交接中心.md 一致）：
  - 拿不到锁也**绝不丢数据**：锁失败降级为无锁直写 + [G] 告警。
  - 业务 JSON 一律不注入 _metadata（embed_checksum=False）。
"""
import os
import sys
import tempfile

# 让本模块能 import scripts/lease_helper（复用 LeaseManager + write_alert）
_THIS = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(os.path.dirname(_THIS), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import lease_helper  # noqa: E402
from lease_helper import LeaseManager, write_alert  # noqa: E402
from utils.safe_json import safe_write_json  # noqa: E402


def _atomic_write_text(path, content):
    """临时文件 + os.replace 原子写文本；失败清理临时文件。"""
    parent = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix=".pw_", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def protected_write_text(rel_path, content, mode="w", intent="写共享文档", wait_secs=15):
    """在全局写锁保护下写入文本（共享文档 / 知识库）。

    - mode='w'：原子写（临时文件 + os.replace）
    - mode='a'：加锁后追加（并发追加串行化）
    拿不到锁（被占 / 超时）→ [G] 告警 + 无锁直写（**不丢数据**）。
    返回 True / False。
    """
    lm = LeaseManager()
    acquired = lm.acquire_for_write(rel_path, intent, wait_secs=wait_secs)
    if not acquired:
        write_alert("[G] 受保护写未获锁，降级无锁直写（不丢数据）: %s" % rel_path)
        try:
            if mode == "a":
                with open(rel_path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                _atomic_write_text(rel_path, content)
            return True
        except Exception as e:
            write_alert("[G] 降级直写失败: %s err=%s" % (rel_path, e))
            return False
    try:
        if mode == "a":
            with open(rel_path, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            _atomic_write_text(rel_path, content)
        return True
    except Exception as e:
        write_alert("[G] 受保护写执行异常: %s err=%s" % (rel_path, e))
        return False
    finally:
        lm.release()


def protected_rmw_text(rel_path, transform, intent="改写共享文档", wait_secs=15):
    """读-改-写 在锁内完成（防并发 RMW 互覆盖）。transform(content:str)->str。

    锁失败仍直读直写（**不丢数据**）。返回 True / False。
    """
    def _do():
        with open(rel_path, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = transform(content)
        _atomic_write_text(rel_path, new_content)

    lm = LeaseManager()
    acquired = lm.acquire_for_write(rel_path, intent, wait_secs=wait_secs)
    if not acquired:
        write_alert("[G] 受保护RMW未获锁，降级无锁直写（不丢数据）: %s" % rel_path)
        try:
            _do()
            return True
        except Exception as e:
            write_alert("[G] 降级RMW失败: %s err=%s" % (rel_path, e))
            return False
    try:
        _do()
        return True
    except Exception as e:
        write_alert("[G] 受保护RMW异常: %s err=%s" % (rel_path, e))
        return False
    finally:
        lm.release()


def protected_write_json(rel_path, data, intent="写共享JSON", wait_secs=15):
    """在全局写锁保护下原子写 JSON（embed_checksum=False，满足契约）。

    锁成功 → safe_write_json → release；锁失败 → 直接 safe_write_json（**不丢数据**）。
    """
    lm = LeaseManager()
    acquired = lm.acquire_for_write(rel_path, intent, wait_secs=wait_secs)
    try:
        return bool(safe_write_json(rel_path, data, embed_checksum=False))
    except Exception as e:
        write_alert("[G] 受保护JSON写异常: %s err=%s" % (rel_path, e))
        return False
    finally:
        if acquired:
            lm.release()
