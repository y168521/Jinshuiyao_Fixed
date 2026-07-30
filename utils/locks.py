# -*- coding: utf-8 -*-
"""金水谣系统 - 线程锁统一管理

所有全局线程锁集中在此模块定义，禁止在其他文件中重复创建。
其他模块通过 from utils.locks import json_lock, corr_lock, preds_lock 导入使用。
"""
import threading

# JSON数据文件读写锁（保护 lot_data/*.json 的并发写入）
json_lock = threading.Lock()

# 关联矩阵锁（保护 correlation_matrix.json 的读写）
corr_lock = threading.Lock()

# 预测记录锁（保护 predictions 列表的并发修改）
preds_lock = threading.Lock()

# 日志轮转锁（保护 JSONL 日志文件的轮转操作，防止并发重命名冲突）
log_rotate_lock = threading.Lock()
