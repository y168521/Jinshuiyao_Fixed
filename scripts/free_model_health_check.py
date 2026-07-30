# -*- coding: utf-8 -*-
"""金水谣 · 免费模型健康巡检

主动探活：对每个启用的免费模型发轻量请求，更新健康状态到
金水谣数据/free_model_status.json；全挂时写告警标记并以退出码 2 提示。

供 WorkBuddy 自动化（jinshuiyao-free-model-health）每日定时触发，
体现"前瞻性主动巡检，而非被动等挂"——免费模型政策多变，早一分钟发现早一分钟顶住。

只读取配置 + 轻量 ping，零业务数据写入。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.free_model_pool import health_check_all


def main():
    res = health_check_all()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    # 全挂 → 非 0 退出码，便于自动化层识别并告警
    if res.get("all_down"):
        sys.exit(2)


if __name__ == "__main__":
    main()
