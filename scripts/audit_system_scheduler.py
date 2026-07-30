#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变更记录系统自动化调度器
用途：定期自动运行系统健康检查，防止问题反复出现
"""

import subprocess
import time
import os
import sys
import ast
import json
from datetime import datetime, timedelta
from pathlib import Path


def _safe_parse_log_line(line):
    """安全解析审计日志行：优先 ast.literal_eval（不执行代码）；日志由 json.dumps 写出，
    布尔/None 为 true/false/null，ast 无法解析时回退到同样安全的 json.loads。
    两者均不执行任意代码，消除原先 eval() 的任意代码执行风险。"""
    s = line.strip()
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return json.loads(s)

class AuditSystemScheduler:
    """变更记录系统自动化调度器"""
    
    def __init__(self, base_path=None):
        """初始化调度器"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 日志路径
        self.scheduler_log_path = self.base_path / "金水谣数据" / "log" / "scheduler_log.jsonl"
        self.alerts_path = self.base_path / "金水谣数据" / "log" / "automated_alerts.md"
        
        # 配置
        self.config = {
            'check_interval_hours': 6,          # 检查间隔（小时）
            'notification_threshold': 60,       # 通知阈值（综合评分）
            'max_check_history': 100,           # 最大历史记录数
            'enable_email_alerts': False,       # 启用邮件告警
            'alert_recipients': [],             # 告警接收人
            'critical_errors_trigger_immediate': True,  # 严重错误立即触发
        }
        
        # 确保日志目录存在
        self.scheduler_log_path.parent.mkdir(exist_ok=True, parents=True)
    
    def run_scheduled_check(self):
        """运行计划检查"""
        print("=" * 70)
        print(f"变更记录系统自动化检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # 记录开始时间
        start_time = datetime.now()
        
        try:
            # 运行监控脚本
            monitor_script = self.base_path / "scripts" / "audit_system_monitor.py"
            cmd = [sys.executable, str(monitor_script)]
            
            print(f"执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.base_path)
            
            # 解析结果
            check_result = {
                'timestamp': start_time.isoformat(),
                'command': ' '.join(cmd),
                'stdout': result.stdout,
                'stderr': result.stderr,
                'return_code': result.returncode,
                'execution_time_ms': int((datetime.now() - start_time).total_seconds() * 1000)
            }
            
            # 分析输出获取综合评分
            overall_score = self._extract_score_from_output(result.stdout)
            
            # 记录结果
            check_result['overall_score'] = overall_score
            
            # 记录到日志
            self._log_check_result(check_result)
            
            # 判断是否需要发送告警
            if overall_score < self.config['notification_threshold']:
                self._generate_alert(check_result, overall_score)
                print(f"⚠️  系统评分较低 ({overall_score:.1f}/100)，已生成告警")
            
            # 打印摘要
            print(f"\n📊 检查完成")
            print(f"   状态码: {result.returncode}")
            print(f"   综合评分: {overall_score:.1f}/100")
            print(f"   执行时间: {check_result['execution_time_ms']}ms")
            
            if result.returncode == 0:
                print("✅ 检查通过，系统状态良好")
            elif result.returncode == 1:
                print("❌ 检查失败，系统存在严重问题")
            elif result.returncode == 2:
                print("⚠️  检查有警告项，需要关注")
            
            return check_result
        
        except Exception as e:
            error_result = {
                'timestamp': start_time.isoformat(),
                'error': str(e),
                'execution_time_ms': int((datetime.now() - start_time).total_seconds() * 1000)
            }
            
            # 记录错误
            self._log_check_result(error_result)
            
            # 生成错误告警
            self._generate_error_alert(error_result)
            
            print(f"❌ 自动化检查执行出错: {e}")
            return error_result
    
    def _extract_score_from_output(self, output):
        """从输出中提取综合评分"""
        import re
        
        # 寻找综合评分模式
        score_patterns = [
            r'综合评分[:\s]+([\d.]+)/100',
            r'整体评分[:\s]+([\d.]+)/100',
            r'score[:\s]+([\d.]+)/100',
            r'overall_score[:\s]+([\d.]+)'
        ]
        
        for pattern in score_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        # 如果没有找到明确的评分，尝试根据返回码估算
        return 75.0  # 默认中等评分
    
    def _log_check_result(self, result):
        """记录检查结果到日志"""
        try:
            with open(self.scheduler_log_path, 'a', encoding='utf-8') as f:
                import json
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
            
            # 保持日志大小
            self._trim_log_file()
        
        except Exception as e:
            print(f"记录日志时出错: {e}")
    
    def _trim_log_file(self):
        """修剪日志文件，保持合理大小"""
        try:
            if self.scheduler_log_path.exists():
                with open(self.scheduler_log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                if len(lines) > self.config['max_check_history']:
                    # 只保留最新的记录
                    with open(self.scheduler_log_path, 'w', encoding='utf-8') as f:
                        f.writelines(lines[-self.config['max_check_history']:])
        
        except Exception as e:
            print(f"修剪日志文件时出错: {e}")
    
    def _generate_alert(self, check_result, score):
        """生成系统告警"""
        try:
            current_time = datetime.now()
            
            alert_content = [
                "# 自动化系统检查告警",
                f"生成时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"严重级别: {'🚨 严重' if score < 50 else '⚠️  警告' if score < 70 else 'ℹ️  通知'}",
                "",
                "## 📊 检查结果摘要",
                f"- **综合评分**: {score:.1f}/100",
                f"- **检查时间**: {check_result['timestamp']}",
                f"- **执行状态**: {self._get_status_text(check_result['return_code'])}",
                f"- **执行耗时**: {check_result.get('execution_time_ms', 0)}ms",
                "",
                "## 🔍 详细输出"
            ]
            
            # 添加摘要输出
            stdout_lines = check_result.get('stdout', '').split('\n')
            summary_lines = []
            capturing = False
            
            for line in stdout_lines:
                if '检查结果总结' in line:
                    capturing = True
                elif capturing and '自动化检查完成' in line:
                    break
                
                if capturing and line and not line.startswith('==='):
                    summary_lines.append(line)
            
            if summary_lines:
                alert_content.append("")
                alert_content.extend(summary_lines)
            
            # 如果有错误输出
            stderr = check_result.get('stderr', '')
            if stderr:
                alert_content.append("")
                alert_content.append("## 🔴 错误输出")
                alert_content.append("```")
                alert_content.append(stderr[:1000])  # 限制长度
                alert_content.append("```")
            
            # 建议操作
            alert_content.append("")
            alert_content.append("## 💡 建议操作")
            
            if score < 50:
                alert_content.append("1. **立即检查系统** - 存在严重问题需要立即处理")
                alert_content.append("2. **运行详细诊断** - 执行 `python scripts/audit_system_monitor.py`")
                alert_content.append("3. **审查变更记录** - 检查最近的FIX和ERROR类型记录")
            elif score < 70:
                alert_content.append("1. **近期审查** - 建议24小时内检查系统问题")
                alert_content.append("2. **优化配置** - 运行 `python scripts/supplement_changelog.py` 补充缺失引用")
                alert_content.append("3. **清理重复** - 检查审计日志中的重复记录")
            else:
                alert_content.append("1. **持续监控** - 保持当前检查频率")
                alert_content.append("2. **定期优化** - 每周运行一次系统优化")
            
            alert_content.append("")
            alert_content.append("## 📈 历史评分趋势")
            alert_content.append("最近5次检查结果:")
            
            # 添加历史评分
            try:
                if self.scheduler_log_path.exists():
                    with open(self.scheduler_log_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    recent_results = []
                    for line in lines[-6:-1] if len(lines) >= 6 else lines:  # 最多5条
                        try:
                            entry = _safe_parse_log_line(line.strip())
                            if 'overall_score' in entry:
                                recent_results.append(entry)
                        except Exception:
                            continue
                    
                    if recent_results:
                        alert_content.append("```")
                        for entry in recent_results[-5:]:  # 显示最近5次
                            timestamp = entry.get('timestamp', '')
                            score_val = entry.get('overall_score', 0)
                            status = self._get_status_text(entry.get('return_code', 0))
                            
                            if timestamp:
                                # 格式化时间
                                try:
                                    dt = datetime.fromisoformat(timestamp)
                                    time_str = dt.strftime('%m-%d %H:%M')
                                except Exception:
                                    time_str = timestamp[:16]
                                
                                alert_content.append(f"{time_str} | {score_val:5.1f}/100 | {status}")
                        alert_content.append("```")
            
            except Exception as e:
                alert_content.append(f"(无法获取历史数据: {str(e)})")
            
            # 写入告警文件
            with open(self.alerts_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(alert_content))
            
            print(f"告警已生成: {self.alerts_path}")
        
        except Exception as e:
            print(f"生成告警时出错: {e}")
    
    def _generate_error_alert(self, error_result):
        """生成错误告警"""
        try:
            alert_content = [
                "# 自动化检查系统错误",
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"严重级别: 🔴 严重错误",
                "",
                "## 🔴 错误详情",
                f"错误信息: {error_result.get('error', '未知错误')}",
                f"发生时间: {error_result.get('timestamp', '未知')}",
                f"耗时: {error_result.get('execution_time_ms', 0)}ms",
                "",
                "## 🛠️ 修复建议",
                "1. **检查脚本路径** - 确保监控脚本存在: `scripts/audit_system_monitor.py`",
                "2. **检查Python环境** - 确保Python环境和依赖可用",
                "3. **检查权限** - 确保有足够的文件读写权限",
                "4. **手动运行测试** - 运行 `python scripts/audit_system_monitor.py` 查看具体错误",
                "",
                "请立即处理此错误，否则自动化检查将无法正常运行。"
            ]
            
            # 写入错误告警
            with open(self.alerts_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(alert_content))
        
        except Exception as e:
            print(f"生成错误告警时出错: {e}")
    
    def _get_status_text(self, return_code):
        """获取状态文本"""
        status_map = {
            0: "✅ 通过",
            1: "❌ 失败",
            2: "⚠️  警告",
            -1: "🔴 错误",
            None: "❓ 未知"
        }
        return status_map.get(return_code, f"未知 ({return_code})")
    
    def run_continuous_monitoring(self):
        """运行持续监控（守护进程模式）"""
        print("=" * 70)
        print("启动变更记录系统持续监控")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"检查间隔: {self.config['check_interval_hours']} 小时")
        print("=" * 70)
        print("按 Ctrl+C 停止监控\n")
        
        check_count = 0
        
        try:
            while True:
                # 运行检查
                check_count += 1
                print(f"\n📋 执行第 {check_count} 次检查...")
                
                result = self.run_scheduled_check()
                
                # 计算下次检查时间
                next_check = datetime.now() + timedelta(hours=self.config['check_interval_hours'])
                print(f"\n⏰ 下一次检查: {next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # 等待下次检查
                wait_seconds = self.config['check_interval_hours'] * 3600
                print(f"等待 {self.config['check_interval_hours']} 小时...")
                
                # 分段等待，允许中断
                segment = 600  # 10分钟一个段
                for i in range(wait_seconds // segment):
                    try:
                        time.sleep(segment)
                        # 每10分钟打印一次等待状态
                        elapsed = (i + 1) * segment
                        print(f"等待中... 已等待 {elapsed//60} 分钟")
                    except KeyboardInterrupt:
                        print("\n🛑 用户中断监控")
                        return
        
        except KeyboardInterrupt:
            print("\n🛑 监控已停止")
        
        except Exception as e:
            print(f"\n❌ 监控出错: {e}")
    
    def generate_status_report(self):
        """生成状态报告"""
        print("=" * 70)
        print("变更记录系统状态报告")
        print(f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # 检查日志文件
        if not self.scheduler_log_path.exists():
            print("📭 无历史检查记录")
            return
        
        try:
            with open(self.scheduler_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if not lines:
                print("📭 历史记录为空")
                return
            
            # 解析历史记录
            history = []
            for line in lines[-20:]:  # 最近20条记录
                try:
                    entry = _safe_parse_log_line(line.strip())
                    history.append(entry)
                except Exception:
                    continue
            
            if not history:
                print("❌ 无法解析历史记录")
                return
            
            # 计算统计信息
            latest = history[-1]
            latest_score = latest.get('overall_score', 0)
            latest_time = latest.get('timestamp', '未知')
            
            scores = [entry.get('overall_score', 0) for entry in history if entry.get('overall_score')]
            average_score = sum(scores) / len(scores) if scores else 0
            max_score = max(scores) if scores else 0
            min_score = min(scores) if scores else 0
            
            # 成功/失败统计
            success_count = sum(1 for entry in history if entry.get('return_code') == 0)
            failure_count = sum(1 for entry in history if entry.get('return_code') == 1)
            warning_count = sum(1 for entry in history if entry.get('return_code') == 2)
            error_count = sum(1 for entry in history if entry.get('error'))
            
            total_count = len(history)
            
            # 打印报告
            print(f"\n📅 监控统计 (最近{total_count}次)")
            print(f"   最新检查: {latest_score:.1f}/100")
            print(f"   平均评分: {average_score:.1f}/100")
            print(f"   最高评分: {max_score:.1f}/100")
            print(f"   最低评分: {min_score:.1f}/100")
            
            print(f"\n📊 结果分布")
            print(f"   ✅ 成功: {success_count} 次 ({success_count/total_count*100:.1f}%)")
            print(f"   ⚠️  警告: {warning_count} 次 ({warning_count/total_count*100:.1f}%)")
            print(f"   ❌ 失败: {failure_count} 次 ({failure_count/total_count*100:.1f}%)")
            print(f"   🔴 错误: {error_count} 次 ({error_count/total_count*100:.1f}%)")
            
            # 趋势分析
            if len(scores) >= 5:
                recent_scores = scores[-5:]
                score_trend = sum(recent_scores[i] - recent_scores[i-1] for i in range(1, len(recent_scores))) / (len(recent_scores) - 1)
                
                print(f"\n📈 趋势分析")
                print(f"   短期趋势: {'↗️ 上升' if score_trend > 1 else '↘️ 下降' if score_trend < -1 else '➡️ 稳定'}")
                print(f"   最近5次得分: {', '.join(f'{s:.1f}' for s in recent_scores)}")
            
            # 建议
            print(f"\n💡 建议")
            if average_score < 60:
                print("   🚨 系统整体状况需要改进，建议立即进行优化")
            elif average_score < 80:
                print("   ⚠️  系统状况尚可，建议定期优化")
            else:
                print("   ✅ 系统状况良好，继续保持")
            
            # 最近告警
            if self.alerts_path.exists():
                try:
                    with open(self.alerts_path, 'r', encoding='utf-8') as f:
                        alert_content = f.read()
                    
                    if alert_content:
                        print(f"\n🚨 最近告警")
                        # 提取告警标题
                        lines = alert_content.split('\n')
                        title_line = next((line for line in lines if '自动化系统检查告警' in line or '自动化检查系统错误' in line), None)
                        if title_line:
                            print(f"   存在未处理的告警: {title_line}")
                except Exception:
                    pass
        
        except Exception as e:
            print(f"生成报告时出错: {e}")

def main():
    """主函数"""
    import sys
    
    scheduler = AuditSystemScheduler()
    
    # 解析命令行参数
    if len(sys.argv) > 1:
        action = sys.argv[1]
        
        if action == 'run':
            # 运行单次检查
            scheduler.run_scheduled_check()
        
        elif action == 'monitor':
            # 启动持续监控
            scheduler.run_continuous_monitoring()
        
        elif action == 'report':
            # 生成状态报告
            scheduler.generate_status_report()
        
        elif action == 'test':
            # 测试模式（不等待）
            scheduler.config['check_interval_hours'] = 0.1  # 6分钟
            scheduler.run_continuous_monitoring()
        
        else:
            print(f"未知操作: {action}")
            print("可用操作: run, monitor, report, test")
    
    else:
        # 默认运行单次检查
        scheduler.run_scheduled_check()

if __name__ == "__main__":
    main()