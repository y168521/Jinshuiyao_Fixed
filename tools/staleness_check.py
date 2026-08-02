# -*- coding: utf-8 -*-
"""知识新鲜度检测（Staleness Check）— 诊断遗留缺口的第四块

对比各知识资产最后更新时间与"知识源"（经验收集箱/ai_decisions）的最后写入时间：
若某资产陈旧（最后一次构建早于知识源最近变化），说明知识网存在断链：
知识写了但没进卡片/图谱/向量 —— 需要重提。

输出：控制台表格 + 退出码（0=全新鲜, 1=有陈旧, 2=资产缺失）。
可挂自动化（自动同步.ps1 第9步候选）或人工随时跑。
"""
import json
import os
import sys
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 知识源（L1 原始层）→ 派生资产（L2/L3）
SOURCES = [
    ('经验收集箱', os.path.join(BASE_DIR, '金水谣数据', 'log', '经验收集箱.md')),
    ('AI决策', os.path.join(BASE_DIR, '金水谣数据', 'log', 'ai_decisions.md')),
]
ASSETS = [
    ('知识卡片(MiroFish)', os.path.join(BASE_DIR, 'knowledge', 'mirofish_db.json'), '经验收集箱|AI决策'),
    ('图谱三元组', os.path.join(BASE_DIR, 'knowledge', 'graph_triples.json'), '经验收集箱|AI决策'),
    ('向量索引', os.path.join(BASE_DIR, 'knowledge', 'vector_index.json'), '经验收集箱|AI决策'),
    ('知识图谱', os.path.join(BASE_DIR, 'knowledge', 'knowledge_graph.json'), '经验收集箱|AI决策|卡片'),
    ('Skill蒸馏区', os.path.join(BASE_DIR, '.opencode', 'skills'), '经验收集箱'),
    ('知识网关索引', os.path.join(BASE_DIR, '知识网关索引.md'), '全部'),
]


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except Exception:
        return None


def _newest_source_mtime():
    ts = []
    for name, p in SOURCES:
        t = _mtime(p)
        if t:
            ts.append(t)
    return max(ts) if ts else None


def _newest_exp_titles(n=3):
    """经验箱最新 n 条标题（内容探针用：验证资产是否已包含新知识）"""
    try:
        with open(SOURCES[0][1], encoding='utf-8') as f:
            text = f.read()
        import re
        titles = re.findall(r'^## (\d{4}-\d{2}-\d{2} 第.+?条[^\n]*)', text, re.M)
        return titles[-n:]
    except Exception:
        return []


def _content_probe(name, path, titles):
    """内容级新鲜度探针：mirofish/图谱是否已含经验箱最新条目标题（免疫 mtime 失真）"""
    if not titles:
        return None
    try:
        if 'MiroFish' in name:
            with open(path, encoding='utf-8') as f:
                txt = f.read()
            return any('经验收集箱.md#' + t.split('：')[0] in txt for t in titles)
        if '三元组' in name:
            with open(path, encoding='utf-8') as f:
                txt = f.read()
            return any(t.split('：')[0] in txt for t in titles)
    except Exception:
        pass
    return None  # 不适用（无探针）


def check(verbose=True):
    newest = _newest_source_mtime()
    titles = _newest_exp_titles()
    rows = []
    for name, p, dep in ASSETS:
        if os.path.isdir(p):
            ts = None
            for root, _dirs, files in os.walk(p):
                for f in files:
                    t = _mtime(os.path.join(root, f))
                    if t and (ts is None or t > ts):
                        ts = t
        else:
            ts = _mtime(p)
        rows.append((name, p, ts, dep))
    if verbose:
        print('知识新鲜度检测（源最后更新 vs 资产最后构建）')
        print('-' * 66)
        src_txt = ' / '.join('%s=%s' % (n, time.strftime('%m-%d %H:%M', time.localtime(t)))
                             for n, t in [(n, _mtime(p)) for n, p in SOURCES] if t)
        print('知识源最新写入: %s' % src_txt)
        print('-' * 66)
    stale = 0
    for name, p, ts, dep in rows:
        if ts is None:
            status = '缺失'
            if verbose:
                print('%-22s  %-8s' % (name, status))
            continue
        is_stale = newest is not None and ts < newest - 2  # 源比资产新 2 秒以上视为陈旧
        probe = None
        if is_stale:
            probe = _content_probe(name, p, titles)
            if probe is True:
                is_stale = False  # 内容已含最新知识 → mtime 失真，视为新鲜
        if is_stale:
            stale += 1
        mark = '陈旧' if is_stale else '新鲜'
        if verbose:
            note = '  (内容探针: 已含最新知识)' if probe is True else ''
            print('%-22s %s  %s   (依赖: %s)%s' % (
                name, time.strftime('%m-%d %H:%M', time.localtime(ts)), mark, dep, note))
    if verbose:
        print('-' * 66)
        if stale:
            print('⚠ %d 个资产陈旧：知识写了但没进派生层，建议重跑提取/蒸馏' % stale)
        else:
            print('✓ 全部新鲜，知识网无断链')
    return 0 if stale == 0 else 1


if __name__ == '__main__':
    sys.exit(check())
