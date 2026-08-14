# -*- coding: utf-8 -*-
"""生成 quick-search.js 页面索引（注入式）：读 page_registry.json + 各页 <title>，
只替换文件内 window.JSY_SEARCH_INDEX = [...] 索引段，保留搜索逻辑部分。
用法: py -3.14 tools/gen_quick_search_index.py
未来新增页面后重跑本脚本即可刷新 Ctrl+K 搜索索引。"""
import io, os, re, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
registry = json.load(open(os.path.join(BASE, 'config', 'page_registry.json'), encoding='utf-8'))
pages = registry['pages']

idx = []
missing_title = []
for p in pages:
    route = p.get('route', '')
    desc = p.get('desc', '')
    cat = p.get('category', '')
    path = p.get('path', '')
    title = route
    try:
        src = open(os.path.join(BASE, path), encoding='utf-8').read()
        m = re.search(r'<title>(.*?)</title>', src, re.S)
        if m:
            title = m.group(1).strip()
        else:
            missing_title.append(route)
    except Exception:
        missing_title.append(route)
    idx.append({'n': title, 'r': route, 'd': desc, 'c': cat})

data = 'window.JSY_SEARCH_INDEX = [\n' + ',\n'.join(
    '  {{"n": {n}, "r": {r}, "d": {d}, "c": {c}}}'.format(
        n=json.dumps(x['n'], ensure_ascii=False),
        r=json.dumps(x['r'], ensure_ascii=False),
        d=json.dumps(x['d'], ensure_ascii=False),
        c=json.dumps(x['c'], ensure_ascii=False))
    for x in idx) + '\n];'

out = os.path.join(BASE, 'jinshuiyao-guide', '_shared', 'js', 'quick-search.js')
src = open(out, encoding='utf-8').read()
pat = re.compile(r'window\.JSY_SEARCH_INDEX\s*=\s*\[[\s\S]*?\];\n?')
if pat.search(src):
    new_src = pat.sub(data + '\n', src)
    open(out, 'w', encoding='utf-8').write(new_src)
    print(f'索引注入完成: {len(idx)} 页，逻辑保留={("__jsyQuickSearchLoaded" in new_src)}')
else:
    open(out, 'w', encoding='utf-8').write(data + '\n' + src)
    print(f'未找到索引段，已前置写入: {len(idx)} 页')
print('缺 title 的路由:', missing_title if missing_title else '无')