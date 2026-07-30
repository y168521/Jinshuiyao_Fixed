#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修改前预检和梳理系统
用途：在每次修改前强制进行全面的系统梳理，防止"失忆"问题
"""

import os
import sys
import json
import time
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

class PreChangeAnalyzer:
    """修改前预检分析器"""
    
    def __init__(self, base_path=None):
        """初始化预检器"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 关键文件路径
        self.audit_log_path = self.base_path / "金水谣数据" / "log" / "change_audit.logl"
        self.changelog_path = self.base_path / "CHANGELOG.md"
        self.precheck_log_path = self.base_path / "金水谣数据" / "log" / "prechange_analysis.logl"
        self.analysis_report_path = self.base_path / "金水谣数据" / "log" / "prechange_report.md"
        
        # 配置文件
        self.config = {
            'min_analysis_score': 70,        # 最低分析评分
            'required_checks': ['file_status', 'audit_coherence', 'change_pattern'],
            'max_recent_changes': 20,        # 分析的最近变更数量
            'warning_thresholds': {
                'recent_fixes': 3,           # 最近修复警告阈值
                'unlinked_changes': 5,       # 未关联变更警告阈值
                'duplicate_patterns': 3,     # 重复模式警告阈值
            }
        }
    
    def run_prechange_analysis(self, target_path=None, change_description=""):
        """运行修改前全面分析"""
        print("=" * 70)
        print("📋 修改前全面分析系统")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # 记录分析开始
        analysis_data = {
            'timestamp': datetime.now().isoformat(),
            'target_path': str(target_path) if target_path else None,
            'change_description': change_description,
            'analysis_steps': [],
            'findings': [],
            'warnings': [],
            'recommendations': [],
            'scores': {},
            'overall_score': 0
        }
        
        print(f"\n1. 🎯 分析目标")
        print(f"   变更描述: {change_description or '未指定'}")
        if target_path:
            target_abs = self.base_path / target_path if not Path(target_path).is_absolute() else target_path
            print(f"   目标路径: {target_path}")
            print(f"   文件存在: {'✅ 是' if target_abs.exists() else '❌ 否'}")
        
        # 运行各项分析
        analysis_data['analysis_steps'].append("开始修改前全面分析")
        
        # 2. 系统状态分析
        print(f"\n2. 📊 系统状态概览")
        system_status = self._analyze_system_status()
        analysis_data.update(system_status)
        print(f"   最近变更: {system_status.get('recent_change_count', 0)} 条")
        print(f"   活跃文件: {system_status.get('active_file_count', 0)} 个")
        print(f"   系统评分: {system_status.get('system_score', 0)}/100")
        
        # 3. 目标文件分析
        if target_path:
            print(f"\n3. 🔍 目标文件详细分析")
            file_analysis = self._analyze_target_file(target_path)
            analysis_data.update(file_analysis)
            
            if file_analysis.get('file_exists'):
                print(f"   文件大小: {file_analysis.get('file_size_mb', 0):.2f} MB")
                print(f"   最近修改: {file_analysis.get('last_modified', '未知')}")
                print(f"   变更历史: {file_analysis.get('change_history_count', 0)} 次")
            else:
                print(f"   ⚠️  目标文件不存在，这将是新文件")
        
        # 4. 变更影响分析
        print(f"\n4. 📈 变更影响分析")
        impact_analysis = self._analyze_change_impact(target_path, change_description)
        analysis_data.update(impact_analysis)
        
        if impact_analysis.get('related_files'):
            print(f"   相关文件: {len(impact_analysis['related_files'])} 个")
            for i, file in enumerate(impact_analysis['related_files'][:3]):
                print(f"     - {file}")
            if len(impact_analysis['related_files']) > 3:
                print(f"     ... 还有 {len(impact_analysis['related_files']) - 3} 个相关文件")
        
        # 5. 历史模式分析
        print(f"\n5. 🔄 历史变更模式分析")
        pattern_analysis = self._analyze_change_patterns(target_path)
        analysis_data.update(pattern_analysis)
        
        patterns = pattern_analysis.get('common_patterns', [])
        if patterns:
            print(f"   常见模式: {len(patterns)} 种")
            for i, pattern in enumerate(patterns[:2]):
                print(f"     - {pattern[:60]}...")
        else:
            print(f"   ℹ️  未发现明显的变更模式")
        
        # 6. 风险评估
        print(f"\n6. ⚠️  变更风险评估")
        risk_assessment = self._assess_change_risks(target_path, change_description)
        analysis_data.update(risk_assessment)
        
        risks = risk_assessment.get('identified_risks', [])
        if risks:
            print(f"   发现风险: {len(risks)} 项")
            for i, risk in enumerate(risks[:3]):
                print(f"     - {risk}")
        else:
            print(f"   ✅ 未发现高风险")
        
        # 7. 综合评分
        overall_score = self._calculate_overall_score(analysis_data)
        analysis_data['overall_score'] = overall_score
        
        print(f"\n7. 🎯 综合评估")
        print(f"   综合评分: {overall_score}/100")
        
        status_text = self._get_status_text(overall_score)
        print(f"   建议: {status_text}")
        
        # 8. 生成报告
        report_path = self._generate_analysis_report(analysis_data)
        
        # 9. 记录分析结果
        self._log_analysis_result(analysis_data)
        
        print(f"\n" + "=" * 70)
        print(f"📋 分析完成！")
        print(f"报告位置: {report_path}")
        print(f"分析记录: {self.precheck_log_path}")
        print("=" * 70)
        
        # 决策支持
        if overall_score >= self.config['min_analysis_score']:
            print(f"\n✅ 建议继续修改，系统状态良好")
        else:
            print(f"\n⚠️  建议重新考虑或优化计划，存在风险")
        
        return analysis_data
    
    def _analyze_system_status(self):
        """分析系统整体状态"""
        status = {
            'system_score': 0,
            'recent_change_count': 0,
            'active_file_count': 0,
            'recent_fixes_count': 0,
            'status_summary': ''
        }
        
        try:
            # 统计最近变更
            if self.audit_log_path.exists():
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    lines = list(f)
                    status['recent_change_count'] = len(lines)
                
                # 分析最近24小时变更
                one_day_ago = datetime.now().timestamp() - 86400
                recent_count = 0
                fix_count = 0
                
                for line in lines[-100:]:  # 最近100行
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('type') == 'FIX':
                            fix_count += 1
                        recent_count += 1
                    except Exception:
                        continue
                
                status['recent_fixes_count'] = fix_count
            
            # 统计活跃文件
            code_dirs = ['core', 'utils', 'scripts', 'gui', 'engines']
            active_files = 0
            
            for code_dir in code_dirs:
                dir_path = self.base_path / code_dir
                if dir_path.exists():
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            if file.endswith('.py'):
                                active_files += 1
            
            status['active_file_count'] = active_files
            
            # 计算系统评分
            score = 80  # 基础分
            
            # 根据修复频率调整分数
            if status['recent_fixes_count'] > 5:
                score -= 20
            elif status['recent_fixes_count'] > 2:
                score -= 10
            
            # 根据活跃文件数量调整
            if active_files > 200:
                score += 10
            elif active_files < 50:
                score -= 5
            
            status['system_score'] = max(0, min(100, score))
            
            # 生成状态摘要
            if score >= 80:
                status['status_summary'] = "系统状态优秀"
            elif score >= 60:
                status['status_summary'] = "系统状态良好" 
            else:
                status['status_summary'] = "系统状态需要关注"
                
        except Exception as e:
            status['status_summary'] = f"分析系统状态时出错: {str(e)}"
        
        return status
    
    def _analyze_target_file(self, target_path):
        """分析目标文件"""
        analysis = {
            'file_exists': False,
            'file_size_mb': 0,
            'last_modified': None,
            'change_history_count': 0,
            'file_type': 'unknown',
            'dependencies': []
        }
        
        try:
            target_abs = self.base_path / target_path if not Path(target_path).is_absolute() else target_path
            
            if target_abs.exists():
                analysis['file_exists'] = True
                analysis['file_size_mb'] = os.path.getsize(target_abs) / (1024 * 1024)
                analysis['last_modified'] = datetime.fromtimestamp(target_abs.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                
                # 根据扩展名判断文件类型
                ext = target_abs.suffix.lower()
                if ext in ['.py', '.pyw']:
                    analysis['file_type'] = 'python'
                elif ext == '.md':
                    analysis['file_type'] = 'markdown'
                elif ext in ['.json', '.jsonl']:
                    analysis['file_type'] = 'json'
                elif ext == '.html':
                    analysis['file_type'] = 'html'
                elif ext in ['.js', '.ts', '.jsx', '.tsx']:
                    analysis['file_type'] = 'javascript'
                else:
                    analysis['file_type'] = ext.replace('.', '')
                
                # 查找文件变更历史
                if self.audit_log_path.exists():
                    with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                        file_changes = 0
                        for line in f:
                            try:
                                entry = json.loads(line.strip())
                                files = entry.get('files_changed', [])
                                if isinstance(files, list):
                                    for file in files:
                                        if target_path in file or str(target_abs) in file:
                                            file_changes += 1
                                            break
                                elif isinstance(entry.get('file'), str):
                                    if target_path in entry['file'] or str(target_abs) in entry['file']:
                                        file_changes += 1
                            except Exception:
                                continue
                        
                        analysis['change_history_count'] = file_changes
                
                # 分析依赖关系（针对Python文件）
                if analysis['file_type'] == 'python':
                    dependencies = self._analyze_python_dependencies(target_abs)
                    analysis['dependencies'] = dependencies
            
            else:
                # 对于不存在的文件，检查类似文件
                similar_files = self._find_similar_files(target_path)
                analysis['similar_files'] = similar_files
        
        except Exception as e:
            analysis['error'] = f"分析目标文件时出错: {str(e)}"
        
        return analysis
    
    def _analyze_python_dependencies(self, file_path):
        """分析Python文件的依赖关系"""
        dependencies = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # 查找import语句
                import_patterns = [
                    r'import\s+([a-zA-Z0-9_]+(?:\s*,\s*[a-zA-Z0-9_]+)*)',
                    r'from\s+([a-zA-Z0-9_.]+)\s+import'
                ]
                
                for pattern in import_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if isinstance(match, str):
                            deps = [dep.strip() for dep in match.split(',')]
                            dependencies.extend(deps)
        
        except Exception:
            pass
        
        return dependencies[:10]  # 最多返回10个依赖
    
    def _find_similar_files(self, target_path):
        """查找类似文件"""
        similar_files = []
        
        try:
            target_name = Path(target_path).name
            
            # 在常见目录中查找类似文件
            search_dirs = ['core', 'utils', 'scripts', 'gui']
            
            for search_dir in search_dirs:
                dir_path = self.base_path / search_dir
                if dir_path.exists():
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            if target_name in file or target_name.split('.')[0] in file.split('.')[0]:
                                rel_path = Path(root) / file
                                try:
                                    rel_to_base = rel_path.relative_to(self.base_path)
                                    similar_files.append(str(rel_to_base))
                                except Exception:
                                    similar_files.append(str(rel_path))
        
        except Exception:
            pass
        
        return similar_files[:5]
    
    def _analyze_change_impact(self, target_path, change_description):
        """分析变更影响"""
        impact = {
            'related_files': [],
            'impact_level': 'low',
            'affected_modules': [],
            'risk_areas': []
        }
        
        if not target_path:
            return impact
        
        try:
            target_abs = self.base_path / target_path if not Path(target_path).is_absolute() else target_path
            
            # 1. 直接相关文件
            impact['related_files'].append(target_path)
            
            # 2. 根据文件类型分析可能的关联文件
            if target_abs.suffix.lower() == '.py':
                # 对于Python文件，查找可能的测试文件
                test_file = self._find_test_file(target_path)
                if test_file:
                    impact['related_files'].append(test_file)
                
                # 查找可能的配置文件
                config_files = self._find_config_files(target_path)
                impact['related_files'].extend(config_files)
            
            # 3. 根据变更描述分析影响范围
            if change_description:
                keywords = self._extract_keywords(change_description)
                for keyword in keywords:
                    # 查找包含关键词的文件
                    keyword_files = self._find_files_with_keyword(keyword)
                    impact['related_files'].extend(keyword_files)
            
            # 去重
            impact['related_files'] = list(set(impact['related_files']))[:10]
            
            # 评估影响级别
            impact_count = len(impact['related_files'])
            if impact_count >= 5:
                impact['impact_level'] = 'high'
            elif impact_count >= 2:
                impact['impact_level'] = 'medium'
            else:
                impact['impact_level'] = 'low'
            
            # 识别风险领域
            if 'fix' in change_description.lower() or 'bug' in change_description.lower():
                impact['risk_areas'].append('修复性变更可能存在兼容性问题')
            
            if 'core' in target_path or 'core/' in target_path:
                impact['risk_areas'].append('核心模块变更需谨慎')
        
        except Exception as e:
            impact['error'] = f"分析变更影响时出错: {str(e)}"
        
        return impact
    
    def _find_test_file(self, file_path):
        """查找对应的测试文件"""
        try:
            file_name = Path(file_path).stem
            test_patterns = [
                f"test_{file_name}.py",
                f"{file_name}_test.py",
                f"test_{file_name}_*.py"
            ]
            
            test_dirs = ['tests', 'test', 'tests/unit', 'tests/integration']
            
            for test_dir in test_dirs:
                dir_path = self.base_path / test_dir
                if dir_path.exists():
                    for pattern in test_patterns:
                        for test_file in dir_path.glob(pattern):
                            try:
                                return str(test_file.relative_to(self.base_path))
                            except Exception:
                                return str(test_file)
        
        except Exception:
            pass
        
        return None
    
    def _find_config_files(self, file_path):
        """查找可能的配置文件"""
        config_files = []
        
        try:
            # 常见配置文件
            common_configs = ['config.py', 'settings.py', 'config.json', 'settings.json']
            
            for config in common_configs:
                config_path = self.base_path / config
                if config_path.exists():
                    config_files.append(config)
        
        except Exception:
            pass
        
        return config_files
    
    def _extract_keywords(self, text):
        """从文本中提取关键词"""
        keywords = []
        
        if not text:
            return keywords
        
        # 移除标点符号
        import re
        clean_text = re.sub(r'[^\w\s]', ' ', text.lower())
        
        # 分词
        words = clean_text.split()
        
        # 筛选有意义的关键词
        meaningful_words = []
        for word in words:
            if len(word) > 3 and word not in ['this', 'that', 'with', 'from', 'will', 'need', 'when']:
                meaningful_words.append(word)
        
        return meaningful_words[:5]
    
    def _find_files_with_keyword(self, keyword):
        """查找包含关键词的文件"""
        files_found = []
        
        try:
            # 搜索路径
            search_dirs = ['core', 'utils', 'scripts', 'gui']
            
            for search_dir in search_dirs:
                dir_path = self.base_path / search_dir
                if dir_path.exists():
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            if file.endswith('.py'):
                                file_path = Path(root) / file
                                try:
                                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read().lower()
                                        if keyword in content:
                                            try:
                                                rel_path = file_path.relative_to(self.base_path)
                                                files_found.append(str(rel_path))
                                            except Exception:
                                                files_found.append(str(file_path))
                                except Exception:
                                    pass
        
        except Exception:
            pass
        
        return files_found[:3]
    
    def _analyze_change_patterns(self, target_path):
        """分析历史变更模式"""
        patterns = {
            'common_patterns': [],
            'recurring_issues': [],
            'change_frequency': 'low',
            'last_change_date': None
        }
        
        try:
            if target_path and self.audit_log_path.exists():
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    target_changes = []
                    
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            
                            # 检查是否与目标文件相关
                            is_related = False
                            files = entry.get('files_changed', [])
                            if isinstance(files, list):
                                for file in files:
                                    if target_path in file:
                                        is_related = True
                                        break
                            elif isinstance(entry.get('file'), str):
                                if target_path in entry['file']:
                                    is_related = True
                            
                            if is_related:
                                target_changes.append(entry)
                        except Exception:
                            continue
                    
                    # 分析变更模式
                    if target_changes:
                        patterns['change_count'] = len(target_changes)
                        patterns['last_change'] = target_changes[-1].get('timestamp')
                        
                        # 分析常见变更类型
                        change_types = defaultdict(int)
                        for change in target_changes:
                            change_type = change.get('type', '')
                            if change_type:
                                change_types[change_type] += 1
                        
                        for change_type, count in change_types.items():
                            if count > 1:
                                patterns['common_patterns'].append(f"{change_type}类型变更{count}次")
                        
                        # 分析变更频率
                        if len(target_changes) >= 5:
                            patterns['change_frequency'] = 'high'
                            patterns['recurring_issues'].append(f"文件频繁变更 ({len(target_changes)}次)")
                        
                        if change_types.get('FIX', 0) > 2:
                            patterns['recurring_issues'].append(f"多次修复性变更 ({change_types['FIX']}次)")
        
        except Exception as e:
            patterns['error'] = f"分析变更模式时出错: {str(e)}"
        
        return patterns
    
    def _assess_change_risks(self, target_path, change_description):
        """评估变更风险"""
        risks = {
            'identified_risks': [],
            'risk_level': 'low',
            'confidence_score': 0
        }
        
        try:
            confidence = 80  # 初始置信度
            
            # 1. 新的文件风险较低
            if not target_path or not Path(target_path).exists():
                risks['identified_risks'].append("新文件创建风险较低")
                confidence += 10
            
            # 2. 变更描述不明确会增加风险
            if not change_description or len(change_description.strip()) < 10:
                risks['identified_risks'].append("变更描述不明确")
                confidence -= 20
                risks['risk_level'] = 'medium'
            
            # 3. 核心模块变更风险较高
            if target_path:
                core_paths = ['core/', 'engines/', 'gui/main']
                for core_path in core_paths:
                    if core_path in target_path:
                        risks['identified_risks'].append("核心模块变更需谨慎")
                        confidence -= 15
                        risks['risk_level'] = 'high'
                        break
            
            # 4. 修复性变更可能涉及已知问题
            if change_description and ('fix' in change_description.lower() or 'bug' in change_description.lower()):
                risks['identified_risks'].append("修复性变更需确保不引入新问题")
                confidence -= 5
            
            # 5. 近期频繁变更增加风险
            change_analysis = self._analyze_change_patterns(target_path)
            if change_analysis.get('change_frequency') == 'high':
                risks['identified_risks'].append("文件近期频繁变更，可能存在隐藏问题")
                confidence -= 10
                risks['risk_level'] = 'medium'
            
            risks['confidence_score'] = max(0, min(100, confidence))
            
            # 确定风险级别
            if confidence >= 80:
                risks['risk_level'] = 'low'
            elif confidence >= 60:
                risks['risk_level'] = 'medium'
            else:
                risks['risk_level'] = 'high'
        
        except Exception as e:
            risks['error'] = f"评估变更风险时出错: {str(e)}"
        
        return risks
    
    def _calculate_overall_score(self, analysis_data):
        """计算综合评分"""
        score = 80  # 基础分
        
        try:
            # 1. 系统状态 (权重30%)
            system_score = analysis_data.get('system_score', 0)
            score += (system_score - 80) * 0.3
            
            # 2. 变更清晰度 (权重20%)
            change_desc = analysis_data.get('change_description', '')
            if change_desc and len(change_desc.strip()) >= 20:
                score += 15
            elif change_desc and len(change_desc.strip()) >= 10:
                score += 5
            else:
                score -= 20
            
            # 3. 风险评估 (权重25%)
            risk_level = analysis_data.get('risk_level', 'low')
            if risk_level == 'low':
                score += 15
            elif risk_level == 'medium':
                score -= 5
            elif risk_level == 'high':
                score -= 25
            
            # 4. 变更影响 (权重15%)
            impact_level = analysis_data.get('impact_level', 'low')
            if impact_level == 'low':
                score += 10
            elif impact_level == 'medium':
                score -= 5
            elif impact_level == 'high':
                score -= 15
            
            # 5. 历史模式 (权重10%)
            change_freq = analysis_data.get('change_frequency', 'low')
            if change_freq == 'low':
                score += 5
            elif change_freq == 'high':
                risk_count = len(analysis_data.get('recurring_issues', []))
                score -= risk_count * 5
        
        except Exception:
            pass
        
        return max(0, min(100, score))
    
    def _get_status_text(self, score):
        """获取状态文本"""
        if score >= 80:
            return "准备充分，可以安全继续"
        elif score >= 65:
            return "准备基本充分，建议微调后继续"
        elif score >= 50:
            return "存在一定风险，建议优化计划"
        else:
            return "风险过高，建议重新规划"
    
    def _generate_analysis_report(self, analysis_data):
        """生成详细分析报告"""
        try:
            current_time = datetime.now()
            
            report_content = [
                "# 修改前全面分析报告",
                f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 📋 分析摘要",
                f"- **目标路径**: {analysis_data.get('target_path') or '未指定'}",
                f"- **变更描述**: {analysis_data.get('change_description') or '未提供'}",
                f"- **综合评分**: **{analysis_data.get('overall_score', 0)}/100**",
                f"- **分析时间**: {analysis_data.get('timestamp', '未知')}",
                "",
                "## 📊 系统状态分析",
                f"- **系统评分**: {analysis_data.get('system_score', 0)}/100",
                f"- **状态摘要**: {analysis_data.get('status_summary', '未知')}",
                f"- **最近变更**: {analysis_data.get('recent_change_count', 0)} 条审计记录",
                f"- **活跃文件**: {analysis_data.get('active_file_count', 0)} 个代码文件",
                "",
                "## 🔍 目标文件分析"
            ]
            
            # 目标文件信息
            if analysis_data.get('file_exists', False):
                report_content.append(f"- **文件存在**: ✅ 是")
                report_content.append(f"- **文件大小**: {analysis_data.get('file_size_mb', 0):.2f} MB")
                report_content.append(f"- **最后修改**: {analysis_data.get('last_modified', '未知')}")
                report_content.append(f"- **文件类型**: {analysis_data.get('file_type', '未知')}")
                report_content.append(f"- **变更历史**: {analysis_data.get('change_history_count', 0)} 次记录")
                
                if analysis_data.get('dependencies'):
                    report_content.append(f"- **主要依赖**: {', '.join(analysis_data.get('dependencies', [])[:5])}")
            else:
                report_content.append(f"- **文件存在**: ❌ 否")
                report_content.append(f"- **文件类型**: 新文件")
                if analysis_data.get('similar_files'):
                    report_content.append(f"- **类似文件**:")
                    for file in analysis_data.get('similar_files', [])[:3]:
                        report_content.append(f"  - {file}")
            
            report_content.append("")
            
            # 变更影响分析
            report_content.append("## 📈 变更影响分析")
            report_content.append(f"- **影响级别**: {analysis_data.get('impact_level', 'unknown').upper()}")
            
            if analysis_data.get('related_files'):
                report_content.append(f"- **相关文件**:")
                for i, file in enumerate(analysis_data.get('related_files', [])[:5]):
                    report_content.append(f"  - {file}")
                
                if len(analysis_data.get('related_files', [])) > 5:
                    report_content.append(f"  - ... 共 {len(analysis_data['related_files'])} 个相关文件")
            else:
                report_content.append(f"- **相关文件**: 未发现其他相关文件")
            
            report_content.append("")
            
            # 历史模式分析
            report_content.append("## 🔄 历史变更模式")
            if analysis_data.get('common_patterns'):
                report_content.append(f"- **常见模式**:")
                for pattern in analysis_data.get('common_patterns', [])[:3]:
                    report_content.append(f"  - {pattern}")
            else:
                report_content.append(f"- **常见模式**: 未发现明显模式")
            
            if analysis_data.get('recurring_issues'):
                report_content.append(f"- **重复问题**:")
                for issue in analysis_data.get('recurring_issues', [])[:3]:
                    report_content.append(f"  - {issue}")
            
            if analysis_data.get('change_frequency'):
                report_content.append(f"- **变更频率**: {analysis_data['change_frequency'].upper()}")
            
            report_content.append("")
            
            # 风险评估
            report_content.append("## ⚠️  风险评估")
            report_content.append(f"- **风险级别**: {analysis_data.get('risk_level', 'unknown').upper()}")
            report_content.append(f"- **置信度**: {analysis_data.get('confidence_score', 0)}/100")
            
            if analysis_data.get('identified_risks'):
                report_content.append(f"- **识别风险**:")
                for risk in analysis_data.get('identified_risks', [])[:5]:
                    report_content.append(f"  - {risk}")
            else:
                report_content.append(f"- **识别风险**: 未识别到高风险")
            
            report_content.append("")
            
            # 建议
            report_content.append("## 💡 修改建议")
            
            score = analysis_data.get('overall_score', 0)
            if score >= 80:
                report_content.append("1. **可以继续修改** - 系统状态良好，准备充分")
                report_content.append("2. **保持记录完整** - 确保在变更审计日志中添加记录")
                report_content.append("3. **进行冒烟测试** - 修改后运行简测试")
            elif score >= 65:
                report_content.append("1. **建议优化后继续** - 存在一些次要问题")
                report_content.append("2. **充实变更描述** - 更清晰地说明修改目的")
                report_content.append("3. **检查依赖关系** - 确保不会影响其他模块")
            elif score >= 50:
                report_content.append("1. **建议重新规划** - 存在中等风险")
                report_content.append("2. **详细分析影响** - 进行更深入的代码审查")
                report_content.append("3. **咨询相关人员** - 获取更多专业知识支持")
            else:
                report_content.append("1. **不建议继续** - 风险过高")
                report_content.append("2. **召开专项会议** - 讨论替代方案")
                report_content.append("3. **分阶段实施** - 将大变更拆分成小步骤")
            
            # 操作指南
            report_content.append("")
            report_content.append("## 🛠️ 操作指南")
            report_content.append("### 继续修改的操作:")
            report_content.append("1. 确认变更计划已充分理解")
            report_content.append("2. 在CHANGELOG中预添加变更记录")
            report_content.append("3. 创建备份: `python scripts/create_backup.py`")
            report_content.append("4. 实施变更")
            report_content.append("5. 添加审计日志记录")
            report_content.append("6. 运行验证测试")
            
            # 写入报告
            with open(self.analysis_report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_content))
            
            return self.analysis_report_path
            
        except Exception as e:
            print(f"生成分析报告时出错: {e}")
            return None
    
    def _log_analysis_result(self, analysis_data):
        """记录分析结果到日志"""
        try:
            log_entry = {
                'timestamp': analysis_data.get('timestamp'),
                'target_path': analysis_data.get('target_path'),
                'change_description': analysis_data.get('change_description'),
                'overall_score': analysis_data.get('overall_score'),
                'system_score': analysis_data.get('system_score', 0),
                'risk_level': analysis_data.get('risk_level', 'unknown'),
                'analysis_duration_ms': (datetime.fromisoformat(analysis_data.get('timestamp').replace('Z', '+00:00')) - datetime.now()).total_seconds() * -1000 if analysis_data.get('timestamp') else 0
            }
            
            with open(self.precheck_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        except Exception as e:
            print(f"记录分析结果时出错: {e}")

def main():
    """主函数"""
    import sys
    
    analyzer = PreChangeAnalyzer()
    
    if len(sys.argv) > 1:
        target_path = sys.argv[1]
        change_description = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        
        print(f"目标路径: {target_path}")
        print(f"变更描述: {change_description}")
        
        result = analyzer.run_prechange_analysis(target_path, change_description)
        
        # 返回分析结果状态码
        score = result.get('overall_score', 0)
        if score >= 80:
            sys.exit(0)  # 优秀
        elif score >= 65:
            sys.exit(1)  # 良好
        elif score >= 50:
            sys.exit(2)  # 中等
        else:
            sys.exit(3)  # 高风险
    
    else:
        # 交互式模式
        print("请指定要分析的目标文件路径:")
        print("示例: python scripts/prechange_analyzer.py core/example.py '修复数据验证逻辑'")
        sys.exit(1)

if __name__ == "__main__":
    main()