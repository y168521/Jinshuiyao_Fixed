#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣系统全流程梳理与AI增强工具
用途：梳理所有开发流程，提供AI辅助优化建议，防止"失忆"问题
"""

import os
import sys
import json
import re
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

class JinshuiyaoProcessManager:
    """金水谣系统流程管理器"""
    
    def __init__(self, base_path=None):
        """初始化流程管理器"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 文件路径
        self.audit_log_path = self.base_path / "金水谣数据" / "log" / "change_audit.logl"
        self.changelog_path = self.base_path / "CHANGELOG.md"
        self.process_report_path = self.base_path / "金水谣数据" / "log" / "process_overview_report.md"
        self.ai_advice_path = self.base_path / "金水谣数据" / "log" / "ai_optimization_advice.md"
        
        # DeepSeek API配置 (示例配置，需要用户自己注册获取API key)
        self.ai_config = {
            'deepseek_enabled': False,
            'deepseek_api_key': 'your_api_key_here',
            'deepseek_api_url': 'https://api.deepseek.com/v1/chat/completions',
            'ai_model': 'deepseek-v4-pro',
            'ai_temperature': 0.7,
            'ai_max_tokens': 2000
        }
        
        # 流程定义
        self.processes = {
            '代码开发流程': {
                'description': '日常代码编写、调试和提交',
                'steps': [
                    '需求分析', '设计构思', '代码实现', '本地测试',
                    '代码审查', '提交推送', '部署验证'
                ],
                'tools': ['prechange_analyzer.py', 'work_record_validator.py'],
                'checkpoints': 7
            },
            '变更管理流程': {
                'description': '系统变更的记录、验证和追溯',
                'steps': [
                    '变更申请', '影响分析', '实施计划', '代码修改',
                    '记录审计', '更新CHANGELOG', '验证测试'
                ],
                'tools': ['audit_system_monitor.py', 'supplement_changelog.py'],
                'checkpoints': 7
            },
            '质量保证流程': {
                'description': '代码质量检查和优化',
                'steps': [
                    '代码审查', '静态分析', '单元测试', '集成测试',
                    '性能测试', '安全检查', '文档更新'
                ],
                'tools': ['analyze_changelog_coverage.py', 'audit_system_scheduler.py'],
                'checkpoints': 7
            },
            '版本发布流程': {
                'description': '版本规划、发布和维护',
                'steps': [
                    '版本规划', '功能冻结', '测试验证', '文档完善',
                    '发布打包', '部署上线', '监控反馈'
                ],
                'tools': ['utils/smart_audit.py'],
                'checkpoints': 7
            },
            '问题解决流程': {
                'description': '识别、分析和解决系统问题',
                'steps': [
                    '问题识别', '根本分析', '方案设计', '实施修复',
                    '验证测试', '经验总结', '知识归档'
                ],
                'tools': ['scripts/enhance_audit_system.py'],
                'checkpoints': 7
            }
        }
        
        # 业界最佳实践（基于搜索结果）
        self.best_practices = {
            'AI辅助开发': {
                '来源': '2026年AI Agent开发完全指南',
                '建议': [
                    '使用多模型调用策略：不同的模型擅长不同的任务',
                    '建立工具编排系统：将AI能力与开发工具集成',
                    '实施成本控制机制：平衡性能与成本',
                    '设计熔断和降级策略：保证系统稳定性'
                ],
                '实施工具': ['DeepSeek', '自定义AI助手']
            },
            '变更管理': {
                '来源': '软件开发中的代码版本控制与变更管理',
                '建议': [
                    '建立完整的版本控制与变更管理流程',
                    '利用自动化工具提升效率和质量',
                    '实施代码审查与分支管理最佳实践',
                    '建立代码质量管理与监控机制'
                ],
                '实施工具': ['Git流程', '自动化CI/CD']
            },
            '智能代码助手': {
                '来源': 'DeepSeek深度解析：程序员必备的AI助手',
                '建议': [
                    '将AI助手作为24小时待命的"技术搭档"',
                    '用于处理重复性代码和复杂算法',
                    '集成到本地开发环境（如PyCharm）',
                    '建立代码模板和最佳实践库'
                ],
                '实施工具': ['DeepSeek-R1', 'IDE插件']
            },
            '流程优化': {
                '来源': 'AI辅助编程工具在软件开发中的集成与优化策略',
                '建议': [
                    '从代码生成到智能调试全流程优化',
                    '实现自动化测试和持续集成',
                    '建立智能代码审查机制',
                    '降低AI编程成本40%'
                ],
                '实施工具': ['智能代码助手', 'AI测试工具']
            }
        }
    
    def run_full_process_analysis(self):
        """运行全流程分析"""
        print("=" * 80)
        print("🚀 金水谣系统全流程梳理与分析")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        analysis_result = {
            'timestamp': datetime.now().isoformat(),
            'processes_analyzed': len(self.processes),
            'best_practices_applied': len(self.best_practices),
            'process_health_scores': {},
            'gaps_identified': [],
            'optimization_opportunities': [],
            'ai_assistance_needs': [],
            'overall_score': 0
        }
        
        print(f"\n1. 📋 分析系统流程架构")
        process_overview = self._analyze_process_architecture()
        analysis_result.update(process_overview)
        
        print(f"   发现流程数量: {len(self.processes)}")
        print(f"   每个流程步骤数: 平均{sum(len(p['steps']) for p in self.processes.values()) // len(self.processes)}步")
        
        print(f"\n2. 🛠️  评估现有工具支持")
        tool_assessment = self._assess_tool_support()
        analysis_result.update(tool_assessment)
        
        tool_coverage = tool_assessment.get('tool_coverage_percentage', 0)
        print(f"   工具覆盖率: {tool_coverage:.1f}%")
        print(f"   已有工具: {tool_assessment.get('available_tools_count', 0)}个")
        print(f"   建议补充工具: {tool_assessment.get('suggested_tools_count', 0)}个")
        
        print(f"\n3. 🔍 比对业界最佳实践")
        practice_comparison = self._compare_with_best_practices()
        analysis_result.update(practice_comparison)
        
        practice_match_rate = practice_comparison.get('best_practice_match_rate', 0)
        print(f"   最佳实践匹配度: {practice_match_rate:.1f}%")
        print(f"   已采纳最佳实践: {practice_comparison.get('adopted_practices_count', 0)}项")
        print(f"   待采纳最佳实践: {practice_comparison.get('suggested_practices_count', 0)}项")
        
        print(f"\n4. 🧠 分析AI集成需求")
        ai_analysis = self._analyze_ai_integration_needs()
        analysis_result.update(ai_analysis)
        
        print(f"   AI集成得分: {ai_analysis.get('ai_integration_score', 0)}/100")
        print(f"   建议AI应用场景: {len(ai_analysis.get('recommended_ai_scenarios', []))}个")
        print(f"   潜在AI瓶颈: {len(ai_analysis.get('potential_ai_bottlenecks', []))}个")
        
        print(f"\n5. 📈 计算流程健康度")
        health_scores = self._calculate_process_health_scores(
            process_overview, tool_assessment, practice_comparison, ai_analysis
        )
        analysis_result.update(health_scores)
        
        overall_score = health_scores.get('overall_process_score', 0)
        analysis_result['overall_score'] = overall_score
        
        print(f"   代码开发流程: {health_scores.get('code_development_score', 0)}/100")
        print(f"   变更管理流程: {health_scores.get('change_management_score', 0)}/100")
        print(f"   质量保证流程: {health_scores.get('quality_assurance_score', 0)}/100")
        print(f"   版本发布流程: {health_scores.get('version_release_score', 0)}/100")
        print(f"   问题解决流程: {health_scores.get('issue_resolution_score', 0)}/100")
        print(f"   综合流程得分: {overall_score}/100")
        
        print(f"\n6. 🎯 流程状态评估")
        status_assessment = self._assess_process_status(overall_score)
        analysis_result['process_status'] = status_assessment.get('status', 'unknown')
        analysis_result['status_description'] = status_assessment.get('description', '')
        
        status_text = {
            'excellent': '✅ 优秀',
            'good': '👍 良好',
            'fair': '⚠️ 中等',
            'poor': '❌ 需要改进',
            'very_poor': '🔴 问题严重'
        }.get(analysis_result['process_status'], '❓ 未知')
        
        print(f"   总体状态: {status_text}")
        print(f"   状态说明: {status_assessment.get('description', '')}")
        
        print(f"\n7. 💡 生成优化建议")
        optimization_advice = self._generate_optimization_advice(analysis_result)
        analysis_result['optimization_advice'] = optimization_advice
        
        print(f"   短期建议: {len(optimization_advice.get('short_term', []))}条")
        print(f"   中期建议: {len(optimization_advice.get('medium_term', []))}条")
        print(f"   长期建议: {len(optimization_advice.get('long_term', []))}条")
        
        print(f"\n8. 🤖 调用AI优化建议（可选）")
        if self.ai_config['deepseek_enabled']:
            ai_optimization = self._get_ai_optimization_advice(analysis_result)
            analysis_result['ai_optimization_advice'] = ai_optimization
            print(f"   获取到AI优化建议: {len(ai_optimization.get('top_suggestions', []))}条")
        else:
            print(f"   AI建议: 未启用（需要配置DeepSeek API）")
        
        print(f"\n9. 📋 生成详细报告")
        report_path = self._generate_comprehensive_report(analysis_result)
        print(f"   报告位置: {report_path}")
        
        print(f"\n10. 📝 生成AI优化建议报告")
        ai_report_path = self._generate_ai_advice_report(analysis_result)
        print(f"   AI建议报告: {ai_report_path}")
        
        print("\n" + "=" * 80)
        print("全流程梳理完成！")
        print("=" * 80)
        
        # 显示关键结论
        print(f"\n📊 关键结论:")
        print(f"   综合流程得分: {overall_score}/100")
        print(f"   工具覆盖率: {tool_coverage:.1f}%")
        print(f"   最佳实践匹配: {practice_match_rate:.1f}%")
        print(f"   流程健全度: {status_text}")
        
        if overall_score >= 80:
            print(f"✅ 流程体系: 基本健全，已建立有效机制")
        elif overall_score >= 60:
            print(f"⚠️  流程体系: 部分健全，需要改进关键环节")
        else:
            print(f"❌ 流程体系: 不够健全，建议优先优化")
        
        return analysis_result
    
    def _analyze_process_architecture(self):
        """分析流程架构"""
        result = {
            'total_processes': len(self.processes),
            'process_details': {},
            'process_interconnections': {},
            'average_steps_per_process': 0,
            'total_checkpoints': 0
        }
        
        total_steps = 0
        total_checkpoints = 0
        
        for process_name, process_info in self.processes.items():
            steps = process_info.get('steps', [])
            tools = process_info.get('tools', [])
            checkpoints = process_info.get('checkpoints', 0)
            
            result['process_details'][process_name] = {
                'steps_count': len(steps),
                'tools_count': len(tools),
                'checkpoints': checkpoints,
                'description': process_info.get('description', '')
            }
            
            total_steps += len(steps)
            total_checkpoints += checkpoints
        
        result['average_steps_per_process'] = total_steps // len(self.processes) if self.processes else 0
        result['total_checkpoints'] = total_checkpoints
        
        # 分析流程间关系
        process_connections = defaultdict(list)
        process_names = list(self.processes.keys())
        
        for i, proc1 in enumerate(process_names):
            for j, proc2 in enumerate(process_names):
                if i != j:
                    # 简单的连接关系分析
                    tools1 = self.processes[proc1].get('tools', [])
                    tools2 = self.processes[proc2].get('tools', [])
                    
                    common_tools = set(tools1).intersection(set(tools2))
                    if common_tools:
                        process_connections[proc1].append({
                            'connected_to': proc2,
                            'connection_type': 'tool_sharing',
                            'common_tools': list(common_tools)
                        })
        
        result['process_interconnections'] = dict(process_connections)
        
        return result
    
    def _assess_tool_support(self):
        """评估工具支持"""
        result = {
            'available_tools': [],
            'missing_tools': [],
            'tool_coverage_percentage': 0,
            'available_tools_count': 0,
            'suggested_tools_count': 0
        }
        
        # 收集所有需要的工具
        all_required_tools = set()
        for process_info in self.processes.values():
            tools = process_info.get('tools', [])
            all_required_tools.update(tools)
        
        # 检查工具是否存在
        available_tools = []
        missing_tools = []
        
        for tool in all_required_tools:
            tool_path = self.base_path / tool
            
            # 检查文件是否存在
            if tool_path.exists():
                available_tools.append({
                    'name': tool,
                    'path': str(tool_path.relative_to(self.base_path)),
                    'exists': True,
                    'size_mb': tool_path.stat().st_size / (1024 * 1024) if tool_path.exists() else 0
                })
            else:
                missing_tools.append({
                    'name': tool,
                    'path': tool,
                    'exists': False,
                    'suggested_alternative': self._suggest_tool_alternative(tool)
                })
        
        result['available_tools'] = available_tools
        result['missing_tools'] = missing_tools
        result['available_tools_count'] = len(available_tools)
        result['suggested_tools_count'] = len(missing_tools)
        
        # 计算工具覆盖率
        if all_required_tools:
            result['tool_coverage_percentage'] = (len(available_tools) / len(all_required_tools)) * 100
        
        return result
    
    def _suggest_tool_alternative(self, tool_name):
        """建议工具替代品"""
        tool_suggestions = {
            'prechange_analyzer.py': '可使用 scripts/analyze_changelog_coverage.py 分析变更影响',
            'work_record_validator.py': '可使用脚本验证审计记录完整性',
            'audit_system_monitor.py': '已存在 - scripts/audit_system_monitor.py',
            'supplement_changelog.py': '已存在 - scripts/supplement_changelog.py',
            'analyze_changelog_coverage.py': '可检查CHANGELOG引用覆盖率',
            'audit_system_scheduler.py': '已存在 - scripts/audit_system_scheduler.py',
            'utils/smart_audit.py': '已存在 - utils/smart_audit.py',
            'scripts/enhance_audit_system.py': '可创建审计系统增强工具'
        }
        
        return tool_suggestions.get(tool_name, f"需要新工具: {tool_name}")
    
    def _compare_with_best_practices(self):
        """比对业界最佳实践"""
        result = {
            'adopted_practices': [],
            'suggested_practices': [],
            'best_practice_match_rate': 0,
            'adopted_practices_count': 0,
            'suggested_practices_count': 0
        }
        
        # 检查已存在的工具和功能
        existing_features = []
        
        # 检查是否已有AI相关功能
        if self._check_ai_capabilities():
            existing_features.append('AI辅助开发')
        
        # 检查是否已有变更管理工具
        if self.audit_log_path.exists() and self.changelog_path.exists():
            existing_features.append('变更管理')
        
        # 检查是否已有代码助手功能
        if self._check_code_assistant_capabilities():
            existing_features.append('智能代码助手')
        
        # 检查是否已有流程优化功能
        if self._check_process_optimization_capabilities():
            existing_features.append('流程优化')
        
        # 比对最佳实践
        for practice_name, practice_info in self.best_practices.items():
            if any(feature in practice_name for feature in existing_features):
                result['adopted_practices'].append({
                    'name': practice_name,
                    'description': '部分采纳',
                    'status': 'partial',
                    'recommendations': practice_info.get('建议', [])
                })
            else:
                result['suggested_practices'].append({
                    'name': practice_name,
                    'description': '未采纳',
                    'status': 'missing',
                    'recommendations': practice_info.get('建议', [])[:2]
                })
        
        result['adopted_practices_count'] = len(result['adopted_practices'])
        result['suggested_practices_count'] = len(result['suggested_practices'])
        
        # 计算最佳实践匹配率
        total_practices = len(self.best_practices)
        if total_practices > 0:
            result['best_practice_match_rate'] = (result['adopted_practices_count'] / total_practices) * 100
        
        return result
    
    def _check_ai_capabilities(self):
        """检查AI能力"""
        # 检查是否有AI相关配置或工具
        ai_files = ['scripts/analyze_changelog_coverage.py', 'scripts/supplement_changelog.py']
        
        for ai_file in ai_files:
            if (self.base_path / ai_file).exists():
                return True
        
        # 检查配置文件
        if self.ai_config.get('deepseek_enabled', False):
            return True
        
        return False
    
    def _check_code_assistant_capabilities(self):
        """检查代码助手能力"""
        # 检查是否有代码分析工具
        analysis_files = ['scripts/analyze_changelog_coverage.py', 'utils/smart_audit.py']
        
        for analysis_file in analysis_files:
            if (self.base_path / analysis_file).exists():
                return True
        
        return False
    
    def _check_process_optimization_capabilities(self):
        """检查流程优化能力"""
        # 检查是否有流程优化工具
        optimization_files = ['scripts/audit_system_monitor.py', 'scripts/audit_system_scheduler.py']
        
        for opt_file in optimization_files:
            if (self.base_path / opt_file).exists():
                return True
        
        return False
    
    def _analyze_ai_integration_needs(self):
        """分析AI集成需求"""
        result = {
            'ai_integration_score': 0,
            'recommended_ai_scenarios': [],
            'potential_ai_bottlenecks': [],
            'ai_tools_needed': []
        }
        
        score = 0
        
        # 推荐AI应用场景
        recommended_scenarios = [
            {
                'name': '智能变更分析',
                'description': '使用AI分析代码变更的影响范围和风险',
                'priority': 'high',
                'tools_needed': ['DeepSeek API', '变更分析模块']
            },
            {
                'name': '自动代码审查',
                'description': 'AI辅助代码质量检查和优化建议',
                'priority': 'medium',
                'tools_needed': ['代码理解AI', '审查规则库']
            },
            {
                'name': '智能流程优化',
                'description': '分析和优化开发流程瓶颈',
                'priority': 'low',
                'tools_needed': ['流程分析AI', '优化建议引擎']
            },
            {
                'name': '自动文档生成',
                'description': '基于代码变更自动更新文档',
                'priority': 'medium',
                'tools_needed': ['文档生成AI', '模板系统']
            }
        ]
        
        # 识别潜在AI瓶颈
        potential_bottlenecks = [
            'API调用成本控制',
            'AI响应时间延迟',
            '模型精度与可靠性',
            '数据隐私与安全性',
            '集成复杂度管理'
        ]
        
        # 推荐AI工具
        ai_tools_needed = [
            'DeepSeek API集成',
            '本地AI模型部署（可选）',
            'API调用代理和缓存',
            'AI响应质量监控'
        ]
        
        # 计算AI集成分数
        existing_ai_capabilities = self._check_ai_capabilities()
        existing_code_assistant = self._check_code_assistant_capabilities()
        
        if existing_ai_capabilities:
            score += 40
        
        if existing_code_assistant:
            score += 30
        
        if self.ai_config.get('deepseek_enabled', False):
            score += 30
        
        result['ai_integration_score'] = min(score, 100)
        result['recommended_ai_scenarios'] = recommended_scenarios
        result['potential_ai_bottlenecks'] = potential_bottlenecks
        result['ai_tools_needed'] = ai_tools_needed
        
        return result
    
    def _calculate_process_health_scores(self, process_overview, tool_assessment, practice_comparison, ai_analysis):
        """计算流程健康度分数"""
        result = {
            'code_development_score': 0,
            'change_management_score': 0,
            'quality_assurance_score': 0,
            'version_release_score': 0,
            'issue_resolution_score': 0,
            'overall_process_score': 0
        }
        
        # 基础分数
        base_score = 60
        
        # 1. 代码开发流程分数（权重25%）
        code_dev_score = base_score
        
        # 工具支持加分
        tool_coverage = tool_assessment.get('tool_coverage_percentage', 0)
        code_dev_score += tool_coverage * 0.25
        
        # AI集成加分
        ai_score = ai_analysis.get('ai_integration_score', 0)
        code_dev_score += ai_score * 0.15
        
        result['code_development_score'] = min(100, code_dev_score)
        
        # 2. 变更管理流程分数（权重25%）
        change_mgmt_score = base_score
        
        # 流程步骤完整性
        if process_overview.get('total_processes', 0) >= 5:
            change_mgmt_score += 15
        
        # 最佳实践采纳
        practice_rate = practice_comparison.get('best_practice_match_rate', 0)
        change_mgmt_score += practice_rate * 0.25
        
        result['change_management_score'] = min(100, change_mgmt_score)
        
        # 3. 质量保证流程分数（权重20%）
        quality_score = base_score
        
        # 工具覆盖率
        if tool_coverage >= 80:
            quality_score += 20
        elif tool_coverage >= 60:
            quality_score += 10
        
        result['quality_assurance_score'] = min(100, quality_score)
        
        # 4. 版本发布流程分数（权重15%）
        version_score = base_score
        
        # 检查是否有版本管理工具
        if self._check_version_management():
            version_score += 25
        
        result['version_release_score'] = min(100, version_score)
        
        # 5. 问题解决流程分数（权重15%）
        issue_score = base_score
        
        # 检查是否有问题追踪机制
        if self._check_issue_tracking():
            issue_score += 30
        
        result['issue_resolution_score'] = min(100, issue_score)
        
        # 6. 综合分数（加权平均）
        weights = {
            'code_development': 0.25,
            'change_management': 0.25,
            'quality_assurance': 0.20,
            'version_release': 0.15,
            'issue_resolution': 0.15
        }
        
        overall_score = (
            result['code_development_score'] * weights['code_development'] +
            result['change_management_score'] * weights['change_management'] +
            result['quality_assurance_score'] * weights['quality_assurance'] +
            result['version_release_score'] * weights['version_release'] +
            result['issue_resolution_score'] * weights['issue_resolution']
        )
        
        result['overall_process_score'] = round(overall_score, 1)
        
        return result
    
    def _check_version_management(self):
        """检查版本管理"""
        # 检查是否有版本管理相关文件
        version_files = [
            'CHANGELOG.md',
            '金水谣数据/log/change_audit.logl'
        ]
        
        for vfile in version_files:
            vpath = self.base_path / vfile
            if vpath.exists():
                return True
        
        return False
    
    def _check_issue_tracking(self):
        """检查问题追踪"""
        # 检查是否有问题追踪相关文件
        issue_files = [
            '金水谣数据/log/问题解决报告.md',
            '金水谣数据/log/health_monitor_log.jsonl',
            '金水谣数据/log/system_alerts.md'
        ]
        
        for ifile in issue_files:
            ipath = self.base_path / ifile
            if ipath.exists():
                return True
        
        return False
    
    def _assess_process_status(self, overall_score):
        """评估流程状态"""
        if overall_score >= 90:
            return {
                'status': 'excellent',
                'description': '流程体系非常健全，已采纳业界最佳实践，工具支持完善',
                'emoji': '✅'
            }
        elif overall_score >= 80:
            return {
                'status': 'good',
                'description': '流程体系基本健全，关键环节有较好支持，部分方面可优化',
                'emoji': '👍'
            }
        elif overall_score >= 70:
            return {
                'status': 'fair',
                'description': '流程体系中等，有基本框架但需要加强工具支持和最佳实践采纳',
                'emoji': '⚠️'
            }
        elif overall_score >= 60:
            return {
                'status': 'poor',
                'description': '流程体系需要改进，存在明显短板和缺失环节',
                'emoji': '❌'
            }
        else:
            return {
                'status': 'very_poor',
                'description': '流程体系问题严重，建议重新设计和实施流程管理',
                'emoji': '🔴'
            }
    
    def _generate_optimization_advice(self, analysis_result):
        """生成优化建议"""
        advice = {
            'short_term': [],
            'medium_term': [],
            'long_term': []
        }
        
        overall_score = analysis_result.get('overall_score', 0)
        tool_coverage = analysis_result.get('tool_coverage_percentage', 0)
        practice_rate = analysis_result.get('best_practice_match_rate', 0)
        ai_score = analysis_result.get('ai_integration_score', 0)
        
        # 短期建议（1个月内）
        if tool_coverage < 70:
            advice['short_term'].append(f"🛠️ 补充关键工具：工具覆盖率 {tool_coverage:.1f}% < 70%，建议补充缺失工具")
        
        if practice_rate < 60:
            advice['short_term'].append(f"📚 采纳基础实践：最佳实践采纳率 {practice_rate:.1f}% < 60%，建议采纳基础管理实践")
        
        # 中期建议（1-3个月）
        if ai_score < 50:
            advice['medium_term'].append(f"🤖 集成AI辅助：AI集成分数 {ai_score}/100，建议集成基础AI能力")
        
        if overall_score < 70:
            advice['medium_term'].append(f"🔄 优化流程衔接：综合得分 {overall_score}/100，建议优化流程间衔接")
        
        # 长期建议（3-6个月）
        advice['long_term'].append(f"🚀 建立智能开发平台：规划建立集AI辅助、流程自动化、智能分析于一体的开发平台")
        
        if overall_score < 80:
            advice['long_term'].append(f"🏗️ 架构深度优化：实施架构层面的深度优化，提升系统可维护性和可扩展性")
        
        # 如果各方面都不错，给出保持建议
        if overall_score >= 80:
            advice['short_term'].append(f"🎯 保持优秀实践：继续保持当前良好流程和工具使用")
            advice['medium_term'].append(f"📊 建立度量体系：建立流程效率和质量度量体系")
            advice['long_term'].append(f"✨ 探索前沿技术：探索更先进的AI辅助开发技术")
        
        return advice
    
    def _get_ai_optimization_advice(self, analysis_result):
        """获取AI优化建议"""
        if not self.ai_config['deepseek_enabled']:
            return {'error': 'DeepSeek API未启用', 'top_suggestions': []}
        
        try:
            # 准备分析数据
            analysis_text = f"""
            请分析以下软件开发流程现状并提供优化建议：
            
            1. 整体评估分数：{analysis_result.get('overall_score', 0)}/100
            2. 工具覆盖率：{analysis_result.get('tool_coverage_percentage', 0)}%
            3. 最佳实践匹配率：{analysis_result.get('best_practice_match_rate', 0)}%
            4. AI集成分数：{analysis_result.get('ai_integration_score', 0)}/100
            5. 流程状态：{analysis_result.get('process_status', '未知')}
            
            请提供3-5条最关键的优化建议。
            """
            
            # 调用DeepSeek API
            headers = {
                'Authorization': f'Bearer {self.ai_config["deepseek_api_key"]}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': self.ai_config['ai_model'],
                'messages': [
                    {
                        'role': 'system',
                        'content': '你是一个软件开发流程优化专家，擅长分析软件开发流程问题并提供实用的优化建议。'
                    },
                    {
                        'role': 'user',
                        'content': analysis_text
                    }
                ],
                'temperature': self.ai_config['ai_temperature'],
                'max_tokens': self.ai_config['ai_max_tokens']
            }
            
            response = requests.post(
                self.ai_config['deepseek_api_url'],
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                ai_advice = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
                
                # 解析AI建议
                advice_items = [line.strip() for line in ai_advice.split('\n') if line.strip()]
                
                return {
                    'ai_advice_raw': ai_advice[:500] + '...' if len(ai_advice) > 500 else ai_advice,
                    'top_suggestions': advice_items[:5],
                    'source': 'DeepSeek AI'
                }
            else:
                return {
                    'error': f'API调用失败: {response.status_code}',
                    'top_suggestions': []
                }
        
        except Exception as e:
            return {
                'error': f'获取AI建议时出错: {str(e)}',
                'top_suggestions': []
            }
    
    def _generate_comprehensive_report(self, analysis_result):
        """生成综合报告"""
        try:
            current_time = datetime.now()
            
            report_content = [
                "# 金水谣系统全流程梳理报告",
                f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 📊 执行摘要",
                f"- **综合流程得分**: **{analysis_result.get('overall_score', 0)}/100**",
                f"- **流程状态**: {analysis_result.get('process_status', '未知').upper()}",
                f"- **状态说明**: {analysis_result.get('status_description', '')}",
                f"- **分析时间**: {analysis_result.get('timestamp', '未知')}",
                f"- **涵盖流程**: {analysis_result.get('processes_analyzed', 0)} 个",
                f"- **参考最佳实践**: {analysis_result.get('best_practices_applied', 0)} 项",
                "",
                "## 🔗 流程架构分析",
                f"- **总流程数**: {analysis_result.get('total_processes', 0)}",
                f"- **平均步骤数**: {analysis_result.get('average_steps_per_process', 0)} 步/流程",
                f"- **总检查点**: {analysis_result.get('total_checkpoints', 0)}",
                ""
            ]
            
            # 流程详情
            report_content.append("### 各流程详情")
            
            processes = [
                ("代码开发流程", analysis_result.get('code_development_score', 0)),
                ("变更管理流程", analysis_result.get('change_management_score', 0)),
                ("质量保证流程", analysis_result.get('quality_assurance_score', 0)),
                ("版本发布流程", analysis_result.get('version_release_score', 0)),
                ("问题解决流程", analysis_result.get('issue_resolution_score', 0))
            ]
            
            for process_name, process_score in processes:
                status = '✅ 良好' if process_score >= 70 else '⚠️ 中等' if process_score >= 50 else '❌ 需要改进'
                report_content.append(f"- **{process_name}**: {process_score}/100 - {status}")
            
            report_content.append("")
            
            # 工具支持分析
            report_content.append("## 🛠️ 工具支持分析")
            report_content.append(f"- **工具覆盖率**: {analysis_result.get('tool_coverage_percentage', 0):.1f}%")
            report_content.append(f"- **已有工具**: {analysis_result.get('available_tools_count', 0)} 个")
            report_content.append(f"- **建议补充工具**: {analysis_result.get('suggested_tools_count', 0)} 个")
            report_content.append("")
            
            # 最佳实践分析
            report_content.append("## 📚 最佳实践采纳")
            report_content.append(f"- **最佳实践匹配率**: {analysis_result.get('best_practice_match_rate', 0):.1f}%")
            report_content.append(f"- **已采纳实践**: {analysis_result.get('adopted_practices_count', 0)} 项")
            report_content.append(f"- **待采纳实践**: {analysis_result.get('suggested_practices_count', 0)} 项")
            
            if self.best_practices:
                report_content.append("")
                report_content.append("**业界推荐最佳实践**:")
                for practice_name, practice_info in self.best_practices.items():
                    report_content.append(f"- **{practice_name}**: {practice_info.get('来源', '未知')}")
            
            report_content.append("")
            
            # AI集成分析
            report_content.append("## 🤖 AI集成分析")
            report_content.append(f"- **AI集成分数**: {analysis_result.get('ai_integration_score', 0)}/100")
            
            ai_scenarios = analysis_result.get('recommended_ai_scenarios', [])
            if ai_scenarios:
                report_content.append("")
                report_content.append("**推荐AI应用场景**:")
                for i, scenario in enumerate(ai_scenarios[:3]):
                    priority_text = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(scenario.get('priority', 'low'), '⚪')
                    report_content.append(f"- {priority_text} {scenario.get('name')}: {scenario.get('description')}")
            
            if self.ai_config['deepseek_enabled']:
                report_content.append("")
                report_content.append("**DeepSeek支持**: ✅ 已启用")
            else:
                report_content.append("")
                report_content.append("**DeepSeek支持**: ⚠️ 未启用（需要配置API Key）")
            
            report_content.append("")
            
            # 优化建议
            report_content.append("## 💡 优化建议总览")
            
            optimization_advice = analysis_result.get('optimization_advice', {})
            
            if optimization_advice.get('short_term'):
                report_content.append("### 🔥 短期建议（1个月内）")
                for i, advice in enumerate(optimization_advice.get('short_term', [])):
                    report_content.append(f"{i+1}. {advice}")
            
            if optimization_advice.get('medium_term'):
                report_content.append("")
                report_content.append("### ⏳ 中期建议（1-3个月）")
                for i, advice in enumerate(optimization_advice.get('medium_term', [])):
                    report_content.append(f"{i+1}. {advice}")
            
            if optimization_advice.get('long_term'):
                report_content.append("")
                report_content.append("### 🚀 长期建议（3-6个月）")
                for i, advice in enumerate(optimization_advice.get('long_term', [])):
                    report_content.append(f"{i+1}. {advice}")
            
            report_content.append("")
            
            # 行动指南
            report_content.append("## 🛠️ 立即行动指南")
            
            score = analysis_result.get('overall_score', 0)
            
            if score >= 80:
                report_content.append("1. **保持优势** - 继续执行当前有效的流程和工具使用")
                report_content.append("2. **量化评估** - 建立流程效率和质量度量体系")
                report_content.append("3. **分享经验** - 将良好实践推广到更广范围")
            elif score >= 60:
                report_content.append("1. **补齐短板** - 优先补充缺失的工具和支持")
                report_content.append("2. **强化实践** - 采纳更多业界最佳实践")
                report_content.append("3. **建立基线** - 建立流程改进的基线目标")
            else:
                report_content.append("1. **紧急改进** - 立即处理最关键的流程问题")
                report_content.append("2. **重构流程** - 考虑重新设计和实施关键流程")
                report_content.append("3. **寻求支持** - 咨询专家或研究成功案例")
            
            # 附录：现有工具列表
            if analysis_result.get('available_tools'):
                report_content.append("")
                report_content.append("## 📋 附录：现有工具清单")
                
                available_tools = analysis_result.get('available_tools', [])
                for tool in available_tools[:10]:
                    report_content.append(f"- **{tool.get('name')}**: {tool.get('path')} ({tool.get('size_mb', 0):.2f}MB)")
                
                if len(available_tools) > 10:
                    report_content.append(f"... 还有 {len(available_tools) - 10} 个工具")
            
            # 写入报告
            with open(self.process_report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_content))
            
            return self.process_report_path
            
        except Exception as e:
            print(f"生成综合报告时出错: {e}")
            return None
    
    def _generate_ai_advice_report(self, analysis_result):
        """生成AI建议报告"""
        try:
            current_time = datetime.now()
            
            ai_advice = analysis_result.get('ai_optimization_advice', {})
            
            if ai_advice.get('error'):
                # 如果没有AI建议，生成基于规则的版本
                advice_content = [
                    "# AI优化建议（基于规则）",
                    f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                    "",
                    "## ⚠️ 注意",
                    "DeepSeek API未启用，以下是基于规则的优化建议：",
                    ""
                ]
                
                # 基于分析结果生成建议
                score = analysis_result.get('overall_score', 0)
                tool_coverage = analysis_result.get('tool_coverage_percentage', 0)
                practice_rate = analysis_result.get('best_practice_match_rate', 0)
                
                if score < 70:
                    advice_content.append("## 🔥 核心建议")
                    advice_content.append("1. **建立完整流程基线** - 确保所有核心流程都有明确的定义和工具支持")
                    advice_content.append("2. **实施渐进式改进** - 每周改进一个流程，逐步优化")
                    advice_content.append("3. **建立反馈循环** - 收集流程执行反馈，持续改进")
                
                if tool_coverage < 70:
                    advice_content.append("")
                    advice_content.append("## 🛠️ 工具建议")
                    advice_content.append("1. **补充关键工具** - 优先补充对质量影响最大的工具")
                    advice_content.append("2. **建立工具库** - 整理可重用工具，形成工具链")
                    advice_content.append("3. **培训使用** - 确保团队成员能熟练使用工具")
                
                if practice_rate < 60:
                    advice_content.append("")
                    advice_content.append("## 📚 实践建议")
                    advice_content.append("1. **研究案例** - 学习类似项目的成功经验")
                    advice_content.append("2. **小规模试点** - 选择部分流程进行最佳实践试点")
                    advice_content.append("3. **总结经验** - 定期总结和分享实践心得")
                
            else:
                # 使用AI生成的建议
                advice_content = [
                    "# AI优化建议（DeepSeek生成）",
                    f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"来源: {ai_advice.get('source', '未知')}",
                    ""
                ]
                
                top_suggestions = ai_advice.get('top_suggestions', [])
                if top_suggestions:
                    advice_content.append("## 🎯 核心建议")
                    for i, suggestion in enumerate(top_suggestions):
                        advice_content.append(f"{i+1}. {suggestion}")
                else:
                    advice_content.append("## ⚠️ 未获取到明确的AI建议")
                
                if ai_advice.get('ai_advice_raw'):
                    advice_content.append("")
                    advice_content.append("## 📝 AI完整建议摘录")
                    advice_content.append(ai_advice.get('ai_advice_raw', ''))
            
            # 添加深度集成建议（基于搜索结果）
            advice_content.append("")
            advice_content.append("## 🔮 深度集成建议（基于业界研究）")
            advice_content.append("根据最新研究（2026年），建议考虑：")
            advice_content.append("")
            advice_content.append("### 🚀 AI智能助手深度集成")
            advice_content.append("1. **本地部署DeepSeek-R1模型** - 提供离线的智能代码助手")
            advice_content.append("2. **IDE插件开发** - 将AI能力集成到开发环境")
            advice_content.append("3. **自动化代码审查** - AI辅助的智能代码质量检查")
            advice_content.append("")
            
            advice_content.append("### 🔗 流程自动化增强")
            advice_content.append("1. **智能任务分配** - AI辅助的任务优先级排序和分配")
            advice_content.append("2. **自动文档生成** - 基于代码变更的自动化文档更新")
            advice_content.append("3. **预测性缺陷检测** - 基于历史数据的缺陷预测")
            advice_content.append("")
            
            advice_content.append("### 📊 数据驱动流程优化")
            advice_content.append("1. **流程效率度量** - 收集和分析流程执行数据")
            advice_content.append("2. **瓶颈识别** - AI辅助的流程瓶颈分析")
            advice_content.append("3. **持续改进循环** - 基于数据的持续流程优化")
            
            # 写入报告
            with open(self.ai_advice_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(advice_content))
            
            return self.ai_advice_path
            
        except Exception as e:
            print(f"生成AI建议报告时出错: {e}")
            return None

def main():
    """主函数"""
    import sys
    
    manager = JinshuiyaoProcessManager()
    
    print("金水谣系统全流程梳理与优化工具")
    print(f"版本: 1.0 | 日期: {datetime.now().strftime('%Y-%m-%d')}")
    print("")
    
    if len(sys.argv) > 1 and sys.argv[1] == '--auto':
        print("自动模式启动...")
    else:
        print("交互模式启动，按任意键开始分析...")
        input()
    
    # 运行全流程分析
    result = manager.run_full_process_analysis()
    
    # 返回分析结果状态码
    score = result.get('overall_score', 0)
    
    if score >= 80:
        sys.exit(0)  # 优秀
    elif score >= 70:
        sys.exit(1)  # 良好
    elif score >= 60:
        sys.exit(2)  # 中等
    else:
        sys.exit(3)  # 需要改进

if __name__ == "__main__":
    main()