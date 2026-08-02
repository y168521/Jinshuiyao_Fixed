# -*- coding: utf-8 -*-
"""数据真实性自动守卫（自动同步第7步调用）

每次运行执行全量数据真实性检测（足彩/股票/彩票），把结果追加到
`金水谣数据/log/data_truth.log`。仅在总体状态发生变化时输出
`[STATUS-CHANGED]` 行（供 ps1 判断是否弹窗提醒），避免每 30 分钟打扰。

exit code: 0=healthy, 1=degraded, 2=critical, 3=运行失败
"""
import os
import sys
import io

if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(BASE)
LOG_PATH = os.path.join(REPO, "金水谣数据", "log", "data_truth.log")

STATUS_LABEL = {"healthy": "健康", "degraded": "降级", "critical": "异常"}
CHECK_LABEL = {"pass": "正常", "warn": "注意", "fail": "异常", "unknown": "未知"}
EXIT_CODE = {"healthy": 0, "degraded": 1, "critical": 2}


def last_status() -> str:
    """读取日志最后一行的状态"""
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        for ln in reversed(lines):
            if "状态:" in ln and "]" in ln:
                return ln.split("状态:")[1].split("]")[0].strip()
    except OSError:
        pass
    return ""


def main():
    sys.path.insert(0, REPO)
    try:
        from core.data_truth_guard import DataTruthGuard
        report = DataTruthGuard().run_full_check()
    except Exception as e:
        print("[STATUS-CHANGED] 数据真实性守卫运行失败: %s" % e)
        return 3

    overall = report.get("overall", "critical")
    summary = report.get("summary", {})
    ss = report.get("subsystems", {})
    ss_desc = " ".join(
        "%s:%s" % (name, CHECK_LABEL.get(v.get("status", "unknown"), "未知"))
        for name, v in sorted(ss.items())
    )
    line = "[%s] 状态: %s ] 通过=%d 警告=%d 失败=%d | %s" % (
        report.get("timestamp", "-"), STATUS_LABEL.get(overall, overall),
        summary.get("pass", 0), summary.get("warn", 0), summary.get("fail", 0), ss_desc,
    )

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    prev = last_status()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    new_label = STATUS_LABEL.get(overall, overall)
    changed = prev != new_label
    print("数据真实性: %s（通过=%d 警告=%d 失败=%d）" % (
        new_label, summary.get("pass", 0),
        summary.get("warn", 0), summary.get("fail", 0)))
    if overall != "healthy":
        for a in report.get("action_required", []):
            print("  建议: %s" % a)
        if changed:
            print("[STATUS-CHANGED] 数据真实性状态变为「%s」（此前「%s」），请查看金水谣数据/log/data_truth.log" %
                  (new_label, prev))
    return EXIT_CODE.get(overall, 2)


if __name__ == "__main__":
    sys.exit(main())
