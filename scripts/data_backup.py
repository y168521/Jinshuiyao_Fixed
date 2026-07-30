# -*- coding: utf-8 -*-
"""数据三层隔离 · 副本层备份（T03 · 纯标准库）

BackupManager：活层 → 副本层（`金水谣数据/backups/`）周期快照 + 滚动保留 +
旧 `*.json.bak.0~2` 迁移 + manifest + 自检联动 jinshuiyao_data_guard。

快照路径：`<replica_root>/<tier>/<rel_path_sanitized>/<YYYYMMDD_HHMMSS_NNNNNN>.bak`
（目录条目则生成 `<...>.bak/` 目录副本）。`<rel_path_sanitized>` 把 `/` 替换为 `__`。

fail-safe：任何异常一律降级为 [G] 告警，不抛异常阻断主流程。
"""
import os
import re
import sys
import json
import shutil
import hashlib
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from layer_registry import (                              # noqa: E402
    LayerRegistry, write_alert, DEFAULT_REGISTRY,
    PROJECT_ROOT, JINSHUIYAO_DATA_DIR, REPLICA_DIR, DEFAULT_RETENTION,
)
from lease_helper import LeaseManager                    # noqa: E402

try:
    from jinshuiyao_data_guard import check_jinshuiyao_data   # 自检联动
except Exception:                                         # 防御：守护模块异常也不阻断备份
    check_jinshuiyao_data = None


_LEGACY_BAK_RE = re.compile(r"\.bak\.[0-2]$")     # 旧三代 *.json.bak.0~2


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_dir(path):
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            fp = os.path.join(root, name)
            h.update(os.path.relpath(fp, path).encode("utf-8"))
            h.update(_sha256_file(fp).encode("utf-8"))
    return h.hexdigest()


def _sanitize(rel_path):
    """相对路径的 / 替换为 __，用于副本层目录命名。"""
    return rel_path.replace("\\", "/").replace("/", "__")


def _now_ts():
    """时间戳：到微秒，避免高频调用快照名碰撞。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


class BackupManager:
    """副本层备份管理器。"""

    def __init__(self, registry=None, replica_root=None, live_root=None, sc_module=None):
        self._reg = registry or DEFAULT_REGISTRY
        self.replica_root = replica_root or REPLICA_DIR
        # rel_path 以项目根为基准（如 "金水谣数据/brain_state.json"），
        # 故 live_root 默认应取项目根而非 金水谣数据 子目录。
        self.live_root = live_root or PROJECT_ROOT
        self.retention = dict(DEFAULT_RETENTION)
        self.manifest_path = os.path.join(self.replica_root, "manifest.json")
        self._lm = LeaseManager(registry=self._reg, sc_module=sc_module)

    # —— 快照单条 ——
    def snapshot(self, rel_path, tier):
        """对单条活层条目生成副本层快照。

        路径：<replica_root>/<tier>/<sanitized>/<ts>.bak
        目录条目则生成 <ts>.bak/ 目录副本。
        返回 True 表示成功；任何失败 → [G] 告警 + False。
        """
        rel = rel_path.replace("\\", "/")
        live_path = os.path.join(self.live_root, rel)
        if not (os.path.isfile(live_path) or os.path.isdir(live_path)):
            write_alert("备份快照跳过（源不存在）: %s" % rel)
            return False
        if not self._lm.acquire_for_write(rel, "备份读快照", wait_secs=10):
            write_alert("备份快照跳过（占锁失败，降级告警）: %s" % rel)
            return False
        try:
            ts = _now_ts()
            dest_dir = os.path.join(self.replica_root, tier, _sanitize(rel))
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, ts + ".bak")
            if os.path.isdir(live_path):
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(live_path, dest)
            else:
                shutil.copy2(live_path, dest)
            return True
        except Exception as e:
            write_alert("备份快照异常（降级为告警，不阻断）: %s err=%s" % (rel, e))
            return False
        finally:
            try:
                self._lm.release()
            except Exception:
                pass

    # —— 滚动保留 ——
    def _prune(self, tier):
        """对指定 tier 下每个 (file) 目录保留最新 retention[tier] 份。"""
        try:
            tier_dir = os.path.join(self.replica_root, tier)
            if not os.path.isdir(tier_dir):
                return
            keep = self.retention.get(tier, 0)
            for entry_dir in os.listdir(tier_dir):
                d = os.path.join(tier_dir, entry_dir)
                if not os.path.isdir(d):
                    continue
                snaps = [
                    f for f in os.listdir(d)
                    if f.endswith(".bak") and (
                        os.path.isfile(os.path.join(d, f))
                        or os.path.isdir(os.path.join(d, f))
                    )
                ]
                snaps.sort(reverse=True)              # 最新在前
                for old in snaps[keep:]:
                    old_path = os.path.join(d, old)
                    try:
                        if os.path.isdir(old_path):
                            shutil.rmtree(old_path)
                        else:
                            os.remove(old_path)
                    except Exception as e:
                        write_alert("滚动保留删除失败（降级告警）: %s err=%s" % (old_path, e))
        except Exception as e:
            write_alert("滚动保留异常（降级为告警）: tier=%s err=%s" % (tier, e))

    # —— 一轮快照 ——
    def run_once(self):
        """跑一轮：对所有备份条目按频率档生成快照并滚动保留。返回成功条数。"""
        ok = 0
        for entry in self._reg.get_backup_entries():
            tier = entry.freq_tier
            if tier == "none":
                continue
            if self.snapshot(entry.rel_path, tier):
                ok += 1
            self._prune(tier)
        self.build_manifest()
        self.self_check()
        return ok

    # —— 旧 .bak 迁移 ——
    def migrate_legacy_bak(self):
        """把活层旧 *.json.bak.0~2 迁移进副本层（保留原文件兼容期）。返回迁移条数。"""
        count = 0
        try:
            for root, _dirs, files in os.walk(self.live_root):
                # 不递归进副本层自身
                if os.path.abspath(root).startswith(os.path.abspath(self.replica_root)):
                    continue
                for name in files:
                    if not _LEGACY_BAK_RE.search(name):
                        continue
                    src = os.path.join(root, name)
                    rel = os.path.relpath(src, self.live_root).replace("\\", "/")
                    # 去除 .bak.N 后缀，把三代归并到原文件目录，避免嵌套
                    base_rel = _LEGACY_BAK_RE.sub("", rel)
                    dest_dir = os.path.join(self.replica_root, "legacy", _sanitize(base_rel))
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(dest_dir, name)
                    if os.path.exists(dest):
                        continue                      # 已迁移则跳过（幂等）
                    shutil.copy2(src, dest)
                    count += 1
        except Exception as e:
            write_alert("旧 .bak 迁移异常（降级为告警）: err=%s" % e)
        return count

    # —— manifest ——
    def build_manifest(self):
        """扫描副本层所有 .bak（文件 / 目录）写入 manifest.json。"""
        try:
            manifest = []
            if os.path.isdir(self.replica_root):
                for tier in ("hourly", "daily", "weekly", "legacy"):
                    tier_dir = os.path.join(self.replica_root, tier)
                    if not os.path.isdir(tier_dir):
                        continue
                    for entry_dir in os.listdir(tier_dir):
                        ed = os.path.join(tier_dir, entry_dir)
                        if not os.path.isdir(ed):
                            continue
                        rel = entry_dir.replace("__", "/")   # 反解 sanitized
                        for snap in os.listdir(ed):
                            sp = os.path.join(ed, snap)
                            if not snap.endswith(".bak"):
                                continue
                            ts = snap[: -len(".bak")]
                            if os.path.isdir(sp):
                                sha = _sha256_dir(sp)
                                size = sum(
                                    os.path.getsize(os.path.join(r, f))
                                    for r, _, fs in os.walk(sp) for f in fs
                                )
                                mtime = max(
                                    (os.path.getmtime(os.path.join(r, f))
                                     for r, _, fs in os.walk(sp) for f in fs),
                                    default=0.0,
                                )
                            else:
                                sha = _sha256_file(sp)
                                size = os.path.getsize(sp)
                                mtime = os.path.getmtime(sp)
                            manifest.append({
                                "rel_path": rel,
                                "tier": tier,
                                "ts": ts,
                                "sha256": sha,
                                "mtime": mtime,
                                "size": size,
                            })
            os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"generated_at": datetime.now().isoformat(timespec="seconds"),
                     "snapshots": manifest},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            write_alert("manifest 生成异常（降级为告警）: err=%s" % e)

    # —— 自检联动 ——
    def self_check(self):
        """联动 jinshuiyao_data_guard。损坏 / 缺失 → [G] 告警。返回 bool。"""
        if check_jinshuiyao_data is None:
            return True
        try:
            ok = check_jinshuiyao_data()
            if not ok:
                write_alert("副本自检联动门禁：金水谣数据强校验项缺失（[G]告警）")
            return bool(ok)
        except Exception as e:
            write_alert("副本自检异常（降级为告警）: err=%s" % e)
            return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="数据三层隔离 · 副本层备份")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run-once")
    sub.add_parser("migrate-legacy")
    sub.add_parser("manifest")
    sub.add_parser("self-check")
    args = ap.parse_args()
    bm = BackupManager()
    if args.cmd == "run-once":
        print("快照成功条数:", bm.run_once())
    elif args.cmd == "migrate-legacy":
        print("迁移条数:", bm.migrate_legacy_bak())
    elif args.cmd == "manifest":
        bm.build_manifest()
        print("manifest 已生成:", bm.manifest_path)
    elif args.cmd == "self-check":
        print("self_check:", bm.self_check())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
