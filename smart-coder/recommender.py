# -*- coding: utf-8 -*-
"""金水谣 · 智能推荐引擎（纯标准库，零外部依赖）
============================================
对应需求 4「智能推荐与提示」：根据已加载文件内容，主动向用户推荐：
  1) 常见问题预设（preset_questions）—— 新手常问的方向；
  2) 代码风格检测（style_issues）—— 可读性/规范问题；
  3) 潜在问题预警（warnings）—— 隐患（硬编码路径、密钥、危险函数等）；
  4) 性能优化建议（perf）—— 轻量启发式。
内容随加载结果动态生成（不同项目给出不同推荐）。
"""
import os
import re

_PY_ONLY = True  # 风格/预警/性能主要针对代码文件


def _read_lines(root, rel, max_lines=2500):
    ab = os.path.join(root, rel)
    try:
        with open(ab, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()[:max_lines]
    except Exception:
        return []


def _preset_questions(files):
    """基于检测到的文件类型，给出新手常见提问方向。"""
    cats = {f["category"] for f in files}
    has_entry = any(f["category"] == "entry" for f in files)
    has_config = any(f["category"] == "config" for f in files)
    has_test = any(f["category"] == "test" for f in files)
    has_doc = any(f["category"] == "doc" for f in files)
    qs = []
    if has_entry:
        qs.append({"q": "这个项目从哪里启动？入口文件怎么运行？",
                   "why": "你加载的项目有入口文件，先弄清启动方式最稳妥。"})
    if has_config:
        qs.append({"q": "配置文件里的各项参数分别是什么意思？能改吗？",
                   "why": "配置常含关键开关/密钥，理解它再改动更安全。"})
    if has_test:
        qs.append({"q": "怎么运行测试？测试覆盖了哪些功能？",
                   "why": "有测试说明项目重视正确性，先学会跑测试。"})
    if has_doc:
        qs.append({"q": "有没有给新手看的使用说明？第一步该做什么？",
                   "why": "文档是最快的上手途径。"})
    qs.append({"q": "这段代码（或这个文件）到底是做什么的？",
               "why": "先用大白话搞懂用途，再谈修改。"})
    qs.append({"q": "如果我想加一个新功能，应该改哪个文件？",
               "why": "帮你定位改动落点，避免到处乱改。"})
    qs.append({"q": "项目里有没有重复代码可以合并？",
               "why": "发现重复能减少维护负担。"})
    return qs


def _scan_code_issues(root, files):
    style_issues = []
    warnings = []
    perf = []
    for f in files:
        if f["ext"] != ".py":
            continue
        lines = _read_lines(root, f["rel"])
        if not lines:
            continue
        rel = f["rel"]
        joined = "\n".join(lines)
        has_tab = any("\t" in ln for ln in lines)
        has_space_indent = any(ln.startswith("    ") for ln in lines)
        if has_tab and has_space_indent:
            warnings.append({"file": rel, "line": 0, "level": "中",
                             "issue": "缩进混用（Tab 与空格）",
                             "detail": "同一文件里既用 Tab 又用空格，容易在某些环境报错；建议统一为 4 个空格。"})
        # 逐行模式
        def_areas = []  # (start_line, indent)
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            # 风格：裸 except
            if re.search(r"except\s*:", s):
                style_issues.append({"file": rel, "line": i,
                                     "issue": "裸 except（未指定异常类型）",
                                     "detail": "except: 会吞掉所有错误包括 Ctrl+C，建议写成 except Exception as e:。"})
            # 风格：TODO/FIXME
            if re.search(r"#.*\b(TODO|FIXME|XXX|HACK)\b", s):
                style_issues.append({"file": rel, "line": i,
                                     "issue": "留有 TODO/FIXME 待办",
                                     "detail": "代码里标记了待办事项，可能功能尚未完成。"})
            # 风格：print 调试
            if re.search(r"print\s*\(", s) and "print(" in s:
                style_issues.append({"file": rel, "line": i,
                                     "issue": "使用 print 输出（疑似调试残留）",
                                     "detail": "大量 print 多为调试用，正式代码建议改用日志模块 logging。"})
            # 预警：硬编码绝对路径
            if re.search(r"[A-Za-z]:\\\\|/Users/|/home/|C:\\\\", s):
                warnings.append({"file": rel, "line": i, "level": "高",
                                 "issue": "硬编码绝对路径",
                                 "detail": "写死了本机路径，换电脑/换人就会找不到文件；建议用相对路径或配置项。"})
            # 预警：疑似密钥/密码
            if re.search(r"(api[_-]?key|password|passwd|secret|token)\s*=\s*['\"]", s, re.I):
                warnings.append({"file": rel, "line": i, "level": "高",
                                 "issue": "代码里疑似写了密钥/密码",
                                 "detail": "明文密钥有泄露风险，建议放到配置文件并用环境变量，切勿提交到公开仓库。"})
            # 预警：危险函数
            if re.search(r"\beval\s*\(|\bexec\s*\(", s):
                warnings.append({"file": rel, "line": i, "level": "高",
                                 "issue": "使用了 eval/exec",
                                 "detail": "eval/exec 会执行任意字符串，存在严重安全隐患；除非必要否则不要用。"})
            if re.search(r"os\.system\s*\(|shell\s*=\s*True", s):
                warnings.append({"file": rel, "line": i, "level": "中",
                                 "issue": "调用系统命令（os.system / shell=True）",
                                 "detail": "直接执行系统命令有注入风险；建议用参数列表形式调用 subprocess。"})
            # 预警：import *
            if re.search(r"import\s+\*\s*$", s):
                warnings.append({"file": rel, "line": i, "level": "低",
                                 "issue": "使用了 import *",
                                 "detail": "会引入大量不明名称，不利于阅读和维护。"})
            # 性能：循环里 append
            if re.search(r"\.append\s*\(", s) and re.search(r"for\s+.*in\s+", lines[i-2] if i >= 2 else ""):
                perf.append({"file": rel, "line": i,
                             "issue": "循环里用 append 累积列表",
                             "detail": "可考虑用列表推导式 [f(x) for x in ...] 更简洁也更高效。"})
            # 记录函数定义区域（用于长函数检测）
            m = re.match(r"^(\s*)def\s+\w+", ln)
            if m:
                def_areas.append((i, len(m.group(1))))
        # 长函数检测
        for j in range(len(def_areas)):
            start, ind = def_areas[j]
            end = def_areas[j + 1][0] if j + 1 < len(def_areas) else len(lines) + 1
            length = end - start
            if length > 80:
                style_issues.append({"file": rel, "line": start,
                                     "issue": f"函数过长（约 {length} 行）",
                                     "detail": "单个函数太长难维护，建议拆成更小的函数。"})
    return style_issues, warnings, perf


def recommend(root, files, tree=None):
    """生成四维推荐。files 为 scan_directory 返回的文件清单。"""
    preset = _preset_questions(files)
    style_issues, warnings, perf = _scan_code_issues(root, files)
    # 控制数量，避免刷屏
    return {
        "preset_questions": preset[:8],
        "style_issues": style_issues[:30],
        "warnings": warnings[:30],
        "perf": perf[:20],
        "summary": {
            "预设问题": len(preset),
            "风格问题": len(style_issues),
            "隐患预警": len(warnings),
            "性能建议": len(perf),
        },
    }


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test():
    import tempfile
    import shutil
    print("== recommender 自测 ==")
    tmp = tempfile.mkdtemp(prefix="rec_test_")
    try:
        code = (
            "import os\n"
            "API_KEY = 'sk-123'\n"          # 密钥预警
            "def long_func():\n"             # 长函数+裸except
            + "    x = 1\n" * 90
            + "    try:\n        y = 1\n    except:\n        pass\n"
            "def f():\n    for i in range(3):\n        a.append(i)\n"  # append in loop
        )
        open(os.path.join(tmp, "main.py"), "w", encoding="utf-8").write(code)
        open(os.path.join(tmp, "config.json"), "w", encoding="utf-8").write('{}')
        files = [
            {"rel": "main.py", "name": "main.py", "ext": ".py", "category": "entry", "importance": "high"},
            {"rel": "config.json", "name": "config.json", "ext": ".json", "category": "config", "importance": "high"},
        ]
        r = recommend(tmp, files)
        assert any("API_KEY" in w["detail"] or "密钥" in w["issue"] for w in r["warnings"]), r["warnings"]
        assert any("长" in s["issue"] for s in r["style_issues"]), r["style_issues"]
        assert any("列表推导" in p["detail"] or "append" in p["issue"] for p in r["perf"]), r["perf"]
        assert r["preset_questions"], "无预设问题"
        print("✓ 推荐：命中密钥预警、长函数、append 性能建议，并给出预设问题")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("recommender 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
