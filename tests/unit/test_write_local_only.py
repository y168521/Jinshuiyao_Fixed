# -*- coding: utf-8 -*-
"""安全三件套单测（P1-3 写操作仅本机 / P1-4 弹窗转义 / P1-5 user-kb 路径包含）
JS-20261021-06 · 第二批修复

先证它红的依据（全部实测，详见 outputs/项目全面复查报告_JS-20261021-03.md）：
  P1-3: 10 个写数据接口没有 _is_local 检查（同门类兄弟接口 memory/user-kb/
        extract-archive/ask/extract 都有）——默认只绑本机所以风险低，但项目
        自己的启动日志就提示"手机访问需 ALLOW_LAN=1"，一开 LAN 立即同网可写；
  P1-4: openCardModal 把 card.summary/content/tags/value/domain 原样拼进
        innerHTML，而同文件的列表视图规规矩矩用了 _esc——存储型 XSS 链的渲染端；
  P1-5: os.path.join(目录, "D:secret.txt") 实测返回 "D:secret.txt"——盘符
        相对路径骗过 join 逃出目录（旧代码只挡 .. / \\，不挡盘符）。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock as mock

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from server.handlers import (  # noqa: E402
    ai as h_ai, fund as h_fund, health as h_health, keys as h_keys,
    knowledge as h_knowledge, prediction as h_prediction, quant as h_quant,
)
from server.router import GuideHandler  # noqa: E402

_NON_LOCAL_IP = "192.168.1.50"   # 典型局域网地址，绝非本机
_HTML_PATH = os.path.join(_project_dir, "jinshuiyao-guide", "ai-agent.html")


class _FakeHandler:
    """模拟 GuideHandler：_is_local / _read_body 绑真实实现，其余只记录不真写。"""

    def __init__(self, ip="127.0.0.1", command="POST", body=b"{}", query=""):
        self.client_address = (ip, 5555)
        self.command = command
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.path = "/api/x"
        self.payload = None
        self.code = None

    def _send_json(self, payload, code=200):
        self.payload = payload
        self.code = code

    def _is_local(self):
        # 绑真实实现：测试不能复刻判据逻辑，否则源码改了测试照样绿
        return GuideHandler._is_local(self)

    def _read_body(self):
        return GuideHandler._read_body(self)


def _write_handler_cases():
    """10 个写数据接口：(模块, 函数名, 额外位置参数, 补丁目标)。

    补丁目标 = 真正落盘的那一层；红态用它证明"非本机请求已经摸到了写操作"，
    绿态用它证明"写操作根本没被调用"。
    """
    P = types.SimpleNamespace(query="code=000001&name=x&shares=10&cost=1", path="/api/x")
    return [
        (h_knowledge, "handle_knowledge_add", (), "knowledge.mirofish_db.MiroFishDB"),
        (h_fund, "handle_portfolio_add", (P,), "server.handlers.fund._get_portfolio_manager"),
        (h_fund, "handle_portfolio_update", (P,), "server.handlers.fund._get_portfolio_manager"),
        (h_fund, "handle_portfolio_remove", (P,), "server.handlers.fund._get_portfolio_manager"),
        (h_keys, "handle_keys_save", (), "server.handlers.keys._write_secret"),
        (h_prediction, "handle_prediction_record", (), "server.handlers.prediction.record_prediction"),
        (h_prediction, "handle_prediction_outcome", (), "server.handlers.prediction.set_prediction_outcome"),
        (h_ai, "handle_theme", (None,), "core.infra.theme_manager.save_user_theme"),
        (h_quant, "handle_knowledge_upsert", (P,), "server.handlers.quant._upsert_knowledge"),
        (h_health, "handle_ai_mode_set_post", (), "server.handlers.health._do_mode_switch"),
    ]


def _write_mock(patch_target):
    """按补丁目标造一个"记录了但没真写"的替身，返回 (patcher, mock_obj)。"""
    if patch_target.endswith("MiroFishDB"):
        cls = mock.MagicMock()
        return mock.patch(patch_target, cls), cls
    if patch_target.endswith("_get_portfolio_manager"):
        mgr = mock.MagicMock()
        mgr.add_holding.return_value = True
        mgr.update_holding.return_value = True
        mgr.remove_holding.return_value = True
        return mock.patch(patch_target, lambda: mgr), mgr
    m = mock.MagicMock(return_value=True)
    return mock.patch(patch_target, m), m


class TestWriteHandlersRejectNonLocal(unittest.TestCase):
    """P1-3：10 个写接口，非本机请求必须 403 且写操作零调用"""

    def test_non_local_gets_403_and_no_write(self):
        for mod, fn, extra, patch_target in _write_handler_cases():
            with self.subTest(handler=fn):
                body = json.dumps({"user_id": "u1", "vars": {"--x": "red"},
                                   "slot": "deepseek", "value": "k",
                                   "mode": "online", "title": "t", "content": "c",
                                   "id": 1, "outcome": "win"}).encode("utf-8")
                fh = _FakeHandler(ip=_NON_LOCAL_IP, command="POST", body=body)
                patcher, wmock = _write_mock(patch_target)
                with patcher:
                    getattr(mod, fn)(fh, *extra)
                self.assertEqual(fh.code, 403,
                                 "%s 非本机请求应被 403 挡下，实际 code=%s" % (fn, fh.code))
                self.assertIn("安全限制", str(fh.payload.get("error", "")),
                              "%s 的 403 必须说明是安全限制" % fn)
                if patch_target.endswith("MiroFishDB"):
                    self.assertFalse(wmock.called, "%s 非本机不应实例化数据库" % fn)
                elif patch_target.endswith("_get_portfolio_manager"):
                    for m in ("add_holding", "update_holding", "remove_holding"):
                        self.assertFalse(getattr(wmock, m).called,
                                         "%s 非本机不应调用 %s" % (fn, m))
                else:
                    self.assertFalse(wmock.called, "%s 非本机不应触发写操作" % fn)


class TestWriteHandlersAllowLocal(unittest.TestCase):
    """P1-3：本机请求不能被误伤（收口不能把主人关在门外）"""

    def test_theme_post_local_still_saves(self):
        with mock.patch("core.infra.theme_manager.save_user_theme",
                        return_value=True) as m:
            fh = _FakeHandler(ip="127.0.0.1", command="POST",
                              body=json.dumps({"user_id": "u1",
                                               "vars": {"--x": "red"}}).encode("utf-8"))
            h_ai.handle_theme(fh, None)
        self.assertNotEqual(fh.code, 403)
        self.assertTrue(m.called, "本机保存主题必须放行")

    def test_prediction_record_local_still_writes(self):
        with mock.patch("server.handlers.prediction.record_prediction",
                        return_value="rid1") as m:
            fh = _FakeHandler(ip="127.0.0.1", body=json.dumps(
                {"question": "q", "answer": "a", "domain": "lottery"}).encode("utf-8"))
            h_prediction.handle_prediction_record(fh)
        self.assertNotEqual(fh.code, 403)
        self.assertTrue(m.called, "本机记录预测必须放行")

    def test_portfolio_add_local_still_writes(self):
        mgr = mock.MagicMock()
        mgr.add_holding.return_value = True
        P = types.SimpleNamespace(query="code=000001&name=x&shares=10&cost=1", path="/api/x")
        with mock.patch("server.handlers.fund._get_portfolio_manager", lambda: mgr):
            fh = _FakeHandler(ip="127.0.0.1", body=b"{}")
            h_fund.handle_portfolio_add(fh, P)
        self.assertNotEqual(fh.code, 403)
        self.assertTrue(mgr.add_holding.called, "本机添加持仓必须放行")


class TestWriteLocalOnlyGateCore(unittest.TestCase):
    """AST 闸核心判据（合成源码，正反例）"""

    def test_detects_guard_call(self):
        from tools.check_write_local_only import handler_has_local_guard
        src = ("def handle_x(handler):\n"
               "    if not handler._is_local():\n"
               "        handler._send_json({}, 403)\n"
               "        return\n"
               "    do_write()\n")
        self.assertTrue(handler_has_local_guard(src, "handle_x"))

    def test_missing_guard_detected(self):
        from tools.check_write_local_only import handler_has_local_guard
        src = "def handle_x(handler):\n    do_write()\n"
        self.assertFalse(handler_has_local_guard(src, "handle_x"))

    def test_self_call_not_counted(self):
        """self._is_local() 是路由器内部方法，不算处理器自卫"""
        from tools.check_write_local_only import handler_has_local_guard
        src = "def handle_x(handler):\n    self._is_local()\n"
        self.assertFalse(handler_has_local_guard(src, "handle_x"))

    def test_real_repo_passes(self):
        """真实仓库必须过闸（修完之后）"""
        from tools.check_write_local_only import main
        self.assertEqual(main(), 0)


class TestUserKbDetailPathSafety(unittest.TestCase):
    """P1-5：user-kb 详情接口，盘符/相对路径都别想逃出目录"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.kb = os.path.join(self.tmp, "用户知识库")
        os.makedirs(self.kb)
        with open(os.path.join(self.kb, "real_card.md"), "w", encoding="utf-8") as f:
            f.write("# 真卡片内容")
        with open(os.path.join(self.tmp, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("机密机密机密")
        self._orig = h_knowledge._USER_KB_DIR
        h_knowledge._USER_KB_DIR = self.kb
        self.addCleanup(setattr, h_knowledge, "_USER_KB_DIR", self._orig)

    def _detail(self, filename, ip="127.0.0.1"):
        P = types.SimpleNamespace(query="file=" + filename, path="/api/user-kb/detail")
        fh = _FakeHandler(ip=ip, command="GET", body=b"")
        h_knowledge.handle_user_kb_detail(fh, P)
        return fh

    def test_real_card_readable_locally(self):
        fh = self._detail("real_card.md")
        self.assertEqual(fh.code, 200)
        self.assertIn("真卡片内容", fh.payload.get("content", ""))

    def test_evil_names_never_leak(self):
        for name in ("D:secret.txt", "C:/Windows/win.ini", "..%2Fsecret.txt",
                     "..%5Csecret.txt", "%2E%2E%2Fsecret.txt"):
            with self.subTest(name=name):
                fh = self._detail(name)
                self.assertIn(fh.code, (400, 404), "恶意名应被拒或找不到，实际 %s" % fh.code)
                self.assertNotIn("机密机密机密", json.dumps(fh.payload, ensure_ascii=False),
                                 "目录外文件内容绝不外泄")

    def test_non_local_rejected(self):
        fh = self._detail("real_card.md", ip=_NON_LOCAL_IP)
        self.assertEqual(fh.code, 403)
        self.assertIn("安全限制", str(fh.payload.get("error", "")))


def _extract_js_function(src, header):
    """按花括号配对从页面源码里抠出一个 JS 函数"""
    i = src.index(header)
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError("%s 花括号不配对" % header)


class TestModalEscapingStatic(unittest.TestCase):
    """P1-4（静态判据）：弹窗与列表视图里每个用户字段都必须过 _esc"""

    @classmethod
    def setUpClass(cls):
        with open(_HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_modal_user_fields_all_escaped(self):
        src = _extract_js_function(self.html, "function openCardModal(cardId)")
        for pattern in ("_esc(card.summary)", "_esc(card.content)",
                        "_esc(t)", "_esc(card.value)",
                        "_esc(domainLabels[card.domain] || card.domain)",
                        "_esc(card.date"):
            self.assertIn(pattern, src,
                          "弹窗缺少转义：%s——原样拼接就是 XSS 入口" % pattern)

    def test_modal_no_raw_interpolation(self):
        src = _extract_js_function(self.html, "function openCardModal(cardId)")
        for raw in ("' + card.summary + '", "' + card.content + '",
                    "' + t + '", "' + card.value + '", "' + card.date"):
            self.assertNotIn(raw, src, "弹窗仍在原样拼接：%s" % raw)

    def test_list_view_attributes_escaped(self):
        src = _extract_js_function(self.html, "function renderKnowledgeCards()")
        for pattern in ("_esc(card.domain)", "_esc(card.id)", "_esc(card.value)",
                        "_esc(card.date"):
            self.assertIn(pattern, src,
                          "列表视图属性/文本缺少转义：%s" % pattern)
        self.assertNotIn("data-domain=\"' + card.domain", src,
                         "data-domain 属性仍在原样拼接")


def _find_node():
    cands = [r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-6\node.exe"]
    for c in cands:
        if os.path.isfile(c):
            return c
    return shutil.which("node")


@unittest.skipUnless(_find_node(), "node 不可用，跳过行为级转义测试（静态判据仍会跑）")
class TestModalEscapingNode(unittest.TestCase):
    """P1-4（行为级）：真跑 ai-agent.html 里的 openCardModal / escapeHtml，看输出是否安全"""

    def test_modal_and_escaper_safe(self):
        node = _find_node()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        harness = os.path.join(tmp, "harness.js")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(_NODE_HARNESS.replace("__HTML__", _HTML_PATH.replace("\\", "/")))
        out = subprocess.run([node, harness], capture_output=True, text=True,
                             timeout=60, encoding="utf-8")
        self.assertEqual(out.returncode, 0, "node 跑挂: %s" % (out.stderr or "")[-500:])
        result = json.loads(out.stdout.strip().splitlines()[-1])
        body, esc = result["body"], result["esc"]
        # 判据是"未转义的破链模式"——带真实标签/真实引号的才危险；
        # 转义后的 onmouseover=&quot; 只是普通文本，不算失守。
        self.assertNotIn("<img src=x", body, "摘要里的 img 标签必须被转义")
        self.assertNotIn("<script>alert(2)", body, "正文里的 script 必须被转义")
        self.assertNotIn("<b>tag</b>", body, "标签必须被转义")
        self.assertNotIn('onmouseover="alert(1)"', body, "属性注入必须被转义")
        self.assertNotIn('general"><script>', body, "领域字段必须被转义")
        self.assertIn("&lt;img", body, "应当出现转义后的实体")
        # escapeHtml 升级后必须连引号一起转（属性上下文安全）
        self.assertIn("&quot;", esc, "双引号必须转义")
        self.assertIn("&#39;", esc, "单引号必须转义")
        self.assertIn("&lt;", esc, "小于号必须转义")


_NODE_HARNESS = r"""
const fs = require('fs');
const html = fs.readFileSync('__HTML__', 'utf8');
function extractFn(src, header) {
  const i = src.indexOf(header);
  if (i < 0) throw new Error('找不到 ' + header);
  let depth = 0;
  const j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (depth === 0) return src.slice(i, k + 1); }
  }
  throw new Error('花括号不配对');
}
function extractStmt(src, header) {
  const i = src.indexOf(header);
  if (i < 0) throw new Error('找不到 ' + header);
  let depth = 0;
  for (let k = i; k < src.length; k++) {
    const ch = src[k];
    if (ch === '{') depth++;
    else if (ch === '}') depth--;
    else if (ch === ';' && depth <= 0) return src.slice(i, k + 1);
  }
  throw new Error(header + ' 语句不完整');
}
const modalSrc = extractFn(html, 'function openCardModal(cardId)');
const escSrc = extractFn(html, 'function escapeHtml(text)');
const escVarSrc = extractStmt(html, 'var _esc =');
const elements = {};
function makeEl() {
  const el = { _text: '', _html: undefined, classList: { add() {}, remove() {} } };
  Object.defineProperty(el, 'textContent', {
    set(v) { this._text = v == null ? '' : String(v); },
    get() { return this._text; },
  });
  Object.defineProperty(el, 'innerHTML', {
    set(v) { this._html = v; },
    // 没被显式赋值时，按浏览器规则把 textContent 序列化（转义 & < >）
    get() {
      if (this._html !== undefined) return this._html;
      return this._text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  });
  return el;
}
function el(id) {
  return elements[id] || (elements[id] = makeEl());
}
global.document = { getElementById: el, createElement: makeEl, addEventListener() {} };
global.loadCrossLinks = function () {};
global.knowledgeCards = [{
  id: 'c1', title: 'T',
  value: 'data" onmouseover="alert(1)',
  summary: '<img src=x onerror=alert(1)>',
  content: '<script>alert(2)</script>',
  tags: ['<b>tag</b>'],
  domain: 'general"><script>alert(3)</script>',
  date: '2026-10-21',
}];
eval(escSrc);       // escapeHtml 先定义，_esc 才会别名到它（与页面同序）
eval(escVarSrc);
eval(modalSrc);
openCardModal('c1');
console.log(JSON.stringify({
  body: el('modalBody').innerHTML,
  esc: escapeHtml('<x a="1" b=\'2\'>'),
}));
"""


class TestLanModeWarning(unittest.TestCase):
    """P1-3 配套：开局域网时必须明确警告"写操作仅本机" """

    def test_local_bind_no_warning(self):
        from server import _lan_write_warning
        self.assertEqual(_lan_write_warning("127.0.0.1"), [])

    def test_lan_bind_warns_write_local_only(self):
        from server import _lan_write_warning
        lines = _lan_write_warning("0.0.0.0")
        self.assertTrue(lines, "局域网开放必须给警告")
        joined = "\n".join(lines)
        self.assertIn("写操作", joined)
        self.assertIn("仅", joined)


if __name__ == "__main__":
    unittest.main()
