# -*- coding: utf-8 -*-
"""金水谣 · 彩票数据源健康日报 (lottery_datasource_health.py)
============================================================

定时检查彩票数据源健康：复用 /api/lottery/sources-health 面板，
汇总「各数据源熔断状态（熔断器单例）+ 各彩种数据新鲜度」，产出 HTML/JSON 日报。

设计对齐项目铁律与经验底座：
  - MEMORY 第9条：旧 lottery_health_report.json 曾引用失效基准、界面"命中率"误导。
    本日报只做「数据源可用性 + 数据新鲜度」监控，并标注诚实基准来源与新鲜度，
    **绝不输出中奖概率**。
  - S3/F6：复用功能端点 + 超时探活；超时即视为不健康（服务端不可达则跳过）。
  - F10：只读监控，不写库、不下单、不重启、不改任何抓取/预测逻辑。

用法：
  python lottery_datasource_health.py            # 生成日报 + 追加历史
  python lottery_datasource_health.py --quiet    # 仅输出摘要行（供自动化调度）
退出码：0=全部健康；1=存在熔断/陈旧异常 或 端点不可达（供调度判"需关注"）。
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error

PORT = 18888
BASE = "http://127.0.0.1:{0}".format(PORT)
ENDPOINT = "{0}/api/lottery/sources-health".format(BASE)

ROOT = "C:/Users/Administrator/Nutstore/1/我的坚果云/模型"
LOG_DIR = os.path.join(ROOT, "金水谣数据", "log")
HISTORY_FILE = os.path.join(LOG_DIR, "lottery_health_history.json")
REPORT_FILE = os.path.join(ROOT, "金水谣数据", "lottery_datasource_health.html")
HONEST_REPORT = os.path.join(ROOT, "金水谣数据", "lottery_health_report.json")

STALE_THRESHOLD_MIN = 1440  # 24h，每日开奖彩种应 <24h 更新
PROBE_TIMEOUT = 10
HISTORY_KEEP = 90           # 保留近 90 天历史


def log(msg):
    print("[{0}] {1}".format(time.strftime("%H:%M:%S"), msg))


def probe():
    """探活数据源健康端点；返回 dict 或 None。"""
    try:
        req = urllib.request.Request(ENDPOINT, method="GET")
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return None
    except Exception as e:
        log("探活失败: {0} {1}".format(type(e).__name__, str(e)[:100]))
        return None


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            return []
    return []


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(rec, sources, lotteries, honest, honest_age_days):
    gen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec["ts"]))

    rows_sources = ""
    for s in sources:
        state = s.get("state", "?")
        color = "#4ade80" if state == "closed" else ("#fbbf24" if state == "half_open" else "#ff6b6b")
        lf = s.get("last_failure") or "无"
        rows_sources += (
            "<tr><td>{src}</td><td style='color:{c}'>{st}</td>"
            "<td>{f}</td><td>{ok}</td><td>{lf}</td></tr>"
        ).format(src=_esc(s.get("source")), c=color, st=state,
                 f=s.get("total_failure", 0), ok=s.get("total_success", 0), lf=_esc(lf))

    rows_lots = ""
    for l in lotteries:
        age = l.get("data_age_min")
        age_s = "{0} 分钟".format(age) if age is not None else "缺失"
        stale = l.get("stale")
        color = "#ff6b6b" if stale else "#4ade80"
        rows_lots += (
            "<tr><td>{nm}</td><td style='color:{c}'>{age}</td>"
            "<td style='color:{c}'>{judge}</td></tr>"
        ).format(nm=_esc(l.get("name")), c=color, age=age_s, judge=("陈旧" if stale else "新鲜"))

    if honest:
        if honest_age_days is not None and honest_age_days <= 7:
            warn = ""
        else:
            warn = ("<p style='color:#fbbf24'>⚠ 诚实基准已 {0} 天未刷新，"
                    "建议运行「诚实回测刷新」Skill 更新。</p>").format(honest_age_days)
        honest_html = (
            "<h2>诚实基准（仅信号清晰度，非中奖概率）</h2>{warn}"
            "<pre style='white-space:pre-wrap;background:#1a1d27;padding:10px;"
            "border-radius:6px'>{body}</pre>"
        ).format(warn=warn, body=_esc(json.dumps(honest, ensure_ascii=False, indent=2)[:2000]))
    else:
        honest_html = "<p style='color:#fbbf24'>未找到 lottery_health_report.json，诚实基准缺失。</p>"

    alert = ""
    if rec["open"] or rec["stale_lotteries"]:
        alert = (
            "<div style='border:1px solid #ff6b6b;color:#ff6b6b;padding:8px;"
            "border-radius:6px;margin:8px 0'>⚠ 异常：熔断源 {0} 个，陈旧彩种 {1} 个</div>"
        ).format(rec["open"], rec["stale_lotteries"])

    html = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<title>彩票数据源健康日报</title>
<style>body{{background:#0f1117;color:#e6e6e6;font-family:system-ui,sans-serif;margin:24px}}
h1{{color:#4aa3ff}} h2{{color:#cbd5e1;margin-top:24px}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #2a2e3a;padding:6px 10px;text-align:left}}
th{{background:#1a1d27}} .meta{{color:#9aa0aa;font-size:13px}}</style></head><body>
<h1>🎯 彩票数据源健康日报</h1>
<p class=meta>生成时间：{gen} ｜ 数据源 {tot} 个 ｜ 熔断 open {op} / half_open {ho}
｜ 陈旧彩种 {sl}</p>
{alert}
<h2>数据源熔断状态</h2>
<table><tr><th>数据源</th><th>状态</th><th>累计失败</th><th>累计成功</th><th>最后失败</th></tr>{rs}</table>
<h2>各彩种数据新鲜度（&gt;24h 视为陈旧）</h2>
<table><tr><th>彩种</th><th>数据年龄</th><th>判定</th></tr>{rl}</table>
{honest}
<p class=meta>本日报仅监控数据源可用性与数据新鲜度，不预测中奖、不输出中奖概率。
熔断/陈旧告警请交人工或看门狗处理。</p>
</body></html>""".format(
        gen=gen, tot=rec["total_sources"], op=rec["open"], ho=rec["half_open"],
        sl=rec["stale_lotteries"], alert=alert, rs=rows_sources, rl=rows_lots,
        honest=honest_html,
    )
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    quiet = "--quiet" in sys.argv
    data = probe()
    now = time.time()
    if data is None:
        msg = "⚠ 数据源健康端点不可达（server未运行或端口异常），跳过本次日报。"
        log(msg)
        if quiet:
            print(msg)
        return 1
    if not data.get("ok"):
        log("端点返回 ok=false: {0}".format(data.get("error")))
        if quiet:
            print("ENDPOINT-ERROR: {0}".format(data.get("error")))
        return 1

    sources = data.get("sources", [])
    lotteries = data.get("lotteries", [])

    open_breakers = [s for s in sources if s.get("state") == "open"]
    half_open = [s for s in sources if s.get("state") == "half_open"]
    stale_lots = [l for l in lotteries if l.get("stale")]

    # 诚实基准新鲜度
    honest = None
    honest_age_days = None
    if os.path.exists(HONEST_REPORT):
        try:
            honest = json.load(open(HONEST_REPORT, encoding="utf-8"))
            if honest.get("generated_at"):
                honest_age_days = int((now - honest["generated_at"]) / 86400)
        except Exception:
            honest = None

    rec = {
        "ts": now,
        "total_sources": len(sources),
        "open": len(open_breakers),
        "half_open": len(half_open),
        "stale_lotteries": len(stale_lots),
        "lotteries": [{"name": l.get("name"), "age": l.get("data_age_min"), "stale": l.get("stale")} for l in lotteries],
        "sources": [{"source": s.get("source"), "state": s.get("state"), "fail": s.get("total_failure")} for s in sources],
    }
    hist = load_history()
    hist.append(rec)
    hist = hist[-HISTORY_KEEP:]
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

    render_html(rec, sources, lotteries, honest, honest_age_days)

    summary = "数据源:{tot} 熔断(open={op},half_open={ho}) 陈旧彩种:{sl}".format(
        tot=len(sources), op=len(open_breakers), ho=len(half_open), sl=len(stale_lots))
    if open_breakers:
        summary += " ⚠熔断:" + ",".join(b["source"] for b in open_breakers)
    if stale_lots:
        summary += " 陈旧:" + ",".join(l["name"] for l in stale_lots)
    log("日报已生成: " + REPORT_FILE)
    log(summary)
    if quiet:
        print(summary)
    return 0 if not (open_breakers or stale_lots) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        sys.stderr.write("[数据源健康日报异常] {0}\n".format(e))
        sys.exit(2)
