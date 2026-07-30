# -*- coding: utf-8 -*-
"""文件操作自动记录（轻量、零依赖）

统一记录模型目录下的新增 / 修改 / 删除 / 打开 / 运行 等操作，
追加写入 金水谣数据/log/operation_log.jsonl，便于事后追溯与防同类错误复发。

用法：
    import operation_log
    operation_log.log_file_op("add", "Jinshuiyao_Fixed/xxx.py", detail="新建模块")
    operation_log.log_file_op("open", "启动金水谣助手.bat", mode="run")
"""
import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, '金水谣数据', 'log', 'operation_log.jsonl')

# 操作类型：add(新增) / modify(修改) / delete(删除) / open(打开查看) / run(运行)
VALID_OPS = ('add', 'modify', 'delete', 'open', 'run')


def log_file_op(op, path, detail='', level='info'):
    """记录一次文件操作（追加到 JSONL 日志，失败静默不阻塞主流程）。

    op:      add / modify / delete / open / run
    path:    相对模型根目录的路径（或绝对路径）
    detail:  补充说明
    level:   info / warn / error
    返回生成的记录字典。
    """
    rec = {
        'time': datetime.datetime.now().isoformat(timespec='seconds'),
        'op': op if op in VALID_OPS else 'other',
        'path': path,
        'detail': detail,
        'level': level if level in ('info', 'warn', 'error') else 'info',
    }
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return rec


def recent(limit=50):
    """读取最近 limit 条操作记录（最新在前）。"""
    if not os.path.isfile(LOG_PATH):
        return []
    out = []
    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return out
    return out[-limit:][::-1]


if __name__ == '__main__':
    for r in recent(20):
        print(f"[{r['time']}] {r['op']:6} {r['level']:5} {r['path']}  {r.get('detail','')}")
