# -*- coding: utf-8 -*-
"""数据三层隔离 · 写租约封装（T02 · 纯标准库）

LeaseManager 委托复用 scripts/session_coordinator.py 的 acquire/release/heartbeat
（单一全局 CLAIM，跨团队 / 跨会话串行化），对外提供：
  - acquire_for_write(rel_path, intent, wait_secs=30) -> bool
  - release() -> bool
  - heartbeat() -> bool
  - assert_live_writable(rel_path) -> bool
  - write_protected(rel_path, intent, writer_callable, wait_secs=30) -> bool

fail-safe：任何异常一律降级为 [G] 告警并返回 False，绝不抛异常阻断主流程
（直击「撞号 + 互删 + 悬空提交」事故；与①门禁去盲区一致）。
"""
import os
import sys
import platform

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import session_coordinator as _sc                       # 复用全局 CLAIM 底层
from layer_registry import LayerRegistry, write_alert, DEFAULT_REGISTRY


class LeaseManager:
    """写租约封装（复用 session_coordinator 全局 CLAIM）。

    可选注入：
      - registry：契约中心（默认 DEFAULT_REGISTRY）
      - holder：本会话标识（默认 session_coordinator.DEFAULT_HOLDER = 主机@pid）
      - sc_module：session_coordinator 替身（默认真实模块；测试可注入内存假实现，避免触碰真实全局锁）
    """

    def __init__(self, registry=None, holder=None, sc_module=None):
        self._reg = registry or DEFAULT_REGISTRY
        self._sc = sc_module or _sc
        self._holder = (
            holder
            or getattr(self._sc, "DEFAULT_HOLDER", None)
            or "%s@%d" % (platform.node(), os.getpid())
        )

    # —— 底层委托（全局 CLAIM）——
    def acquire_for_write(self, rel_path, intent, wait_secs=30):
        """占全局写锁。失败（被他者占用 / 超时）→ [G] 告警 + 返回 False。"""
        try:
            self._sc.acquire(intent, holder=self._holder, wait_secs=wait_secs)
            return True
        except RuntimeError as e:
            write_alert("写租约获取失败（降级为告警，不阻断）: path=%s intent=%s err=%s"
                        % (rel_path, intent, e))
            return False
        except Exception as e:  # 其它异常也 fail-safe
            write_alert("写租约获取异常（降级为告警）: path=%s err=%s" % (rel_path, e))
            return False

    def release(self):
        """释放全局写锁。"""
        try:
            return bool(self._sc.release(holder=self._holder, force=False))
        except Exception as e:
            write_alert("写租约释放异常（降级为告警）: err=%s" % e)
            return False

    def heartbeat(self):
        """刷新心跳（防 30min 过期自愈误抢）。"""
        try:
            return bool(self._sc.heartbeat(holder=self._holder))
        except Exception as e:
            write_alert("写租约心跳异常（降级为告警）: err=%s" % e)
            return False

    # —— 白名单 / 可写性 ——
    def assert_live_writable(self, rel_path):
        """活层写前可写性断言：保险 / 副本 / 未授权路径 → False 并告警。"""
        return self._reg.is_live_writable(rel_path)

    # —— 受保护写 ——
    def write_protected(self, rel_path, intent, writer_callable, wait_secs=30):
        """在全局写锁保护下执行 writer_callable（活层对共享文件的写）。

        流程：acquire → writer_callable() → release（finally）。
        任一异常 → [G] 告警 + release 清理 + 返回 False，绝不向上抛。
        返回 True 表示写入成功。
        """
        # 守卫：活层可写性（保险层/副本层/未授权 → False 并 [G] 告警，
        # 不进入占锁写，直击 PRD-17-P0-3「活层代码写保险层触发 [G] 告警」。
        if not self.assert_live_writable(rel_path):
            return False
        if not self.acquire_for_write(rel_path, intent, wait_secs=wait_secs):
            return False
        try:
            writer_callable()
            return True
        except Exception as e:
            write_alert("受保护写执行异常（降级为告警，不阻断）: path=%s intent=%s err=%s"
                        % (rel_path, intent, e))
            return False
        finally:
            self.release()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="数据三层隔离 · 写租约封装 CLI")
    ap.add_argument("action", choices=["acquire", "release", "heartbeat", "check"])
    ap.add_argument("--path", default="金水谣数据/brain_state.json")
    ap.add_argument("--intent", default="手动占锁")
    ap.add_argument("--wait", type=int, default=30)
    args = ap.parse_args()
    lm = LeaseManager()
    if args.action == "acquire":
        print("acquire:", lm.acquire_for_write(args.path, args.intent, args.wait))
    elif args.action == "release":
        print("release:", lm.release())
    elif args.action == "heartbeat":
        print("heartbeat:", lm.heartbeat())
    elif args.action == "check":
        print("is_live_writable:", lm.assert_live_writable(args.path))


if __name__ == "__main__":
    main()
