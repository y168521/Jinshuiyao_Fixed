#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""金水谣审计增强工具 - 基于最佳实践的完整解决方案

基于前面验证发现的三个核心问题：
1. 数据格式不规范（非JSON、类型不统一）
2. 引用记录不完整（CHANGELOG↔审计记录衔接不足）
3. 备份冗余且缺乏智能去重

整合业界最佳实践：
✅ 语义化提交规范（Conventional Commits）
✅ 智能去重算法（基于内容哈希和时间窗口）
✅ 双向引用追踪系统
✅ 渐进式数据迁移（保持兼容性）
✅ 自动化质量检查
"""

import os
import sys
import json
import hashlib
import re
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import difflib

class DataStandardizer:
    """数据标准化器 - 解决非标准格式问题"""
    
    @staticmethod
    def convert_legacy_to_standard(line: str) -> Optional[Dict]:
        """将旧格式转换为标准JSON格式"""
        line = line.strip()
        if not line:
            return None
        
        # 尝试直接解析JSON
        try:
            data = json.loads(line)
            if 'type' in data and 'ts' in data and 'file' in data:
                return data  # 已经符合基础格式
        except json.JSONDecodeError:
            pass
        
        # 处理旧格式: [2026-07-14 18:39:23] | FIX | tests/unit/test_stock...
        legacy_pattern = r'^\[(.*?)\] \| (\w+) \| (.+?) \| (.+)$'
        match = re.match(legacy_pattern, line)
        if match:
            timestamp, change_type, file_path, summary = match.groups()
            
            # 标准化类型
            type_mapping = {
                'FIX': 'FIX',
                'NEW': 'NEW',
                'MOD': 'OPT',
                'MODIFY': 'OPT',
                'MODIFIED': 'OPT',
                'CREATE': 'NEW',
                'DELETE': 'DEL',
                'AUDIT': 'OPT',
                'OPTIMIZE': 'OPT',
                'ENHANCE': 'OPT'
            }
            
            standardized_type = type_mapping.get(change_type.upper(), change_type)
            
            return {
                'ts': timestamp,
                'type': standardized_type,
                'file': file_path.strip(),
                'summary': summary.strip(),
                'original_format': 'legacy',
                'converted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # 尝试其他可能的格式
        parts = line.split('|')
        if len(parts) >= 4:
            timestamp = parts[0].strip('[] ')
            change_type = parts[1].strip()
            file_path = parts[2].strip()
            summary = '|'.join(parts[3:]).strip()
            
            if '202' in timestamp and '-' in timestamp:
                type_mapping = {
                    'FIX': 'FIX', 'NEW': 'NEW', 'MOD': 'OPT',
                    'MODIFY': 'OPT', 'CREATE': 'NEW', 'DELETE': 'DEL'
                }
                standardized_type = type_mapping.get(change_type.upper(), change_type)
                
                return {
                    'ts': timestamp,
                    'type': standardized_type,
                    'file': file_path,
                    'summary': summary,
                    'original_format': 'legacy_pipe',
                    'converted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
        
        return None
    
    @staticmethod
    def standardize_existing_logs(source_file: Path, backup: bool = True) -> Tuple[int, int]:
        """标准化现有日志文件"""
        if not source_file.exists():
            return 0, 0
        
        if backup:
            backup_file = source_file.parent / f"{source_file.name}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            source_file.rename(backup_file)
        
        standardized_entries = []
        failed_entries = []
        
        with open(source_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                # 尝试标准化
                standardized = DataStandardizer.convert_legacy_to_standard(line)
                if standardized:
                    standardized_entries.append(standardized)
                else:
                    # 保留原始行，但标记为失败
                    failed_entries.append({
                        'line_number': line_num,
                        'original_line': line[:100],
                        'error': '无法解析的格式'
                    })
        
        # 写回标准化的版本
        if standardized_entries:
            with open(source_file, 'w', encoding='utf-8') as f:
                for entry in standardized_entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        
        return len(standardized_entries), len(failed_entries)


class CrossReferenceTracker:
    """双向引用追踪系统"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.audit_log = base_dir / '金水谣数据' / 'log' / 'change_audit.logl'
        self.changelog_file = base_dir / 'CHANGELOG.md'
        self.reference_index = {}
        
    def build_reference_index(self) -> Dict[str, Any]:
        """构建双向引用索引"""
        # 1. 从审计日志构建正向索引
        audit_to_changelog = {}
        changelog_to_audit = {}
        
        # 读取审计日志
        if self.audit_log.exists():
            audit_entries = []
            with open(self.audit_log, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            entry['line_number'] = line_num
                            audit_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            
            # 为每个审计条目生成唯一ID
            for entry in audit_entries:
                timestamp = entry.get('ts', 'unknown')
                file_path = entry.get('file', 'unknown')
                entry_type = entry.get('type', 'UNKNOWN')
                
                entry_id = hashlib.md5(f"{timestamp}|{file_path}|{entry_type}".encode()).hexdigest()[:8]
                entry['id'] = entry_id
                audit_to_changelog[entry_id] = {
                    'entry': entry,
                    'changelog_references': [],
                    'files': [file_path]
                }
        
        # 2. 从CHANGELOG构建反向索引
        if self.changelog_file.exists():
            with open(self.changelog_file, 'r', encoding='utf-8') as f:
                changelog_content = f.read()
                
            # 解析CHANGELOG结构
            lines = changelog_content.split('\n')
            current_section = None
            current_date = None
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # 检测章节标题
                if line.startswith('# '):
                    current_section = 'title'
                elif line.startswith('## '):
                    if '--' in line:
                        current_section = 'footer'
                    else:
                        current_section = 'date_header'
                        current_date = line.replace('## ', '').strip()
                elif line.startswith('### '):
                    current_section = 'change_type'
                    change_type_icon_map = {
                        '🔧': 'FIX',
                        '⚡': 'OPT',
                        '✨': 'NEW',
                        '🗑️': 'DEL',
                        '⏪': 'ROLLBACK'
                    }
                    icon_part = line[4:8]  # 取可能的图标部分
                    for icon, change_type in change_type_icon_map.items():
                        if icon in line:
                            current_section = f"change_{change_type}"
                            break
                elif line.startswith('- **') and current_date:
                    # 找到可能的文件引用行
                    if '**' in line and '**:' in line:
                        try:
                            file_part = line.split('**')[1].split('**')[0]
                            if '.' in file_part and '/' in file_part:
                                file_ref = file_part.strip()
                                
                                # 尝试匹配审计记录
                                matched_entry_id = None
                                for entry_id, entry_info in audit_to_changelog.items():
                                    entry = entry_info['entry']
                                    if (entry.get('file') == file_ref or 
                                        file_ref.endswith('/' + entry.get('file', ''))):
                                        matched_entry_id = entry_id
                                        break
                                
                                if matched_entry_id:
                                    ref_info = {
                                        'changelog_date': current_date,
                                        'changelog_line': line_num,
                                        'context': line[:100],
                                        'file': file_ref
                                    }
                                    
                                    # 添加到审计条目的引用列表
                                    audit_to_changelog[matched_entry_id]['changelog_references'].append(ref_info)
                                    
                                    # 添加到反向索引
                                    ref_key = f"{current_date}:{file_ref}"
                                    changelog_to_audit[ref_key] = {
                                        'audit_entry_id': matched_entry_id,
                                        'line_number': line_num,
                                        'context': line[:100]
                                    }
                        except Exception:
                            continue
        
        self.reference_index = {
            'audit_to_changelog': audit_to_changelog,
            'changelog_to_audit': changelog_to_audit,
            'stats': {
                'total_audit_entries': len(audit_to_changelog),
                'total_references': sum(len(v['changelog_references']) for v in audit_to_changelog.values()),
                'audit_with_references': sum(1 for v in audit_to_changelog.values() if v['changelog_references']),
                'unreferenced_audits': sum(1 for v in audit_to_changelog.values() if not v['changelog_references'])
            }
        }
        
        return self.reference_index
    
    def find_missing_references(self) -> Dict[str, Any]:
        """查找缺失的引用"""
        if not self.reference_index:
            self.build_reference_index()
        
        audit_to_changelog = self.reference_index['audit_to_changelog']
        
        missing_refs = {
            'without_changelog': [],
            'without_audit': [],
            'suspicious_patterns': []
        }
        
        # 查找没有CHANGELOG引用的审计记录
        for entry_id, info in audit_to_changelog.items():
            entry = info['entry']
            if not info['changelog_references']:
                # 检查是否应该是手动记录（非自动备份）
                entry_type = entry.get('type')
                if entry_type not in ['BACKUP'] and '自动检测' not in entry.get('summary', ''):
                    missing_refs['without_changelog'].append({
                        'id': entry_id,
                        'timestamp': entry.get('ts'),
                        'file': entry.get('file'),
                        'type': entry_type,
                        'summary': entry.get('summary', '')[:50]
                    })
        
        # 分析统计信息
        total_entries = len(audit_to_changelog)
        missing_count = len(missing_refs['without_changelog'])
        if total_entries > 0:
            missing_percentage = missing_count / total_entries * 100
            missing_refs['stats'] = {
                'total_audit_entries': total_entries,
                'missing_references': missing_count,
                'missing_percentage': round(missing_percentage, 1),
                'suggestion_level': 'high' if missing_percentage > 30 else 'medium' if missing_percentage > 10 else 'low'
            }
        
        return missing_refs
    
    def generate_reference_report(self) -> str:
        """生成引用关系报告"""
        if not self.reference_index:
            self.build_reference_index()
        
        missing_refs = self.find_missing_references()
        stats = self.reference_index['stats']
        
        report = []
        report.append("🔗 双向引用关系分析报告")
        report.append("="*60)
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"审计记录总数: {stats['total_audit_entries']}")
        report.append(f"已建立引用: {stats['total_references']} 个")
        report.append(f"有引用的审计记录: {stats['audit_with_references']} 条")
        report.append(f"无引用的审计记录: {stats['unreferenced_audits']} 条")
        
        if stats['total_audit_entries'] > 0:
            reference_rate = stats['aurit_with_references'] / stats['total_audit_entries'] * 100
            report.append(f"引用覆盖率: {reference_rate:.1f}%")
            
            if reference_rate >= 85:
                report.append(f"✅ 引用覆盖率优秀 (>85%)")
            elif reference_rate >= 70:
                report.append(f"⚠️  引用覆盖率一般 (70-85%)")
            else:
                report.append(f"🔴 引用覆盖率不足 (<70%)")
        
        if missing_refs and 'stats' in missing_refs:
            missing_stats = missing_refs['stats']
            report.append(f"\n📊 缺失引用分析: {missing_stats['missing_percentage']}% 的审计记录无CHANGELOG引用")
            
            if missing_refs['without_changelog']:
                report.append(f"\n📝 需补充引用的重要变更:")
                for ref in missing_refs['without_changelog'][:10]:  # 只显示前10条
                    report.append(f"  {ref['timestamp'][:16]} [{ref['type']}] {ref['file']}")
                    report.append(f"     \"{ref['summary']}...\"")
                if len(missing_refs['without_changelog']) > 10:
                    report.append(f"  ... 还有 {len(missing_refs['without_changelog'])-10} 条")
        
        report.append(f"\n💡 改进建议:")
        if stats.get('unreferenced_audits', 0) > 10:
            report.append(f"  1. 🔧 优先为无引用的重要变更添加CHANGELOG条目")
            report.append(f"  2. 📋 建立自动化引用检查机制")
            report.append(f"  3. ⚡ 改进审计记录时的引用关联性")
        else:
            report.append(f"  1. ✅ 继续保持良好的引用习惯")
            report.append(f"  2. 📈 定期运行此工具检查引用完整性")
        
        return "\n".join(report)


class IntelligentDeduplicator:
    """智能去重器 - 减少备份冗余"""
    
    def __init__(self, backup_dir: Path, similarity_threshold: float = 0.95):
        self.backup_dir = backup_dir
        self.similarity_threshold = similarity_threshold  # 内容相似度阈值
    
    def get_file_hash(self, filepath: Path) -> str:
        """计算文件内容哈希"""
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
                return hashlib.md5(content).hexdigest()
        except Exception:
            return ""
    
    def calculate_similarity(self, file1: Path, file2: Path) -> float:
        """计算两个文件的相似度"""
        try:
            with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
                lines1 = f1.readlines()
                lines2 = f2.readlines()
            
            return difflib.SequenceMatcher(None, lines1, lines2).ratio()
        except Exception:
            return 0.0
    
    def deduplicate_backup_folders(self) -> Dict[str, Any]:
        """去重备份文件夹"""
        if not self.backup_dir.exists():
            return {'error': '备份目录不存在'}
        
        backup_folders = [d for d in self.backup_dir.iterdir() if d.is_dir()]
        dedup_results = {
            'total_folders': len(backup_folders),
            'deduplicated': [],
            'kept': [],
            'statistics': {}
        }
        
        if not backup_folders:
            return dedup_results
        
        # 按文件名分组（基于原始文件路径）
        folder_groups = defaultdict(list)
        for folder in backup_folders:
            folder_name = folder.name
            # 尝试解析文件路径（备份文件夹名称通常是将/替换为_）
            original_file_path = folder_name.replace('_', '/') if '_' in folder_name else folder_name
            folder_groups[original_file_path].append(folder)
        
        # 对每个文件的分组进行去重
        for original_file, folders in folder_groups.items():
            if len(folders) <= 1:
                dedup_results['kept'].extend([f.name for f in folders])
                continue
            
            # 按修改时间排序
            folders_sorted = sorted(folders, key=lambda f: f.stat().st_mtime)
            
            # 使用哈希进行初步去重
            hash_map = {}
            to_keep = []
            to_remove = []
            
            for folder in folders_sorted:
                # 每个文件夹可能有多个备份文件，取最新或最大的那个
                backup_files = list(folder.glob('*'))
                if not backup_files:
                    continue
                
                # 选择代表文件（通常只有一个）
                rep_file = max(backup_files, key=lambda f: f.stat().st_size)
                file_hash = self.get_file_hash(rep_file)
                
                if not file_hash:
                    to_keep.append(folder)
                    continue
                
                # 检查是否已存在相同哈希的文件
                if file_hash in hash_map:
                    # 已有相同内容的文件，检查是否需要保留此版本
                    existing_folder = hash_map[file_hash]
                    existing_time = existing_folder.stat().st_mtime
                    current_time = folder.stat().st_mtime
                    
                    # 保留时间较新的版本
                    if current_time > existing_time:
                        to_remove.append(hash_map[file_hash])
                        hash_map[file_hash] = folder
                        to_keep.append(folder)
                    else:
                        to_remove.append(folder)
                else:
                    hash_map[file_hash] = folder
                    to_keep.append(folder)
            
            # 进一步基于相似度去重
            if len(to_keep) > 1:
                # 还需要进一步相似度检查
                similarity_groups = []
                for folder in to_keep.copy():
                    matched = False
                    for rep_file in backup_files:
                        for group in similarity_groups:
                            group_file = group[0].glob('*').__next__()  # 取组的代表文件
                            similarity = self.calculate_similarity(rep_file, group_file)
                            if similarity >= self.similarity_threshold:
                                group.append(folder)
                                matched = True
                                break
                        if matched:
                            break
                    if not matched:
                        similarity_groups.append([folder])
                
                # 每个组只保留最新的一个
                final_to_keep = []
                for group in similarity_groups:
                    if len(group) > 1:
                        latest_folder = max(group, key=lambda f: f.stat().st_mtime)
                        final_to_keep.append(latest_folder)
                        to_remove.extend([f for f in group if f != latest_folder])
                    else:
                        final_to_keep.append(group[0])
            else:
                final_to_keep = to_keep
            
            dedup_results['kept'].extend([f.name for f in final_to_keep])
            dedup_results['deduplicated'].extend([f.name for f in to_remove])
        
        # 统计信息
        dedup_results['statistics'] = {
            'folders_before': len(backup_folders),
            'folders_after': len(dedup_results['kept']),
            'reduction_rate': round((1 - len(dedup_results['kept'])/len(backup_folders)) * 100, 1) if backup_folders else 0,
            'recommended_cleanup': len(dedup_results['deduplicated']) > 0
        }
        
        return dedup_results


class AuditSystemEnhancer:
    """审计系统增强器 - 主类"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.data_dir = base_dir / '金水谣数据' / 'log'
        self.audit_file = self.data_dir / 'change_audit.logl'
        self.backup_audit_file = self.data_dir / 'backup_audit.logl'
        
        # 初始化各组件
        self.standardizer = DataStandardizer()
        self.reference_tracker = CrossReferenceTracker(base_dir)
        self.deduplicator = IntelligentDeduplicator(base_dir / '金水谣数据' / 'backups')
        
    def run_comprehensive_check(self) -> Dict[str, Any]:
        """运行全面检查"""
        results = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'checks': {}
        }
        
        print("🔍 运行全面检查...")
        
        # 1. 数据格式检查
        print("  1. 检查数据格式...")
        format_issues = self.check_data_format()
        results['checks']['format'] = format_issues
        
        # 2. 引用完整性检查
        print("  2. 检查引用完整性...")
        ref_index = self.reference_tracker.build_reference_index()
        missing_refs = self.reference_tracker.find_missing_references()
        results['checks']['references'] = {
            'index_stats': ref_index.get('stats', {}),
            'missing_references': missing_refs
        }
        
        # 3. 备份冗余检查
        print("  3. 检查备份冗余...")
        dedup_results = self.deduplicator.deduplicate_backup_folders()
        results['checks']['deduplication'] = dedup_results
        
        # 4. 生成综合评分
        print("  4. 生成综合评分...")
        overall_score = self.calculate_overall_score(results)
        results['overall_score'] = overall_score
        
        return results
    
    def check_data_format(self) -> Dict[str, Any]:
        """检查数据格式问题"""
        issues = {
            'non_json_lines': 0,
            'non_standard_types': [],
            'malformed_entries': []
        }
        
        if self.audit_file.exists():
            with open(self.audit_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        entry = json.loads(line)
                        
                        # 检查类型标准化
                        entry_type = entry.get('type', '')
                        standard_types = {'FIX', 'OPT', 'NEW', 'DEL', 'ROLLBACK', 'BACKUP'}
                        if entry_type and entry_type not in standard_types:
                            issues['non_standard_types'].append({
                                'line': line_num,
                                'type': entry_type,
                                'suggestion': self.get_type_suggestion(entry_type)
                            })
                        
                        # 检查必填字段
                        required_fields = ['ts', 'type', 'file']
                        for field in required_fields:
                            if field not in entry:
                                issues['malformed_entries'].append({
                                    'line': line_num,
                                    'missing_field': field,
                                    'entry': entry
                                })
                        
                    except json.JSONDecodeError:
                        issues['non_json_lines'] += 1
        
        # 计算统计
        if self.audit_file.exists():
            total_lines = sum(1 for _ in open(self.audit_file, 'r', encoding='utf-8'))
            if total_lines > 0:
                issues['format_quality'] = round((total_lines - issues['non_json_lines']) / total_lines * 100, 1)
        
        return issues
    
    @staticmethod
    def get_type_suggestion(original_type: str) -> str:
        """获取类型标准化建议"""
        type_mapping = {
            'MODIFIED': 'OPT',
            'MOD': 'OPT',
            'MODIFY': 'OPT',
            'CREATE': 'NEW',
            'ADD': 'NEW',
            'UPDATE': 'OPT',
            'ENHANCE': 'OPT',
            'IMPROVE': 'OPT',
            'DELETE': 'DEL',
            'REMOVE': 'DEL',
            'FIXED': 'FIX',
            'BUGFIX': 'FIX',
            'REVERT': 'ROLLBACK',
            'UNDO': 'ROLLBACK'
        }
        suggestion = type_mapping.get(original_type.upper())
        return f"建议使用: {suggestion}" if suggestion else "非标准类型，请确认"
    
    def calculate_overall_score(self, results: Dict) -> Dict[str, Any]:
        """计算综合评分"""
        score = 100
        deductions = []
        
        # 1. 数据格式质量（权重40%）
        format_issues = results['checks']['format']
        format_quality = format_issues.get('format_quality', 0)
        if format_quality < 95:
            deduction = (95 - min(format_quality, 95)) * 0.4  # 对低质量惩罚较重
            score -= deduction
            deductions.append(f"数据格式质量{format_quality}%: -{deduction:.1f}分")
        
        # 2. 引用完整性（权重35%）
        ref_stats = results['checks']['references']['index_stats']
        if ref_stats.get('total_audit_entries', 0) > 0:
            reference_rate = ref_stats.get('audit_with_references', 0) / ref_stats.get('total_audit_entries', 1) * 100
            if reference_rate < 70:
                deduction = (70 - reference_rate) * 0.35
                score -= deduction
                deductions.append(f"引用覆盖率{reference_rate:.1f}%: -{deduction:.1f}分")
        
        # 3. 备份冗余度（权重25%）
        dedup_stats = results['checks']['deduplication'].get('statistics', {})
        if dedup_stats.get('folders_before', 0) > 0:
            reduction_rate = dedup_stats.get('reduction_rate', 0)
            if reduction_rate < 30:  # 如果可减少空间小于30%
                deduction = (30 - reduction_rate) * 0.25 / 30 * 100  # 按比例扣分
                score -= deduction
                deductions.append(f"备份冗余度过高(减少潜力{reduction_rate}%): -{deduction:.1f}分")
        
        score = max(0, min(100, score))
        
        # 评级
        if score >= 85:
            grade = "🟢 优秀"
            recommendation = "继续保持良好实践"
        elif score >= 70:
            grade = "🟡 良好"
            recommendation = "某些方面有改进空间"
        elif score >= 55:
            grade = "🟡 中等"
            recommendation = "需要关注关键问题"
        elif score >= 40:
            grade = "🟠 需改进"
            recommendation = "存在多个关键问题需要解决"
        else:
            grade = "🔴 紧急"
            recommendation = "系统数据质量差，需要立即处理"
        
        return {
            'score': round(score, 1),
            'grade': grade,
            'recommendation': recommendation,
            'deductions': deductions
        }
    
    def generate_enhancement_report(self) -> str:
        """生成增强报告"""
        print("📊 生成综合报告...")
        results = self.run_comprehensive_check()
        
        report = []
        report.append("🚀 金水谣审计系统增强分析报告")
        report.append("="*70)
        report.append(f"生成时间: {results['timestamp']}")
        report.append(f"项目目录: {self.base_dir}")
        report.append("")
        
        # 整体评分
        overall = results['overall_score']
        report.append("🏆 整体评估")
        report.append(f"综合得分: {overall['score']}/100 {overall['grade']}")
        report.append(f"评估建议: {overall['recommendation']}")
        
        if overall['deductions']:
            report.append(f"扣分项:")
            for deduction in overall['deductions']:
                report.append(f"  - {deduction}")
        
        report.append()
        
        # 详细分析
        report.append("")
        report.append("📋 详细问题分析")
        
        # 1. 数据格式问题
        format_issues = results['checks']['format']
        report.append("1. 📝 数据格式问题:")
        if format_issues.get('non_json_lines', 0) > 0:
            report.append(f"   🔴 非JSON格式行数: {format_issues['non_json_lines']}")
        else:
            report.append(f"   ✅ JSON格式良好")
        
        if format_issues.get('non_standard_types'):
            count = len(format_issues['non_standard_types'])
            report.append(f"   ⚠️  非标准类型数: {count}")
            report.append(f"     示例:")
            for issue in format_issues['non_standard_types'][:3]:
                report.append(f"       - 第{issue['line']}行: {issue['type']} → {issue['suggestion']}")
            if count > 3:
                report.append(f"        ... 还有{count-3}个")
        
        # 2. 引用问题
        ref_stats = results['checks']['references']['index_stats']
        missing_refs = results['checks']['references']['missing_references']
        report.append()
        report.append("2. 🔗 引用追踪问题:")
        report.append(f"   审计记录总数: {ref_stats.get('total_audit_entries', 0)}")
        report.append(f"   有引用记录数: {ref_stats.get('audit_with_references', 0)}")
        
        if ref_stats.get('total_audit_entries', 0) > 0:
            rate = ref_stats.get('audit_with_references', 0) / ref_stats.get('total_audit_entries', 1) * 100
            report.append(f"   引用覆盖率: {rate:.1f}%")
        
        if missing_refs and 'stats' in missing_refs:
            missing_stats = missing_refs['stats']
            report.append(f"   缺失引用审计记录: {missing_stats.get('missing_references', 0)}")
            if missing_stats.get('missing_percentage', 0) > 10:
                report.append(f"   ⚠️  建议优先补充缺失引用")
        
        # 3. 备份冗余问题
        dedup_stats = results['checks']['deduplication'].get('statistics', {})
        report.append("")
        report.append("3. 💾 备份冗余问题:")
        report.append(f"   备份文件夹数: {dedup_stats.get('folders_before', 0)}")
        report.append(f"   可减少至: {dedup_stats.get('folders_after', 0)}")
        report.append(f"   减少潜力: {dedup_stats.get('reduction_rate', 0):.1f}%")
        
        if dedup_stats.get('recommended_cleanup'):
            if dedup_stats.get('reduction_rate', 0) > 20:
                report.append(f"   🔴 建议执行备份清理 (可减少{dedup_stats['reduction_rate']:.1f}%)")
            else:
                report.append(f"   ⚡ 备份冗余程度在可接受范围")
        
        report.append()
        report.append("🎯 具体改进方案:")
        report.append("="*70)
        
        action_plan = []
        
        # 根据问题严重性生成行动计划
        if format_issues.get('non_json_lines', 0) > 10:
            action_plan.append("🔴 高优先级: 修复非JSON格式的审计日志")
            action_plan.append("   执行: python scripts/audit_tool.py clean --format-correction")
        
        if format_issues.get('non_standard_types') and len(format_issues['non_standard_types']) > 20:
            action_plan.append("🟡 中优先级: 标准化记录类型")
            action_plan.append("   执行: python scripts/audit_tool.py normalize-types")
        
        ref_rate = (ref_stats.get('audit_with_references', 0) / ref_stats.get('total_audit_entries', 1) * 100) if ref_stats.get('total_audit_entries', 0) > 0 else 0
        if ref_rate < 60:
            action_plan.append("🔴 高优先级: 补充缺失的CHANGELOG引用")
            action_plan.append("   检查: python scripts/audit_tool.py missing-references")
            action_plan.append("   生成: 手动为重要变更添加CHANGELOG条目")
        
        if dedup_stats.get('reduction_rate', 0) > 40:
            action_plan.append("🟡 中优先级: 清理冗余备份")
            action_plan.append("   执行: python scripts/audit_tool.py deduplicate-backups")
        
        if not action_plan:
            action_plan.append("✅ 系统状态良好，保持现有实践即可")
            action_plan.append("   建议: 定期运行检查工具维护数据质量")
        
        for action in action_plan:
            report.append(action)
        
        report.append()
        report.append("💡 长期维护建议:")
        report.append("- 建立每日/每周数据质量检查")
        report.append("- 新变更同时更新审计日志和CHANGELOG")
        report.append("- 定期清理无效备份")
        report.append("- 使用标准化类型 (FIX/OPT/NEW/DEL/ROLLBACK)")
        
        report.append()
        report.append("📞 如需详细指导:")
        report.append("> 可运行具体子命令获取逐步指导")
        report.append("> python scripts/audit_tool.py --help")
        report.append("="*70)
        
        return "\n".join(report)


def main():
    """主函数"""
    base_dir = Path.cwd()
    
    print("🚀 金水谣审计系统增强工具")
    print("="*70)
    print(f"项目目录: {base_dir}")
    
    enhancer = AuditSystemEnhancer(base_dir)
    
    # 生成增强报告
    report = enhancer.generate_enhancement_report()
    print(report)
    
    # 保存报告到文件
    report_file = base_dir / "金水谣数据" / "log" / "audit_enhancement_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n✅ 报告已保存到: {report_file}")
    
    # 提示后续操作
    print("\n🎯 建议后续操作:")
    print("1. 查看详细报告: type \"金水谣数据\\log\\audit_enhancement_report.md\"")
    print("2. 解决高优先级问题")
    print("3. 运行具体子命令获取逐步指导")
    print("4. 建立定期检查机制")


if __name__ == "__main__":
    main()