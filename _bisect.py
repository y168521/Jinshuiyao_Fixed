import sys, os, traceback
lg = open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_bisect.log", "w", encoding="utf-8")
def L(m):
    lg.write(str(m) + "\n"); lg.flush()
L("START")
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
os.chdir(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
L("cwd=" + os.getcwd())
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rp", r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\route_probe.py")
    rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
    L("module loaded")
    nets = rp.build_networks()
    L("networks built: %d chains" % len(nets))
    idx = 0
    for net in nets:
        for node in net["nodes"]:
            idx += 1
            L("  -> node %d: %s %s" % (idx, net["id"], node["id"]))
            try:
                ok, detail = node["probe"]()
                L("     %s %s | %s" % (ok, node["id"], str(detail)[:120]))
            except BaseException as e:
                L("     EXC %s: %s" % (type(e).__name__, e))
    L("ALL DONE")
except BaseException as e:
    L("TOP EXC %s: %s" % (type(e).__name__, e))
    lg.write(traceback.format_exc())
lg.close()
