# -*- coding: utf-8 -*-
"""
金水谣统一缓存层 v1.0

双级缓存：
  L1: 内存缓存（TTL自动过期，毫秒级访问）
  L2: 文件缓存（safe_json持久化，跨会话复用）

设计原则：
  - 零外部依赖（只用Python标准库+项目已有safe_json）
  - 自动TTL过期，无需手动清理
  - 轻量化装饰器，一行代码接入
  - 支持缓存统计（命中率/大小/过期数）

使用示例：
    cache = CacheManager()
    
    @cache.cached(ttl=300)  # 缓存5分钟
    def get_lottery_data(lot_type):
        # ... 耗时的数据获取 ...
        return result
"""

import time
import json
import hashlib
import logging
import threading
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Dict, List

logger = logging.getLogger("jinshuiyao.cache")


# ======================================================================
# 内存缓存（L1）
# ======================================================================
class MemoryCache:
    """线程安全的内存缓存，支持TTL自动过期"""

    def __init__(self, default_ttl: int = 300):
        """
        Parameters
        ----------
        default_ttl : int
            默认过期时间（秒），默认5分钟
        """
        self._default_ttl = default_ttl
        self._data: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._stats = {"hits": 0, "misses": 0, "expired": 0, "sets": 0}

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，已过期返回 None"""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            if time.time() > entry["expires_at"]:
                del self._data[key]
                self._stats["expired"] += 1
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """设置缓存"""
        with self._lock:
            expires_at = time.time() + (ttl if ttl is not None else self._default_ttl)
            self._data[key] = {
                "value": value,
                "expires_at": expires_at,
                "created_at": time.time()
            }
            self._stats["sets"] += 1

    def delete(self, key: str):
        """删除缓存"""
        with self._lock:
            self._data.pop(key, None)

    def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._data.clear()

    def clean_expired(self) -> int:
        """清理过期缓存，返回清理数量"""
        now = time.time()
        expired_keys = []
        with self._lock:
            for key, entry in self._data.items():
                if now > entry["expires_at"]:
                    expired_keys.append(key)
            for key in expired_keys:
                del self._data[key]
        return len(expired_keys)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0
        return {
            **self._stats,
            "hit_rate": round(rate, 1),
            "current_size": self.size
        }


# ======================================================================
# 文件缓存（L2）
# ======================================================================
class FileCache:
    """基于 safe_json 的磁盘持久化缓存
    适合缓存量大、需跨会话重用的数据（如历史开奖数据）
    """

    def __init__(self, cache_dir: Optional[str] = None, default_ttl: int = 86400):
        """
        Parameters
        ----------
        cache_dir : str | None
            缓存目录，默认: 项目根目录/金水谣数据/cache/
        default_ttl : int
            默认过期时间（秒），默认24小时
        """
        self._default_ttl = default_ttl

        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            # 自动定位到金水谣数据/cache/
            self._cache_dir = Path(__file__).resolve().parent.parent / "金水谣数据" / "cache"

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._stats = {"hits": 0, "misses": 0, "expired": 0, "sets": 0}
        self._lock = threading.Lock()

    def _key_to_path(self, key: str) -> Path:
        """将缓存key转为文件路径"""
        safe_name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self._cache_dir / f"cache_{safe_name}.json"

    def get(self, key: str) -> Optional[Any]:
        """从文件缓存读取"""
        path = self._key_to_path(key)
        if not path.exists():
            self._stats["misses"] += 1
            return None

        try:
            import utils.safe_json as _sj_file
            data = _sj_file.safe_load_json(str(path))

            if data is None:
                self._stats["misses"] += 1
                return None

            if time.time() > data.get("expires_at", 0):
                path.unlink(missing_ok=True)
                self._stats["expired"] += 1
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return data.get("value")

        except Exception as e:
            logger.debug("文件缓存读取失败 %s: %s", key[:20], e)
            self._stats["misses"] += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """写入文件缓存"""
        path = self._key_to_path(key)
        expires_at = time.time() + (ttl if ttl is not None else self._default_ttl)

        data = {
            "value": value,
            "expires_at": expires_at,
            "created_at": time.time(),
            "key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        }

        try:
            import utils.safe_json as _sj
            _sj.safe_write_json(str(path), data)
            self._stats["sets"] += 1
        except Exception as e:
            logger.warning("文件缓存写入失败 %s: %s", key[:20], e)

    def delete(self, key: str):
        path = self._key_to_path(key)
        path.unlink(missing_ok=True)

    def clear(self):
        """清空所有文件缓存"""
        count = 0
        for f in self._cache_dir.glob("cache_*.json"):
            f.unlink(missing_ok=True)
            count += 1
        logger.info("文件缓存已清理: %d 个文件", count)

    def clean_expired(self) -> int:
        """清理过期文件缓存，返回清理数量"""
        count = 0
        now = time.time()
        for f in self._cache_dir.glob("cache_*.json"):
            try:
                import utils.safe_json as _sj_file
                data = _sj_file.safe_load_json(str(f))
                if data and now > data.get("expires_at", 0):
                    f.unlink(missing_ok=True)
                    count += 1
            except Exception:
                continue
        if count:
            logger.info("过期文件缓存已清理: %d 个", count)
        return count

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0
        file_count = len(list(self._cache_dir.glob("cache_*.json")))
        return {
            **self._stats,
            "hit_rate": round(rate, 1),
            "current_files": file_count,
            "cache_dir": str(self._cache_dir)
        }


# ======================================================================
# 统一缓存管理器
# ======================================================================
class CacheManager:
    """统一缓存管理器（L1内存 + L2磁盘）

    自动路由：
      - 小数据 / 高频访问 → L1 内存缓存
      - 大数据 / 需持久化 → L2 文件缓存
      - 默认策略：优先L1，未命中查L2
    """

    def __init__(self, memory_ttl: int = 300, file_ttl: int = 86400,
                 file_cache_dir: Optional[str] = None):
        self.memory = MemoryCache(default_ttl=memory_ttl)
        self.file = FileCache(cache_dir=file_cache_dir, default_ttl=file_ttl)
        self._fallback_enabled = True

    def get(self, key: str, use_file: bool = True) -> Optional[Any]:
        """获取缓存（L1→L2两级查找）"""
        # L1 内存缓存
        value = self.memory.get(key)
        if value is not None:
            return value

        # L2 文件缓存
        if use_file and self._fallback_enabled:
            value = self.file.get(key)
            if value is not None:
                # 回填 L1（缩短下次访问路径）
                self.memory.set(key, value)
                return value

        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None,
            persist: bool = False):
        """存入缓存

        Parameters
        ----------
        key : str
            缓存键
        value : Any
            缓存值（必须是 JSON 可序列化类型）
        ttl : int | None
            过期秒数（None 使用默认值）
        persist : bool
            是否持久化到文件缓存
        """
        self.memory.set(key, value, ttl=ttl)
        if persist:
            self.file.set(key, value, ttl=ttl)

    def delete(self, key: str):
        """从所有层级删除缓存"""
        self.memory.delete(key)
        self.file.delete(key)

    def clear_all(self):
        """清空所有缓存"""
        self.memory.clear()
        self.file.clear()

    def clean_expired(self):
        """清理所有过期缓存"""
        mem_cleaned = self.memory.clean_expired()
        file_cleaned = self.file.clean_expired()
        return mem_cleaned + file_cleaned

    def disable_file_fallback(self):
        """禁用L2文件缓存回退（仅用内存缓存）"""
        self._fallback_enabled = False

    def enable_file_fallback(self):
        """启用L2文件缓存回退"""
        self._fallback_enabled = True

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "memory": self.memory.stats,
            "file": self.file.stats,
            "fallback_enabled": self._fallback_enabled
        }

    def cached(self, ttl: Optional[int] = None, persist: bool = False,
               key_prefix: str = ""):
        """装饰器：一行代码缓存函数返回值

        Parameters
        ----------
        ttl : int | None
            缓存过期秒数
        persist : bool
            是否持久化到文件缓存
        key_prefix : str
            缓存键前缀（用于区分相同参数的不同场景）

        使用示例：
            @cache.cached(ttl=300)
            def fetch_data(lot_type):
                ...

            @cache.cached(ttl=86400, persist=True)
            def get_odds(match_id):
                ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                # 生成缓存键：函数名 + 参数 -> 唯一键
                key_parts = [key_prefix, func.__module__, func.__name__]
                key_parts.extend(str(a) for a in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)

                # 尝试命中缓存
                result = self.get(cache_key, use_file=persist)
                if result is not None:
                    return result

                # 执行原函数
                result = func(*args, **kwargs)

                # 存入缓存
                self.set(cache_key, result, ttl=ttl, persist=persist)
                return result

            # 附加缓存管理方法到装饰后的函数
            _func_prefix = ":".join([key_prefix, func.__module__, func.__name__])
            def _cache_clear():
                """清除该函数所有缓存条目"""
                keys_to_del = [k for k in list(self.memory._data.keys())
                               if k.startswith(_func_prefix)]
                for k in keys_to_del:
                    self.delete(k)
                # 同时清理文件缓存目录
                if self.file and hasattr(self.file, '_cache_dir'):
                    import glob
                    pattern = os.path.join(self.file._cache_dir, _func_prefix.replace(":", "_") + "*")
                    for fp in glob.glob(pattern):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
            wrapper.cache_clear = _cache_clear
            return wrapper
        return decorator


# ======================================================================
# 全局单例（所有模块共享同一个缓存实例）
# ======================================================================
_cache_instance: Optional[CacheManager] = None
_cache_lock = threading.Lock()


def get_cache() -> CacheManager:
    """获取全局缓存实例（单例模式）"""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = CacheManager()
                logger.info("统一缓存层已初始化 (L1:%ds + L2:%ds)",
                           _cache_instance.memory._default_ttl,
                           _cache_instance.file._default_ttl)
    return _cache_instance


# ======================================================================
# 快捷函数
# ======================================================================
def cached(ttl: Optional[int] = None, persist: bool = False, key_prefix: str = ""):
    """装饰器快捷入口"""
    return get_cache().cached(ttl=ttl, persist=persist, key_prefix=key_prefix)


# ======================================================================
# 自测
# ======================================================================
def _self_test():
    """快速自测缓存功能"""
    # 当直接运行时，将项目目录加入路径
    import sys as _sys
    _test_dir = Path(__file__).resolve().parent.parent
    if str(_test_dir) not in _sys.path:
        _sys.path.insert(0, str(_test_dir))

    cache = get_cache()
    test_key = "_self_test_key_"

    # 写入 + 读取
    cache.set(test_key, {"hello": "world"}, ttl=60)
    val = cache.get(test_key)
    assert val == {"hello": "world"}, "缓存写入/读取失败"
    print("✅ 内存缓存 写入/读取 正常")

    # 持久化
    cache.set(test_key + "_persist", "持久化测试", ttl=3600, persist=True)
    val = cache.get(test_key + "_persist", use_file=True)
    assert val == "持久化测试", "文件缓存失败"
    print("✅ 文件缓存 写入/读取 正常")

    # TTL过期
    cache.set(test_key + "_expire", "马上过期", ttl=0)
    import time as _time
    _time.sleep(0.01)
    val = cache.get(test_key + "_expire")
    assert val is None, "TTL过期失败"
    print("✅ TTL过期 正常")

    # 装饰器
    call_count = [0]

    @cache.cached(ttl=60)
    def test_func(x):
        call_count[0] += 1
        return x * 2

    assert test_func(5) == 10
    assert test_func(5) == 10  # 第二次走缓存
    assert call_count[0] == 1  # 函数只被调用了1次
    print("✅ 装饰器缓存 正常")

    # 统计
    stats = cache.stats
    print(f"📊 缓存统计: 命中={stats['memory']['hit_rate']}% "
          f"大小={stats['memory']['current_size']}条")

    # 清理
    cache.delete(test_key)
    cache.delete(test_key + "_persist")
    cache.delete(test_key + "_expire")
    test_func.cache_clear()

    print("✅ 全部缓存测试通过！")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _self_test()
