# -*- coding: utf-8 -*-
"""
金水谣系统 - L0启动自检模块

在系统启动时自动检测所有关键组件的健康状态，包括：
  - 依赖检查：Python版本、关键标准库与第三方库
  - 数据完整性检查：核心目录与数据文件的可读性/可解析性
  - 配置一致性检查：彩种数量、配置文件加载、目录权限
  - 智能大脑检查：版本号、学习状态关键字段

支持自愈机制：自动创建缺失目录、从备份恢复损坏文件、必要时重建空数据文件。
"""

import os
import sys
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 导入项目内部依赖
# ---------------------------------------------------------------------------
try:
    from config import BASE_DIR, DATA_SAVE, LOTTERY_RULES, CONFIG_RULE_PATH
except ImportError as e:
    logger.error("无法导入 config 模块: %s", e)
    raise

try:
    from utils.safe_json import safe_load_json, check_file_health
except ImportError as e:
    logger.warning("无法导入 utils.safe_json 模块，将使用基础JSON读取作为降级方案: %s", e)
    safe_load_json = None
    check_file_health = None


# ---------------------------------------------------------------------------
# 默认空数据模板（用于自愈重建）
# ---------------------------------------------------------------------------
_EMPTY_PREDICTIONS = {"predictions": {}, "last_update": ""}
_EMPTY_BRAIN_STATE = {
    "version": 1,
    "total_reviews": 0,
    "strategy_weights": {},
    "digit_bias": {},
    "confidence": 0.5,
}
_EMPTY_MIROFISH_DB = {}


# ---------------------------------------------------------------------------
# HealthChecker 主类
# ---------------------------------------------------------------------------
class HealthChecker:
    """金水谣系统 L0 启动自检器"""

    def __init__(self):
        self.checks = []
        self._data_dir = BASE_DIR
        self._lot_data_dir = DATA_SAVE
        self._predictions_path = os.path.join(self._data_dir, "predictions.json")
        self._brain_state_path = os.path.join(self._data_dir, "brain_state.json")
        self._mirofish_db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "knowledge", "mirofish_db.json"
        )
        self._rule_config_path = CONFIG_RULE_PATH

    # ===================================================================
    # 公共接口
    # ===================================================================

    def run_all_checks(self) -> dict:
        """执行全部自检，返回结构化报告字典"""
        self.checks = []

        logger.info("=" * 50)
        logger.info("金水谣系统 L0 启动自检开始")
        logger.info("=" * 50)

        self._check_dependencies()
        self._check_data_integrity()
        self._check_config_consistency()
        self._check_brain()

        summary = {"pass": 0, "warn": 0, "fail": 0}
        for chk in self.checks:
            summary[chk["status"]] = summary.get(chk["status"], 0) + 1

        if summary["fail"] > 0:
            overall = "critical"
        elif summary["warn"] > 0:
            overall = "degraded"
        else:
            overall = "healthy"

        report = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall": overall,
            "checks": self.checks,
            "summary": summary,
        }

        logger.info("L0 自检完成: %s (通过=%d, 警告=%d, 失败=%d)",
                     overall, summary["pass"], summary["warn"], summary["fail"])
        return report

    # ===================================================================
    # 1. 依赖检查 (dependency)
    # ===================================================================

    def _check_dependencies(self):
        """检查运行环境依赖"""

        # --- Python版本 ---
        try:
            py_ver = sys.version_info
            if py_ver >= (3, 7):
                self._add_check("dependency", "pass",
                                "Python版本",
                                f"Python {py_ver.major}.{py_ver.minor} (满足 >= 3.7 要求)")
            else:
                self._add_check("dependency", "fail",
                                "Python版本",
                                f"Python {py_ver.major}.{py_ver.minor} 不满足最低版本要求 3.7",
                                action="请升级 Python 到 3.7 或更高版本")
        except Exception as e:
            self._add_check("dependency", "fail", "Python版本",
                            f"检测Python版本时异常: {e}", action="请检查Python安装")

        # --- tkinter ---
        try:
            import tkinter
            self._add_check("dependency", "pass", "tkinter", "tkinter 模块可用")
        except ImportError as e:
            self._add_check("dependency", "fail", "tkinter",
                            f"tkinter 不可用: {e}",
                            action="GUI功能不可用，请安装 tkinter (Linux: apt install python3-tk)")

        # --- requests ---
        try:
            import requests
            self._add_check("dependency", "pass", "requests", "requests 模块可用")
        except ImportError as e:
            self._add_check("dependency", "fail", "requests",
                            f"requests 不可用: {e}",
                            action="网络数据抓取功能不可用，请执行 pip install requests")

        # --- 标准库: json, os, threading ---
        std_libs = {"json": json, "os": os}
        try:
            import threading
            std_libs["threading"] = threading
        except ImportError:
            pass

        for name, mod in std_libs.items():
            if mod is not None:
                self._add_check("dependency", "pass", name, f"{name} 标准库可用")
            else:
                self._add_check("dependency", "fail", name,
                                f"{name} 标准库不可用",
                                action="Python环境异常，请重新安装Python")

        # --- utils.safe_json ---
        if safe_load_json is not None and check_file_health is not None:
            self._add_check("dependency", "pass", "utils.safe_json",
                            "safe_json 数据安全模块可用")
        else:
            self._add_check("dependency", "warn", "utils.safe_json",
                            "safe_json 模块不可用，将使用基础JSON读取降级方案",
                            action="建议修复 utils/safe_json.py 以获得数据安全保护")

    # ===================================================================
    # 2. 数据完整性检查 (data)
    # ===================================================================

    def _check_data_integrity(self):
        """检查核心数据目录和文件的完整性"""

        # --- 金水谣数据/ 目录 ---
        try:
            if os.path.isdir(self._data_dir):
                self._add_check("data", "pass", "金水谣数据目录",
                                f"目录存在: {self._data_dir}")
            else:
                os.makedirs(self._data_dir, exist_ok=True)
                self._add_check("data", "warn", "金水谣数据目录",
                                f"目录不存在，已自动创建: {self._data_dir}",
                                action="目录已自动创建，首次运行属正常情况")
        except Exception as e:
            self._add_check("data", "fail", "金水谣数据目录",
                            f"目录不存在且自动创建失败: {e}",
                            action=f"请手动创建目录 {self._data_dir}")

        # --- 金水谣数据/lot_data/ 目录 ---
        try:
            if os.path.isdir(self._lot_data_dir):
                self._add_check("data", "pass", "lot_data目录",
                                f"目录存在: {self._lot_data_dir}")
            else:
                os.makedirs(self._lot_data_dir, exist_ok=True)
                self._add_check("data", "warn", "lot_data目录",
                                f"目录不存在，已自动创建: {self._lot_data_dir}",
                                action="目录已自动创建，首次运行属正常情况")
        except Exception as e:
            self._add_check("data", "fail", "lot_data目录",
                            f"目录不存在且自动创建失败: {e}",
                            action=f"请手动创建目录 {self._lot_data_dir}")

        # --- predictions.json ---
        self._check_json_file("predictions.json", self._predictions_path,
                              _EMPTY_PREDICTIONS)

        # --- brain_state.json ---
        self._check_json_file("brain_state.json", self._brain_state_path,
                              _EMPTY_BRAIN_STATE)

        # --- mirofish_db.json ---
        self._check_json_file("mirofish_db.json", self._mirofish_db_path,
                              _EMPTY_MIROFISH_DB)

    def _check_json_file(self, display_name, filepath, empty_template):
        """
        检查单个JSON数据文件的完整性与可解析性。
        支持自愈：尝试从备份恢复，备份也损坏则重建空文件。
        """
        try:
            # 文件是否存在
            if not os.path.isfile(filepath):
                self._add_check("data", "fail", display_name,
                                f"文件不存在: {filepath}",
                                action="将尝试重建空数据文件")
                self._rebuild_file(filepath, empty_template, display_name)
                return

            # 使用 safe_load_json 检查可读性和可解析性
            if safe_load_json is not None:
                data = safe_load_json(filepath)
            else:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

            if data is not None and isinstance(data, dict):
                self._add_check("data", "pass", display_name,
                                f"文件可读且JSON解析正常: {display_name}")
            else:
                self._add_check("data", "warn", display_name,
                                f"文件可读但内容为空或格式异常: {display_name}",
                                action="建议检查文件内容")
        except json.JSONDecodeError as e:
            self._add_check("data", "fail", display_name,
                            f"JSON解析失败: {e} (文件: {filepath})",
                            action="将尝试从备份恢复或重建")
            self._try_recover_or_rebuild(filepath, empty_template, display_name)
        except Exception as e:
            self._add_check("data", "fail", display_name,
                            f"读取文件异常: {e} (文件: {filepath})",
                            action="将尝试从备份恢复或重建")
            self._try_recover_or_rebuild(filepath, empty_template, display_name)

    # ===================================================================
    # 3. 配置一致性检查 (config)
    # ===================================================================

    def _check_config_consistency(self):
        """检查配置项的一致性"""

        # --- LOTTERY_RULES 有7个彩种 ---
        try:
            count = len(LOTTERY_RULES)
            if count == 7:
                self._add_check("config", "pass", "彩种数量",
                                f"LOTTERY_RULES 包含 {count} 个彩种，符合预期")
            else:
                self._add_check("config", "warn", "彩种数量",
                                f"LOTTERY_RULES 包含 {count} 个彩种，预期为7个",
                                action="请检查 config.py 中的 LOTTERY_RULES 定义")
        except Exception as e:
            self._add_check("config", "fail", "彩种数量",
                            f"检查LOTTERY_RULES时异常: {e}",
                            action="请检查 config.py 是否正确")

        # --- rule_config.json 如果存在可正常加载 ---
        try:
            if os.path.isfile(self._rule_config_path):
                with open(self._rule_config_path, "r", encoding="utf-8") as f:
                    _ = json.load(f)
                self._add_check("config", "pass", "rule_config.json",
                                "配置文件存在且可正常加载")
            else:
                self._add_check("config", "pass", "rule_config.json",
                                "配置文件不存在（可选配置，属正常情况）")
        except json.JSONDecodeError as e:
            self._add_check("config", "fail", "rule_config.json",
                            f"配置文件JSON解析失败: {e}",
                            action=f"请检查 {self._rule_config_path} 文件内容是否为合法JSON")
        except Exception as e:
            self._add_check("config", "fail", "rule_config.json",
                            f"加载配置文件异常: {e}",
                            action=f"请检查文件 {self._rule_config_path} 的权限和内容")

        # --- 关键目录可写 ---
        writable_dirs = [
            ("金水谣数据目录", self._data_dir),
            ("lot_data目录", self._lot_data_dir),
        ]
        for dir_name, dir_path in writable_dirs:
            try:
                if os.path.isdir(dir_path):
                    test_file = os.path.join(dir_path, ".health_check_write_test")
                    with open(test_file, "w", encoding="utf-8") as f:
                        f.write("test")
                    os.remove(test_file)
                    self._add_check("config", "pass", f"{dir_name}可写",
                                    f"目录可正常写入: {dir_path}")
                else:
                    self._add_check("config", "fail", f"{dir_name}可写",
                                    f"目录不存在，无法测试写入: {dir_path}",
                                    action=f"请确保目录 {dir_path} 存在")
            except PermissionError:
                self._add_check("config", "fail", f"{dir_name}可写",
                                f"目录无写入权限: {dir_path}",
                                action=f"请检查目录 {dir_path} 的写入权限")
            except Exception as e:
                self._add_check("config", "warn", f"{dir_name}可写",
                                f"写入测试异常: {e} (目录: {dir_path})",
                                action=f"请检查目录 {dir_path} 的状态")

    # ===================================================================
    # 4. 智能大脑检查 (brain)
    # ===================================================================

    def _check_brain(self):
        """检查智能大脑状态文件的关键字段"""

        try:
            if not os.path.isfile(self._brain_state_path):
                self._add_check("brain", "fail", "智能大脑状态",
                                "brain_state.json 不存在",
                                action="系统将在数据检查阶段自动创建空状态文件")
                return

            # 加载数据
            if safe_load_json is not None:
                state = safe_load_json(self._brain_state_path)
            else:
                with open(self._brain_state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)

            if not isinstance(state, dict):
                self._add_check("brain", "fail", "智能大脑状态",
                                "brain_state.json 顶层不是字典类型",
                                action="文件格式异常，已尝试恢复")
                return

            # --- version 字段为 1 ---
            version = state.get("version")
            if version == 1:
                self._add_check("brain", "pass", "大脑版本号",
                                f"version = {version}，符合预期")
            elif version is not None:
                self._add_check("brain", "warn", "大脑版本号",
                                f"version = {version}，预期为 1，可能存在兼容性问题",
                                action="请确认 brain_state.json 的版本是否需要升级")
            else:
                self._add_check("brain", "fail", "大脑版本号",
                                "version 字段不存在",
                                action="请检查 brain_state.json 结构，必要时重建")

            # --- total_reviews 是整数 ---
            total_reviews = state.get("total_reviews")
            if isinstance(total_reviews, int):
                self._add_check("brain", "pass", "复盘总数",
                                f"total_reviews = {total_reviews}，类型正确")
            elif total_reviews is not None:
                self._add_check("brain", "warn", "复盘总数",
                                f"total_reviews = {total_reviews}，不是整数类型 (类型: {type(total_reviews).__name__})",
                                action="请修复 total_reviews 字段为整数")
            else:
                self._add_check("brain", "fail", "复盘总数",
                                "total_reviews 字段不存在",
                                action="请检查 brain_state.json 结构")

            # --- strategy_weights 存在 ---
            if "strategy_weights" in state:
                if isinstance(state["strategy_weights"], dict):
                    self._add_check("brain", "pass", "策略权重",
                                    f"strategy_weights 存在且为字典，包含 {len(state['strategy_weights'])} 项")
                else:
                    self._add_check("brain", "warn", "策略权重",
                                    f"strategy_weights 存在但类型异常: {type(state['strategy_weights']).__name__}",
                                    action="strategy_weights 应为字典类型")
            else:
                self._add_check("brain", "fail", "策略权重",
                                "strategy_weights 字段不存在",
                                action="请检查 brain_state.json 结构")

            # --- digit_bias 存在 ---
            if "digit_bias" in state:
                if isinstance(state["digit_bias"], dict):
                    self._add_check("brain", "pass", "号码偏态",
                                    f"digit_bias 存在且为字典，包含 {len(state['digit_bias'])} 项")
                else:
                    self._add_check("brain", "warn", "号码偏态",
                                    f"digit_bias 存在但类型异常: {type(state['digit_bias']).__name__}",
                                    action="digit_bias 应为字典类型")
            else:
                self._add_check("brain", "fail", "号码偏态",
                                "digit_bias 字段不存在",
                                action="请检查 brain_state.json 结构")

        except json.JSONDecodeError as e:
            self._add_check("brain", "fail", "智能大脑状态",
                            f"brain_state.json JSON解析失败: {e}",
                            action="将尝试从备份恢复或重建空状态文件")
            self._try_recover_or_rebuild(self._brain_state_path,
                                          _EMPTY_BRAIN_STATE, "brain_state.json")
        except Exception as e:
            self._add_check("brain", "fail", "智能大脑状态",
                            f"检查智能大脑时异常: {e}",
                            action="请检查 brain_state.json 文件状态")

    # ===================================================================
    # 自愈机制
    # ===================================================================

    def _try_recover_or_rebuild(self, filepath, empty_template, display_name):
        """
        尝试从备份恢复损坏的JSON文件。
        恢复失败则重建空数据文件。
        """
        recovered = False

        # 尝试从备份恢复
        try:
            backup_files = self._find_backup_files(filepath)
            for backup_path in sorted(backup_files):
                try:
                    with open(backup_path, "r", encoding="utf-8") as f:
                        backup_data = json.load(f)
                    if isinstance(backup_data, dict):
                        # 备份有效，覆盖原文件
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(backup_data, f, ensure_ascii=False, indent=2)
                        logger.info("已从备份恢复 %s: %s", display_name, backup_path)
                        self._add_check("data", "warn", f"{display_name}自愈",
                                        f"文件已损坏，已从备份 {backup_path} 成功恢复",
                                        action="数据可能丢失部分近期更新，请核实")
                        recovered = True
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if not recovered:
            self._rebuild_file(filepath, empty_template, display_name)

    def _rebuild_file(self, filepath, empty_template, display_name):
        """用空模板重建数据文件"""
        try:
            parent_dir = os.path.dirname(filepath)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(empty_template, f, ensure_ascii=False, indent=2)
            logger.warning("已重建空数据文件: %s", filepath)
            self._add_check("data", "warn", f"{display_name}重建",
                            f"文件不存在或损坏且无可用备份，已用空模板重建: {filepath}",
                            action="数据已重置为初始状态，历史数据已丢失")
        except Exception as e:
            self._add_check("data", "fail", f"{display_name}重建",
                            f"重建空文件失败: {e}",
                            action=f"请手动检查文件 {filepath} 的父目录权限")

    @staticmethod
    def _find_backup_files(filepath):
        """
        查找文件的备份版本。
        备份文件命名约定: <原文件名>.bak, <原文件名>.bak.1, <原文件名>.bak.2 等。
        """
        backups = []
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)

        if not directory:
            return backups

        for entry in os.listdir(directory):
            # 匹配 .bak, .bak.1, .bak.2 等备份文件
            if entry.startswith(filename + ".bak") and entry != filename:
                full_path = os.path.join(directory, entry)
                if os.path.isfile(full_path):
                    backups.append(full_path)

        return backups

    # ===================================================================
    # 内部工具方法
    # ===================================================================

    def _add_check(self, category, status, name, message, action=None):
        """添加一条检查记录"""
        record = {
            "name": name,
            "category": category,
            "status": status,
            "message": message,
        }
        if action is not None:
            record["action"] = action
        self.checks.append(record)

        # 按级别输出日志
        if status == "pass":
            logger.debug("[PASS] %s - %s", name, message)
        elif status == "warn":
            logger.warning("[WARN] %s - %s", name, message)
        else:
            logger.error("[FAIL] %s - %s", name, message)


# ---------------------------------------------------------------------------
# 公共报告工具函数
# ---------------------------------------------------------------------------

def format_report(report: dict) -> str:
    """
    将结构化报告格式化为可读文本。

    参数:
        report: run_all_checks() 返回的报告字典

    返回:
        可读的多行文本字符串
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  金水谣系统 L0 启动自检报告")
    lines.append("=" * 60)
    lines.append(f"时间: {report['timestamp']}")
    lines.append(f"总体状态: {_status_label(report['overall'])}")
    lines.append("")

    summary = report.get("summary", {})
    lines.append(f"汇总: 通过={summary.get('pass', 0)} | 警告={summary.get('warn', 0)} | 失败={summary.get('fail', 0)}")
    lines.append("")

    # 按类别分组输出
    category_titles = {
        "dependency": "依赖检查",
        "data": "数据完整性",
        "config": "配置一致性",
        "brain": "智能大脑",
    }

    current_category = None
    for chk in report.get("checks", []):
        cat = chk["category"]
        if cat != current_category:
            current_category = cat
            lines.append("-" * 40)
            lines.append(f" [{category_titles.get(cat, cat)}]")
            lines.append("-" * 40)

        status_icon = {"pass": "OK", "warn": "!!", "fail": "XX"}[chk["status"]]
        lines.append(f"  [{status_icon}] {chk['name']}")
        lines.append(f"       {chk['message']}")
        if "action" in chk:
            lines.append(f"       >> {chk['action']}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def get_critical_issues(report: dict) -> list:
    """
    从报告中提取所有失败项。

    参数:
        report: run_all_checks() 返回的报告字典

    返回:
        仅包含 status 为 fail 的检查项列表
    """
    return [chk for chk in report.get("checks", []) if chk["status"] == "fail"]


def _status_label(status: str) -> str:
    """将状态码转为中文标签"""
    return {"healthy": "正常", "degraded": "降级运行", "critical": "严重异常"}.get(status, status)


# ---------------------------------------------------------------------------
# 快速自检入口（供 main.py 调用）
# ---------------------------------------------------------------------------

def run_health_check() -> dict:
    """
    执行一次完整的系统自检并返回报告。
    此为便捷入口函数，供 main.py 启动时直接调用。

    返回:
        结构化报告字典
    """
    checker = HealthChecker()
    return checker.run_all_checks()
