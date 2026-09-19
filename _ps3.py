import sys, os, time
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
print("BEFORE_IMPORT", flush=True)
from engines.smart_brain import SmartBrain
from engines.prediction_service import PredictionService
print("IMPORTED", flush=True)
t0=time.time()
svc = PredictionService(brain=SmartBrain(), on_log=lambda m, level="INFO": None)
print("CONSTRUCTED %.1fs" % (time.time()-t0), flush=True)
t1=time.time()
r = svc.generate("福彩3D")
print("GENERATED %.1fs success=%s" % (time.time()-t1, r.get("success")), flush=True)
