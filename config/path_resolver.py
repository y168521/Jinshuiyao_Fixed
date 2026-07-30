# -*- coding: utf-8 -*-
"""路径解析工具 - 集中管理所有可配置路径"""
import os
import json

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paths.json")

def _load_config():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def expand_env_path(path):
    """展开路径中的环境变量（%VAR% 和 $VAR 两种格式）"""
    return os.path.expandvars(os.path.expanduser(path))

def get_python_candidates():
    cfg = _load_config()
    candidates = []
    for item in cfg.get("python_candidates", []):
        if isinstance(item, dict):
            p = expand_env_path(item.get("path", ""))
        else:
            p = expand_env_path(item)
        if os.path.isfile(p):
            candidates.append(p)
    # 始终追加 PATH 搜索和当前解释器
    import shutil, sys
    found = shutil.which("python")
    if found:
        candidates.append(found)
    if sys.executable not in candidates:
        candidates.append(sys.executable)
    return candidates

def get_ffmpeg_candidates():
    cfg = _load_config()
    candidates = []
    for item in cfg.get("ffmpeg_candidates", []):
        if isinstance(item, dict):
            p = expand_env_path(item.get("path", ""))
        else:
            p = expand_env_path(item)
        candidates.append(p)
    candidates.append("ffmpeg")  # PATH fallback
    return candidates

def get_system_python():
    cfg = _load_config()
    for key in ("system_python", "system_python_fallback"):
        p = expand_env_path(cfg.get(key, ""))
        if p and os.path.isfile(p):
            return p
    return None

def get_system_pythonw():
    cfg = _load_config()
    for key in ("system_pythonw", "system_pythonw_fallback"):
        p = expand_env_path(cfg.get(key, ""))
        if p and os.path.isfile(p):
            return p
    return None
