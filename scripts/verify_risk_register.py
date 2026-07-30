# -*- coding: utf-8 -*-
"""风险登记册校验脚本（T03，纯标准库）

校验 `金水谣数据/risk_register.json`（单一真源）：
  ① 合法 json + dict + 含 risks 数组
    ② 每条 9(+1) 字段齐全；枚举(probability/impact_level/mitigation_status)合法；
     owner 非空且非"待定"；id 格式 R-\\d{3} 且唯一、升序无空缺
  ③ last_review 超 review_policy.stale_days(默认90) 标红 → errors
  ④ 风险登记册.md 生成时间 ≥ json 修改时间（防双写分叉）→ errors
  ⑤ mitigation_status 不在已知枚举 → warns

入口：`verify(path) -> (ok, errors, warns)`，供 lint_knowledge.py import 复用。
CLI 退出码：0=通过；1=有错误；2=文件缺失。
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime, date

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_DEFAULT_JSON = os.path.join(_PROJECT_ROOT, "金水谣数据", "risk_register.json")
_DEFAULT_MD = os.path.join(_PROJECT_ROOT, "金水谣数据", "风险登记册.md")

REQUIRED_KEYS = [
    "id", "description", "impact", "probability", "impact_level",
    "mitigation", "mitigation_status", "owner", "early_signal", "last_review",
]
PROBABILITY_LEVELS = {"高", "中", "低"}
MITIGATION_STATUSES = {"已落地", "待落地(项④)", "待落地(项⑤/⑥)", "规划中"}
ID_RE = re.compile(r"^R-\d{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OWNER_FORBIDDEN = {"待定", "待补充", "TBD", "?"}


def _default_json_path():
    return _DEFAULT_JSON


def _parse_date(s):
    """解析 YYYY-MM-DD -> date；失败返回 None。"""
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def verify(path=None):
    """校验风险登记册。返回 (ok, errors, warns)。"""
    if path is None:
        path = _default_json_path()
    errors = []
    warns = []

    if not os.path.isfile(path):
        return False, ["风险登记册 json 文件缺失: " + path], warns

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, ["风险登记册 json 解析失败: %s" % e], warns

    if not isinstance(data, dict):
        return False, ["风险登记册 json 顶层应为对象"], warns
    risks = data.get("risks")
    if not isinstance(risks, list):
        return False, ["风险登记册 json 缺 risks 数组或类型错误"], warns

    policy = data.get("review_policy", {}) or {}
    stale_days = int(policy.get("stale_days", 90))
    today = date.today()

    # ② 字段齐全 + 枚举 + owner + id
    seen_ids = []
    for idx, r in enumerate(risks):
        tag = "第%d条" % (idx + 1)
        if not isinstance(r, dict):
            errors.append("%s：不是对象" % tag)
            continue
        missing = [k for k in REQUIRED_KEYS if k not in r]
        if missing:
            errors.append("%s：缺字段 %s" % (tag, "/".join(missing)))

        rid = r.get("id", "")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            errors.append("%s：id 格式非法（应为 R-NNN）: %r" % (tag, rid))
        else:
            seen_ids.append(rid)

        prob = r.get("probability", "")
        if prob not in PROBABILITY_LEVELS:
            errors.append("[%s] probability 枚举非法: %r（应为 高/中/低）" % (rid, prob))
        ilevel = r.get("impact_level", "")
        if ilevel not in PROBABILITY_LEVELS:
            errors.append("[%s] impact_level 枚举非法: %r（应为 高/中/低）" % (rid, ilevel))

        mstatus = r.get("mitigation_status", "")
        if mstatus not in MITIGATION_STATUSES:
            warns.append("[%s] mitigation_status 不在已知枚举: %r" % (rid, mstatus))

        owner = r.get("owner", "")
        if not isinstance(owner, str) or not owner.strip():
            errors.append("[%s] owner 为空" % rid)
        elif owner.strip() in OWNER_FORBIDDEN:
            errors.append("[%s] owner 为'%s'（禁止待定，须填具体模块/机制名）" % (rid, owner.strip()))

        # ③ 过期标红
        d = _parse_date(r.get("last_review", ""))
        if d is None:
            errors.append("[%s] last_review 非法或缺失: %r" % (rid, r.get("last_review", "")))
        else:
            age = (today - d).days
            if age > stale_days:
                errors.append("[%s] last_review(%s) 距今 %d 天，超 stale_days(%d)→已过期需复查"
                               % (rid, r.get("last_review"), age, stale_days))

    # id 唯一 + 升序无空缺
    if len(seen_ids) != len(set(seen_ids)):
        errors.append("风险 id 不唯一: %s" % seen_ids)
    else:
        nums = []
        ok_nums = True
        for rid in seen_ids:
            m = re.match(r"^R-(\d{3})$", rid)
            if not m:
                ok_nums = False
                break
            nums.append(int(m.group(1)))
        if ok_nums:
            if nums != list(range(1, len(nums) + 1)):
                errors.append("风险 id 未升序无空缺（应为 R-001,R-002,...）: %s" % seen_ids)

    # ④ md 生成时间 ≥ json 修改时间（防双写分叉）
    md_path = os.path.join(os.path.dirname(path), "风险登记册.md")
    if not os.path.isfile(md_path):
        errors.append("风险登记册.md 缺失（须由 scripts/gen_risk_md.py 生成）: " + md_path)
    else:
        try:
            json_mtime = os.path.getmtime(path)
            md_mtime = os.path.getmtime(md_path)
            if md_mtime < json_mtime - 1e-6:
                errors.append("风险登记册.md 生成时间早于 json 修改时间（疑似未重新生成，双写分叉风险）")
        except Exception as e:
            warns.append("md/json 时间戳比对失败: %s" % e)

    ok = (len(errors) == 0)
    return ok, errors, warns


def main():
    ap = argparse.ArgumentParser(description="风险登记册校验（纯标准库）")
    ap.add_argument("--path", default=_DEFAULT_JSON, help="risk_register.json 路径")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print("❌ 风险登记册文件缺失: " + args.path)
        return 2

    ok, errors, warns = verify(args.path)
    if args.json:
        print(json.dumps({"ok": ok, "errors": errors, "warnings": warns},
                         ensure_ascii=False, indent=2))
    else:
        if errors:
            print("❌ 错误（%d 项）:" % len(errors))
            for e in errors:
                print("   - " + e)
        else:
            print("✅ 无错误")
        if warns:
            print("⚠️ 警告（%d 项）:" % len(warns))
            for w in warns:
                print("   - " + w)
        else:
            print("✅ 无警告")
        print("结论:", "通过 ✅" if ok else "未通过 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
