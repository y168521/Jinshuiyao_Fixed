import sys, os, traceback, time
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
import importlib.util
spec = importlib.util.spec_from_file_location("rp", r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\route_probe.py")
rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
for b in [n for n in dir(rp) if n.startswith("_build_")]:
    ch = getattr(rp, b)()
    for chain in ch:
        print("== CHAIN %s %s mode=%s ==" % (chain.get("id"), chain.get("name"), chain.get("mode")), flush=True)
        for node in chain.get("nodes", []):
            t0=time.time()
            try:
                ok, detail = node["probe"]()
                print("   NODE %s %s -> %s (%.2fs) %s" % (node["id"], node["name"], ok, time.time()-t0, str(detail)[:100]), flush=True)
            except BaseException as e:
                print("   NODE %s %s DIED: %s %s (%.2fs)" % (node["id"], node["name"], type(e).__name__, e, time.time()-t0), flush=True)
                traceback.print_exc()
