#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防止操作失忆的智能提示系统
用途：提供实时的工作记忆增强，防止开发过程中的"失忆"问题
"""

import os
import sys
import json
import re
import time
import threading
import readline
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque

class MemoryAssistSystem:
    """记忆辅助系统"""
    
    def __init__(self, base_path=None):
        """初始化记忆辅助系统"""
        if base_path is None:
            base_path = Path(__file__).parent.parent
        self.base_path = Path(base_path)
        
        # 文件路径
        self.memory_log_path = self.base_path / "金水谣数据" / "log" / "assist_memory.jsonl"
        self.context_snapshot_path = self.base_path / "金水谣数据" / "log" / "context_snapshot.json"
        self.prompt_log_path = self.base_path / "金水谣数据" / "log" / "smart_prompts.log"
        self.reminder_config_path = self.base_path / "金水谣数据" / "reminder_config.json"
        
        # 记忆缓冲区
        self.short_term_memory = deque(maxlen=50)  # 短期记忆，最多50个项目
        self.working_context = {
            'current_task': None,
            'current_files': [],
            'recent_commands': [],
            'active_sessions': [],
            'pending_reminders': []
        }
        
        # 配置
        self.config = {
            'auto_context_snapshot_interval': 60,  # 自动上下文快照间隔（秒）
            'max_short_term_memory_items': 50,     # 短期记忆最大项目数
            'prompt_triggers': {
                'forget_risk_threshold': 5,        # 遗忘风险阈值（分钟）
                'context_change_threshold': 3,      # 上下文变更阈值（文件数）
                'task_complexity_threshold': 0.7,  # 任务复杂度阈值
            },
            'reminder_types': {
                'pre_change_reminder': True,
                'context_reminder': True,
                'progress_reminder': True,
                'integration_reminder': True
            }
        }
        
        # 自动保存线程
        self.auto_save_thread = None
        self.running = False
        
        # 知识库（预定义的最佳实践和常见模式）
        self.knowledge_base = {
            'pre_change_checklist': [
                "📋 修改前检查清单：",
                "1. 运行预检工具: python scripts/prechange_analyzer.py 目标文件 '变更描述'",
                "2. 检查相关文件: 查看会受影响的其他文件",
                "3. 考虑影响: 分析变更对系统的影响",
                "4. 准备回滚: 思考如何快速回退此变更",
                "5. 更新记录: 准备好更新CHANGELOG和审计日志"
            ],
            'commit_best_practices': [
                "✅ 提交最佳实践：",
                "1. 小步提交: 每次提交只解决一个问题",
                "2. 清晰描述: 提交信息要清晰说明'为什么'和'做了什么'",
                "3. 关联记录: 在CHANGELOG中添加对应条目",
                "4. 引用审计: 在审计日志中引用CHANGELOG条目",
                "5. 测试验证: 提交前运行基本测试"
            ],
            'debugging_patterns': [
                "🔍 调试模式：",
                "1. 重现步骤: 明确如何重现问题",
                "2. 缩小范围: 缩小问题所在的范围",
                "3. 假设验证: 建立并验证假设",
                "4. 记录进展: 记录每一步调试发现",
                "5. 总结模式: 总结问题解决模式"
            ],
            'review_guidelines': [
                "🧐 代码审查指南：",
                "1. 检查功能: 变更是否实现预期功能",
                "2. 代码质量: 是否符合编码标准和风格",
                "3. 测试覆盖: 是否有相应的测试",
                "4. 文档更新: 是否有相应的文档更新",
                "5. 性能影响: 是否影响系统性能"
            ]
        }
        
        # 确保目录存在
        self.memory_log_path.parent.mkdir(exist_ok=True, parents=True)
    
    def start_assist_service(self):
        """启动记忆辅助服务"""
        print("=" * 70)
        print("🧠 启动智能记忆辅助系统")
        print("=" * 70)
        
        # 加载配置
        self._load_config()
        
        # 记录启动
        self._log_memory_event('system_start', {
            'timestamp': datetime.now().isoformat(),
            'config': self.config
        })
        
        print(f"📅 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📚 知识库条目: {len(self.knowledge_base)} 类")
        print(f"📊 短期记忆容量: {self.config['max_short_term_memory_items']} 个项目")
        print("")
        
        # 初始化上下文
        self._initialize_context()
        
        # 启动自动保存线程
        self.running = True
        self.auto_save_thread = threading.Thread(target=self._auto_context_snapshot_worker)
        self.auto_save_thread.daemon = True
        self.auto_save_thread.start()
        
        print("✅ 记忆辅助服务已启动")
        print("   自动上下文快照: 每60秒一次")
        print("   实时记忆跟踪: 启用")
        print("   智能提示: 启用")
        print("")
        
        return True
    
    def stop_assist_service(self):
        """停止记忆辅助服务"""
        self.running = False
        
        if self.auto_save_thread:
            self.auto_save_thread.join(timeout=2)
        
        # 保存最终快照
        self._save_context_snapshot()
        
        # 记录停止
        self._log_memory_event('system_stop', {
            'timestamp': datetime.now().isoformat(),
            'short_term_memory_size': len(self.short_term_memory),
            'working_context': self.working_context
        })
        
        print("⏹️  记忆辅助服务已停止")
        
        return True
    
    def track_development_session(self, session_name=None, task_description=None):
        """跟踪开发会话"""
        if not session_name:
            session_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        session_info = {
            'session_id': session_name,
            'start_time': datetime.now().isoformat(),
            'task_description': task_description or '未指定任务',
            'active_files': [],
            'completed_steps': [],
            'current_step': None,
            'notes': []
        }
        
        # 添加到工作上下文
        self.working_context['current_session'] = session_name
        self.working_context['active_sessions'].append(session_info)
        
        # 记录事件
        self._log_memory_event('session_start', session_info)
        
        # 输出提示
        print(f"\n🎬 开始跟踪会话: {session_name}")
        if task_description:
            print(f"📝 任务描述: {task_description}")
        
        # 给出初始建议
        self._provide_initial_guidance(task_description)
        
        return session_name
    
    def record_file_access(self, file_path, action='open'):
        """记录文件访问"""
        file_info = {
            'file_path': file_path,
            'action': action,
            'timestamp': datetime.now().isoformat(),
            'session_id': self.working_context.get('current_session')
        }
        
        # 添加到短期记忆
        self.short_term_memory.append({
            'type': 'file_access',
            'timestamp': datetime.now().isoformat(),
            'data': file_info
        })
        
        # 更新工作上下文
        if file_path not in self.working_context['current_files']:
            self.working_context['current_files'].append(file_path)
        
        # 检查是否需要上下文提醒
        if len(self.working_context['current_files']) > self.config['prompt_triggers']['context_change_threshold']:
            self._trigger_context_reminder()
        
        # 记录事件
        self._log_memory_event('file_access', file_info)
        
        return True
    
    def record_command(self, command, context=None):
        """记录命令执行"""
        command_info = {
            'command': command,
            'timestamp': datetime.now().isoformat(),
            'context': context or 'unknown',
            'session_id': self.working_context.get('current_session')
        }
        
        # 添加到短期记忆
        memory_item = {
            'type': 'command',
            'timestamp': datetime.now().isoformat(),
            'data': command_info
        }
        self.short_term_memory.append(memory_item)
        
        # 更新工作上下文
        if len(self.working_context['recent_commands']) >= 10:
            self.working_context['recent_commands'].pop(0)
        self.working_context['recent_commands'].append(command_info)
        
        # 记录事件
        self._log_memory_event('command', command_info)
        
        return True
    
    def record_decision(self, decision, reasoning=None, alternatives=None):
        """记录决策"""
        decision_info = {
            'decision': decision,
            'reasoning': reasoning,
            'alternatives': alternatives or [],
            'timestamp': datetime.now().isoformat(),
            'session_id': self.working_context.get('current_session')
        }
        
        # 添加重要决策到短期记忆
        memory_item = {
            'type': 'decision',
            'timestamp': datetime.now().isoformat(),
            'data': decision_info,
            'importance': 'high' if '重要' in decision or '关键' in decision else 'medium'
        }
        self.short_term_memory.append(memory_item)
        
        # 记录事件
        self._log_memory_event('decision', decision_info)
        
        # 给出相关建议
        self._provide_decision_feedback(decision_info)
        
        return True
    
    def record_issue(self, issue_description, severity='medium', context=None):
        """记录问题"""
        issue_info = {
            'description': issue_description,
            'severity': severity,
            'timestamp': datetime.now().isoformat(),
            'context': context or self.working_context.get('current_files', []),
            'session_id': self.working_context.get('current_session'),
            'status': 'open'
        }
        
        # 添加问题到短期记忆
        memory_item = {
            'type': 'issue',
            'timestamp': datetime.now().isoformat(),
            'data': issue_info
        }
        self.short_term_memory.append(memory_item)
        
        # 记录事件
        self._log_memory_event('issue', issue_info)
        
        # 给出问题解决指导
        self._provide_issue_guidance(issue_info)
        
        return True
    
    def add_session_note(self, note, category='info'):
        """添加会话笔记"""
        note_info = {
            'note': note,
            'category': category,
            'timestamp': datetime.now().isoformat(),
            'session_id': self.working_context.get('current_session')
        }
        
        # 添加到活跃会话
        for session in self.working_context['active_sessions']:
            if session['session_id'] == self.working_context.get('current_session'):
                session['notes'].append(note_info)
                break
        
        # 记录事件
        self._log_memory_event('note', note_info)
        
        return True
    
    def set_current_task(self, task_description, complexity=0.5):
        """设置当前任务"""
        task_info = {
            'description': task_description,
            'complexity': complexity,
            'start_time': datetime.now().isoformat(),
            'session_id': self.working_context.get('current_session'),
            'status': 'active'
        }
        
        # 更新工作上下文
        self.working_context['current_task'] = task_info
        
        # 记录事件
        self._log_memory_event('task_set', task_info)
        
        # 检查是否需要任务复杂度提醒
        if complexity > self.config['prompt_triggers']['task_complexity_threshold']:
            self._trigger_complex_task_reminder(task_info)
        
        print(f"\n🎯 设置当前任务: {task_description}")
        print(f"📈 任务复杂度: {complexity * 100:.0f}%")
        
        return True
    
    def mark_task_step_completed(self, step_description, notes=None):
        """标记任务步骤完成"""
        step_info = {
            'description': step_description,
            'completion_time': datetime.now().isoformat(),
            'notes': notes,
            'session_id': self.working_context.get('current_session')
        }
        
        # 添加到活跃会话
        for session in self.working_context['active_sessions']:
            if session['session_id'] == self.working_context.get('current_session'):
                session['completed_steps'].append(step_info)
                break
        
        # 记录事件
        self._log_memory_event('step_completed', step_info)
        
        # 给出进度反馈
        self._provide_progress_feedback()
        
        print(f"\n✅ 完成步骤: {step_description}")
        if notes:
            print(f"📝 备注: {notes}")
        
        return True
    
    def provide_context_reminder(self):
        """提供上下文提醒"""
        print("\n" + "=" * 70)
        print("🧠 上下文提醒")
        print("=" * 70)
        
        # 显示当前会话信息
        current_session = self.working_context.get('current_session')
        if current_session:
            print(f"📋 当前会话: {current_session}")
            sessions = [s for s in self.working_context['active_sessions'] if s['session_id'] == current_session]
            if sessions:
                session = sessions[0]
                print(f"📝 任务描述: {session.get('task_description', '未指定')}")
                print(f"📊 完成步骤: {len(session.get('completed_steps', []))}个")
                print(f"📎 笔记数量: {len(session.get('notes', []))}条")
        
        # 显示当前任务
        current_task = self.working_context.get('current_task')
        if current_task:
            print(f"\n🎯 当前任务: {current_task.get('description', '未指定')}")
            print(f"📈 任务复杂度: {current_task.get('complexity', 0) * 100:.0f}%")
            start_time = current_task.get('start_time')
            if start_time:
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    duration = datetime.now() - start_dt
                    print(f"⏱️  任务已进行: {duration.total_seconds() // 60:.0f}分钟")
                except Exception:
                    pass
        
        # 显示当前文件
        current_files = self.working_context.get('current_files', [])
        if current_files:
            print(f"\n📁 当前关注文件 ({len(current_files)}个):")
            for i, file_path in enumerate(current_files[:5]):
                print(f"  {i+1}. {file_path}")
            if len(current_files) > 5:
                print(f"  ... 还有 {len(current_files) - 5} 个文件")
        else:
            print(f"\n📁 当前关注文件: 无")
        
        # 显示最近命令
        recent_commands = self.working_context.get('recent_commands', [])
        if recent_commands:
            print(f"\n💻 最近命令 ({len(recent_commands)}个):")
            for i, cmd in enumerate(recent_commands[-3:]):
                command_text = cmd.get('command', '')[50:]
                if len(command_text) > 50:
                    command_text = command_text[:50] + '...'
                print(f"  {i+1}. {command_text}")
        
        # 显示短期记忆摘要
        recent_memory = list(self.short_term_memory)[-3:] if self.short_term_memory else []
        if recent_memory:
            print(f"\n🧠 近期记忆 ({len(self.short_term_memory)}个项目):")
            for i, memory in enumerate(reversed(recent_memory)):
                memory_type = memory.get('type', 'unknown')
                memory_time = memory.get('timestamp', '')
                if memory_time:
                    try:
                        mem_dt = datetime.fromisoformat(memory_time.replace('Z', '+00:00'))
                        time_ago = datetime.now() - mem_dt
                        time_text = f"{time_ago.total_seconds() // 60:.0f}分钟前"
                    except Exception:
                        time_text = ''
                
                if memory_type == 'file_access':
                    file_path = memory.get('data', {}).get('file_path', '')
                    print(f"  📁 {time_text}: 访问 {file_path}")
                elif memory_type == 'decision':
                    decision = memory.get('data', {}).get('decision', '')[:40]
                    print(f"  🤔 {time_text}: 决策 {decision}...")
                elif memory_type == 'issue':
                    issue = memory.get('data', {}).get('description', '')[:40]
                    print(f"  ⚠️  {time_text}: 问题 {issue}...")
        
        # 显示知识库建议
        self._display_relevant_knowledge()
        
        print("=" * 70)
        
        # 记录提醒事件
        self._log_memory_event('context_reminder', {
            'timestamp': datetime.now().isoformat(),
            'context_summary': {
                'current_session': current_session,
                'current_task': current_task.get('description') if current_task else None,
                'file_count': len(current_files),
                'recent_commands_count': len(recent_commands)
            }
        })
        
        return True
    
    def show_session_summary(self, session_id=None):
        """显示会话摘要"""
        if not session_id:
            session_id = self.working_context.get('current_session')
        
        if not session_id:
            print("⚠️  没有活跃会话")
            return False
        
        # 查找会话
        sessions = [s for s in self.working_context['active_sessions'] if s['session_id'] == session_id]
        if not sessions:
            print(f"⚠️  未找到会话: {session_id}")
            return False
        
        session = sessions[0]
        
        print("\n" + "=" * 70)
        print(f"📊 会话摘要: {session_id}")
        print("=" * 70)
        
        # 基本信息
        start_time = session.get('start_time', '')
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                duration = datetime.now() - start_dt
                duration_mins = duration.total_seconds() // 60
                duration_hours = duration_mins // 60
                duration_remain = duration_mins % 60
                
                print(f"⏱️  时长: {duration_hours:.0f}小时{duration_remain:.0f}分钟")
            except Exception:
                pass
        
        print(f"📝 任务描述: {session.get('task_description', '未指定')}")
        
        # 完成步骤
        completed_steps = session.get('completed_steps', [])
        print(f"✅ 完成步骤: {len(completed_steps)}个")
        
        if completed_steps:
            print("\n📋 步骤详情:")
            for i, step in enumerate(completed_steps[:5]):
                step_time = step.get('completion_time', '')
                time_text = ''
                if step_time:
                    try:
                        step_dt = datetime.fromisoformat(step_time.replace('Z', '+00:00'))
                        time_text = step_dt.strftime('%H:%M')
                    except Exception:
                        pass
                
                print(f"  {i+1}. [{time_text}] {step.get('description', '')}")
                if step.get('notes'):
                    print(f"     备注: {step.get('notes')}")
            
            if len(completed_steps) > 5:
                print(f"     ... 还有 {len(completed_steps) - 5} 个步骤")
        
        # 笔记
        notes = session.get('notes', [])
        if notes:
            print(f"\n📝 笔记: {len(notes)}条")
            for i, note in enumerate(notes[:3]):
                note_time = note.get('timestamp', '')
                time_text = ''
                if note_time:
                    try:
                        note_dt = datetime.fromisoformat(note_time.replace('Z', '+00:00'))
                        time_text = note_dt.strftime('%H:%M')
                    except Exception:
                        pass
                
                category_emoji = {'warning': '⚠️', 'important': '🔥', 'todo': '📝', 'info': 'ℹ️'}.get(note.get('category', ''), '📌')
                print(f"  {category_emoji} [{time_text}] {note.get('note', '')}")
        
        # 活跃文件
        active_files = []
        for memory_item in self.short_term_memory:
            if memory_item.get('type') == 'file_access':
                file_session = memory_item.get('data', {}).get('session_id', '')
                if file_session == session_id:
                    file_path = memory_item.get('data', {}).get('file_path', '')
                    if file_path not in active_files:
                        active_files.append(file_path)
        
        if active_files:
            print(f"\n📁 相关文件 ({len(active_files)}个):")
            for i, file_path in enumerate(active_files[:5]):
                print(f"  {i+1}. {file_path}")
            if len(active_files) > 5:
                print(f"     ... 还有 {len(active_files) - 5} 个文件")
        
        # 给出下一步建议
        self._provide_next_step_suggestions(session)
        
        print("=" * 70)
        
        return True
    
    def generate_memory_report(self, report_type='summary'):
        """生成记忆报告"""
        report_path = self.base_path / "金水谣数据" / "log" / f"memory_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        try:
            report_content = [
                "# 智能记忆辅助系统报告",
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"报告类型: {report_type}",
                "",
                "## 📊 系统状态摘要",
                f"- **短期记忆项目**: {len(self.short_term_memory)}",
                f"- **活跃会话**: {len(self.working_context.get('active_sessions', []))}",
                f"- **当前任务**: {self.working_context.get('current_task', {}).get('description', '无')}",
                f"- **关注文件**: {len(self.working_context.get('current_files', []))}",
                "",
                "## 🔄 近期活动"
            ]
            
            # 近期记忆
            recent_memory = list(self.short_term_memory)[-20:] if self.short_term_memory else []
            if recent_memory:
                report_content.append("### 最近20项记忆:")
                for i, memory in enumerate(reversed(recent_memory)):
                    memory_type = memory.get('type', 'unknown')
                    memory_time = memory.get('timestamp', '')
                    memory_data = memory.get('data', {})
                    
                    emoji_map = {
                        'file_access': '📁',
                        'command': '💻',
                        'decision': '🤔',
                        'issue': '⚠️',
                        'note': '📝',
                        'task_set': '🎯',
                        'step_completed': '✅'
                    }
                    
                    emoji = emoji_map.get(memory_type, '📌')
                    time_text = ''
                    
                    if memory_time:
                        try:
                            mem_dt = datetime.fromisoformat(memory_time.replace('Z', '+00:00'))
                            time_text = mem_dt.strftime('%H:%M')
                        except Exception:
                            pass
                    
                    line = f"{i+1}. {emoji} [{time_text}] "
                    
                    if memory_type == 'file_access':
                        line += f"访问 {memory_data.get('file_path', '')}"
                    elif memory_type == 'command':
                        line += f"执行命令: {memory_data.get('command', '')[:50]}"
                    elif memory_type == 'decision':
                        line += f"决策: {memory_data.get('decision', '')[:40]}"
                    elif memory_type == 'issue':
                        line += f"问题: {memory_data.get('description', '')[:40]}"
                    elif memory_type == 'task_set':
                        line += f"设置任务: {memory_data.get('description', '')[:40]}"
                    elif memory_type == 'step_completed':
                        line += f"完成步骤: {memory_data.get('description', '')[:40]}"
                    else:
                        line += f"{memory_type}: {str(memory_data)[:40]}"
                    
                    report_content.append(line)
            
            # 活跃会话摘要
            active_sessions = self.working_context.get('active_sessions', [])
            if active_sessions:
                report_content.append("")
                report_content.append("## 📋 活跃会话")
                for i, session in enumerate(active_sessions):
                    report_content.append(f"### 会话 {i+1}: {session.get('session_id', '未知')}")
                    report_content.append(f"- **任务描述**: {session.get('task_description', '未指定')}")
                    report_content.append(f"- **开始时间**: {session.get('start_time', '未知')}")
                    report_content.append(f"- **完成步骤**: {len(session.get('completed_steps', []))}个")
                    report_content.append(f"- **笔记数量**: {len(session.get('notes', []))}条")
                    report_content.append("")
            
            # 知识库建议
            report_content.append("")
            report_content.append("## 💡 相关建议")
            
            # 根据当前上下文选择建议
            current_task = self.working_context.get('current_task', {})
            task_desc = current_task.get('description', '').lower()
            
            if any(keyword in task_desc for keyword in ['修改', '变更', 'fix', 'update']):
                report_content.append("### 修改相关建议:")
                for line in self.knowledge_base.get('pre_change_checklist', []):
                    report_content.append(line)
                report_content.append("")
            
            if any(keyword in task_desc for keyword in ['调试', '修复', 'debug', 'fix']):
                report_content.append("### 调试建议:")
                for line in self.knowledge_base.get('debugging_patterns', []):
                    report_content.append(line)
                report_content.append("")
            
            # 通用建议
            report_content.append("### 通用开发建议:")
            for line in self.knowledge_base.get('commit_best_practices', []):
                report_content.append(line)
            
            # 写入报告
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_content))
            
            print(f"\n📄 记忆报告已生成: {report_path}")
            return report_path
            
        except Exception as e:
            print(f"生成记忆报告时出错: {e}")
            return None
    
    def _load_config(self):
        """加载配置"""
        try:
            if self.reminder_config_path.exists():
                with open(self.reminder_config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
        except Exception as e:
            print(f"加载配置时出错: {e}")
    
    def _initialize_context(self):
        """初始化上下文"""
        try:
            # 尝试加载之前的上下文快照
            if self.context_snapshot_path.exists():
                with open(self.context_snapshot_path, 'r', encoding='utf-8') as f:
                    saved_context = json.load(f)
                    
                    # 恢复工作上下文
                    if 'working_context' in saved_context:
                        self.working_context.update(saved_context['working_context'])
                    
                    # 恢复部分短期记忆
                    if 'recent_memory' in saved_context:
                        for memory_item in saved_context['recent_memory'][-10:]:
                            self.short_term_memory.append(memory_item)
                    
                    print(f"📚 已恢复之前的上下文快照")
            else:
                print(f"📚 未找到之前的上下文，初始化新上下文")
        
        except Exception as e:
            print(f"初始化上下文时出错: {e}")
    
    def _auto_context_snapshot_worker(self):
        """自动上下文快照工作线程"""
        while self.running:
            time.sleep(self.config['auto_context_snapshot_interval'])
            if self.running:
                self._save_context_snapshot()
    
    def _save_context_snapshot(self):
        """保存上下文快照"""
        try:
            snapshot = {
                'timestamp': datetime.now().isoformat(),
                'working_context': self.working_context,
                'recent_memory': list(self.short_term_memory),
                'memory_count': len(self.short_term_memory),
                'session_count': len(self.working_context.get('active_sessions', []))
            }
            
            with open(self.context_snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            print(f"保存上下文快照时出错: {e}")
    
    def _log_memory_event(self, event_type, data):
        """记录记忆事件"""
        try:
            log_entry = {
                'event_type': event_type,
                'timestamp': datetime.now().isoformat(),
                'data': data
            }
            
            with open(self.memory_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        except Exception as e:
            print(f"记录记忆事件时出错: {e}")
    
    def _provide_initial_guidance(self, task_description):
        """提供初始指导"""
        prompt_lines = [
            "\n💡 系统建议:",
            "1. 使用 `record_file_access('文件路径')` 记录文件访问",
            "2. 使用 `set_current_task('任务描述', 复杂度)` 设置当前任务",
            "3. 使用 `record_decision('决策', '理由')` 记录重要决策",
            "4. 使用 `provide_context_reminder()` 查看上下文提醒",
            "5. 使用 `show_session_summary()` 查看会话摘要",
            "6. 使用 `add_session_note('笔记', '类别')` 添加笔记"
        ]
        
        for line in prompt_lines:
            print(line)
    
    def _trigger_context_reminder(self):
        """触发上下文提醒"""
        if self.config['reminder_types']['context_reminder']:
            print("\n🔔 上下文变更提示: 关注文件较多，建议运行 `provide_context_reminder()` 查看当前上下文")
    
    def _trigger_complex_task_reminder(self, task_info):
        """触发复杂任务提醒"""
        if self.config['reminder_types']['pre_change_reminder']:
            print("\n🧩 复杂任务提醒: 检测到复杂度较高的任务，建议:")
            print("   1. 拆分为多个小任务")
            print("   2. 逐一验证每个步骤")
            print("   3. 频繁检查进度")
    
    def _provide_decision_feedback(self, decision_info):
        """提供决策反馈"""
        decision_text = decision_info.get('decision', '')
        
        # 根据决策内容给出反馈
        if '修改' in decision_text or '变更' in decision_text:
            print("\n🔧 修改决策建议:")
            print("   请确保已考虑变更的影响")
            print("   建议运行修改前分析工具")
            print("   做好回滚准备")
    
    def _provide_issue_guidance(self, issue_info):
        """提供问题指导"""
        print("\n🚨 问题解决建议:")
        print("   1. 清晰描述问题现象")
        print("   2. 缩小问题范围")
        print("   3. 记录调试步骤")
        print("   4. 总结解决方案")
    
    def _provide_progress_feedback(self):
        """提供进度反馈"""
        current_session = self.working_context.get('current_session')
        if not current_session:
            return
        
        sessions = [s for s in self.working_context['active_sessions'] if s['session_id'] == current_session]
        if not sessions:
            return
        
        session = sessions[0]
        step_count = len(session.get('completed_steps', []))
        
        if step_count == 1:
            print("🎉 很好的开始！")
        elif step_count % 3 == 0:
            print(f"📈 已完成 {step_count} 个步骤，保持进度！")
        
        # 检查长时间无操作
        last_step_time = None
        if session.get('completed_steps'):
            last_step = session['completed_steps'][-1]
            last_step_time = last_step.get('completion_time')
        
        if last_step_time:
            try:
                last_dt = datetime.fromisoformat(last_step_time.replace('Z', '+00:00'))
                time_since_last = datetime.now() - last_dt
                
                if time_since_last.total_seconds() > self.config['prompt_triggers']['forget_risk_threshold'] * 60:
                    print(f"⏰ 距上一步骤已 {time_since_last.total_seconds() // 60:.0f} 分钟，建议查看上下文")
            except Exception:
                pass
    
    def _provide_next_step_suggestions(self, session):
        """提供下一步建议"""
        print("\n💡 下一步建议:")
        
        # 检查是否有未完成的复杂任务
        current_task = self.working_context.get('current_task', {})
        task_complexity = current_task.get('complexity', 0)
        
        if task_complexity > 0.6:
            print("   1. 考虑拆分当前复杂任务")
            print("   2. 为子任务设置明确目标")
            print("   3. 制定验证计划")
        else:
            completed_steps = session.get('completed_steps', [])
            if len(completed_steps) > 0:
                print("   1. 继续执行任务计划的下一个步骤")
                print("   2. 记录当前进展")
                print("   3. 考虑是否需要调整计划")
            else:
                print("   1. 定义首个实施步骤")
                print("   2. 准备所需资源")
                print("   3. 设置完成标准")
    
    def _display_relevant_knowledge(self):
        """显示相关知识"""
        current_task = self.working_context.get('current_task', {})
        task_desc = current_task.get('description', '').lower() if current_task else ''
        
        relevant_knowledge = []
        
        if any(keyword in task_desc for keyword in ['修改', '变更', 'fix', 'update', 'optimize']):
            relevant_knowledge.extend(self.knowledge_base.get('pre_change_checklist', []))
        
        if any(keyword in task_desc for keyword in ['提交', 'commit', '推送', 'push']):
            relevant_knowledge.extend(self.knowledge_base.get('commit_best_practices', []))
        
        if any(keyword in task_desc for keyword in ['调试', '修复', 'debug']):
            relevant_knowledge.extend(self.knowledge_base.get('debugging_patterns', []))
        
        if any(keyword in task_desc for keyword in ['审查', 'review', '检查']):
            relevant_knowledge.extend(self.knowledge_base.get('review_guidelines', []))
        
        if relevant_knowledge:
            print("\n📚 相关知识库:")
            for line in relevant_knowledge[:8]:  # 限制显示行数
                print(line)

def interactive_mode():
    """交互式模式"""
    manager = MemoryAssistSystem()
    
    print("🧠 智能记忆辅助系统 - 交互式模式")
    print("=" * 50)
    print("")
    print("可用命令:")
    print("  start     - 启动辅助服务")
    print("  stop      - 停止辅助服务")
    print("  track [名] [描述] - 开始跟踪会话")
    print("  file [路径]      - 记录文件访问")
    print("  cmd [命令]       - 记录命令执行")
    print("  task [描述] [复杂度] - 设置当前任务")
    print("  step [描述]      - 标记步骤完成")
    print("  rem       - 提供上下文提醒")
    print("  sum       - 显示会话摘要")
    print("  report    - 生成记忆报告")
    print("  note [内容]      - 添加笔记")
    print("  help      - 显示帮助")
    print("  exit      - 退出系统")
    print("")
    
    manager.start_assist_service()
    
    while True:
        try:
            command = input("\n🧠 > ").strip()
            
            if not command:
                continue
            
            parts = command.split()
            cmd_type = parts[0].lower()
            
            if cmd_type == 'exit':
                print("正在停止服务...")
                manager.stop_assist_service()
                print("再见！")
                break
            
            elif cmd_type == 'start':
                manager.start_assist_service()
            
            elif cmd_type == 'stop':
                manager.stop_assist_service()
            
            elif cmd_type == 'track':
                session_name = parts[1] if len(parts) > 1 else None
                task_desc = ' '.join(parts[2:]) if len(parts) > 2 else None
                manager.track_development_session(session_name, task_desc)
            
            elif cmd_type == 'file':
                file_path = parts[1] if len(parts) > 1 else None
                if file_path:
                    manager.record_file_access(file_path)
                else:
                    print("需要文件路径")
            
            elif cmd_type == 'cmd':
                command_text = ' '.join(parts[1:]) if len(parts) > 1 else None
                if command_text:
                    manager.record_command(command_text)
                else:
                    print("需要命令内容")
            
            elif cmd_type == 'task':
                task_desc = ' '.join(parts[1:-1]) if len(parts) > 2 else None
                complexity = float(parts[-1]) if len(parts) > 1 else 0.5
                if task_desc:
                    manager.set_current_task(task_desc, complexity)
                else:
                    print("需要任务描述和复杂度")
            
            elif cmd_type == 'step':
                step_desc = ' '.join(parts[1:]) if len(parts) > 1 else None
                if step_desc:
                    manager.mark_task_step_completed(step_desc)
                else:
                    print("需要步骤描述")
            
            elif cmd_type == 'rem':
                manager.provide_context_reminder()
            
            elif cmd_type == 'sum':
                manager.show_session_summary()
            
            elif cmd_type == 'report':
                manager.generate_memory_report()
            
            elif cmd_type == 'note':
                note_content = ' '.join(parts[1:]) if len(parts) > 1 else None
                if note_content:
                    manager.add_session_note(note_content, 'info')
                else:
                    print("需要笔记内容")
            
            elif cmd_type == 'help':
                print("\n命令帮助:")
                print("  start     - 启动辅助服务")
                print("  stop      - 停止辅助服务")
                print("  track [名] [描述] - 开始跟踪会话")
                print("  file [路径]      - 记录文件访问")
                print("  cmd [命令]       - 记录命令执行")
                print("  task [描述] [复杂度] - 设置当前任务 (复杂度 0.0-1.0)")
                print("  step [描述]      - 标记步骤完成")
                print("  rem       - 提供上下文提醒")
                print("  sum       - 显示会话摘要")
                print("  report    - 生成记忆报告")
                print("  note [内容]      - 添加笔记")
                print("  exit      - 退出系统")
            
            else:
                print(f"未知命令: {cmd_type}")
                print("输入 'help' 查看可用命令")
        
        except KeyboardInterrupt:
            print("\n正在停止服务...")
            manager.stop_assist_service()
            print("再见！")
            break
        except Exception as e:
            print(f"执行命令时出错: {e}")

def main():
    """主函数"""
    import sys
    
    if len(sys.argv) > 1:
        manager = MemoryAssistSystem()
        
        if sys.argv[1] == '--interactive':
            interactive_mode()
        elif sys.argv[1] == '--start':
            manager.start_assist_service()
        elif sys.argv[1] == '--remind':
            manager.provide_context_reminder()
        elif sys.argv[1] == '--report':
            manager.generate_memory_report()
        elif sys.argv[1] == '--test':
            # 测试模式
            manager.start_assist_service()
            manager.track_development_session('测试会话', '测试记忆辅助功能')
            manager.record_file_access('scripts/test.py')
            manager.set_current_task('测试任务设置', 0.6)
            manager.record_decision('采用方案A', '因为性能更好')
            manager.mark_task_step_completed('初始化环境')
            manager.provide_context_reminder()
            manager.stop_assist_service()
        else:
            print(f"未知参数: {sys.argv[1]}")
            print("可用参数: --interactive, --start, --remind, --report, --test")
    else:
        print("智能记忆辅助系统")
        print("使用方法: python scripts/memory_assist_system.py [参数]")
        print("")
        print("参数:")
        print("  --interactive  交互式模式")
        print("  --start        启动辅助服务")
        print("  --remind       提供上下文提醒")
        print("  --report       生成记忆报告")
        print("  --test         运行测试")
        print("")
        print("示例: python scripts/memory_assist_system.py --interactive")

if __name__ == "__main__":
    main()