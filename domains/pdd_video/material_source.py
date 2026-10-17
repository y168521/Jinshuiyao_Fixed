# -*- coding: utf-8 -*-
"""素材登记与授权管理（harvest 产出的落地环节）。

为什么必须有这个模块（不是自找麻烦）：
    拼多多官方《多多视频短剧激励活动规则 V5.0》明文「平台有权要求机构
    提供该等原创或合法有效授权的证明材料」——授权留痕是规则预留要求。
    同时 JS-20261017-04 §2.2 的一线实证：社群共享素材库因「被太多人
    用过」被平台批量清理——所以素材查重（同 md5 告警）也是风控不是洁癖。

异常处理策略：
    授权类型不合法 → ValueError；授权类素材缺凭证 → LicenseError；
    两者都拒绝登记，绝不静默放行。质检问题、重复使用、网络来源标识
    义务全部转化为 record.warnings 显式暴露，不吞不藏。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

LICENSE_TYPES = ("merchant_authorized", "platform_official", "self_shot",
                 "stock_paid", "network_flagged")

# 这几类授权必须有凭证文件路径（对应平台「有权要求提供授权证明材料」）
LICENSE_REQUIRES_EVIDENCE = ("merchant_authorized", "platform_official", "stock_paid")


class LicenseError(Exception):
    """授权材料不全，拒绝登记。"""


@dataclass(frozen=True)
class MaterialRecord:
    """一条素材的授权登记。

    network_flag_required: 网络来源素材 → True，发布时必须按平台
    《商家短视频管理规范》加「内容取材网络」标识（JS-20261017-04 §2.1）。
    warnings: 重复使用 / 质检问题 / 标识义务等显式告警，调用方必须读取。
    """

    material_id: str
    goods_id: str
    license_type: str
    evidence_path: Optional[str]
    license_expire_at: Optional[str]
    source_url: str
    md5: str
    duration_sec: float
    width: int
    height: int
    has_audio: bool
    network_flag_required: bool
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "goods_id": self.goods_id,
            "license_type": self.license_type,
            "evidence_path": self.evidence_path,
            "license_expire_at": self.license_expire_at,
            "source_url": self.source_url,
            "md5": self.md5,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "has_audio": self.has_audio,
            "network_flag_required": self.network_flag_required,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialRecord":
        return cls(
            material_id=d["material_id"],
            goods_id=d["goods_id"],
            license_type=d["license_type"],
            evidence_path=d.get("evidence_path"),
            license_expire_at=d.get("license_expire_at"),
            source_url=d.get("source_url", ""),
            md5=d["md5"],
            duration_sec=d.get("duration_sec", 0.0),
            width=d.get("width", 0),
            height=d.get("height", 0),
            has_audio=d.get("has_audio", True),
            network_flag_required=d.get("network_flag_required", False),
            warnings=tuple(d.get("warnings", ())),
        )


class MaterialRegistry:
    """素材登记簿：授权校验 + 查重 + 到期停用 + 持久化。"""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path
        self.records: List[MaterialRecord] = []
        self._md5_index = set()

    def register(self, goods_id: str, license_type: str, evidence_path: Optional[str],
                 license_expire_at: Optional[str], source_url: str, asset) -> MaterialRecord:
        if license_type not in LICENSE_TYPES:
            raise ValueError("未知授权类型: %r（合法值 %s）" % (license_type, LICENSE_TYPES))
        if license_type in LICENSE_REQUIRES_EVIDENCE and not evidence_path:
            raise LicenseError(
                "%s 类素材必须登记授权凭证路径（平台有权要求提供授权证明材料）"
                % license_type)

        warnings: List[str] = []
        network_flag = license_type == "network_flagged"
        if network_flag:
            warnings.append("network_source_requires_flag")
        if asset.md5 in self._md5_index:
            # 不拒绝，但显式告警：同素材复用=同质化风险（素材库被清理的教训）
            warnings.append("duplicate_material")
        for issue in getattr(asset, "quality_issues", ()) or ():
            warnings.append("quality:%s" % issue)

        rec = MaterialRecord(
            material_id=asset.md5[:12],
            goods_id=goods_id,
            license_type=license_type,
            evidence_path=evidence_path,
            license_expire_at=license_expire_at,
            source_url=source_url,
            md5=asset.md5,
            duration_sec=asset.duration_sec,
            width=asset.width,
            height=asset.height,
            has_audio=asset.has_audio,
            network_flag_required=network_flag,
            warnings=tuple(warnings),
        )
        self.records.append(rec)
        self._md5_index.add(asset.md5)
        return rec

    def is_duplicate(self, md5: str) -> bool:
        return md5 in self._md5_index

    def expired_records(self, today: str) -> List[MaterialRecord]:
        """到期素材（ISO 日期字符串可直接比较）。today 形如 2026-10-17。"""
        return [r for r in self.records
                if r.license_expire_at and r.license_expire_at < today]

    def save(self) -> None:
        if not self.storage_path:
            raise ValueError("未配置 storage_path，无法持久化")
        Path(self.storage_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as fh:
            for rec in self.records:
                fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> None:
        if not self.storage_path:
            raise ValueError("未配置 storage_path，无法加载")
        p = Path(self.storage_path)
        if not p.exists():
            return
        self.records = []
        self._md5_index = set()
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = MaterialRecord.from_dict(json.loads(line))
                self.records.append(rec)
                self._md5_index.add(rec.md5)
