# -*- coding: utf-8 -*-
"""金水谣 · 可扩展能力注册表（纯标准库，零外部依赖）
================================================
对应需求 7「可扩展接口预留」：架构预留标准化扩展接口，后续接入新功能
（如新的分析器、新的问答后端）时，只需 register 一下即可被统一调度，
无需改动 server 或其他模块 —— 即插即用。

用法：
    from extension_registry import REGISTRY
    REGISTRY.register("我的功能", my_handler, desc="...", category="分析")
    REGISTRY.list()           # 列出所有已注册能力（前端可展示）
    REGISTRY.dispatch("我的功能", *args, **kwargs)
"""


class ExtensionRegistry:
    def __init__(self):
        self._caps = {}

    def register(self, name, handler, desc="", category="通用", enabled=True):
        """注册一个能力。handler 为可调用对象；调用时由调度方决定参数。"""
        if not callable(handler):
            raise TypeError("handler 必须是可调用对象")
        self._caps[name] = {
            "name": name, "handler": handler, "desc": desc,
            "category": category, "enabled": enabled,
        }

    def unregister(self, name):
        self._caps.pop(name, None)

    def enable(self, name, on=True):
        if name in self._caps:
            self._caps[name]["enabled"] = on

    def has(self, name):
        return name in self._caps and self._caps[name]["enabled"]

    def list(self):
        """返回能力元信息列表（不含 handler 本身，便于 JSON 序列化）。"""
        out = []
        for c in self._caps.values():
            out.append({
                "name": c["name"], "desc": c["desc"],
                "category": c["category"], "enabled": c["enabled"],
            })
        out.sort(key=lambda x: (x["category"], x["name"]))
        return out

    def dispatch(self, name, *args, **kwargs):
        """调用指定能力。未注册或已禁用则抛 KeyError。"""
        if name not in self._caps:
            raise KeyError(f"未注册的能力：{name}")
        c = self._caps[name]
        if not c["enabled"]:
            raise KeyError(f"能力已禁用：{name}")
        return c["handler"](*args, **kwargs)

    def call(self, name, *args, default=None, **kwargs):
        """同 dispatch，但出错/未注册时返回 default 而不是抛异常。"""
        try:
            return self.dispatch(name, *args, **kwargs)
        except Exception:
            return default


# 全局单例：所有模块共享同一张注册表
REGISTRY = ExtensionRegistry()


def register_builtins():
    """把智能代码助手自带能力登记进全局注册表（幂等，可重复调用）。"""
    # 延迟导入，避免在没有依赖时报错
    try:
        from project_loader import scan_directory
        REGISTRY.register("项目扫描", lambda root: scan_directory(root),
                          desc="解析目录结构、识别入口/配置/核心并分级", category="智能代码助手")
    except Exception:
        pass
    try:
        from recommender import recommend
        REGISTRY.register("智能推荐",
                          lambda root, files: recommend(root, files),
                          desc="四维推荐：预设问题/风格/预警/性能", category="智能代码助手")
    except Exception:
        pass
    try:
        from code_retriever import build_index, search
        def _retrieve(root, files, query, top_k=5):
            idx = build_index(root, files)
            return search(idx, query, top_k=top_k)
        REGISTRY.register("代码检索", _retrieve,
                          desc="按自然语言定位相关代码文件与片段", category="智能代码助手")
    except Exception:
        pass
    return REGISTRY


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test():
    print("== extension_registry 自测 ==")
    reg = ExtensionRegistry()
    reg.register("加一", lambda x: x + 1, desc="把数字加一", category="测试")
    assert reg.has("加一")
    assert reg.dispatch("加一", 4) == 5
    lst = reg.list()
    assert lst[0]["name"] == "加一" and lst[0]["enabled"]
    reg.enable("加一", False)
    assert reg.call("加一", 4, default=-1) == -1, "禁用后应回退 default"
    # 命名冲突覆盖
    reg.register("加一", lambda x: x + 100)
    assert reg.dispatch("加一", 4) == 104
    reg.unregister("加一")
    assert not reg.has("加一")
    print("✓ 注册/调度/禁用/覆盖/注销 均正常")
    print("extension_registry 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
