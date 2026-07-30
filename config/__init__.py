# -*- coding: utf-8 -*-
"""config 包初始化

解决 config.py（根模块）与 config/（目录）同名冲突：
Python 3 中包（directory + __init__.py）优先于同名 .py 模块，
因此本 __init__.py 负责：
  1. 加载根目录 config.py 的全部公共符号 → 保持 `from config import LOTTERY_RULES` 等旧导入兼容
  2. 使 config.path_resolver / config.logging_config 等子模块可正常导入
"""
import importlib.util as _ilu
import os as _os

# 加载与本包同名的根级 config.py（位于上级目录）
_root_cfg_path = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config.py"
)
if _os.path.isfile(_root_cfg_path):
    _spec = _ilu.spec_from_file_location("_root_config", _root_cfg_path)
    _mod = _ilu.module_from_spec(_spec)
    try:
        _spec.loader.exec_module(_mod)
        # 将 config.py 的全部公共符号注入本包命名空间
        for _name in dir(_mod):
            if not _name.startswith("_"):
                globals()[_name] = getattr(_mod, _name)
    except Exception:
        pass  # 加载失败时不阻塞，子模块仍可独立使用
    del _spec, _mod
del _ilu, _os, _root_cfg_path
