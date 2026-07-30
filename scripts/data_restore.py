# -*- coding: utf-8 -*-
"""数据三层隔离 · 恢复脚本（T04 · 纯标准库）

RestoreManager：从副本层（`金水谣数据/backups/`）一键恢复指定文件 / 目录到活层，
含 sha256 完整性校验 + 可读恢复报告。失败一律 [G] 告警 + RecoveryReport(ok=False)，不抛异常。

流程（与 _seq.mermaid ③ 一致）：
  list_points(rel) → 查 manifest 得恢复点（tier/ts/sha256/snapshot_path）
  restore(rel, point="latest") → _verify(快照, 期望 hash) → 占锁覆盖写活层 → 出 RecoveryReport
"""
import os
import sys
import json
import shutil
from dataclasses import dataclass

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from layer_registry import (                             # noqa: E402
    LayerRegistry, write_alert, DEFAULT_REGISTRY,
    PROJECT_ROOT, JINSHUIYAO_DATA_DIR, REPLICA_DIR, INSURANCE_DIR,
)
from lease_helper import LeaseManager                     # noqa: E402
from data_backup import _sha256_file, _sha256_dir, _sanitize   # noqa: E402


@dataclass
class RecoveryReport:
    """恢复报告。"""
    file: str
    source: str
    target: str
    ok: bool
    hash_before: str = ""
    hash_after: str = ""
    message: str = ""


class RestoreManager:
    """恢复管理器。"""

    def __init__(self, registry=None, replica_root=None, live_root=None,
                 insurance_root=None, sc_module=None):
        self._reg = registry or DEFAULT_REGISTRY
        self.replica_root = replica_root or REPLICA_DIR
        # rel_path 以项目根为基准，故 live_root 默认取项目根。
        self.live_root = live_root or PROJECT_ROOT
        self.insurance_root = insurance_root or INSURANCE_DIR
        self.manifest_path = os.path.join(self.replica_root, "manifest.json")
        self._lm = LeaseManager(registry=self._reg, sc_module=sc_module)

    # —— 列出恢复点 ——
    def list_points(self, rel_path):
        """返回该文件可用恢复点列表（按时间倒序），元素含 tier/ts/sha256/snapshot_path。"""
        rel = rel_path.replace("\\", "/")
        points = []
        try:
            if os.path.isfile(self.manifest_path):
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for snap in data.get("snapshots", []):
                    if snap.get("rel_path") == rel:
                        tier = snap.get("tier", "hourly")
                        ts = snap.get("ts", "")
                        sp = os.path.join(self.replica_root, tier, _sanitize(rel), ts + ".bak")
                        points.append({
                            "tier": tier,
                            "ts": ts,
                            "sha256": snap.get("sha256", ""),
                            "snapshot_path": sp,
                        })
            points.sort(key=lambda x: x["ts"], reverse=True)
        except Exception as e:
            write_alert("列出恢复点异常（降级为告警）: %s err=%s" % (rel, e))
        return points

    # —— 校验 ——
    def _verify(self, snapshot_path, expected_hash):
        """比对快照实际 sha256 与期望 hash。"""
        try:
            if os.path.isdir(snapshot_path):
                actual = _sha256_dir(snapshot_path)
            elif os.path.isfile(snapshot_path):
                actual = _sha256_file(snapshot_path)
            else:
                return False
            return actual == expected_hash
        except Exception as e:
            write_alert("快照校验异常（降级为告警）: %s err=%s" % (snapshot_path, e))
            return False

    # —— 恢复 ——
    def restore(self, rel_path, point="latest"):
        """从副本层恢复指定文件 / 目录到活层。

        point="latest" 取最新；或指定 ts。
        成功 → 覆盖写活层 + RecoveryReport(ok=True)；
        缺失 / 损坏 / 校验失败 → [G] 告警 + RecoveryReport(ok=False)。不抛异常。
        """
        rel = rel_path.replace("\\", "/")
        target = os.path.join(self.live_root, rel)
        points = self.list_points(rel)
        if not points:
            return self.generate_report(rel, "", target, False, "", "",
                                      "无可用的副本层恢复点")
        chosen = points[0] if point == "latest" else next(
            (p for p in points if p["ts"] == point), None)
        if chosen is None:
            return self.generate_report(rel, "", target, False, "", "",
                                       "指定恢复点不存在: %s" % point)
        snap = chosen["snapshot_path"]
        if not (os.path.isfile(snap) or os.path.isdir(snap)):
            return self.generate_report(rel, snap, target, False, "", "",
                                      "快照文件缺失")
        if not self._verify(snap, chosen["sha256"]):
            return self.generate_report(rel, snap, target, False, "", "",
                                      "快照完整性校验失败（sha256 不匹配或文件损坏）")
        # 校验通过 → 占锁覆盖写
        hash_before = self._hash_live(rel)
        if not self._lm.acquire_for_write(rel, "恢复写入", wait_secs=30):
            return self.generate_report(rel, snap, target, False, hash_before, "",
                                      "恢复写入占锁失败（降级告警，不阻断）")
        try:
            if os.path.isdir(snap):
                if os.path.isdir(target):
                    shutil.rmtree(target)
                elif os.path.exists(target):
                    os.remove(target)
                shutil.copytree(snap, target)
            else:
                parent = os.path.dirname(target)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.copy2(snap, target)
            hash_after = self._hash_live(rel)
            return self.generate_report(rel, snap, target, True, hash_before, hash_after,
                                      "恢复成功")
        except Exception as e:
            return self.generate_report(rel, snap, target, False, hash_before, "",
                                      "恢复写入异常（降级为告警）: %s" % e)
        finally:
            self._lm.release()

    # —— 辅助 ——
    def _hash_live(self, rel):
        p = os.path.join(self.live_root, rel)
        try:
            if os.path.isdir(p):
                return _sha256_dir(p)
            if os.path.isfile(p):
                return _sha256_file(p)
        except Exception:
            pass
        return ""

    def generate_report(self, file, source, target, ok, hash_before, hash_after, message):
        if not ok:
            # fail-safe：恢复失败一律降级为 [G] 告警（R-002 early_signal /
            # 设计 §5③「失败/缺失→[G]告警+RecoveryReport(ok=False)」）
            write_alert("恢复失败: %s | %s -> %s | %s" % (file, source, target, message))
        return RecoveryReport(
            file=file, source=source, target=target, ok=ok,
            hash_before=hash_before, hash_after=hash_after, message=message,
        )


def main():
    import argparse
    ap = argparse.ArgumentParser(description="数据三层隔离 · 恢复脚本")
    sub = ap.add_subparsers(dest="cmd")
    lp = sub.add_parser("list")
    lp.add_argument("--path", required=True)
    rs = sub.add_parser("restore")
    rs.add_argument("--path", required=True)
    rs.add_argument("--point", default="latest")
    args = ap.parse_args()
    rm = RestoreManager()
    if args.cmd == "list":
        for p in rm.list_points(args.path):
            print(p)
    elif args.cmd == "restore":
        rep = rm.restore(args.path, args.point)
        print("ok=%s | %s -> %s | %s" % (rep.ok, rep.source, rep.target, rep.message))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
