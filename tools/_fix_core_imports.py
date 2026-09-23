# -*- coding: utf-8 -*-
"""修正 from core import <module> → from core.<sub> import <module>"""
import os
import re

BASE = r"c:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"

M2S = {
    'ai_agent': 'ai', 'ai_service': 'ai', 'ai_decisions_extractor': 'ai', 'adaptive_models': 'ai',
    'model_router': 'ai', 'model_shadow': 'ai', 'free_model_pool': 'ai', 'llm_budget': 'ai',
    'agent_orchestrator': 'ai', 'agent_vector_memory': 'ai', 'agent_formatters': 'ai',
    'agent_knowledge_archiver': 'ai', 'agent_project_memory': 'ai', 'agent_reminder': 'ai',
    'agent_system_diagnostics': 'ai', 'agent_theme': 'ai', 'agent_video_handler': 'ai',
    'agent_web_search': 'ai', 'intent_rules': 'ai', 'content_refiner': 'ai', 'cross_domain': 'ai',
    'conversation_log': 'ai',
    'dispatch_lottery': 'dispatch', 'dispatch_fund': 'dispatch', 'dispatch_stock': 'dispatch',
    'dispatch_football': 'dispatch', 'dispatch_music': 'dispatch', 'dispatch_creator': 'dispatch',
    'dispatch_video': 'dispatch', 'dispatch_knowledge': 'dispatch', 'dispatch_system': 'dispatch',
    'security': 'infra', 'context': 'infra', 'registry': 'infra', 'gui_registry': 'infra',
    'tk_style': 'infra', 'theme': 'infra', 'theme_manager': 'infra', 'audit_log': 'infra',
    'telemetry': 'infra', 'file_watcher': 'infra', 'file_organizer': 'infra',
    'data_maintenance': 'infra', 'data_truth_guard': 'infra', 'drift_detector': 'infra',
    'memory_decay': 'infra', 'exp_box_extractor': 'infra', 'auto_knowledge': 'infra',
    'automation_mirror': 'infra', 'circuit_breaker': 'infra', 'concurrency_gate': 'infra',
    'pipeline_state': 'infra', 'pipeline_mode': 'infra', 'scheduler': 'infra',
    'scheduler_tasks': 'infra', 'video_extractor': 'infra', 'video_to_kb': 'infra',
    'knowledge_gateway': 'infra', 'knowledge_stats': 'infra',
}

sorted_m = sorted(M2S.keys(), key=len, reverse=True)
pat = re.compile(r'from core import (' + '|'.join(re.escape(m) for m in sorted_m) + r')(\s+as\s+\w+)?')

files = []
for r, d, fs in os.walk(BASE):
    d[:] = [x for x in d if x not in ('venv', '.venv', '__pycache__', '.git', 'node_modules', '.pytest_cache')]
    for f in fs:
        if f.endswith('.py'):
            files.append(os.path.join(r, f))

cnt = 0
for fp in files:
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            c = f.read()
    except Exception:
        continue
    nc, n = pat.subn(
        lambda m: f"from core.{M2S[m.group(1)]} import {m.group(1)}{m.group(2) or ''}",
        c,
    )
    if n:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(nc)
        cnt += n

print(f"已修正 {cnt} 处 from core import <module>")
