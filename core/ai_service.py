# -*- coding: utf-8 -*-
"""金水谣引擎 - 统一AI服务层

所有子系统（彩票/股票/足彩/基金/音乐）共用此模块调用LLM。
不再各自硬编码API地址和密钥读取逻辑。

支持的AI供应商：
  - DeepSeek（默认，已对接）
  - OpenAI兼容接口（可扩展）

运行模式：
  - online: 在线模式，调用DeepSeek API（需要网络和API Key）
  - offline: 本地模式，不调用API，纯本地算法运行（无需网络）

使用方式：
    from core.ai_service import AIService, get_mode, set_mode
    # 查看当前模式
    print(get_mode())  # 'online' 或 'offline'
    # 切换模式
    set_mode('offline')
    # 使用AI服务（根据模式自动决定是否调用API）
    ai = AIService()
    result = ai.chat("你是分析师", "分析这段数据...")
"""

import json
import os
import time
import logging
import re
import threading
from typing import Optional, Dict, Generator, List
from datetime import datetime

from core.conversation_log import log_conversation as _log_conv
from utils.safe_json import safe_write_json, safe_load_json

try:
    import requests
except ImportError:
    requests = None  # fallback: 使用 urllib（旧版兼容）

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 运行模式管理（online/offline）
# ---------------------------------------------------------------------------

_MODE_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai_mode.json"
)

# 密钥安全：明文密钥从「云同步目录」迁到用户主目录下的非同步目录，避免被同步到云端/其他设备。
# 读取顺序：新位置(优先) → 旧位置(兼容回退) → 环境变量。
_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

# Token用量持久化文件路径（项目根目录/金水谣数据/log/token_usage.json）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN_USAGE_FILE = os.path.join(_PROJECT_ROOT, "金水谣数据", "log", "token_usage.json")


def _resolve_deepseek_key_file():
    """返回 deepseek 密钥文件路径（仅安全目录 ~/.jinshuiyao-secrets/）。

    安全铁律（JS-20260724）：密钥只允许放安全目录，禁止回退到项目根/CWD
    （项目位于坚果云同步树内，明文密钥会被同步外泄）。
    """
    return os.path.join(_SECRETS_DIR, "deepseek_key.txt")


def get_api_key(key_file: str = "") -> str:
    """统一的API密钥读取入口（全项目唯一真相源）。

    读取顺序：指定文件 → 密钥目录(~/.jinshuiyao-secrets/) → 环境变量 DEEPSEEK_API_KEY
    （项目根目录/CWD 明文回退已于 JS-20260724 移除：同步盘外泄风险）

    Args:
        key_file: 可选，指定密钥文件路径

    Returns:
        str: API密钥字符串，未找到则返回空字符串
    """
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        except Exception:
            pass

    # 安全铁律（JS-20260724）：仅安全目录，禁止项目根/CWD 明文回退（同步盘外泄风险）
    default_paths = [
        os.path.join(_SECRETS_DIR, "deepseek_key.txt"),
    ]
    for path in default_paths:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    key = f.read().strip()
                if key:
                    return key
            except Exception:
                pass

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    return ""


def get_mode() -> str:
    """获取当前AI运行模式

    Returns:
        str: 'online' 或 'offline'
    """
    try:
        if os.path.isfile(_MODE_CONFIG_PATH):
            with open(_MODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("mode", "online")
    except Exception as e:
        logger.debug("[ai_service] 读取模式配置失败: %s", e)
    return "online"


def set_mode(mode: str) -> bool:
    """设置AI运行模式

    Args:
        mode: 'online' 或 'offline'

    Returns:
        bool: 是否成功
    """
    if mode not in ("online", "offline"):
        logger.warning("[ai_service] 不支持的模式: %s", mode)
        return False

    try:
        # 读取现有配置
        cfg = {"mode": "online", "description": "", "modes": {}, "last_updated": ""}
        if os.path.isfile(_MODE_CONFIG_PATH):
            with open(_MODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

        # 更新模式
        cfg["mode"] = mode
        cfg["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 确保目录存在
        os.makedirs(os.path.dirname(_MODE_CONFIG_PATH), exist_ok=True)

        # 写入
        with open(_MODE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        logger.info("[ai_service] 模式已切换为: %s", mode)

        # 更新全局实例（如果存在）
        global _instance
        if _instance is not None:
            _instance._mode = mode

        return True
    except Exception as e:
        logger.error("[ai_service] 切换模式失败: %s", e)
        return False


def get_mode_info() -> Dict:
    """获取模式详细信息

    Returns:
        dict: 包含当前模式、模式列表、描述等
    """
    default_info = {
        "mode": "online",
        "description": "AI服务运行模式",
        "modes": {
            "online": {"name": "在线模式", "description": "调用DeepSeek API"},
            "offline": {"name": "本地模式", "description": "不调用API，纯本地运行"}
        }
    }
    try:
        if os.path.isfile(_MODE_CONFIG_PATH):
            with open(_MODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {
                    "mode": cfg.get("mode", "online"),
                    "description": cfg.get("description", ""),
                    "modes": cfg.get("modes", default_info["modes"]),
                    "last_updated": cfg.get("last_updated", "")
                }
    except Exception:
        pass
    return default_info


def _check_network(timeout: int = 5) -> bool:
    """检测网络是否可用

    Args:
        timeout: 超时时间（秒）

    Returns:
        bool: 网络是否可用
    """
    try:
        import urllib.request
        # 尝试连接DeepSeek API（也可连接百度等常用网站）
        test_urls = [
            "https://api.deepseek.com",
            "https://www.baidu.com",
            "https://www.google.com",
        ]
        for url in test_urls:
            try:
                req = urllib.request.Request(url, method="HEAD")
                with urllib.request.urlopen(req, timeout=timeout):
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _check_api_key() -> bool:
    """检测是否有可用的API Key（复用统一入口 get_api_key）"""
    return bool(get_api_key())


def auto_detect_mode(force: bool = False) -> str:
    """自动检测网络和API Key，切换到合适的模式

    检测逻辑：
      1. 如果有网络且有API Key → 在线模式
      2. 如果无网络或无API Key → 本地模式

    Args:
        force: 是否强制检测（即使配置了手动模式）

    Returns:
        str: 检测后的模式（'online' 或 'offline'）
    """
    # 读取配置，检查是否启用自动检测
    auto_enable = True
    try:
        if os.path.isfile(_MODE_CONFIG_PATH):
            with open(_MODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                auto_enable = cfg.get("auto_switch_on_error", True)
                # 如果用户手动设置了模式且没有强制检测，尊重用户选择
                if not force and cfg.get("mode") and cfg.get("last_updated"):
                    # 检查最后更新时间，如果是最近更新的，认为是用户手动设置的
                    # 这里简化处理：如果配置文件存在且有mode，且没有force，就不自动切换
                    current_mode = cfg.get("mode", "online")
                    logger.info("[ai_service] 检测到用户手动设置的模式: %s，跳过自动检测", current_mode)
                    return current_mode
    except Exception as e:
        logger.debug("[ai_service] 读取配置失败，使用默认自动检测: %s", e)

    # 检测网络
    has_network = _check_network()
    logger.info("[ai_service] 网络检测: %s", "可用" if has_network else "不可用")

    # 检测API Key
    has_api_key = _check_api_key()
    # 仅记录 API Key“是否存在”，从不打印真实密钥内容（semgrep logger-credential-leak 误报）
    logger.info("[ai_service] API Key检测: %s", "存在" if has_api_key else "不存在")  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure

    # 决定模式
    if has_network and has_api_key:
        target_mode = "online"
    else:
        target_mode = "offline"

    # 切换模式
    if set_mode(target_mode):
        logger.info("[ai_service] 自动检测完成，已切换到: %s", target_mode)
    else:
        logger.warning("[ai_service] 自动检测完成，但切换模式失败")

    return target_mode


# ---------------------------------------------------------------------------
# AI供应商配置
# ---------------------------------------------------------------------------

PROVIDERS = {
    "deepseek": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "max_tokens": 2000,
        "temperature": 0.7,
        "provider_type": "remote",  # 远程API
    },
    "deepseek-reasoner": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-reasoner",
        "max_tokens": 4000,
        "temperature": 0.3,
        "provider_type": "remote",
    },
    "dashscope": {
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        # 默认模型 qwen3.6-flash：百炼免费额度可用（qwen-plus 免费额度易耗尽）
        "model": "qwen3.6-flash",
        "max_tokens": 2000,
        "temperature": 0.7,
        "provider_type": "remote",
    },
    "zhipu": {
        "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4.5-air",
        "max_tokens": 2000,
        "temperature": 0.7,
        "provider_type": "remote",
    },
    "moonshot": {
        "api_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "kimi-k2.6",
        "max_tokens": 2000,
        "temperature": 0.7,
        "provider_type": "remote",
    },
    "ollama": {
        "api_url": "http://localhost:11434/v1/chat/completions",
        "model": "llama3.2",
        "max_tokens": 2048,
        "temperature": 0.7,
        "provider_type": "local",  # 本地模型
    },
}

# 供应商 → 密钥文件名（统一密钥槽位，与 server/handlers/keys.py 一致）
PROVIDER_KEY_FILES = {
    "deepseek": "deepseek_key.txt",
    "deepseek-reasoner": "deepseek_key.txt",
    "dashscope": "dashscope_key.txt",
    "zhipu": "zhipu_key.txt",
    "moonshot": "moonshot_key.txt",
    "ollama": "",  # 本地模型无需密钥
}

# 模型 fallback 链：当首选模型失败时按序尝试备选
FALLBACK_CHAIN = [
    "deepseek",
    "deepseek-reasoner",
    "zhipu",
    "dashscope",
    "ollama",
]

# 流式响应 SSE 解析正则
_SSE_DATA_RE = re.compile(r'data:\s*(.*)')

# 子系统预设Prompt模板（各子系统可自定义，但提供默认值）
_SUBSYSTEM_PROMPTS = {
    "football": (
        "你是一位专业的足球比赛分析师，精通各国联赛和杯赛。"
        "请根据提供的比赛信息和赔率数据，给出简洁专业的分析。"
        "要求：\n"
        "1. 先给出核心观点（谁更有优势，关键因素是什么）\n"
        "2. 简要分析双方实力对比和战术特点\n"
        "3. 给出胜平负建议和让球倾向\n"
        "4. 指出可能的冷门风险\n"
        "5. 推荐2-3个最可能的比分\n"
        "6. 全文控制在300字以内，用中文\n"
        "不要输出废话，直接给干货分析。"
    ),
    "lottery": (
        "你是一位资深的彩票数据分析专家，精通概率统计和数理模型。"
        "请根据提供的历史开奖数据和统计指标，给出简洁的分析。"
        "要求中文回答，控制在200字以内。"
    ),
    "stock": (
        "你是一位专业的A股市场分析师，精通技术分析和基本面分析。"
        "请根据提供的股票/指数数据和技术指标，给出简洁的分析。"
        "要求：中文回答，给出趋势判断和操作建议，控制在200字以内。"
    ),
    "fund": (
        "你是一位专业的基金分析师，精通基金筛选、定投策略和资产配置。"
        "请根据提供的基金数据，给出简洁的分析和配置建议。"
        "要求：中文回答，控制在200字以内。"
    ),
    "music": (
        "你是一位AI音乐创作助手，精通音乐理论和音频处理。"
        "请根据用户的需求，给出专业的音乐创作建议。"
        "要求：中文回答。"
    ),
    "general": (
        "你是金水谣万物引擎的AI助手，请根据用户需求给出专业、简洁的回答。"
        "要求：中文回答。"
    ),
}


class AIService:
    """统一AI服务 — 所有子系统共用入口

    特性：
      - 支持双模式切换（online/offline）
      - 自动读取 deepseek_key.txt 或环境变量 DEEPSEEK_API_KEY
      - 内置频率限制（防止API过载）
      - 内置熔断保护（连续失败自动暂停）
      - 子系统预设Prompt（也可自定义）
      - 支持 requests 连接池（自动重试）
      - 支持流式响应（SSE）
      - 模型 fallback 链（自动切换备选模型）
    """

    def __init__(self, provider: str = "deepseek", api_key: str = "",
                 key_file: str = ""):
        """初始化AI服务

        Args:
            provider: 供应商名称，默认 deepseek
            api_key: API密钥，为空则自动从文件/环境变量读取
            key_file: 密钥文件路径，为空则自动查找
        """
        self.provider = provider
        self._config = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        self._timeout = 30
        self._stream_timeout = 60
        self._last_call_time = 0
        self._min_interval = 2  # 最小调用间隔（秒）
        self._fail_count = 0
        self._fail_threshold = 5  # 连续失败N次后熔断
        self._breaker_until = 0  # 熔断恢复时间戳
        self._total_calls = 0
        self._total_success = 0
        self._retry_count = 2  # 失败重试次数

        # 运行模式
        self._mode = get_mode()

        # 共享状态锁（JS-20260723-37）：_fail_count 读改写、provider 切换须串行，
        # 防止多线程 chat() 并发导致计数丢失 / 切到错误模型。
        self._state_lock = threading.Lock()

        # 读取API Key
        self.api_key = api_key or self._auto_read_key(key_file)

        # Token用量追踪
        self._token_usage = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "calls_with_usage": 0,
            "last_usage": None,
            "daily": {},
        }
        # 持久化写入节流控制（每10次调用或每5分钟写一次）
        self._usage_write_count = 0
        self._usage_last_write_time = 0.0
        # 从 token_usage.json 恢复历史用量（重启不归零）
        self._restore_usage_from_file()

        # 初始化 requests session（连接池）
        self._session = None
        self._init_session()

        # 自动检测Ollama是否可用
        self._ollama_available = False
        self._detect_ollama()

    def _init_session(self):
        """初始化 requests session（连接池）"""
        if requests is None:
            return
        try:
            self._session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=5,
                pool_maxsize=10,
                max_retries=2
            )
            self._session.mount('https://', adapter)
            self._session.mount('http://', adapter)
            self._session.headers.update({
                "Content-Type": "application/json",
            })
        except Exception as e:
            logger.debug("[ai_service] session初始化失败，使用urllib降级: %s", e)
            self._session = None

    def _auto_read_key(self, key_file: str = "") -> str:
        """自动读取API Key（复用统一入口 get_api_key）"""
        key = get_api_key(key_file)
        if key:
            logger.info("[ai_service] API Key读取成功")
        else:
            logger.warning("[ai_service] 未找到API Key，AI功能将不可用")
        return key

    def _track_usage(self, api_response: Dict):
        """从API响应中追踪Token用量"""
        usage = api_response.get("usage")
        if usage:
            prompt_tk = usage.get("prompt_tokens", 0)
            completion_tk = usage.get("completion_tokens", 0)
            total_tk = usage.get("total_tokens", 0)
            self._token_usage["total_prompt_tokens"] += prompt_tk
            self._token_usage["total_completion_tokens"] += completion_tk
            self._token_usage["total_tokens"] += total_tk
            self._token_usage["calls_with_usage"] += 1
            self._token_usage["last_usage"] = {
                "prompt": prompt_tk,
                "completion": completion_tk,
                "total": total_tk,
            }
            # 按日统计
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                daily = self._token_usage.setdefault("daily", {})
                day_entry = daily.setdefault(today, {"tokens": 0, "calls": 0})
                day_entry["tokens"] += total_tk
                day_entry["calls"] += 1
            except Exception as e:
                logger.debug("[ai_service] 日用量统计异常: %s", e)
            # 节流持久化：每10次调用或每5分钟写一次
            self._usage_write_count += 1
            now_ts = time.time()
            if (self._usage_write_count >= 10
                    or (now_ts - self._usage_last_write_time) >= 300):
                self._persist_usage_to_file()
                self._usage_write_count = 0
                self._usage_last_write_time = now_ts

    def _restore_usage_from_file(self):
        """启动时从 token_usage.json 恢复历史Token用量"""
        try:
            data = safe_load_json(_TOKEN_USAGE_FILE, default=None,
                                  verify_checksum_flag=False)
            if data and isinstance(data, dict):
                self._token_usage["total_tokens"] = data.get("total_tokens", 0)
                self._token_usage["total_prompt_tokens"] = data.get("total_prompt_tokens", 0)
                self._token_usage["total_completion_tokens"] = data.get("total_completion_tokens", 0)
                self._token_usage["calls_with_usage"] = data.get("total_calls", 0)
                self._token_usage["daily"] = data.get("daily", {})
                logger.info("[ai_service] 从持久化文件恢复Token用量: total_tokens=%d, calls=%d",
                            self._token_usage["total_tokens"],
                            self._token_usage["calls_with_usage"])
        except Exception as e:
            # 仅打印异常对象 e（类型/消息），不含任何密钥/Token 明文（semgrep logger-credential-leak 误报）
            logger.warning("[ai_service] 恢复Token用量失败（文件不存在或损坏）: %s", e)  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure

    def _persist_usage_to_file(self):
        """将累计Token用量写入 token_usage.json（节流调用，非每次触发）"""
        try:
            payload = {
                "total_tokens": self._token_usage["total_tokens"],
                "total_prompt_tokens": self._token_usage["total_prompt_tokens"],
                "total_completion_tokens": self._token_usage["total_completion_tokens"],
                "total_calls": self._token_usage["calls_with_usage"],
                "last_updated": datetime.now().isoformat(timespec="seconds"),
                "daily": self._token_usage.get("daily", {}),
            }
            safe_write_json(_TOKEN_USAGE_FILE, payload, embed_checksum=False)
            logger.debug("[ai_service] Token用量已持久化: total_tokens=%d",
                         payload["total_tokens"])
        except Exception as e:
            # 仅打印异常对象 e，不含 Token 明文（semgrep logger-credential-leak 误报）
            logger.warning("[ai_service] Token用量持久化写入失败: %s", e)  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure

    def _detect_ollama(self):
        """检测本地Ollama服务是否可用（先socket探活，未安装时瞬间跳过）"""
        import socket
        # 第一步：TCP探活（0.3秒超时，无重试），端口不通直接返回
        try:
            sock = socket.create_connection(("127.0.0.1", 11434), timeout=0.3)
            sock.close()
        except (OSError, socket.timeout):
            self._ollama_available = False
            return
        # 第二步：端口通了才发HTTP请求获取模型列表
        if self._session is None:
            return
        try:
            resp = self._session.get(
                "http://localhost:11434/api/tags",
                timeout=2
            )
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    available = [m["name"] for m in models[:5]]
                    self._ollama_available = True
                    logger.info("[ai_service] 检测到Ollama: %s", available)
                    # 自动更新Ollama model配置为实际可用模型
                    if "llama3.2" not in available:
                        # 使用第一个可用模型
                        first_model = available[0].split(":")[0]
                        PROVIDERS["ollama"]["model"] = first_model
                        logger.info("[ai_service] Ollama默认模型设为: %s", first_model)
        except Exception:
            self._ollama_available = False

    @property
    def mode(self) -> str:
        """当前运行模式"""
        return self._mode

    @property
    def is_online(self) -> bool:
        """是否为在线模式"""
        return self._mode == "online"

    @property
    def is_available(self) -> bool:
        """AI服务是否可用"""
        # 本地模式：检查Ollama是否可用作为替代
        if self._mode == "offline":
            return self._ollama_available
        return bool(self.api_key) and not self._is_breaker_open()

    @property
    def stats(self) -> Dict:
        """调用统计"""
        return {
            "provider": self.provider,
            "model": self._config["model"],
            "mode": self._mode,
            "available": self.is_available,
            "total_calls": self._total_calls,
            "total_success": self._total_success,
            "fail_count": self._fail_count,
            "is_breaker_open": self._is_breaker_open(),
            "ollama_detected": self._ollama_available,
            "token_usage": self._token_usage,
        }

    def _is_breaker_open(self) -> bool:
        """熔断器是否打开"""
        return time.time() < self._breaker_until

    def _record_success(self):
        with self._state_lock:
            self._total_calls += 1
            self._total_success += 1
            self._fail_count = 0

    def _record_failure(self):
        with self._state_lock:
            self._total_calls += 1
            self._fail_count += 1
            if self._fail_count >= self._fail_threshold:
                # 熔断60秒
                self._breaker_until = time.time() + 60
                logger.warning(
                    "[ai_service] 连续失败%d次，熔断器打开60秒",
                    self._fail_count
                )

    def _ensure_rate_limit(self):
        """频率限制"""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _build_payload(self, system_prompt: str, user_prompt: str,
                       temperature: float = None, max_tokens: int = None,
                       stream: bool = False) -> Dict:
        """构建API请求体"""
        config = self._config
        return {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else config["temperature"],
            "max_tokens": max_tokens if max_tokens is not None else config["max_tokens"],
            "stream": stream,
        }

    def _call_api(self, payload: Dict) -> Optional[Dict]:
        """调用API（requests优先，urllib降级）

        Returns:
            API响应JSON，失败返回None
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        api_url = self._config["api_url"]

        # 方法1: requests + 连接池
        if self._session is not None:
            try:
                resp = self._session.post(
                    api_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._track_usage(data)
                    return data
                else:
                    logger.warning("[ai_service] API错误 %d: %s",
                                  resp.status_code, resp.text[:200])
                    return None
            except requests.exceptions.Timeout:
                logger.warning("[ai_service] 请求超时 (%ss)", self._timeout)
                return None
            except requests.exceptions.ConnectionError as e:
                logger.warning("[ai_service] 连接失败: %s", e)
                return None
            except Exception as e:
                logger.warning("[ai_service] 请求异常: %s", e)
                return None

        # 方法2: urllib 降级
        try:
            import urllib.request
            import urllib.error
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                api_url, data=data,
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning("[ai_service] urllib HTTP错误: %d", e.code)
            return None
        except Exception as e:
            logger.warning("[ai_service] urllib异常: %s", e)
            return None

    def _call_api_stream(self, payload: Dict) -> Generator[str, None, None]:
        """流式调用API（SSE解析）

        Yields:
            每次返回一个文本块（增量输出）
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        api_url = self._config["api_url"]

        if self._session is None:
            logger.warning("[ai_service] 流式响应需要requests库支持")
            yield ""
            return

        try:
            with self._session.post(
                api_url, json=payload, headers=headers,
                timeout=self._stream_timeout, stream=True,
            ) as resp:
                if resp.status_code != 200:
                    logger.warning("[ai_service] 流式API错误 %d", resp.status_code)
                    yield ""
                    return

                for line in resp.iter_lines(decode_unicode=True):
                    if not line or line.strip() == "":
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = (chunk.get("choices", [{}])[0]
                                     .get("delta", {}).get("content", ""))
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning("[ai_service] 流式请求异常: %s", e)
            yield ""

    def chat(self, system_prompt: str, user_prompt: str,
             temperature: float = None, max_tokens: int = None,
             _fallback_depth: int = 0, free_first: bool = None) -> str:
        """通用AI对话

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户输入
            temperature: 温度参数，None使用供应商默认值
            max_tokens: 最大token数，None使用供应商默认值
            _fallback_depth: 内部使用，fallback递归深度
            free_first: 免费优先（W63补38）。None=自动开启：硅基流动免费池可用时
                先用免费模型（GLM-4-32B 等），免费池全部失败才走本供应商(付费DeepSeek)，
                符合用户约定"能用免费就用，免费不行才付费"；False=跳过免费直走原路径。

        Returns:
            AI回复文本，失败返回空字符串
        """
        # 免费优先（W63补38）：离线模式保持本地 Ollama 优先，不混入
        if self._mode != "offline" and free_first is not False:
            try:
                from core.free_model_pool import get_free_provider_cfgs, call_ai_failover
                _cfgs = get_free_provider_cfgs()
                if _cfgs:
                    _t = temperature if temperature is not None else 0.7
                    _m = max_tokens if max_tokens is not None else 800
                    _text, _err, _used = call_ai_failover(
                        _cfgs, system_prompt, user_prompt,
                        timeout=60, max_tokens=_m, temperature=_t,
                        force_json_mode=False, allow_paid_fallback=False)
                    if _text:
                        _log_conv(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            reply=_text,
                            provider=(_used or {}).get("_provider", "siliconflow"),
                            model=(_used or {}).get("_model_id", "free"),
                            token_usage={},
                            duration_ms=0,
                            success=True,
                        )
                        return _text
            except Exception:
                pass  # 免费池异常不影响原有付费路径

        # 本地模式：尝试使用Ollama
        if self._mode == "offline":
            if self._ollama_available:
                old_provider = self.provider
                self.switch_provider("ollama")
                logger.debug("[ai_service] 离线模式，使用Ollama")
                try:
                    result = self.chat(system_prompt, user_prompt,
                                       temperature, max_tokens,
                                       _fallback_depth=len(FALLBACK_CHAIN))
                finally:
                    self.switch_provider(old_provider)
                return result
            logger.debug("[ai_service] 本地模式，跳过API调用")
            return ""

        if not self.api_key:
            logger.warning("[ai_service] API Key未配置")
            return ""

        if self._is_breaker_open():
            logger.warning("[ai_service] 熔断器打开中，跳过调用")
            return ""

        self._ensure_rate_limit()

        # 构建请求
        payload = self._build_payload(system_prompt, user_prompt,
                                      temperature, max_tokens)

        # 调用API（带计时和持久化日志）
        self._last_call_time = time.time()
        _call_start = time.time()
        for attempt in range(self._retry_count + 1):
            data = self._call_api(payload)
            if data is not None:
                try:
                    result = data["choices"][0]["message"]["content"]
                    self._record_success()
                    # 持久化对话日志
                    _duration = (time.time() - _call_start) * 1000
                    _usage = data.get("usage", {})
                    _log_conv(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        reply=result,
                        provider=self.provider,
                        model=self._config.get("model", ""),
                        token_usage={
                            "prompt": _usage.get("prompt_tokens", 0),
                            "completion": _usage.get("completion_tokens", 0),
                            "total": _usage.get("total_tokens", 0),
                        },
                        duration_ms=_duration,
                        success=True,
                    )
                    return result
                except (KeyError, IndexError) as e:
                    logger.warning("[ai_service] 响应解析失败: %s", e)
                    continue
            # 重试前等待
            if attempt < self._retry_count:
                time.sleep(1)

        # 所有重试都失败 → 记录失败日志 → 模型自适应 → 尝试 fallback 模型
        self._record_failure()
        _log_conv(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            reply="",
            provider=self.provider,
            model=self._config.get("model", ""),
            duration_ms=(time.time() - _call_start) * 1000,
            success=False,
            error_msg=f"连续{self._retry_count + 1}次调用失败",
        )

        # 模型自适应（W63补52/53）：dashscope 等长尾平台额度耗尽(403)时
        # 自动探测账号下可用的免费模型并切换重试，无需人工手动切换
        _ssp, _usp = system_prompt, user_prompt
        if self.provider in ("dashscope",) and self.api_key:
            try:
                from core.adaptive_models import find_working_model
                best = find_working_model(
                    self.provider, self.api_key,
                    preferred=self._config.get("model", ""))
                if best and best != self._config.get("model", ""):
                    logger.info("[ai_service] 额度自适应: %s → %s",
                                self._config.get("model", ""), best)
                    with self._state_lock:
                        self._config["model"] = best
                    data = self._call_api(self._build_payload(
                        _ssp, _usp, temperature, max_tokens))
                    if data is not None:
                        try:
                            result = data["choices"][0]["message"]["content"]
                            self._record_success()
                            _log_conv(
                                system_prompt=_ssp, user_prompt=_usp,
                                reply=result, provider=self.provider,
                                model=best,
                                token_usage={"prompt": 0, "completion": 0,
                                             "total": 0},
                                duration_ms=(time.time() - _call_start) * 1000,
                                success=True,
                            )
                            return result
                        except (KeyError, IndexError):
                            pass
            except Exception:
                pass
        if _fallback_depth < len(FALLBACK_CHAIN):
            fallback_provider = FALLBACK_CHAIN[_fallback_depth]
            if fallback_provider != self.provider:
                # 跳过未配置密钥的远程供应商（避免在它处断链空手返回；
                # deepseek 系保留环境变量回退，不受此限制）
                _kf = PROVIDER_KEY_FILES.get(fallback_provider, "")
                if _kf and _kf != "deepseek_key.txt" and not os.path.isfile(
                        os.path.join(_SECRETS_DIR, _kf)):
                    return self.chat(
                        system_prompt, user_prompt, temperature, max_tokens,
                        _fallback_depth=_fallback_depth + 1)
                logger.info("[ai_service] 尝试fallback到: %s", fallback_provider)
                old_provider = self.provider
                self.switch_provider(fallback_provider)
                try:
                    result = self.chat(system_prompt, user_prompt,
                                       temperature, max_tokens,
                                       _fallback_depth=_fallback_depth + 1)
                finally:
                    # 恢复原供应商
                    self.switch_provider(old_provider)
                return result

        return ""

    def chat_stream(self, system_prompt: str, user_prompt: str,
                    temperature: float = None, max_tokens: int = None
                    ) -> Generator[str, None, None]:
        """流式AI对话（SSE）

        使用方式：
            for chunk in ai.chat_stream("prompt", "问话"):
                print(chunk, end="", flush=True)

        Yields:
            文本增量块
        """
        if self._mode == "offline" or not self.api_key or self._is_breaker_open():
            yield ""
            return

        self._ensure_rate_limit()

        payload = self._build_payload(system_prompt, user_prompt,
                                      temperature, max_tokens,
                                      stream=True)
        self._last_call_time = time.time()

        collected = []
        for chunk in self._call_api_stream(payload):
            if chunk:
                collected.append(chunk)
                yield chunk
            else:
                break

        if collected:
            self._record_success()
        else:
            self._record_failure()

    def analyze(self, subsystem: str, content: str,
                extra_system: str = "", **kwargs) -> str:
        """按子系统分析的快捷方法

        Args:
            subsystem: 子系统名称 (football/lottery/stock/fund/music/general)
            content: 要分析的内容
            extra_system: 额外的系统提示词（追加到预设Prompt后面）
            **kwargs: 传递给 chat() 的参数 (temperature, max_tokens)

        Returns:
            AI分析文本
        """
        system_prompt = _SUBSYSTEM_PROMPTS.get(subsystem,
                                                _SUBSYSTEM_PROMPTS["general"])
        if extra_system:
            system_prompt = system_prompt + "\n" + extra_system
        return self.chat(system_prompt, content, **kwargs)

    def quick(self, subsystem: str, content: str) -> str:
        """快速分析（短token版，适合实时显示）"""
        return self.analyze(subsystem, content,
                            extra_system="用一句话回答，不超过50字。",
                            max_tokens=200, temperature=0.3)

    def switch_provider(self, provider: str):
        """切换AI供应商（持锁，保证 provider/_config 原子切换）

        切换时按 PROVIDER_KEY_FILES 读取对应平台的密钥文件
        （如切到 dashscope 读 dashscope_key.txt）；该平台密钥文件不存在则
        api_key 置空（视为不可用，绝不回退用别的平台密钥）。
        """
        with self._state_lock:
            if provider in PROVIDERS:
                self.provider = provider
                self._config = PROVIDERS[provider]
                key_file = PROVIDER_KEY_FILES.get(provider, "")
                if key_file:
                    _kf = os.path.join(_SECRETS_DIR, key_file)
                    if key_file == "deepseek_key.txt":
                        # deepseek 保留历史兼容回退（默认路径+环境变量）
                        self.api_key = get_api_key(_kf)
                    else:
                        # 其他平台严格绑定本平台密钥文件，缺失视为不可用
                        self.api_key = get_api_key(_kf) if os.path.isfile(_kf) else ""
                # 读取持久化的可用模型（自适应切换后的选择，如百炼额度耗尽自动替换）
                if provider == "dashscope" and "dashscope" in PROVIDERS:
                    try:
                        from core.adaptive_models import current_model
                        _m = current_model(
                            provider, self._config.get("model", ""))
                        if _m:
                            self._config["model"] = _m
                    except Exception:
                        pass
                logger.info("[ai_service] 已切换到供应商: %s", provider)
            else:
                logger.warning("[ai_service] 不支持的供应商: %s", provider)


# ---------------------------------------------------------------------------
# 全局单例（延迟初始化，线程安全）
# ---------------------------------------------------------------------------
_instance: Optional[AIService] = None
_instance_lock = threading.Lock()


def get_ai_service(force_new: bool = False) -> AIService:
    """获取全局AI服务单例（线程安全）

    Args:
        force_new: 强制创建新实例（用于重新读取API Key）

    Returns:
        AIService 实例
    """
    global _instance
    if _instance is None or force_new:
        with _instance_lock:
            # Double-check: 另一个线程可能已在等锁期间完成初始化
            if _instance is None or force_new:
                _instance = AIService()
    return _instance
