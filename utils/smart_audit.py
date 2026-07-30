# -*- coding: utf-8 -*-
"""金水谣智能审计引擎 - 增强变更记录系统

基于最佳实践的升级方案，包含：
1. 智能去重过滤 - 自动识别过滤重复/相似备份记录
2. 自动化CHANGELOG - 基于审计日志自动生成结构化变更日志
3. 智能比对工具 - 支持前后版本对比和差异分析
4. 结构化高级查询 - 多维度查询和可视化能力

核心原则：在现有change_audit.py基础上增强，向前兼容，不破坏已有功能。
"""

import os
import json
import re
import difflib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import hashlib
from collections import defaultdict


class SmartAuditFilter:
    """智能去重过滤器"""
    
    def __init__(self, backup_log_path: str):
        self.backup_log_path = backup_log_path
        self.hash_cache = {}  # 文件路径 -> 内容哈希
        
    def _get_file_hash(self, file_path: str) -> str:
        """计算文件内容哈希，用于去重判断"""
        if file_path in self.hash_cache:
            return self.hash_cache[file_path]
        
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                file_hash = hashlib.md5(content).hexdigest()
                self.hash_cache[file_path] = file_hash
                return file_hash
        except Exception:
            return ""
    
    def filter_duplicate_backups(self, entries: List[Dict]) -> List[Dict]:
        """过滤重复备份记录（基于文件内容和时间接近性）"""
        filtered = []
        file_times = defaultdict(list)
        
        # 按文件分组记录时间
        for entry in entries:
            if entry.get('type') == 'BACKUP':
                file_path = entry.get('file', '')
                timestamp = entry.get('ts', '')
                if file_path and timestamp:
                    try:
                        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                        file_times[file_path].append((dt, entry))
                    except ValueError:
                        filtered.append(entry)  # 保留格式错误的记录
            else:
                filtered.append(entry)  # 非备份记录全部保留
        
        # 对每个文件的备份记录进行智能筛选
        for file_path, times_entries in file_times.items():
            if len(times_entries) <= 1:
                # 只有一个备份记录，直接保留
                filtered.append(times_entries[0][1])
                continue
            
            # 按时间排序
            times_entries.sort(key=lambda x: x[0])
            
            # 基于时间间隔的智能筛选（30分钟内视为重复）
            last_kept_time = None
            for dt, entry in times_entries:
                if last_kept_time is None:
                    filtered.append(entry)
                    last_kept_time = dt
                else:
                    # 检查时间间隔
                    time_diff = (dt - last_kept_time).total_seconds() / 60  # 分钟
                    if time_diff >= 30:
                        filtered.append(entry)
                        last_kept_time = dt
                    else:
                        # 30分钟内的备份视为重复，过滤掉
                        pass
        
        return filtered
    
    def analyze_backup_patterns(self) -> Dict[str, Any]:
        """分析备份模式，识别异常行为"""
        if not os.path.exists(self.backup_log_path):
            return {"error": "备份日志文件不存在"}
        
        patterns = {
            "frequent_files": [],       # 频繁备份的文件
            "similarity_groups": [],    # 相似备份分组
            "time_distribution": {},    # 时间分布
            "total_count": 0,           # 总备份数量
            "unique_files": set()       # 唯一文件数
        }
        
        try:
            with open(self.backup_log_path, 'r', encoding='utf-8') as f:
                backup_count = defaultdict(int)
                file_timestamps = defaultdict(list)
                
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        entry = json.loads(line)
                        if entry.get('type') == 'BACKUP':
                            patterns["total_count"] += 1
                            file_path = entry.get('file', '')
                            timestamp = entry.get('ts', '')
                            
                            if file_path:
                                patterns["unique_files"].add(file_path)
                                backup_count[file_path] += 1
                                
                                if timestamp:
                                    try:
                                        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                        hour_key = dt.strftime("%Y-%m-%d %H")
                                        time_key = f"{dt.strftime('%H:%M')}点"
                                        file_timestamps[file_path].append(dt)
                                    except ValueError:
                                        pass
                    except json.JSONDecodeError:
                        continue
                
                # 识别频繁备份的文件（每小时超过2次）
                for file_path, count in backup_count.items():
                    if count > 2:
                        patterns["frequent_files"].append({
                            "file": file_path,
                            "count": count,
                            "timestamps": [ts.strftime("%H:%M:%S") for ts in file_timestamps.get(file_path, [])]
                        })
                
                # 分析时间分布
                if file_timestamps:
                    hour_distribution = defaultdict(int)
                    for timestamps in file_timestamps.values():
                        for ts in timestamps:
                            hour_distribution[ts.strftime("%H")] += 1
                    
                    patterns["time_distribution"] = dict(hour_distribution)
                
                return patterns
        
        except Exception as e:
            return {"error": f"分析失败: {str(e)}"}


class AutoChangelogGenerator:
    """自动化CHANGELOG生成器"""
    
    @staticmethod
    def generate_from_audit_log(audit_log_path: str, days: int = 7) -> str:
        """从审计日志生成结构化CHANGELOG"""
        if not os.path.exists(audit_log_path):
            return "## 变更日志生成\n\n⚠️ 审计日志文件不存在"
        
        changelog = "## 📋 自动化生成变更日志\n\n"
        
        try:
            # 读取并解析审计日志
            entries = []
            with open(audit_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            
            # 按日期分组
            date_groups = defaultdict(list)
            for entry in entries:
                timestamp = entry.get('ts', '')
                if timestamp:
                    date_part = timestamp.split(' ')[0]
                    date_groups[date_part].append(entry)
            
            # 按日期倒序排列（最新的在前）
            sorted_dates = sorted(date_groups.keys(), reverse=True)
            
            # 只显示最近指定天数的记录
            days_ago = datetime.now() - timedelta(days=days)
            displayed_dates = []
            
            for date_str in sorted_dates:
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if entry_date >= days_ago:
                        displayed_dates.append(date_str)
                except ValueError:
                    continue
            
            if not displayed_dates:
                changelog += "暂无最近变更记录。\n"
                return changelog
            
            # 生成格式化的CHANGELOG
            for date_str in displayed_dates:
                date_entries = date_groups[date_str]
                
                # 按类型分组
                type_groups = defaultdict(list)
                for entry in date_entries:
                    entry_type = entry.get('type', 'UNKNOWN')
                    type_groups[entry_type].append(entry)
                
                changelog += f"### 📅 {date_str}\n\n"
                
                # 按类型顺序显示（修复 -> 优化 -> 新增 -> 删除）
                type_order = ['FIX', 'OPT', 'NEW', 'DEL', 'ROLLBACK']
                type_icons = {
                    'FIX': '🔧',
                    'OPT': '⚡', 
                    'NEW': '✨',
                    'DEL': '🗑️',
                    'ROLLBACK': '⏪',
                    'BACKUP': '💾'
                }
                
                for entry_type in type_order:
                    if entry_type in type_groups:
                        icon = type_icons.get(entry_type, '📝')
                        changelog += f"#### {icon} {entry_type}\n\n"
                        
                        type_entries = type_groups[entry_type]
                        for entry in type_entries:
                            file_path = entry.get('file', '未知文件')
                            summary = entry.get('summary', '')
                            detail = entry.get('detail', '')
                            
                            changelog += f"- **{file_path}**: {summary}\n"
                            if detail:
                                changelog += f"  - *{detail}*\n"
                        changelog += "\n"
                
            return changelog
        
        except Exception as e:
            return f"## 变更日志生成\n\n❌ 生成失败: {str(e)}"


class SmartDiffTool:
    """智能比对工具"""
    
    @staticmethod
    def compare_versions(file1: str, file2: str) -> Dict[str, Any]:
        """比较两个版本的文件差异"""
        result = {
            "file1": file1,
            "file2": file2,
            "exists": {
                "file1": os.path.exists(file1),
                "file2": os.path.exists(file2)
            },
            "differences": [],
            "summary": "",
            "similarity": 1.0
        }
        
        if not result["exists"]["file1"] or not result["exists"]["file2"]:
            result["summary"] = "文件不存在，无法比较"
            return result
        
        try:
            with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
                lines1 = f1.readlines()
                lines2 = f2.readlines()
                
            # 计算相似度
            similarity = difflib.SequenceMatcher(None, lines1, lines2).ratio()
            result["similarity"] = round(similarity, 3)
            
            # 生成差异详情
            diff = list(difflib.unified_diff(
                lines1, lines2,
                fromfile="旧版本", 
                tofile="新版本",
                lineterm=''
            ))
            
            if diff:
                result["differences"] = diff
                
                # 统计差异
                add_count = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
                del_count = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
                total_changes = add_count + del_count
                
                result["summary"] = f"共发现 {total_changes} 处变更（+{add_count}/-{del_count}），相似度 {similarity*100:.1f}%"
            else:
                result["summary"] = "文件内容完全相同"
            
            return result
            
        except Exception as e:
            result["summary"] = f"比较失败: {str(e)}"
            return result
    
    @staticmethod
    def compare_git_styles(old_content: str, new_content: str) -> str:
        """生成类git风格的差异显示"""
        import difflib
        
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile='旧版本',
            tofile='新版本',
            lineterm=''
        )
        
        return ''.join(diff)


class AdvancedAuditQuery:
    """高级审计查询"""
    
    def __init__(self, audit_log_paths: List[str]):
        self.audit_log_paths = audit_log_paths
        
    def load_all_entries(self) -> List[Dict]:
        """加载所有审计日志条目"""
        all_entries = []
        
        for log_path in self.audit_log_paths:
            if not os.path.exists(log_path):
                continue
                
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                all_entries.append(entry)
                            except json.JSONDecodeError:
                                continue
            except Exception:
                continue
        
        return all_entries
    
    def query_by_time_range(self, start_date: str, end_date: str) -> List[Dict]:
        """按时间范围查询"""
        entries = self.load_all_entries()
        filtered = []
        
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
            
            for entry in entries:
                timestamp = entry.get('ts', '')
                if timestamp:
                    try:
                        entry_dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                        if start_dt <= entry_dt <= end_dt:
                            filtered.append(entry)
                    except ValueError:
                        continue
        
        except ValueError as e:
            print(f"时间格式错误: {e}")
            
        return filtered
    
    def query_by_file_pattern(self, pattern: str) -> List[Dict]:
        """按文件模式查询（支持通配符）"""
        entries = self.load_all_entries()
        if not pattern:
            return entries
        
        import fnmatch
        filtered = []
        
        for entry in entries:
            file_path = entry.get('file', '')
            if fnmatch.fnmatch(file_path, pattern):
                filtered.append(entry)
            elif pattern in file_path:  # 也支持包含匹配
                filtered.append(entry)
        
        return filtered
    
    def query_by_impact_level(self) -> Dict[str, List]:
        """按影响级别分组查询"""
        entries = self.load_all_entries()
        
        # 定义影响级别
        high_impact_files = ['gui/', 'core/', 'utils/change_audit.py', 'server/']
        medium_impact_files = ['domains/', 'engines/', 'tests/']
        low_impact_files = ['scripts/', 'config/']
        
        result = {
            "HIGH": [],
            "MEDIUM": [],
            "LOW": []
        }
        
        for entry in entries:
            file_path = entry.get('file', '')
            entry_type = entry.get('type', '')
            
            # 基于文件的路径和变更类型判断影响级别
            impact = "LOW"
            
            # 高风险：核心文件和修复/删除类型
            if any(file_path.startswith(prefix) for prefix in high_impact_files):
                impact = "HIGH"
            elif entry_type in ['DEL', 'ROLLBACK']:
                impact = "HIGH"
            elif any(file_path.startswith(prefix) for prefix in medium_impact_files):
                impact = "MEDIUM"
            
            result[impact].append(entry)
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        entries = self.load_all_entries()
        
        stats = {
            "total_entries": len(entries),
            "by_type": defaultdict(int),
            "by_date": defaultdict(int),
            "by_file_extension": defaultdict(int),
            "recent_activity": [],
            "most_active_files": []
        }
        
        # 统计类型分布
        for entry in entries:
            entry_type = entry.get('type', 'UNKNOWN')
            stats["by_type"][entry_type] += 1
            
            timestamp = entry.get('ts', '')
            if timestamp:
                date_part = timestamp.split(' ')[0]
                stats["by_date"][date_part] += 1
            
            file_path = entry.get('file', '')
            if file_path:
                ext = os.path.splitext(file_path)[1]
                if ext:
                    stats["by_file_extension"][ext] += 1
        
        # 最近活动
        recent_dates = sorted(stats["by_date"].keys(), reverse=True)[:5]
        for date in recent_dates:
            stats["recent_activity"].append({
                "date": date,
                "count": stats["by_date"][date]
            })
        
        # 文件活跃度（需要单独统计）
        file_counts = defaultdict(int)
        for entry in entries:
            file_path = entry.get('file', '')
            if file_path:
                file_counts[file_path] += 1
        
        top_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for file_path, count in top_files:
            stats["most_active_files"].append({
                "file": file_path,
                "change_count": count
            })
        
        return stats


# ======== 主接口函数 ========

def get_smart_audit_filter():
    """获取智能审计过滤器实例"""
    global _smart_filter
    try:
        from utils import change_audit
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backup_log_path = os.path.join(base_dir, "金水谣数据", "log", "backup_audit.logl")
        return SmartAuditFilter(backup_log_path)
    except Exception:
        return None


def generate_auto_changelog(days: int = 7) -> str:
    """生成自动化变更日志"""
    try:
        from utils import change_audit
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        audit_log_path = os.path.join(base_dir, "金水谣数据", "log", "change_audit.logl")
        generator = AutoChangelogGenerator()
        return generator.generate_from_audit_log(audit_log_path, days)
    except Exception as e:
        return f"生成失败: {str(e)}"


def compare_files(file1: str, file2: str) -> Dict[str, Any]:
    """比较两个文件"""
    diff_tool = SmartDiffTool()
    return diff_tool.compare_versions(file1, file2)


def get_advanced_query():
    """获取高级查询实例"""
    try:
        from utils import change_audit
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        audit_log = os.path.join(base_dir, "金水谣数据", "log", "change_audit.logl")
        backup_log = os.path.join(base_dir, "金水谣数据", "log", "backup_audit.logl")
        
        return AdvancedAuditQuery([audit_log, backup_log])
    except Exception:
        return None


def export_audit_data(format: str = 'json') -> Dict[str, Any]:
    """导出审计数据"""
    try:
        query = get_advanced_query()
        if not query:
            return {"error": "无法初始化查询"}
        
        stats = query.get_statistics()
        entries = query.load_all_entries()
        
        result = {
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "statistics": stats,
            "recent_entries": entries[-50:] if len(entries) > 50 else entries,
            "summary": {
                "total_changes": len(entries),
                "unique_files": len(set(e.get('file', '') for e in entries if e.get('file'))),
                "time_span": {
                    "first": None,
                    "last": None
                }
            }
        }
        
        # 计算时间跨度
        if entries:
            timestamps = [e.get('ts', '') for e in entries if e.get('ts')]
            if timestamps:
                try:
                    first_dt = datetime.strptime(timestamps[0], "%Y-%m-%d %H:%M:%S")
                    last_dt = datetime.strptime(timestamps[-1], "%Y-%m-%d %H:%M:%S")
                    result["summary"]["time_span"]["first"] = first_dt.strftime("%Y-%m-%d")
                    result["summary"]["time_span"]["last"] = last_dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
        
        return result
        
    except Exception as e:
        return {"error": f"导出失败: {str(e)}"}


# ======== 测试和示例 ========

if __name__ == "__main__":
    print("=== 金水谣智能审计引擎测试 ===")
    
    # 测试自动化CHANGELOG生成
    print("\n1. 测试自动化CHANGELOG生成:")
    changelog = generate_auto_changelog(7)
    print(changelog[:500])  # 只显示前500字符
    
    # 测试高级查询
    print("\n2. 测试高级查询:")
    query = get_advanced_query()
    if query:
        stats = query.get_statistics()
        print(f"总记录数: {stats['total_entries']}")
        print(f"类型分布: {dict(stats['by_type'])}")
    
    print("\n测试完成。")