# -*- coding: utf-8 -*-
"""JS-20260806-09 · CORS 与 SSRF 纵深加固 测试

覆盖：
  - video_extractor._is_safe_host 离线纯函数（public/private/link-local/非http）
  - _request_with_retry 入口 SSRF 拦截（link-local 初始 URL 直接返回 None，绝不发请求）
  - _request_with_retry 入口放行（安全 URL 正常走请求，验证修复未破坏正常路径）
  - _post_with_retry 入口同样拦截（防御性）
  - health.handle_status 不再硬编码 '*'，且委托 router._set_cors（同源反射）
  - router._set_cors 同源反射 / 跨域拒绝
  - quant_server.Handler._is_same_origin / _set_cors（本刀新增代码）
  - server.utils.open_local_file 用参数列表启动 explorer（消除引号注入歧义）
"""
import importlib.util
import pathlib
import sys
import types
from io import BytesIO
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.video_extractor import VideoExtractor
from server.handlers import health
from server import router as _router

# 动态定位实现了 _set_cors 的 router 类（类名不固定，避免硬编码）
_CORS_CLS = next((c for c in vars(_router).values()
                  if isinstance(c, type) and hasattr(c, '_set_cors')), None)


# ---------------------------------------------------------------------------
# 辅助：捕获 HTTP handler 头写入的假对象
# ---------------------------------------------------------------------------
class _FakeHandler:
    """模拟 router/BaseHTTPRequestHandler 的头写入接口。

    cors_cls：注入实现了 _is_same_origin 的真实类（router / quant_server.Handler），
    使 _set_cors 走真实同源判定逻辑。
    """

    def __init__(self, origin=None, port=18888, cors_cls=None):
        self.headers = {'Origin': origin} if origin else {}
        self.server = types.SimpleNamespace(server_port=port)
        self._sent = []
        self.wfile = BytesIO()
        self._code = None
        self._cors_cls = cors_cls

    def send_response(self, code):
        self._code = code

    def send_header(self, k, v):
        self._sent.append((k, v))

    def end_headers(self):
        pass

    def _is_same_origin(self, origin):
        if self._cors_cls is not None:
            return self._cors_cls._is_same_origin(self, origin)
        return False  # 默认回退（不应在测试中触发）


# ---------------------------------------------------------------------------
# video_extractor SSRF
# ---------------------------------------------------------------------------
def test_is_safe_host_offline():
    ve = VideoExtractor()
    # 公网 IP 字面量 → 放行（离线，纯解析，无 DNS）
    assert ve._is_safe_host('http://8.8.8.8/x') is True
    # 私网 / 环回 / 链路本地 / 非 http → 拒绝
    assert ve._is_safe_host('http://192.168.1.1/x') is False
    assert ve._is_safe_host('http://127.0.0.1/x') is False
    assert ve._is_safe_host('http://169.254.169.254/latest/meta-data/') is False
    assert ve._is_safe_host('file:///etc/passwd') is False
    assert ve._is_safe_host('ftp://example.com') is False
    assert ve._is_safe_host('not-a-url') is False


def test_request_entry_denies_ssrf():
    """初始 URL 为 link-local → 入口直接拦截，绝不发起网络请求。"""
    ve = VideoExtractor()
    with mock.patch.object(ve, '_get_session') as gs, \
         mock.patch.object(ve, '_is_safe_host', return_value=False):
        res = ve._request_with_retry('http://169.254.169.254/x')
        assert res is None
        gs.assert_not_called()  # 连 session 都没取，更不可能发请求


def test_request_entry_allows_safe():
    """安全 URL → 入口放行并正常发起请求（验证修复未破坏正常路径）。"""
    ve = VideoExtractor()
    fake_session = mock.MagicMock()
    fake_resp = mock.MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {}
    fake_session.get.return_value = fake_resp
    with mock.patch.object(ve, '_get_session', return_value=fake_session), \
         mock.patch.object(ve, '_is_safe_host', return_value=True):
        res = ve._request_with_retry('http://example.com/x', timeout=1)
        assert res is fake_resp
        fake_session.get.assert_called_once()


def test_post_entry_denies_ssrf():
    """_post_with_retry 入口同样拦截（防御性，当前虽无调用方）。"""
    ve = VideoExtractor()
    with mock.patch.object(ve, '_get_session') as gs, \
         mock.patch.object(ve, '_is_safe_host', return_value=False):
        res = ve._post_with_retry('http://169.254.169.254/x')
        assert res is None
        gs.assert_not_called()


# ---------------------------------------------------------------------------
# CORS：health 委托 + router 同源反射
# ---------------------------------------------------------------------------
def test_health_status_no_wildcard():
    """handle_status 不再硬编码 '*'，且委托 router._set_cors。"""
    h = _FakeHandler(origin=None)
    h._set_cors = lambda: _CORS_CLS._set_cors(h)
    health.handle_status(h)
    assert ('Access-Control-Allow-Origin', '*') not in h._sent


def test_router_set_cors_same_origin_reflects():
    h = _FakeHandler(origin='http://127.0.0.1:18888', port=18888, cors_cls=_CORS_CLS)
    _CORS_CLS._set_cors(h)
    assert ('Access-Control-Allow-Origin', 'http://127.0.0.1:18888') in h._sent


def test_router_set_cors_cross_origin_denied():
    h = _FakeHandler(origin='http://evil.example.com', port=18888, cors_cls=_CORS_CLS)
    _CORS_CLS._set_cors(h)
    assert all(k != 'Access-Control-Allow-Origin' for k, _ in h._sent)


# ---------------------------------------------------------------------------
# CORS：quant_server 新增的同源反射（hyphen 目录，importlib 加载）
# ---------------------------------------------------------------------------
_QS_PATH = ROOT / 'frontend' / 'quant-dashboard' / 'quant_server.py'
_qs_spec = importlib.util.spec_from_file_location('quant_server_test_mod', str(_QS_PATH))
qs = importlib.util.module_from_spec(_qs_spec)
_qs_spec.loader.exec_module(qs)


def test_qs_is_same_origin():
    fake = types.SimpleNamespace(server=types.SimpleNamespace(server_port=8891))
    assert qs.Handler._is_same_origin(fake, 'http://127.0.0.1:8891') is True
    # 端口不符 → 拒绝（防其他本机服务伪造）
    assert qs.Handler._is_same_origin(fake, 'http://127.0.0.1:9999') is False
    # 跨主机 → 拒绝
    assert qs.Handler._is_same_origin(fake, 'http://evil.com:8891') is False
    # 非 http/https → 拒绝
    assert qs.Handler._is_same_origin(fake, 'file:///x') is False


def test_qs_set_cors_same_origin():
    h = _FakeHandler(origin='http://127.0.0.1:8891', port=8891, cors_cls=qs.Handler)
    qs.Handler._set_cors(h)
    assert ('Access-Control-Allow-Origin', 'http://127.0.0.1:8891') in h._sent


def test_qs_set_cors_cross_origin():
    h = _FakeHandler(origin='http://evil.com', port=8891, cors_cls=qs.Handler)
    qs.Handler._set_cors(h)
    assert all(k != 'Access-Control-Allow-Origin' for k, _ in h._sent)


# ---------------------------------------------------------------------------
# 路径注入：open_local_file 用参数列表启动 explorer
# ---------------------------------------------------------------------------
def test_open_local_file_uses_arg_list(monkeypatch):
    """打开目录时应以参数列表启动 explorer，而非 f-string（防引号注入）。"""
    import server.utils as su
    captured = {}

    def fake_popen(args, **kw):
        captured['args'] = args

        class _P:
            pass
        return _P()

    monkeypatch.setattr(su.subprocess, 'Popen', fake_popen)
    ok = su.open_local_file('.', mode='auto')  # BASE_DIR 自身，必为目录
    assert ok is True
    assert isinstance(captured['args'], (list, tuple)), "explorer 应以参数列表启动"
    assert str(captured['args'][0]).lower().endswith('explorer.exe')
    assert len(captured['args']) == 2  # 程序 + 目标路径，未拼接成单字符串
