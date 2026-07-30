# -*- coding: utf-8 -*-
"""金水谣模型 - 自动全量审查与操作留痕（零依赖，纯标准库）

目标：
  1. 对模型目录下“所有文件”做一次全面体检，确保每个文件状态可核查：
     - .bat ：检查是否带 UTF-8 BOM（cmd.exe 不会剥离 BOM，会导致首行乱码、
              双击打不开——这是已经真实发生过的同类错误，必须自动拦截）。
     - .py  ：用 py_compile 做语法检查（捕获 SyntaxError）。
     - .html/.htm ：检查内部 href/src 是否指向不存在的本地文件（死链）。
  2. 维护文件清单(manifest)，每次运行与上一次 diff，自动记录 新增/修改/删除
     到 operation_log.jsonl，做到“增删改”全程留痕、可追溯。
  3. 输出报告：金水谣数据/log/auto_audit_report.json（最新）+ 追加 金水谣数据/log/auto_audit.log。

可作为独立脚本运行：  python auto_audit.py
也可被导航服务器在每次启动时自动调用（run_audit()）。
"""
import os
import re
import sys
import json
import hashlib
import datetime
import tempfile
import py_compile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)          # 模型根目录（auto_audit.py 在 Jinshuiyao_Fixed 内）
LOG_DIR = os.path.join(BASE_DIR, '金水谣数据', 'log')
REPORT_PATH = os.path.join(LOG_DIR, 'auto_audit_report.json')
RUNLOG_PATH = os.path.join(LOG_DIR, 'auto_audit.log')
MANIFEST_PATH = os.path.join(LOG_DIR, 'manifest.json')
# 知识库目录（用户知识库，含 Lint 体检脚本）
KB_DIR = os.path.join(BASE_DIR, 'knowledge', '用户知识库')

# 不参与审查的目录（第三方环境 / 缓存 / 纯日志 / 隐藏目录）
SKIP_DIRS = {
    'venv_314', '.workbuddy', '__pycache__', 'node_modules', '.git',
    '.trae-html-share-packages', '.uploads', '运行日志与临时文件',
    # 历史备份归档：内含大量陈旧页面/脚本，其死链/语法噪声掩盖真实问题
    # （JS-20260730-04 P2-5），不参与审计
    '_old_backups_consolidated',
}
# 运行时动态生成的日志文件（如 jinshuiyao-guide/server.log）每次启动都会变，
# 不应计入“新增/修改”diff，否则会掩盖真实的代码/资产变更，故整体排除。
SKIP_FILE_EXTS = {'.log', '.logl'}

BOM = b'\xef\xbb\xbf'

# HTML 内部链接提取（href / src）
_LINK_RE = re.compile(r'''(?:href|src)\s*=\s*["\']([^"\']+)["\']''', re.IGNORECASE)
# 视为“非本地文件链接”的前缀
_NON_FILE_PREFIX = ('http://', 'https://', '//', '#', 'mailto:', 'data:',
                    'javascript:', 'file://', 'ftp://')
# 具有这些扩展名却不存在 → 判为死链；无扩展名的 / 开头链接视为服务器路由，跳过
_FILE_EXTS = {
    '.html', '.htm', '.py', '.bat', '.md', '.txt', '.json', '.css', '.js',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.pdf', '.ico', '.csv',
}


def _is_skipped(dirpath):
    parts = set(os.path.normpath(dirpath).split(os.sep))
    return bool(parts & SKIP_DIRS)


def _collect_files():
    """递归收集需要审查的文件，返回 [(abspath, relpath), ...]"""
    files = []
    for cur, dirs, fnames in os.walk(ROOT_DIR):
        # 不递归审计自身的日志目录（避免 manifest/report/log 自噪声）
        if os.path.abspath(cur).startswith(LOG_DIR):
            dirs[:] = []
            continue
        # 原地修剪跳过目录
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not _is_skipped(os.path.join(cur, d))]
        for fn in fnames:
            # 排除运行时日志文件（避免每次启动产生的 server.log 等污染变更 diff）
            if os.path.splitext(fn)[1].lower() in SKIP_FILE_EXTS:
                continue
            absp = os.path.join(cur, fn)
            try:
                relp = os.path.relpath(absp, ROOT_DIR)
            except (ValueError, OSError):
                # Windows 保留设备名（如 nul → '\\.\nul'）会令 relpath 抛
                # "path is on mount '\\.\nul', start on mount 'C:'"，跳过该路径
                # （JS-20260730-04 P2-2）
                continue
            files.append((absp, relp))
    return files


def _check_bat(absp, relp, errors, warnings):
    try:
        with open(absp, 'rb') as f:
            data = f.read()
    except Exception as e:
        errors.append({'path': relp, 'type': 'bat_read', 'msg': f'读取失败: {e}'})
        return
    if data[:3] == BOM:
        errors.append({
            'path': relp, 'type': 'bat_bom',
            'msg': '文件带 UTF-8 BOM：cmd.exe 不会自动剥离 BOM，开头 3 字节会被当成 GBK 乱码 '
                   '“锘緻”污染首行 @echo off，导致双击打不开/整段崩溃。请改为 UTF-8 无 BOM（或 GBK/ANSI 无 BOM）。',
        })
        return
    # 编码探测（仅记录，不报错）：优先 utf-8，失败再 gb18030
    try:
        data.decode('utf-8')
        enc = 'utf-8'
    except UnicodeDecodeError:
        try:
            data.decode('gb18030')
            enc = 'gb18030/ansi'
        except UnicodeDecodeError:
            enc = 'unknown'
            warnings.append({'path': relp, 'type': 'bat_enc', 'msg': '无法以 utf-8 或 gb18030 解码，编码异常。'})
    # 建议：含中文且未显式 chcp 65001 时给出提示（非致命）
    text = data.decode(enc.split('/')[0] if enc != 'unknown' else 'utf-8', errors='replace')
    if ('中文' in text or '。' in text or '：' in text) and 'chcp 65001' not in text and 'chcp 936' not in text:
        warnings.append({
            'path': relp, 'type': 'bat_no_chcp',
            'msg': '含中文但未见 chcp 65001/936：建议第 2 行加 `chcp 65001 >nul` 以保证中文显示（首行须为纯 ASCII 的 @echo off）。',
        })


def _check_py(absp, relp, errors):
    cfile = os.path.join(tempfile.gettempdir(),
                         '_audit_' + os.path.basename(absp) + '.pyc')
    try:
        py_compile.compile(absp, cfile=cfile, doraise=True, quiet=2)
    except py_compile.PyCompileError as e:
        errors.append({'path': relp, 'type': 'py_syntax', 'msg': f'语法错误: {str(e).strip()}'})
    except Exception as e:
        errors.append({'path': relp, 'type': 'py_other', 'msg': f'检查异常: {e}'})
    finally:
        try:
            os.remove(cfile)
        except Exception:
            pass


def _check_html(absp, relp, errors):
    try:
        with open(absp, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        errors.append({'path': relp, 'type': 'html_read', 'msg': f'读取失败: {e}'})
        return
    base_dir = os.path.dirname(absp)
    for m in _LINK_RE.finditer(content):
        link = m.group(1).strip()
        if not link:
            continue
        low = link.lower()
        if any(low.startswith(p) for p in _NON_FILE_PREFIX):
            continue
        # 去掉锚点与查询串
        link_path = link.split('#')[0].split('?')[0]
        if not link_path:
            continue
        # 以 / 开头：相对模型根目录（服务器路由或根下文件）
        if link_path.startswith('/'):
            target = os.path.normpath(os.path.join(ROOT_DIR, link_path.lstrip('/')))
            if os.path.isfile(target):
                continue
            # 有文件扩展名却不存在 → 死链；无扩展名视为服务器路由（如 /docs、/open）→ 跳过
            if os.path.splitext(target)[1].lower() in _FILE_EXTS:
                errors.append({
                    'path': relp, 'type': 'html_dead_link',
                    'msg': f'死链（指向不存在的文件）: {link}',
                })
            continue
        # 相对路径：相对当前 html 所在目录
        target = os.path.normpath(os.path.join(base_dir, link_path))
        if os.path.isfile(target) or os.path.isdir(target):
            continue
        errors.append({
            'path': relp, 'type': 'html_dead_link',
            'msg': f'死链（指向不存在的文件）: {link}',
        })


def _check_kb():
    """对用户知识库做一次 Lint 体检（防幻觉复利/占位符/空卡/索引不一致）。
    返回 (kb_errors, kb_warnings) 两个列表，元素形如 {'path':..., 'type':..., 'msg':...}。"""
    if not os.path.isdir(KB_DIR):
        return [], []
    try:
        sys.path.insert(0, KB_DIR)
        import lint_knowledge
        rep = lint_knowledge.lint(KB_DIR)
    except Exception as e:
        return [], [{'path': 'knowledge/用户知识库', 'type': 'kb_lint_exception',
                     'msg': f'知识库体检异常: {e}'}]
    kb_errs, kb_warns = [], []
    for e in rep.errors:
        kb_errs.append({'path': 'knowledge/用户知识库', 'type': 'kb_error', 'msg': e})
    for w in rep.warns:
        kb_warns.append({'path': 'knowledge/用户知识库', 'type': 'kb_warn', 'msg': w})
    return kb_errs, kb_warns


def _load_manifest():
    if os.path.isfile(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_manifest(manifest):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def run_audit():
    """执行一次全量审查，返回报告字典（并写盘）。"""
    files = _collect_files()
    errors = []
    warnings = []
    checked_bat = checked_py = checked_html = 0

    manifest = {}
    for absp, relp in files:
        try:
            st = os.stat(absp)
            manifest[relp] = {'size': st.st_size, 'mtime': int(st.st_mtime)}
        except Exception:
            manifest[relp] = {'size': -1, 'mtime': -1}

        ext = os.path.splitext(absp)[1].lower()
        try:
            if ext == '.bat':
                checked_bat += 1
                _check_bat(absp, relp, errors, warnings)
            elif ext == '.py':
                checked_py += 1
                _check_py(absp, relp, errors)
            elif ext in ('.html', '.htm'):
                checked_html += 1
                _check_html(absp, relp, errors)
        except Exception as e:
            # 单文件检查异常不应中断整体审查
            errors.append({'path': relp, 'type': 'check_exception', 'msg': str(e)})

    # 知识库 Lint 体检（并入总错误/警告，防止污染卡长期留存）
    kb_errs, kb_warns = _check_kb()
    errors.extend(kb_errs)
    warnings.extend(kb_warns)

    # 清单 diff → 自动记录 新增/修改/删除
    prev = _load_manifest()
    added, removed, modified = [], [], []
    prev_keys = set(prev.keys())
    cur_keys = set(manifest.keys())
    for k in cur_keys - prev_keys:
        added.append(k)
    for k in prev_keys - cur_keys:
        removed.append(k)
    for k in (cur_keys & prev_keys):
        p, c = prev[k], manifest[k]
        if p.get('size') != c.get('size') or p.get('mtime') != c.get('mtime'):
            modified.append(k)

    # 写入 operation_log（自动留痕）
    try:
        sys.path.insert(0, BASE_DIR)
        import operation_log
        for k in added:
            operation_log.log_file_op('add', k, detail='自动审查发现新增文件')
        for k in removed:
            operation_log.log_file_op('delete', k, detail='自动审查发现文件被删除')
        for k in modified:
            operation_log.log_file_op('modify', k, detail='自动审查发现文件被修改')
    except Exception:
        pass

    _save_manifest(manifest)

    report = {
        'time': datetime.datetime.now().isoformat(timespec='seconds'),
        'root': ROOT_DIR,
        'total_files': len(files),
        'checked_bat': checked_bat,
        'checked_py': checked_py,
        'checked_html': checked_html,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'kb_error_count': len(kb_errs),
        'kb_warning_count': len(kb_warns),
        'added': added,
        'removed': removed,
        'modified': modified,
        'errors': errors,
        'warnings': warnings,
    }

    # 写最新报告
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(REPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 追加运行日志（人类可读摘要）
    try:
        with open(RUNLOG_PATH, 'a', encoding='utf-8') as f:
            f.write(
                f"[{report['time']}] 审查完成 | 文件总数={report['total_files']} "
                f"(bat={checked_bat}, py={checked_py}, html={checked_html}) | "
                f"错误={report['error_count']}, 警告={report['warning_count']} | "
                f"新增={len(added)}, 删除={len(removed)}, 修改={len(modified)}\n"
            )
            for e in errors[:50]:
                f.write(f"    [ERROR] {e['path']} ({e['type']}): {e['msg']}\n")
    except Exception:
        pass

    return report


def main():
    rep = run_audit()
    print(f"模型自动审查完成 @ {rep['time']}")
    print(f"  文件总数 : {rep['total_files']}")
    print(f"  检查覆盖 : .bat={rep['checked_bat']}  .py={rep['checked_py']}  .html={rep['checked_html']}")
    print(f"  错误     : {rep['error_count']}    警告: {rep['warning_count']}")
    print(f"  知识库体检 : 错误={rep.get('kb_error_count', 0)}  警告={rep.get('kb_warning_count', 0)}"
          f"（脚本: knowledge/用户知识库/lint_knowledge.py）")
    print(f"  变更     : 新增={len(rep['added'])} 删除={len(rep['removed'])} 修改={len(rep['modified'])}")
    if rep['errors']:
        print("  --- 错误明细（前 30 条）---")
        for e in rep['errors'][:30]:
            print(f"    [ERROR] {e['path']} ({e['type']})\n        {e['msg']}")
    print(f"  报告已写入: {REPORT_PATH}")
    sys.exit(0 if rep['error_count'] == 0 else 1)


if __name__ == '__main__':
    main()
