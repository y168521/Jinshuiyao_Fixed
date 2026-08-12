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
import tokenize

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_FUNC_LINES = 50
MAX_SQL_INJECT = 0
MAX_PLAINTEXT_SECRET = 0
MAX_UNTIMED_REQUESTS = 0
# Any 阈值：理论 0；但因历史代码可能大量使用，先以 WARN 提示，BLOCKING 翻硬时再卡 0。
MAX_ANY = 0

BLOCKING = False  # ← 基线清理干净后改为 True 即变硬拦截

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


def check_code_health(blocking=BLOCKING):
    """返回 (ok, msg, violated)。ok 仅在 blocking 且有违规时为 False。"""
    results = scan_project()
    if not results:
        return True, (
            "未检出超阈值代码异味（最大函数≤%d、Any=0、SQL注入=0、明文密钥=0、未超时requests=0）"
            % MAX_FUNC_LINES
        ), False
    worst_func = max(results, key=lambda r: r["max_func"])
    total_any = sum(r["any"] for r in results)
    total_sql = sum(r["sql"] for r in results)
    total_secret = sum(len(r["secrets"]) for r in results)
    total_untimed = sum(r["untimed"] for r in results)
    msg = (
        "检出 %d 个文件超阈值：最大函数 %s:%s=%d行(≤%d)；Any 共%d；SQL注入%d；明文密钥%d；未超时requests%d。"
        "代表文件: %s"
    ) % (
        len(results), worst_func["file"], worst_func["max_func_name"],
        worst_func["max_func"], MAX_FUNC_LINES, total_any, total_sql,
        total_secret, total_untimed,
        "; ".join(r["file"] for r in results[:8]),
    )
    violated = True
    ok = (not blocking) or False  # blocking 且有违规 → ok=False
    if blocking:
        ok = False
    return ok, msg, violated


if __name__ == "__main__":
    ok, msg, violated = check_code_health()
    tag = "FAIL" if not ok else ("WARN" if violated else "OK")
    print("[%s] 代码体检门禁: %s" % (tag, msg))
    if violated:
        print("  明细（前 15 个超阈值文件）:")
        for r in scan_project()[:15]:
            print("   - %s | 最大函数%d(%s) Any%d SQL%d 密钥%s 未超时%d" % (
                r["file"], r["max_func"], r["max_func_name"], r["any"], r["sql"],
                r["secrets"] or "-", r["untimed"]))
