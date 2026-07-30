#!/usr/bin/env python3
"""金水谣·前端健康巡检脚本 — 只读探测，绝不改码/重启。

探测全部 GET/POST 端点，分类 HTTP 码 + 响应片段前 200 字节。
产出：健康率 + 异常清单（端点、现象、建议修复）。
"""

import urllib.request
import urllib.error
import json
import time
import sys
import socket
from datetime import datetime

BASE_URL = "http://localhost:18888"
TIMEOUT = 15  # 秒，探测超时

# ── 端点清单（从 server/router.py 路由表提取）──

# GET 端点：(路径, 查询参数, 说明)
GET_ENDPOINTS = [
    ("/health", "", "健康检查"),
    ("/api/fund-notification", "", "基金日报通知状态"),
    ("/api/fund-notification/read", "", "标记通知已读"),
    ("/api/ip", "", "本机局域网IP"),
    ("/api/test-results", "", "最近测试结果"),
    ("/api/selfcheck", "", "启动自检报告"),
    ("/api/selfcheck/history", "", "自检历史日志"),
    ("/api/ai/mode", "", "当前AI运行模式"),
    ("/api/ai/status", "", "AI服务详细状态"),
    ("/api/status", "", "AI服务状态兼容"),
    ("/api/route", "?task=probe", "任务智能路由(只读)"),
    ("/api/project/scan", "", "项目自动扫描"),
    ("/api/project/recommend", "", "四维推荐"),
    ("/api/memory", "", "AI记忆读取"),
    ("/api/user-kb/list", "", "知识库卡片列表"),
    ("/api/user-kb/detail", "?id=probe", "知识库卡片详情"),
    ("/api/user-kb/stats", "", "知识库统计"),
    ("/api/knowledge/crosslinks/stats", "", "交叉链接统计"),
    ("/api/knowledge/crosslinks/all", "", "全部交叉链接"),
    ("/api/knowledge/crosslinks", "?lib=core&id=probe", "跨库链接查询"),
    ("/api/knowledge/graph", "", "知识图谱数据"),
    ("/api/knowledge/graph/neighbors", "?entity=probe", "实体关联查询"),
    ("/api/knowledge/graph/top", "", "最重要实体"),
    ("/api/knowledge/graph/search", "?q=probe", "图谱三元组检索"),
    ("/api/knowledge/vector/search", "?q=probe", "语义向量召回"),
    ("/api/knowledge/tags/validate", "", "标签校验"),
    ("/api/scheduler/status", "", "定时任务状态"),
    ("/api/scheduler/log", "?limit=1", "定时任务日志"),
    ("/api/lottery/sources-health", "", "彩票数据源健康"),
    ("/api/lottery/reference", "?type=3d", "彩票多维参考"),
    ("/api/lottery/math-model", "?type=3d", "彩票数学模型"),
    ("/api/trend/data", "", "走势图数据"),
    ("/api/trend/freshness", "", "走势图新鲜度"),
    ("/api/review/dashboard", "", "审查仪表盘"),
    ("/api/review/patterns", "", "审查模式库"),
    ("/api/backtest", "?type=fund", "统一回测"),
    ("/api/fund-backtest", "?code=000001", "基金回测"),
    ("/api/fund-compare", "", "基金横向对比"),
    ("/api/prediction/stats", "", "预测统计"),
    ("/api/prediction/history", "", "预测历史"),
    ("/api/audit", "", "模型审查报告"),
]

# POST 端点：(路径, JSON body, 说明)
POST_ENDPOINTS = [
    ("/api/route", {"task": "probe"}, "任务智能路由(POST)"),
    ("/api/ask", {"question": "probe"}, "智能问答"),
    ("/api/chat", {"message": "probe"}, "AI对话"),
    ("/api/prediction/record", {"domain": "probe"}, "预测记录"),
    ("/api/prediction/list", {"domain": "probe"}, "预测列表"),
    ("/api/prediction/outcome", {"id": "probe"}, "预测结果录入"),
    ("/api/status", {}, "AI状态(POST)"),
    ("/api/ai/mode/set", {"mode": "online"}, "切换AI模式"),
    ("/api/review/trigger", {"files": ["probe.py"]}, "触发代码审查"),
    ("/api/review/feedback", {"review_id": "probe"}, "审查反馈"),
    ("/api/backtest", {"type": "fund"}, "统一回测(POST)"),
    ("/api/fund-backtest", {"code": "000001"}, "基金回测(POST)"),
    ("/api/fund-compare", {"codes": ["000001"]}, "基金对比(POST)"),
    ("/api/extract", {"url": "http://example.com"}, "视频文案提取"),
    ("/api/refine", {"content": "probe"}, "内容提炼"),
    ("/api/knowledge/stats", {}, "知识库统计(POST)"),
    ("/api/knowledge/search", {"q": "probe"}, "知识搜索"),
    ("/api/knowledge/list", {"limit": 1}, "知识列表"),
    ("/api/knowledge/add", {"title": "probe"}, "添加知识卡片"),
    ("/api/user-kb/add", {"title": "probe"}, "新增个人知识卡片"),
    ("/api/knowledge/extract-archive", {"url": "http://example.com"}, "URL提取归档"),
    ("/api/knowledge/crosslinks/discover", {}, "交叉链接自动发现"),
    ("/api/knowledge/graph/build", {}, "重建知识图谱"),
    ("/api/video/ingest", {"url": "http://example.com"}, "视频文案归档"),
    ("/api/memory", {"action": "probe"}, "AI记忆(POST)"),
    ("/api/run-tests", {"suite": "quick"}, "运行测试"),
    ("/api/error-report", {"error": "probe"}, "错误上报"),
]


def probe_get(path, query=""):
    """探测 GET 端点，返回 (http_code, response_snippet, error_type)."""
    url = f"{BASE_URL}{path}{query}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
            body = resp.read(200).decode("utf-8", errors="replace")
            return code, body, None
    except urllib.error.HTTPError as e:
        # 服务器返回了错误码（4xx/5xx）
        try:
            body = e.read(200).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body, None
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower() or "time" in reason.lower():
            return 0, "", "超时(疑似挂起/死锁)"
        return 0, "", f"连接失败: {reason}"
    except socket.timeout:
        return 0, "", "超时(疑似挂起/死锁)"
    except Exception as e:
        return 0, "", f"异常: {str(e)[:100]}"


def probe_post(path, body_dict):
    """探测 POST 端点，返回 (http_code, response_snippet, error_type)."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body_dict).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
            body = resp.read(200).decode("utf-8", errors="replace")
            return code, body, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(200).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body, None
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "timed out" in reason.lower() or "time" in reason.lower():
            return 0, "", "超时(疑似挂起/死锁)"
        return 0, "", f"连接失败: {reason}"
    except socket.timeout:
        return 0, "", "超时(疑似挂起/死锁)"
    except Exception as e:
        return 0, "", f"异常: {str(e)[:100]}"


def classify(code, snippet, error):
    """分类结果。返回 (category, suggestion)."""
    if error and ("超时" in error or "挂起" in error):
        return "挂起", "疑似死锁，检查是否用了普通 Lock（应改 RLock）"
    if error:
        return "连接失败", f"网络/连接异常: {error}"
    if 500 <= code <= 599:
        suggestion = "检查 handler 实现"
        if "AttributeError" in snippet:
            suggestion = "GuideHandler 缺少对应方法，需在 router.py 实现或补基础设施方法"
        return f"5xx({code})", suggestion
    if code == 404:
        return "404", "路由未注册或路径不匹配"
    if 400 <= code <= 499:
        return f"4xx({code})", "参数/鉴权问题(前端传入参数可能不兼容，需核对)"
    if code == 200:
        return "200 OK", ""
    if 200 <= code <= 299:
        return f"2xx({code})", ""
    if code == 0:
        return "无响应", "连接失败或超时"
    return f"其他({code})", ""


def main():
    print("=" * 70)
    print(f"  金水谣·前端健康巡检  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Server: {BASE_URL}")
    print("=" * 70)
    print()

    # ── 前置检查 ──
    print("[前置] 验证 /health ... ", end="", flush=True)
    code, snippet, err = probe_get("/health")
    if code != 200:
        print(f"✗ ({code})")
        print(f"\n  ❌ 告警：server未运行或异常，health检查失败（code={code}）")
        print("  → 跳过全部端点巡检，脚本结束。")
        return 1
    print("✓ 200")

    # ── 批量探测 ──
    results = []
    total = 0
    ok_count = 0

    print(f"\n[GET] 探测 {len(GET_ENDPOINTS)} 个端点...")
    for path, query, desc in GET_ENDPOINTS:
        code, snippet, err = probe_get(path, query)
        cat, sug = classify(code, snippet, err)
        results.append(("GET", path, desc, code, snippet[:120], err, cat, sug))
        total += 1
        if cat == "200 OK":
            ok_count += 1
        # 简要进度
        sym = "✓" if cat == "200 OK" else "✗"
        print(f"  {sym} {path:50s} → {cat:12s}")

    print(f"\n[POST] 探测 {len(POST_ENDPOINTS)} 个端点...")
    for path, body, desc in POST_ENDPOINTS:
        code, snippet, err = probe_post(path, body)
        cat, sug = classify(code, snippet, err)
        results.append(("POST", path, desc, code, snippet[:120], err, cat, sug))
        total += 1
        if cat == "200 OK":
            ok_count += 1
        sym = "✓" if cat == "200 OK" else "✗"
        print(f"  {sym} {path:50s} → {cat:12s}")

    # ── 汇总报告 ──
    print("\n" + "=" * 70)
    print("  巡检结果汇总")
    print("=" * 70)

    healthy = [r for r in results if r[6] == "200 OK"]
    abnormal = [r for r in results if r[6] != "200 OK"]

    health_rate = ok_count / total * 100 if total > 0 else 0

    print(f"\n  总端点: {total} | 正常: {ok_count} | 异常: {len(abnormal)}")
    print(f"  健康率: {health_rate:.1f}%")

    if abnormal:
        print(f"\n  ── 异常清单 ({len(abnormal)} 个) ──")
        for method, path, desc, code, snippet, err, cat, sug in abnormal:
            print(f"\n  [{method}] {path}")
            print(f"    说明: {desc}")
            print(f"    现象: {cat}")
            if err:
                print(f"    细节: {err}")
            if snippet:
                print(f"    响应片段: {snippet[:100]}")
            if sug:
                print(f"    建议: {sug}")

        # 专项统计
        code_500 = [r for r in abnormal if "5xx" in r[6]]
        code_404 = [r for r in abnormal if r[6] == "404"]
        hang = [r for r in abnormal if r[6] == "挂起"]
        other = [r for r in abnormal if r[6] not in ("5xx", "404", "挂起") and "5xx" not in r[6]]

        print(f"\n  ── 分类统计 ──")
        print(f"    5xx 服务端错误: {len(code_500)}")
        print(f"    404 路由未匹配: {len(code_404)}")
        print(f"    挂起/超时: {len(hang)}")
        print(f"    其他异常: {len(other)} (4xx/连接失败等)")

        # 重点提醒
        if code_500:
            attr_count = sum(1 for r in code_500 if "AttributeError" in (r[4] or "") + (r[5] or ""))
            if attr_count:
                print(f"\n  ⚠️  其中 {attr_count} 个 500 错误包含 AttributeError → GuideHandler 缺方法")
        if hang:
            print(f"\n  ⚠️  其中 {len(hang)} 个挂起/超时 → 疑似死锁，建议检查改 RLock")
    else:
        print(f"\n  ✅ 全部端点正常，无异常。")

    print("\n" + "=" * 70)
    print("  巡检完成。只读探测，未做任何改码/重启。")
    print("=" * 70)

    return 0 if len(abnormal) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
