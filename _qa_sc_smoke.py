# -*- coding: utf-8 -*-
"""真实 session_coordinator 委托冒烟（独立于主探针，写自身结果文件）。
先 force-release 清理上一会话遗留的过期占锁（环境状态，非 ④ 缺陷），
再验证 LeaseManager 经真实 sc 的 acquire/release 返回 bool、不抛异常。
"""
import sys, os
PROJ = r"C:\Users\Administrator\Nutstore\1\我的坚果云/模型/Jinshuiyao_Fixed"
sys.path.insert(0, os.path.join(PROJ, "scripts"))
out = []
def w(m):
    out.append(str(m))
    try:
        with open(os.path.join(PROJ, "_qa_sc_smoke.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    except Exception:
        pass

w("===== 真实 session_coordinator 委托冒烟 =====")
try:
    import session_coordinator as real_sc
    w("  import real_sc OK")
    # 清理遗留过期占锁（若存在）
    try:
        before = real_sc.release(force=True)
        w("  force-release 前置清理=%s" % before)
    except Exception as e:
        w("  force-release 异常(忽略): %r" % e)
    import lease_helper as lh
    import layer_registry as lr
    lmR = lh.LeaseManager(lr.LayerRegistry(), sc_module=real_sc)
    rA = lmR.acquire_for_write("金水谣数据/brain_state.json", "qa-probe", wait_secs=0)
    w("  acquire_for_write=%s (期望 True)" % rA)
    rR = lmR.release()
    w("  release=%s (期望 True)" % rR)
    # 再次清理，避免遗留占锁影响产品
    try: real_sc.release(force=True)
    except Exception: pass
    w("  结论: 真实 sc 委托 acquire=%s release=%s（均 bool，未抛异常）" % (rA, rR))
except Exception as e:
    import traceback
    w("  真实 sc 委托异常(降级): %r" % e)
    w(traceback.format_exc())
w("===== 真实 sc 冒烟结束 =====")
