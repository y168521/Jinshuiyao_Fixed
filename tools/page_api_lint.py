# -*- coding: utf-8 -*-
"""金水谣 · 页面-API 契约检查器（防空壳机制）

原理：前端页面调用的 /api/* 路径必须能在 server/router.py 找到注册；
      static.py 注册的页面路由必须指向真实存在的文件。
任意一边出现死链即报错（exit 1），供 pre-commit 拦截"空壳页面"入库。

用法：
    python tools/page_api_lint.py            # 全量检查
    python tools/page_api_lint.py --json     # 输出 JSON 报告
"""
import os
import re
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API_RE = re.compile(r"['\"]((?:/api)/[a-zA-Z0-9_./{}-]*)['\"]")
ROUTE_RE = re.compile(r"['\"]((?:/api)/[a-zA-Z0-9_./{}-]*)['\"]")
STATIC_ROUTE_RE = re.compile(r"['\"]((?:/lottery|/fund|/stock|/football|/api/)[a-zA-Z0-9_./{}-]*)['\"]\s*:\s*os\.path\.join")

SCAN_DIRS = ["frontend", "jinshuiyao-guide"]
SKIP_DIRS = {"node_modules", "_shared", "assets"}

# 已知待修死链（WARN 不阻断提交，修完必须移除！）
# JS-20260812-03 第二批：彩票 4 分析页后端引擎缺失，需新建引擎+handler+路由后再移除
PENDING_APIS = {
    "/api/lottery/historical-same-period",
    "/api/lottery/number-follow-up",
    "/api/lottery/omission-table",
    "/api/lottery/trend-classification",
}


def norm(path):
    """去掉 query 与尾部分隔符，归一化 API 路径"""
    p = path.split("?")[0].rstrip("/")
    if "{" in p:
        return p.split("{")[0] + "<var>"
    return p


def collect_apis():
    """从 server/router.py 提取已注册 API 列表"""
    apis = set()
    router_file = os.path.join(ROOT, "server", "router.py")
    with open(router_file, encoding="utf-8") as f:
        for m in ROUTE_RE.finditer(f.read()):
            apis.add(norm(m.group(1)))
    return apis


def collect_pages():
    """收集待扫描页面文件"""
    pages = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(".html"):
                    pages.append(os.path.join(dirpath, fn))
    return sorted(pages)


def scan_page(page_path):
    """提取页面中引用的 API 路径"""
    apis = []
    try:
        with open(page_path, encoding="utf-8") as f:
            content = f.read()
        seen = set()
        for m in API_RE.finditer(content):
            p = norm(m.group(1))
            if p in seen:
                continue
            seen.add(p)
            apis.append(p)
    except (OSError, UnicodeDecodeError) as e:
        apis.append(f"<无法读取: {e}>")
    return apis


def check_static_routes():
    """反向检查：static.py 注册的路由必须指向存在的文件"""
    errors = []
    static_file = os.path.join(ROOT, "server", "handlers", "static.py")
    with open(static_file, encoding="utf-8") as f:
        content = f.read()
    # _PAGE_ROUTES 与 _EXTERNAL_PAGE_ROUTES / _LOTTERY_ROUTES / _SUBSYSTEM_ROUTES
    # 提取 "路由": os.path.join(...) 键值对
    for m in re.finditer(r"['\"](/(?:lottery|fund|stock|football)[a-zA-Z0-9_/.-]*)['\"]\s*:\s*(?:os\.path\.join\()?['\"]([^'\"]+)['\"]", content):
        route, target = m.group(1), m.group(2)
        if route.startswith("/api"):
            continue
        full = os.path.normpath(os.path.join(ROOT, target))
        if not os.path.isfile(full):
            errors.append(f"路由 {route} → 文件不存在: {target}")
    return errors


def main():
    apis = collect_apis()
    errors = []
    warnings = []
    page_refs = {}

    for page in collect_pages():
        refs = [a for a in scan_page(page) if a.startswith("/api")]
        page_refs[page] = refs
        for a in refs:
            if a not in apis:
                rel = os.path.relpath(page, ROOT).replace("\\", "/")
                if a in PENDING_APIS:
                    warnings.append(f"{rel} 调用未注册 API: {a}（已知待修名单内，第二批处理）")
                else:
                    errors.append(f"{rel} 调用未注册 API: {a}")

    static_errors = check_static_routes()
    errors.extend(static_errors)

    report = {
        "registered_apis": sorted(apis),
        "errors": errors,
        "warnings": warnings,
        "page_count": len(page_refs),
        "api_count": len(apis),
    }

    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[page-api-lint] 页面 {len(page_refs)} 个，已注册 API {len(apis)} 个")
        for w in warnings:
            print(f"[page-api-lint] WARN {w}")
        for e in errors:
            print(f"[page-api-lint] FAIL {e}")
        if not errors:
            print("[page-api-lint] OK 页面调用与路由注册表契约一致（无未登记死链）")
        else:
            print(f"[page-api-lint] 发现 {len(errors)} 处死链，契约不通过")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
