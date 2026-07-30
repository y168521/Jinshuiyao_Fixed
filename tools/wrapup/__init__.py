# -*- coding: utf-8 -*-
"""金水谣收工自检包 — 从子模块 re-export 所有检查函数。"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.checks_workflow import *  # noqa: F403,F401
from tools.wrapup.checks_infra import *  # noqa: F403,F401
from tools.wrapup.checks_code import *  # noqa: F403,F401
from tools.wrapup.checks_quality import *  # noqa: F403,F401
from tools.wrapup.checks_integrity import *  # noqa: F403,F401
from tools.wrapup.checks_security import *  # noqa: F403,F401
from tools.wrapup.checks_linkage import *  # noqa: F403,F401

# 显式 re-export 公共检查函数
__all__ = [
    "check_ai_decision_coverage",
    "check_change_linkage",
    "check_change_volume",
    "check_config_consistency",
    "check_css_var_override",
    "check_experience",
    "check_experience_field_completeness",
    "check_experience_quality",
    "check_experience_tag_count",
    "check_file_integrity",
    "check_file_map",
    "check_gui_variable_scope",
    "check_handoff",
    "check_history_field_sampling",
    "check_html_security",
    "check_knowledge_reuse",
    "check_mindmap_ids",
    "check_page_routes",
    "check_reference_integrity",
    "check_rejected_solutions_quality",
    "check_scheduler_sync",
    "check_script_integrity",
    "check_secrets_leak",
    "check_skip_frequency",
    "check_source_code_verification",
    "check_tag_index_consistency",
    "check_tests",
    "check_time_anomaly",
    "check_trace_coverage",
    "check_trace_field_completeness",
    "check_trace_index",
    "check_variable_naming_convention",
    "check_wukaisan",
    "get_changed_files_by_hash",
    "update_file_hash_baseline",
    "update_script_hash",
]
