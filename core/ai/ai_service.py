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
    from core.ai.ai_service import AIService, get_mode, set_mode
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

from core.ai.conversation_log import log_conversation as _log_conv
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
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "ai_mode.json"
)

# 密钥安全：明文密钥从「云同步目录」迁到用户主目录下的非同步目录，避免被同步到云端/其他设备。
# 读取顺序：新位置(优先) → 旧位置(兼容回退) → 环境变量。
_SECRETS_DIR = os.path.join(os.path.expanduser("~"), ".jinshuiyao-secrets")

# Token用量持久化文件路径（项目根目录/金水谣数据/log/token_usage.json）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOKEN_USAGE_FILE = os.path.join(_PROJECT_ROOT, "金水谣数据", "log", "token_usage.json")


def _resolve_deepseek_key_file():
    """返回 deepseek 密钥文件路径（仅安全目录 ~/.jinshuiyao-secrets/）。

    安全铁律（JS-20260724）：密钥只允许放安全目录，禁止回退到项目根/CWD
    （项目位于坚果云同步树内，明文密钥会被同步外泄）。
    """
    return os.path.join(_SECRETS_DIR, "deepseek_key.txt")


def get_api_key(key_file: str = "") -> str:
    """统一的API密钥读取入口（全项目唯一真相源，内部委托 core.infra.security.get_secret）。

    读取顺序：指定文件 → 密钥目录(~/.jinshuiyao-secrets/) → 环境变量 DEEPSEEK_API_KEY
    （项目根目录/CWD 明文回退已于 JS-20260724 移除：同步盘外泄风险）

    Args:
        key_file: 可选，指定密钥文件路径

    Returns:
        str: API密钥字符串，未找到则返回空字符串
    """
    from core.infra.security import get_secret
    if key_file:
        v = get_secret(key_file)
        if v:
            return v
    # 安全铁律（JS-20260724）：仅安全目录，禁止项目根/CWD 明文回退（同步盘外泄风险）
    v = get_secret("deepseek_key.txt")
    if v:
        return v
    return os.environ.get("DEEPSEEK_API_KEY", "")


def get_mode() -> str:
    """获取当前AI运行模式

    Returns:
        str: 'online' 或 'offline'
    """
    # 刀⑥(JS-20260807-02): safe_load_json 原子读+损坏恢复，避免裸 open+json.load 半读/崩
    cfg = safe_load_json(_MODE_CONFIG_PATH, default={})
    if isinstance(cfg, dict):
        return cfg.get("mode", "online")
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
        # 读取现有配置（刀⑥: safe_load_json 原子读+损坏恢复）
        cfg = safe_load_json(_MODE_CONFIG_PATH, default={
            "mode": "online", "description": "", "modes": {}, "last_updated": "",
        })
        if not isinstance(cfg, dict):
            cfg = {"mode": "online", "description": "", "modes": {}, "last_updated": ""}

        # 更新模式
        cfg["mode"] = mode
        cfg["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 写入（刀⑥: safe_write_json 原子写+备份，含 makedirs，移除冗余 makedirs）
        if not safe_write_json(_MODE_CONFIG_PATH, cfg, backup=True):
            logger.error("[ai_service] 模式配置写入失败: %s", _MODE_CONFIG_PATH)
            return False

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
    # 刀⑥: safe_load_json 原子读+损坏恢复
    cfg = safe_load_json(_MODE_CONFIG_PATH, default={})
    if isinstance(cfg, dict):
        return {
            "mode": cfg.get("mode", "online"),
            "description": cfg.get("description", ""),
            "modes": cfg.get("modes", default_info["modes"]),
            "last_updated": cfg.get("last_updated", "")
        }
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
    except Exception as e:
        logger.debug("[ai_service] 网络探测异常: %s", e)
        return False


def _check_api_key() -> bool:
    """检测是否有可用的API Key（复用统一入口 get_api_key）"""
    return bool(get_api_key())


def auto_detect_mode(force: bool = False) -> str:
    """自动检测网络和 API Key 并切换模式（在线/本地）。force=True 时忽略用户手动设置。"""
    auto_enable = True
    try:
        if os.path.isfile(_MODE_CONFIG_PATH):
            with open(_MODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                auto_enable = cfg.get("auto_switch_on_error", True)
                if not force and cfg.get("mode") and cfg.get("last_updated"):
                    current_mode = cfg.get("mode", "online")
                    logger.info("[ai_service] 检测到用户手动设置的模式: %s，跳过自动检测", current_mode)
                    return current_mode
    except Exception as e:
        logger.debug("[ai_service] 读取配置失败，使用默认自动检测: %s", e)
    has_network = _check_network()
    logger.info("[ai_service] 网络检测: %s", "可用" if has_network else "不可用")
    has_api_key = _check_api_key()
    logger.info("[ai_service] API Key检测: %s", "存在" if has_api_key else "不存在")  # nosemgrep
    target_mode = "online" if (has_network and has_api_key) else "offline"
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
# 2026-08-16 调整：免费额度优先链 zhipu→dashscope(自适应)→deepseek(付费)（JS-20260816-02/03）
FALLBACK_CHAIN = [
    "zhipu",
    "dashscope",
    "deepseek",
    "deepseek-reasoner",
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


def _ais_init_state(self, provider: str, api_key: str, key_file: str):
    self.provider = provider
    self._config = PROVIDERS.get(provider, PROVIDERS["deepseek"])
    self._timeout = 30
    self._stream_timeout = 60
    self._last_call_time = 0
    self._min_interval = 2
    self._fail_count = 0
    self._fail_threshold = 5
    self._breaker_until = 0
    self._total_calls = 0
    self._total_success = 0
    self._retry_count = 2
    self._mode = get_mode()
    self._state_lock = threading.Lock()
    self.api_key = api_key or _ais_auto_read_key(self, key_file)
    self._token_usage = {"total_prompt_tokens": 0, "total_completion_tokens": 0,
                         "total_tokens": 0, "calls_with_usage": 0, "last_usage": None, "daily": {}}
    self._usage_write_count = 0
    self._usage_last_write_time = 0.0
    _ais_restore_usage_from_file(self)
    self._session = None
    _ais_init_session(self)
    self._ollama_available = False
    _ais_detect_ollama(self)


def _ais_init_session(self):
    if requests is None:
        return
    try:
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=2)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)
        self._session.headers.update({"Content-Type": "application/json"})
    except Exception as e:
        logger.debug("[ai_service] session初始化失败，使用urllib降级: %s", e)
        self._session = None


def _ais_auto_read_key(self, key_file: str = "") -> str:
    key = get_api_key(key_file)
    if key:
        logger.info("[ai_service] API Key读取成功")
    else:
        logger.warning("[ai_service] 未找到API Key，AI功能将不可用")
    return key


def _ais_track_usage(self, api_response: Dict):
    usage = api_response.get("usage")
    if not usage:
        return
    prompt_tk = usage.get("prompt_tokens", 0)
    completion_tk = usage.get("completion_tokens", 0)
    total_tk = usage.get("total_tokens", 0)
    self._token_usage["total_prompt_tokens"] += prompt_tk
    self._token_usage["total_completion_tokens"] += completion_tk
    self._token_usage["total_tokens"] += total_tk
    self._token_usage["calls_with_usage"] += 1
    self._token_usage["last_usage"] = {"prompt": prompt_tk, "completion": completion_tk, "total": total_tk}
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        day_entry = self._token_usage.setdefault("daily", {}).setdefault(today, {"tokens": 0, "calls": 0})
        day_entry["tokens"] += total_tk
        day_entry["calls"] += 1
    except Exception as e:
        logger.debug("[ai_service] 日用量统计异常: %s", e)
    self._usage_write_count += 1
    now_ts = time.time()
    if self._usage_write_count >= 10 or (now_ts - self._usage_last_write_time) >= 300:
        _ais_persist_usage_to_file(self)
        self._usage_write_count = 0
        self._usage_last_write_time = now_ts


def _ais_restore_usage_from_file(self):
    try:
        data = safe_load_json(_TOKEN_USAGE_FILE, default=None, verify_checksum_flag=False)
        if data and isinstance(data, dict):
            self._token_usage["total_tokens"] = data.get("total_tokens", 0)
            self._token_usage["total_prompt_tokens"] = data.get("total_prompt_tokens", 0)
            self._token_usage["total_completion_tokens"] = data.get("total_completion_tokens", 0)
            self._token_usage["calls_with_usage"] = data.get("total_calls", 0)
            self._token_usage["daily"] = data.get("daily", {})
            logger.info("[ai_service] 恢复Token用量: total_tokens=%d, calls=%d",
                        self._token_usage["total_tokens"], self._token_usage["calls_with_usage"])
    except Exception as e:
        logger.warning("[ai_service] 恢复Token用量失败: %s", e)


def _ais_persist_usage_to_file(self):
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
        logger.debug("[ai_service] Token用量已持久化: total_tokens=%d", payload["total_tokens"])
    except Exception as e:
        logger.warning("[ai_service] Token用量持久化写入失败: %s", e)


def _ais_detect_ollama(self):
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", 11434), timeout=0.3)
        sock.close()
    except (OSError, socket.timeout):
        self._ollama_available = False
        return
    if self._session is None:
        return
    try:
        resp = self._session.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if models:
                available = [m["name"] for m in models[:5]]
                self._ollama_available = True
                logger.info("[ai_service] 检测到Ollama: %s", available)
                if "llama3.2" not in available:
                    first_model = available[0].split(":")[0]
                    PROVIDERS["ollama"]["model"] = first_model
                    logger.info("[ai_service] Ollama默认模型设为: %s", first_model)
    except Exception:
        self._ollama_available = False


def _ais_is_breaker_open(self) -> bool:
    return time.time() < self._breaker_until


def _ais_record_success(self):
    with self._state_lock:
        self._total_calls += 1
        self._total_success += 1
        self._fail_count = 0


def _ais_record_failure(self):
    with self._state_lock:
        self._total_calls += 1
        self._fail_count += 1
        if self._fail_count >= self._fail_threshold:
            self._breaker_until = time.time() + 60
            logger.warning("[ai_service] 连续失败%d次，熔断器打开60秒", self._fail_count)


def _ais_ensure_rate_limit(self):
    elapsed = time.time() - self._last_call_time
    if elapsed < self._min_interval:
        time.sleep(self._min_interval - elapsed)


def _ais_build_payload(self, system_prompt: str, user_prompt: str,
                       temperature: float = None, max_tokens: int = None,
                       stream: bool = False) -> Dict:
    config = self._config
    return {
        "model": config["model"],
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": temperature if temperature is not None else config["temperature"],
        "max_tokens": max_tokens if max_tokens is not None else config["max_tokens"],
        "stream": stream,
    }


def _ais_call_api(self, payload: Dict) -> Optional[Dict]:
    headers = {"Authorization": f"Bearer {self.api_key}"}
    api_url = self._config["api_url"]
    if self._session is not None:
        try:
            resp = self._session.post(api_url, json=payload, headers=headers, timeout=self._timeout)
            if resp.status_code == 200:
                data = resp.json()
                _ais_track_usage(self, data)
                return data
            logger.warning("[ai_service] API错误 %d: %s", resp.status_code, resp.text[:200])
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
    try:
        import urllib.request
        import urllib.error
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(api_url, data=data,
                                     headers={**headers, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("[ai_service] urllib HTTP错误: %d", e.code)
        return None
    except Exception as e:
        logger.warning("[ai_service] urllib异常: %s", e)
        return None


def _ais_call_api_stream(self, payload: Dict) -> Generator[str, None, None]:
    headers = {"Authorization": f"Bearer {self.api_key}"}
    api_url = self._config["api_url"]
    if self._session is None:
        logger.warning("[ai_service] 流式响应需要requests库支持")
        yield ""
        return
    try:
        with self._session.post(api_url, json=payload, headers=headers,
                                timeout=self._stream_timeout, stream=True) as resp:
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
                        delta = json.loads(data_str).get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.warning("[ai_service] 流式请求异常: %s", e)
        yield ""


def _ais_try_free_first(self, system_prompt, user_prompt, temperature, max_tokens, free_first) -> Optional[str]:
    """免费优先（W63补38）：免费池可用时先走免费模型。返回文本或 None。"""
    if self._mode == "offline" or free_first is False:
        return None
    try:
        from core.ai.free_model_pool import get_free_provider_cfgs, call_ai_failover
        _cfgs = get_free_provider_cfgs()
        if not _cfgs:
            return None
        _t = temperature if temperature is not None else 0.7
        _m = max_tokens if max_tokens is not None else 800
        _text, _err, _used = call_ai_failover(
            _cfgs, system_prompt, user_prompt, timeout=60, max_tokens=_m, temperature=_t,
            force_json_mode=False, allow_paid_fallback=False)
        if _text:
            _log_conv(system_prompt=system_prompt, user_prompt=user_prompt, reply=_text,
                      provider=(_used or {}).get("_provider", "siliconflow"),
                      model=(_used or {}).get("_model_id", "free"), token_usage={},
                      duration_ms=0, success=True)
            return _text
    except Exception as e:
        logger.debug("[ai_service] 免费优先调用异常: %s", e)
    return None


def _ais_chat_retry(self, payload, system_prompt, user_prompt, _call_start) -> Optional[str]:
    """主重试循环：调用 API 并记录成功日志。返回文本或 None（全部失败）。"""
    for attempt in range(self._retry_count + 1):
        data = self._call_api(payload)
        if data is not None:
            try:
                result = data["choices"][0]["message"]["content"]
                _ais_record_success(self)
                _duration = (time.time() - _call_start) * 1000
                _usage = data.get("usage", {})
                _log_conv(system_prompt=system_prompt, user_prompt=user_prompt, reply=result,
                          provider=self.provider, model=self._config.get("model", ""),
                          token_usage={"prompt": _usage.get("prompt_tokens", 0),
                                       "completion": _usage.get("completion_tokens", 0),
                                       "total": _usage.get("total_tokens", 0)},
                          duration_ms=_duration, success=True)
                return result
            except (KeyError, IndexError) as e:
                logger.warning("[ai_service] 响应解析失败: %s", e)
                continue
        if attempt < self._retry_count:
            time.sleep(1)
    return None


def _ais_try_adaptive_model(self, system_prompt, user_prompt, temperature, max_tokens, _call_start) -> Optional[str]:
    """模型自适应（W63补52/53）：dashscope 额度耗尽时自动切换可用模型重试。"""
    if self.provider not in ("dashscope",) or not self.api_key:
        return None
    try:
        from core.ai.adaptive_models import find_working_model
        best = find_working_model(self.provider, self.api_key, preferred=self._config.get("model", ""))
        if not best or best == self._config.get("model", ""):
            return None
        logger.info("[ai_service] 额度自适应: %s → %s", self._config.get("model", ""), best)
        with self._state_lock:
            self._config["model"] = best
        data = self._call_api(_ais_build_payload(self, system_prompt, user_prompt, temperature, max_tokens))
        if data is not None:
            try:
                result = data["choices"][0]["message"]["content"]
                _ais_record_success(self)
                _log_conv(system_prompt=system_prompt, user_prompt=user_prompt, reply=result,
                          provider=self.provider, model=best,
                          token_usage={"prompt": 0, "completion": 0, "total": 0},
                          duration_ms=(time.time() - _call_start) * 1000, success=True)
                return result
            except (KeyError, IndexError):
                pass
    except Exception as e:
        logger.debug("[ai_service] 模型自适应异常: %s", e)
    return None


def _ais_try_fallback(self, system_prompt, user_prompt, temperature, max_tokens, _fallback_depth) -> Optional[str]:
    """fallback 链：切换到下一个供应商重试。返回文本或 None。"""
    while (_fallback_depth < len(FALLBACK_CHAIN) and FALLBACK_CHAIN[_fallback_depth] == self.provider):
        _fallback_depth += 1
    if _fallback_depth >= len(FALLBACK_CHAIN):
        return None
    fallback_provider = FALLBACK_CHAIN[_fallback_depth]
    _kf = PROVIDER_KEY_FILES.get(fallback_provider, "")
    if _kf and _kf != "deepseek_key.txt" and not os.path.isfile(os.path.join(_SECRETS_DIR, _kf)):
        return _ais_chat(self, system_prompt, user_prompt, temperature, max_tokens,
                         _fallback_depth=_fallback_depth + 1)
    logger.info("[ai_service] 尝试fallback到: %s", fallback_provider)
    old_provider = self.provider
    self.switch_provider(fallback_provider)
    try:
        return _ais_chat(self, system_prompt, user_prompt, temperature, max_tokens,
                         _fallback_depth=_fallback_depth + 1)
    finally:
        self.switch_provider(old_provider)


def _ais_chat_offline(self, system_prompt, user_prompt, temperature, max_tokens) -> str:
    """离线模式：优先用 Ollama，否则返回空串。"""
    if self._ollama_available and self.provider != "ollama":
        old_provider = self.provider
        self.switch_provider("ollama")
        try:
            return _ais_chat(self, system_prompt, user_prompt, temperature, max_tokens,
                             _fallback_depth=len(FALLBACK_CHAIN))
        finally:
            self.switch_provider(old_provider)
    logger.debug("[ai_service] 本地模式，跳过API调用")
    return ""


def _ais_chat(self, system_prompt: str, user_prompt: str,
              temperature: float = None, max_tokens: int = None,
              _fallback_depth: int = 0, free_first: bool = None) -> str:
    free_text = _ais_try_free_first(self, system_prompt, user_prompt, temperature, max_tokens, free_first)
    if free_text is not None:
        return free_text
    if self._mode == "offline":
        return _ais_chat_offline(self, system_prompt, user_prompt, temperature, max_tokens)
    if not self.api_key:
        logger.warning("[ai_service] API Key未配置")
        return ""
    if _ais_is_breaker_open(self):
        logger.warning("[ai_service] 熔断器打开中，跳过调用")
        return ""
    _ais_ensure_rate_limit(self)
    payload = _ais_build_payload(self, system_prompt, user_prompt, temperature, max_tokens)
    self._last_call_time = time.time()
    _call_start = time.time()
    result = _ais_chat_retry(self, payload, system_prompt, user_prompt, _call_start)
    if result is not None:
        return result
    _ais_record_failure(self)
    _log_conv(system_prompt=system_prompt, user_prompt=user_prompt, reply="",
              provider=self.provider, model=self._config.get("model", ""),
              duration_ms=(time.time() - _call_start) * 1000, success=False,
              error_msg=f"连续{self._retry_count + 1}次调用失败")
    adaptive = _ais_try_adaptive_model(self, system_prompt, user_prompt, temperature, max_tokens, _call_start)
    if adaptive is not None:
        return adaptive
    fb = _ais_try_fallback(self, system_prompt, user_prompt, temperature, max_tokens, _fallback_depth)
    return fb if fb is not None else ""


def _ais_chat_stream(self, system_prompt: str, user_prompt: str,
                     temperature: float = None, max_tokens: int = None
                     ) -> Generator[str, None, None]:
    if self._mode == "offline" or not self.api_key or _ais_is_breaker_open(self):
        yield ""
        return
    _ais_ensure_rate_limit(self)
    payload = _ais_build_payload(self, system_prompt, user_prompt, temperature, max_tokens, stream=True)
    self._last_call_time = time.time()
    collected = []
    for chunk in _ais_call_api_stream(self, payload):
        if chunk:
            collected.append(chunk)
            yield chunk
        else:
            break
    if collected:
        _ais_record_success(self)
    else:
        _ais_record_failure(self)


def _ais_analyze(self, subsystem: str, content: str, extra_system: str = "", **kwargs) -> str:
    system_prompt = _SUBSYSTEM_PROMPTS.get(subsystem, _SUBSYSTEM_PROMPTS["general"])
    if extra_system:
        system_prompt = system_prompt + "\n" + extra_system
    return _ais_chat(self, system_prompt, content, **kwargs)


def _ais_quick(self, subsystem: str, content: str) -> str:
    return _ais_analyze(self, subsystem, content, extra_system="用一句话回答，不超过50字。",
                        max_tokens=200, temperature=0.3)


def _ais_switch_provider(self, provider: str):
    with self._state_lock:
        if provider in PROVIDERS:
            self.provider = provider
            self._config = PROVIDERS[provider]
            key_file = PROVIDER_KEY_FILES.get(provider, "")
            if key_file:
                _kf = os.path.join(_SECRETS_DIR, key_file)
                if key_file == "deepseek_key.txt":
                    self.api_key = get_api_key(_kf)
                else:
                    self.api_key = get_api_key(_kf) if os.path.isfile(_kf) else ""
            if provider == "dashscope" and "dashscope" in PROVIDERS:
                try:
                    from core.ai.adaptive_models import current_model
                    _m = current_model(provider, self._config.get("model", ""))
                    if _m:
                        self._config["model"] = _m
                except Exception as e:
                    logger.debug("[ai_service] adaptive_models.current_model 异常: %s", e)
            logger.info("[ai_service] 已切换到供应商: %s", provider)
        else:
            logger.warning("[ai_service] 不支持的供应商: %s", provider)


class AIService:
    """统一AI服务 — 所有子系统共用入口（方法委托模块级函数）。"""
    def __init__(self, provider: str = "zhipu", api_key: str = "", key_file: str = ""):
        _ais_init_state(self, provider, api_key, key_file)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_online(self) -> bool:
        return self._mode == "online"

    @property
    def is_available(self) -> bool:
        if self._mode == "offline":
            return self._ollama_available
        return bool(self.api_key) and not _ais_is_breaker_open(self)

    @property
    def stats(self) -> Dict:
        return {"provider": self.provider, "model": self._config["model"], "mode": self._mode,
                "available": self.is_available, "total_calls": self._total_calls,
                "total_success": self._total_success, "fail_count": self._fail_count,
                "is_breaker_open": _ais_is_breaker_open(self),
                "ollama_detected": self._ollama_available, "token_usage": self._token_usage}

    def _is_breaker_open(self) -> bool:
        return _ais_is_breaker_open(self)
    def _call_api(self, payload):
        return _ais_call_api(self, payload)
    def _detect_ollama(self):
        _ais_detect_ollama(self)

    def chat(self, system_prompt, user_prompt, temperature=None, max_tokens=None,
             _fallback_depth=0, free_first=None):
        return _ais_chat(self, system_prompt, user_prompt, temperature, max_tokens, _fallback_depth, free_first)
    def chat_stream(self, system_prompt, user_prompt, temperature=None, max_tokens=None):
        return _ais_chat_stream(self, system_prompt, user_prompt, temperature, max_tokens)
    def analyze(self, subsystem, content, extra_system="", **kwargs):
        return _ais_analyze(self, subsystem, content, extra_system, **kwargs)
    def quick(self, subsystem, content):
        return _ais_quick(self, subsystem, content)
    def switch_provider(self, provider):
        _ais_switch_provider(self, provider)


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
