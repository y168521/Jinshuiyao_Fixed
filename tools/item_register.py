#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本轮事项登记器 (item register) — 收工门禁「反向自查」的数据底座

背景（JS-20260920-02 教训）：
    排查/诊断/定性类工作**不产生代码改动**，AI 极易误以为"没改代码就不用留痕"，
    导致三件套（交接中心/经验箱/总索引）整轮漏登，而旧的收工门禁只检查
    "今天有没有登记过"，只要当天有别的事登记了就放行 —— 抓不住"第二件事漏登"。

机制：
    干活前先 `add` 申报事项 → 收工前 `close <id> JS-编号` 回填编号 →
    `tools/closeout_gate.py` 校验：存在 status=open 或 done 但无编号的事项即 FAIL。

数据文件：金水谣数据/log/本轮事项清单.json（随仓库同步，跨会话可见）

用法：
    python tools/item_register.py add "修复数据真实性守卫假红"
    python tools/item_register.py list
    python tools/item_register.py close 3 JS-20260920-02
    python tools/item_register.py drop 3
    python tools/item_register.py purge          # 清掉已闭环(done 且有编号)的事项
"""

import json
import os
import re
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, "金水谣数据", "log", "本轮事项清单.json")

JS_RE = re.compile(r"^JS-\d{8}-\d{2}$")


# ---------------------------------------------------------------------------
# 读写（共享文件，读改写需谨慎：单进程工具，不引入锁，保留 last_write 便于排查）
# ---------------------------------------------------------------------------
def load_items():
    if not os.path.isfile(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def save_items(items):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _next_id(items):
    return (max([i.get("id", 0) for i in items]) + 1) if items else 1


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def cmd_add(title):
    items = load_items()
    item = {
        "id": _next_id(items),
        "title": title,
        "status": "open",          # open -> done
        "js": None,                # 回填的留痕编号
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": None,
    }
    items.append(item)
    save_items(items)
    print(f"[item] 已登记 #{item['id']}: {title}")
    print("       收工前请回填编号: python tools/item_register.py close %d JS-YYYYMMDD-NN" % item["id"])
    return 0


def cmd_list():
    items = load_items()
    if not items:
        print("[item] 清单为空（本轮未申报事项）")
        return 0
    print("=" * 60)
    print("  本轮事项清单")
    print("=" * 60)
    for it in items:
        if it.get("status") == "done" and it.get("js"):
            flag = "OK  "
        elif it.get("status") == "done":
            flag = "NOJS"
        else:
            flag = "OPEN"
        print(f"  [{flag}] #{it['id']} {it['title']}  (js={it.get('js') or '-'})")
    return 0


def cmd_close(item_id, js):
    if not JS_RE.match(js or ""):
        print(f"[item] 编号格式不对: {js}（应为 JS-YYYYMMDD-NN）")
        return 1
    items = load_items()
    for it in items:
        if it.get("id") == item_id:
            it["status"] = "done"
            it["js"] = js
            it["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_items(items)
            print(f"[item] #{item_id} 已闭环 -> {js}")
            return 0
    print(f"[item] 未找到 #{item_id}")
    return 1


def cmd_drop(item_id):
    items = load_items()
    left = [i for i in items if i.get("id") != item_id]
    if len(left) == len(items):
        print(f"[item] 未找到 #{item_id}")
        return 1
    save_items(left)
    print(f"[item] 已删除 #{item_id}")
    return 0


def cmd_purge():
    """清掉已闭环（done 且有编号）的事项，避免清单无限增长"""
    items = load_items()
    left = [i for i in items if not (i.get("status") == "done" and i.get("js"))]
    removed = len(items) - len(left)
    save_items(left)
    print(f"[item] 已清理 {removed} 条闭环事项，剩余 {len(left)} 条")
    return 0


# ---------------------------------------------------------------------------
# 供 closeout_gate 调用
# ---------------------------------------------------------------------------
def check_items():
    """返回 (ok, msg, open_items, no_js_items)

    ok=False 的情形：
      - 有 status=open 的事项（干了事没留痕）
      - 有 done 但没有 js 编号的事项（留痕了但没编号）
    """
    items = load_items()
    open_items = [i for i in items if i.get("status") == "open"]
    no_js = [i for i in items if i.get("status") == "done" and not i.get("js")]
    if not items:
        return True, "未申报事项（若本轮做过排查/诊断类工作，请先 add 登记）", [], []
    if open_items or no_js:
        parts = []
        if open_items:
            parts.append("未闭环 %d 项: %s" % (
                len(open_items), "; ".join(f"#{i['id']} {i['title']}" for i in open_items[:5])))
        if no_js:
            parts.append("缺编号 %d 项: %s" % (
                len(no_js), "; ".join(f"#{i['id']} {i['title']}" for i in no_js[:5])))
        return False, "；".join(parts), open_items, no_js
    done = [i for i in items if i.get("status") == "done"]
    return True, "本轮 %d 项全部闭环: %s" % (
        len(done), ", ".join(str(i.get("js")) for i in done)), [], []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "add":
        if len(sys.argv) < 3:
            print("[item] 用法: add \"事项描述\"")
            return 1
        return cmd_add(sys.argv[2])
    if cmd == "list":
        return cmd_list()
    if cmd == "close":
        if len(sys.argv) < 4:
            print("[item] 用法: close <id> JS-YYYYMMDD-NN")
            return 1
        return cmd_close(int(sys.argv[2]), sys.argv[3])
    if cmd == "drop":
        if len(sys.argv) < 3:
            print("[item] 用法: drop <id>")
            return 1
        return cmd_drop(int(sys.argv[2]))
    if cmd == "purge":
        return cmd_purge()
    if cmd == "check":
        ok, msg, _, _ = check_items()
        print(("[OK] " if ok else "[FAIL] ") + msg)
        return 0 if ok else 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
