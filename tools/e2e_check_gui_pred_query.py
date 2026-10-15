# -*- coding: utf-8 -*-
"""端到端验证：GUI 预测列表走统一查询层（JS-20261015-04）。

用真实 3636 条彩票预测数据，验证：
  1. 默认（无条件）第 1 页只返回 page_size 条，total=3636
  2. 彩种筛选生效
  3. 关键词（无空格号码串）能命中
  4. 翻页不改条件
  5. 空态三分支：no_data / no_match / error
"""
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import tkinter as tk  # noqa: E402

LOT_FILE = os.path.join(BASE, "金水谣数据", "predictions.json")


def _load():
    with io.open(LOT_FILE, encoding="utf-8") as f:
        return json.load(f)


def main():
    root = tk.Tk()
    root.withdraw()

    from gui.main_window import App

    w = App.__new__(App)
    w._init_pred_query_state()
    w.preds = _load()
    n = len(w.preds)
    print("[0] 载入真实预测记录: %d 条" % n)
    assert n > 3000, "真实数据量异常"

    # ---- 场景 1：无条件第 1 页 ----
    w._ensure_pred_query_vars()
    w._pred_size_var.set("20")
    w._pred_page = 1
    rows, total, pages, reason, err = w._query_pred_page()
    print("[1] 无条件 page=1 size=20 -> rows=%d total=%d pages=%d reason=%r err=%r"
          % (len(rows), total, pages, reason, err))
    assert err == "", err
    assert len(rows) == 20, "每页条数不对: %d" % len(rows)
    assert total == n, "total 应为过滤后总数 %d，实际 %d" % (n, total)
    assert pages == (n + 19) // 20
    assert reason == ""

    # ---- 场景 2：彩种筛选 ----
    w._pred_lot_var.set("福彩3D")
    w._pred_size_var.set("200")
    w._pred_page = 1
    rows, total, pages, reason, err = w._query_pred_page()
    lots = set(r.get("lot") for r in rows)
    print("[2] 彩种=福彩3D -> rows=%d total=%d lots=%s reason=%r"
          % (len(rows), total, sorted(lots), reason))
    assert err == "", err
    assert lots == {"福彩3D"}, "筛选后仍混入其他彩种: %s" % lots
    assert total == 1018, "福彩3D 应为 1018 条，实际 %d" % total

    # ---- 场景 3：关键词命中（无空格号码串）----
    sample = [r for r in w.preds if r.get("lot") == "福彩3D"][0]
    nums = str(sample.get("nums", "")).replace(",", "").replace(" ", "")
    w._pred_lot_var.set("")
    w._pred_kw_var.set(nums)
    w._pred_page = 1
    rows, total, pages, reason, err = w._query_pred_page()
    hit = any(str(r.get("nums", "")).replace(",", "") == nums for r in rows)
    print("[3] 关键词=%s -> total=%d 命中样本=%s" % (nums, total, hit))
    assert err == "", err
    assert hit, "无空格号码串未能命中原始记录（号码结构化比对失效）"

    # ---- 场景 4：翻页保持条件（必须用多页数据，否则断言形同虚设）----
    w._pred_kw_var.set("")
    w._pred_lot_var.set("福彩3D")   # 1018 条 / 每页 20 = 51 页
    w._pred_size_var.set("20")
    w._pred_page = 1
    rows1, total1, pages1, _, err = w._query_pred_page()
    assert err == "", err
    w._pred_next_page()
    rows2, total2, pages2, _, err = w._query_pred_page()
    assert err == "", err
    print("[4] 翻页: pages=%d | 第1页 %d 条(page=%d) -> 第2页 %d 条(page=%d) total=%d"
          % (pages1, len(rows1), 1, len(rows2), w._pred_page, total2))
    assert pages1 == (1018 + 19) // 20, "页数不对: %d" % pages1
    assert w._pred_page == 2, "翻页失败，仍停在第 %d 页" % w._pred_page
    assert total2 == total1 == 1018, "翻页后 total 变了，说明条件未保持"
    assert all(r.get("lot") == "福彩3D" for r in rows2), "翻页后筛选条件丢失"
    ids1 = set(id(r) for r in rows1)
    ids2 = set(id(r) for r in rows2)
    assert not (ids1 & ids2), "两页数据重叠，分页切片错误"
    # 末页：越界页码必须被夹取，而不是返回空
    w._pred_last_page()
    rowsL, totalL, pagesL, reasonL, err = w._query_pred_page()
    print("    末页: page=%d rows=%d reason=%r" % (w._pred_page, len(rowsL), reasonL))
    assert err == "", err
    assert w._pred_page == pages1, "末页页码未被夹取: %d != %d" % (w._pred_page, pages1)
    assert rowsL, "末页不应为空"

    # ---- 场景 5：空态 no_match ----
    w._pred_kw_var.set("不存在的号码zzz9999")
    rows, total, pages, reason, err = w._query_pred_page()
    print("[5] 不可能关键词 -> rows=%d reason=%r" % (len(rows), reason))
    assert rows == [] and reason == "no_match", (len(rows), reason)

    # ---- 场景 6：空态 no_data ----
    w._pred_kw_var.set("")
    w._pred_lot_var.set("")
    w._pred_size_var.set("50")
    w.preds = []
    rows, total, pages, reason, err = w._query_pred_page()
    print("[6] 空数据源 -> rows=%d reason=%r" % (len(rows), reason))
    assert rows == [] and reason == "no_data", (len(rows), reason)

    # ---- 场景 7：故障不静默 ----
    broken = App.__new__(App)
    broken._init_pred_query_state()
    broken.preds = None  # 制造故障：None 不可迭代
    rows, total, pages, reason, err = broken._query_pred_page()
    print("[7] 故障注入 -> rows=%d err=%r" % (len(rows), err[:60]))
    assert rows == [] and err != "", "故障被静默降级为空列表（本项目头号禁止项）"

    root.destroy()
    print("\n=== 端到端全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
