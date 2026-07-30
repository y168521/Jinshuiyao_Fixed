# -*- coding: utf-8 -*-
"""
金水谣系统 - 插件化扩展接口管理器

提供插件化扩展能力，让系统可以方便地对接其他模块和系统。
支持动态发现、加载、卸载插件，并通过钩子机制在各阶段注入自定义逻辑。

设计原则：
- 使用 abc 模块定义抽象接口
- 使用 importlib 动态加载插件
- 异常隔离：单个插件失败不影响整体
- 纯 Python 标准库，不依赖第三方包
"""

import os
import sys
import logging
import importlib.util
import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


# =============================================================================
# 插件基类
# =============================================================================

class JinshuiyaoPlugin(ABC):
    """金水谣插件基类 - 所有插件必须继承此类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """插件唯一名称"""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """插件版本"""
        ...

    @abstractmethod
    def on_init(self, app_context):
        """插件初始化（系统启动时调用）

        Parameters
        ----------
        app_context : dict
            包含 App 实例引用和系统配置的字典，例如：
            {
                "app": <App实例>,
                "config": <系统配置字典>,
                "settings": <用户设置字典>
            }
        """
        ...

    @abstractmethod
    def on_predict(self, lot, play_plan, prediction_result):
        """预测完成后的钩子（可修改预测结果）

        Parameters
        ----------
        lot : str
            彩种标识，如 'ssq'
        play_plan : dict
            当前使用的方案配置
        prediction_result : dict
            预测生成的结果数据

        Returns
        -------
        dict or None
            返回修改后的 prediction_result，或 None 表示不修改
        """
        ...

    @abstractmethod
    def on_review(self, lot, period, predictions, actual_nums, hits):
        """复盘完成后的钩子

        Parameters
        ----------
        lot : str
            彩种标识
        period : str
            期号
        predictions : dict
            预测数据
        actual_nums : list
            实际开奖号码
        hits : int
            命中数量
        """
        ...

    def on_shutdown(self):
        """插件关闭（系统退出时调用）

        子类可按需重写此方法，执行资源释放等清理操作。
        默认实现为空操作。
        """
        pass

    def on_data_fetch(self, lot, period, raw_data):
        """数据抓取完成后的钩子（预留）

        Parameters
        ----------
        lot : str
            彩种标识
        period : str
            期号
        raw_data : dict
            抓取到的原始数据

        Returns
        -------
        dict or None
            返回处理后的数据，或 None 表示不修改
        """
        pass

    def on_settings_change(self, old_settings, new_settings):
        """设置变更时的钩子（预留）

        Parameters
        ----------
        old_settings : dict
            变更前的设置
        new_settings : dict
            变更后的设置
        """
        pass

    def get_info(self) -> Dict[str, str]:
        """获取插件信息

        Returns
        -------
        dict
            包含插件名称和版本的信息字典
        """
        return {"name": self.name, "version": self.version}

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r} version={self.version!r}>"


# =============================================================================
# 示例插件
# =============================================================================

class ExamplePlugin(JinshuiyaoPlugin):
    """示例插件 - 展示如何编写金水谣插件

    此插件仅用于演示插件开发流程，不执行任何实际业务逻辑。
    """

    name = "example"
    version = "1.0.0"

    def on_init(self, app_context):
        """示例插件初始化"""
        logger.info("示例插件已加载, app_context keys: %s",
                     list(app_context.keys()) if app_context else [])

    def on_predict(self, lot, play_plan, prediction_result):
        """预测钩子示例：不做修改，直接返回原结果"""
        logger.debug("示例插件 on_predict: lot=%s, play_plan=%s",
                      lot, play_plan)
        # 可以修改预测结果或添加额外信息，此处仅做演示
        return prediction_result  # 返回 None 则表示不修改

    def on_review(self, lot, period, predictions, actual_nums, hits):
        """复盘钩子示例：记录复盘信息"""
        logger.info("示例插件 on_review: %s 第%s期 复盘完成, 命中=%s",
                     lot, period, hits)

    def on_shutdown(self):
        """示例插件关闭"""
        logger.info("示例插件已关闭")


# =============================================================================
# 插件管理器
# =============================================================================

class PluginManager:
    """插件管理器 - 负责插件的发现、加载、卸载和钩子调度

    插件发现方式：
    1. 扫描 plugins/ 目录下的 .py 文件
    2. 每个文件中查找继承自 JinshuiyaoPlugin 的类
    3. 实例化并注册

    使用示例::

        manager = PluginManager(plugin_dir="Jinshuiyao_Fixed/plugins")
        manager.discover_plugins()
        manager.initialize_all({"app": app, "config": config})
        results = manager.call_hook("on_predict", lot, plan, result)
        manager.shutdown_all()
    """

    # 预留的钩子点列表
    _KNOWN_HOOKS = {
        "on_init",           # 系统初始化
        "on_predict",        # 预测生成后
        "on_review",         # 复盘完成后
        "on_data_fetch",     # 数据抓取后
        "on_settings_change",# 设置变更时
        "on_shutdown",       # 系统关闭
    }

    def __init__(self, plugin_dir: Optional[str] = None):
        """初始化插件管理器

        Parameters
        ----------
        plugin_dir : str or None
            插件目录路径。默认为 Jinshuiyao_Fixed/plugins/
        """
        # 确定插件目录
        if plugin_dir is None:
            # 默认：Jinshuiyao_Fixed/plugins/
            current = Path(__file__).resolve().parent.parent  # engines/ -> Jinshuiyao_Fixed/
            plugin_dir = str(current / "plugins")

        self.plugin_dir = plugin_dir
        # 已注册的插件: {name: instance}
        self._plugins: Dict[str, JinshuiyaoPlugin] = {}
        # 插件加载顺序列表（用于按优先级调用钩子）
        self._plugin_order: List[str] = []
        # 加载失败的插件记录: {name: error_message}
        self._failed_plugins: Dict[str, str] = {}
        logger.info("插件管理器初始化, 插件目录: %s", self.plugin_dir)

    # -------------------------------------------------------------------------
    # 插件发现与加载
    # -------------------------------------------------------------------------

    def discover_plugins(self) -> List[str]:
        """扫描并发现所有可用插件

        扫描 plugin_dir 目录下的 .py 文件，在每个文件中查找
        继承自 JinshuiyaoPlugin 的具体类，并自动加载。

        Returns
        -------
        list[str]
            成功加载的插件名称列表
        """
        plugin_dir_path = Path(self.plugin_dir)

        if not plugin_dir_path.is_dir():
            logger.warning("插件目录不存在: %s, 跳过插件发现", self.plugin_dir)
            return []

        discovered = []

        for py_file in sorted(plugin_dir_path.glob("*.py")):
            # 跳过 __init__.py 和以 _ 开头的私有文件
            if py_file.name.startswith("_"):
                continue

            file_path = str(py_file.resolve())
            logger.debug("扫描插件文件: %s", file_path)

            try:
                classes = self._find_plugin_classes(file_path)
                for cls in classes:
                    plugin_name = self._load_plugin(cls)
                    if plugin_name:
                        discovered.append(plugin_name)
            except Exception as e:
                logger.error("加载插件文件失败: %s, 错误: %s", file_path, e,
                             exc_info=True)
                self._failed_plugins[file_path] = str(e)

        logger.info("插件发现完成, 成功加载 %d 个插件: %s",
                     len(discovered), discovered)
        return discovered

    def _find_plugin_classes(self, file_path: str) -> List[Type[JinshuiyaoPlugin]]:
        """在指定文件中查找所有继承自 JinshuiyaoPlugin 的具体类

        Parameters
        ----------
        file_path : str
            Python 文件路径

        Returns
        -------
        list[type]
            找到的插件类列表
        """
        module_name = f"_jinshuiyao_plugin_{Path(file_path).stem}"

        # 使用 importlib 动态加载模块
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.warning("无法为文件 %s 创建模块规格", file_path)
            return []

        module = importlib.util.module_from_spec(spec)

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error("执行插件模块失败: %s, 错误: %s", file_path, e)
            raise

        # 查找所有继承自 JinshuiyaoPlugin 的类（排除基类自身和抽象类）
        plugin_classes = []
        for attr_name, attr_value in inspect.getmembers(module, inspect.isclass):
            if (issubclass(attr_value, JinshuiyaoPlugin)
                    and attr_value is not JinshuiyaoPlugin
                    and not inspect.isabstract(attr_value)):
                plugin_classes.append(attr_value)
                logger.debug("发现插件类: %s (模块: %s)", attr_name, module_name)

        return plugin_classes

    def load_plugin(self, plugin_class: Type[JinshuiyaoPlugin]) -> Optional[str]:
        """加载单个插件（异常隔离）

        Parameters
        ----------
        plugin_class : type
            插件类（必须是 JinshuiyaoPlugin 的子类）

        Returns
        -------
        str or None
            成功返回插件名称，失败返回 None
        """
        return self._load_plugin(plugin_class)

    def _load_plugin(self, plugin_class: Type[JinshuiyaoPlugin]) -> Optional[str]:
        """内部方法：加载单个插件实例

        异常隔离：加载失败不会影响其他插件，只会记录错误日志。

        Parameters
        ----------
        plugin_class : type
            插件类

        Returns
        -------
        str or None
            成功返回插件名称，失败返回 None
        """
        try:
            instance = plugin_class()
            plugin_name = instance.name

            # 检查是否已存在同名插件：先创建新实例成功后再卸载旧插件
            if plugin_name in self._plugins:
                logger.warning("插件名称冲突: '%s' 已被占用, 将覆盖旧插件", plugin_name)

            # 注册插件
            self._plugins[plugin_name] = instance
            if plugin_name not in self._plugin_order:
                self._plugin_order.append(plugin_name)

            # 新实例注册成功后再卸载旧实例（如果有冲突）
            # 旧实例已在上面通过 self._plugins[plugin_name] = instance 被替换

            logger.info("插件加载成功: %s v%s", plugin_name, instance.version)
            return plugin_name

        except Exception as e:
            cls_name = getattr(plugin_class, "__name__", str(plugin_class))
            logger.error("加载插件类 '%s' 失败: %s", cls_name, e,
                         exc_info=True)
            self._failed_plugins[cls_name] = str(e)
            return None

    # -------------------------------------------------------------------------
    # 插件卸载
    # -------------------------------------------------------------------------

    def unload_plugin(self, name: str) -> bool:
        """卸载指定插件

        卸载前会调用插件的 on_shutdown 方法。

        Parameters
        ----------
        name : str
            插件名称

        Returns
        -------
        bool
            成功返回 True，插件不存在返回 False
        """
        if name not in self._plugins:
            logger.warning("尝试卸载不存在的插件: %s", name)
            return False

        return self._unload_plugin_internal(name)

    def _unload_plugin_internal(self, name: str) -> bool:
        """内部方法：执行插件卸载逻辑"""
        instance = self._plugins[name]

        try:
            instance.on_shutdown()
        except Exception as e:
            logger.error("插件 '%s' 关闭时出错: %s", name, e, exc_info=True)

        del self._plugins[name]
        if name in self._plugin_order:
            self._plugin_order.remove(name)

        logger.info("插件已卸载: %s", name)
        return True

    # -------------------------------------------------------------------------
    # 插件查询
    # -------------------------------------------------------------------------

    def get_plugin(self, name: str) -> Optional[JinshuiyaoPlugin]:
        """获取插件实例

        Parameters
        ----------
        name : str
            插件名称

        Returns
        -------
        JinshuiyaoPlugin or None
            插件实例，不存在则返回 None
        """
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, str]]:
        """列出所有已加载插件

        Returns
        -------
        list[dict]
            每个元素包含插件名称和版本，按加载顺序排列
        """
        result = []
        for name in self._plugin_order:
            if name in self._plugins:
                result.append(self._plugins[name].get_info())
        return result

    def list_failed(self) -> Dict[str, str]:
        """列出所有加载失败的插件及其错误信息

        Returns
        -------
        dict
            {插件名/文件名: 错误信息}
        """
        return dict(self._failed_plugins)

    # -------------------------------------------------------------------------
    # 钩子调用
    # -------------------------------------------------------------------------

    def call_hook(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """调用所有插件的指定钩子

        按加载顺序（优先级）依次调用每个插件中对应名称的方法。
        单个插件调用失败不会影响后续插件的调用（异常隔离）。

        Parameters
        ----------
        hook_name : str
            钩子方法名，如 'on_predict', 'on_review' 等
        *args : tuple
            传递给钩子方法的位置参数
        **kwargs : dict
            传递给钩子方法的关键字参数

        Returns
        -------
        list
            所有插件该钩子的返回值列表
        """
        results = []

        if hook_name not in self._KNOWN_HOOKS:
            logger.warning("调用了未知的钩子: %s", hook_name)

        for name in self._plugin_order:
            instance = self._plugins.get(name)
            if instance is None:
                continue

            hook_method = getattr(instance, hook_name, None)
            if hook_method is None or not callable(hook_method):
                continue

            # 跳过抽象方法（未被子类实现）
            if getattr(hook_method, "__isabstractmethod__", False):
                continue

            try:
                result = hook_method(*args, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error("插件 '%s' 的钩子 '%s' 调用失败: %s",
                             name, hook_name, e, exc_info=True)
                results.append(None)

        return results

    def broadcast_event(self, event_name: str, data: Any) -> Dict[str, Any]:
        """广播事件给所有插件

        与 call_hook 不同，broadcast_event 使用统一的事件签名，
        适用于自定义事件或插件间通信场景。

        每个插件可以通过实现 ``on_event`` 方法来接收事件广播。
        如果插件未实现 ``on_event`` 方法，将跳过该插件。

        Parameters
        ----------
        event_name : str
            事件名称
        data : any
            事件数据（可以是任意类型）

        Returns
        -------
        dict
            {插件名称: 插件返回值} 的映射字典
        """
        results = {}

        for name in self._plugin_order:
            instance = self._plugins.get(name)
            if instance is None:
                continue

            on_event = getattr(instance, "on_event", None)
            if on_event is None or not callable(on_event):
                continue

            try:
                result = on_event(event_name, data)
                results[name] = result
            except Exception as e:
                logger.error("插件 '%s' 处理事件 '%s' 失败: %s",
                             name, event_name, e, exc_info=True)
                results[name] = None

        return results

    # -------------------------------------------------------------------------
    # 生命周期管理
    # -------------------------------------------------------------------------

    def initialize_all(self, app_context: dict) -> None:
        """初始化所有已加载的插件

        Parameters
        ----------
        app_context : dict
            应用上下文，包含 App 实例和配置信息
        """
        logger.info("初始化所有插件, 共 %d 个", len(self._plugins))
        self.call_hook("on_init", app_context)

    def shutdown_all(self) -> None:
        """关闭所有已加载的插件

        按加载顺序的逆序依次关闭，确保后加载的插件先关闭。
        """
        logger.info("关闭所有插件, 共 %d 个", len(self._plugins))

        # 逆序关闭
        for name in reversed(self._plugin_order):
            self.unload_plugin(name)

        logger.info("所有插件已关闭")

    def reload_all(self, app_context: dict = None) -> List[str]:
        """重新发现并加载所有插件

        先关闭所有插件，再重新扫描插件目录。

        Parameters
        ----------
        app_context : dict or None
            如果提供，加载完成后将调用 initialize_all

        Returns
        -------
        list[str]
            重新加载后的插件名称列表
        """
        logger.info("重新加载所有插件")
        self.shutdown_all()
        self._failed_plugins.clear()
        discovered = self.discover_plugins()

        if app_context is not None:
            self.initialize_all(app_context)

        return discovered

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def __len__(self) -> int:
        """已加载插件数量"""
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        """检查插件是否已加载"""
        return name in self._plugins

    def __iter__(self):
        """迭代所有插件实例"""
        for name in self._plugin_order:
            if name in self._plugins:
                yield self._plugins[name]

    def __repr__(self):
        return (f"PluginManager(loaded={len(self._plugins)}, "
                f"failed={len(self._failed_plugins)}, "
                f"dir={self.plugin_dir!r})")
