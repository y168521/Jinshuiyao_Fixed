# -*- coding: utf-8 -*-
"""
金水谣 · 变异测试（机制自证）
=============================
对 error_registry.json 中登记的每种错误类型，故意制造真实故障，
运行 gate_all.py 总门禁，验证【必须拦截】，然后恢复现场。
全部拦截通过 = 防复发机制真实有效（不是纸面承诺）。

用法:
  py -3.14 tools/mutation_test.py          # 全量
  py -3.14 tools/mutation_test.py --quick  # 只跑快速用例（不动服务器/慢检测）

返回码: 0 = 全部拦截生效; 1 = 有拦截失效
"""
import os
import sys
import json
import shutil
import subprocess
import tempfile
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)   # Jinshuiyao_Fixed/
MODEL = os.path.dirname(ROOT)  # 模型/
PY = sys.executable

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def run_gate(quick=True):
    """跑总门禁，返回 (exit_code, 输出文本)。
    quick=True 跳过 auto_audit 报告重扫（E-012 用例需 quick=False 验证报告拦截）"""
    cmd = [PY, os.path.join(BASE, 'gate_all.py')]
    if quick:
        cmd.append('--quick')
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=ROOT)
    return proc.returncode, proc.stdout + proc.stderr


def _post_restore_cleanup():
    """恢复后统一清理：消除 mtime 残留导致的误报
    (1) risk_register.json 与 风险登记册.md 时间戳同步（防『双写分叉』误报）
    (2) 模型根门户与 repo 副本 mtime 同步（防 GITSYNC 误报）
    """
    try:
        # (1) 风险册 md 时间戳不早于 json
        j = os.path.join(ROOT, '金水谣数据', 'risk_register.json')
        m = os.path.join(ROOT, '金水谣数据', '风险登记册.md')
        if os.path.isfile(j) and os.path.isfile(m):
            now = time.time()
            os.utime(m, (now, now))
            os.utime(j, (now - 1, now - 1))
    except Exception:
        pass
    try:
        # (2) 根门户 mtime <= repo 副本 mtime
        root_p = os.path.join(MODEL, '金水谣助手门户.html')
        repo_p = os.path.join(ROOT, '金水谣助手门户.html')
        if os.path.isfile(root_p) and os.path.isfile(repo_p):
            rm = os.path.getmtime(repo_p)
            os.utime(root_p, (rm, rm))
    except Exception:
        pass


class MutationCase:
    """变异用例：setup 制造故障，must_block 期望拦截，restore 恢复现场"""

    def __init__(self, eid, desc, setup, restore, quick=True):
        self.eid = eid
        self.desc = desc
        self.setup = setup
        self.restore = restore
        self.quick = quick

    def run(self):
        backup = self.setup()
        try:
            rc, out = run_gate(quick=self.quick)
            blocked = rc != 0
        finally:
            self.restore(backup)
            _post_restore_cleanup()
        # 恢复后再跑一次，确认现场干净（防止污染后续用例）
        rc2, out2 = run_gate(quick=self.quick)
        clean = rc2 == 0
        return blocked, clean, out, out2


def _read(fp):
    """读文本并规范化为 \n（行尾细节由 _write 按原文件还原）"""
    with open(fp, 'r', encoding='utf-8', errors='replace', newline='') as f:
        return f.read().replace('\r\n', '\n').replace('\r', '\n')


def _write(fp, content):
    """按原文件行尾写入：先探测原始换行符，保持字节一致，避免污染 git 工作区"""
    newline = None
    try:
        with open(fp, 'rb') as f:
            raw = f.read(4096)
        if b'\r\n' in raw:
            newline = '\r\n'
        elif b'\r' in raw:
            newline = '\r'
        else:
            newline = '\n'
    except Exception:
        pass
    with open(fp, 'w', encoding='utf-8', newline=newline) as f:
        f.write(content)


# ─────────────────────────── 用例定义 ───────────────────────────
# E-001/E-002 HTML结构
def setup_html_broken():
    fp = os.path.join(ROOT, 'frontend', 'lottery', 'dashboard.html')
    txt = _read(fp)
    _write(fp, txt + '\n</div>\n')  # 多余闭合
    return fp, txt


def setup_html_no_close():
    fp = os.path.join(ROOT, 'frontend', 'guide', 'ai-agent.html')
    txt = _read(fp)
    patched = txt.replace('</body>', '', 1)  # 删闭合标签
    _write(fp, patched)
    return fp, txt


def restore_backup(bak):
    if bak is None:
        return
    if isinstance(bak, tuple) and len(bak) == 2 and isinstance(bak[0], str) and isinstance(bak[1], str):
        fp, txt = bak
        _write(fp, txt)
    elif isinstance(bak, tuple):
        for fp, txt in bak:
            if txt is None:
                if os.path.isfile(fp):
                    os.remove(fp)
            else:
                _write(fp, txt)
    elif isinstance(bak, str) and os.path.isfile(bak):
        os.remove(bak)


# E-003 CSS类未定义：在页面静态 HTML 新增一个无定义的类
def setup_css_break():
    fp = os.path.join(ROOT, 'frontend', 'lottery', 'dashboard.html')
    txt = _read(fp)
    # 在 <body> 后插入使用未定义类 zz-mut-undef-class 的元素（静态 HTML，非 script）
    patched = txt.replace('<body>', '<body>\n<div class="zz-mut-undef-class">mut</div>', 1)
    if patched == txt:
        import re as _re
        patched = _re.sub(r'<body[^>]*>', '<body>\n<div class="zz-mut-undef-class">mut</div>', txt, count=1)
    _write(fp, patched)
    return fp, txt


# E-004 死链接（模型根目录门户加不存在链接）
def setup_deadlink():
    fp = os.path.join(MODEL, '金水谣助手门户.html')
    txt = _read(fp)
    _write(fp, txt.replace('</body>', '<a href="/zz-mut-nonexist.html">mut</a>\n</body>'))
    return fp, txt


# E-005 知识库孤儿索引
def setup_orphan_index():
    fp = os.path.join(ROOT, 'knowledge', '用户知识库', 'INDEX.json')
    txt = _read(fp)
    idx = json.loads(txt)
    # 加一条指向不存在文件的条目
    if isinstance(idx, list):
        idx.append({"title": "变异测试孤儿条目", "file": "zz_mut_nonexist.md"})
    elif isinstance(idx, dict):
        items = idx.setdefault("items", [])
        if not isinstance(items, list):
            items = idx["items"] = []
        items.append({"title": "变异测试孤儿条目", "file": "zz_mut_nonexist.md"})
    _write(fp, json.dumps(idx, ensure_ascii=False, indent=2))
    return fp, txt


# E-006 知识库占位符污染
def setup_placeholder():
    fp = os.path.join(ROOT, 'knowledge', '用户知识库', 'zz_mut_placeholder.md')
    content = """# 变异测试占位卡
---
记录时间: 2026-07-31
来源: 变异测试
---
## 内容
TODO: 这是占位符污染，必须被 lint 拦截
"""
    _write(fp, content)
    return fp


# E-007 风险登记册枚举非法
def setup_risk_enum():
    fp = os.path.join(ROOT, '金水谣数据', 'risk_register.json')
    txt = _read(fp)
    patched = txt.replace('"部分落地"', '"完全不落地变异"')
    _write(fp, patched)
    return fp, txt


def restore_risk(bak):
    """写回 json 后同步 md 时间戳，避免 lint/verify 的『双写分叉』误报"""
    restore_backup(bak)
    md = os.path.join(ROOT, '金水谣数据', '风险登记册.md')
    if os.path.isfile(md):
        now = time.time()
        os.utime(md, (now, now))


# E-008 数据目录缺失
def setup_data_dir():
    target = os.path.join(ROOT, '金水谣数据', 'backtest_results')
    if not os.path.isdir(target):
        return None  # 已不存在，跳过
    tmp = target + '.__mut__'
    os.rename(target, tmp)
    return target, tmp


def restore_data_dir(bak):
    if bak is None:
        return
    target, tmp = bak
    if not os.path.isdir(target) and os.path.isdir(tmp):
        os.rename(tmp, target)


# E-009 路由文件缺失
def setup_route_missing():
    fp = os.path.join(ROOT, 'frontend', 'lottery', 'lottery-hub.html')
    if not os.path.isfile(fp):
        return None
    tmp = fp + '.__mut__'
    os.rename(fp, tmp)
    return fp, tmp


def restore_rename(bak):
    if bak is None:
        return
    orig, tmp = bak
    if not os.path.isfile(orig) and os.path.isfile(tmp):
        os.rename(tmp, orig)


# E-010 钩子缺失
def setup_hook_missing():
    hook = os.path.join(ROOT, '.git', 'hooks', 'pre-commit')
    if not os.path.isfile(hook):
        return None
    tmp = hook + '.__mut__'
    os.rename(hook, tmp)
    return hook, tmp


# E-012 auto_audit 报告有错误
def setup_audit_error():
    import datetime
    rep_dir = os.path.join(ROOT, '金水谣数据', 'log')
    os.makedirs(rep_dir, exist_ok=True)
    fp = os.path.join(rep_dir, 'auto_audit_report.json')
    bak = None
    if os.path.isfile(fp):
        bak = (fp, _read(fp))
    rep = {
        "ts": datetime.datetime.now().isoformat(),
        "error_count": 3,
        "errors": [
            {"path": "zz_mut.html", "type": "dead_link", "msg": "变异测试死链"}
        ],
        "warnings": [],
        "scanned": 0,
    }
    _write(fp, json.dumps(rep, ensure_ascii=False, indent=2))
    return bak if bak else (fp, None)


def restore_backup_generic(bak):
    if isinstance(bak, tuple):
        fp, txt = bak
        if txt is None:
            if os.path.isfile(fp):
                os.remove(fp)
        else:
            _write(fp, txt)


# ─────────────────────────── 用例注册 ───────────────────────────
CASES = [
    MutationCase('E-001', 'HTML多余闭合标签 → 结构检查拦截',
                 setup_html_broken, restore_backup),
    MutationCase('E-002', 'HTML缺</body>闭合 → 结构检查拦截',
                 setup_html_no_close, restore_backup),
    MutationCase('E-003', '共享CSS类定义被破坏 → CSS类检查拦截',
                 setup_css_break, restore_backup),
    MutationCase('E-004', '门户死链接 → 链接检查拦截',
                 setup_deadlink, restore_backup),
    MutationCase('E-005', '知识库孤儿INDEX条目 → lint拦截',
                 setup_orphan_index, restore_backup),
    MutationCase('E-006', '知识库占位符污染 → lint拦截',
                 setup_placeholder, restore_backup),
    MutationCase('E-007', '风险册枚举非法 → verify拦截',
                 setup_risk_enum, restore_risk),
    MutationCase('E-008', '数据目录缺失 → 数据门禁拦截',
                 setup_data_dir, restore_data_dir),
    MutationCase('E-009', '路由文件缺失 → 路由检查拦截',
                 setup_route_missing, restore_rename),
    MutationCase('E-010', 'pre-commit钩子被移除 → 钩子检查拦截',
                 setup_hook_missing, restore_rename),
    MutationCase('E-012', 'auto_audit报告有错误 → 报告检查拦截',
                 setup_audit_error, restore_backup_generic, quick=False),
]


def main():
    print('=' * 60)
    print('  金水谣 · 变异测试（故意破坏 → 验证拦截 → 恢复）')
    print('  覆盖错误注册表 error_registry.json 全部 E-001~E-012')
    print('=' * 60)
    all_pass = True
    n_blocked = 0
    for case in CASES:
        try:
            blocked, clean, out, out2 = case.run()
        except Exception as e:
            print(f'[MUT-FAIL] {case.eid} {case.desc}: 用例执行异常 {e}')
            traceback.print_exc()
            all_pass = False
            continue
        if blocked and clean:
            print(f'[PASS] {case.eid} {case.desc} → 拦截生效，恢复干净')
            n_blocked += 1
        elif not blocked:
            print(f'[FAIL] {case.eid} {case.desc} → 制造故障但【未拦截】！机制失效')
            print(f'  门禁输出片段: {out[-600:]}')
            all_pass = False
        else:
            print(f'[FAIL] {case.eid} {case.desc} → 拦截了，但恢复不干净（污染后续）')
            print(f'  恢复后门禁输出片段: {out2[-600:]}')
            all_pass = False
    print('=' * 60)
    if all_pass:
        print(f'结论: 全部 {len(CASES)} 个变异用例均被拦截（{n_blocked}/{len(CASES)}），机制真实有效')
        return 0
    print(f'结论: {n_blocked}/{len(CASES)} 拦截成功，存在失效用例，机制未完全生效！')
    return 1


if __name__ == '__main__':
    sys.exit(main())
