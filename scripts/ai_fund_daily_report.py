# -*- coding: utf-8 -*-
"""AI 深度版基金日报（ai_fund_daily_report.py）

在每日 18:00 脚本版基金日报（daily_fund_monitor.py，规则计算）基础上，
生成"AI 深度解读版"：把当日数据喂给大模型（优先付费 DeepSeek，免费池兜底），
由 AI 产出持仓分析、风险解读、操作建议等深度内容，生成独立 HTML 报告。

道衍推导（JS-20260806-01）：
  阴阳两仪：阳 = 脚本版（数值精确、可复现，阳主动）；阴 = AI 版（解读深刻、会联想，阴守底）。
  天地人：天=每日 08:00 定时生成（先于操作时段，早看早决策）；地=数据隔离（只读当日
         fund_monitor JSON，不碰其它子系统数据）；人=用户可手动触发/自动定时双入口。
  知止：模型挂/数据缺 → 跳过不阻断（AI 版是增强项，非系统命门；脚本版照常 18:00 出）。

依赖：
  - 金水谣数据/fund_data/fund_monitor_YYYYMMDD.json（daily_fund_monitor.py 产物）
  - core/free_model_pool（付费 DeepSeek + 免费硅基流动池 + 熔断 + 成本闸）

用法：
  python scripts/ai_fund_daily_report.py [--date YYYY-MM-DD] [--force]
"""
import json
import os
import re
import sys
from datetime import datetime

_BASE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_BASE)
sys.path.insert(0, _PROJ)

_DATA_DIR = os.path.join(_PROJ, "金水谣数据", "fund_data")
_OUT_DIR = os.path.join(_PROJ, "金水谣数据", "fund_reports")

try:
    from core.free_model_pool import call_paid, call_ai_failover, get_free_provider_cfgs
except Exception:
    call_paid = None
    call_ai_failover = None
    get_free_provider_cfgs = None


def _log(msg):
    print("[ai-fund] %s %s" % (datetime.now().strftime("%H:%M:%S"), msg))


def _load_monitor_json(date_str):
    """读当日监控数据 JSON（fund_monitor_YYYYMMDD.json）"""
    ymd = date_str.replace("-", "")
    p = os.path.join(_DATA_DIR, "fund_monitor_%s.json" % ymd)
    if not os.path.isfile(p):
        return None, "监控数据不存在: %s" % p
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, "读取监控数据失败: %s" % e


def _funds_summary(data):
    """把 8 支基金数据压缩成给模型的紧凑输入（每支几行）"""
    lines = []
    funds = data.get("funds", {})
    for code, fd in funds.items():
        snap = fd.get("snapshot", {})
        risks = fd.get("risks", {})
        sigs = fd.get("signals", {})
        line = "%s %s 净值=%s 昨日=%s 当日涨跌=%s 买入=%s 卖出=%s 费用=%s 更新=%s" % (
            code, snap.get("name", ""), snap.get("nav_today", "?"),
            snap.get("nav_yesterday", "?"), snap.get("daily_return", "?"),
            snap.get("buy_status", "?"), snap.get("sell_status", "?"),
            snap.get("fee", "?"), snap.get("update_date", "?"))
        r = []
        for k, v in risks.items():
            if v not in (None, "", 0, "0"):
                r.append("%s=%s" % (k, v))
        if r:
            line += " | 风险: " + ", ".join(r)
        s = []
        for k, v in sigs.items():
            if v not in (None, "", 0, False):
                s.append("%s=%s" % (k, v))
        if s:
            line += " | 信号: " + ", ".join(s)
        lines.append(line)
    return "\n".join(lines)


def _call_ai(system_prompt, user_prompt, max_tokens=3000):
    """优先付费 DeepSeek（质量高），失败自动降级免费池，再失败返回 None"""
    if call_paid:
        try:
            text, err = call_paid(system_prompt, user_prompt, timeout=180,
                                  max_tokens=max_tokens, temperature=0.6,
                                  force_json_mode=False)
            if text and not err:
                _log("已用付费 DeepSeek 生成")
                return text
            _log("付费失败(%s)，降级免费池" % (err or "empty"))
        except Exception as e:
            _log("付费异常(%s)，降级免费池" % e)
    if call_ai_failover and get_free_provider_cfgs:
        try:
            cfgs = get_free_provider_cfgs()
            text, err, _ = call_ai_failover(cfgs, system_prompt, user_prompt,
                                            timeout=180, max_tokens=max_tokens,
                                            temperature=0.6, force_json_mode=False,
                                            allow_paid_fallback=False)
            if text and not err:
                _log("已用免费池生成")
                return text
            _log("免费池失败: %s" % (err or "empty"))
        except Exception as e:
            _log("免费池异常: %s" % e)
    return None


def _render_html(date_str, title, body_md):
    """把 AI 输出的 Markdown 包成报告 HTML（逐块渲染，避免段落嵌套块级标签）"""
    import html as _html
    out = []
    for raw_line in body_md.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("###"):
            out.append("<h4>%s</h4>" % _html.escape(line.lstrip("#").strip()))
        elif line.startswith("##"):
            out.append("<h3>%s</h3>" % _html.escape(line.lstrip("#").strip()))
        elif line.startswith("#"):
            out.append("<h2>%s</h2>" % _html.escape(line.lstrip("#").strip()))
        elif line.startswith("|") and line.endswith("|"):
            out.append("<div style='overflow-x:auto'><code>%s</code></div>" % _html.escape(line))
        elif line.startswith("- ") or line.startswith("* "):
            out.append("<li>%s</li>" % _render_inline(line[2:]))
        else:
            out.append("<p>%s</p>" % _render_inline(line))
    body_html = "".join(out)
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>AI 深度版基金日报 %s</title>
<style>
body{font-family:'Microsoft YaHei',sans-serif;max-width:860px;margin:24px auto;padding:0 20px;color:#2b2b2b;line-height:1.7;}
h1{color:#1a5fb4;border-bottom:2px solid #1a5fb4;padding-bottom:8px;}
h2{color:#1a5fb4;margin-top:28px;} h3{color:#3584e4;} h4{color:#3584e4;}
b{color:#c01c28;} li{margin:4px 0;} p{margin:8px 0;}
.footer{color:#888;font-size:12px;margin-top:40px;border-top:1px solid #ddd;padding-top:10px;}
</style></head><body>
<h1>AI 深度版基金日报</h1>
<p style="color:#666;font-size:13px;">%s（基于 %s 收盘数据，由 AI 解读，仅供参考）</p>
%s
<div class="footer">生成: %s | 数据源: 天天基金/晨星（脚本版采集）| 投资有风险，决策需谨慎</div>
</body></html>""" % (
        title, title, date_str, body_html, datetime.now().strftime("%Y-%m-%d %H:%M"))


def _render_inline(text):
    """行内 markdown 最简渲染：**粗体**、*斜体*"""
    import html as _html
    t = _html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
    return t


def _latest_data_date():
    """找最新一期已生成的 fund_monitor_YYYYMMDD.json 日期（AI 版报告基于它解读）"""
    import re
    _pat = re.compile(r"^fund_monitor_(\d{4})(\d{2})(\d{2})\.json$")
    dates = []
    try:
        for name in os.listdir(_DATA_DIR):
            m = _pat.match(name)
            if m:
                dates.append("%s-%s-%s" % (m.group(1), m.group(2), m.group(3)))
    except OSError:
        pass
    if not dates:
        return None
    dates.sort(reverse=True)
    return dates[0]


def run(date_str=None, force=False):
    """生成 AI 深度版日报。返回 (报告路径, 提示语) 或 (None, 错误)"""
    if not date_str:
        date_str = _latest_data_date()
        if not date_str:
            return None, "暂无 fund_monitor 数据（先跑 scripts/daily_fund_monitor.py）"
    out_path = os.path.join(_OUT_DIR, "ai_fund_report_%s.html" % date_str)
    if os.path.isfile(out_path) and not force:
        _log("今日 AI 版报告已存在，跳过（--force 可覆盖）")
        return out_path, "已存在"

    data, err = _load_monitor_json(date_str)
    if err:
        _log("ERR: %s" % err)
        return None, err
    _log("已加载 %s 的监控数据" % date_str)

    funds_summary = _funds_summary(data)
    if not funds_summary.strip():
        return None, "监控数据为空"

    sys_p = ("你是专业基金投资顾问（金水谣助手 AI 深度版）。根据给定的当日基金监控数据，"
             "输出一份结构清晰的基金日报解读，要求："
             "1) 分节：今日概览/持仓分析/风险预警/操作建议/止盈提醒；"
             "2) 每个基金一句话点评，突出关键变化（净值、风险指标、限购、信号）；"
             "3) 风险预警必须具体到基金代码和指标数值；"
             "4) 操作建议要可执行（定投/止盈/加仓/观察），不要笼统套话；"
             "5) 全部用中文，Markdown 格式，标题用 ##。")
    user_p = ("以下是 %s 的 8 支基金监控数据：\n\n%s\n\n请生成今天的基金日报解读。" % (date_str, funds_summary))

    _log("调用 AI 生成解读（最多 3000 tokens）...")
    ai_text = _call_ai(sys_p, user_p, max_tokens=3000)
    if not ai_text:
        return None, "AI 生成失败（付费+免费池均不可用），今日跳过，脚本版报告不受影响"

    html = _render_html(date_str, "AI 深度版 · " + date_str, ai_text)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    _log("已生成: %s (%d 字节)" % (out_path, os.path.getsize(out_path)))
    return out_path, "OK"


if __name__ == "__main__":
    date_arg = None
    force_flag = False
    for a in sys.argv[1:]:
        if a.startswith("--date="):
            date_arg = a.split("=", 1)[1]
        elif a == "--force":
            force_flag = True
    path, msg = run(date_arg, force_flag)
    if path:
        print("报告路径: %s (%s)" % (path, msg))
    else:
        print("生成失败: %s" % msg)
        sys.exit(1)
