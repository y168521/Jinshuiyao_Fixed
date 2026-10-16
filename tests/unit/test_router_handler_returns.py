# -*- coding: utf-8 -*-
"""路由分发闸：调用 handler 后必须 return，否则会往同一个 socket 写两次响应

背景（JS-20261015-07 复查发现）
------------------------------
`server/router.py:498` 曾经是：

    if parsed.path == '/api/knowledge/list':
        h_static.handle_knowledge_list(self)      # ← 缺 return

而 `handle_knowledge_list`（`server/handlers/static.py:712`）末尾已经 `_send_json`
发出了第一个 200 响应。缺 return 会让执行继续往下走，最终落到 `self._serve_static()`；
路径 `api/knowledge/list` 没有扩展名、不在静态白名单 ⇒ **再发一个 403 JSON**。
同一个 socket 上出现两个 HTTP 响应，前端 `r.json()` 直接解析失败。

这类缺陷的隐蔽之处在于：后端日志看不出异常（两个响应都"成功"发出了），
表现是前端某个页面莫名其妙取不到数据，很容易被当成前端 bug 排查。

本闸用 AST 扫描 router.py，锁住「if 分支里调了 handler 就必须 return」这一语义。
"""
import ast
import io
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTER = os.path.join(REPO_ROOT, "server", "router.py")


def _is_handler_call(stmt):
    """判断语句是否为 `h_xxx.handle_yyy(self, ...)` 形式的调用。"""
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    fn = stmt.value.func
    if not isinstance(fn, ast.Attribute):
        return False
    if not fn.attr.startswith("handle_"):
        return False
    # 形如 h_static.handle_xxx / h_prediction.handle_xxx
    return isinstance(fn.value, ast.Name)


def _offending_branch_nodes(tree):
    """返回「调了 handler 但分支体末尾没有 return」的 If 节点列表。"""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        body = node.body
        if not any(_is_handler_call(s) for s in body):
            continue
        if not isinstance(body[-1], ast.Return):
            bad.append((node.lineno, getattr(body[-1], "lineno", body[-1].lineno)))
    return bad


def _parse_source(src):
    return ast.parse(src)


def test_every_handler_branch_returns():
    """router.py 中每个调用 handler 的 if 分支，结尾都必须是 return。"""
    with io.open(ROUTER, encoding="utf-8") as f:
        tree = _parse_source(f.read())
    bad = _offending_branch_nodes(tree)
    assert not bad, (
        "以下 if 分支调用了 handler 却没有 return，会向同一 socket 写两次响应"
        "（前端表现为该接口取不到数据）：%s" % bad
    )


def test_gate_catches_missing_return():
    """反向验证：闸本身必须能抓到缺 return 的写法，否则它就是个假闸。"""
    src = (
        "def dispatch(self, parsed):\n"
        "    if parsed.path == '/api/knowledge/list':\n"
        "        h_static.handle_knowledge_list(self)\n"
        "    if parsed.path == '/api/changelog':\n"
        "        h_static.handle_changelog(self)\n"
        "        return\n"
    )
    bad = _offending_branch_nodes(_parse_source(src))
    assert len(bad) == 1, "应恰好抓到 1 处缺 return，实际 %d 处：%s" % (len(bad), bad)
    assert bad[0][0] == 2, "应定位到第 2 行的 if，实际 %s" % (bad[0],)


def test_gate_passes_correct_branch():
    """正向验证：补上 return 后必须放行，避免闸误伤正常写法。"""
    src = (
        "def dispatch(self, parsed):\n"
        "    if parsed.path == '/api/knowledge/list':\n"
        "        h_static.handle_knowledge_list(self)\n"
        "        return\n"
    )
    assert _offending_branch_nodes(_parse_source(src)) == []
