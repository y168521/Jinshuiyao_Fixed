# -*- coding: utf-8 -*-
"""core/ 拆包脚本：将 59 个模块按职责拆分为 core/ai/、core/dispatch/、core/infra/。

执行步骤：
1. 创建子包目录及 __init__.py
2. 移动文件
3. 全仓库正则替换 import 路径（core.X → core.<sub>.X）
4. 修正 core/__init__.py 内部相对导入
"""
import os
import re
import shutil

BASE = r"c:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
CORE = os.path.join(BASE, "core")

# 模块 → 子包 映射
AI_MODULES = [
    "ai_agent", "ai_service", "ai_decisions_extractor", "adaptive_models",
    "model_router", "model_shadow", "free_model_pool", "llm_budget",
    "agent_orchestrator", "agent_vector_memory", "agent_formatters",
    "agent_knowledge_archiver", "agent_project_memory", "agent_reminder",
    "agent_system_diagnostics", "agent_theme", "agent_video_handler",
    "agent_web_search", "intent_rules", "content_refiner",
    "cross_domain", "conversation_log",
]
DISPATCH_MODULES = [
    "dispatch_lottery", "dispatch_fund", "dispatch_stock", "dispatch_football",
    "dispatch_music", "dispatch_creator", "dispatch_video",
    "dispatch_knowledge", "dispatch_system",
]
INFRA_MODULES = [
    "security", "context", "registry", "gui_registry", "tk_style", "theme",
    "theme_manager", "audit_log", "telemetry", "file_watcher", "file_organizer",
    "data_maintenance", "data_truth_guard", "drift_detector", "memory_decay",
    "exp_box_extractor", "auto_knowledge", "automation_mirror",
    "circuit_breaker", "concurrency_gate", "pipeline_state", "pipeline_mode",
    "scheduler", "scheduler_tasks", "video_extractor", "video_to_kb",
    "knowledge_gateway", "knowledge_stats",
]

MODULE_TO_SUB = {}
for m in AI_MODULES:
    MODULE_TO_SUB[m] = "ai"
for m in DISPATCH_MODULES:
    MODULE_TO_SUB[m] = "dispatch"
for m in INFRA_MODULES:
    MODULE_TO_SUB[m] = "infra"

assert len(MODULE_TO_SUB) == 59, f"模块数应为 59，实际 {len(MODULE_TO_SUB)}"

# 1. 创建子包
for sub in ("ai", "dispatch", "infra"):
    sub_dir = os.path.join(CORE, sub)
    os.makedirs(sub_dir, exist_ok=True)
    init_path = os.path.join(sub_dir, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(f'# -*- coding: utf-8 -*-\n"""core.{sub} 子包"""\n')
print("[1/4] 子包目录已创建")

# 2. 移动文件
moved = 0
for module, sub in MODULE_TO_SUB.items():
    src = os.path.join(CORE, f"{module}.py")
    dst = os.path.join(CORE, sub, f"{module}.py")
    if os.path.isfile(src):
        shutil.move(src, dst)
        moved += 1
print(f"[2/4] 已移动 {moved} 个文件")

# 3. 全仓库替换 import 路径
# 构建正则：core.MODULE 后跟非单词字符（避免 core.infra.theme 匹配 core.infra.theme_manager）
# 按模块名长度倒序，确保长名先匹配（如 theme_manager 先于 theme）
sorted_modules = sorted(MODULE_TO_SUB.keys(), key=len, reverse=True)
pattern = re.compile(
    r"core\.(" + "|".join(re.escape(m) for m in sorted_modules) + r")(?![A-Za-z0-9_])"
)

py_files = []
for root, dirs, files in os.walk(BASE):
    # 跳过 venv / 缓存 / .git
    dirs[:] = [d for d in dirs if d not in (
        "venv", ".venv", "__pycache__", ".git", "node_modules", ".pytest_cache"
    )]
    for fn in files:
        if fn.endswith(".py"):
            py_files.append(os.path.join(root, fn))

replaced_files = 0
total_replacements = 0
for fp in py_files:
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, OSError):
        continue
    new_content, n = pattern.subn(
        lambda m: f"core.{MODULE_TO_SUB[m.group(1)]}.{m.group(1)}",
        content,
    )
    if n > 0:
        with open(fp, "w", encoding="utf-8") as f:
            f.write(new_content)
        replaced_files += 1
        total_replacements += n
print(f"[3/4] 已替换 {replaced_files} 个文件中的 {total_replacements} 处 import")

# 4. 修正 core/__init__.py 的相对导入（.ai_service → .ai.ai_service 等）
core_init = os.path.join(CORE, "__init__.py")
with open(core_init, "r", encoding="utf-8") as f:
    init_content = f.read()
for module, sub in MODULE_TO_SUB.items():
    init_content = init_content.replace(f"from .{module} ", f"from .{sub}.{module} ")
    init_content = init_content.replace(f"from .{module}\n", f"from .{sub}.{module}\n")
    init_content = init_content.replace(f"from .{module},", f"from .{sub}.{module},")
    init_content = init_content.replace(f"    from .{module} ", f"    from .{sub}.{module} ")
with open(core_init, "w", encoding="utf-8") as f:
    f.write(init_content)
print("[4/4] core/__init__.py 相对导入已修正")

print("\n✅ core/ 拆包完成")
print(f"   ai/      : {len(AI_MODULES)} 个模块")
print(f"   dispatch/: {len(DISPATCH_MODULES)} 个模块")
print(f"   infra/   : {len(INFRA_MODULES)} 个模块")
