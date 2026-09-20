#!/usr/bin/env python3
"""金水谣 · 代码体检门禁 (code health gate)

复用 agent_refactor_demo 的「四 Agent 重构管线」方法论，针对 Python 代码库做量化体检：
  - 最大函数/方法体行数        → 阈值 ≤ MAX_FUNC_LINES (默认 50)
  - 类型不安全 Any 使用数       → 阈值 0
  - SQL 注入风险点(f-string/%-拼 SQL) → 阈值 0
  - 明文密钥(写死密码/key/token) → 阈值 0
  - 未带 timeout 的 requests 调用 → 阈值 0 (参考指标)

扫描 Jinshuiyao_Fixed 下 .py（排除 node_modules/.git/.workbuddy/venv/log/backups 等）。
统计前先用 tokenize 剥离注释与字符串字面量，避免注释/文档里的字面量误判
（这是 measure.py 的真实教训：第一版把注释里的 "(req: any, res: any)" 算成了真 any）。

门禁默认 WARN-ONLY（BLOCKING=False）：现有代码库体量未清，直接硬拦会阻断收工。
待基线清理干净后，把 BLOCKING 改为 True 即变硬拦截。
"""
import io
import os
import re
import sys
import json
import tokenize
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_FUNC_LINES = 50
MAX_SQL_INJECT = 0
MAX_PLAINTEXT_SECRET = 0
MAX_UNTIMED_REQUESTS = 0
# Any 阈值：理论 0；但因历史代码可能大量使用，先以 WARN 提示，BLOCKING 翻硬时再卡 0。
MAX_ANY = 0

BLOCKING = False  # ← 基线清理干净后改为 True 即变硬拦截

# ---------------------------------------------------------------------------
# 基线快照（JS-20260920-18）
# 背景：本门禁长期挂着「248 个文件超阈值」的 WARN，谁都知道、谁都不看——
# 这就是典型的假红噪音：它报的是**存量历史包袱**，不是"今天又变坏了"。
# 解决办法是锁一份基线：只告警"新增的超阈值文件"与"比基线更差的指标"，
# 存量按年收敛。基线文件随仓库走，任何人不经 --snapshot 不得改动。
# ---------------------------------------------------------------------------
BASELINE_PATH = os.path.join(BASE_DIR, "金水谣数据", "log", "code_health_baseline.json")
BASELINE_ENABLED = True
# 参与基线的指标（与 scan_project 输出的键一致）；secrets 记条数而非明细
METRIC_KEYS = ("max_func", "any", "sql", "untimed", "secret_n")

SKIP_DIRS = {
    "node_modules", ".git", ".workbuddy", "venv", ".venv", "__pycache__",
    "backups", "_old_backups", "dist", "build", ".pytest_cache", "migrations",
}
SKIP_PATH_FRAGMENTS = (
    "/log/", "/backups/", "/.workbuddy/", "/.git/", "/node_modules/",
    "/venv/", "/mirofish_db/", "/__pycache__/",
)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _strip_comments_strings(src):
    """用 tokenize 剥离注释和字符串字面量，保留代码结构用于类型/SQL 统计。"""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except Exception:
        return src  # 解析失败退回原文（仍可用，只是可能含字符串噪声）
    return "\n".join(out)


def max_function_lines(src):
    """返回 (最大函数体行数, 函数名)。统计 def/class 到缩进回退之间的代码行。"""
    lines = src.splitlines()
    n = len(lines)
    best = 0
    best_name = ""
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.lstrip()
        if re.match(r"^(async\s+def|def|class)\s+", stripped):
            indent = len(line) - len(stripped)
            name_m = re.match(r"^(?:async\s+def|def|class)\s+(\w+)", stripped)
            name = name_m.group(1) if name_m else "?"
            j = i + 1
            body = 0
            while j < n:
                l2 = lines[j]
                if l2.strip() == "":
                    j += 1
                    continue
                ind2 = len(l2) - len(l2.lstrip())
                if ind2 <= indent:
                    break
                body += 1
                j += 1
            if body > best:
                best = body
                best_name = name
            i = j
        else:
            i += 1
    return best, best_name


def count_any(code_only):
    # 只统计作为类型使用的 Any：: Any  -> Any  [Any]  (Any  , Any
    return len(re.findall(r"(?::\s*|->\s*|\[\s*|,\s*|\(\s*|\b)Any\b", code_only))


def count_sql_injection(code_only):
    # f-string / % 拼 SQL 的风险写法
    pat = re.compile(
        r'f["\'][^"\']*\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b'
        r'|["\'][^"\']*\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b[^"\']*%\s*['
        r'|["\'][^"\']*\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b[^"\']*\.format\('
    )
    return len(pat.findall(code_only))


def count_plaintext_secret(src):
    # 明文写死密钥：KEY/SECRET/PASS/PASSWORD/TOKEN = "非空串"，且非 os.environ/getenv/占位符
    hits = []
    for m in re.finditer(
        r"(\w*(?:KEY|SECRET|PASS|PASSWORD|TOKEN)\w*)\s*=\s*[\"']([^\"']{4,})[\"']",
        src,
    ):
        rhs = m.group(2)
        line = m.group(0)
        if "os.environ" in line or "getenv" in line or "get(" in line:
            continue
        if rhs.startswith("{") or rhs.startswith("<") or rhs.endswith(">") or "*" in rhs:
            continue
        if re.search(r"(your[-_ ]?|placeholder|xxx|todo|example|xxxx)", rhs, re.I):
            continue
        hits.append((m.group(1), rhs))
    return hits


def count_untimed_requests(code_only):
    # requests.get/post/... 调用且语句内无 timeout=
    calls = list(re.finditer(r"requests\.(get|post|put|delete|patch|head|options)\s*\(", code_only))
    bad = 0
    for c in calls:
        depth = 0
        k = c.end() - 1
        seg = ""
        while k < len(code_only):
            ch = code_only[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            seg += ch
            k += 1
        if "timeout" not in seg:
            bad += 1
    return bad


def scan_project():
    results = []
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_root = root.replace(os.sep, "/")
        if any(s in rel_root for s in SKIP_PATH_FRAGMENTS):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(root, fn).replace(os.sep, "/")
            if any(s in fp for s in SKIP_PATH_FRAGMENTS):
                continue
            src = _read(fp)
            if not src:
                continue
            code_only = _strip_comments_strings(src)
            mf, mname = max_function_lines(src)
            any_n = count_any(code_only)
            sql_n = count_sql_injection(code_only)
            secrets = count_plaintext_secret(src)
            untimed = count_untimed_requests(code_only)
            if (mf > MAX_FUNC_LINES or any_n > MAX_ANY or sql_n > MAX_SQL_INJECT
                    or len(secrets) > MAX_PLAINTEXT_SECRET or untimed > MAX_UNTIMED_REQUESTS):
                results.append({
                    "file": fp[len(BASE_DIR) + 1:],
                    "max_func": mf, "max_func_name": mname,
                    "any": any_n, "sql": sql_n,
                    "secrets": [s[0] for s in secrets],
                    "untimed": untimed,
                })
    return results


def _metrics_of(r):
    """把一条扫描结果压成可比较的数值字典"""
    return {
        "max_func": int(r["max_func"]),
        "any": int(r["any"]),
        "sql": int(r["sql"]),
        "untimed": int(r["untimed"]),
        "secret_n": int(len(r["secrets"])),
    }


def _load_baseline():
    """读基线。文件不存在/损坏一律返回 None（由调用方退化为全量模式并说明原因），
    绝不静默吞掉——基线读不出来必须让人知道门禁此刻是"没牙"的。"""
    if not os.path.isfile(BASELINE_PATH):
        return None
    try:
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        files = data.get("files")
        if not isinstance(files, dict):
            return None
        return data
    except Exception as e:
        print("  [基线] 读取失败(%s: %s)，本次退化为全量模式" % (type(e).__name__, e))
        return None


def _save_baseline(results):
    """写基线快照（原子写：先写 tmp 再替换）"""
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    payload = {
        "generated": date.today().isoformat(),
        "note": "代码体检基线快照。存量=基线内已存在且未恶化的项（挂账，不告警）；"
                "只有「新增的超阈值文件」与「比基线更差的指标」才算违规。"
                "重新生成：python tools/code_health_gate.py --snapshot（须人工确认后再执行）",
        "thresholds": {
            "MAX_FUNC_LINES": MAX_FUNC_LINES, "MAX_ANY": MAX_ANY,
            "MAX_SQL_INJECT": MAX_SQL_INJECT, "MAX_PLAINTEXT_SECRET": MAX_PLAINTEXT_SECRET,
            "MAX_UNTIMED_REQUESTS": MAX_UNTIMED_REQUESTS,
        },
        "file_count": len(results),
        "files": {r["file"]: _metrics_of(r) for r in results},
    }
    tmp = BASELINE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    if os.path.exists(BASELINE_PATH):
        os.remove(BASELINE_PATH)
    os.rename(tmp, BASELINE_PATH)
    return payload


def _diff_against_baseline(results, baseline):
    """返回 (new_files, worsened, fixed, unchanged)
    new_files: 基线里没有的超阈值文件（今天新增的坏味道）
    worsened : 基线里有、但某项指标比基线更差 (文件, 指标, 旧值, 新值)
    fixed    : 基线里有、但现在已经不超阈值了（修好了，下次 --snapshot 会被移出基线）
    unchanged: 存量挂账（已存在且未恶化）
    """
    base_files = baseline.get("files", {})
    new_files, worsened, fixed, unchanged = [], [], [], []
    for r in results:
        key = r["file"]
        cur = _metrics_of(r)
        if key not in base_files:
            new_files.append(r)
            continue
        old = base_files[key]
        worse = []
        for k in METRIC_KEYS:
            ov = int(old.get(k, 0))
            cv = int(cur.get(k, 0))
            if cv > ov:
                worse.append((k, ov, cv))
        if worse:
            worsened.append((r, worse))
        else:
            unchanged.append(r)
    return new_files, worsened, fixed, unchanged


def _verdict_baseline(results, baseline, blocking):
    """基线模式下的判定：只认「新增」与「恶化」，存量挂账不算违规。"""
    new_f, worse, _fixed, unchanged = _diff_against_baseline(results, baseline)
    total = len(results)
    gen = baseline.get("generated", "?")
    if not new_f and not worse:
        msg = ("未检出新增/恶化的代码异味（存量挂账 %d 个文件已锁基线 %s"
               "；最大函数≤%d、Any=0、SQL注入=0、明文密钥=0、未超时requests=0）"
               % (total, gen, MAX_FUNC_LINES))
        return True, msg, False
    parts = []
    if new_f:
        parts.append("新增超阈值 %d 个: %s" % (
            len(new_f), "; ".join(r["file"] for r in new_f[:5])))
    if worse:
        sample = "; ".join("%s(%s %d→%d)" % (
            r["file"], d[0][0], d[0][1], d[0][2]) for r, d in worse[:5])
        parts.append("较基线恶化 %d 个: %s" % (len(worse), sample))
    msg = ("检出 %d 个超阈值文件，其中**需要处理的**：%s。存量挂账 %d 个（基线 %s，按年收敛）。"
           % (total, "；".join(parts), len(unchanged), gen))
    return (not blocking), msg, True


def _verdict_full(results, blocking, note=""):
    """全量模式（无基线/--full）：沿用原有口径。"""
    worst_func = max(results, key=lambda r: r["max_func"])
    msg = (
        "检出 %d 个文件超阈值%s：最大函数 %s:%s=%d行(≤%d)；Any 共%d；SQL注入%d；明文密钥%d；未超时requests%d。"
        "代表文件: %s"
    ) % (
        len(results), note,
        worst_func["file"], worst_func["max_func_name"],
        worst_func["max_func"], MAX_FUNC_LINES,
        sum(r["any"] for r in results), sum(r["sql"] for r in results),
        sum(len(r["secrets"]) for r in results), sum(r["untimed"] for r in results),
        "; ".join(r["file"] for r in results[:8]),
    )
    return (not blocking), msg, True


def check_code_health(blocking=BLOCKING, use_baseline=BASELINE_ENABLED):
    """返回 (ok, msg, violated)。ok 仅在 blocking 且有违规时为 False。

    use_baseline=True（默认）时：
      - violated 只由「新增超阈值文件」与「比基线恶化的指标」决定；
      - 存量挂账照常报数，但**不算违规**——否则这条 WARN 永远红着，等于没装。
    基线缺失/损坏时退化为全量模式，并在 msg 里明确写出（不许假装基线存在）。
    """
    results = scan_project()
    if not results:
        return True, (
            "未检出超阈值代码异味（最大函数≤%d、Any=0、SQL注入=0、明文密钥=0、未超时requests=0）"
            % MAX_FUNC_LINES
        ), False
    if use_baseline:
        bl = _load_baseline()
        if bl is not None:
            return _verdict_baseline(results, bl, blocking)
        # 基线缺失/损坏：退化为全量，但必须说清楚（不许假装基线存在而悄悄放宽）
        return _verdict_full(results, blocking,
                             "（⚠️ 基线快照缺失或不可读，本次按**全量**判定）")
    return _verdict_full(results, blocking)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--snapshot" in args:
        # 人工确认后再执行：它会把"今天的坏味道"合法化为基线
        res = scan_project()
        payload = _save_baseline(res)
        print("[基线] 已写入 %s" % BASELINE_PATH)
        print("       生成日期=%s 文件数=%d" % (payload["generated"], payload["file_count"]))
        print("       ⚠️ 该操作会把当前全部超阈值项记为「存量挂账」，之后只告警新增/恶化。")
        sys.exit(0)

    use_bl = "--full" not in args
    ok, msg, violated = check_code_health(use_baseline=use_bl)
    tag = "FAIL" if not ok else ("WARN" if violated else "OK")
    print("[%s] 代码体检门禁: %s" % (tag, msg))
    if violated:
        print("  明细（前 15 个超阈值文件）:")
        for r in scan_project()[:15]:
            print("   - %s | 最大函数%d(%s) Any%d SQL%d 密钥%s 未超时%d" % (
                r["file"], r["max_func"], r["max_func_name"], r["any"], r["sql"],
                r["secrets"] or "-", r["untimed"]))
    if not use_bl:
        print("  （本次为全量模式：--full，未与基线比较）")
