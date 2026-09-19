import sys, os, traceback, time
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
print("WRAP START", flush=True)
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("route_probe", r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\route_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print("MODULE LOADED, calling run_probe()", flush=True)
    t0=time.time()
    p = mod.run_probe()
    print("run_probe done in %.1fs" % (time.time()-t0), flush=True)
    import json
    print("SUMMARY:", json.dumps(p["summary"], ensure_ascii=False), flush=True)
    for ch in p["chains"]:
        print("[%s] %s %s verdict=%s blocks_at=%s" % ("OK" if ch["verdict"]=="ok" else "FAIL", ch["id"], ch["name"], ch["verdict"], ch["blocks_at"]), flush=True)
        for n in ch["nodes"]:
            print("    %s %s %s | %s" % (n["status"], n["id"], n["name"], (n.get("detail") or "")[:80]), flush=True)
except BaseException as e:
    print("EXCEPTION:", type(e).__name__, e, flush=True)
    traceback.print_exc()
