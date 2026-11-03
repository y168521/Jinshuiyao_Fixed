#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写操作仅本机收口闸（P1-3，JS-20261021-06）

背景（实测，见 outputs/项目全面复查报告_JS-20261021-03.md）：
  45 个处理外部输入的接口函数没有本机校验，其中 10 个真正会改写数据
  （知识卡片/基金持仓/密钥/预测记录/个人主题/量化知识库/AI 模式）。
  服务默认只绑本机所以风险低，但项目自己的启动日志就提示"手机访问需
  设 BIND_HOST+ALLOW_LAN"——一开局域网，这些接口立即变成同网可写。
  同门类兄弟接口（memory/user-kb/extract-archive/ask/extract）早就收了口，
  漏的这 10 个属"同型错误在不同入口重复犯"。

机制（AST 判据，不靠 grep——grep 会被注释和字符串骗）：
  1. AST 解析 server/router.py，取出 _do_POST_impl 里的 path → handler 映射；
  2. WRITE_HANDLERS 登记册显式声明"这些 handler 会写数据"；
  3. 逐个检查登记册里的 handler 函数体含 handler._is_local() 调用，
     缺一个即 FAIL（登记册里找不到函数 = 登记册过期，同样 FAIL）；
  4. 兜底扫描：POST 路由里名字带写操作特征（add/save/update/remove/...）、
     又没登记、又没有自卫的 handler → WARN 交人工 Review（不硬拦，
     避免读接口误报；新写接口必须登记进 WRITE_HANDLERS）。

退出码：0 = 通过（WARN 不阻断）；1 = 有 FAIL。
"""
import ast
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception as _e:
    # 编码设置失败不阻断，但绝不静默（JS-20260921-02：吞异常最毒的是"错得无声"）
    print("[check_write_local_only] 标准输出编码设置失败: %s" % _e, file=sys.stderr)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER_PATH = os.path.join(BASE_DIR, "server", "router.py")

# 登记册：会写数据的 handler（router 里的模块别名 → 函数名列表）。
# 新增写接口必须在这里登记，否则兜底扫描会 WARN；登记了却没自卫 = FAIL。
WRITE_HANDLERS = {
    "h_knowledge": ["handle_knowledge_add"],
    "h_fund": ["handle_portfolio_add", "handle_portfolio_update",
               "handle_portfolio_remove"],
    "h_keys": ["handle_keys_save"],
    "h_prediction": ["handle_prediction_record", "handle_prediction_outcome"],
    "h_ai": ["handle_theme"],            # GET/POST 混合，仅 POST 分支写
    "h_quant": ["handle_knowledge_upsert"],
    "h_health": ["handle_ai_mode_set_post"],
}

# 兜底扫描用的写操作特征名（命中 + 未登记 + 无自卫 → WARN）
WRITE_NAME_HINTS = ("add", "save", "update", "remove", "delete", "set",
                    "record", "upsert", "write", "clear", "purge", "switch")


def handler_has_local_guard(src, func_name):
    """AST 判据：名为 func_name 的函数体内是否有 handler._is_local() 调用。

    self._is_local() 是 GuideHandler 的内部方法，不算处理器自卫；
    注释/字符串里提到 _is_local 也不算（AST 只看真实调用节点）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    f = sub.func
                    if f.attr == "_is_local" and isinstance(f.value, ast.Name) \
                            and f.value.id == "handler":
                        return True
            return False
    return False


def handler_function_exists(src, func_name):
    """func_name 是否在 src 里定义过（登记册过期检测用）"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            return True
    return False


def alias_module_map(router_src):
    """router 的 import 别名 → 模块文件路径（h_knowledge → server/handlers/knowledge.py）"""
    mapping = {}
    try:
        tree = ast.parse(router_src)
    except SyntaxError:
        return mapping
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("handlers"):
            # 相对导入（from .handlers import x as h_x）以 router.py 所在包 server/ 为基
            if node.level and node.level > 0:
                base = os.path.join(BASE_DIR, "server")
            else:
                base = BASE_DIR
            pkg = node.module.replace(".", os.sep)
            for a in node.names:
                if a.asname:
                    mapping[a.asname] = os.path.join(base, pkg, a.name + ".py")
    return mapping


def _handler_calls_in(node):
    """收集一个 If 语句体里的 h_xxx.handle_yyy(...) 调用 → (alias, handler)"""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            v = sub.func.value
            if isinstance(v, ast.Name) and v.id.startswith("h_") \
                    and sub.func.attr.startswith("handle_"):
                out.append((v.id, sub.func.attr))
    return out


def _path_consts(test):
    """从 if 的条件里取路径常量：parsed.path == '/x' 或 parsed.path.startswith('/x')"""
    consts = []
    for sub in ast.walk(test):
        if isinstance(sub, ast.Compare):
            for op, comp in zip(sub.ops, sub.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comp, ast.Constant) \
                        and isinstance(comp.value, str):
                    consts.append(comp.value)
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "startswith":
            for arg in sub.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    consts.append(arg.value)
    return consts


def post_routes(router_src):
    """_do_POST_impl 里的 path → [(alias, handler), ...]"""
    try:
        tree = ast.parse(router_src)
    except SyntaxError:
        return {}
    impl = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_do_POST_impl":
            impl = node
            break
    if impl is None:
        return {}
    routes = {}
    for node in ast.walk(impl):
        if isinstance(node, ast.If):
            consts = _path_consts(node.test)
            calls = _handler_calls_in(node)
            if consts and calls:
                for c in consts:
                    routes.setdefault(c, []).extend(calls)
    return routes


def run_check(base_dir=BASE_DIR):
    """返回 (ok, failures, warnings, passed_count)"""
    router_path = os.path.join(base_dir, "server", "router.py")
    if not os.path.isfile(router_path):
        return False, ["找不到 server/router.py"], [], 0
    with open(router_path, "r", encoding="utf-8") as f:
        router_src = f.read()
    amap = alias_module_map(router_src)
    routes = post_routes(router_src)

    failures, warnings, passed = [], [], 0
    for alias, fns in sorted(WRITE_HANDLERS.items()):
        mod_path = amap.get(alias)
        if mod_path is None or not os.path.isfile(mod_path):
            failures.append("登记册别名 %s 解析不到模块文件（router import 变了？）" % alias)
            continue
        with open(mod_path, "r", encoding="utf-8") as f:
            src = f.read()
        for fn in fns:
            if not handler_function_exists(src, fn):
                failures.append("%s.%s 在 %s 里不存在——登记册过期或函数被改名"
                                % (alias, fn, os.path.relpath(mod_path, base_dir)))
            elif not handler_has_local_guard(src, fn):
                failures.append("%s.%s 缺 _is_local 自卫——非本机请求可越权写入"
                                % (alias, fn))
            else:
                passed += 1

    # 兜底：未登记、名字像写操作、又没自卫的 POST handler → WARN
    registered = {(a, fn) for a, fns in WRITE_HANDLERS.items() for fn in fns}
    for path, calls in sorted(routes.items()):
        for alias, fn in calls:
            if (alias, fn) in registered:
                continue
            if not any(h in fn.lower() for h in WRITE_NAME_HINTS):
                continue
            mod_path = amap.get(alias)
            if mod_path is None or not os.path.isfile(mod_path):
                continue
            with open(mod_path, "r", encoding="utf-8") as f:
                src = f.read()
            if not handler_function_exists(src, fn):
                continue
            if not handler_has_local_guard(src, fn):
                warnings.append("%s (%s) 疑似写接口但未登记也无自卫——确认后补进 "
                                "WRITE_HANDLERS 登记册" % (path, fn))
    return (not failures), failures, warnings, passed


def main():
    ok, failures, warnings, passed = run_check()
    print("=" * 60)
    print("  写操作仅本机收口检查（P1-3 · JS-20261021-06）")
    print("=" * 60)
    if failures:
        for f_ in failures:
            print("  [FAIL] %s" % f_)
    if warnings:
        for w in warnings:
            print("  [WARN] %s" % w)
    if ok and not warnings:
        print("  [OK] 登记册 %d 个写接口全部有 _is_local 自卫" % passed)
        print("  [OK] 未发现未登记且无自卫的写接口（兜底扫描通过）")
    elif ok:
        print("  [OK] 登记册 %d 个写接口全部有 _is_local 自卫" % passed)
    print("-" * 60)
    if ok:
        print("  结论: [PASS] 写操作收口合规（%d 项登记，%d 条待人工确认）"
              % (passed, len(warnings)))
        return 0
    print("  结论: [FAIL] %d 个写接口没收口——修复: 在该 handler 开头补\n"
          "        if not handler._is_local(): 403 return（参照 memory/user-kb 兄弟接口）"
          % len(failures))
    return 1


if __name__ == "__main__":
    sys.exit(main())
