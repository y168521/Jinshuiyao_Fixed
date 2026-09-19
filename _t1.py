import sys, os
open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_t1.log","w").write("line1\n")
open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_t1.log","a").write("line2 before import\n")
sys.path.insert(0, r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed")
import engines.smart_brain
open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_t1.log","a").write("line3 after import\n")
open(r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\_t1.log","a").write("line4 DONE\n")
