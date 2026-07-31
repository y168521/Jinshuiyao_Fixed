# -*- coding: utf-8 -*-
"""金水谣知识库体检脚本（Lint 层）

对应 Karpathy「LLM Wiki」方法论里的 Lint 健康检查流程：定期给知识库做体检，
防止「幻觉复利」——测试垃圾 / 占位符 / 空卡片一旦进库，会变成长期错误资产。

纯标准库、零外部依赖，可被任意 Python 直接运行。

用法：
    python lint_knowledge.py                  # 体检默认目录（本文件所在文件夹）
    python lint_knowledge.py --dir 路径       # 体检指定目录
    python lint_knowledge.py --json           # 输出 JSON（便于程序读）
    python lint_knowledge.py --self-test      # 自我测试（在临时目录造污染，验证能抓到）

退出码：0 = 仅警告或无问题；1 = 发现错误（占位符/空正文/索引不一致等）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

__all__ = ["lint", "LintReport"]

# 本文件所在文件夹即「用户知识库」
KB_DIR = os.path.dirname(os.path.abspath(__file__))

# 占位符 / 幻觉标记（命中即判为错误）
PLACEHOLDER_TOKENS = [
    "DEEPSEEK_WAS_CALLED", "PLACEHOLDER", "[待补充]", "【待补充】",
    "TODO", "XXX", "FIXME", "<<<", ">>>",
]
# 不区分大小写匹配的短标记
CASE_INSENSITIVE = {"DEEPSEEK_WAS_CALLED", "PLACEHOLDER", "TODO", "XXX", "FIXME"}

# 不算知识卡片的元文件
META_FILES = {"README.md", "索引.md", "schema.md", "SCHEMA.md", "INDEX.json"}

CARD_RE = re.compile(r"^(概念页|实体页|摘要页)$")


class LintReport:
    """体检结果收集器。"""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warns: List[str] = []
        self.cards: int = 0
        self.raw_files: int = 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "cards": self.cards,
            "raw_files": self.raw_files,
            "errors": self.errors,
            "warnings": self.warns,
        }


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_card(text: str) -> Tuple[str, Dict[str, str], str]:
    """解析一张卡片：返回 (标题, frontmatter字典, 正文)。"""
    title = ""
    fm: Dict[str, str] = {}
    body = ""
    lines = text.splitlines()
    in_body = False
    body_lines: List[str] = []
    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if not in_body:
            m = re.match(r"^- (记录时间|记录者|来源|标签|类型|相关)：\s*(.*)$", line)
            if m:
                fm[m.group(1)] = m.group(2).strip()
                continue
            if line.strip() == "## 内容":
                in_body = True
                continue
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return title, fm, body


def _has_placeholder(text: str) -> Optional[str]:
    low = text.lower()
    for tok in CASE_INSENSITIVE:
        if tok.lower() in low:
            return tok
    for tok in PLACEHOLDER_TOKENS:
        if tok in text:
            return tok
    return None


def lint(kb_dir: str = KB_DIR) -> LintReport:
    """体检指定知识库目录，返回 LintReport。"""
    rep = LintReport()
    if not os.path.isdir(kb_dir):
        rep.error("目录不存在: " + kb_dir)
        return rep

    # 列出所有 .md（排除元文件与子目录）
    card_files: List[str] = []
    for fn in sorted(os.listdir(kb_dir)):
        fp = os.path.join(kb_dir, fn)
        if not os.path.isfile(fp):
            continue
        if not fn.endswith(".md"):
            continue
        if fn in META_FILES:
            continue
        card_files.append(fn)
    rep.cards = len(card_files)

    titles: List[str] = []
    # 第一遍：收集所有卡片的标题与解析结果（先不查互链，避免遍历顺序误报）
    parsed: List[Tuple[str, Dict[str, str], str, str]] = []
    for fn in card_files:
        fp = os.path.join(kb_dir, fn)
        try:
            text = _read(fp)
        except Exception as e:
            rep.error(f"[{fn}] 读取失败: {e}")
            continue
        title, fm, body = _parse_card(text)
        if title:
            titles.append(title)
        parsed.append((fn, title, fm, body, text))

    # 第二遍：逐卡体检（此时 titles 已完整，互链可正确解析）
    for fn, title, fm, body, text in parsed:
        # 占位符 / 幻觉标记
        ph = _has_placeholder(text)
        if ph:
            rep.error(f"[{fn}] 命中占位符/幻觉标记: {ph}（疑似测试污染，必须清理）")

        # 空正文
        if not body:
            rep.error(f"[{fn}] 正文为空（缺少有效『## 内容』）")

        # 缺关键 frontmatter
        if "记录时间" not in fm:
            rep.warn(f"[{fn}] 缺少『记录时间』")
        if "来源" not in fm or not fm.get("来源"):
            rep.warn(f"[{fn}] 缺少『来源』（建议写明真实出处，避免空泛）")

        # 类型字段（schema 要求，但不强制报错，逐步补齐）
        t = fm.get("类型", "")
        if t and not CARD_RE.match(t):
            rep.warn(f"[{fn}] 类型字段值『{t}』不在 概念页/实体页/摘要页 中")

        # 卡片间互链 [[标题]]
        for m in re.findall(r"\[\[([^\]]+)\]\]", text):
            if m not in titles and m != title:
                rep.warn(f"[{fn}] 互链 [[{m}]] 指向的卡片不存在")

        # 引用 raw 证据（截掉可能粘连的中文标点：。，；：、）」』等）
        for m in re.findall(r"raw/([^\s)\]（）]+)", text):
            m = m.strip().rstrip("。，；：、）」』”’")
            if not m:
                continue
            rawp = os.path.join(kb_dir, "raw", m)
            if not os.path.isfile(rawp):
                rep.warn(f"[{fn}] 引用的 raw 证据不存在: raw/{m}")

    # 索引一致性
    index_file = os.path.join(kb_dir, "INDEX.json")
    if os.path.isfile(index_file):
        try:
            idx = json.load(open(index_file, encoding="utf-8"))
        except Exception as e:
            rep.error(f"INDEX.json 解析失败: {e}")
            idx = []
        if isinstance(idx, list):
            idx_files = set()
            seen_titles = set()
            for e in idx:
                f = e.get("file", "")
                idx_files.add(f)
                t = e.get("title", "")
                if t in seen_titles:
                    rep.warn(f"索引存在重复标题: {t}")
                seen_titles.add(t)
                fp = os.path.join(kb_dir, f)
                if not os.path.isfile(fp):
                    rep.error(f"索引指向的文件不存在（孤儿索引）: {f}")
            # 卡片不在索引里
            for fn in card_files:
                if fn not in idx_files:
                    rep.warn(f"卡片 [{fn}] 不在 INDEX.json（建议运行 archive_knowledge.py --rebuild）")
    else:
        rep.warn("缺少 INDEX.json（建议运行 archive_knowledge.py --rebuild）")

    # raw 层体检
    raw_dir = os.path.join(kb_dir, "raw")
    if os.path.isdir(raw_dir):
        raw_files = [f for f in sorted(os.listdir(raw_dir))
                     if f.endswith(".md") and f != "README.md"]
        rep.raw_files = len(raw_files)
        for fn in raw_files:
            fp = os.path.join(raw_dir, fn)
            try:
                if not _read(fp).strip():
                    rep.error(f"[raw/{fn}] 为空（raw 证据不应空白）")
            except Exception as e:
                rep.error(f"[raw/{fn}] 读取失败: {e}")
    else:
        rep.warn("缺少 raw/ 目录（建议建立原始证据层）")

    # 元文件存在性
    for mf in ("README.md", "索引.md", "schema.md"):
        if not os.path.isfile(os.path.join(kb_dir, mf)):
            rep.warn(f"缺少元文件 {mf}")

    # 风险登记册校验（挂每月1号体检；不新建自动化，仅并入既有收集器）
    lint_risk_register(rep)

    return rep


def lint_risk_register(rep: "LintReport") -> None:
    """复用 scripts/verify_risk_register.py 的 verify()，把风险登记册的
    errors/warns 并入 LintReport。路径由上溯两级定位到 Jinshuiyao_Fixed 根的
    `金水谣数据/risk_register.json`。"""
    project_root = os.path.dirname(os.path.dirname(KB_DIR))  # .../Jinshuiyao_Fixed
    json_path = os.path.join(project_root, "金水谣数据", "risk_register.json")
    scripts_dir = os.path.join(project_root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from verify_risk_register import verify
    except Exception as e:  # pragma: no cover - 脚本缺失为环境异常
        rep.warn("风险登记册校验脚本不可用（scripts/verify_risk_register.py）: %s" % e)
        return
    ok, errors, warns = verify(json_path)
    for e in errors:
        rep.error("风险登记册: " + e)
    for w in warns:
        rep.warn("风险登记册: " + w)


def _print_report(rep: LintReport, kb_dir: str) -> None:
    print("=" * 56)
    print("金水谣知识库体检报告")
    print(f"目录: {kb_dir}")
    print(f"卡片数: {rep.cards} | raw 证据: {rep.raw_files}")
    print("-" * 56)
    if rep.errors:
        print(f"❌ 错误（{len(rep.errors)} 项，必须处理）:")
        for e in rep.errors:
            print("   - " + e)
    else:
        print("✅ 无错误")
    if rep.warns:
        print(f"⚠️ 警告（{len(rep.warns)} 项，建议处理）:")
        for w in rep.warns:
            print("   - " + w)
    else:
        print("✅ 无警告")
    print("-" * 56)
    print("结论:", "通过 ✅" if rep.ok else "未通过 ❌（有错误需清理）")
    print("=" * 56)


def _self_test() -> None:
    """在临时目录制造污染，验证 Lint 能抓到。"""
    tmp = tempfile.mkdtemp(prefix="jinshuiyao_lint_test_")
    print("→ 临时目录:", tmp)

    # 一张好卡
    good = os.path.join(tmp, "20260718_好卡.md")
    with open(good, "w", encoding="utf-8") as f:
        f.write("# 好卡\n- 记录时间：2026-07-18 10:00:00\n- 来源：测试\n"
                "- 类型：概念页\n\n## 内容\n这是正常内容。\n")
    # 一张污染卡（占位符）
    bad = os.path.join(tmp, "20260718_污染卡.md")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("# 污染卡\n- 记录时间：2026-07-18 10:00:00\n- 来源：测试\n\n"
                "## 内容\nDEEPSEEK_WAS_CALLED\n")
    # 一张空正文卡
    empty = os.path.join(tmp, "20260718_空卡.md")
    with open(empty, "w", encoding="utf-8") as f:
        f.write("# 空卡\n- 记录时间：2026-07-18 10:00:00\n- 来源：测试\n\n## 内容\n")
    # 孤儿索引
    with open(os.path.join(tmp, "INDEX.json"), "w", encoding="utf-8") as f:
        json.dump([
            {"title": "好卡", "file": "20260718_好卡.md", "source": "测试", "time": "x", "tags": []},
            {"title": "幽灵卡", "file": "不存在.md", "source": "测试", "time": "x", "tags": []},
        ], f, ensure_ascii=False)
    # raw 空证据
    rawd = os.path.join(tmp, "raw")
    os.makedirs(rawd, exist_ok=True)
    with open(os.path.join(rawd, "empty_evidence.md"), "w", encoding="utf-8") as f:
        f.write("")

    rep = lint(tmp)
    assert not rep.ok, "应当检测到错误"
    assert any("DEEPSEEK_WAS_CALLED" in e for e in rep.errors), "应抓到占位符"
    assert any("为空" in e for e in rep.errors), "应抓到空正文"
    assert any("孤儿索引" in e for e in rep.errors), "应抓到孤儿索引"
    assert any("raw/" in e and "为空" in e for e in rep.errors), "应抓到空 raw"
    print("✓ 自测通过：占位符 / 空正文 / 孤儿索引 / 空 raw 均被正确识别")

    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass


def _main() -> int:
    ap = argparse.ArgumentParser(description="金水谣知识库体检（Lint）")
    ap.add_argument("--dir", default=KB_DIR, help="知识库目录（默认本文件所在文件夹）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--self-test", action="store_true", help="运行自我测试")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return 0

    rep = lint(args.dir)
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_report(rep, args.dir)
    return 0 if rep.ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(_main())
