# -*- coding: utf-8 -*-
"""金水谣系统 - 导航服务器模块

原 guide_server.py（1758 行单体文件）已完全退役，本包为唯一服务器入口。

模块结构：
  server/config.py     — 服务器常量（端口、路径、版本等）
  server/utils.py      — 通用工具（日志、IP 检测、外部调用熔断）
  server/router.py     — GuideHandler 路由调度
  server/handlers/     — 按功能域划分的请求处理器
"""
import http.server
import os
import sys
import threading

# 从子模块导出关键常量
from .config import SERVER_VERSION, PORT  # noqa: F401
from .config import (
    BASE_DIR, ROOT_DIR, HTML_DIR, NAV_FILE, CONTROL_CENTER, LOG_FILE,
    SYSTEM_PYTHON, SYSTEM_PYTHONW,
)
from .utils import log, get_local_ip
from .router import GuideHandler


def _background_startup_tasks():
    """后台执行启动自检 / 冒烟测试 / 自动模型审查 / AI模式检测（不阻塞端口绑定）。"""
    # === 修后审查 Pipeline（事前拦截V2，走全局统一入口 run_review） ===
    try:
        import subprocess as _sp
        import os as _os
        review_script = _os.path.join(BASE_DIR, "tools", "run_review.py")
        if _os.path.exists(review_script):
            log('>>> [后台] 审查Pipeline(quick)开始(ruff+AST+smoke+metrics)...')
            _r = _sp.run(
                [sys.executable, review_script, "--quick", "--no-learn"],
                capture_output=True, text=True, errors="replace", timeout=180,
                cwd=BASE_DIR
            )
            if _r.returncode == 0:
                log('<<< [后台] 审查Pipeline全绿(无P0)，metrics已同步')
            else:
                _out = _r.stdout + _r.stderr
                _fails = [l.strip() for l in _out.splitlines() if 'P0' in l or 'FAIL' in l]
                if not _fails:
                    # 红灯详情兜底（JS-20260730-04 P1-3）：过滤不到 P0/FAIL 行时
                    # 输出退出码 + 输出末尾，避免冒号后恒为空、告警失明
                    _tail = [l.strip() for l in _out.splitlines() if l.strip()][-3:]
                    _fails = [f'returncode={_r.returncode}'] + _tail
                log('!!! 审查Pipeline有红灯: ' + '; '.join(_fails[:3]))
        else:
            log('run_review.py不存在，跳过审查Pipeline')
    except Exception as e:
        log(f'审查Pipeline异常(不阻塞): {e}')

    # === 启动AI语义审查（免费模型优先，用户约定"能用免费就用不然算了"）===
    # 与 pre-commit 钩子互补：钩子拦"本次提交"，此处兜底"近期已入库代码"。
    # 无硅基流动密钥/免费池不可用 → 静默跳过（绝不调用付费 DeepSeek，不阻塞启动）。
    try:
        import subprocess as _sp
        import os as _os
        _secrets = _os.path.join(_os.path.expanduser("~"), ".jinshuiyao-secrets")
        _agent = _os.path.join(BASE_DIR, "tools", "ai_review_agent.py")
        if _os.path.isfile(_os.path.join(_secrets, "siliconflow_key.txt")) and _os.path.isfile(_agent):
            log('>>> [后台] AI语义审查(免费模型)开始...')
            _env = dict(_os.environ)
            _env["AI_REVIEW_PROVIDER"] = "siliconflow"
            _r = _sp.run(
                [sys.executable, _agent, "--diff-only", "--json"],
                capture_output=True, timeout=900, env=_env, cwd=BASE_DIR,
            )
            _out = (_r.stdout or b"").decode("utf-8", errors="replace")
            try:
                import json as _json
                _rep = _json.loads(_out)
                _p0 = sum(1 for i in _rep.get("issues", []) if i.get("severity") == "P0")
                _tot = len(_rep.get("files", []))
                log(f'<<< [后台] AI语义审查完成: {_tot}文件 P0={_p0} (rc={_r.returncode})')
            except Exception:
                log(f'<<< [后台] AI语义审查结束(rc={_r.returncode}, 输出不可解析)')
        else:
            log('[后台] 无硅基流动密钥，跳过AI语义审查（免费优先约定）')
    except Exception as e:
        log(f'AI语义审查异常(不阻塞): {e}')

    # === 启动自检 ===
    try:
        from startup_selfcheck import run_startup_check_safe
        log('>>> [后台] 启动自检开始...')
        selfcheck_report = run_startup_check_safe()
        log(f'<<< [后台] 启动自检完成: {selfcheck_report["summary"]}')
        if not selfcheck_report["all_passed"]:
            log('!!! 自检有失败项，详见 金水谣数据/log/selfcheck.log')
    except Exception as e:
        log(f'启动自检异常(不阻塞): {e}')

    # === 系统一致性检测（防复发：路由/静态资源/git同步/门户链接/共享资源）===
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
        from check_consistency import run_all as _run_consistency
        _ok, _report = _run_consistency()
        _status = '通过' if _ok else f'失败 ({sum(1 for l in _report if "[ERR]" in l)} 项)'
        log(f'>>> [后台] 系统一致性检测: {_status}')
        if not _ok:
            for _l in _report:
                if '[ERR]' in _l:
                    log(f'  !!! 一致性: {_l}')
            log('!!! 一致性问题已记录，建议运行 python tools/check_consistency.py 查看详情')
    except Exception as e:
        log(f'系统一致性检测异常(不阻塞): {e}')

    # === 自动模型审查 ===
    try:
        import sys as _sys
        if BASE_DIR not in _sys.path:
            _sys.path.insert(0, BASE_DIR)
        import auto_audit
        log('>>> [后台] 自动模型审查开始...')
        audit_report = auto_audit.run_audit()
        log(f'<<< [后台] 自动模型审查完成: 文件总数={audit_report.get("total_files")}, '
            f'错误={audit_report.get("errors")}, '
            f'新增={len(audit_report.get("added", []))}, '
            f'删除={len(audit_report.get("removed", []))}, '
            f'修改={len(audit_report.get("modified", []))}')
        if audit_report.get('errors'):
            log('!!! 模型审查发现错误，详见 金水谣数据/log/auto_audit.log')
    except Exception as e:
        log(f'自动模型审查异常(不阻塞): {e}')

    # === AI模式自动检测 ===
    try:
        from core.ai_service import auto_detect_mode, get_mode_info
        log('>>> [后台] AI模式自动检测开始...')
        detected_mode = auto_detect_mode()
        mode_info = get_mode_info()
        log(f'<<< [后台] AI模式自动检测完成: 当前模式={detected_mode}')
    except Exception as e:
        log(f'AI模式自动检测异常(不阻塞): {e}')


def main(port=None):
    """启动金水谣导航服务器

    Args:
        port: 可选端口号。若为 None，使用 config.PORT（默认 18888）。
              外部脚本可直接传参：server.main(port=18950)。
    """
    import server.config as _cfg
    # 统一日志配置（config/logging_config.py；原 main.py 已删除）
    try:
        from config.logging_config import setup_logging
        setup_logging()
    except Exception as e:
        log(f'统一日志配置加载失败(不阻塞): {e}')
    _actual_port = port or _cfg.PORT
    # 同步到 config 模块，确保 handler 层也能读到覆盖后的端口
    _cfg.PORT = _actual_port
    # 调试信息
    log('[DEBUG] server模块启动')
    log(f'[DEBUG] 端口: {_actual_port}')
    log(f'[DEBUG] 当前工作目录: {os.getcwd()}')

    # 清空日志（P2-4: 加进程级 guard，防重入/与并行写线程竞态重复截断）
    if not globals().get('_log_initialized'):
        globals()['_log_initialized'] = True
        try:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(f'=== 金水谣导航服务器启动 {__import__("datetime").datetime.now()} ===\n')
                f.write(f'Python(TRAE): {sys.executable}\n')
                f.write(f'Python(系统): {SYSTEM_PYTHON}\n')
                f.write(f'PythonW(系统): {SYSTEM_PYTHONW}\n')
                f.write(f'BASE_DIR: {BASE_DIR}\n')
                f.write(f'HTML_DIR: {HTML_DIR}\n\n')
        except Exception:
            pass

    log(f'Python路径(TRAE): {sys.executable}')
    log(f'系统Python: {SYSTEM_PYTHON}')
    log(f'系统PythonW: {SYSTEM_PYTHONW}')
    log(f'项目目录: {BASE_DIR}')
    log(f'HTML目录: {HTML_DIR}')

    # 注：启动自检 / 自动模型审查 / AI模式检测 已移至后台线程（端口绑定后执行），
    #     见 _background_startup_tasks()，避免阻塞用户等待。

    # 检查关键文件
    for f in ['control-center.html', '金水谣助手门户.html', '启动金水谣助手.bat']:
        if f == '启动金水谣助手.bat':
            fp = os.path.join(ROOT_DIR, f)
        elif f == 'control-center.html':
            fp = CONTROL_CENTER
        else:
            fp = NAV_FILE
        exists = os.path.isfile(fp)
        log(f'检查 {f}: {"存在" if exists else "不存在!"}')

    # 获取局域网IP（手机端访问用）
    local_ip = get_local_ip()
    log(f'本机局域网IP: {local_ip}')
    log(f'手机端访问（同WiFi）: http://{local_ip}:{_actual_port}/')

    log(f'[DEBUG] 启动HTTP服务器，端口: {_actual_port}')

    # 尝试推送微信通知（如果有 sendkey.txt）
    try:
        from utils.notifier import notify_startup
        notify_startup(ip=local_ip, port=_actual_port)
    except Exception:
        pass  # 推送失败不阻塞启动

    # 自动选端口：18888 被占用时顺延到 18889/18890…，避免"端口冲突闪退"
    # P0-① 安全加固：默认仅绑定本机回环地址，杜绝服务误暴露到局域网 / 公网。
    #   仅当显式设置环境变量 JINSHUIYAO_ALLOW_LAN=1 时才允许临时开放到 0.0.0.0
    #   （上线前必须先补全 认证 + 限流 + TLS，否则一律拒绝启动）。
    _bind_host = os.environ.get("JINSHUIYAO_BIND_HOST", "127.0.0.1")
    if _bind_host not in ("127.0.0.1", "localhost") and \
            os.environ.get("JINSHUIYAO_ALLOW_LAN", "") != "1":
        log(f'!! 安全拦截：拒绝绑定到非本机地址 {_bind_host}（可能误暴露到局域网/公网）。')
        log('   如需临时对局域网开放，请显式设置环境变量 JINSHUIYAO_ALLOW_LAN=1 后再启动。')
        return
    log(f'[安全] 绑定地址校验通过：将仅监听 {_bind_host}（回环/本机）')
    httpd = None
    used_port = None
    last_err = None
    for candidate in range(_actual_port, _actual_port + 6):
        try:
            # 默认 ("127.0.0.1", candidate)；上线改 0.0.0.0 前必须先完成认证 + 限流 + TLS。
            httpd = http.server.ThreadingHTTPServer((_bind_host, candidate), GuideHandler)
            used_port = candidate
            break
        except OSError as e:
            last_err = e
            if getattr(e, 'winerror', None) == 10048 or 'Address already in use' in str(e):
                log(f'端口 {candidate} 被占用，尝试下一个…')
                continue
            raise
    if httpd is None:
        log(f'!! 无法绑定任何端口（{_actual_port}~{_actual_port + 5}）：{last_err}')
        log('请关闭其他占用端口的程序后重试；或告诉助手"启动失败，端口被占用"。')
        return

    log(f'[安全] 实际监听地址：{_bind_host}:{used_port}（仅本机 127.0.0.1 可达，局域网/公网不可达）')

    with httpd:
        actual_port = used_port
        # 端口已绑定，立即启动后台任务（自检/审查/AI检测），不阻塞用户访问
        _bg = threading.Thread(target=_background_startup_tasks, daemon=True, name='startup-bg')
        _bg.start()
        log('后台自检/审查/AI检测线程已启动（不阻塞访问）')
        # 启动后台调度器：经验收集箱文件监听(B,近实时同步) + 120分钟兜底同步
        # + 知识维护自动化(N1/N3 衰减/双库链接/图谱重建/Lint)。
        # 调度器内 JinshuiyaoScheduler.start() 会拉起监听线程并触发 GraphRAG 三元组抽取(D)。
        try:
            from core.scheduler import start_background_scheduler
            start_background_scheduler()
            log('后台调度器已启动（经验收集箱监听 + 定时同步 + 知识维护）')
        except Exception as e:
            log(f'后台调度器启动失败(不阻塞启动): {e}')
        # 自动打开浏览器（端口以实际绑定为准；无桌面环境自动跳过）
        from .config import safe_open_browser
        if os.path.isfile(CONTROL_CENTER):
            url = f'http://localhost:{actual_port}/'
            if safe_open_browser(url):
                log(f'总控台已打开: {url}')
            else:
                log(f'总控台地址: {url}（无桌面环境，请手动访问）')
        elif os.path.isfile(NAV_FILE):
            safe_open_browser('file:///' + NAV_FILE)
            log(f'旧版导航: {NAV_FILE}')
        else:
            url = f'http://localhost:{actual_port}/jinshuiyao-guide.html'
            safe_open_browser(url)
            log(f'导航地址: {url}')
        if actual_port != _actual_port:
            log(f'注意：默认端口 {_actual_port} 被占用，已改用 {actual_port}，访问地址同步更新。')
            log(f'手机端访问（同WiFi）: http://{local_ip}:{actual_port}/')
        log('浏览器已打开，等待操作...')

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log('服务器已停止')
            httpd.server_close()
