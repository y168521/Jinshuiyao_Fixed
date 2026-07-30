# -*- coding: utf-8 -*-
"""临时测试服务器：在空闲端口 18950 启动，用于验证 /workbench 路由与自动审查。"""
import sys, os
BASE = r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
sys.path.insert(0, BASE)
from server import main as server_main
server_main(port=18950)
