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
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)  # 模型/
HTML_DIR = os.path.join(BASE_DIR, 'jinshuiyao-guide')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')

# JS-20260925-03：AI 决策卡新鲜度阈值（天）。
# 决策卡是「上一个 AI 为什么这么改」的唯一载体，断档 = 后续 AI 检索到的全是旧结论。
# 之所以要机器盯着：入库链路本身是好的（经验箱那条三元组来源每天都在涨），
# 断的是「AI 收工时写卡」这一步——纯靠自觉的环节，30 天没人发现（实测 2026-08-26 停更）。
AI_DECISION_STALE_WARN_DAYS = 14

# JS-20261002-11：知识存储层「业务键数」最高水位基线（只升不降）。
# 为什么要基线而不是直接比"比上次少"：事故原型 MEMORY JS-20260925-06 —— data_maintenance
# 把 predictions.json 从 3258 条硬截成 200 条，单次看是"少了一点"，逐日累积才暴露。
# 用**最高水位**（只升不降）才能捕获"每天悄悄删一点"；用"比上次"会被"上次也少"骗过去。
KNOWLEDGE_STORE_WATERMARK = os.path.join(
    BASE_DIR, '金水谣数据', 'knowledge_store', '.watermark.json')


def _find_git():
    """探测 git 可执行文件（PATH 无 git 时回退常见安装路径）"""
    import shutil
    g = shutil.which('git')
    if g:
        return g
    for cand in [r'E:\Git\cmd\git.exe', r'C:\Program Files\Git\cmd\git.exe',
                 r'C:\Program Files (x86)\Git\cmd\git.exe']:
        if os.path.isfile(cand):
            return cand
    return 'git'


GIT = _find_git()

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
    '/audit-dashboard':  os.path.join(BASE_DIR, 'frontend/lottery/audit-dashboard.html'),
    '/head-tail-analysis': os.path.join(BASE_DIR, 'frontend/lottery/head-tail-analysis.html'),
    # A股情绪日报（与 static.py 路由一致：独立脚本每日生成，覆盖 deliverables 下的固定文件 · JS-20260811-03）
    '/daily-sentiment': os.path.join(ROOT_DIR, 'deliverables', 'A股情绪日报_最新.html'),
    '/stock/daily-sentiment': os.path.join(ROOT_DIR, 'deliverables', 'A股情绪日报_最新.html'),
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
    """③ 仓外文件修改后仓内是否同步：双向检查关键文件与 repo 副本是否一致
    mtime 只做方向提示，最终以内容哈希为准（坚果云同步会改写 mtime，
    2026-08-04 实测 mtime 差 102s 但内容一致，mtime 单判会误拦提交）"""
    errors = []
    key_files = [
        '启动提示词.txt', '复制启动提示词.bat',
        '金水谣_纲.md', '金水谣_契.md', '金水谣_录.md',
        'AI协作交接中心.md',
        '金水谣助手门户.html',
        # 2026-08-04 校准：总索引/经验箱是高频更新文档，补入双向检查（此前漏检）
        '工作留痕总索引.md',
        '金水谣数据/log/经验收集箱.md',
    ]
    import hashlib
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
            if root_mtime == repo_mtime:
                continue
            def md5(p):
                h = hashlib.md5()
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                return h.hexdigest()
            try:
                if md5(root_fp) == md5(repo_fp):
                    continue  # 内容一致，仅 mtime 因坚果云/拷贝漂移
            except OSError:
                continue
            if root_mtime > repo_mtime:
                errors.append(f"  GITSYNC: {fname} 根目录比 repo 新（{root_mtime} > {repo_mtime}），未同步！")
            elif repo_mtime > root_mtime:
                errors.append(f"  GITSYNC: {fname} repo 比根目录新（{repo_mtime} > {root_mtime}），未拷回根目录！")
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


# 已人工确认无害的组合类（2026-07-31 审查）：样式由基类/JS/inline 承担，
# 加类名只为语义标记。检查器不报这些。
KNOWN_HARMLESS_CLASSES = {
    # workbench 视图容器：切换靠 .view.active + JS classList
    'kb-view', 've-view', 'cm-view', 'collab-view', 'mem-view',
    'kb-library-tabs', 'kb-tab', 'kb-content',
    # 页面容器：JS 注入 CSS 或 inline style 兜底
    'cu-app', 'cu-error',
    'api-panel', 'api-desc', 'api-header', 'api-path', 'api-list-item',
    # 通用辅助类（视觉由 theme 变量/父级承担）
    'muted', 'footer', 'sub', 'flex', 'pulse', 'primary', 'tabs', 'tab',
    'active', 'tab-content', 'tab-pane', 'grid2', 'grid4', 'stat-grid',
    'legend', 'scroll-x', 'num-grid', 'hidden', 'btn-primary', 'btn-sm',
    'flex-row', 'card-title', 'header', 'time', 'page-title', 'page-sub',
    'stats', 'stat-card', 'neutral', 'lbl', 'val', 'card-icon',
    'section-title', 'back', 'tag', 'header-bar', 'controls', 'stat-item',
    'chart-wrap', 'chart-tip', 'trend-chart', 'table-wrap', 'filter-row',
    'summary-grid', 'price-grid', 'idx-card', 'name', 'chart-card',
    'factor-grid', 'mt12', 'indicator-grid', 'info-grid', 'brand', 'spacer',
    'ticker-box', 'sym-select', 'sym-name', 'live-price', 'live-chg',
    'mode-badge', 'static', 'ctrl', 'danger', 'panel', 'dot', 'body',
    'signals', 'bt-line', 'event-wrap', 'event-input', 'event-table',
    'event-summary', 'terminal', 'drawer', 'hint', 'grow', 'on', 'ch', 'cn',
    'p', 'pl', 'pv', 'si', 'sv', 'ssd', 'ssi', 's1', 's2', 's3', 's4',
    'back-link', 'loading', 'timeline', 'topbar', 'weights', 'scanlines',
    'filter-group', 'btn-amber', 'btn-green', 'btn-purple', 'btn-run',
    'btn-row', 'btn-mini', 'tag-active', 'tag-blue', 'tag-core', 'tag-dev',
    'tag-green', 'tag-purple', 'tag-red', 'tag-shield', 'tag-v4',
    'tag-yellow', 'stat-blue', 'stat-green', 'stat-red', 'stat-yellow',
    'gen-area', 'manage-area', 'priority-body', 'modal-section-content',
    'dislike-btn', 'like-btn', 'download-btn', 'api-panel',
    # 动态拼接前缀（JS 生成）
    'c-', 'ci-', 'sqi-', 'af-', 'cm-', 'cu-', 'kb-', 've-', 'sc-', 'ws-',
}


def check_css_classes(changed_files=None):
    """⑦ CSS 类自洽性检查：页面使用的类必须在其引用的 CSS 或内联 <style> 中有定义。
    规则：每个 HTML 页面的静态 class 属性（排除 <script> 内动态模板）必须能在
    ① 该页面 <link> 引用的本地 css 文件 或 ② 页面内 <style> 块 中找到定义。
    覆盖：.lot-btn 42 处使用但从未定义 → 裸样式类。
    changed_files: 若传入（pre-commit 增量模式），只检查这些文件中【新增行】引入的类，
    存量未定义类不阻塞（登记于 error_registry E-003 待清理），新引入的必拦截。
    """
    errors = []
    html_dirs = [HTML_DIR, FRONTEND_DIR,
                 os.path.join(BASE_DIR, 'frontend', 'guide')]
    RE_DEF = re.compile(r'\.([A-Za-z_][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])')
    RE_CLASS = re.compile(r'class\s*=\s*["\']([^"\']+)["\']')
    RE_SCRIPT = re.compile(r'<script[^>]*>.*?</script>', re.S)
    RE_STYLE = re.compile(r'<style[^>]*>(.*?)</style>', re.S)
    RE_LINK = re.compile(r'<link[^>]*rel\s*=\s*["\']stylesheet["\'][^>]*>')

    def _defined_classes(fp, content):
        defined = set()
        for m in RE_LINK.finditer(content):
            href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', m.group(0))
            if not href_m:
                continue
            href = href_m.group(1)
            if href.startswith('http') or href.startswith('//'):
                continue
            if href.startswith('/'):
                css_fp = os.path.normpath(os.path.join(ROOT_DIR, href.lstrip('/')))
            else:
                css_fp = os.path.normpath(os.path.join(os.path.dirname(fp), href))
            if not os.path.isfile(css_fp):
                continue  # 资源存在性由检查②负责
            try:
                css_txt = open(css_fp, 'r', encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for dm in RE_DEF.finditer(css_txt):
                defined.add(dm.group(1))
        for m in RE_STYLE.finditer(content):
            for dm in RE_DEF.finditer(m.group(1)):
                defined.add(dm.group(1))
        return defined

    def _page_classes(content):
        body = RE_SCRIPT.sub('', content)
        out = set()
        for m in RE_CLASS.finditer(body):
            if '${' in m.group(1) or '<%' in m.group(1):
                continue
            for c in m.group(1).split():
                if re.match(r'^[A-Za-z_][A-Za-z0-9_-]*$', c):
                    out.add(c)
        return out

    for html_dir in html_dirs:
        if not os.path.isdir(html_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(html_dir):
            for fn in sorted(filenames):
                if not fn.endswith('.html'):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    content = open(fp, 'r', encoding='utf-8', errors='replace').read()
                except Exception:
                    continue
                rel = os.path.relpath(fp, BASE_DIR).replace('\\', '/')

                defined = _defined_classes(fp, content)
                page_classes = _page_classes(content)
                missing = (page_classes - defined) - KNOWN_HARMLESS_CLASSES
                if not missing:
                    continue

                if changed_files is None:
                    # 全量模式：存量未定义类登记告警，不阻塞（待 error_registry E-003 清理）
                    for c in sorted(missing):
                        errors.append(f"  CSSCLASS-STALE {rel}: 类 {c} 未定义（存量，登记待清理）")
                else:
                    # 增量模式：只检查本次变更文件的新增行
                    if rel not in changed_files:
                        continue
                    try:
                        import subprocess
                        # 变更行（pre-commit 下用索引对比）
                        base_cmd = [GIT, 'diff', '--cached', '-U0', '--', rel]
                        proc = subprocess.run(base_cmd, capture_output=True, text=True,
                                              encoding='utf-8', errors='replace', cwd=BASE_DIR)
                        diff = proc.stdout
                    except Exception:
                        diff = ''
                    added_lines = set()
                    for line in diff.splitlines():
                        if line.startswith('+') and not line.startswith('+++'):
                            for m in RE_CLASS.finditer(line):
                                if '${' in m.group(1) or '<%' in m.group(1):
                                    continue
                                for c in m.group(1).split():
                                    if re.match(r'^[A-Za-z_][A-Za-z0-9_-]*$', c):
                                        added_lines.add(c)
                    for c in sorted(missing & added_lines):
                        errors.append(
                            f"  CSSCLASS {rel}: 本次新增了类 {c} 但本页引用 CSS/内联样式中无定义"
                            f"（要么补样式定义，要么去掉该 class）")
    # 去重
    seen = set()
    uniq = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def check_doc_tables():
    """⑥ 交接中心/总索引/经验箱表格管道数一致性：防 AI 拼接破损行复发
    （W63补23||补24 拼接行事件后加入 · 2026-08-04 校准）
    注：\\| 转义管道不计数（说明列内嵌代码如 vars\\|\\|{} 属合法）"""
    errors = []
    targets = [
        os.path.join(BASE_DIR, 'AI协作交接中心.md'),
        os.path.join(BASE_DIR, '工作留痕总索引.md'),
        os.path.join(BASE_DIR, '金水谣数据/log/经验收集箱.md'),
    ]
    for fp in targets:
        if not os.path.isfile(fp):
            continue
        with open(fp, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()

        def pipes(line):
            """去掉 \\| 转义后再数管道数"""
            return line.replace('\\|', '').count('|')

        bad = []
        i = 0
        while i < len(lines):
            s = lines[i].strip()
            if s.startswith('|'):
                n = pipes(lines[i])
                j = i
                while j < len(lines) and lines[j].strip().startswith('|'):
                    c = pipes(lines[j])
                    if '---' not in lines[j] and c != n:
                        bad.append(f"{os.path.basename(fp)}:L{j+1} 管道数 {c} != {n} :: {lines[j].strip()[:60]}")
                    j += 1
                i = j
            else:
                i += 1
        if bad:
            errors.append(f"  DOC-TABLE: {os.path.basename(fp)} 表格管道数不一致（{len(bad)} 行）")
            errors.extend('    ' + b for b in bad[:8])
    return errors


def _parse_code_consts(path):
    """用 AST 提取模块级数值常量（只取 int/float 字面量，排除 bool）"""
    import ast
    out = {}
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        # 同时支持 `X = 1.0`(Assign) 与 `X: float = 1.0`(AnnAssign)
        # ——只认 Assign 会让带注解的常量被静默跳过，造成"闸门假绿"
        targets, value = [], None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        v = _num_value(value)
        if v is None:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = v
    return out


def _num_value(node):
    """取数值字面量，含负号与**常量表达式**。

    支持四种 AST 形态，漏一种即"静默漏检"（常量写进 §三 却从不被校验 = 闸门假绿）：
      1. `X = 1`            → Constant
      2. `X = -30.0`        → UnaryOp(USub, ...)，**不是** Constant（漏了它负数全丢）
      3. `X = 2 * 1024 * 1024` → BinOp（`2MB`、秒数 `60 * 60 * 24` 都是这么写的，
                                  JS-20261002-11 发现：这类常量此前整个逃过校验）
      4. `X: float = 1.0`   → AnnAssign（在 _parse_code_consts 里处理）

    ⚠️ 故意不收 Div：`X = 1 / 3` 会算出 0.333333，`%g` 格式化后与文档写法难对齐，
    容易变成"改不动的假警"，故保守跳过。
    """
    import ast as _ast
    if isinstance(node, _ast.Constant):
        v = node.value
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return None
    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, (_ast.USub, _ast.UAdd)):
        v = _num_value(node.operand)
        if v is None:
            return None
        return -v if isinstance(node.op, _ast.USub) else v
    if isinstance(node, _ast.BinOp):
        lv, rv = _num_value(node.left), _num_value(node.right)
        if lv is None or rv is None:
            return None
        if isinstance(node.op, _ast.Mult):
            return lv * rv
        if isinstance(node.op, _ast.Add):
            return lv + rv
        if isinstance(node.op, _ast.Sub):
            return lv - rv
        # Div / Pow / Mod 等不收（见 docstring）
    return None


def _check_threshold_text(md_text, consts, watch, label):
    """校验 md 文本中每个被 watch 的常量行，是否含有代码里的实际数值"""
    errors = []
    norm = lambda s: s.replace('\u2212', '-').replace('\u2013', '-').replace('\uff0d', '-')
    lines = md_text.splitlines()
    for name in watch:
        if name not in consts:
            continue
        val = consts[name]
        hit = [ln for ln in lines if name in ln]
        if not hit:
            errors.append("  STD-THRESHOLD: %s 未登记常量 %s（标准唯一真源 §三 阈值表应登记）" % (label, name))
            continue
        want = ('%g' % val) if isinstance(val, float) else str(val)
        if not any(want in norm(ln) for ln in hit):
            errors.append("  STD-THRESHOLD: %s 常量 %s 代码值=%s 与文档登记不一致 → 以代码为准，回来修 §三 阈值表"
                          % (label, name, want))
    return errors


def check_std_thresholds():
    """⑦ 标准唯一真源 §三「数值阈值表」 vs 代码常量 一致性
    立标准最大的风险是文档漂移：改了代码不改文档，就又变成两套口径
    （这正是"每个 AI 各有各的标准"的根因）。本检查让机器保证
    「代码常量 = 唯一事实源，文档只能跟随」。
    安全设计：本检查自身任何异常一律降级为跳过，绝不因它而阻断提交。"""
    try:
        # JS-20260920-15：监视清单改为「多文件 → 多常量」，之前只盯 fund_profile_risk.py
        # 一个文件，导致 data_truth_guard 的新鲜度阈值提常量后闸门照样假绿（看不见）。
        # 路径铁律：BASE_DIR 就是仓库根（见第 22 行，其它检查项都直接拼 'frontend/...'），
        # 再拼一层 'Jinshuiyao_Fixed' 会全部找不到 → 静默 return [] → **闸门 100% 假绿**。
        # （JS-20260920-15 探测发现：本检查自上线起其实一次都没真正跑过。）
        watch_map = {
            os.path.join(BASE_DIR, 'domains', 'fund', 'fund_profile_risk.py'): [
                'SCALE_DANGER_YI', 'SCALE_WARN_YI', 'SCALE_DROP_WARN_PCT',
                'SCALE_SURGE_WARN_PCT', 'MANAGER_CHANGE_WARN_DAYS',
                'MANAGER_TTL_HOURS', 'SCALE_TTL_DAYS', 'PURCHASE_TTL_HOURS',
            ],
            # JS-20260924-02：该文件已迁到 core/infra/ 下，旧路径会让本闸门「源文件缺失」而失效
            os.path.join(BASE_DIR, 'core', 'infra', 'data_truth_guard.py'): [
                'MATCH_STALE_WARN_DAYS', 'MATCH_STALE_FAIL_DAYS', 'LOT_STALE_WARN_DAYS',
            ],
            # JS-20260924-02：Calmar 回撤下限（回撤≈0 时比值发散，留白优于伪精确值）
            os.path.join(BASE_DIR, 'scripts', 'daily_fund_monitor.py'): [
                'CALMAR_MIN_DRAWDOWN_PCT',
                # JS-20260924-08 批3·切片B：加仓规则引擎阈值（TRAE 七期全稳口径）
                'ADD_DROP_TIER1_PCT', 'ADD_DROP_TIER2_PCT',
                'ADD_AMOUNT_TIER1', 'ADD_AMOUNT_TIER2',
            ],
            os.path.join(BASE_DIR, 'tools', 'code_health_gate.py'): [
                'MAX_FUNC_LINES', 'MAX_SILENT_SWALLOW', 'MAX_BARE_EXCEPT',
            ],
            # JS-20260924-28：留痕行数骤降闸阈值（防误提交并发会话重写中的中间态）
            os.path.join(BASE_DIR, 'tools', 'closeout_gate.py'): [
                'TRAIL_SHRINK_RATIO', 'TRAIL_SHRINK_MIN_LINES',
                # JS-20260925-10：第 10 闸（未跟踪源码）报告条数上限
                'UNTRACKED_REPORT_MAX',
            ],
            # JS-20260925-02：知识网关相关度门槛（limit 修好后紧接着补的质量闸，
            # 否则"截断生效了但截断的全是噪声"，等于只修了一半）
            os.path.join(BASE_DIR, 'core', 'infra', 'knowledge_gateway.py'): [
                'KB_RELEVANCE_RATIO', 'KB_MIN_SCORE_ABS',
            ],
            # JS-20260925-03：AI 决策卡新鲜度阈值
            os.path.join(BASE_DIR, 'tools', 'check_consistency.py'): [
                'AI_DECISION_STALE_WARN_DAYS',
            ],
            # JS-20260925-05：健康看门狗阈值（把"孤儿检查器"接进自动链路后，
            # 阈值同样必须受闸门约束，否则又是一处改代码不改文档的漂移）
            os.path.join(BASE_DIR, 'tools', 'health_watch.py'): [
                'ASSET_STALE_DAYS', 'TASK_LATE_FACTOR',
                'ARCHIVE_BASELINE_MIN_COUNT',
            ],
            # JS-20260925-06：档案清理守卫阈值（predictions.json 被硬截 3258→200 的事故）。
            # 档案保留策略的每一处数字都要能被闸门盯住——这次事故的根因之一就是
            # 硬编码魔数 200 从来没进过任何文档。
            os.path.join(BASE_DIR, 'core', 'infra', 'archive_guard.py'): [
                'ARCHIVE_SHRINK_GUARD_RATIO', 'DEFAULT_ARCHIVE_KEEP_DAYS',
            ],
            # JS-20261002-11：知识存储层阈值（WAL + 版本链 + 软删除）。
            # 立这些常量就是为了不再出现"硬编码魔数从来没进过任何文档"——
            # 那正是 archive_guard 那次事故的根因，新建存储层必须一开始就受闸约束。
            os.path.join(BASE_DIR, 'core', 'infra', 'knowledge_store.py'): [
                'SCHEMA_VERSION', 'RETRY_MAX', 'RETRY_BASE_SLEEP',
                'COMPACT_SHRINK_GUARD', 'DEFAULT_TTL_DAYS', 'MAX_LINE_BYTES',
            ],
            os.path.join(BASE_DIR, 'core', 'infra', 'scheduler.py'): [
                'PRED_ARCHIVE_KEEP_DAYS', 'PRED_ARCHIVE_MAX_RECORDS',
            ],
            os.path.join(BASE_DIR, 'core', 'ai', 'agent_vector_memory.py'): [
                'VECTOR_MEM_KEEP_DAYS', 'VECTOR_MEM_MAX_ENTRIES',
            ],
            os.path.join(BASE_DIR, 'core', 'ai', 'ai_agent.py'): [
                'AGENT_MEM_KEEP_DAYS', 'AGENT_MEM_MAX_RECORDS',
            ],
            # JS-20260925-07：备份跳过的告警阈值（备份整包报废的伴生修复）
            os.path.join(BASE_DIR, 'utils', 'data_backup.py'): [
                'BACKUP_SKIP_WARN_COUNT',
            ],
        }
        consts = {}
        watch = []
        errors = []
        for code, names in watch_map.items():
            # 找不到源文件必须**报警**，不能静默跳过——跳过只会伪造出一片绿
            if not os.path.isfile(code):
                errors.append("  STD-THRESHOLD: 源文件缺失 %s（闸门无法工作，路径基准可能又错了）" % code)
                continue
            consts.update(_parse_code_consts(code))
            watch.extend(names)
        if not consts:
            return errors if errors else []
        targets = [
            (os.path.join(BASE_DIR, '金水谣_标准唯一真源.md'), '仓库真源'),
            (os.path.join(os.path.dirname(BASE_DIR), '金水谣_标准唯一真源.md'), '根镜像'),
        ]
        for fp, label in targets:
            if not os.path.isfile(fp):
                errors.append("  STD-THRESHOLD: %s 缺失 %s" % (label, fp))
                continue
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                errors.extend(_check_threshold_text(f.read(), consts, watch, label))
        return errors
    except Exception as e:  # 绝不因本检查阻断提交
        print("  STD-THRESHOLD: 检查自身异常，已跳过（%s: %s）" % (type(e).__name__, e))
        return []


def check_prize_rules_freshness():
    """⑩ 彩票官方中奖规则新鲜度（JS-20260924-34）

    为什么要有这一项：官方奖级此前**写死在前端 JS 里**，既没有日期也没有提醒，
    规则过时了谁都不知道。现规则收敛到 `config/lottery_prize_rules.json` 并带
    `updated_at`；本检查在超过 `stale_days`（默认 180 天）时告警，提醒人工核对
    官方公告后更新——**只提醒，绝不自动改写规则**（自动抓官方站点一旦页面改版
    就会静默抓错，比不更新更危险）。

    能变绿：把 updated_at 改成核对当日即可，属「可行动的告警」而非噪音。
    读不出日期/文件缺失一律按过期处理（静默才是敌人）。
    """
    try:
        sys.path.insert(0, BASE_DIR)
        from utils.lottery_prize import rules_staleness, load_rules
        rules = load_rules(force=True)
        if not isinstance(rules, dict):
            return ["  PRIZE-RULES: 官方奖级规则文件读不到（%s）" %
                    os.path.join(BASE_DIR, 'config', 'lottery_prize_rules.json')]
        st = rules_staleness(rules)
        if not st.get("is_stale"):
            return []
        days = st.get("days")
        return ["  PRIZE-RULES: 中奖规则已 %s未核对（≥%s 天）→ 请核对官方公告后更新 "
                "config/lottery_prize_rules.json 的 updated_at 与 version" %
                ("未知天数" if days is None else "%d 天" % days, st.get("stale_days"))]
    except Exception as e:  # 检查自身异常必须报出来，不能静默放行
        return ["  PRIZE-RULES: 检查自身异常（%s: %s）" % (type(e).__name__, e)]


def check_ai_decisions_freshness():
    """⑪ AI 决策卡新鲜度（JS-20260925-03）

    为什么要有这一项：`金水谣数据/log/ai_decisions.md` 是「上一个 AI 为什么这么改」
    的唯一载体，由 `extract_from_ai_decisions` 自动转成知识卡 + 三元组供后续 AI 检索。
    但它只能检测"文件变了没"——**没人往里写，它就一直安静**，于是断档 30 天
    （实测最后一条停在 2026-08-26）无人察觉，期间所有 AI 检索到的都是旧结论。

    这是典型的「链路是好的、源头没人喂」型停滞，靠人记必漏，必须机器盯。

    能变绿：补一张决策卡即可（append-only），属「可行动的告警」而非噪音。
    读不出日期 / 文件缺失一律按过期处理（静默才是敌人）。
    """
    path = os.path.join(BASE_DIR, '金水谣数据', 'log', 'ai_decisions.md')
    try:
        if not os.path.isfile(path):
            return ["  AI-DECISION: 决策卡文件缺失（%s）→ 无法判断新鲜度" % path]
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        dates = re.findall(r'^###\s*(\d{4}-\d{2}-\d{2})', text, re.M)
        if not dates:
            return ["  AI-DECISION: 决策卡里解析不出任何 `### YYYY-MM-DD` 标题 → 按过期处理"]
        last = max(dates)
        try:
            import datetime as _dt
            d = _dt.date(*[int(x) for x in last.split('-')])
            days = (_dt.date.today() - d).days
        except Exception:
            return ["  AI-DECISION: 最新卡片日期 %s 解析失败 → 按过期处理" % last]
        if days > AI_DECISION_STALE_WARN_DAYS:
            return ["  AI-DECISION: 决策卡已 %d 天无新增（最新 %s，阈值 %d 天）→ "
                    "补一张决策卡即可变绿：向 %s 追加 `### YYYY-MM-DD ...` 十字段卡片" %
                    (days, last, AI_DECISION_STALE_WARN_DAYS, path)]
        return []
    except Exception as e:  # 检查自身异常必须报出来，不能静默放行
        return ["  AI-DECISION: 检查自身异常（%s: %s）" % (type(e).__name__, e)]


# ===== ⑫ 告警落盘契约（JS-20260925-08 复盘）=====
# 背景：server/__init__.py 提示「详见 金水谣数据/log/selfcheck.log」，但当时全仓
# 只有一处**读**（handlers/health.py），没有任何代码在写 → 用户按提示去找一个
# 根本不存在的文件，比没有告警更浪费时间。
# 铁律：产生 / 拦截 / 呈现三层都要通；「告警指向空气」是最隐蔽的一种断链。
ALERT_HINT_RE = re.compile(
    r'详见\s*([^\s，。；、）)\'"、]+\.(?:log|json|md|txt|csv))')
# 只有出现这些动词，才认为"确实在写"这个文件
WRITE_VERBS_RE = re.compile(
    r"(open\s*\([^)]*['\"][wa]\+?['\"]|write_text|write_bytes|\.write\s*\(|"
    r"json\.dump|safe_write_json|safe_append|to_csv|append_text)")
ALERT_SCAN_SKIP_DIRS = ('.git', '__pycache__', 'node_modules', 'venv', '.venv',
                        'archive', '90_归档文档', 'obsidian-vault')
# 正则可能误提的散文式提示（如「详见交接中心§六」），显式排除
ALERT_SINK_ALLOWLIST = ('交接中心', '上方', '下文', '附录', '标准')


def _iter_py_files():
    """遍历仓库内 .py（跳过归档/副本/虚拟环境）。"""
    for dp, dns, fns in os.walk(BASE_DIR):
        dns[:] = [d for d in dns if d not in ALERT_SCAN_SKIP_DIRS]
        for fn in sorted(fns):
            if fn.endswith('.py'):
                yield os.path.join(dp, fn)


def _read_py_cache():
    """预读所有 .py → ([(相对路径, 行列表)], [读取失败项])。

    读失败必须记账回传：静默跳过会让"扫描覆盖不全"伪装成"契约都满足"。
    """
    out, failed = [], []
    for fp in _iter_py_files():
        rel = os.path.relpath(fp, BASE_DIR).replace('\\', '/')
        if rel.startswith('tests/'):
            continue
        try:
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                out.append((rel, f.read().splitlines()))
        except Exception as e:
            failed.append('%s (%s)' % (rel, type(e).__name__))
    return out, failed


def _find_writers(base, files):
    """返回写入者相对路径集合。

    两段式判定（为什么不能只比"同一行"）：真实代码里路径通常先赋给常量
    （`SELFCHECK_LOG = os.path.join(..., 'selfcheck.log')`），真正执行写入的是
    `open(SELFCHECK_LOG, 'a')` —— 两行相距几十行。只比同一行会把已经修好的
    落盘逻辑误判成"没人写"（假警比没告警更坏）。
    """
    consts, direct = set(), set()
    for rel, lines in files:
        for ln in lines:
            if base not in ln:
                continue
            if WRITE_VERBS_RE.search(ln):
                direct.add(rel)
            m = re.match(r'^\s*([A-Z][A-Z0-9_]{2,})\s*=', ln)
            if m:
                consts.add(m.group(1))
    writers = set(direct)
    for c in consts:
        for rel, lines in files:
            for ln in lines:
                if c in ln and WRITE_VERBS_RE.search(ln):
                    writers.add(rel)
                    break
    return writers


def check_alert_sink_writers():
    """⑫ 告警落盘契约：提示"详见 X"的 X，必须有代码真的在写它。

    能变绿：给该 sink 补一个真实写入调用即可，属可行动告警而非噪音。
    """
    files, failed = _read_py_cache()
    errors = ['  ALERT-SINK: 读取失败 %s' % f for f in failed]
    sinks = {}
    for rel, lines in files:
        if rel == 'tools/check_consistency.py':
            continue
        for ln in lines:
            for m in ALERT_HINT_RE.finditer(ln):
                p = m.group(1)
                if any(w in p for w in ALERT_SINK_ALLOWLIST):
                    continue
                base = os.path.basename(p.replace('\\', '/'))
                sinks.setdefault(base, set()).add(rel)
    for base, srcs in sorted(sinks.items()):
        writers = _find_writers(base, files)
        if not writers:
            errors.append(
                "  ALERT-SINK: 「详见 …/%s」由 %s 提示，但全仓找不到任何写入者 → "
                "告警指向空气（用户会去看一个不存在的文件）。修复：补真实写入调用，"
                "或把提示改成指向确实会生成的文件" % (base, '、'.join(sorted(srcs))))
    return errors


def _read_watermark():
    """读知识存储水位基线。文件缺失 = 首次运行，返回 0（不算跌）。"""
    if not os.path.isfile(KNOWLEDGE_STORE_WATERMARK):
        return {}
    try:
        with open(KNOWLEDGE_STORE_WATERMARK, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        # 基线损坏不能让整库变红，按"无基线"处理（下次写入会自愈）
        return {}


def check_knowledge_store():
    """⑬ 知识存储一致性（JS-20261002-11）

    为什么要有这一项：`core/infra/knowledge_store.py` 是本轮新建的版本化存储层，
    自带 `verify()/find_expired()/compact()` 三道自检——**但没有任何东西定期跑它们**。
    这正是 MEMORY「孤儿检查器潜伏 46 天」的原型：写了检查不接调用链 = 没有检查。
    本项把它接进一致性门禁，保证每天有人看见。

    查三件事（每一项都能变绿，不是噪音）：
      1. **日志可解析 + 索引对得上**（verify）→ 索引是物化视图，坏了 `refresh()` 重建即可
      2. **过期条目**（expires_at 到期）→ `deprecate()` 标记或更新 expires_at
      3. **业务键骤降** → 用最高水位基线守（只升不降），从 `archive/` 恢复

    边界：库不存在（从未写入）不算异常——空库恒绿是"还没数据"，不是"数据坏了"。
    """
    try:
        sys.path.insert(0, BASE_DIR)
        from core.infra import knowledge_store as ks
    except Exception as e:
        # 导入失败必须报出来：存储层校验不了 ≠ 存储层健康
        return ["  KB-STORE: 模块导入失败（%s: %s）→ 无法校验，按失败处理" %
                (type(e).__name__, e)]

    errors = []
    try:
        rec = ks.records_path()
        if not os.path.isfile(rec):
            return []           # 从未写入，空库不算异常
        v = ks.verify()
        st = ks.stats()
    except Exception as e:
        return ["  KB-STORE: 读取存储失败（%s: %s）→ 不静默放行" % (type(e).__name__, e)]

    if not v.get("ok"):
        if v.get("bad_lines"):
            errors.append(
                "  KB-STORE: %d 行无法解析（多为崩溃残留的半行）→ 归档后重写该行；"
                "日志是权威，宁可丢一行也不能整库失效" % len(v["bad_lines"]))
        if v.get("bad_checksum"):
            errors.append(
                "  KB-STORE: %d 条 checksum 与 payload 不符（内容被外部改动）→ "
                "用 history() 找就近版本 rollback()" % len(v["bad_checksum"]))
        if v.get("index_mismatch"):
            errors.append(
                "  KB-STORE: %d 条索引 offset 与日志对不上 → 调用 "
                "core.infra.knowledge_store.refresh() 重建索引（索引是物化视图，可安全重建）"
                % len(v["index_mismatch"]))

    expired = st.get("expired") or 0
    if expired:
        errors.append(
            "  KB-STORE: %d 条已过期（expires_at 早于今天）→ 用 deprecate() 标记墓碑，"
            "或确认仍有效则更新 expires_at（只提醒不自动删）" % expired)

    # 骤降守卫：最高水位基线，只升不降
    keys_now = int(st.get("keys") or 0)
    prev = int(_read_watermark().get("max_keys") or 0)
    if keys_now > prev:
        try:
            d = os.path.dirname(KNOWLEDGE_STORE_WATERMARK)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(KNOWLEDGE_STORE_WATERMARK, 'w', encoding='utf-8') as f:
                json.dump({"max_keys": keys_now,
                           "updated_at": time.strftime('%Y-%m-%d %H:%M:%S')}, f,
                          ensure_ascii=False)
        except Exception as e:
            # 基线写不进去 = 骤降守卫失效，等于没守卫 → 必须报出来
            errors.append("  KB-STORE: 水位基线落盘失败（%s: %s）→ 骤降守卫失效" %
                          (type(e).__name__, e))
    elif prev and keys_now < prev * ks.COMPACT_SHRINK_GUARD:
        errors.append(
            "  KB-STORE: 业务键从最高水位 %d 骤降到 %d（低于 %.0f%%）→ 疑似误删或误压实，"
            "请先从 金水谣数据/knowledge_store/archive/ 恢复；确认是有意清理后再重置基线 %s"
            % (prev, keys_now, ks.COMPACT_SHRINK_GUARD * 100, KNOWLEDGE_STORE_WATERMARK))
    return errors


def run_all(changed_files=None):
    """运行全部检查。changed_files: pre-commit 增量模式的变更文件列表（相对 BASE_DIR）"""
    css_fn = check_css_classes
    checks = {
        '路由-文件一致性': check_routes,
        'HTML资源存在性': check_html_assets,
        'Git同步状态': check_git_sync,
        '门户链接可解析': check_portal_links,
        '共享资源完整性': check_shared_resources,
        'HTML结构平衡': check_html_structure,
        'CSS类定义完整': lambda: css_fn(changed_files),
        '文档表格管道数': check_doc_tables,
        '标准阈值-代码常量': check_std_thresholds,
        '彩票奖级规则新鲜度': check_prize_rules_freshness,
        'AI决策卡新鲜度': check_ai_decisions_freshness,
        '告警落盘契约': check_alert_sink_writers,
        '知识存储一致性': check_knowledge_store,
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
    changed = None
    if '--changed' in sys.argv:
        # pre-commit 增量模式：取暂存区变更的 HTML
        try:
            import subprocess
            proc = subprocess.run([GIT, 'diff', '--cached', '--name-only'],
                                  capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', cwd=BASE_DIR)
            changed = {l.strip() for l in proc.stdout.splitlines() if l.strip()}
        except Exception:
            changed = None
    all_ok, report = run_all(changed)
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