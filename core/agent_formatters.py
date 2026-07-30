# -*- coding: utf-8 -*-
"""金水谣引擎 - AI体结果格式化器

从 ai_agent.py 拆分出的独立模块。
包含所有子系统的结果格式化函数，将原始数据转为用户友好的中文文本。
"""

import os


def _as_float(v, default=0.0):
    """统一把任意类型转 float，避免缓存里 confidence 为字符串时 f-string 报 'Unknown format code'。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def format_lottery_result(result: dict) -> str:
    """格式化彩票预测结果"""
    lines = []
    predictions = result.get("predictions", [])
    for pred in predictions:
        lot = pred.get("lottery", "未知")
        numbers = pred.get("numbers", [])
        scheme = pred.get("scheme", "")
        lines.append(f"【{lot}】 {numbers}")
        if scheme:
            lines.append(f"  方案: {scheme}")
    summary = result.get("summary", "")
    if summary:
        lines.append(f"\n{summary}")
    return "\n".join(lines) if lines else "未生成预测结果"


def format_lottery_result_detailed(result: dict) -> str:
    """格式化彩票预测详细结果（含引擎信息）"""
    lines = []
    predictions = result.get("predictions", [])
    for pred in predictions:
        lot = pred.get("lottery", "未知")
        numbers = pred.get("numbers", [])
        scheme = pred.get("scheme", "")
        engine = pred.get("engine", "")
        confidence = pred.get("confidence", 0)
        lines.append(f"【{lot}】 {numbers}")
        if scheme:
            lines.append(f"  方案: {scheme}")
        if engine:
            lines.append(f"  引擎: {engine} | 置信度: {_as_float(confidence):.0f}%")
    summary = result.get("summary", "")
    if summary:
        lines.append(f"\n{summary}")
    return "\n".join(lines) if lines else "未生成预测结果"


def format_stock_result(fetch_result: dict, analysis: dict, target: str) -> str:
    """格式化股票行情结果"""
    lines = [f"【{target}行情】"]
    results = analysis.get("results", {})
    for symbol, info in results.items():
        indicators = info.get("indicators", {})
        trend = info.get("trend", {})
        signals = info.get("signals", [])
        price = indicators.get("latest_price", indicators.get("close", 0))
        direction = trend.get("direction", "unknown")
        strength = trend.get("strength", 0)
        dir_map = {"up": "上涨", "down": "下跌", "sideways": "震荡"}
        lines.append(f"\n{symbol}: {price}")
        lines.append(f"  趋势: {dir_map.get(direction, direction)} (强度{strength:.0f})")
        if signals:
            lines.append(f"  信号: {', '.join(signals)}")
    return "\n".join(lines) if len(lines) > 1 else "暂无行情数据"


def format_stock_picks(picks: dict) -> str:
    """格式化选股推荐"""
    lines = ["【选股推荐】"]
    predictions = picks.get("predictions", [])
    for p in predictions[:10]:
        symbol = p.get("symbol", "")
        action = p.get("action", "")
        confidence = p.get("confidence", 0)
        reason = p.get("reason", "")
        action_map = {"buy": "买入", "hold": "持有", "watch": "观望", "sell": "卖出"}
        lines.append(f"  {symbol} | {action_map.get(action, action)} | 置信度{_as_float(confidence):.0f}% | {reason}")
    return "\n".join(lines) if len(lines) > 1 else "暂无推荐"


def format_stock_technical(analysis: dict) -> str:
    """格式化技术指标"""
    lines = ["【技术指标】"]
    results = analysis.get("results", {})
    for symbol, info in results.items():
        indicators = info.get("indicators", {})
        lines.append(f"\n{symbol}:")
        for key in ["ma5", "ma20", "ma60", "macd", "kdj", "rsi", "boll"]:
            if key in indicators:
                val = indicators[key]
                if isinstance(val, dict):
                    lines.append(f"  {key.upper()}: {val}")
                else:
                    lines.append(f"  {key.upper()}: {val}")
    return "\n".join(lines) if len(lines) > 1 else "暂无技术指标数据"


def format_football_result(fetch_result: dict, generate_result: dict) -> str:
    """格式化足彩结果"""
    lines = ["【足彩分析】"]
    predictions = generate_result.get("predictions", [])
    for pred in predictions[:8]:
        home = pred.get("home", "")
        away = pred.get("away", "")
        league = pred.get("league", "")
        suggestion = pred.get("suggestion", pred.get("action", ""))
        confidence = pred.get("confidence", 0)
        lines.append(f"\n{league} | {home} vs {away}")
        lines.append(f"  推荐: {suggestion} | 置信度{confidence:.0f}%")
    summary = generate_result.get("summary", "")
    if summary:
        lines.append(f"\n{summary}")
    return "\n".join(lines) if len(lines) > 1 else "暂无赛事数据"


def format_football_odds(fetch_result: dict) -> str:
    """格式化赔率数据"""
    return "赔率分析功能需要加载赛事数据后查看。请先问'今天有什么比赛'。"


def format_music_result(result: dict) -> str:
    """格式化音乐生成结果"""
    predictions = result.get("predictions", [])
    if not predictions:
        return result.get("summary", "未生成音乐")

    pred = predictions[0]
    ptype = pred.get("type", "")

    if ptype == "melody":
        name = pred.get("name", "")
        output = pred.get("output", "")
        style = pred.get("style", "")
        bpm = pred.get("bpm", 0)
        duration = pred.get("duration_sec", 0)
        note_count = pred.get("note_count", 0)
        return (
            f"【AI音乐生成】\n\n"
            f"曲目: {name}\n"
            f"风格: {style}\n"
            f"BPM: {bpm}\n"
            f"时长: {_as_float(duration):.0f}秒\n"
            f"音符数: {note_count}\n"
            f"格式: WAV 无损\n"
            f"文件: {output}\n\n"
            f"已保存到音乐目录，可用任意播放器播放。"
        )
    elif ptype == "convert":
        return (
            f"【格式转换完成】\n\n"
            f"输出: {os.path.basename(pred.get('output', ''))}\n"
            f"格式: {pred.get('format', '')}\n"
            f"大小: {_as_float(pred.get('size_mb', 0)):.2f}MB\n"
            f"耗时: {_as_float(pred.get('time_sec', 0)):.1f}秒"
        )
    elif ptype == "normalize":
        return (
            f"【音量标准化完成】\n\n"
            f"输出: {os.path.basename(pred.get('output', ''))}\n"
            f"模式: {pred.get('mode', '')}\n"
            f"目标响度: {pred.get('target_lufs', -14)} LUFS\n"
            f"原始响度: {pred.get('original_lufs', '?')} LUFS"
        )
    elif ptype == "optimize":
        issues = pred.get("issues_fixed", [])
        issues_text = "\n".join(f"  - {i}" for i in issues) if issues else "  - 音量标准化"
        return (
            f"【智能优化完成】\n\n"
            f"输出: {os.path.basename(pred.get('output', ''))}\n"
            f"修复项目:\n{issues_text}"
        )
    else:
        return result.get("summary", "处理完成")


def format_music_analysis(analysis: dict) -> str:
    """格式化音频分析结果"""
    results = analysis.get("results", [])
    lines = [f"【音频分析】共 {len(results)} 个文件\n"]

    def fmt_dur(sec):
        sec = _as_float(sec)
        if sec <= 0:
            return "未知"
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

    for r in results[:10]:
        lines.append(f"  {r.get('file', '?')}")
        lines.append(f"    时长: {fmt_dur(r.get('duration', 0))} | "
                     f"采样率: {r.get('sample_rate', '?')}Hz | "
                     f"声道: {r.get('channels', '?')} | "
                     f"码率: {_as_float(r.get('bitrate', 0)):.0f}kbps")
        lines.append(f"    质量评分: {r.get('score', 0)}/100")

    lines.append(f"\n总时长: {fmt_dur(analysis.get('total_duration', 0))}")
    lines.append(f"总大小: {_as_float(analysis.get('total_size_mb', 0)):.2f}MB")
    lines.append(f"平均评分: {_as_float(analysis.get('avg_score', 0)):.1f}/100")
    return "\n".join(lines)


def format_extracted_result(extracted: dict) -> str:
    """格式化视频提取结果"""
    if not extracted:
        return "提取失败，未获取到内容。"
    title = extracted.get("title", "未知标题")
    content = extracted.get("content", extracted.get("text", ""))
    platform = extracted.get("platform", "")
    lines = [f"【视频文案提取】\n"]
    if platform:
        lines.append(f"平台: {platform}")
    lines.append(f"标题: {title}")
    if content:
        preview = content[:500] + ("..." if len(content) > 500 else "")
        lines.append(f"\n内容:\n{preview}")
    return "\n".join(lines)


def format_refined_result(refined: dict) -> str:
    """格式化内容提炼结果"""
    if not refined:
        return "提炼失败。"
    title = refined.get("title", "")
    summary = refined.get("summary", refined.get("content", ""))
    tags = refined.get("tags", [])
    lines = [f"【内容提炼】\n"]
    if title:
        lines.append(f"标题: {title}")
    if summary:
        lines.append(f"\n摘要:\n{summary}")
    if tags:
        lines.append(f"\n标签: {', '.join(tags)}")
    return "\n".join(lines)
