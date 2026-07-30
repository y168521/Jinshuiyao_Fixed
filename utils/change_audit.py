# -*- coding: utf-8 -*-
"""金水谣系统 - 变更审计日志模块

文件分两类，互不污染：
  1. change_audit.logl   → 手动操作记录：FIX/OPT/NEW/DEL/ROLLBACK
  2. backup_audit.logl   → 自动备份记录：BACKUP（FileWatcher生成）

日志格式: JSON Lines（每行一个JSON对象）
类型:
  FIX=修复, OPT=优化, NEW=新增, DEL=删除,
  ROLLBACK=回滚, BACKUP=备份（写入独立文件）

使用方式:
    from utils import change_audit
    change_audit.log_fix("config.py", "rule_config覆盖无校验", "加载后补全缺失字段")
    change_audit.log_new("plugin_manager.py", "插件热加载", "支持运行时加载新插件")

自动备份功能：
    backup_before_modify("gui/main_window.py")  # 修改前备份，生成带时间戳的副本
    list_backups("gui/main_window.py")           # 查看某文件的所有备份
    restore_backup("gui/main_window.py", 0)       # 恢复最近的备份（0=最新）
"""
import os
import shutil
import json
import threading
from datetime import datetime

AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "金水谣数据", "log")

# 手动操作日志（FIX/OPT/NEW/DEL/ROLLBACK）
AUDIT_FILE = os.path.join(AUDIT_DIR, "change_audit.logl")

# 自动备份日志（BACKUP），与手动操作分离，避免污染
BACKUP_AUDIT_FILE = os.path.join(AUDIT_DIR, "backup_audit.logl")

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "金水谣数据", "backups")

_lock = threading.Lock()

# 确保目录存在
os.makedirs(AUDIT_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


def _write_entry(entry_type, file_path, summary, detail=""):
    """写入审计日志条目

    BACKUP 类型写入 backup_audit.logl，其他写入 change_audit.logl。
    """
    with _lock:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = json.dumps({
            "ts": timestamp,
            "type": entry_type,
            "file": file_path,
            "summary": summary,
            "detail": detail,
        }, ensure_ascii=False) + "\n"

        if entry_type == "BACKUP":
            target = BACKUP_AUDIT_FILE
        else:
            target = AUDIT_FILE

        with open(target, "a", encoding="utf-8") as f:
            f.write(line)


def _write_entry_to_file(target_file, entry_type, file_path, summary, detail=""):
    """直接写入指定文件（供 FileWatcher 后备模式使用）"""
    with _lock:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = json.dumps({
            "ts": timestamp,
            "type": entry_type,
            "file": file_path,
            "summary": summary,
            "detail": detail,
        }, ensure_ascii=False) + "\n"
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(line)


# ======== 自动文件备份 ========

def backup_before_modify(file_path, project_dir=None):
    """修改前自动备份文件到 金水谣数据/backups/

    Args:
        file_path: 相对路径（如 'gui/main_window.py'）或绝对路径
        project_dir: 项目根目录，默认自动推断

    Returns:
        备份文件的绝对路径，失败返回 None
    """
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 处理绝对路径：转为相对于项目根目录的路径
    if os.path.isabs(file_path):
        try:
            rel = os.path.relpath(file_path, project_dir)
        except ValueError:
            rel = file_path
    else:
        rel = file_path
        file_path = os.path.join(project_dir, rel)

    if not os.path.isfile(file_path):
        return None

    backup_subdir = os.path.join(BACKUP_DIR, rel.replace(os.sep, "_"))
    os.makedirs(backup_subdir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = os.path.basename(rel)
    name, ext = os.path.splitext(basename)
    backup_name = f"{name}_{timestamp}{ext}"
    backup_path = os.path.join(backup_subdir, backup_name)

    try:
        shutil.copy2(file_path, backup_path)
        _write_entry("BACKUP", rel, f"修改前自动备份 → {backup_name}", f"原文件 {os.path.getsize(file_path)} 字节")
        return backup_path
    except Exception as e:
        _write_entry("BACKUP", rel, f"备份失败: {e}", str(e))
        return None


def list_backups(file_path, project_dir=None):
    """列出某文件的所有备份（按时间倒序，最新的在前）

    Args:
        file_path: 相对路径或绝对路径

    Returns:
        [{"path": ..., "time": ..., "size": ...}, ...]
    """
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if os.path.isabs(file_path):
        rel = os.path.relpath(file_path, project_dir)
    else:
        rel = file_path

    backup_subdir = os.path.join(BACKUP_DIR, rel.replace(os.sep, "_"))
    if not os.path.isdir(backup_subdir):
        return []

    backups = []
    for f in sorted(os.listdir(backup_subdir), reverse=True):
        fp = os.path.join(backup_subdir, f)
        if os.path.isfile(fp):
            backups.append({
                "path": fp,
                "name": f,
                "time": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S"),
                "size": os.path.getsize(fp),
            })
    return backups


def restore_backup(file_path, index=0, project_dir=None):
    """从备份恢复文件

    Args:
        file_path: 相对路径或绝对路径
        index: 备份索引（0=最新），或备份文件名
        project_dir: 项目根目录

    Returns:
        恢复后的绝对路径，失败返回 None
    """
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if os.path.isabs(file_path):
        rel = os.path.relpath(file_path, project_dir)
    else:
        rel = file_path
        file_path = os.path.join(project_dir, rel)

    backups = list_backups(rel, project_dir)
    if not backups:
        return None

    if isinstance(index, str):
        for b in backups:
            if b["name"] == index:
                src = b["path"]
                break
        else:
            return None
    else:
        if index < 0 or index >= len(backups):
            return None
        src = backups[index]["path"]

    try:
        backup_before_modify(rel, project_dir)
        shutil.copy2(src, file_path)
        _write_entry("ROLLBACK", rel, f"从备份恢复: {backups[index if isinstance(index, int) else 0]['name']}", f"恢复到 {backups[0]['time'] if isinstance(index, int) else backups[0]['time']} 的版本")
        return file_path
    except Exception as e:
        _write_entry("ROLLBACK", rel, f"恢复失败: {e}", str(e))
        return None


def log_fix(file_path, summary, detail=""):
    """记录Bug修复"""
    _write_entry("FIX", file_path, summary, detail)


def log_opt(file_path, summary, detail=""):
    """记录优化"""
    _write_entry("OPT", file_path, summary, detail)


def log_new(file_path, summary, detail=""):
    """记录新功能"""
    _write_entry("NEW", file_path, summary, detail)


def log_del(file_path, summary, detail=""):
    """记录删除"""
    _write_entry("DEL", file_path, summary, detail)


def log_rollback(file_path, summary, detail=""):
    """记录回滚"""
    _write_entry("ROLLBACK", file_path, summary, detail)


def query(file_path=None, entry_type=None, limit=50, include_backups=False):
    """查询审计日志

    Args:
        file_path: 按文件路径过滤
        entry_type: 按类型过滤（FIX/OPT/NEW/DEL/ROLLBACK）
        limit: 返回条数上限
        include_backups: 是否包含BACKUP类型（从backup_audit.logl读取）

    Returns:
        list[dict]
    """
    results = []

    # 查询主日志
    if os.path.isfile(AUDIT_FILE):
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if file_path and entry.get("file") != file_path:
                        continue
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    results.append(entry)
                except json.JSONDecodeError:
                    continue
                if len(results) >= limit:
                    return results

    # 需要包含备份记录
    if include_backups and os.path.isfile(BACKUP_AUDIT_FILE):
        with open(BACKUP_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if file_path and entry.get("file") != file_path:
                        continue
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    results.append(entry)
                except json.JSONDecodeError:
                    continue
                if len(results) >= limit:
                    return results

    return results[:limit]


def get_recent(limit=20, include_backups=False):
    """获取最近N条变更记录

    Args:
        limit: 返回条数
        include_backups: 是否包含备份记录

    Returns:
        list[dict]
    """
    entries = []

    if os.path.isfile(AUDIT_FILE):
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    if include_backups and os.path.isfile(BACKUP_AUDIT_FILE):
        with open(BACKUP_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    return entries[-limit:]


def format_entries(entries):
    """格式化输出审计记录"""
    lines = []
    for e in entries:
        icon = {
            "FIX": "🔧",
            "OPT": "⚡",
            "NEW": "✨",
            "DEL": "🗑",
            "ROLLBACK": "⏪",
            "BACKUP": "💾",
        }.get(e.get("type", ""), "📝")
        lines.append(f"{icon} [{e.get('ts')}] [{e.get('type')}] {e.get('file')}: {e.get('summary')}")
        if e.get("detail"):
            lines.append(f"   └─ {e['detail']}")
    return "\n".join(lines)


# ======== 智能去重增强功能 ========

def query_smart_filtered(file_path=None, entry_type=None, limit=50, include_backups=False, deduplicate=False):
    """智能过滤查询 - 可选去重功能
    
    Args:
        file_path: 按文件路径过滤
        entry_type: 按类型过滤（FIX/OPT/NEW/DEL/ROLLBACK）
        limit: 返回条数上限
        include_backups: 是否包含BACKUP类型
        deduplicate: 是否开启智能去重（仅对BACKUP类型有效）
    
    Returns:
        list[dict]
    """
    results = []
    
    # 查询主日志（不过滤去重）
    if os.path.isfile(AUDIT_FILE):
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if file_path and entry.get("file") != file_path:
                        continue
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    results.append(entry)
                except json.JSONDecodeError:
                    continue
                if len(results) >= limit and not include_backups:
                    return results
    
    # 需要包含备份记录
    backup_entries = []
    if include_backups and os.path.isfile(BACKUP_AUDIT_FILE):
        with open(BACKUP_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if file_path and entry.get("file") != file_path:
                        continue
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    backup_entries.append(entry)
                except json.JSONDecodeError:
                    continue
    
    # 如果不需要去重，直接加入结果
    if not deduplicate or not backup_entries:
        results.extend(backup_entries[:limit - len(results)])
        return results[:limit]
    
    # 智能去重逻辑（仅对BACKUP类型）
    deduplicated = []
    file_time_map = {}  # 文件路径 -> 最后保留的时间
    
    for entry in backup_entries:
        if entry.get("type") != "BACKUP":
            deduplicated.append(entry)
            continue
        
        file_path_val = entry.get("file", "")
        timestamp_str = entry.get("ts", "")
        
        if not timestamp_str:
            deduplicated.append(entry)
            continue
        
        try:
            entry_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            deduplicated.append(entry)
            continue
        
        # 检查是否应去重（同一文件30分钟内的重复备份）
        if file_path_val in file_time_map:
            last_time = file_time_map[file_path_val]
            time_diff = (entry_time - last_time).total_seconds() / 60  # 分钟
            
            if time_diff >= 30:  # 只保留30分钟以外的备份
                deduplicated.append(entry)
                file_time_map[file_path_val] = entry_time
            # 否则（30分钟内）丢弃，视为重复备份
        else:
            deduplicated.append(entry)
            file_time_map[file_path_val] = entry_time
    
    results.extend(deduplicated[:limit - len(results)])
    return results[:limit]


def get_statistics():
    """获取审计统计信息"""
    stats = {
        "total_entries": 0,
        "by_type": {},
        "by_month": {},
        "files_most_changed": [],
        "recent_activity": []
    }
    
    try:
        # 读取所有条目
        all_entries = []
        
        # 主日志
        if os.path.isfile(AUDIT_FILE):
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            all_entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        
        # 备份日志（不包含内容相似的重复项）
        if os.path.isfile(BACKUP_AUDIT_FILE):
            dedup_map = {}  # 文件路径 -> 最近时间
            with open(BACKUP_AUDIT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if entry.get("type") == "BACKUP":
                                file_path = entry.get("file", "")
                                timestamp = entry.get("ts", "")
                                if file_path and timestamp:
                                    try:
                                        entry_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                        # 同一文件每个小时只保留一条记录
                                        hour_key = f"{file_path}_{entry_time.strftime('%Y-%m-%d %H')}"
                                        if hour_key not in dedup_map:
                                            all_entries.append(entry)
                                            dedup_map[hour_key] = entry_time
                                    except ValueError:
                                        all_entries.append(entry)
                                else:
                                    all_entries.append(entry)
                            else:
                                all_entries.append(entry)
                        except json.JSONDecodeError:
                            continue
        
        stats["total_entries"] = len(all_entries)
        
        # 按类型统计
        type_count = {}
        for entry in all_entries:
            entry_type = entry.get("type", "UNKNOWN")
            type_count[entry_type] = type_count.get(entry_type, 0) + 1
        stats["by_type"] = type_count
        
        # 按月统计
        month_count = {}
        for entry in all_entries:
            timestamp = entry.get("ts", "")
            if timestamp:
                try:
                    month_key = timestamp[:7]  # YYYY-MM
                    month_count[month_key] = month_count.get(month_key, 0) + 1
                except Exception:
                    pass
        stats["by_month"] = month_count
        
        # 文件变更频率
        file_count = {}
        for entry in all_entries:
            file_path = entry.get("file", "")
            if file_path:
                file_count[file_path] = file_count.get(file_path, 0) + 1
        
        top_files = sorted(file_count.items(), key=lambda x: x[1], reverse=True)[:10]
        stats["files_most_changed"] = [{"file": f, "count": c} for f, c in top_files]
        
        # 最近活动（最近7天）
        today = datetime.now()
        recent_entries = []
        for entry in all_entries[-20:][::-1]:  # 最近的20条
            timestamp = entry.get("ts", "")
            if timestamp:
                try:
                    entry_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                    days_diff = (today - entry_time).days
                    if days_diff <= 7:
                        recent_entries.append(entry)
                except Exception:
                    pass
        
        stats["recent_activity"] = recent_entries
        
    except Exception as e:
        stats["error"] = f"统计生成失败: {str(e)}"
    
    return stats


# ======== 向前兼容的增强功能 ========

def generate_smart_report():
    """生成智能审计报告"""
    try:
        stats = get_statistics()
        
        report_lines = []
        report_lines.append("=== 金水谣系统审计智能报告 ===")
        report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"总记录数: {stats['total_entries']} 条")
        report_lines.append("")
        
        report_lines.append("📊 变更类型分布:")
        for entry_type, count in sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True):
            emoji = {
                "FIX": "🔧", "OPT": "⚡", "NEW": "✨", 
                "DEL": "🗑️", "ROLLBACK": "⏪", "BACKUP": "💾"
            }.get(entry_type, "📝")
            report_lines.append(f"  {emoji} {entry_type}: {count} 条")
        
        report_lines.append("")
        report_lines.append("📈 月度活动:")
        for month, count in sorted(stats['by_month'].items(), reverse=True)[:6]:
            report_lines.append(f"  📅 {month}: {count} 次变更")
        
        report_lines.append("")
        report_lines.append("🏆 最活跃文件（前10）:")
        for file_data in stats.get('files_most_changed', [])[:10]:
            report_lines.append(f"  📄 {file_data['file']}: {file_data['count']} 次修改")
        
        # 计算数据清洁度分数
        if 'by_type' in stats:
            backup_count = stats['by_type'].get('BACKUP', 0)
            manual_count = sum(count for type_, count in stats['by_type'].items() if type_ != 'BACKUP')
            total_count = stats['total_entries']
            
            if total_count > 0:
                clean_score = min(100, 100 - (backup_count / total_count * 50))
                data_cleanliness = f"{clean_score:.1f}分"
                if clean_score >= 80:
                    data_cleanliness += " (优秀 ✓)"
                elif clean_score >= 60:
                    data_cleanliness += " (良好)"
                else:
                    data_cleanliness += " (需优化)"
                
                report_lines.append("")
                report_lines.append("🧹 数据清洁度分析:")
                report_lines.append(f"  手动记录: {manual_count} 条")
                report_lines.append(f"  自动备份: {backup_count} 条")
                report_lines.append(f"  清洁度评分: {data_cleanliness}")
        
        return "\n".join(report_lines)
    
    except Exception as e:
        return f"报告生成失败: {str(e)}"


def get_backup_pattern_analysis():
    """分析备份模式，识别异常行为"""
    if not os.path.exists(BACKUP_AUDIT_FILE):
        return {"error": "备份日志文件不存在"}
    
    analysis = {
        "frequent_backups": [],
        "peak_hours": [],
        "total_backup_entries": 0,
        "unique_files_backed_up": set()
    }
    
    try:
        hourly_count = {}
        file_frequency = {}
        
        with open(BACKUP_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "BACKUP":
                        analysis["total_backup_entries"] += 1
                        file_path = entry.get("file", "")
                        timestamp = entry.get("ts", "")
                        
                        if file_path:
                            analysis["unique_files_backed_up"].add(file_path)
                            file_frequency[file_path] = file_frequency.get(file_path, 0) + 1
                        
                        if timestamp:
                            try:
                                hour_key = timestamp[11:13]  # 提取小时部分
                                hourly_count[hour_key] = hourly_count.get(hour_key, 0) + 1
                            except Exception:
                                pass
                except json.JSONDecodeError:
                    continue
        
        # 识别频繁备份的文件（超过5次）
        for file_path, count in file_frequency.items():
            if count > 5:
                analysis["frequent_backups"].append({
                    "file": file_path,
                    "backup_count": count,
                    "suggestion": "可能需要调整备份频率或添加去重逻辑"
                })
        
        # 找出高峰时段
        if hourly_count:
            sorted_hours = sorted(hourly_count.items(), key=lambda x: x[1], reverse=True)[:3]
            analysis["peak_hours"] = [{"hour": f"{h}:00", "count": c} for h, c in sorted_hours]
        
        analysis["unique_files_backed_up"] = list(analysis["unique_files_backed_up"])
        
        return analysis
    
    except Exception as e:
        return {"error": f"分析失败: {str(e)}"}
