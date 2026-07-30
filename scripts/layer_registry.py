# -*- coding: utf-8 -*-
"""数据三层隔离 · 分层归属契约中心（T01 · 纯标准库）

职责（对应设计 docs/数据三层隔离_架构设计与任务分解.md）：
  - 定义 活(LIVE) / 副本(REPLICA) / 保险(INSURANCE) 三层边界。
  - 维护「活层可写白名单 / 租约文件清单 / 保险层受保护清单 / 备份条目清单 / 频率档」。
  - 提供 classify / is_lease_required / is_live_writable / get_backup_entries /
    get_freq_tier / classify_demo_real 等查询。
  - 提供统一的 fail-safe 告警入口 write_alert（写入 金水谣数据/log/isolation_alerts.log，
    带 [G] 标记），任何异常都静默吞掉，绝不向上抛。

铁律：
  - 零新依赖，仅标准库（os/re/sys/datetime/enum/dataclasses）。
  - 演示/真实铁律：真实数据(*_real*)归保险层关注、演示/补充(*_demo*/*_supplemented*)归活层派生。
"""
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

PROJECT_ROOT = os.path.dirname(_THIS_DIR)                       # Jinshuiyao_Fixed
JINSHUIYAO_DATA_DIR = os.path.join(PROJECT_ROOT, "金水谣数据")
INSURANCE_DIR = os.path.join(JINSHUIYAO_DATA_DIR, "insurance")
REPLICA_DIR = os.path.join(JINSHUIYAO_DATA_DIR, "backups")


class Layer(Enum):
    """三层之一。"""
    LIVE = "live"            # 活层：运行时高频易变
    REPLICA = "replica"      # 副本层：周期快照（派生）
    INSURANCE = "insurance"  # 保险层：版本化真源 / 受控归档


@dataclass
class FileEntry:
    """单条文件归属契约。"""
    rel_path: str             # 相对项目根，如 "金水谣数据/brain_state.json"
    layer: Layer
    freq_tier: str = "none"  # "hourly" | "daily" | "weekly" | "none"
    lease_required: bool = False
    git_tracked: bool = False


# —— 活层可写白名单（运行时代码允许直接写的路径；其余活层路径按
#      「金水谣数据/ 或 knowledge/ 前缀」默认可写，见 is_live_writable）——
LIVE_WRITABLE_WHITELIST = [
    "金水谣数据/brain_state.json",
    "金水谣数据/predictions.json",
    "金水谣数据/correlation_matrix.json",
    "金水谣数据/reference_pool.json",
    "金水谣数据/risk_state.json",
    "金水谣数据/free_model_status.json",
    "金水谣数据/lottery_health_report.json",
    "金水谣数据/log/ai_decisions.md",
    "金水谣数据/log/经验收集箱.md",
    "knowledge/用户知识库/",
]

# —— 租约文件清单（共享高频写，写前必须 acquire 全局 CLAIM）——
LEASE_REQUIRED_FILES = [
    "金水谣数据/log/ai_decisions.md",     # 决策卡
    "金水谣数据/log/经验收集箱.md",        # 经验箱
    "金水谣数据/brain_state.json",
    "金水谣数据/predictions.json",
    "knowledge/用户知识库/",                # 知识库/经验箱（共享高频写）
]

# —— 保险层受保护清单（活层运行时代码只读，禁止写入）——
INSURANCE_PROTECTED = [
    "金水谣数据/insurance/",               # 受控脚本写、活层只读
    "金水谣数据/risk_register.json",        # 保险层真源
    "jinshuiyao/data/matches_real.csv",    # 真实数据真源
    "AGENTS.md",
    "启动提示词.txt",
    "docs/",
    "config/",
    "scripts/",
]

# —— 备份条目清单（活层 → 副本层周期快照）——
_BACKUP_ENTRIES = [
    FileEntry("金水谣数据/brain_state.json", Layer.LIVE, "hourly", True, False),
    FileEntry("金水谣数据/predictions.json", Layer.LIVE, "daily", True, False),   # 大文件降频
    FileEntry("金水谣数据/log/ai_decisions.md", Layer.LIVE, "hourly", True, False),
    FileEntry("金水谣数据/log/经验收集箱.md", Layer.LIVE, "hourly", True, False),
    FileEntry("knowledge/用户知识库/", Layer.LIVE, "daily", True, False),
]

# 频率档默认滚动保留窗口
DEFAULT_RETENTION = {"hourly": 24, "daily": 7, "weekly": 4}

# 演示/真实命名后缀（演示/真实铁律）
_REAL_PATTERN = re.compile(r"(^|[/\\])([^/\\]*_real([^/\\]*)?)$")
_DEMO_PATTERN = re.compile(r"(^|[/\\])([^/\\]*_(demo|supplemented)([^/\\]*)?)$")


def _norm(rel_path):
    """统一为正斜杠相对路径。"""
    return rel_path.replace("\\", "/")


def write_alert(message, level="[G]"):
    """统一的 fail-safe 告警入口（默认 [G] 告警，不阻断主流程）。

    写入 金水谣数据/log/isolation_alerts.log（可用环境变量 ISOLATION_ALERT_LOG 重定向，
    便于测试）。任何异常都静默吞掉，绝不向上抛。
    """
    try:
        log_path = os.environ.get("ISOLATION_ALERT_LOG") or os.path.join(
            JINSHUIYAO_DATA_DIR, "log", "isolation_alerts.log"
        )
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = "%s %s | isolation | %s\n" % (level, ts, message)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


class LayerRegistry:
    """分层归属契约中心。"""

    LIVE_WRITABLE_WHITELIST = LIVE_WRITABLE_WHITELIST
    LEASE_REQUIRED_FILES = LEASE_REQUIRED_FILES
    INSURANCE_PROTECTED = INSURANCE_PROTECTED

    def __init__(self, backup_entries=None):
        self._backup_entries = list(backup_entries) if backup_entries else list(_BACKUP_ENTRIES)

    # —— 分类 ——
    def classify(self, rel_path):
        """返回路径所属层（活/副本/保险）。"""
        p = _norm(rel_path)
        if p.startswith("金水谣数据/backups/"):
            return Layer.REPLICA
        for pref in self.INSURANCE_PROTECTED:
            pref = _norm(pref)
            if p == pref or p.startswith(pref):
                return Layer.INSURANCE
        if p.endswith(".py") or p.endswith(".toml") or p.endswith(".cfg") or p.endswith(".ini"):
            return Layer.INSURANCE
        return Layer.LIVE

    def is_insurance(self, rel_path):
        """路径是否属保险层。"""
        return self.classify(rel_path) == Layer.INSURANCE

    # —— 租约 ——
    def is_lease_required(self, rel_path):
        """路径是否属共享高频写（须先 acquire 租约）。"""
        p = _norm(rel_path)
        for e in self.LEASE_REQUIRED_FILES:
            e = _norm(e)
            if p == e or (e.endswith("/") and p.startswith(e)):
                return True
        return False

    # —— 活层可写性 ——
    def is_live_writable(self, rel_path):
        """活层运行时代码能否写该路径。

        保险层 / 副本层 → False 并 [G] 告警；
        活层已知白名单或「金水谣数据/」「knowledge/」前缀 → True；
        其余未授权路径 → False 并 [G] 告警（PRD-17-P0-3）。
        """
        p = _norm(rel_path)
        layer = self.classify(p)
        if layer == Layer.INSURANCE:
            write_alert("活层写入保险层路径被拒绝: %s" % p)
            return False
        if layer == Layer.REPLICA:
            write_alert("活层写入副本层路径被拒绝: %s" % p)
            return False
        if p in [_norm(x) for x in self.LIVE_WRITABLE_WHITELIST]:
            return True
        if p.startswith("金水谣数据/") or p.startswith("knowledge/"):
            return True
        write_alert("活层写入未授权路径被拒绝: %s" % p)
        return False

    # —— 备份清单 / 频率档 ——
    def get_backup_entries(self):
        """返回备份条目清单（副本）。"""
        return list(self._backup_entries)

    def get_freq_tier(self, rel_path):
        """返回某路径的备份频率档（hourly/daily/weekly/none）。"""
        p = _norm(rel_path)
        for e in self._backup_entries:
            if _norm(e.rel_path) == p:
                return e.freq_tier
        for e in self._backup_entries:       # 目录条目前缀匹配
            ep = _norm(e.rel_path)
            if ep.endswith("/") and p.startswith(ep):
                return e.freq_tier
        return "none"

    # —— 演示 / 真实铁律 ——
    def classify_demo_real(self, rel_path):
        """返回 'real' / 'demo' / 'unknown'（命名合规校验）。"""
        base = os.path.basename(_norm(rel_path))
        if _REAL_PATTERN.search(base):
            return "real"
        if _DEMO_PATTERN.search(base):
            return "demo"
        return "unknown"

    def is_real_data(self, rel_path):
        return self.classify_demo_real(rel_path) == "real"

    def is_demo_data(self, rel_path):
        return self.classify_demo_real(rel_path) == "demo"


# 进程级默认契约单例
DEFAULT_REGISTRY = LayerRegistry()


if __name__ == "__main__":
    import json
    reg = DEFAULT_REGISTRY
    samples = [
        "金水谣数据/brain_state.json",
        "金水谣数据/backups/hourly/x/y.bak",
        "金水谣数据/insurance/decisions.json",
        "scripts/layer_registry.py",
        "jinshuiyao/data/matches_real.csv",
        "knowledge/用户知识库/foo.md",
    ]
    print(json.dumps(
        {s: {"layer": reg.classify(s).value,
         "lease": reg.is_lease_required(s),
         "live_writable": reg.is_live_writable(s),
         "freq": reg.get_freq_tier(s)}
         for s in samples},
        ensure_ascii=False, indent=2,
    ))
