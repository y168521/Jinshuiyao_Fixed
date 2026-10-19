# -*- coding: utf-8 -*-
"""告警中枢 utils/alert_hub.py 单元测试（JS-20261020-02）

守住三件事：
    1. 去重/冷却真的生效（同一根因不重复打扰）——否则告警风暴会让人彻底无视告警
    2. 被冷却的告警**仍完整落盘**（降噪不得制造盲区，flashlog Step3 硬性要求）
    3. 分级路由正确：CRITICAL 弹窗、WARN 进摘要不打扰；弹窗失败必须可见
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils import alert_hub  # noqa: E402


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """把落盘路径重定向到临时目录，避免污染真实告警日志。"""
    monkeypatch.setattr(alert_hub, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(alert_hub, "ALERT_LOG", str(tmp_path / "alert_hub.jsonl"))
    monkeypatch.setattr(alert_hub, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(alert_hub, "DIGEST_FILE", str(tmp_path / "digest.json"))
    calls = []
    monkeypatch.setattr(alert_hub, "popup",
                        lambda t, m, timeout_ms=5000: (calls.append((t, m)) or True))
    return calls


class TestFingerprint:
    def test_stable_and_distinct(self):
        a = alert_hub.fingerprint("自动同步", "缺留痕")
        b = alert_hub.fingerprint("自动同步", "缺留痕")
        c = alert_hub.fingerprint("自动同步", "网络失败")
        assert a == b, "同一根因必须同指纹（否则去重失效）"
        assert a != c, "不同根因必须不同指纹（否则误抑制）"


class TestDedupAndCooldown:
    def test_second_same_alert_is_suppressed(self, hub):
        r1 = alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "补三件套")
        r2 = alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "补三件套")
        assert r1["suppressed"] is False
        assert r2["suppressed"] is True, "冷却窗口内必须抑制，否则就是告警风暴"
        assert len(hub) == 1, "只应弹一次窗"

    def test_suppressed_alert_still_logged(self, hub):
        """降噪不得制造盲区：被抑制的告警仍要落盘可查。"""
        alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "")
        alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "")
        rows = alert_hub.recent()
        assert len(rows) == 2, "被冷却的告警也必须完整落盘"
        assert rows[-1]["suppressed"] is True

    def test_different_signature_not_suppressed(self, hub):
        alert_hub.alert("CRITICAL", "巡检", "AST P0", "修P0")
        r = alert_hub.alert("CRITICAL", "巡检", "一致性失败", "拷回根镜像")
        assert r["suppressed"] is False, "不同根因不应互相抑制"

    def test_cooldown_expiry_re_alerts(self, hub, monkeypatch):
        """冷却到期后必须能再次告警（不能永久静音）。"""
        alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "")
        # 把状态时间往前推 1 小时，模拟冷却过期
        st = alert_hub._load_state()
        for k in st:
            st[k] -= 3600
        alert_hub._save_state(st)
        r = alert_hub.alert("CRITICAL", "自动同步", "缺留痕", "")
        assert r["suppressed"] is False, "冷却过期后应重新告警（永久静音＝假告警系统）"


class TestLevelRouting:
    def test_critical_pops_up(self, hub):
        alert_hub.alert("CRITICAL", "巡检", "数据缺失", "重跑抓取")
        assert len(hub) == 1, "CRITICAL 必须弹窗"
        assert "CRITICAL" in hub[0][0]

    def test_warn_goes_to_digest_not_popup(self, hub):
        alert_hub.alert("WARN", "健康看门狗", "资产陈旧", "重跑构建")
        assert len(hub) == 0, "WARN 不应立即打扰"
        # 但必须进每日摘要（兜底）
        with open(alert_hub.DIGEST_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        assert len(d["items"]) == 1, "WARN 必须进每日摘要，否则等于没报"

    def test_info_never_pops(self, hub):
        alert_hub.alert("INFO", "巡检", "耗时略增", "观察")
        assert len(hub) == 0

    def test_unknown_level_falls_back_to_warn(self, hub):
        r = alert_hub.alert("NOPE", "巡检", "x", "")
        assert r["level"] == "WARN", "未知级别应降级为 WARN 而非抛异常"


class TestPopupFailureIsVisible:
    def test_popup_failure_emits_stderr(self, hub, monkeypatch, capsys):
        """弹窗失败必须可见——否则 CRITICAL 等于没发出去（静默失败的经典形态）。"""
        monkeypatch.setattr(alert_hub, "popup", lambda *a, **k: False)
        alert_hub.alert("CRITICAL", "巡检", "严重故障", "立即处理")
        err = capsys.readouterr().err
        assert "CRITICAL" in err, "弹窗失败时必须写 stderr，不能无声吞掉"


class TestDigest:
    def test_flush_digest_aggregates(self, hub):
        for i in range(3):
            alert_hub.alert("WARN", "健康看门狗", "资产陈旧 %d" % i, "")
        n = alert_hub.flush_digest()
        assert n == 3, "摘要应汇总 3 条"
        assert len(hub) == 1, "摘要只弹一次窗，不逐条打扰"

    def test_flush_empty_digest_is_noop(self, hub):
        assert alert_hub.flush_digest() == 0
        assert len(hub) == 0


class TestReverseVerification:
    """撤销验证：破坏实现后上述断言必须转红，否则是假闸。"""

    def _break_and_restore(self, old, new, check_fn):
        import hashlib
        path = os.path.join(ROOT, "utils", "alert_hub.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        md5 = hashlib.md5(src.encode("utf-8")).hexdigest()
        assert old in src, "撤销验证未命中目标代码"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src.replace(old, new, 1))
            failed = False
            try:
                check_fn()
            except AssertionError:
                failed = True
            assert failed, "撤销后断言仍为绿 ⇒ 假闸"
        finally:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            with open(path, "r", encoding="utf-8") as f:
                assert hashlib.md5(f.read().encode("utf-8")).hexdigest() == md5
        return True

    def test_removing_cooldown_is_detected(self, hub):
        """把冷却判定改成恒不抑制 → 重复告警断言必须变红。"""
        def check():
            import importlib
            m = importlib.reload(alert_hub)
            m.LOG_DIR = str(alert_hub.LOG_DIR)
            a = m.alert("CRITICAL", "x", "y", "")
            b = m.alert("CRITICAL", "x", "y", "")
            assert b["suppressed"] is True

        assert self._break_and_restore(
            "    suppressed = (now - last) < COOLDOWN[level]",
            "    suppressed = False  # 撤销验证：去掉冷却",
            check)
