# -*- coding: utf-8 -*-
"""JS-20261017-04 · 素材登记与授权管理测试（先证它红：本文件先于实现落地）

对应交付物 JS-20261017-04 §六：harvest 的产出必须绑定授权登记——
拼多多官方规则明文「有权要求提供合法有效授权的证明材料」（短剧激励规则 V5.0），
所以授权凭证留痕不是自找麻烦，是规则预留要求。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from domains.pdd_video.material_source import (  # noqa: E402
    LICENSE_REQUIRES_EVIDENCE,
    LICENSE_TYPES,
    LicenseError,
    MaterialRecord,
    MaterialRegistry,
)


def _asset(md5="a" * 32, duration=30.0, width=1080, height=1920,
           has_audio=True, issues=()):
    from domains.pdd_video.harvest import NormalizedAsset

    return NormalizedAsset(path="/tmp/x.mp4", md5=md5, size_bytes=1024,
                           duration_sec=duration, width=width, height=height,
                           has_audio=has_audio, quality_issues=tuple(issues))


def _load_fresh(path):
    """exec 沙箱加载：绕开 pyc；exec 期间临时注册 sys.modules
    （dataclass 字符串注解解析需要），用完即摘。撤销验证专用。"""
    import types

    src = open(path, encoding="utf-8").read()
    mod = types.ModuleType("module_under_test")
    mod.__file__ = path
    sys.modules["module_under_test"] = mod
    try:
        exec(compile(src, path, "exec"), mod.__dict__)
    finally:
        sys.modules.pop("module_under_test", None)
    return mod


class TestRegister:
    def test_register_self_shot_ok(self, tmp_path):
        reg = MaterialRegistry()
        rec = reg.register(goods_id="G1", license_type="self_shot",
                           evidence_path=None, license_expire_at=None,
                           source_url="local", asset=_asset())
        assert rec.material_id == "a" * 12
        assert rec.network_flag_required is False

    def test_authorized_without_evidence_rejected(self):
        reg = MaterialRegistry()
        with pytest.raises(LicenseError):
            reg.register(goods_id="G1", license_type="merchant_authorized",
                         evidence_path=None, license_expire_at=None,
                         source_url="local", asset=_asset())

    def test_authorized_with_evidence_ok(self, tmp_path):
        ev = tmp_path / "auth.png"
        ev.write_bytes(b"x")
        reg = MaterialRegistry()
        rec = reg.register(goods_id="G1", license_type="merchant_authorized",
                           evidence_path=str(ev), license_expire_at="2027-01-01",
                           source_url="local", asset=_asset())
        assert rec.evidence_path == str(ev)

    def test_network_flagged_forces_label_warning(self):
        reg = MaterialRegistry()
        rec = reg.register(goods_id="G1", license_type="network_flagged",
                           evidence_path=None, license_expire_at=None,
                           source_url="http://x/v.mp4", asset=_asset())
        assert rec.network_flag_required is True
        assert "network_source_requires_flag" in rec.warnings

    def test_unknown_license_type_rejected(self):
        reg = MaterialRegistry()
        with pytest.raises(ValueError):
            reg.register(goods_id="G1", license_type="stolen",
                         evidence_path=None, license_expire_at=None,
                         source_url="local", asset=_asset())

    def test_duplicate_material_warns_not_silent(self):
        reg = MaterialRegistry()
        reg.register(goods_id="G1", license_type="self_shot", evidence_path=None,
                     license_expire_at=None, source_url="local", asset=_asset())
        rec2 = reg.register(goods_id="G1", license_type="self_shot",
                            evidence_path=None, license_expire_at=None,
                            source_url="local", asset=_asset())
        assert "duplicate_material" in rec2.warnings
        assert reg.is_duplicate("a" * 32)

    def test_quality_issues_surface_in_record(self):
        reg = MaterialRegistry()
        rec = reg.register(goods_id="G1", license_type="self_shot",
                           evidence_path=None, license_expire_at=None,
                           source_url="local",
                           asset=_asset(issues=("no_audio_track",)))
        assert "quality:no_audio_track" in rec.warnings


class TestExpiry:
    def test_expired_detected_by_iso_date(self):
        reg = MaterialRegistry()
        reg.register(goods_id="G1", license_type="self_shot", evidence_path=None,
                     license_expire_at="2026-10-01", source_url="local",
                     asset=_asset())
        expired = reg.expired_records(today="2026-10-17")
        assert len(expired) == 1
        assert reg.expired_records(today="2026-09-30") == []

    def test_no_expiry_never_expires(self):
        reg = MaterialRegistry()
        reg.register(goods_id="G1", license_type="self_shot", evidence_path=None,
                     license_expire_at=None, source_url="local", asset=_asset())
        assert reg.expired_records(today="2099-01-01") == []


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        p = tmp_path / "materials.jsonl"
        reg = MaterialRegistry(storage_path=str(p))
        reg.register(goods_id="G1", license_type="self_shot", evidence_path=None,
                     license_expire_at="2027-01-01", source_url="local",
                     asset=_asset())
        reg.save()
        reg2 = MaterialRegistry(storage_path=str(p))
        reg2.load()
        assert reg2.is_duplicate("a" * 32)
        assert len(reg2.records) == 1


class TestRuleTables:
    def test_license_tables_not_empty(self):
        assert len(LICENSE_TYPES) >= 5
        assert len(LICENSE_REQUIRES_EVIDENCE) >= 2

    def test_scan_finds_all_tables(self):
        import domains.pdd_video.material_source as mod

        found = [n for n in dir(mod) if n.isupper() and isinstance(getattr(mod, n), tuple)]
        assert len(found) >= 2, "扫描口径只找到 %d 张表: %s" % (len(found), found)


class TestReverseVerification:
    def test_reverse_verification_evidence_gate(self):
        """撤销验证：清空 LICENSE_REQUIRES_EVIDENCE → 无凭证授权必须被放行
        （证明拒绝确实来自这张表）→ 恢复后重新加载，必须重新拒绝。

        用 exec 沙箱加载（不碰 sys.modules/pyc，避开时间戳 staleness）。
        """
        import hashlib

        import domains.pdd_video.material_source as mod

        path = mod.__file__
        original = open(path, "rb").read()
        md5_before = hashlib.md5(original).hexdigest()
        patched = original.replace(
            b'LICENSE_REQUIRES_EVIDENCE = ("merchant_authorized", "platform_official", "stock_paid")',
            b'LICENSE_REQUIRES_EVIDENCE = ()',
        )
        assert patched != original, "撤销验证注入点没匹配上"
        try:
            open(path, "wb").write(patched)
            ns = _load_fresh(path)
            rec = ns.MaterialRegistry().register(
                goods_id="G1", license_type="merchant_authorized",
                evidence_path=None, license_expire_at=None,
                source_url="local", asset=_asset())
            assert rec is not None, "表已清空却仍拒绝，说明拒绝不来自这张表"
        finally:
            open(path, "wb").write(original)
            assert hashlib.md5(open(path, "rb").read()).hexdigest() == md5_before
        ns2 = _load_fresh(path)
        try:
            ns2.MaterialRegistry().register(
                goods_id="G1", license_type="merchant_authorized",
                evidence_path=None, license_expire_at=None,
                source_url="local", asset=_asset())
            raise AssertionError("恢复后无凭证授权竟然被放行")
        except ns2.LicenseError:
            pass
