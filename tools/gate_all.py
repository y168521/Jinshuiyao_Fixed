# -*- coding: utf-8 -*-
"""
金水谣 · 统一总门禁 gate_all
=============================
pre-commit / 启动自检 / 定时任务 共用的【唯一】拦截入口。
聚合全部检测器，任一失败 → 退出码非 0 → 阻止提交/告警：

  ① check_consistency（7项：路由/资源/同步/门户链接/共享/HTML结构/CSS类）
  ② lint_knowledge 知识库体检（错误=失败）
  ③ verify_risk_register 风险登记册
  ④ jinshuiyao_data_guard 数据门禁
  ⑤ closeout_gate 收工门禁（钩子已安装等）
  ⑥ auto_audit 上次自动审查报告（有 error → 失败，记录≠预防，报告要拦提交）

用法:
  py -3.14 tools/gate_all.py           # 全量
  py -3.14 tools/gate_all.py --quick   # 跳过重检测（auto_audit 全盘扫描）
  py -3.14 tools/gate_all.py --changed # pre-commit 增量模式
"""
import os
import sys
import json
import subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
PY = sys.executable


def _run_script(path, label, extra=None):
    """子进程跑独立检测器，返回 (ok, lines)"""
    cmd = [PY, path] + (extra or [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', cwd=ROOT)
        out = (proc.stdout or '') + (proc.stderr or '')
        lines = [l for l in out.splitlines() if l.strip()]
        return proc.returncode == 0, lines
    except Exception as e:
        return False, [f'执行异常: {e}']


def _check_consistency(changed):
    sys.path.insert(0, BASE)
    try:
        import check_consistency
    except Exception as e:
        return False, [f'导入 check_consistency 失败: {e}']
    ok, report = check_consistency.run_all(changed)
    return ok, report


def _check_lint():
    kb = os.path.join(ROOT, 'knowledge', '用户知识库')
    sys.path.insert(0, kb)
    try:
        import lint_knowledge
        rep = lint_knowledge.lint(kb)
        lines = []
        for e in rep.errors:
            lines.append('  LINT-ERR ' + e)
        return rep.ok, lines
    except Exception as e:
        return False, [f'知识库体检执行异常: {e}']


def _check_risk():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        import verify_risk_register
        ok, errors, warns = verify_risk_register.verify()
        lines = ['  RISK-ERR ' + e for e in errors]
        return ok, lines
    except Exception as e:
        return False, [f'风险登记册校验执行异常: {e}']


def _check_data_guard():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        import jinshuiyao_data_guard
        ok = jinshuiyao_data_guard.check_jinshuiyao_data()
        return bool(ok), ([] if ok else ['数据门禁红灯：金水谣数据 关键目录/文件缺失'])
    except Exception as e:
        return False, [f'数据门禁执行异常: {e}']


def _check_hook():
    hook = os.path.join(ROOT, '.git', 'hooks', 'pre-commit')
    if os.path.isfile(hook):
        return True, []
    return False, [f'pre-commit 钩子缺失: {hook}（运行 python tools/install_hooks.py 安装）']


def _check_audit_report():
    """auto_audit 上次报告：有 error 且未标记为已处理 → 拦截"""
    fp = os.path.join(ROOT, '金水谣数据', 'log', 'auto_audit_report.json')
    if not os.path.isfile(fp):
        return True, []  # 无报告视为无数据，不拦截
    try:
        rep = json.load(open(fp, encoding='utf-8'))
    except Exception as e:
        return False, [f'auto_audit 报告解析失败: {e}（需重新运行 auto_audit）']
    errs = rep.get('errors', []) or []
    if not errs:
        return True, []
    lines = [f'  AUDIT-ERR {e.get("path", "?")}: {e.get("msg", "")}' for e in errs[:10]]
    return False, lines


def run_all(quick=False, changed=None):
    checks = []
    checks.append(('系统一致性(7项)', *_check_consistency(changed)))
    checks.append(('知识库体检', *_check_lint()))
    checks.append(('风险登记册', *_check_risk()))
    checks.append(('数据门禁', *_check_data_guard()))
    checks.append(('pre-commit钩子', *_check_hook()))
    if not quick:
        checks.append(('auto_audit报告', *_check_audit_report()))
    return checks


def main():
    quick = '--quick' in sys.argv
    changed = None
    if '--changed' in sys.argv:
        try:
            proc = subprocess.run(['git', 'diff', '--cached', '--name-only'],
                                  capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', cwd=ROOT)
            changed = {l.strip() for l in proc.stdout.splitlines() if l.strip()}
        except Exception:
            changed = None

    print('=' * 56)
    print('  金水谣 · 统一总门禁')
    print('=' * 56)
    all_ok = True
    for name, ok, lines in run_all(quick=quick, changed=changed):
        if ok and not lines:
            print(f'[OK] {name}')
        elif ok:
            print(f'[WARN] {name}（警告不阻塞）')
            for l in lines[:10]:
                print('  ' + l)
        else:
            print(f'[ERR] {name}')
            for l in lines[:15]:
                print('  ' + l)
            all_ok = False
    print('=' * 56)
    if all_ok:
        print('结论: [PASS] 全部门禁通过')
        return 0
    print('结论: [FAIL] 存在未通过项，操作被阻止')
    return 1


if __name__ == '__main__':
    sys.exit(main())
