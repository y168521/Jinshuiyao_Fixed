# -*- coding: utf-8 -*-
"""金水谣 · 任务智能路由器（纯标准库，零外部依赖）

给定一个自然语言任务，判断【最省的实现路径】，避免一上来就花 DeepSeek：

  - data_fetch : 联网抓取公开数据（免费）—— 行情 / 彩票 / 天气 / 新闻等
  - knowledge  : 查本地知识库 / 提示词库（免费）—— 解释名词 / 回忆过往经验
  - local      : 纯本地能做的琐事（重命名 / 格式化 / 计算 / 统计）
  - deepseek   : 需要 AI 推理或写代码（花钱）—— 改逻辑 / 修 bug / 写函数
  - clarify    : 描述太含糊，先问清楚再决定

只做“判断”，不真正执行；具体执行由各对应模块负责。这是「全局调度中枢」的判断核心。
"""
import re

# 各类任务的关键词（命中即加分；免费类优先，写代码类明确需要 AI）
_KW = {
    "data_fetch": ["抓取", "爬取", "下载", "行情", "彩票", "双色球", "大乐透",
                   "股票", "基金", "股价", "天气", "新闻", "实时数据", "最新数据", "数据"],
    "knowledge": ["什么是", "解释", "讲解", "是什么意思", "记得", "之前记",
                  "查一下知识库", "知识库里", "回忆", "总结一下我们", "之前讨论"],
    "local": ["重命名", "移动文件", "改文件名", "格式化", "去尾随",
              "计算", "算一下", "统计一下", "列出", "列一下"],
    "deepseek": ["改代码", "加注释", "优化", "修复", "修bug", "重构", "写个函数",
                 "写代码", "实现", "补全", "调试", "排错", "生成代码"],
}

_REASON = {
    "data_fetch": "检测到“抓取 / 行情 / 数据”类需求，可走免费联网数据抓取，不花 DeepSeek。",
    "knowledge": "检测到“查询 / 解释 / 回忆”类需求，可走免费本地知识库，不花 DeepSeek。",
    "local": "检测到本地可做的琐事，直接本地处理，不花 DeepSeek。",
    "deepseek": "检测到写代码 / 改逻辑类需求，需要 AI 推理，走 DeepSeek（按防浪费规则计额度）。",
    "clarify": "任务描述太含糊，无法确定最省路径，建议先说清楚要做什么。",
}


def classify(task_text):
    """返回 {path, reason, scores}。path ∈ data_fetch/knowledge/local/deepseek/clarify。"""
    t = (task_text or "").lower()
    scores = {}
    for cat, kws in _KW.items():
        s = sum(1 for kw in kws if kw in t)
        if s:
            scores[cat] = s
    if not scores:
        return {"path": "clarify", "reason": _REASON["clarify"], "scores": scores}
    # 免费路径优先；但“写代码”类明确必须 AI，优先级最高
    best = max(scores, key=lambda c: (scores[c], c == "deepseek"))
    return {"path": best, "reason": _REASON.get(best, ""), "scores": scores}


def _self_test():
    print("== jinshuiyao_router 自测 ==")
    cases = [
        ("帮我抓一下今天双色球开奖结果", "data_fetch"),
        ("什么是共形预测", "knowledge"),
        ("帮我把这个文件重命名", "local"),
        ("给这段 Python 加注释并优化性能", "deepseek"),
        ("随便弄弄", "clarify"),
        ("下载最近股票行情并画个图", "data_fetch"),
        ("回忆之前我们记过的漂移检测内容", "knowledge"),
        ("写个函数读取 csv 并去重", "deepseek"),
    ]
    for text, expect in cases:
        r = classify(text)
        assert r["path"] == expect, (text, r)
        print(f"✓ {text[:28]:<34s} -> {r['path']}")
    print("jinshuiyao_router 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
