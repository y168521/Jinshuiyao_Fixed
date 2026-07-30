#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""金水谣智能审计工具 - 整合增强变更记录功能

功能特性：
1. 🧹 智能去重过滤
2. 📋 自动化CHANGELOG生成
3. 🔍 智能比对工具
4. 📊 结构化高级查询
5. 📈 可视化和统计分析

使用方法：
    python audit_tool.py --help
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 添加当前目录到路径，确保可以导入模块
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from utils import change_audit, smart_audit
    SMART_AUDIT_AVAILABLE = True
except ImportError:
    SMART_AUDIT_AVAILABLE = False
    print("⚠️ smart_audit模块不可用，部分功能受限")


def setup_args_parser():
    """设置命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='金水谣智能审计工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 显示系统审计统计
  python audit_tool.py stats
  
  # 生成最近7天的CHANGELOG
  python audit_tool.py changelog --days 7
  
  # 查询特定文件的变更记录
  python audit_tool.py query --file "gui/main_window.py" --limit 20
  
  # 智能去重查询（仅保留30分钟外的备份）
  python audit_tool.py query --include-backups --deduplicate
  
  # 分析备份模式
  python audit_tool.py analyze-backups
  
  # 对比两个文件
  python audit_tool.py diff /path/to/file1.py /path/to/file2.py
  
  # 导出JSON格式的审计数据
  python audit_tool.py export --format json
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # stats 命令：显示统计信息
    stats_parser = subparsers.add_parser('stats', help='显示审计统计信息')
    stats_parser.add_argument('--detailed', action='store_true', help='显示详细统计')
    
    # changelog 命令：生成CHANGELOG
    changelog_parser = subparsers.add_parser('changelog', help='生成自动化CHANGELOG')
    changelog_parser.add_argument('--days', type=int, default=7, help='天数范围（默认7天）')
    changelog_parser.add_argument('--output', type=str, help='输出文件路径（不指定则打印到控制台）')
    
    # query 命令：查询变更记录
    query_parser = subparsers.add_parser('query', help='查询变更记录')
    query_parser.add_argument('--file', type=str, help='过滤文件路径')
    query_parser.add_argument('--type', type=str, choices=['FIX', 'OPT', 'NEW', 'DEL', 'ROLLBACK', 'BACKUP'], 
                             help='变更类型过滤')
    query_parser.add_argument('--limit', type=int, default=50, help='返回条数限制')
    query_parser.add_argument('--include-backups', action='store_true', help='包含备份记录')
    query_parser.add_argument('--deduplicate', action='store_true', help='启用智能去重')
    query_parser.add_argument('--format', choices=['json', 'text', 'table'], default='table', help='输出格式')
    
    # analyze-backups 命令：分析备份模式
    analyze_parser = subparsers.add_parser('analyze-backups', help='分析备份模式，识别异常行为')
    
    # diff 命令：对比文件
    diff_parser = subparsers.add_parser('diff', help='对比两个文件的差异')
    diff_parser.add_argument('file1', type=str, help='第一个文件路径')
    diff_parser.add_argument('file2', type=str, help='第二个文件路径')
    diff_parser.add_argument('--output', choices=['text', 'json'], default='text', help='输出格式')
    
    # export 命令：导出数据
    export_parser = subparsers.add_parser('export', help='导出审计数据')
    export_parser.add_argument('--format', choices=['json', 'csv'], default='json', help='导出格式')
    export_parser.add_argument('--output', type=str, required=True, help='输出文件路径')
    
    # report 命令：生成智能报告
    report_parser = subparsers.add_parser('report', help='生成智能审计报告')
    report_parser.add_argument('--output', type=str, help='输出文件路径（不指定则打印到控制台）')
    
    # clean 命令：清理重复数据
    clean_parser = subparsers.add_parser('clean', help='清理重复的备份记录')
    clean_parser.add_argument('--backup-hours', type=int, default=24, 
                            help='保留最近N小时的备份（默认24小时）')
    clean_parser.add_argument('--dry-run', action='store_true', help='模拟运行，不实际修改')
    
    return parser


def print_stats(detailed=False):
    """显示审计统计信息"""
    try:
        stats = change_audit.get_statistics()
        
        print("📊 金水谣审计系统统计")
        print("=" * 50)
        print(f"总记录数: {stats.get('total_entries', 0):,} 条")
        
        if 'by_type' in stats and stats['by_type']:
            print("\n📈 变更类型分布:")
            type_icons = {
                "FIX": "🔧", "OPT": "⚡", "NEW": "✨", 
                "DEL": "🗑️", "ROLLBACK": "⏪", "BACKUP": "💾"
            }
            
            sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)
            max_count = max(stats['by_type'].values()) if stats['by_type'].values() else 1
            
            for entry_type, count in sorted_types:
                icon = type_icons.get(entry_type, "📝")
                percentage = (count / stats['total_entries'] * 100) if stats['total_entries'] > 0 else 0
                bar_length = int(count / max_count * 40) if max_count > 0 else 0
                bar = "█" * bar_length + "░" * (40 - bar_length)
                print(f"  {icon} {entry_type:<10} {count:>5} 条 {percentage:5.1f}%")
                print(f"     {bar}")
        
        if 'files_most_changed' in stats and stats['files_most_changed']:
            print("\n🏆 最活跃文件:")
            for i, file_data in enumerate(stats['files_most_changed'][:10], 1):
                print(f"  {i:2d}. {file_data['file']} - {file_data['count']:>4} 次修改")
        
        # 数据清洁度分析
        if 'by_type' in stats:
            backup_count = stats['by_type'].get('BACKUP', 0)
            manual_count = stats['total_entries'] - backup_count
            
            print("\n🧹 数据清洁度分析:")
            print(f"  🔴 手动操作记录: {manual_count} 条")
            print(f"  🟡 自动备份记录: {backup_count} 条")
            
            if stats['total_entries'] > 0:
                backup_ratio = backup_count / stats['total_entries']
                clean_score = min(100, 100 - (backup_ratio * 50))
                
                if clean_score >= 85:
                    color_emoji = "🟢"
                elif clean_score >= 70:
                    color_emoji = "🟡"
                else:
                    color_emoji = "🔴"
                
                print(f"  {color_emoji} 清洁度评分: {clean_score:.1f}/100")
                print(f"     {'█' * int(clean_score/5)}{'░' * (20 - int(clean_score/5))}")
                
                if clean_score < 70 and backup_count > 100:
                    print(f"  ⚠️  警告: 备份记录过多 ({backup_count}条)，建议清理")
        
        if detailed and 'recent_activity' in stats and stats['recent_activity']:
            print("\n⏰ 最近活动（最近7天）:")
            recent_entries = stats['recent_activity'][:10]
            for entry in recent_entries:
                timestamp = entry.get('ts', '未知时间')
                entry_type = entry.get('type', 'UNKNOWN')
                file_path = entry.get('file', '未知文件')
                summary = entry.get('summary', '')
                
                icon = type_icons.get(entry_type, "📝")
                print(f"  {icon} [{timestamp}] {file_path}")
                if summary:
                    print(f"      {summary}")
        
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ 获取统计信息失败: {e}")


def generate_changelog(days=7, output_file=None):
    """生成CHANGELOG"""
    try:
        if SMART_AUDIT_AVAILABLE:
            changelog = smart_audit.generate_auto_changelog(days)
        else:
            # 回退方案：使用基础功能生成
            changelog = "## 📋 基本变更日志\n\n"
            changelog += "⚠️ smart_audit模块不可用，使用基础查询功能\n\n"
            
            try:
                entries = change_audit.get_recent(limit=50, include_backups=False)
                if entries:
                    current_date = None
                    for entry in entries[::-1]:  # 最旧的在前
                        timestamp = entry.get('ts', '')
                        if timestamp:
                            entry_date = timestamp.split(' ')[0]
                            if entry_date != current_date:
                                changelog += f"### 📅 {entry_date}\n\n"
                                current_date = entry_date
                            
                            entry_type = entry.get('type', 'UNKNOWN')
                            file_path = entry.get('file', '未知文件')
                            summary = entry.get('summary', '')
                            
                            type_icons = {
                                "FIX": "🔧", "OPT": "⚡", "NEW": "✨", 
                                "DEL": "🗑️", "ROLLBACK": "⏪"
                            }
                            icon = type_icons.get(entry_type, "📝")
                            
                            changelog += f"- {icon} **{file_path}**: {summary}\n"
                else:
                    changelog += "暂无变更记录。\n"
            except Exception as inner_e:
                changelog += f"❌ 生成失败: {inner_e}\n"
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(changelog)
            print(f"✅ CHANGELOG已保存到: {output_file}")
        else:
            print(changelog)
        
    except Exception as e:
        print(f"❌ 生成CHANGELOG失败: {e}")


def query_audit_logs(file_filter=None, type_filter=None, limit=50, 
                    include_backups=False, deduplicate=False, format_type='table'):
    """查询审计日志"""
    try:
        if hasattr(change_audit, 'query_smart_filtered') and callable(change_audit.query_smart_filtered):
            entries = change_audit.query_smart_filtered(
                file_path=file_filter,
                entry_type=type_filter,
                limit=limit,
                include_backups=include_backups,
                deduplicate=deduplicate
            )
        else:
            # 回退到基础查询
            entries = change_audit.query(
                file_path=file_filter,
                entry_type=type_filter,
                limit=limit,
                include_backups=include_backups
            )
        
        if not entries:
            print("📭 未找到符合条件的记录")
            return
        
        if format_type == 'json':
            print(json.dumps(entries, ensure_ascii=False, indent=2))
            return
        
        print(f"📋 查询结果: {len(entries)} 条记录")
        if deduplicate and include_backups:
            print("🧹 （已启用智能去重）")
        print("-" * 80)
        
        if format_type == 'table':
            # 简单的表格格式
            type_icons = {
                "FIX": "🔧", "OPT": "⚡", "NEW": "✨", 
                "DEL": "🗑️", "ROLLBACK": "⏪", "BACKUP": "💾"
            }
            
            for i, entry in enumerate(entries, 1):
                entry_type = entry.get('type', 'UNKNOWN')
                icon = type_icons.get(entry_type, "📝")
                timestamp = entry.get('ts', '未知时间')
                file_path = entry.get('file', '未知文件')
                summary = entry.get('summary', '')
                
                print(f"{i:3d}. {icon} [{timestamp[:19]}]")
                print(f"    文件: {file_path}")
                print(f"    类型: {entry_type}")
                print(f"    摘要: {summary}")
                
                detail = entry.get('detail')
                if detail:
                    print(f"    详情: {detail}")
                
                print("")
        else:
            # 文本格式
            for entry in entries:
                print(change_audit.format_entries([entry]))
                print()
        
        print(f"✅ 共查询到 {len(entries)} 条记录")
        
    except Exception as e:
        print(f"❌ 查询失败: {e}")


def analyze_backup_patterns():
    """分析备份模式"""
    try:
        if hasattr(change_audit, 'get_backup_pattern_analysis'):
            analysis = change_audit.get_backup_pattern_analysis()
        else:
            print("❌ 分析功能在当前版本不可用")
            return
        
        if 'error' in analysis:
            print(f"⚠️ {analysis['error']}")
            return
        
        print("📊 备份模式分析报告")
        print("=" * 60)
        print(f"总备份记录数: {analysis.get('total_backup_entries', 0):,} 条")
        print(f"唯一备份文件数: {len(analysis.get('unique_files_backed_up', []))}")
        print()
        
        freq_backups = analysis.get('frequent_backups', [])
        if freq_backups:
            print("🔔 频繁备份文件警告（每小时备份超过5次）:")
            for backup in freq_backups:
                print(f"  📄 {backup['file']}")
                print(f"     备份次数: {backup['backup_count']} 次")
                print(f"     建议: {backup.get('suggestion', '请检查备份逻辑')}")
                print()
        
        peak_hours = analysis.get('peak_hours', [])
        if peak_hours:
            print("⏰ 备份高峰时段（按备份次数排序）:")
            for hour_data in peak_hours:
                hour = hour_data.get('hour', '未知')
                count = hour_data.get('count', 0)
                print(f"  🕐 {hour}: {count} 次备份")
        
        # 计算建议
        total_backups = analysis.get('total_backup_entries', 0)
        if total_backups > 1000:
            print("\n⚠️ 警告: 备份记录过多，可能存在过度备份问题")
            print("  建议: 考虑启用智能去重或调整备份策略")
        
        unique_files = len(analysis.get('unique_files_backed_up', []))
        if unique_files > 0:
            avg_backup_per_file = total_backups / unique_files
            if avg_backup_per_file > 10:
                print(f"\n⚠️ 警告: 平均每个文件备份 {avg_backup_per_file:.1f} 次")
                print("  建议: 检查是否有文件被频繁修改，或备份逻辑过于敏感")
                
                if avg_backup_per_file > 50:
                    print("  🚨 高级警报: 可能存在备份循环或测试文件")
        
        print("=" * 60)
        print("💡 改进建议:")
        print("  - 启用智能去重过滤: python audit_tool.py query --deduplicate")
        print("  - 清理旧备份: python audit_tool.py clean")
        print("  - 调整FileWatcher监控频率或忽略模式")
        
    except Exception as e:
        print(f"❌ 分析失败: {e}")


def compare_files(file1, file2, output_format='text'):
    """对比两个文件"""
    try:
        if SMART_AUDIT_AVAILABLE:
            result = smart_audit.compare_files(file1, file2)
        else:
            result = {"error": "smart_audit模块不可用"}
        
        if output_format == 'json':
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        
        print(f"🔍 文件对比: {file1} ↔ {file2}")
        print("=" * 60)
        
        if 'error' in result or 'exists' not in result:
            if 'summary' in result:
                print(f"❌ {result['summary']}")
            else:
                print(f"❌ 对比失败")
            return
        
        if not result['exists']['file1']:
            print(f"❌ 文件1不存在: {file1}")
            return
        
        if not result['exists']['file2']:
            print(f"❌ 文件2不存在: {file2}")
            return
        
        print(f"📊 相似度: {result.get('similarity', 0) * 100:.1f}%")
        print(f"📝 {result.get('summary', '')}")
        
        differences = result.get('differences', [])
        if differences:
            print(f"\n📋 差异详情 ({len(differences)} 行):")
            print("-" * 60)
            
            # 限制显示行数
            max_lines_to_show = 50
            if len(differences) > max_lines_to_show:
                print(f"...（仅显示前 {max_lines_to_show} 行差异）")
                differences = differences[:max_lines_to_show]
            
            for line in differences:
                if line.startswith('+') and not line.startswith('+++'):
                    print(f"  \033[92m{line}\033[0m")  # 绿色 - 新增
                elif line.startswith('-') and not line.startswith('---'):
                    print(f"  \033[91m{line}\033[0m")  # 红色 - 删除
                elif line.startswith('@'):
                    print(f"  \033[93m{line}\033[0m")  # 黄色 - 位置信息
                else:
                    print(f"  {line}")
        else:
            print("\n✅ 文件内容完全相同")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 对比失败: {e}")


def export_data(format_type='json', output_file=None):
    """导出审计数据"""
    try:
        if SMART_AUDIT_AVAILABLE:
            try:
                export_data = smart_audit.export_audit_data(format_type)
            except AttributeError:
                export_data = {"error": "export_audit_data函数不可用"}
        else:
            export_data = {"error": "smart_audit模块不可用"}
        
        if 'error' in export_data:
            print(f"❌ 导出失败: {export_data['error']}")
            
            # 尝试基础导出
            print("尝试基础导出...")
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            audit_log = os.path.join(base_dir, "金水谣数据", "log", "change_audit.logl")
            
            export_data = {
                "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "基础导出",
                "records": []
            }
            
            try:
                if os.path.exists(audit_log):
                    with open(audit_log, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    export_data["records"].append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
            except Exception as e:
                export_data["error"] = f"读取日志失败: {e}"
        
        if not output_file:
            print(json.dumps(export_data, ensure_ascii=False, indent=2))
            return
        
        if format_type == 'json':
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            print(f"✅ JSON数据已导出到: {output_file}")
        elif format_type == 'csv':
            # 简化的CSV导出
            import csv
            
            if 'records' not in export_data or not export_data['records']:
                print("❌ 无可导出的记录数据")
                return
            
            with open(output_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["ts", "type", "file", "summary", "detail"])
                writer.writeheader()
                
                for record in export_data['records'][:1000]:  # 限制1000条
                    writer.writerow({
                        "ts": record.get('ts', ''),
                        "type": record.get('type', ''),
                        "file": record.get('file', ''),
                        "summary": record.get('summary', ''),
                        "detail": record.get('detail', '')
                    })
            
            print(f"✅ CSV数据已导出到: {output_file} ({len(export_data['records'])} 条记录)")
        else:
            print(f"❌ 不支持的导出格式: {format_type}")
        
    except Exception as e:
        print(f"❌ 导出失败: {e}")


def generate_report(output_file=None):
    """生成智能报告"""
    try:
        if hasattr(change_audit, 'generate_smart_report'):
            report = change_audit.generate_smart_report()
        else:
            report = "=== 基础审计报告 ===\n\n"
            report += "智能报告功能需要更新change_audit.py模块\n"
            report += "请确保使用的是最新版本的金水谣系统\n"
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ 报告已保存到: {output_file}")
        else:
            print(report)
        
    except Exception as e:
        print(f"❌ 生成报告失败: {e}")


def clean_duplicate_backups(backup_hours=24, dry_run=False):
    """清理重复备份记录"""
    try:
        print("🧹 备份记录清理工具")
        print("=" * 60)
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backup_log_path = os.path.join(base_dir, "金水谣数据", "log", "backup_audit.logl")
        
        if not os.path.exists(backup_log_path):
            print(f"❌ 备份日志文件不存在: {backup_log_path}")
            return
        
        # 读取所有备份记录
        entries = []
        with open(backup_log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entries.append((line, entry))
                    except json.JSONDecodeError:
                        continue
        
        print(f"📊 原始备份记录数: {len(entries)} 条")
        
        # 统计需要清理的记录
        to_keep = []
        to_remove = []
        file_time_map = {}
        
        cut_off_time = datetime.now() - timedelta(hours=backup_hours)
        
        for line, entry in entries:
            if entry.get('type') != 'BACKUP':
                to_keep.append(line)
                continue
            
            file_path = entry.get('file', '')
            timestamp_str = entry.get('ts', '')
            
            if not timestamp_str:
                to_keep.append(line)
                continue
            
            try:
                entry_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                
                # 检查是否超过保留时间
                if entry_time < cut_off_time:
                    if dry_run:
                        print(f"  标记为过期: {timestamp_str} - {file_path}")
                    to_remove.append((timestamp_str, file_path, "超出保留时间"))
                    continue
                
                # 检查是否重复（同一文件30分钟内）
                if file_path in file_time_map:
                    last_time = file_time_map[file_path]
                    time_diff = (entry_time - last_time).total_seconds() / 60  # 分钟
                    
                    if time_diff < 30:
                        to_remove.append((timestamp_str, file_path, f"重复备份（距离上次{time_diff:.0f}分钟）"))
                        continue
                    else:
                        file_time_map[file_path] = entry_time
                        to_keep.append(line)
                else:
                    file_time_map[file_path] = entry_time
                    to_keep.append(line)
                    
            except ValueError:
                to_keep.append(line)
        
        print(f"🔍 分析完成:")
        print(f"  ✅ 保留记录: {len(to_keep)} 条")
        print(f"  🗑️  标记删除: {len(to_remove)} 条")
        
        if to_remove:
            print(f"\n📋 标记删除的备份记录:")
            for i, (ts, file_path, reason) in enumerate(to_remove[:20], 1):
                print(f"  {i:3d}. [{ts}] {file_path}")
                print(f"      原因: {reason}")
            
            if len(to_remove) > 20:
                print(f"  ... 还有 {len(to_remove) - 20} 条未显示")
        
        if not dry_run and to_remove:
            # 实际执行清理
            backup_path = backup_log_path + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(backup_log_path, backup_path)
            print(f"📁 已创建备份: {backup_path}")
            
            with open(backup_log_path, 'w', encoding='utf-8') as f:
                for line in to_keep:
                    f.write(line + '\n')
            
            print(f"✅ 清理完成！删除 {len(to_remove)} 条记录，保留 {len(to_keep)} 条")
            print(f"💾 压缩率: {len(to_remove)/len(entries)*100:.1f}% 减少")
        
        elif dry_run:
            print(f"\n🔍 模拟运行完成（未实际修改文件）")
            print(f"  如需实际清理，请移除 --dry-run 参数")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 清理失败: {e}")


def main():
    """主函数"""
    parser = setup_args_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'stats':
        print_stats(args.detailed)
    
    elif args.command == 'changelog':
        generate_changelog(args.days, args.output)
    
    elif args.command == 'query':
        query_audit_logs(
            file_filter=args.file,
            type_filter=args.type,
            limit=args.limit,
            include_backups=args.include_backups,
            deduplicate=args.deduplicate,
            format_type=args.format
        )
    
    elif args.command == 'analyze-backups':
        analyze_backup_patterns()
    
    elif args.command == 'diff':
        compare_files(args.file1, args.file2, args.output)
    
    elif args.command == 'export':
        export_data(args.format, args.output)
    
    elif args.command == 'report':
        generate_report(args.output)
    
    elif args.command == 'clean':
        try:
            import shutil  # 只在需要时导入
            clean_duplicate_backups(args.backup_hours, args.dry_run)
        except ImportError:
            print("❌ shutil模块不可用，清理功能受限")


if __name__ == "__main__":
    main()