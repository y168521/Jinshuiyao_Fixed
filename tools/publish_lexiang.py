#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
乐享（云知）单向发布引擎
========================
本地是唯一真源，乐享只做「只读镜像」，供手机/跨设备/分享场景查看。
本脚本**不直接调用 MCP**（MCP 只有 AI 助手能调），职责分离：

    脚本负责：算出该发什么、安全闸门、记录真实结果、出成果页
    AI  负责：拿计划去真实调用 entry_import_content / entry_create_folder

用法：
    py -3.14 tools/publish_lexiang.py                    # 干跑：只看清单，不碰网络（默认）
    py -3.14 tools/publish_lexiang.py --plan             # 生成发布计划 JSON（喂给 AI 执行）
    py -3.14 tools/publish_lexiang.py --record 结果.json  # 回写真实 entry_id / url
    py -3.14 tools/publish_lexiang.py --report           # 生成暗色成果展示页 HTML

安全闸门（任一命中即拒发该文件）：
    ① 命中 blacklist_patterns   ② 内容扫出疑似密钥   ③ 超过 max_bytes

纯标准库，无第三方依赖。
"""

import argparse
import fnmatch
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime

try:
    # 只放宽错误处理，不强改 encoding：
    # 强制 utf-8 会和 cmd 的 GBK 代码页打架，导致双击 bat 时满屏乱码。
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(BASE_DIR, "config", "lexiang_publish.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "金水谣数据")
STATE_PATH = os.path.join(DATA_DIR, "lexiang_publish_state.json")
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
PLAN_PATH = os.path.join(OUT_DIR, "lexiang_publish_plan.json")
REPORT_PATH = os.path.join(OUT_DIR, "乐享发布成果页.html")


# ---------------------------------------------------------------- 基础读写

def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print("[警告] 读取失败 %s：%s" % (path, exc))
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_config():
    cfg = _read_json(CONFIG_PATH, None)
    if cfg is None:
        raise SystemExit("[致命] 找不到配置：%s" % CONFIG_PATH)
    return cfg


def load_state():
    return _read_json(STATE_PATH, {"target": {}, "items": {}, "history": []})


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 安全闸门

def hit_blacklist(rel_path, patterns):
    norm = rel_path.replace("\\", "/")
    for pat in patterns or []:
        if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(os.path.basename(norm), pat):
            return pat
    return None


def scan_secrets(text, patterns):
    hits = []
    for pat in patterns or []:
        try:
            if re.search(pat, text):
                hits.append(pat)
        except re.error:
            continue
    return hits


def inspect(entry, cfg):
    """返回单个白名单项的体检结果 dict。"""
    opts = cfg.get("options", {})
    rel = entry["path"]
    abs_path = os.path.join(PROJECT_ROOT, rel)
    res = {
        "path": rel,
        "title": entry.get("title") or os.path.basename(rel),
        "group": entry.get("group", "misc"),
        "order": entry.get("order", 999),
        "abs_path": abs_path,
        "ok": False,
        "reason": "",
        "sha256": "",
        "bytes": 0,
    }

    if not os.path.exists(abs_path):
        res["reason"] = "文件不存在"
        return res

    bad = hit_blacklist(rel, cfg.get("blacklist_patterns"))
    if bad:
        res["reason"] = "命中黑名单：%s" % bad
        return res

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        res["reason"] = "读取失败：%s" % exc
        return res

    size = len(text.encode("utf-8"))
    res["bytes"] = size
    if size > int(opts.get("max_bytes", 300000)):
        res["reason"] = "超过体积上限（%d 字节）" % size
        return res

    if opts.get("secret_scan", True):
        hits = scan_secrets(text, cfg.get("secret_patterns"))
        if hits:
            res["reason"] = "疑似密钥命中 %d 条规则，已拒发" % len(hits)
            return res

    res["sha256"] = sha256_text(text)
    res["ok"] = True
    return res


# ---------------------------------------------------------------- 计划构建

def build_items(cfg, state):
    skip_unchanged = cfg.get("options", {}).get("skip_unchanged", True)
    known = state.get("items", {})
    items = []
    for entry in cfg.get("whitelist", []):
        res = inspect(entry, cfg)
        prev = known.get(res["path"], {})
        if not res["ok"]:
            res["action"] = "blocked"
        elif not prev.get("entry_id"):
            res["action"] = "create"
        elif skip_unchanged and prev.get("sha256") == res["sha256"]:
            res["action"] = "skip"
        else:
            res["action"] = "update"
        res["entry_id"] = prev.get("entry_id", "")
        res["url"] = prev.get("url", "")
        items.append(res)
    gorder = group_order(cfg)
    items.sort(key=lambda x: (gorder.get(x["group"], 999), x["order"]))
    return items


def group_order(cfg):
    """分组必须按配置声明顺序，不能按 key 字母序。"""
    return {g["key"]: i for i, g in enumerate(cfg.get("groups", []))}


def resolve_target(cfg, state):
    tgt = dict(cfg.get("target", {}))
    tgt.update({k: v for k, v in (state.get("target") or {}).items() if v})
    url = (tgt.get("space_url") or "").strip()
    if url and not tgt.get("space_id"):
        m = re.search(r"/spaces/([A-Za-z0-9_-]+)", url)
        if m:
            tgt["space_id"] = m.group(1)
    return tgt


# ---------------------------------------------------------------- 各子命令

def cmd_dryrun(cfg, state):
    tgt = resolve_target(cfg, state)
    items = build_items(cfg, state)

    print("=" * 64)
    print(" 乐享单向发布 · 干跑预览（不联网、不写入）")
    print("=" * 64)
    if tgt.get("space_id"):
        print(" 目标知识库：%s" % (tgt.get("space_url") or tgt.get("space_id")))
    else:
        print(" 目标知识库：[未配置] 请把乐享知识库链接填进")
        print("             config/lexiang_publish.json → target.space_url")
    print("-" * 64)

    buckets = {}
    for it in items:
        buckets.setdefault(it["group"], []).append(it)

    names = {g["key"]: g["name"] for g in cfg.get("groups", [])}
    mark = {"create": "[新建]", "update": "[更新]", "skip": "[跳过]", "blocked": "[拒发]"}
    for gkey, lst in buckets.items():
        print("\n %s" % names.get(gkey, gkey))
        for it in lst:
            line = "   %s %s" % (mark.get(it["action"], "[?]"), it["title"])
            if it["action"] == "blocked":
                line += "  <- %s" % it["reason"]
            elif it["action"] != "skip":
                kb = it["bytes"] / 1024.0
                line += "  (%.1f KB)" % kb
                if kb > 100:
                    line += "  <- 偏大，建议单独一批导入"
            print(line)

    stat = {}
    for it in items:
        stat[it["action"]] = stat.get(it["action"], 0) + 1
    print("\n" + "-" * 64)
    print(" 合计：新建 %d · 更新 %d · 跳过 %d · 拒发 %d"
          % (stat.get("create", 0), stat.get("update", 0),
             stat.get("skip", 0), stat.get("blocked", 0)))
    if stat.get("blocked"):
        print(" 注意：拒发项不会上传，请先处理上面的原因。")
    print(" 下一步：确认无误后让 AI 助手跑 --plan，再由它真实导入。")
    return 0


def cmd_plan(cfg, state):
    tgt = resolve_target(cfg, state)
    if not tgt.get("space_id"):
        print("[拒绝] 目标知识库未配置，无法生成计划。")
        print("       请把乐享知识库链接填进 config/lexiang_publish.json → target.space_url")
        return 2

    items = build_items(cfg, state)
    todo = [it for it in items if it["action"] in ("create", "update")]
    if not todo:
        print("[提示] 没有需要发布的内容（全部未变更或被拒发）。")
        return 0

    groups = cfg.get("groups", [])
    used = {it["group"] for it in todo}
    plan = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": tgt,
        "root_folder_name": tgt.get("root_folder_name", "金水谣项目文档（自动发布）"),
        "folder_tree": [g for g in groups if g["key"] in used],
        "footer_note": cfg.get("options", {}).get("footer_note", ""),
        "batch_hint": "建议按 folder_tree 分批执行，一组一批，避免单次上下文过长。",
        "items": [
            {
                "id": it["path"],
                "group": it["group"],
                "title": it["title"],
                "source_abs_path": it["abs_path"],
                "sha256": it["sha256"],
                "bytes": it["bytes"],
                "action": it["action"],
                "existing_entry_id": it["entry_id"],
            }
            for it in todo
        ],
    }
    _write_json(PLAN_PATH, plan)
    print("[完成] 发布计划已生成：%s" % PLAN_PATH)
    print("       待发布 %d 篇，分 %d 个分组。" % (len(todo), len(plan["folder_tree"])))
    print("       请让 AI 助手读取该计划，逐项真实调用乐享 MCP 导入。")
    return 0


def cmd_record(cfg, state, result_path):
    """回写 AI 真实导入后的结果。结果 JSON 形如：
    {"target":{"space_id":"...","root_entry_id":"...","root_url":"..."},
     "folders":[{"key":"spec","entry_id":"...","url":"..."}],
     "items":[{"id":"金水谣_纲.md","entry_id":"...","url":"...","sha256":"..."}]}
    """
    data = _read_json(result_path, None)
    if data is None:
        print("[致命] 读不到结果文件：%s" % result_path)
        return 2

    state.setdefault("target", {}).update(data.get("target") or {})
    state.setdefault("folders", {})
    for fd in data.get("folders") or []:
        if fd.get("key"):
            state["folders"][fd["key"]] = {
                "entry_id": fd.get("entry_id", ""),
                "url": fd.get("url", ""),
                "name": fd.get("name", ""),
            }

    state.setdefault("items", {})
    n = 0
    for it in data.get("items") or []:
        key = it.get("id")
        if not key or not it.get("entry_id"):
            continue
        state["items"][key] = {
            "entry_id": it["entry_id"],
            "url": it.get("url", ""),
            "title": it.get("title", ""),
            "group": it.get("group", ""),
            "sha256": it.get("sha256", ""),
            "published_at": datetime.now().isoformat(timespec="seconds"),
        }
        n += 1

    state.setdefault("history", []).append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "count": n,
    })
    _write_json(STATE_PATH, state)
    print("[完成] 已回写 %d 条真实导入结果 -> %s" % (n, STATE_PATH))
    print("       下一步：--report 生成成果展示页。")
    return 0


# ---------------------------------------------------------------- 成果页

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0B1220;color:#E6EDF7;font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;line-height:1.7;padding:48px 24px}
.wrap{max-width:1080px;margin:0 auto}
.hd{border:1px solid #1E2D45;border-radius:16px;padding:32px;background:#111A2B;margin-bottom:28px}
.hd h1{font-size:26px;font-weight:600;color:#F2F6FC;display:flex;align-items:center;gap:12px}
.hd .sub{color:#8FA3BF;font-size:14px;margin-top:10px}
.hd a{color:#6AA8FF;text-decoration:none;border-bottom:1px dashed #2F4A6E}
.tag{display:inline-block;font-size:12px;padding:3px 10px;border-radius:999px;background:#16233A;color:#7FB2FF;border:1px solid #24385A;margin-right:8px}
h2{font-size:18px;font-weight:600;color:#F2F6FC;margin:36px 0 16px;display:flex;align-items:center;gap:10px}
.cmp{display:grid;grid-template-columns:1fr 56px 1fr;gap:0;align-items:stretch;margin-bottom:8px}
.pane{border:1px solid #1E2D45;border-radius:14px;padding:22px;background:#111A2B}
.pane.before{border-color:#3A2A38}
.pane.after{border-color:#22405F}
.pane h3{font-size:14px;color:#8FA3BF;font-weight:500;margin-bottom:14px;letter-spacing:1px}
.pane ul{list-style:none}
.pane li{font-size:13px;color:#C3D2E6;padding:7px 0 7px 18px;position:relative}
.pane li::before{content:"";position:absolute;left:0;top:15px;width:6px;height:6px;border-radius:50%;background:#3E5C86}
.arrow{display:flex;align-items:center;justify-content:center}
.card{border:1px solid #1E2D45;border-radius:12px;padding:18px 20px;background:#111A2B;margin-bottom:12px}
.card .t{font-size:15px;color:#F2F6FC;font-weight:500}
.card .m{font-size:12px;color:#7E8FA8;margin-top:8px;font-family:Consolas,monospace}
.card a{color:#6AA8FF;text-decoration:none;font-size:13px}
.card a:hover{text-decoration:underline}
.tree{border:1px solid #1E2D45;border-radius:14px;padding:26px 28px;background:#111A2B}
.node{position:relative;padding-left:26px}
.node .row{display:flex;align-items:center;gap:10px;padding:7px 0}
.node .row .nm{font-size:14px;color:#E6EDF7}
.node .row a{font-size:12px;color:#6AA8FF;text-decoration:none}
.node .row .eid{font-size:11px;color:#5E7086;font-family:Consolas,monospace}
.lv1>.row .nm{color:#A98BFF;font-weight:500}
.line{position:absolute;left:8px;top:0;bottom:0;width:1px;background:#24385A}
.ft{margin-top:36px;border:1px solid #1E2D45;border-radius:16px;padding:28px;background:#111A2B}
.ft p{color:#C3D2E6;font-size:14px;margin-bottom:10px}
.empty{border:1px dashed #3A4A66;border-radius:12px;padding:28px;text-align:center;color:#8FA3BF;font-size:14px;background:#0F1726}
.meta{color:#5E7086;font-size:12px;margin-top:22px;text-align:center}
"""

_ICON_DOC = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6AA8FF" stroke-width="1.6">'
             '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
             '<path d="M14 2v6h6M8 13h8M8 17h5"/></svg>')
_ICON_TREE = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#A98BFF" stroke-width="1.6">'
              '<rect x="3" y="3" width="7" height="5" rx="1"/><rect x="14" y="16" width="7" height="5" rx="1"/>'
              '<rect x="3" y="16" width="7" height="5" rx="1"/><path d="M6.5 8v8M17.5 16v-4H6.5"/></svg>')
_ICON_ARROW = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4A7FC1" stroke-width="1.8">'
               '<path d="M5 12h14M13 6l6 6-6 6"/></svg>')
_ICON_SPARK = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7FD6C0" stroke-width="1.6">'
               '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18"/></svg>')


def _esc(s):
    return html.escape(str(s or ""))


def cmd_report(cfg, state):
    tgt = resolve_target(cfg, state)
    items = state.get("items", {})
    folders = state.get("folders", {})
    gnames = {g["key"]: g["name"] for g in cfg.get("groups", [])}

    space_url = tgt.get("space_url") or ""
    space_label = tgt.get("root_folder_name") or "（未配置目标知识库）"
    head_link = ('<a href="%s" target="_blank">%s</a>' % (_esc(space_url), _esc(space_url))
                 if space_url else '<span style="color:#8FA3BF">链接待配置</span>')

    # 成果一：文档卡片
    gorder = group_order(cfg)
    if items:
        cards = []
        for path, it in sorted(items.items(),
                               key=lambda kv: gorder.get(kv[1].get("group", ""), 999)):
            link = ('<a href="%s" target="_blank">打开在线文档 -&gt;</a>' % _esc(it.get("url"))
                    if it.get("url") else '<span style="color:#7E8FA8">链接缺失</span>')
            cards.append(
                '<div class="card"><div class="t">%s</div>'
                '<div class="m">entry_id: %s &nbsp;|&nbsp; 源文件: %s</div>'
                '<div style="margin-top:10px">%s</div></div>'
                % (_esc(it.get("title") or path), _esc(it.get("entry_id")), _esc(path), link)
            )
        cards_html = "".join(cards)
    else:
        cards_html = ('<div class="empty">尚未执行真实导入，暂无在线文档。<br>'
                      '请先配置目标知识库并让 AI 助手完成导入，再重新生成本页。</div>')

    # 成果二：目录树
    if items:
        by_group = {}
        for path, it in items.items():
            by_group.setdefault(it.get("group", "misc"), []).append((path, it))
        blocks = []
        for gkey, lst in sorted(by_group.items(), key=lambda kv: gorder.get(kv[0], 999)):
            fd = folders.get(gkey, {})
            flink = ('<a href="%s" target="_blank">打开</a>' % _esc(fd.get("url"))) if fd.get("url") else ""
            children = []
            for path, it in lst:
                clink = ('<a href="%s" target="_blank">打开</a>' % _esc(it.get("url"))) if it.get("url") else ""
                children.append(
                    '<div class="node"><div class="line"></div><div class="row">'
                    '<span class="nm">%s</span><span class="eid">%s</span>%s</div></div>'
                    % (_esc(it.get("title") or path), _esc(it.get("entry_id")), clink)
                )
            blocks.append(
                '<div class="node lv1"><div class="line"></div><div class="row">'
                '<span class="nm">%s</span>%s</div>%s</div>'
                % (_esc(gnames.get(gkey, gkey)), flink, "".join(children))
            )
        tree_html = ('<div class="tree"><div class="node"><div class="row">'
                     '<span class="nm" style="color:#7FD6C0">%s</span></div>%s</div></div>'
                     % (_esc(space_label), "".join(blocks)))
    else:
        tree_html = '<div class="empty">目录树将在真实导入完成后自动生成。</div>'

    total = len(items)
    html_doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>乐享发布成果页 · 金水谣</title><style>%s</style></head><body><div class="wrap">

<div class="hd">
  <h1>%s 金水谣项目文档 · 乐享发布成果</h1>
  <div class="sub"><span class="tag">单向发布</span><span class="tag">本地为真源</span>
  <span class="tag">共 %d 篇</span></div>
  <div class="sub">目标知识库：%s</div>
</div>

<h2>%s 一键转化：导入前 &rarr; 导入后</h2>
<div class="cmp">
  <div class="pane before"><h3>导入前</h3><ul>
    <li>Markdown 散落在本地磁盘</li><li>要看必须开电脑、启 18888 服务</li>
    <li>换台机器就看不到</li><li>没法分享给别人</li><li>手机上完全打不开</li></ul></div>
  <div class="arrow">%s</div>
  <div class="pane after"><h3>导入后</h3><ul>
    <li>在线文档，排版层级表格全保留</li><li>浏览器直接打开，无需本地服务</li>
    <li>任意设备同一份内容</li><li>链接一发即可协作</li><li>手机随时查阅</li></ul></div>
</div>

<h2>%s 成果一：在线文档</h2>
%s

<h2>%s 成果二：拆解目录树</h2>
%s

<div class="ft">
  <h2 style="margin-top:0">%s 价值总结</h2>
  <p>1. <b>查阅成本归零</b> —— 项目规范从"要开电脑启服务"变成"手机点链接"。</p>
  <p>2. <b>协作门槛消失</b> —— 新人接手不再要口头交代，一条链接给到位。</p>
  <p>3. <b>真源不乱</b> —— 乐享只读镜像，本地仍是唯一真源，杜绝两份内容互相打架。</p>
  <p>4. <b>增量可持续</b> —— 内容指纹比对，改过的才推，没改的自动跳过。</p>
</div>

<div class="meta">生成时间 %s · 数据来自真实导入回执，无编造内容</div>
</div></body></html>""" % (
        _CSS, _ICON_DOC, total, head_link, _ICON_ARROW, _ICON_ARROW,
        _ICON_DOC, cards_html, _ICON_TREE, tree_html, _ICON_SPARK,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("[完成] 成果页已生成：%s" % REPORT_PATH)
    if not items:
        print("       当前为空态页（尚未真实导入），导入后重跑本命令即可填充。")
    return 0


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="乐享（云知）单向发布引擎")
    ap.add_argument("--plan", action="store_true", help="生成发布计划 JSON")
    ap.add_argument("--record", metavar="FILE", help="回写真实导入结果 JSON")
    ap.add_argument("--report", action="store_true", help="生成成果展示页 HTML")
    args = ap.parse_args()

    cfg = load_config()
    state = load_state()

    if args.record:
        return cmd_record(cfg, state, args.record)
    if args.plan:
        return cmd_plan(cfg, state)
    if args.report:
        return cmd_report(cfg, state)
    return cmd_dryrun(cfg, state)


if __name__ == "__main__":
    sys.exit(main())
