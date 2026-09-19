import sys, os, traceback, time, json
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
import importlib.util
spec = importlib.util.spec_from_file_location("rp", r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\route_probe.py")
rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
# find chain builders
builders = [n for n in dir(rp) if n.startswith("_build_")]
print("BUILDERS:", builders, flush=True)
for b in builders:
    try:
        fn = getattr(rp, b)
        t0=time.time()
        ch = fn()
        print("OK %s (%.1fs) id=%s name=%s nodes=%d" % (b, time.time()-t0, ch.get("id"), ch.get("name"), len(ch.get("nodes",[]))), flush=True)
    except BaseException as e:
        print("FAIL %s: %s %s" % (b, type(e).__name__, e), flush=True)
        traceback.print_exc()
