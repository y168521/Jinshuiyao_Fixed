#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化变更记录检查机制
用途：定期检查变更记录系统的健康状态，防止问题反复出现
"""

import json
import re
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

class AuditSystemMonitor:
    """变更记录系统监控器"""
    
    def __init__(self, base_path=None):
        """初始化监控器"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 关键文件路径
        self.audit_log_path = self.base_path / "金水谣数据" / "log" / "change_audit.logl"
        self.backup_audit_path = self.base_path / "金水谣数据" / "log" / "backup_audit.logl"
        self.changelog_path = self.base_path / "CHANGELOG.md"
        self.health_log_path = self.base_path / "金水谣数据" / "log" / "health_monitor_log.jsonl"
        self.alert_log_path = self.base_path / "金水谣数据" / "log" / "system_alerts.md"
        
        # 检查阈值配置
        self.config = {
            'max_duplicate_backups': 5,           # 最大重复备份数
            'min_changelog_coverage': 50,         # 最低CHANGELOG覆盖率(%)
            'max_format_errors_percent': 5,       # 最大格式错误率(%)
            'max_missing_timestamps': 10,         # 最大缺失时间戳数
            'backup_frequency_threshold': 5,      # 备份频率阈值(分钟)
            'alert_severity_level': 'MEDIUM',     # 告警严重级别
        }
        
        # 当前检查结果
        self.check_results = {
            'timestamp': datetime.now().isoformat(),
            'overall_score': 0,
            'checks_passed': 0,
            'checks_failed': 0,
            'checks_warning': 0,
            'detailed_findings': [],
            'alerts': [],
            'recommendations': []
        }
    
    def run_all_checks(self):
        """运行所有检查"""
        print("=" * 70)
        print("变更记录系统自动化检查")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        print("\n运行检查中...\n")
        
        # 1. 文件存在性检查
        self._check_file_existence()
        
        # 2. 数据格式检查
        self._check_data_formats()
        
        # 3. 完整性检查
        self._check_integrity_issues()
        
        # 4. CHANGELOG覆盖率检查
        self._check_changelog_coverage()
        
        # 5. 备份系统健康检查
        self._check_backup_health()
        
        # 6. 性能检查
        self._check_performance_metrics()
        
        # 7. 风险分析
        self._run_risk_analysis()
        
        # 总结和报告
        self._generate_summary_report()
        
        # 记录检查结果
        self._log_health_check()
        
        # 如有严重问题则生成告警
        if self.check_results['checks_failed'] > 0:
            self._generate_alerts()
        
        print("=" * 70)
        print("自动化检查完成")
        print("=" * 70)
        
        return self.check_results
    
    def _check_file_existence(self):
        """检查关键文件是否存在"""
        print("🔍 检查关键文件...")
        
        critical_files = [
            (self.audit_log_path, "主审计日志"),
            (self.changelog_path, "变更日志"),
            (self.health_log_path, "健康监控日志")
        ]
        
        all_exist = True
        for file_path, description in critical_files:
            if file_path.exists():
                self._add_check_result('PASS', f"文件存在: {description}", 10)
            else:
                self._add_check_result('FAIL', f"关键文件缺失: {description}", -30)
                all_exist = False
        
        if all_exist:
            self._add_check_result('PASS', "所有关键文件均存在", 20)
    
    def _check_data_formats(self):
        """检查数据格式问题"""
        print("🔍 检查数据格式...")
        
        total_errors = 0
        total_lines = 0
        
        # 检查主审计日志格式
        if self.audit_log_path.exists():
            try:
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    total_lines = len(lines)
                    
                    format_errors = 0
                    missing_timestamps = 0
                    
                    for line_num, line in enumerate(lines, 1):
                        line = line.strip()
                        if not line:
                            continue
                        
                        # 检查JSON格式
                        try:
                            entry = json.loads(line)
                            
                            # 检查时间戳
                            if not entry.get('ts') and not entry.get('timestamp'):
                                missing_timestamps += 1
                            
                            # 检查类型字段
                            change_type = entry.get('type', '').upper()
                            valid_types = ['FIX', 'NEW', 'OPT', 'DEL', 'BACKUP', 'ROLLBACK']
                            if change_type and change_type not in valid_types:
                                format_errors += 1
                        
                        except json.JSONDecodeError:
                            format_errors += 1
                
                # 计算错误率
                if total_lines > 0:
                    format_error_rate = (format_errors / total_lines) * 100
                    missing_timestamp_rate = (missing_timestamps / total_lines) * 100
                    
                    # 评估
                    if format_errors == 0:
                        self._add_check_result('PASS', f"审计日志JSON格式完好 ({total_lines}行)", 15)
                    else:
                        self._add_check_result('FAIL', f"审计日志JSON格式错误: {format_errors}处", -20)
                    
                    if missing_timestamps == 0:
                        self._add_check_result('PASS', f"审计日志时间戳完整 ({total_lines}行)", 10)
                    else:
                        self._add_check_result('FAIL', f"审计日志缺失时间戳: {missing_timestamps}处", -15)
                
            except Exception as e:
                self._add_check_result('FAIL', f"读取审计日志出错: {str(e)}", -25)
    
    def _check_integrity_issues(self):
        """检查数据完整性问题"""
        print("🔍 检查数据完整性...")
        
        # 检查重复记录
        duplicate_count = self._check_for_duplicates()
        
        if duplicate_count > 0:
            self._add_check_result('WARNING', f"检测到重复记录: {duplicate_count}处", -5)
        else:
            self._add_check_result('PASS', "审计记录无重复", 10)
        
        # 检查时间顺序
        time_order_issues = self._check_time_order()
        
        if time_order_issues > 0:
            self._add_check_result('WARNING', f"时间顺序问题: {time_order_issues}处", -3)
        else:
            self._add_check_result('PASS', "记录时间顺序正确", 8)
    
    def _check_changelog_coverage(self):
        """检查CHANGELOG覆盖率"""
        print("🔍 检查CHANGELOG覆盖率...")
        
        try:
            # 简单的覆盖率估算
            if self.audit_log_path.exists() and self.changelog_path.exists():
                
                # 统计审计日志记录数
                audit_count = 0
                if self.audit_log_path.exists():
                    with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                        audit_count = sum(1 for line in f if line.strip())
                
                # 统计CHANGELOG条目数 (估算)
                changelog_count = 0
                with open(self.changelog_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 通过表格行数估算
                    changelog_count = content.count('| `') // 2
                
                if audit_count > 0 and changelog_count > 0:
                    # 使用简化的覆盖率计算方法
                    coverage_ratio = min(changelog_count * 5 / audit_count * 100, 100)  # 假设每个changelog条目对应5个审计记录
                    
                    if coverage_ratio >= self.config['min_changelog_coverage']:
                        self._add_check_result('PASS', 
                            f"CHANGELOG覆盖率良好 (~{coverage_ratio:.1f}%)", 
                            25)
                    
                    elif coverage_ratio >= 30:
                        self._add_check_result('WARNING', 
                            f"CHANGELOG覆盖率中等 (~{coverage_ratio:.1f}%)", 
                            5)
                    
                    else:
                        self._add_check_result('FAIL', 
                            f"CHANGELOG覆盖率过低 (~{coverage_ratio:.1f}%)", 
                            -20)
                        
                        # 添加建议
                        self.check_results['recommendations'].append(
                            f"运行 `python scripts/supplement_changelog.py` 补充缺失的CHANGELOG引用"
                        )
                
            else:
                self._add_check_result('FAIL', "无法计算CHANGELOG覆盖率", -10)
        
        except Exception as e:
            self._add_check_result('FAIL', f"检查CHANGELOG覆盖率时出错: {str(e)}", -15)
    
    def _check_backup_health(self):
        """检查备份系统健康状态"""
        print("🔍 检查备份系统...")
        
        try:
            if self.backup_audit_path.exists():
                # 统计备份记录
                backup_count = 0
                recent_backups = 0
                
                with open(self.backup_audit_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        backup_count += 1
                        
                        try:
                            entry = json.loads(line)
                            timestamp = entry.get('ts') or entry.get('timestamp')
                            if timestamp:
                                try:
                                    log_time = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                                    one_hour_ago = datetime.now() - timedelta(hours=1)
                                    if log_time > one_hour_ago:
                                        recent_backups += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass
                
                if backup_count > 0:
                    self._add_check_result('PASS', 
                        f"备份系统活跃 ({backup_count}条记录, 最近1小时{recent_backups}条)", 
                        15)
                else:
                    self._add_check_result('WARNING', "备份系统无记录", -5)
            
            else:
                self._add_check_result('WARNING', "备份审计日志不存在", -5)
        
        except Exception as e:
            self._add_check_result('FAIL', f"检查备份系统时出错: {str(e)}", -10)
    
    def _check_performance_metrics(self):
        """检查性能指标"""
        print("🔍 检查性能指标...")
        
        # 检查文件大小
        try:
            if self.audit_log_path.exists():
                file_size_mb = os.path.getsize(self.audit_log_path) / (1024 * 1024)
                
                if file_size_mb < 10:
                    self._add_check_result('PASS', 
                        f"审计日志大小正常 ({file_size_mb:.1f}MB)", 
                        8)
                elif file_size_mb < 50:
                    self._add_check_result('WARNING', 
                        f"审计日志较大 ({file_size_mb:.1f}MB)", 
                        2)
                else:
                    self._add_check_result('WARNING', 
                        f"审计日志过大 ({file_size_mb:.1f}MB)", 
                        -5)
                    
                    self.check_results['recommendations'].append(
                        f"考虑归档或清理审计日志，当前大小 {file_size_mb:.1f}MB"
                    )
        
        except Exception as e:
            self._add_check_result('FAIL', f"检查性能指标时出错: {str(e)}", -10)
    
    def _run_risk_analysis(self):
        """运行风险分析"""
        print("🔍 进行风险分析...")
        
        # 计算整体风险分数
        risk_factors = 0
        risk_details = []
        
        # 检查是否有近期的FIX类型记录 (潜在问题指标)
        recent_fixes = self._count_recent_fixes()
        if recent_fixes > 10:
            risk_factors += 2
            risk_details.append(f"近期有 {recent_fixes} 个修复记录，可能存在系统问题")
        
        # 检查备份频率是否异常
        backup_freq = self._check_backup_frequency()
        if backup_freq < self.config['backup_frequency_threshold']:
            risk_factors += 1
            risk_details.append(f"备份过于频繁 (平均间隔 {backup_freq:.1f} 分钟)")
        
        # 评估风险水平
        if risk_factors == 0:
            self._add_check_result('PASS', "风险分析: 低风险", 12)
        
        elif risk_factors <= 2:
            self._add_check_result('WARNING', f"风险分析: 中等风险 ({risk_factors}个风险因素)", 3)
            for detail in risk_details:
                self.check_results['recommendations'].append(f"⚠️ {detail}")
        
        else:
            self._add_check_result('FAIL', f"风险分析: 高风险 ({risk_factors}个风险因素)", -15)
            for detail in risk_details:
                self.check_results['alerts'].append(f"🚨 {detail}")
    
    def _check_for_duplicates(self):
        """检查重复记录"""
        try:
            if self.audit_log_path.exists():
                seen_hashes = set()
                duplicate_count = 0
                
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = json.loads(line)
                            # 创建简单哈希
                            hash_key = f"{entry.get('type')}_{entry.get('summary', '')[:50]}"
                            if hash_key in seen_hashes:
                                duplicate_count += 1
                            else:
                                seen_hashes.add(hash_key)
                        except Exception:
                            continue
                
                return duplicate_count
        
        except Exception:
            pass
        
        return 0
    
    def _check_time_order(self):
        """检查时间顺序问题"""
        try:
            if self.audit_log_path.exists():
                times = []
                
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = json.loads(line)
                            timestamp = entry.get('ts') or entry.get('timestamp')
                            if timestamp:
                                try:
                                    dt = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                                    times.append(dt)
                                except Exception:
                                    pass
                        except Exception:
                            continue
                
                # 检查时间是否大体有序
                if len(times) > 1:
                    issues = 0
                    for i in range(1, len(times)):
                        if times[i] < times[i-1]:
                            time_diff = (times[i-1] - times[i]).total_seconds() / 60  # 分钟
                            if time_diff > 10:  # 超过10分钟的时间倒序认为是问题
                                issues += 1
                    
                    return issues
        
        except Exception:
            pass
        
        return 0
    
    def _count_recent_fixes(self):
        """统计近期修复记录"""
        try:
            if self.audit_log_path.exists():
                fix_count = 0
                one_day_ago = datetime.now() - timedelta(days=1)
                
                with open(self.audit_log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = json.loads(line)
                            if entry.get('type', '').upper() == 'FIX':
                                timestamp = entry.get('ts') or entry.get('timestamp')
                                if timestamp:
                                    try:
                                        log_time = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                                        if log_time > one_day_ago:
                                            fix_count += 1
                                    except Exception:
                                        pass
                        except Exception:
                            continue
                
                return fix_count
        
        except Exception:
            pass
        
        return 0
    
    def _check_backup_frequency(self):
        """检查备份频率"""
        try:
            if self.backup_audit_path.exists():
                timestamps = []
                
                with open(self.backup_audit_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            entry = json.loads(line)
                            timestamp = entry.get('ts') or entry.get('timestamp')
                            if timestamp:
                                try:
                                    dt = datetime.fromisoformat(timestamp.replace(' ', 'T'))
                                    timestamps.append(dt)
                                except Exception:
                                    pass
                        except Exception:
                            continue
                
                if len(timestamps) > 1:
                    timestamps.sort()
                    total_minutes = 0
                    for i in range(1, len(timestamps)):
                        diff = (timestamps[i] - timestamps[i-1]).total_seconds() / 60
                        total_minutes += diff
                    
                    avg_interval = total_minutes / (len(timestamps) - 1)
                    return avg_interval
        
        except Exception:
            pass
        
        return 0
    
    def _add_check_result(self, status, message, score_impact):
        """添加检查结果"""
        status_symbols = {
            'PASS': '✅',
            'WARNING': '⚠️',
            'FAIL': '❌'
        }
        
        result = {
            'status': status,
            'message': message,
            'score_impact': score_impact,
            'symbol': status_symbols.get(status, '❓')
        }
        
        self.check_results['detailed_findings'].append(result)
        
        if status == 'PASS':
            self.check_results['checks_passed'] += 1
        elif status == 'WARNING':
            self.check_results['checks_warning'] += 1
        else:
            self.check_results['checks_failed'] += 1
        
        self.check_results['overall_score'] += score_impact
        self.check_results['overall_score'] = max(0, min(100, self.check_results['overall_score']))
    
    def _generate_summary_report(self):
        """生成总结报告"""
        print("\n" + "=" * 70)
        print("检查结果总结")
        print("=" * 70)
        
        # 展示详细检查结果
        for finding in self.check_results['detailed_findings']:
            print(f"{finding['symbol']} {finding['message']}")
        
        print("\n" + "=" * 70)
        
        # 计算整体状态
        summary_score = self.check_results['overall_score']
        
        if summary_score >= 80:
            status = "✅ 优秀"
            color_start, color_end = "\033[92m", "\033[0m"  # 绿色
        elif summary_score >= 60:
            status = "⚠️ 中等"
            color_start, color_end = "\033[93m", "\033[0m"  # 黄色
        else:
            status = "❌ 需要关注"
            color_start, color_end = "\033[91m", "\033[0m"  # 红色
        
        print(f"\n📊 综合评分: {color_start}{summary_score:.1f}/100{color_end} {status}")
        print(f"✅ 通过: {self.check_results['checks_passed']} 项")
        print(f"⚠️ 警告: {self.check_results['checks_warning']} 项")
        print(f"❌ 失败: {self.check_results['checks_failed']} 项")
        
        # 显示建议
        if self.check_results['recommendations']:
            print("\n💡 改进建议:")
            for rec in self.check_results['recommendations'][:3]:
                print(f"  • {rec}")
        
        # 显示告警
        if self.check_results['alerts']:
            print("\n🚨 系统告警:")
            for alert in self.check_results['alerts'][:3]:
                print(f"  • {alert}")
    
    def _log_health_check(self):
        """记录健康检查结果到日志"""
        try:
            log_entry = {
                'timestamp': self.check_results['timestamp'],
                'overall_score': self.check_results['overall_score'],
                'checks_passed': self.check_results['checks_passed'],
                'checks_failed': self.check_results['checks_failed'],
                'checks_warning': self.check_results['checks_warning'],
                'summary': self._get_summary_text()
            }
            
            # 创建目录（如果不存在）
            self.health_log_path.parent.mkdir(exist_ok=True, parents=True)
            
            # 追加到健康日志
            with open(self.health_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        except Exception as e:
            print(f"记录健康检查结果时出错: {e}")
    
    def _generate_alerts(self):
        """生成系统告警"""
        try:
            if self.check_results['checks_failed'] > 0:
                
                alert_content = [
                    "# 变更记录系统告警",
                    f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"严重级别: {self.config['alert_severity_level']}",
                    "",
                    "## 📊 检查结果",
                    f"- 综合评分: {self.check_results['overall_score']:.1f}/100",
                    f"- 失败检查: {self.check_results['checks_failed']} 项",
                    f"- 警告检查: {self.check_results['checks_warning']} 项",
                    "",
                    "## 🚨 失败项目"
                ]
                
                # 添加失败的检查项目
                for finding in self.check_results['detailed_findings']:
                    if finding['status'] == 'FAIL':
                        alert_content.append(f"- {finding['message']}")
                
                # 添加建议
                if self.check_results['recommendations']:
                    alert_content.append("")
                    alert_content.append("## 💡 建议操作")
                    for rec in self.check_results['recommendations'][:5]:
                        alert_content.append(f"- {rec}")
                
                # 写入告警文件
                with open(self.alert_log_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(alert_content))
        
        except Exception as e:
            print(f"生成告警时出错: {e}")
    
    def _get_summary_text(self):
        """获取总结文本"""
        score = self.check_results['overall_score']
        
        if score >= 90:
            return "系统状态优秀，所有关键指标正常"
        elif score >= 70:
            return "系统状态良好，少数方面可优化"
        elif score >= 50:
            return "系统状态中等，建议处理警告项"
        elif score >= 30:
            return "系统状态需要关注，有多个问题需解决"
        else:
            return "系统状态严重，需要立即关注"

def main():
    """主函数"""
    import sys
    
    monitor = AuditSystemMonitor()
    results = monitor.run_all_checks()
    
    # 返回退出码（用于自动化脚本）
    if results['checks_failed'] > 0:
        sys.exit(1)
    elif results['checks_warning'] > 0:
        sys.exit(2)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()