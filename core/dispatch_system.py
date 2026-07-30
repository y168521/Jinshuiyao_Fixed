# -*- coding: utf-8 -*-
"""金水谣引擎 - 系统管理调度模块

从 ai_agent.py 的 _dispatch_system 方法拆出。
接收 agent 实例以复用其 _get_domain / _get_ai 等属性。
"""

import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def dispatch_system(agent, action: str, target: str) -> str:
    """调度系统管理

    Args:
        agent: JinshuiyaoAgent 实例，用于访问子系统/AI服务等
        action: 操作类型（test/status/review/help/greet/auto_knowledge/data_maintenance/scheduler_status/backup/launch）
        target: 目标
    """
    try:
        if action == "test":
            return "正在运行全量测试...（请在终端查看 run_tests.py 输出）"

        elif action == "status":
            parts = []
            for name in ["lottery", "stock", "football", "music", "creator"]:
                domain = agent._get_domain(name)
                if domain:
                    st = domain.status()
                    parts.append(f"  {name}: {'✅ 就绪' if st.get('ready') else '❌ 未就绪'}")
                else:
                    parts.append(f"  {name}: ❌ 不可用")

            ai = agent._get_ai()
            ai_status = "✅ DeepSeek 已配置" if (ai and ai.is_available) else "⚠️ AI未配置"
            parts.append(f"  AI服务: {ai_status}")
            parts.append(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            return "【系统状态】\n" + "\n".join(parts)

        elif action == "review":
            parts = []
            for name in ["lottery", "stock", "football", "music", "creator"]:
                domain = agent._get_domain(name)
                if domain:
                    try:
                        result = domain.review()
                        hits = result.get("hits", 0)
                        reviews = result.get("reviews", 0)
                        rate = hits / reviews if reviews > 0 else 0
                        parts.append(f"  {name}: {reviews}次复盘, {hits}次命中, 命中率{rate:.1%}")
                    except Exception:
                        parts.append(f"  {name}: 暂无复盘数据")
            return "【复盘统计】\n" + "\n".join(parts) if parts else "暂无复盘数据"

        elif action == "help":
            return (
                "【金水谣万物引擎 - 功能列表】\n\n"
                "彩票预测：\n"
                "  问我'双色球预测'、'大乐透号码'、'3D推荐'等\n"
                "  直接说'今天双色球'可快速生成预测\n\n"
                "股票行情：\n"
                "  问我'大盘怎么样'、'上证指数'、'选股推荐'、'技术指标'等\n\n"
                "足彩分析：\n"
                "  问我'今天有什么比赛'、'赔率分析'、'赛事数据'等\n\n"
                "音乐/音频：\n"
                "  问我'生成音乐'、'创作旋律'、'格式转换'、'音频分析'等\n\n"
                "视频文案提取：\n"
                "  问我'视频提取'、'文案提取'、'视频链接'，或直接发送视频链接\n"
                "  支持抖音、B站、快手、小红书、微信视频号等平台\n"
                "  提取后说'存入知识库'或'归档'可保存到知识库\n\n"
                "知识库：\n"
                "  '知识库' / '我的知识' → 查看知识库统计和最近卡片\n"
                "  '搜索知识 xxx' → 搜索知识卡片\n"
                "  '归档 xxx' → 手动归档内容到知识库\n"
                "  '价值分层' → 查看各价值层级的卡片数量\n\n"
                "创作者工具箱：\n"
                "  问我'写文案'、'AI文案'、'语音转文字'、'配音'、'OCR'等\n\n"
                "系统管理：\n"
                "  说'系统状态'、'复盘统计'、'运行测试'等\n\n"
                "自动系统管理：\n"
                "  '自动学习' / '知识提取' — 自动从复盘中提取知识卡片\n"
                "  '数据维护' / '清理数据' — 一键执行数据库全面维护\n"
                "  '调度器状态' / '定时任务' — 查看后台定时任务运行状态\n"
                "  '备份' / '数据备份' — 创建全量数据备份\n\n"
                "你也可以自由提问，我会尽力帮你分析！"
            )

        elif action == "greet":
            return (
                "你好！我是金水谣AI助手，随时为你服务。\n\n"
                "你可以问我：\n"
                "  • 彩票预测（双色球、大乐透、3D等）\n"
                "  • 股票行情（大盘、选股、技术指标）\n"
                "  • 足彩分析（赛事、赔率、推荐）\n"
                "  • 音乐生成（AI作曲、旋律创作）\n"
                "  • 视频文案提取（抖音、B站、快手等）\n"
                "  • 知识库管理（归档、搜索、价值分层）\n"
                "  • 创作者工具箱（AI文案/语音转文字/TTS/OCR等）\n"
                "  • 系统管理（状态、复盘）\n\n"
                "或者说'帮助'查看完整功能列表。"
            )

        elif action == "auto_knowledge":
            try:
                from core.auto_knowledge import run_auto_extraction
                result = run_auto_extraction("lottery")
                cards = result.get("total_extracted", 0)
                saved = result.get("total_saved", 0)
                return (
                    f"【自动知识积累】\n"
                    f"  子系统: {result.get('subsystem', 'lottery')}\n"
                    f"  提取卡片: {cards} 张\n"
                    f"  保存卡片: {saved} 张\n"
                    f"  时间: {result.get('timestamp', '')}"
                )
            except Exception as e:
                return f"自动知识积累执行失败：{e}"

        elif action == "data_maintenance":
            try:
                from core.data_maintenance import DataMaintainer
                report = DataMaintainer().vacuum_all()
                summary = report.get("summary", {})
                return (
                    f"【数据维护】\n"
                    f"  清理文件: {summary.get('total_files_cleaned', 0)} 个\n"
                    f"  删除记录: {summary.get('total_records_removed', 0)} 条\n"
                    f"  释放空间: {summary.get('total_freed_kb', 0):.2f} KB\n"
                    f"  压缩文件: {summary.get('files_compressed', 0)} 个\n"
                    f"  修复索引: {summary.get('indices_repaired', 0)} 个\n"
                    f"  错误数: {summary.get('errors', 0)}"
                )
            except Exception as e:
                return f"数据维护执行失败：{e}"

        elif action == "scheduler_status":
            try:
                from core.scheduler import get_scheduler
                scheduler = get_scheduler()
                tasks = scheduler.status()
                if not tasks:
                    return "【调度器状态】\n当前无已注册的定时任务。"
                lines = ["【调度器状态】", f"  共 {len(tasks)} 个任务\n"]
                for t in tasks:
                    status_icon = "已启用" if t["enabled"] else "已禁用"
                    lines.append(f"  {t['name']}:")
                    lines.append(f"    状态: {status_icon}")
                    lines.append(f"    间隔: {t['interval_minutes']} 分钟")
                    lines.append(f"    执行次数: {t['run_count']}")
                    last = t.get("last_run") or "未执行"
                    lines.append(f"    上次执行: {last}")
                    err = t.get("last_error")
                    if err:
                        lines.append(f"    上次错误: {err}")
                return "\n".join(lines)
            except Exception as e:
                return f"获取调度器状态失败：{e}"

        elif action == "backup":
            try:
                from utils.data_backup import backup_all
                backup_path = backup_all()
                import os as _os
                size_mb = _os.path.getsize(backup_path) / (1024 * 1024) if _os.path.isfile(backup_path) else 0
                return (
                    f"【数据备份】\n"
                    f"  备份完成!\n"
                    f"  文件: {backup_path}\n"
                    f"  大小: {size_mb:.2f} MB"
                )
            except Exception as e:
                return f"数据备份失败：{e}"

        elif action == "launch":
            return "请在总控台页面点击对应子系统的'启动窗口'按钮。"

        elif action == "closeout":
            try:
                from core.agent_system_diagnostics import check_closeout
                return check_closeout()
            except Exception as e:
                return f"收工门禁检查失败：{e}"

        elif action == "mirror_status":
            try:
                from core.agent_system_diagnostics import check_automation_mirror
                return check_automation_mirror()
            except Exception as e:
                return f"自动化镜像检查失败：{e}"

        elif action == "health_check":
            try:
                from core.agent_system_diagnostics import check_health
                return check_health()
            except Exception as e:
                return f"健康检查失败：{e}"

        elif action == "diagnose":
            try:
                from core.agent_system_diagnostics import run_diagnostics
                return run_diagnostics(auto_fix=(target == "fix"))
            except Exception as e:
                return f"系统诊断失败：{e}"

        elif action == "route":
            try:
                from core.model_router import route_report
                return route_report()
            except Exception as e:
                return f"模型路由报告失败：{e}"

        elif action == "theme":
            try:
                from core import agent_theme as at
                from core import theme_manager as tm
                tgt = (target or "").strip()

                # 0) 能力询问：『你能/会配色吗』之类 → 能力说明
                if re.search(r"(你能|你会|可以|会不会|能帮我).{0,4}(配色|配色吗|颜色|改颜色|识别颜色)", tgt):
                    themes = tm.list_themes()
                    lines = ["【智能配色 · 我能帮你】",
                             "· 扫色合规检查：『检查 ai-agent.html 的颜色』",
                             "· 自动纠错：『把 ai-agent.html 的禁用色改掉』",
                             "· 建议主题：『帮我配一套浅色中性』『用七色体系』",
                             "· 套用主题：『把报告.html 套用七色』",
                             "",
                             "当前可用主题（回退序：客户自选→系统默认→个人七色）："]
                    for th in themes:
                        lines.append("  · {}（{}）".format(th["label"], th["kind"]))
                    return "\n".join(lines)

                # 抽取文本中出现的文件路径（不要求出现在句尾）
                fp = re.search(r"([\w./\\-]+\.(?:html|css|scss|vue))", tgt, re.IGNORECASE)

                # 1) 修复/套用主题到文件（点名文件 + 改/套用类动词）
                if fp and any(k in tgt for k in ["修复", "改掉", "改成", "套用", "应用", "换成", "apply", "fix", "重做", "整体重做"]):
                    path = fp.group(1)
                    if not os.path.isfile(path):
                        return "找不到文件：{}".format(path)
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if "七色" in tgt or "修复" in tgt or "改掉" in tgt:
                        new_content, changes = at.fix_colors(content)
                        mode = "禁用色纠错"
                    else:
                        sug = at.suggest_theme(tgt)
                        new_content = tm.apply_to_html(content, sug["vars"])
                        changes = [{"from": "结构注入", "to": sug["label"]}]
                        mode = "套用主题（{})".format(sug["label"])
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    return "【{}】{}\n已改写 {} 处，文件已保存。刷新页面即可生效。".format(
                        mode, os.path.basename(path), len(changes))

                # 2) 扫描文件配色（点名文件 + 检查/扫描类动词，或仅点名文件）
                if fp and (any(k in tgt for k in ["检查", "扫描", "扫色", "颜色", "配色", "看下", "看看"]) or True):
                    path = fp.group(1)
                    if not os.path.isfile(path):
                        return "找不到文件：{}".format(path)
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    scan = at.scan_colors(content)
                    result = "【配色扫描】{}\n".format(path) + at.explain_scan(scan)
                    if scan["violations"]:
                        result += "\n\n可说『把 {} 的禁用色改掉』自动纠错，或『把 {} 套用七色』整体重做。".format(
                            os.path.basename(path), os.path.basename(path))
                    return result

                # 3) 自然语言建议主题（不点名文件）
                if any(k in tgt for k in ["配一套", "建议", "套用", "用七色", "浅色", "深色", "客户自选", "自选", "我的主题", "换主题", "改成", "换成", "配色", "配个", "配一"]):
                    sug = at.suggest_theme(tgt)
                    css = tm.theme_to_css_vars(sug["vars"])
                    return ("【智能配色建议】\n主题：{}\n\n变量预览：\n{}\n\n"
                            "在「主题设置」面板保存即生效；也可说『把 xxx.html 套用这套主题』让我直接改文件。").format(
                        sug["label"], css)

                # 4) 默认：能力说明 + 列出主题
                themes = tm.list_themes()
                lines = ["【智能配色 · 我能帮你】",
                         "· 扫色合规检查：『检查 ai-agent.html 的颜色』",
                         "· 自动纠错：『把 ai-agent.html 的禁用色改掉』",
                         "· 建议主题：『帮我配一套浅色中性』『用七色体系』",
                         "· 套用主题：『把报告.html 套用七色』",
                         "",
                         "当前可用主题（回退序：客户自选→系统默认→个人七色）："]
                for th in themes:
                    lines.append("  · {}（{}）".format(th["label"], th["kind"]))
                return "\n".join(lines)
            except Exception as e:
                return f"配色处理失败：{e}"

        else:
            return "未知的系统操作。"

    except Exception as e:
        return f"系统管理异常：{e}"
