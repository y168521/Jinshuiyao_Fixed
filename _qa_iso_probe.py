# -*- coding: utf-8 -*-
"""QA 独立集成探针：真跑 ④ 数据三层隔离核心链路（不污染真实数据，用临时工作区）。

bm / rm 注入 _FakeSC 内存 mock，使快照/恢复走「隔离逻辑」本身、不触碰真实
session_coordinator（真实协调器另有单独的 _qa_sc_smoke.py 冒烟测试）。
这与 18 个 pytest 的做法一致——单元/集成测试验证的是 ④ 隔离逻辑，而非协调器本身。

每个段落后即时 _flush 写盘，确保即便后续被环境异常中断，前面证据也已落盘。
"""
import os, sys, time, threading, tempfile, shutil, traceback, json

PROJ = r"C:\Users\Administrator\Nutstore\1\我的坚果云/模型/Jinshuiyao_Fixed"
sys.path.insert(0, os.path.join(PROJ, "scripts"))
import layer_registry as lr
import lease_helper as lh
import data_backup as db
import data_restore as dr

R = []
def log(m):
    R.append(str(m))

def _flush():
    try:
        out = "\n".join(R)
        with open(os.path.join(PROJ, "_qa_iso_report.txt"), "w", encoding="utf-8") as f:
            f.write(out)
    except Exception:
        pass

# 内存 mock 协调器（复刻全局 CLAIM 语义，供 bm/rm 注入）
class _FakeSC:
    def __init__(self):
        self._c = None; self._cv = threading.Condition()
    def acquire(self, intent, holder="h", stale_secs=1800, wait_secs=0, poll=0.01):
        dl = time.time() + max(0, wait_secs)
        with self._cv:
            while True:
                now = time.time()
                if self._c is None:
                    self._c = {"holder": holder, "intent": intent, "heartbeat": now}; return dict(self._c)
                if self._c["holder"] == holder:
                    self._c["heartbeat"] = now; self._c["intent"] = intent; return dict(self._c)
                if (now - self._c["heartbeat"]) > stale_secs:
                    self._c = {"holder": holder, "intent": intent, "heartbeat": now}; return dict(self._c)
                if now >= dl:
                    raise RuntimeError("locked by %s" % self._c["holder"])
                self._cv.wait(min(0.02, max(0, dl - now)))
    def release(self, holder="h", force=False):
        with self._cv:
            if self._c is None: return True
            if force or self._c["holder"] == holder:
                self._c = None; self._cv.notify_all(); return True
            return False
    def heartbeat(self, holder="h"):
        with self._cv:
            if self._c and self._c["holder"] == holder:
                self._c["heartbeat"] = time.time(); return True
            return False

try:
    WS = tempfile.mkdtemp(prefix="qa_iso_")
    live = os.path.join(WS, "live"); replica = os.path.join(WS, "replica"); ins = os.path.join(WS, "insurance")
    os.makedirs(os.path.join(live, "金水谣数据")); os.makedirs(ins)
    ALERT = os.path.join(WS, "isolation_alerts.log")
    os.environ["ISOLATION_ALERT_LOG"] = ALERT

    sc = _FakeSC()
    reg = lr.LayerRegistry()
    bm = db.BackupManager(registry=reg, replica_root=replica, live_root=live, sc_module=sc)
    rm = dr.RestoreManager(registry=reg, replica_root=replica, live_root=live, insurance_root=ins, sc_module=sc)

    # ===== 演示/真实分类 =====
    log("===== 演示/真实分类 (classify_demo_real) =====")
    for p, exp in [("jinshuiyao/data/matches_real.csv", "real"),
                   ("foo_demo.json", "demo"),
                   ("foo_supplemented.json", "demo"),
                   ("plain.json", "unknown")]:
        got = reg.classify_demo_real(p)
        log("  %-40s -> %s (期望 %s) %s" % (p, got, exp, "OK" if got == exp else "FAIL"))
    _flush()

    # ===== 活层可写性 =====
    log("===== 活层可写性 is_live_writable (非授权→False+[G]告警) =====")
    cases = [
        ("金水谣数据/insurance/x.json", False, "保险层"),
        ("金水谣数据/backups/hourly/x/y.bak", False, "副本层"),
        ("unauthorized/foo.txt", False, "未授权"),
        ("金水谣数据/brain_state.json", True, "白名单"),
    ]
    for p, exp, label in cases:
        got = reg.is_live_writable(p)
        log("  %-42s -> %s (期望 %s) %s" % (label + ":" + p, got, exp, "OK" if got == exp else "FAIL"))
    alert0 = open(ALERT, encoding="utf-8").read() if os.path.exists(ALERT) else ""
    log("  [G]告警已写入隔离日志: 行数=%d, 含[G]=%s" % (alert0.count("\n"), "[G]" in alert0))
    _flush()

    # ===== 周期快照 + 滚动保留 =====
    log("===== 备份快照 + 滚动保留 (hourly=24 / daily=7) =====")
    rel = "金水谣数据/brain_state.json"
    src = os.path.join(live, rel)
    for i in range(30):
        open(src, "w", encoding="utf-8").write("BASE-%d" % i)
        bm.snapshot(rel, "hourly")
    bm._prune("hourly")
    ddir = os.path.join(replica, "hourly", db._sanitize(rel))
    n = len([f for f in os.listdir(ddir) if f.endswith(".bak")])
    log("  30次快照后 _prune('hourly') 保留数=%d (期望24) %s" % (n, "OK" if n == 24 else "FAIL"))
    rel2 = "金水谣数据/predictions.json"; s2 = os.path.join(live, rel2)
    for i in range(10):
        open(s2, "w", encoding="utf-8").write("P%d" % i); bm.snapshot(rel2, "daily")
    bm._prune("daily")
    d2 = os.path.join(replica, "daily", db._sanitize(rel2))
    n2 = len([f for f in os.listdir(d2) if f.endswith(".bak")])
    log("  10次快照后 _prune('daily') 保留数=%d (期望7) %s" % (n2, "OK" if n2 == 7 else "FAIL"))
    bm.build_manifest()
    man = json.load(open(bm.manifest_path, encoding="utf-8"))
    log("  manifest 快照条数=%d, 首条sha256长度=%d, size类型=%s" % (
        len(man["snapshots"]), len(man["snapshots"][0]["sha256"]),
        type(man["snapshots"][0]["size"]).__name__))
    _flush()

    # ===== 真恢复 + sha256 校验 =====
    log("===== 恢复 + sha256 校验一致 =====")
    open(src, "w", encoding="utf-8").write("ORIGINAL_V1")
    bm.snapshot(rel, "hourly"); bm.build_manifest()
    orig_sha = db._sha256_file(src)
    before = open(src, encoding="utf-8").read()
    open(src, "w", encoding="utf-8").write("TAMPERED_LIVE_BAD")
    rep = rm.restore(rel)
    after = open(src, encoding="utf-8").read()
    restored_sha = db._sha256_file(src)
    log("  篡改前 live=%r | 篡改后=TAMPERED_LIVE_BAD | 恢复后 live=%r" % (before, after))
    log("  restore ok=%s msg=%r" % (rep.ok, rep.message))
    log("  orig_sha=%s... restored_sha=%s... 一致=%s" % (orig_sha[:16], restored_sha[:16], orig_sha == restored_sha))
    log("  内容还原正确=%s, ok=True=%s" % (after == "ORIGINAL_V1", rep.ok is True))
    _flush()

    # ===== 损坏备份 → ok=False + [G]告警 =====
    log("===== 损坏备份 → ok=False + [G]告警（不抛异常）=====")
    open(src, "w", encoding="utf-8").write("FRESH_V2")
    bm.snapshot(rel, "hourly"); bm.build_manifest()
    pts = rm.list_points(rel)
    sf = pts[0]["snapshot_path"]
    with open(sf, "w", encoding="utf-8") as f:
        f.write("CORRUPTED_SNAPSHOT_CONTENT")
    rep2 = rm.restore(rel)
    log("  损坏恢复 ok=%s msg=%r (期望 False, 含'校验失败')" % (rep2.ok, rep2.message))
    alert1 = open(ALERT, encoding="utf-8").read() if os.path.exists(ALERT) else ""
    log("  [G]告警日志总行数=%d (恢复/损坏均触发告警，未抛异常)" % alert1.count("\n"))
    _flush()

    # ===== 写租约互斥 =====
    log("===== 写租约互斥（两 holder 串行化）=====")
    lA = lh.LeaseManager(reg, holder="qaA@1", sc_module=sc)
    lB = lh.LeaseManager(reg, holder="qaB@2", sc_module=sc)
    lp = "金水谣数据/log/ai_decisions.md"
    a1 = lA.acquire_for_write(lp, "qa", wait_secs=0)
    b1 = lB.acquire_for_write(lp, "qa", wait_secs=0)
    log("  A先占锁=%s(期望True), B同时占同文件=%s(期望False)" % (a1, b1))
    lA.release()
    b2 = lB.acquire_for_write(lp, "qa", wait_secs=0)
    log("  A释放后 B占锁=%s(期望True)" % b2)
    lB.release()
    log("  释放后 claim=None=%s" % (sc._c is None))
    _flush()

    # ===== fail-safe 终验 =====
    log("===== fail-safe 终验 write_alert 不抛异常 =====")
    try:
        lr.write_alert("qa final probe"); lr.write_alert("qa final probe 2")
        log("  write_alert x2 无异常 OK")
    except Exception as e:
        log("  write_alert 抛异常 FAIL: %r" % e)
    log("===== 探针全部段落执行完毕 =====")
    _flush()

    try:
        shutil.rmtree(WS)
    except Exception:
        pass

except Exception:
    log("!!!!! 探针异常（traceback）!!!!!")
    log(traceback.format_exc())
    _flush()

finally:
    _flush()
