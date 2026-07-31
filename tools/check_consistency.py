# -*- coding: utf-8 -*-
"""
系统一致性检测器（金水谣 · 防复发机制）

功能：启动时 / 提交前自动检查所有已知问题模式，发现则阻止。
覆盖从交接中心/工作留痕提炼的反复发作根因：
  ① 路由表与实际文件位置不一致
  ② HTML 中引用的静态资源（js/css）不存在
  ③ 仓外文件被修改但仓内未同步
  ④ 子系统页面未在导航中注册
  ⑤ 共享资源（_shared/）缺失

避免"用户发现→记录→再犯"的死循环。
"""

import os
import sys
import json
import re
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)  # 模型/
HTML_DIR = os.path.join(BASE_DIR, 'jinshuiyao-guide')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')

# ── 注册表：所有已知的子系统页面（与 router.py / static.py 保持一致）──
# 从 static.py 复制而来，作为单一真源
KNOWN_SUBSYSTEM_PAGES = {
    # lottery
    '/lottery':              os.path.join(BASE_DIR, 'frontend/lottery/lottery-hub.html'),
    '/lottery/dashboard':    os.path.join(BASE_DIR, 'frontend/lottery/dashboard.html'),
    '/lottery/omission-heatmap': os.path.join(BASE_DIR, 'frontend/lottery/omission-heatmap.html'),
    '/lottery/rotation-matrix': os.path.join(BASE_DIR, 'frontend/lottery/rotation-matrix.html'),
    '/lottery/filter-panel':    os.path.join(BASE_DIR, 'frontend/lottery/filter-panel.html'),
    '/lottery/prize-calculator': os.path.join(BASE_DIR, 'frontend/lottery/prize-calculator.html'),
    '/lottery/head-tail-analysis': os.path.join(BASE_DIR, 'frontend/lottery/head-tail-analysis.html'),
    '/lottery/historical-same-period': os.path.join(BASE_DIR, 'frontend/lottery/historical-same-period.html'),
    '/lottery/number-follow-up':  os.path.join(BASE_DIR, 'frontend/lottery/number-follow-up.html'),
    '/lottery/audit-dashboard':   os.path.join(BASE_DIR, 'frontend/lottery/audit-dashboard.html'),
    '/lottery/ac-calculator':    os.path.join(BASE_DIR, 'frontend/lottery/ac-calculator.html'),
    '/lottery/trend-classification': os.path.join(BASE_DIR, 'frontend/lottery/trend-classification.html'),
    '/lottery/omission-table':    os.path.join(BASE_DIR, 'frontend/lottery/omission-table.html'),
    # fund
    '/fund':              os.path.join(BASE_DIR, 'frontend/fund/fund-hub.html'),
    '/fund/dashboard':    os.path.join(BASE_DIR, 'frontend/fund/dashboard.html'),
    '/fund/nav-trend':    os.path.join(BASE_DIR, 'frontend/fund/nav-trend.html'),
    '/fund/holdings':     os.path.join(BASE_DIR, 'frontend/fund/holdings.html'),
    '/fund/screener':     os.path.join(BASE_DIR, 'frontend/fund/screener.html'),
    '/fund/detail':       os.path.join(BASE_DIR, 'frontend/fund/fund-detail.html'),
    '/fund/dca':          os.path.join(BASE_DIR, 'frontend/fund/dca-simulator.html'),
    '/fund/portfolio':    os.path.join(BASE_DIR, 'frontend/fund/portfolio.html'),
    # stock
    '/stock':             os.path.join(BASE_DIR, 'frontend/stock/stock-hub.html'),
    '/stock/dashboard':   os.path.join(BASE_DIR, 'frontend/stock/stock-dashboard.html'),
    '/stock/detail':      os.path.join(BASE_DIR, 'frontend/stock/stock-detail.html'),
    # football
    '/football':          os.path.join(BASE_DIR, 'frontend/football/football-hub.html'),
    '/football/dashboard': os.path.join(BASE_DIR, 'frontend/football/dashboard.html'),
    '/football/matches':   os.path.join(BASE_DIR, 'frontend/football/matches.html'),
    '/football/predict':   os.path.join(BASE_DIR, 'frontend/football/predict.html'),
}

# 已知页面路由（from server/handlers/static.py _PAGE_ROUTES 和 _EXTERNAL_PAGE_ROUTES）
KNOWN_GUIDE_PAGES = {
    '/docs':             os.path.join(HTML_DIR, 'api-docs.html'),
    '/test-report':      os.path.join(HTML_DIR, 'test-report.html'),
    '/health-check':     os.path.join(HTML_DIR, 'health-check.html'),
    '/ai-test':          os.path.join(HTML_DIR, 'ai-test.html'),
    '/ai-agent':         os.path.join(HTML_DIR, 'ai-agent.html'),
    '/workbench':        os.path.join(HTML_DIR, 'workbench.html'),
    '/jinshuiyao-guide': os.path.join(HTML_DIR, 'jinshuiyao-guide.html'),
    '/route':            os.path.join(HTML_DIR, 'route.html'),
    '/smart-coder':      os.path.join(HTML_DIR, 'assistant.html'),
    '/control-center':   os.path.join(HTML_DIR, 'control-center.html'),
    '/architecture':     os.path.join(HTML_DIR, 'jinshuiyao-architecture.html'),
    '/global-plan':      os.path.join(HTML_DIR, 'jinshuiyao-global-plan.html'),
    '/scheduler':        os.path.join(HTML_DIR, 'scheduler.html'),
    '/engine-dashboard': os.path.join(HTML_DIR, 'engine-dashboard.html'),
    '/review-dashboard': os.path.join(HTML_DIR, 'review-dashboard.html'),
    '/compare-tech':     os.path.join(HTML_DIR, 'compare-tech.html'),
    '/math-model':       os.path.join(HTML_DIR, 'math-model.html'),
    '/prediction-reference': os.path.join(HTML_DIR, 'prediction-reference.html'),
}

KNOWN_EXTERNAL_PAGES = {
    '/dashboard':      os.path.join(BASE_DIR, 'frontend/dashboard/jinshuiyao-dashboard.html'),
    '/trend':          os.path.join(BASE_DIR, 'frontend/trend/jinshuiyao-trend.html'),
    '/quant':          os.path.join(BASE_DIR, 'frontend/quant-dashboard/index.html'),
    '/gap-analysis':   os.path.join(BASE_DIR, 'frontend/gap-analysis/jinshuiyao-gap-analysis.html'),
    '/omission-heatmap': os.path.join(BASE_DIR, 'frontend/trend/omission-heatmap.html'),
    '/audit-dashboard':  os.path.join(HTML_DIR, 'audit-dashboard.html'),
    '/head-tail-analysis': os.path.join(HTML_DIR, 'head-tail-analysis.html'),
}

# 门户页面中的链接（必须全部可访问）
PORTAL_LINKS = [
    '/lottery', '/fund', '/stock', '/football',
    '/workbench', '/control-center', '/ai-agent', '/sync',
    '/smart-coder',
    '/金水谣助手使用说明.html',
    '/金水谣助手提示词库.html',
]


def check_routes():
    """① 路由表与实际文件一致性：所有注册路由对应的文件必须存在"""
    errors = []
    all_routes = {}
    all_routes.update(KNOWN_SUBSYSTEM_PAGES)
    all_routes.update(KNOWN_GUIDE_PAGES)
    all_routes.update(KNOWN_EXTERNAL_PAGES)
    for route, filepath in all_routes.items():
        if not os.path.isfile(filepath):
            errors.append(f"  ROUTE {route} → 文件不存在: {filepath}")
    return errors


def check_html_assets():
    """② HTML 引用的静态资源存在性检测（仅限本地引用）"""
    errors = []
    html_dirs = [
        HTML_DIR,
        FRONTEND_DIR,
        os.path.join(BASE_DIR, 'frontend', 'guide'),
    ]
    # 收集所有 _shared 下的实际文件
    shared_dir = os.path.join(HTML_DIR, '_shared')
    shared_files = set()
    if os.path.isdir(shared_dir):
        for dirpath, dirnames, filenames in os.walk(shared_dir):
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), shared_dir)
                shared_files.add(rel.replace('\\', '/'))

    # 扫描所有 HTML 文件中的 script src 和 link href
    for html_dir in html_dirs:
        if not os.path.isdir(html_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(html_dir):
            for fn in filenames:
                if not fn.endswith('.html'):
                    continue
                fp = os.path.join(dirpath, fn)
                rel_html = os.path.relpath(fp, BASE_DIR)
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                # 查找 <script src="..."> 和 <link href="...">
                # 只检测明确引用静态资源的属性，排除导航/API链接
                static_exts = {'.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.woff', '.woff2', '.ttf'}
                for m in re.finditer(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', content):
                    ref = m.group(1)
                    if ref.startswith('http') or ref.startswith('//') or ref.startswith('data:') or ref.startswith('#'):
                        continue
                    ext = os.path.splitext(ref.split('?')[0].split('#')[0])[1].lower()
                    if ext not in static_exts:
                        continue  # 不是静态资源引用，跳过（如路由链接 <a href="/lottery">）
                    if '/open?' in ref:
                        continue
                    if ref.startswith('/'):
                        full = os.path.normpath(os.path.join(ROOT_DIR, ref.lstrip('/')))
                    else:
                        full = os.path.normpath(os.path.join(os.path.dirname(fp), ref))
                    if not os.path.isfile(full):
                        if 'echarts.min.js' in ref:
                            continue
                        errors.append(f"  ASSET {rel_html}: 引用不存在 {ref} ({full})")
    return errors


def check_git_sync():
    """③ 仓外文件修改后仓内是否同步：检查根目录关键文件与 repo 副本是否一致"""
    errors = []
    key_files = [
        '启动提示词.txt', '复制启动提示词.bat',
        '金水谣_纲.md', '金水谣_契.md', '金水谣_录.md',
        'AI协作交接中心.md',
        '金水谣助手门户.html',
    ]
    for fname in key_files:
        root_fp = os.path.join(ROOT_DIR, fname)
        repo_fp = os.path.join(BASE_DIR, fname)
        root_exists = os.path.isfile(root_fp)
        repo_exists = os.path.isfile(repo_fp)
        if root_exists and not repo_exists:
            errors.append(f"  GITSYNC: {fname} 在根目录存在但 repo 中没有！")
        elif root_exists and repo_exists:
            root_mtime = os.path.getmtime(root_fp)
            repo_mtime = os.path.getmtime(repo_fp)
            if root_mtime > repo_mtime:
                errors.append(f"  GITSYNC: {fname} 根目录比 repo 新（{root_mtime} > {repo_mtime}），未同步！")
    return errors


def check_portal_links():
    """④ 门户页面所有链接是否可解析"""
    errors = []
    portal_fp = os.path.join(ROOT_DIR, '金水谣助手门户.html')
    if not os.path.isfile(portal_fp):
        return [f"  门户页面不存在: {portal_fp}"]
    with open(portal_fp, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    # API 路由（由 handler 函数处理，不映射到静态文件）
    api_routes = {'/sync', '/open', '/health', '/status', '/api'}
    for m in re.finditer(r'href\s*=\s*"([^"]*)"', content):
        href = m.group(1)
        if href.startswith('http') or href.startswith('//') or href.startswith('#') or href.startswith('Jinshuiyao_Fixed/'):
            continue
        # 去掉 anchor 片段后再查
        href_clean = href.split('#')[0]
        # API 路由跳过检查
        if any(href_clean.startswith(r) for r in api_routes):
            continue
        # 检查路由是否存在
        if href_clean in KNOWN_SUBSYSTEM_PAGES:
            target = KNOWN_SUBSYSTEM_PAGES[href_clean]
        elif href_clean in KNOWN_GUIDE_PAGES:
            target = KNOWN_GUIDE_PAGES[href_clean]
        elif href_clean in KNOWN_EXTERNAL_PAGES:
            target = KNOWN_EXTERNAL_PAGES[href_clean]
        else:
            # 尝试静态文件查找
            full = os.path.normpath(os.path.join(ROOT_DIR, href_clean.lstrip('/')))
            if os.path.isfile(full):
                continue
            errors.append(f"  PORTALLINK: 门户中的链接 {href} 找不到对应路由或文件")
            continue
        if not os.path.isfile(target):
            errors.append(f"  PORTALLINK: 门户链接 {href} → 文件不存在 {target}")
    return errors


def check_shared_resources():
    """⑤ 共享资源完整性：_shared/ 不应缺少常用资源"""
    errors = []
    expected = [
        'css/theme.css',
        'js/topnav.js',
        'js/error-monitor.js',
        'js/jinshuiyao-echarts-theme.js',
        'js/compare-utils.js',
    ]
    for rel in expected:
        fp = os.path.join(HTML_DIR, '_shared', rel)
        if not os.path.isfile(fp):
            errors.append(f"  SHARED: 缺失 _shared/{rel}")
    return errors


def check_html_structure():
    """⑥ HTML 结构平衡：所有标签必须正确闭合（防卡片错位/布局错乱）"""
    from html.parser import HTMLParser

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'}

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.stack = []
            self.errors = []

        def handle_starttag(self, tag, attrs):
            if tag in VOID:
                return
            self.stack.append((tag, self.getpos()))

        def handle_endtag(self, tag):
            if tag in VOID:
                return
            if not self.stack:
                self.errors.append(f'多余 </{tag}> @{self.getpos()}')
                return
            if self.stack[-1][0] == tag:
                self.stack.pop()
            else:
                for i in range(len(self.stack) - 1, -1, -1):
                    if self.stack[i][0] == tag:
                        self.errors.append(
                            f'未闭合 <{self.stack[-1][0]}> @{self.stack[-1][1]} (遇 </{tag}> @{self.getpos()})')
                        del self.stack[i:]
                        break
                else:
                    self.errors.append(f'多余 </{tag}> @{self.getpos()}')

    errors = []
    html_dirs = [HTML_DIR, FRONTEND_DIR,
                 os.path.join(BASE_DIR, 'frontend', 'guide')]
    for html_dir in html_dirs:
        if not os.path.isdir(html_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(html_dir):
            for fn in sorted(filenames):
                if not fn.endswith('.html'):
                    continue
                fp = os.path.join(dirpath, fn)
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                p = P()
                p.feed(content)
                issues = list(p.errors)
                for tag, pos in p.stack:
                    issues.append(f'未闭合 <{tag}> @{pos}')
                if issues:
                    rel = os.path.relpath(fp, BASE_DIR)
                    for i in issues[:5]:
                        errors.append(f"  HTMLSTRUCT {rel}: {i}")
    return errors


def run_all():
    """运行全部检查"""
    checks = {
        '路由-文件一致性': check_routes,
        'HTML资源存在性': check_html_assets,
        'Git同步状态': check_git_sync,
        '门户链接可解析': check_portal_links,
        '共享资源完整性': check_shared_resources,
        'HTML结构平衡': check_html_structure,
    }
    all_ok = True
    report = []
    for name, fn in checks.items():
        errors = fn()
        if errors:
            all_ok = False
            report.append(f"[ERR] [{name}] ({len(errors)} 项)")
            for e in errors:
                report.append(e)
        else:
            report.append(f"[OK] [{name}] 全部通过")
    return all_ok, report


if __name__ == '__main__':
    # GBK 终端兼容：降级无法编码的字符
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    all_ok, report = run_all()
    print("=" * 50)
    print("  系统一致性检测报告")
    print("=" * 50)
    for line in report:
        print(line)
    print("=" * 50)
    if all_ok:
        print("  结论: [PASS] 所有检查通过，系统一致")
    else:
        print("  结论: [FAIL] 存在不一致，请修复后再操作")
        sys.exit(1)
