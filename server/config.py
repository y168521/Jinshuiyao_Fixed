# -*- coding: utf-8 -*-
"""金水谣系统 - 服务器配置与共享状态

集中管理服务器常量（端口、路径、版本号等）与跨模块共享对象（线程池、锁等）。
支持环境变量覆盖，为云端部署做准备：
  JINSHUIYAO_PORT      — 服务端口（默认 18888）
  JINSHUIYAO_BASE_DIR  — 项目根目录（默认自动检测）
  JINSHUIYAO_ROOT_DIR  — 模型根目录（默认 BASE_DIR 的上级）
  JINSHUIYAO_HEADLESS  — 设为 1/true 时禁用自动打开浏览器（云端/无桌面环境）
"""
import os
import sys
import shutil
import platform
import threading
import concurrent.futures

# 服务器版本号：每次发布重要修复时递增；前端靠 /health 的 version 字段判断后端是否为最新版
SERVER_VERSION = "2026.07.19.2"

# ===== 平台检测（云端迁移基础）=====
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
# 无桌面环境判定：显式设置 headless 或 Linux 无 DISPLAY
IS_HEADLESS = os.environ.get("JINSHUIYAO_HEADLESS", "").lower() in ("1", "true", "yes") or \
              (IS_LINUX and not os.environ.get("DISPLAY"))

PORT = int(os.environ.get("JINSHUIYAO_PORT", "18888"))

# POST 请求体上限（字节），防止超大 body 拖垮服务器或耗尽内存
MAX_BODY = 1_000_000

# ===== 外部调用并发限制 + 接口级总超时熔断 =====
# 限制同时进行的外部调用（AI 对话 / 视频提取）数量，避免线程暴涨耗尽资源；
# 单次处理超过下方总超时即熔断返回 504（工作线程随后会因底层 timeout 自行结束），
# 这样即使某个底层库未遵守 timeout，HTTP 连接也不会永久挂起。
_EXTERNAL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="jinshuiyao-ext")
# 各外部接口总超时（秒）；正常情况底层已有 15~60s timeout，不会触发熔断
_EXT_TIMEOUT = {
    "chat": 60,        # AI 对话（底层 30s）
    "ask": 60,         # 智能代码助手（底层 30s）
    "video": 150,      # 视频提取+归档（可能较慢）
    "extract": 150,    # URL 提取+归档
}

# 使用相对路径，不再硬编码用户目录；支持环境变量覆盖（云端部署用）
BASE_DIR = os.environ.get("JINSHUIYAO_BASE_DIR") or \
           os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.environ.get("JINSHUIYAO_ROOT_DIR") or os.path.dirname(BASE_DIR)
HTML_DIR = os.path.join(BASE_DIR, 'jinshuiyao-guide')
NAV_FILE = os.path.join(ROOT_DIR, '金水谣助手门户.html')
CONTROL_CENTER = os.path.join(HTML_DIR, 'control-center.html')
LOG_FILE = os.path.join(BASE_DIR, 'jinshuiyao-guide', 'server.log')

# 智能代码助手（需求 1~7）模块目录加入导入路径，便于统一调度
SMART_DIR = os.path.join(BASE_DIR, 'smart-coder')
DEEPSEEK_DIR = os.path.join(BASE_DIR, 'AI代码助手(DeepSeek备用)')
for _p in (SMART_DIR, DEEPSEEK_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# 跨设备任务同步模块目录加入导入路径（基于坚果云共享目录做传输）
SYNC_DIR = os.path.join(BASE_DIR, 'sync')
if os.path.isdir(SYNC_DIR) and SYNC_DIR not in sys.path:
    sys.path.insert(0, SYNC_DIR)

# ---------------------------------------------------------------------------
# 预测记录配置
# ---------------------------------------------------------------------------
PREDICTION_DIR = os.path.join(BASE_DIR, 'predictions')
PREDICTION_FILE = os.path.join(PREDICTION_DIR, 'predictions.json')

_PRED_DOMAIN_KEYWORDS = {
    'lottery': ['双色球', '彩票', '大乐透', '福彩', '体彩', '3d', '排列三', '排列5', '时时彩', '七星彩'],
    'stock': ['股票', '基金', '个股', '大盘', 'a股', '上证', '深证', '走势', '行情', '涨停', '跌停', '沪深'],
    'football': ['足彩', '足球', '竞彩', '赔率', '比分', '联赛', '世界杯', '欧冠', '英超'],
    'music': ['音乐', '歌曲', '歌词'],
    'video': ['视频', '抖音', 'b站', '哔哩', '快手', '影视', '电影'],
}
_DOMAIN_LABELS = {'lottery': '彩票', 'stock': '股票', 'football': '足球',
                  'music': '音乐', 'video': '视频', 'other': '其他'}

# 并发写锁：服务器线程化后，多个 AI 对话可能同时 record_prediction，需串行化避免覆盖。
_PRED_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Python 解释器自动查找
# 优先使用 config/paths.json 集中化配置，回退到内置候选列表。
# 查找优先级：venv_314 → 系统Python 3.14 → Python 3.8 → py启动器 → 当前解释器
# ---------------------------------------------------------------------------
try:
    from config.path_resolver import get_python_candidates as _get_candidates
    _CANDIDATE_PYTHONS = _get_candidates()
except Exception:
    _CANDIDATE_PYTHONS = []

if not _CANDIDATE_PYTHONS:
    # 回退：内置候选列表（按优先级排序）
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _localapp = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    _CANDIDATE_PYTHONS = [
        os.path.join(_localapp, 'Jinshuiyao', 'venv', 'Scripts', 'python.exe'),
        os.path.join(os.path.dirname(os.path.dirname(_BASE)), 'venv_314', 'Scripts', 'python.exe'),
        r'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe',
        r'C:\Users\Administrator\AppData\Local\Programs\Python\Python38\python.exe',
        r'C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe',
    ]

PYTHON_EXE = sys.executable


def _find_python():
    """按优先级查找可用的系统Python（用于启动各子程序）"""
    for cand in _CANDIDATE_PYTHONS:
        if os.path.isfile(cand):
            return cand, cand
    # 尝试py启动器
    _py = shutil.which('py')
    if _py:
        return _py, _py
    # 尝试python命令
    _py2 = shutil.which('python')
    if _py2:
        return _py2, _py2
    # 最终回退到当前解释器
    return sys.executable, sys.executable


SYSTEM_PYTHON, SYSTEM_PYTHONW = _find_python()


# ===== 跨平台安全打开（云端迁移：无桌面环境自动跳过）=====

def safe_open_browser(url):
    """安全打开浏览器。无桌面环境（headless/云端）时静默跳过。

    Returns:
        bool: 是否成功调用了打开操作
    """
    if IS_HEADLESS:
        return False
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        return False


def safe_open_local(path):
    """安全打开本地文件/文件夹（Windows 用 os.startfile，其他平台用 xdg-open/open）。

    无桌面环境时静默跳过。

    Returns:
        bool: 是否成功调用了打开操作
    """
    if IS_HEADLESS:
        return False
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606 — Windows 专属
        elif IS_MACOS:
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False
