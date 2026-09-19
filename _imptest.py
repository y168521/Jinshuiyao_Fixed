import sys, traceback
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
try:
    import models.lottery_data
    print("models.lottery_data OK")
except Exception:
    print("IMPORT FAIL models.lottery_data"); traceback.print_exc()
try:
    import engines.smart_brain
    print("engines.smart_brain OK")
except Exception:
    print("IMPORT FAIL engines.smart_brain"); traceback.print_exc()
try:
    import utils.safe_json
    print("utils.safe_json OK")
except Exception:
    print("IMPORT FAIL utils.safe_json"); traceback.print_exc()
