import sys, os, time
lg = open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_a3b.log", "w", encoding="utf-8")
def L(m):
    lg.write(str(m) + "\n"); lg.flush()
L("START t=0")
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
t0=time.time()
try:
    L("import SmartBrain...")
    from engines.smart_brain import SmartBrain
    L("SmartBrain imported t=%.1f" % (time.time()-t0))
    L("import PredictionService...")
    from engines.prediction_service import PredictionService
    L("PredictionService imported t=%.1f" % (time.time()-t0))
    L("construct SmartBrain()...")
    b = SmartBrain()
    L("SmartBrain constructed t=%.1f" % (time.time()-t0))
    L("construct PredictionService...")
    svc = PredictionService(brain=b, on_log=lambda m, level="INFO": None)
    L("PredictionService constructed t=%.1f" % (time.time()-t0))
    L("generate()...")
    r = svc.generate("福彩3D")
    L("generate done t=%.1f success=%s" % (time.time()-t0, r.get("success")))
except BaseException as e:
    import traceback
    L("EXC %s: %s" % (type(e).__name__, e))
    lg.write(traceback.format_exc())
lg.close()
