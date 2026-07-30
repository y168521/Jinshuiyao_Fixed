# -*- coding: utf-8 -*-
"""详细诊断真实 sc 占锁：逐步记录 claim 状态。"""
import sys, os, json, time, traceback
PROJ = r"C:\Users\Administrator\Nutstore/1/我的坚果云/模型/Jinshuiyao_Fixed"
sys.path.insert(0, os.path.join(PROJ, "scripts"))
out = []
def w(m):
    out.append(str(m))
    with open(os.path.join(PROJ, "_qa_sc_diag.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

import session_coordinator as real_sc
w("REPO_ROOT = %s" % real_sc.REPO_ROOT)
w("CLAIM_PATH = %s" % real_sc.CLAIM_PATH)
w("CLAIM exists before = %s" % real_sc.CLAIM_PATH.exists())
if real_sc.CLAIM_PATH.exists():
    w("  claim before = %s" % real_sc.CLAIM_PATH.read_text(encoding="utf-8"))
r1 = real_sc.release(force=True)
w("force-release #1 -> %s" % r1)
w("CLAIM exists after release = %s" % real_sc.CLAIM_PATH.exists())

import lease_helper as lh, layer_registry as lr
lmR = lh.LeaseManager(lr.LayerRegistry(), sc_module=real_sc)
w("holder = %r" % lmR._holder)
try:
    rA = lmR.acquire_for_write("金水谣数据/brain_state.json", "qa-probe", wait_secs=0)
    w("acquire_for_write -> %s (no exception)" % rA)
except Exception as e:
    w("acquire_for_write raised: %r" % e)
    w(traceback.format_exc())
w("CLAIM exists after acquire = %s" % real_sc.CLAIM_PATH.exists())
if real_sc.CLAIM_PATH.exists():
    w("  claim after acquire = %s" % real_sc.CLAIM_PATH.read_text(encoding="utf-8"))
try:
    rR = lmR.release()
    w("release -> %s" % rR)
except Exception as e:
    w("release raised: %r" % e)
try:
    real_sc.release(force=True)
except Exception:
    pass
w("done")
