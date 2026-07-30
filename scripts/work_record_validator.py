#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作记录验证机制
用途：验证每次变更是否有真实记录，确保"都会记录"的承诺有效执行
"""

import os
import sys
import json
import time
import hashlib
import difflib
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

class WorkRecordValidator:
    """工作记录验证器"""
    
    def __init__(self, base_path=None):
        """初始化验证器"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 关键文件路径
        self.audit_log_path = self.base_path / "金水谣数据" / "log" / "change_audit.logl"
        self.changelog_path = self.base_path / "CHANGELOG.md"
        self.validation_log_path = self.base_path / "金水谣数据" / "log" / "work_validation.logl"
        self.verification_report_path = self.base_path / "金水谣数据" / "log" / "work_verification_report.md"
        self.last_snapshot_path = self.base_path / "金水谣数据" / "log" / "last_system_snapshot.json"
        
        # 配置
        self.config = {
            'verification_window_hours': 24,         # 验证时间窗口（小时）
            'min_change_records_required': 1,        # 最低变更记录要求
            'auto_fix_missing_records': True,        # 自动修复缺失记录
            'notify_on_missing_records': True,       # 缺失记录时通知
            'record_verification_score_threshold': 80,  # 记录验证分数阈值
        }
    
    def run_work_validation(self, auto_fix=True):
        """运行工作记录验证"""
        print("=" * 70)
        print("🔍 工作记录验证系统")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        validation_data = {
            'timestamp': datetime.now().isoformat(),
            'validation_window_hours': self.config['verification_window_hours'],
            'verification_steps': [],
            'found_changes': [],
            'verified_records': [],
            'missing_records': [],
            'validation_errors': [],
            'statistics': {},
            'overall_score': 0,
            'validation_status': 'unknown'
        }
        
        print(f"\n1. 📅 确定验证时间窗口")
        window_start = datetime.now() - timedelta(hours=self.config['verification_window_hours'])
        print(f"   时间段: {window_start.strftime('%Y-%m-%d %H:%M')} 到 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        validation_data['verify_window_start'] = window_start.isoformat()
        validation_data['verify_window_end'] = datetime.now().isoformat()
        
        # 2. 扫描系统文件变更
        print(f"\n2. 📁 扫描文件系统变更")
        file_changes = self._scan_file_system_changes(window_start)
        
        validation_data['file_changes_count'] = len(file_changes)
        validation_data['found_changes'] = file_changes
        
        if file_changes:
            print(f"   发现文件变更: {len(file_changes)} 个")
            for i, change in enumerate(file_changes[:5]):
                print(f"     - {change.get('file_path', '未知')}: {change.get('change_type', '未知')}")
            if len(file_changes) > 5:
                print(f"     ... 还有 {len(file_changes) - 5} 个文件变更")
        else:
            print(f"   发现文件变更: 在时间窗口内未发现文件变更")
        
        # 3. 检查审计日志记录
        print(f"\n3. 📋 验证审计日志记录")
        audit_records = self._verify_audit_log_records(window_start, file_changes)
        
        validation_data['audit_records_count'] = len(audit_records.get('verified', []))
        validation_data['verified_records'] = audit_records.get('verified', [])
        validation_data['missing_records'] = audit_records.get('missing', [])
        
        verified_count = len(audit_records.get('verified', []))
        missing_count = len(audit_records.get('missing', []))
        
        print(f"   已验证记录: {verified_count} 个")
        print(f"   缺失记录: {missing_count} 个")
        
        if missing_count > 0:
            print(f"   ⚠️  发现缺失审计记录!")
            for missing in audit_records.get('missing', [])[:3]:
                print(f"     - {missing.get('file_path', '未知')}")
            if missing_count > 3:
                print(f"     ... 还有 {missing_count - 3} 个缺失记录")
        
        # 4. 检查CHANGELOG记录
        print(f"\n4. 📝 验证CHANGELOG记录")
        changelog_records = self._verify_changelog_records(window_start, file_changes)
        
        validation_data['changelog_records_count'] = len(changelog_records.get('verified', []))
        validation_data['changelog_missing_count'] = len(changelog_records.get('missing', []))
        
        changelog_verified = len(changelog_records.get('verified', []))
        changelog_missing = len(changelog_records.get('missing', []))
        
        print(f"   CHANGELOG已验证: {changelog_verified} 个")
        print(f"   CHANGELOG缺失: {changelog_missing} 个")
        
        # 5. 计算验证分数
        print(f"\n5. 📊 计算验证分数")
        score_result = self._calculate_validation_score(
            file_changes, 
            audit_records, 
            changelog_records
        )
        
        validation_data.update(score_result)
        validation_data['overall_score'] = score_result.get('overall_score', 0)
        
        print(f"   文件一致性分数: {score_result.get('file_consistency_score', 0)}/100")
        print(f"   审计完整性分数: {score_result.get('audit_completeness_score', 0)}/100")
        print(f"   CHANGELOG完整性分数: {score_result.get('changelog_completeness_score', 0)}/100")
        print(f"   综合验证分数: {validation_data['overall_score']}/100")
        
        # 6. 确定验证状态
        print(f"\n6. 🎯 确定验证状态")
        status_result = self._determine_validation_status(validation_data)
        validation_data['validation_status'] = status_result.get('status', 'unknown')
        validation_data['status_explanation'] = status_result.get('explanation', '')
        
        status_emoji = {
            'excellent': '✅',
            'good': '👍',
            'fair': '⚠️',
            'poor': '❌',
            'very_poor': '🔴'
        }.get(validation_data['validation_status'], '❓')
        
        print(f"   验证状态: {status_emoji} {validation_data['validation_status'].upper()}")
        print(f"   状态说明: {status_result.get('explanation', '')}")
        
        # 7. 自动修复缺失记录
        if auto_fix and self.config['auto_fix_missing_records']:
            print(f"\n7. 🔧 自动修复缺失记录")
            fix_result = self._auto_fix_missing_records(
                audit_records.get('missing', []),
                changelog_records.get('missing', [])
            )
            
            validation_data['auto_fix_result'] = fix_result
            
            if fix_result.get('records_fixed', 0) > 0:
                print(f"   已修复记录: {fix_result.get('records_fixed', 0)} 个")
                print(f"   修复详情: {fix_result.get('details', '')}")
            else:
                print(f"   无需修复或修复失败")
        
        # 8. 生成详细报告
        print(f"\n8. 📋 生成验证报告")
        report_path = self._generate_verification_report(validation_data)
        print(f"   报告位置: {report_path}")
        
        # 9. 记录验证结果
        log_path = self._log_validation_result(validation_data)
        print(f"   验证记录: {log_path}")
        
        print("\n" + "=" * 70)
        print(f"工作记录验证完成!")
        print("=" * 70)
        
        # 显示关键结论
        overall_score = validation_data['overall_score']
        print(f"\n📊 关键结论:")
        print(f"   综合分数: {overall_score}/100")
        print(f"   文件变更: {len(file_changes)} 个")
        print(f"   已验证记录: {verified_count} 个")
        print(f"   缺失记录: {missing_count} 个")
        
        if overall_score >= 80:
            print(f"✅ '都会记录'承诺: 有效执行，记录完整")
        elif overall_score >= 60:
            print(f"⚠️  '都会记录'承诺: 基本执行，部分缺失")
        elif overall_score >= 40:
            print(f"❌  '都会记录'承诺: 执行不佳，较多缺失")
        else:
            print(f"🔴  '都会记录'承诺: 执行失败，记录严重缺失")
        
        return validation_data
    
    def _scan_file_system_changes(self, window_start):
        """扫描文件系统变更"""
        file_changes = []
        
        try:
            # 定义要扫描的目录
            scan_dirs = [
                'core', 'utils', 'scripts', 'gui', 'engines',
                '金水谣数据', 'models', 'config', 'logs'
            ]
            
            for scan_dir in scan_dirs:
                dir_path = self.base_path / scan_dir
                if not dir_path.exists():
                    continue
                
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        # 只关注特定类型的文件
                        if not self._is_relevant_file(file):
                            continue
                        
                        file_path = Path(root) / file
                        try:
                            file_stat = file_path.stat()
                            mod_time = file_stat.st_mtime
                            
                            # 检查是否在时间窗口内修改
                            if mod_time >= window_start.timestamp():
                                file_info = {
                                    'file_path': str(file_path.relative_to(self.base_path)) 
                                    if str(file_path).startswith(str(self.base_path)) else str(file_path),
                                    'absolute_path': str(file_path),
                                    'modification_time': datetime.fromtimestamp(mod_time).isoformat(),
                                    'file_size': file_stat.st_size,
                                    'change_type': self._detect_change_type(file_path, mod_time),
                                    'file_hash': self._calculate_file_hash(file_path),
                                    'timestamp': datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
                                }
                                file_changes.append(file_info)
                        
                        except Exception as e:
                            continue
            
            # 按修改时间排序
            file_changes.sort(key=lambda x: x.get('modification_time', ''), reverse=True)
            
            return file_changes
        
        except Exception as e:
            print(f"扫描文件系统变更时出错: {e}")
            return []
    
    def _is_relevant_file(self, filename):
        """判断是否为相关文件"""
        relevant_extensions = [
            '.py', '.pyw', '.md', '.json', '.jsonl', '.yaml', '.yml',
            '.txt', '.log', '.html', '.css', '.js', '.ts', '.sql',
            '.sh', '.bat', '.ps1'
        ]
        
        # 排除一些临时文件
        excluded_patterns = [
            'temp_', 'tmp_', 'backup_', 'old_', 'test_',
            '__pycache__', '.pyc', '.log.', '.bak'
        ]
        
        filename_lower = filename.lower()
        
        # 检查排除模式
        for pattern in excluded_patterns:
            if pattern in filename_lower:
                return False
        
        # 检查扩展名
        for ext in relevant_extensions:
            if filename_lower.endswith(ext):
                return True
        
        # 检查无扩展名的配置文件
        if '.' not in filename and len(filename) < 20:
            return True
        
        return False
    
    def _detect_change_type(self, file_path, mod_time):
        """检测变更类型"""
        try:
            # 检查是否为新建文件
            create_time = file_path.stat().st_ctime
            time_diff = mod_time - create_time
            
            # 如果创建时间和修改时间接近，可能是新建文件
            if time_diff < 60:  # 60秒内
                return 'NEW'
            
            # 尝试从文件名和内容猜测变更类型
            file_content = ""
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read(2000)  # 读取前2000个字符
            except Exception:
                pass
            
            # 根据内容关键词判断
            content_lower = file_content.lower()
            
            if any(keyword in content_lower for keyword in ['fix', 'bug', 'error', '修复', '错误']):
                return 'FIX'
            elif any(keyword in content_lower for keyword in ['new', 'add', 'create', '新增', '添加']):
                return 'NEW'
            elif any(keyword in content_lower for keyword in ['optimize', 'improve', 'enhance', '优化', '改进']):
                return 'OPT'
            elif any(keyword in content_lower for keyword in ['remove', 'delete', '清理', '删除']):
                return 'DEL'
            
            return 'MODIFY'
        
        except Exception:
            return 'UNKNOWN'
    
    def _calculate_file_hash(self, file_path):
        """计算文件哈希"""
        try:
            with open(file_path, 'rb') as f:
                file_hash = hashlib.md5()
                for chunk in iter(lambda: f.read(4096), b''):
                    file_hash.update(chunk)
                return file_hash.hexdigest()
        except Exception:
            return "unknown"
    
    def _verify_audit_log_records(self, window_start, file_changes):
        """验证审计日志记录"""
        result = {
            'verified': [],
            'missing': [],
            'partial': [],
            'errors': []
        }
        
        try:
            if not self.audit_log_path.exists():
                result['errors'].append("审计日志文件不存在")
                return result
            
            # 读取审计日志
            audit_entries = []
            with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        entry = json.loads(line)
                        audit_entries.append(entry)
                    except json.JSONDecodeError:
                        result['errors'].append(f"JSON解析错误: {line[:50]}...")
                        continue
            
            # 筛选时间窗口内的记录
            window_entries = []
            for entry in audit_entries:
                timestamp = entry.get('ts') or entry.get('timestamp')
                if not timestamp:
                    continue
                
                try:
                    entry_time = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                    if entry_time >= window_start:
                        window_entries.append(entry)
                except Exception:
                    continue
            
            # 匹配文件变更与审计记录
            verified_files = set()
            
            for file_change in file_changes:
                file_path = file_change.get('file_path', '')
                change_time = file_change.get('timestamp', '')
                
                matched = False
                match_details = None
                
                for audit_entry in window_entries:
                    # 尝试匹配文件路径
                    entry_files = audit_entry.get('files_changed', [])
                    if isinstance(entry_files, list):
                        for ef in entry_files:
                            if file_path in ef or file_path == ef:
                                matched = True
                                match_details = {
                                    'audit_line': audit_entry,
                                    'match_type': 'exact_file'
                                }
                                break
                    
                    # 尝试匹配文件路径字符串
                    if not matched and audit_entry.get('file'):
                        if file_path in audit_entry['file'] or file_path == audit_entry['file']:
                            matched = True
                            match_details = {
                                'audit_line': audit_entry,
                                'match_type': 'file_field'
                            }
                    
                    if matched:
                        break
                
                if matched:
                    result['verified'].append({
                        'file_change': file_change,
                        'audit_record': match_details['audit_line'],
                        'match_type': match_details['match_type'],
                        'verification_status': 'verified'
                    })
                    verified_files.add(file_path)
                else:
                    result['missing'].append({
                        'file_change': file_change,
                        'verification_status': 'missing',
                        'missing_since': change_time
                    })
            
            result['statistics'] = {
                'total_file_changes': len(file_changes),
                'verified_changes': len(result['verified']),
                'missing_changes': len(result['missing']),
                'coverage_percentage': (len(result['verified']) / len(file_changes) * 100) if file_changes else 0
            }
        
        except Exception as e:
            result['errors'].append(f"验证审计日志时出错: {str(e)}")
        
        return result
    
    def _verify_changelog_records(self, window_start, file_changes):
        """验证CHANGELOG记录"""
        result = {
            'verified': [],
            'missing': [],
            'partial': [],
            'errors': []
        }
        
        try:
            if not self.changelog_path.exists():
                result['errors'].append("CHANGELOG文件不存在")
                return result
            
            # 读取CHANGELOG
            changelog_content = ""
            with open(self.changelog_path, 'r', encoding='utf-8') as f:
                changelog_content = f.read()
            
            # 分析CHANGELOG中的日期和条目
            changelog_entries = self._parse_changelog_entries(changelog_content)
            
            # 筛选时间窗口内的条目
            window_entries = []
            for entry in changelog_entries:
                entry_date = entry.get('date', '')
                if not entry_date:
                    continue
                
                try:
                    if '-' in entry_date:
                        date_parts = entry_date.split('-')
                        if len(date_parts) >= 3:
                            entry_time = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                            if entry_time >= window_start.replace(hour=0, minute=0, second=0, microsecond=0):
                                window_entries.append(entry)
                except Exception:
                    continue
            
            # 匹配文件变更与CHANGELOG条目
            for file_change in file_changes:
                file_path = file_change.get('file_path', '')
                file_name = Path(file_path).name
                
                matched = False
                match_details = None
                
                for changelog_entry in window_entries:
                    description = changelog_entry.get('description', '')
                    file_ref = changelog_entry.get('file', '')
                    
                    # 检查是否提到文件
                    if file_name in description or file_path in description or file_name in file_ref:
                        matched = True
                        match_details = {
                            'changelog_entry': changelog_entry,
                            'match_type': 'description_or_file'
                        }
                        break
                
                if matched:
                    result['verified'].append({
                        'file_change': file_change,
                        'changelog_entry': match_details['changelog_entry'],
                        'match_type': match_details['match_type'],
                        'verification_status': 'verified'
                    })
                else:
                    # 只对重要文件检查CHANGELOG记录
                    if self._is_important_file(file_path):
                        result['missing'].append({
                            'file_change': file_change,
                            'verification_status': 'missing',
                            'importance': 'high'
                        })
        
        except Exception as e:
            result['errors'].append(f"验证CHANGELOG时出错: {str(e)}")
        
        return result
    
    def _parse_changelog_entries(self, content):
        """解析CHANGELOG条目"""
        entries = []
        
        try:
            lines = content.split('\n')
            current_date = None
            current_type = None
            
            for line in lines:
                line = line.strip()
                
                # 解析日期标题
                if line.startswith('## ') and line.count('#') == 2:
                    current_date = line.replace('## ', '').strip()
                    current_type = None
                
                # 解析类型标题
                elif line.startswith('### ') and line.count('#') == 3:
                    current_type = line.replace('### ', '').strip()
                
                # 解析表格行
                elif line.startswith('|') and '|' in line and '----' not in line:
                    parts = [part.strip() for part in line.split('|')]
                    if len(parts) >= 3 and current_date:
                        entry = {
                            'date': current_date,
                            'type': current_type,
                            'file': parts[1] if len(parts) > 1 else '',
                            'description': parts[2] if len(parts) > 2 else '',
                            'full_line': line
                        }
                        entries.append(entry)
        
        except Exception as e:
            print(f"解析CHANGELOG时出错: {e}")
        
        return entries
    
    def _is_important_file(self, file_path):
        """判断是否为重要文件"""
        important_dirs = ['core/', 'utils/', 'scripts/', 'gui/', 'engines/']
        important_suffixes = ['.py', '.md', '.json']
        
        # 检查是否在重要目录
        if any(file_path.startswith(dir_prefix) for dir_prefix in important_dirs):
            return True
        
        # 检查文件后缀
        if any(file_path.endswith(suffix) for suffix in important_suffixes):
            return True
        
        return False
    
    def _calculate_validation_score(self, file_changes, audit_records, changelog_records):
        """计算验证分数"""
        scores = {
            'file_consistency_score': 0,
            'audit_completeness_score': 0,
            'changelog_completeness_score': 0,
            'overall_score': 0
        }
        
        try:
            total_files = len(file_changes)
            audit_verified = len(audit_records.get('verified', []))
            changelog_verified = len(changelog_records.get('verified', []))
            
            # 1. 文件一致性分数（如果无文件变更，则给予高分）
            if total_files == 0:
                scores['file_consistency_score'] = 95
            else:
                # 有文件变更情况
                scores['file_consistency_score'] = 70  # 基础分
            
            # 2. 审计完整性分数
            if total_files > 0:
                audit_coverage = (audit_verified / total_files) * 100
                scores['audit_completeness_score'] = min(100, audit_coverage)
            else:
                scores['audit_completeness_score'] = 90  # 无变更时给予高分
            
            # 3. CHANGELOG完整性分数
            important_files = [f for f in file_changes if self._is_important_file(f.get('file_path', ''))]
            important_count = len(important_files)
            
            if important_count > 0:
                # 只检查重要文件的CHANGELOG覆盖率
                scores['changelog_completeness_score'] = min(100, (changelog_verified / max(1, important_count)) * 100)
            else:
                scores['changelog_completeness_score'] = 85
            
            # 4. 综合分数（加权平均）
            weights = {
                'file_consistency': 0.3,
                'audit_completeness': 0.4,
                'changelog_completeness': 0.3
            }
            
            overall = (
                scores['file_consistency_score'] * weights['file_consistency'] +
                scores['audit_completeness_score'] * weights['audit_completeness'] +
                scores['changelog_completeness_score'] * weights['changelog_completeness']
            )
            
            scores['overall_score'] = round(overall, 1)
            
            scores['statistics'] = {
                'total_file_changes': total_files,
                'audit_verified': audit_verified,
                'audit_missing': len(audit_records.get('missing', [])),
                'changelog_verified': changelog_verified,
                'important_files': important_count
            }
        
        except Exception as e:
            scores['error'] = f"计算验证分数时出错: {str(e)}"
        
        return scores
    
    def _determine_validation_status(self, validation_data):
        """确定验证状态"""
        score = validation_data.get('overall_score', 0)
        
        if score >= 90:
            return {
                'status': 'excellent',
                'explanation': '记录非常完整，所有变更都有对应记录',
                'emoji': '✅'
            }
        elif score >= 80:
            return {
                'status': 'good',
                'explanation': '记录基本完整，大部分变更都有对应记录',
                'emoji': '👍'
            }
        elif score >= 65:
            return {
                'status': 'fair',
                'explanation': '记录存在缺失，需要关注某些变更没有记录',
                'emoji': '⚠️'
            }
        elif score >= 50:
            return {
                'status': 'poor',
                'explanation': '记录严重缺失，许多变更没有记录',
                'emoji': '❌'
            }
        else:
            return {
                'status': 'very_poor',
                'explanation': '记录系统可能存在问题，需要立即检查',
                'emoji': '🔴'
            }
    
    def _auto_fix_missing_records(self, missing_audit_records, missing_changelog_records):
        """自动修复缺失记录"""
        fix_result = {
            'audit_records_fixed': 0,
            'changelog_records_fixed': 0,
            'records_fixed': 0,
            'details': [],
            'errors': []
        }
        
        try:
            # 1. 修复缺失的审计日志记录
            for missing in missing_audit_records[:10]:  # 最多修复10个
                file_change = missing.get('file_change', {})
                file_path = file_change.get('file_path', '')
                change_time = file_change.get('timestamp', datetime.now().isoformat())
                
                if file_path and self._should_create_audit_record(file_path):
                    created = self._create_audit_record(file_change)
                    if created:
                        fix_result['audit_records_fixed'] += 1
                        fix_result['details'].append(f"审计记录: {file_path}")
            
            # 2. 修复缺失的CHANGELOG记录
            for missing in missing_changelog_records[:5]:  # 最多修复5个
                file_change = missing.get('file_change', {})
                file_path = file_change.get('file_path', '')
                
                if file_path and self._should_create_changelog_record(file_path):
                    created = self._create_changelog_record(file_change)
                    if created:
                        fix_result['changelog_records_fixed'] += 1
                        fix_result['details'].append(f"CHANGELOG记录: {file_path}")
            
            fix_result['records_fixed'] = fix_result['audit_records_fixed'] + fix_result['changelog_records_fixed']
        
        except Exception as e:
            fix_result['errors'].append(f"自动修复时出错: {str(e)}")
        
        return fix_result
    
    def _should_create_audit_record(self, file_path):
        """判断是否应创建审计记录"""
        # 排除一些不需要记录的文件
        excluded_patterns = [
            'temp_', 'tmp_', 'backup_', '.log', '__pycache__',
            '.pyc', '.log.', '.bak', 'test_'
        ]
        
        file_path_lower = file_path.lower()
        
        for pattern in excluded_patterns:
            if pattern in file_path_lower:
                return False
        
        # 只对重要文件创建记录
        if self._is_important_file(file_path):
            return True
        
        return False
    
    def _should_create_changelog_record(self, file_path):
        """判断是否应创建CHANGELOG记录"""
        # CHANGELOG只记录重要代码文件
        important_dirs = ['core/', 'utils/', 'scripts/', 'gui/', 'engines/']
        
        for dir_prefix in important_dirs:
            if file_path.startswith(dir_prefix) and file_path.endswith('.py'):
                return True
        
        return False
    
    def _create_audit_record(self, file_change):
        """创建审计记录"""
        try:
            file_path = file_change.get('file_path', '')
            change_type = file_change.get('change_type', 'MODIFY')
            
            audit_entry = {
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': change_type,
                'file': file_path,
                'summary': f"自动补全的变更记录: {file_path}",
                'detail': f"系统检测到文件变更，自动生成的审计记录。更改时间: {file_change.get('timestamp', '未知')}",
                'auto_generated': True,
                'verification_triggered': True
            }
            
            # 追加到审计日志
            with open(self.audit_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(audit_entry, ensure_ascii=False) + '\n')
            
            return True
        
        except Exception:
            return False
    
    def _create_changelog_record(self, file_change):
        """创建CHANGELOG记录"""
        try:
            current_date = datetime.now().strftime('%Y-%m-%d')
            file_path = file_change.get('file_path', '')
            change_type = file_change.get('change_type', 'MODIFY')
            
            # 简单的CHANGELOG条目
            changelog_entry = f"| `{file_path}` | 系统自动补全的变更记录 ({change_type}) | [#auto](自动生成) |\n"
            
            # 读取现有的CHANGELOG
            with open(self.changelog_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 找到今天日期的位置，如果没有则创建
            insert_index = 0
            found_date = False
            
            for i, line in enumerate(lines):
                if line.strip() == f'## {current_date}':
                    found_date = True
                    # 找到今天的第一个表格行
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip().startswith('|') and '----' not in lines[j]:
                            insert_index = j
                            break
                    if insert_index == 0:
                        insert_index = len(lines)
                    break
            
            if not found_date:
                # 添加新的日期部分
                new_section = [
                    f'\n## {current_date}\n',
                    f'\n### 🔄 系统自动记录\n',
                    '\n| 文件 | 变更说明 | 审计日志引用 |\n',
                    '|------|----------|--------------|\n',
                    changelog_entry,
                    '\n---\n'
                ]
                lines.extend(new_section)
            else:
                # 在表格中插入
                lines.insert(insert_index, changelog_entry)
            
            # 写回文件
            with open(self.changelog_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            return True
        
        except Exception as e:
            print(f"创建CHANGELOG记录时出错: {e}")
            return False
    
    def _generate_verification_report(self, validation_data):
        """生成验证报告"""
        try:
            current_time = datetime.now()
            
            report_content = [
                "# 工作记录验证报告",
                f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"验证窗口: {validation_data.get('verify_window_start', '未知')} 到 {validation_data.get('verify_window_end', '未知')}",
                "",
                "## 📊 验证摘要",
                f"- **综合分数**: **{validation_data.get('overall_score', 0)}/100**",
                f"- **验证状态**: {validation_data.get('validation_status', '未知').upper()}",
                f"- **状态说明**: {validation_data.get('status_explanation', '')}",
                f"- **文件变更数量**: {validation_data.get('file_changes_count', 0)}",
                f"- **审计记录验证**: {validation_data.get('audit_records_count', 0)} 个",
                f"- **缺失审计记录**: {len(validation_data.get('missing_records', []))} 个",
                f"- **CHANGELOG验证**: {validation_data.get('changelog_records_count', 0)} 个",
                "",
                "## 📈 详细分数",
                f"- **文件一致性**: {validation_data.get('file_consistency_score', 0)}/100",
                f"- **审计完整性**: {validation_data.get('audit_completeness_score', 0)}/100",
                f"- **CHANGELOG完整性**: {validation_data.get('changelog_completeness_score', 0)}/100",
                ""
            ]
            
            # 文件变更详情
            if validation_data.get('found_changes'):
                report_content.append("## 📁 发现的文件变更")
                
                for i, change in enumerate(validation_data['found_changes'][:10]):
                    file_path = change.get('file_path', '未知')
                    change_type = change.get('change_type', '未知')
                    timestamp = change.get('timestamp', '未知')
                    
                    is_verified = any(r.get('file_change', {}).get('file_path') == file_path 
                                    for r in validation_data.get('verified_records', []))
                    
                    status_emoji = '✅' if is_verified else '❌'
                    
                    report_content.append(f"{i+1}. **{file_path}**")
                    report_content.append(f"   - 类型: {change_type}")
                    report_content.append(f"   - 时间: {timestamp}")
                    report_content.append(f"   - 记录状态: {status_emoji} {'已验证' if is_verified else '缺失'}")
                
                if len(validation_data['found_changes']) > 10:
                    report_content.append(f"... 还有 {len(validation_data['found_changes']) - 10} 个文件变更")
                
                report_content.append("")
            
            # 缺失记录详情
            if validation_data.get('missing_records'):
                report_content.append("## ⚠️  缺失记录详情")
                
                for i, missing in enumerate(validation_data['missing_records'][:10]):
                    file_change = missing.get('file_change', {})
                    file_path = file_change.get('file_path', '未知')
                    
                    report_content.append(f"{i+1}. **{file_path}**")
                    report_content.append(f"   - 变更时间: {file_change.get('timestamp', '未知')}")
                
                report_content.append("")
            
            # 验证承诺评估
            report_content.append("## 🏆 '都会记录'承诺验证")
            
            overall_score = validation_data['overall_score']
            
            if overall_score >= 90:
                report_content.append("### ✅ 承诺完全兑现")
                report_content.append("系统验证表明，所有文件变更都有对应的审计记录和CHANGELOG记录。")
                report_content.append("'都会记录'承诺得到了有效执行。")
            elif overall_score >= 80:
                report_content.append("### 👍 承诺基本兑现")
                report_content.append("大多数文件变更都有记录，只有少量缺失。")
                report_content.append("承诺得到了良好的执行。")
            elif overall_score >= 65:
                report_content.append("### ⚠️  承诺部分兑现")
                report_content.append("存在一定数量的缺失记录，需要关注。")
                report_content.append("承诺执行需要改进。")
            elif overall_score >= 50:
                report_content.append("### ❌ 承诺执行不佳")
                report_content.append("有较多缺失记录，'都会记录'承诺未能有效执行。")
                report_content.append("需要立即采取措施改进记录系统。")
            else:
                report_content.append("### 🔴 承诺执行失败")
                report_content.append("记录系统存在严重问题，'都会记录'承诺未能兑现。")
                report_content.append("需要紧急修复记录系统。")
            
            # 建议
            report_content.append("")
            report_content.append("## 💡 建议")
            
            if validation_data.get('records_fixed', 0) > 0:
                report_content.append(f"已自动修复 {validation_data.get('records_fixed', 0)} 个记录")
                report_content.append("建议:")
                report_content.append("1. **审查自动生成的记录** - 确保它们准确反映了变更")
                report_content.append("2. **完善缺失记录的描述** - 添加更多详细信息")
            elif validation_data.get('missing_records'):
                report_content.append(f"发现 {len(validation_data.get('missing_records', []))} 个缺失记录")
                report_content.append("建议:")
                report_content.append("1. **手动补充缺失记录** - 运行补全工具")
                report_content.append("2. **改进变更流程** - 确保每次修改后立即记录")
            else:
                report_content.append("✅ 所有变更都有记录")
                report_content.append("建议:")
                report_content.append("1. **继续保持良好实践** - 持续按照当前流程操作")
                report_content.append("2. **定期运行验证** - 确保记录质量")
            
            # 写入报告
            with open(self.verification_report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_content))
            
            return self.verification_report_path
            
        except Exception as e:
            print(f"生成验证报告时出错: {e}")
            return None
    
    def _log_validation_result(self, validation_data):
        """记录验证结果到日志"""
        try:
            log_entry = {
                'timestamp': validation_data.get('timestamp'),
                'overall_score': validation_data.get('overall_score'),
                'validation_status': validation_data.get('validation_status'),
                'file_changes_count': validation_data.get('file_changes_count', 0),
                'audit_records_count': validation_data.get('audit_records_count', 0),
                'missing_records_count': len(validation_data.get('missing_records', [])),
                'promise_fulfilled': validation_data.get('overall_score', 0) >= 75
            }
            
            with open(self.validation_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            return self.validation_log_path
        
        except Exception as e:
            print(f"记录验证结果时出错: {e}")
            return None

def main():
    """主函数"""
    import sys
    
    validator = WorkRecordValidator()
    
    auto_fix = len(sys.argv) > 1 and sys.argv[1] == '--no-fix'
    
    print("工作记录验证系统")
    print("验证'都会记录'承诺是否有效执行")
    print("")
    
    result = validator.run_work_validation(auto_fix=not auto_fix)
    
    # 根据验证结果返回状态码
    score = result.get('overall_score', 0)
    
    if score >= 80:
        print("\n✅ 验证通过: '都会记录'承诺有效执行")
        sys.exit(0)
    elif score >= 65:
        print("\n⚠️  验证警告: 承诺执行存在不足")
        sys.exit(1)
    else:
        print("\n❌ 验证失败: 承诺未能有效执行")
        sys.exit(2)

if __name__ == "__main__":
    main()