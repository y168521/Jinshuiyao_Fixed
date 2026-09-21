# -*- coding: utf-8 -*-
"""金水谣系统 - 预测记录端点

预测记录（历史预测沉淀 + 复盘报告）。
纯标准库实现，数据存放在 Jinshuiyao_Fixed/predictions/predictions.json

路由（POST）：
  /api/prediction/record   — 保存一条预测记录
  /api/prediction/list     — 列出历史预测
  /api/prediction/outcome  — 更新预测结果标注

路由（GET）：
  /api/prediction/stats    — 预测统计（按域聚合 + 按天趋势）
  /api/prediction/history  — 各域逐日命中率 + 置信度
  /api/prediction/hit-trend — 各彩种滚动命中率趋势（W63补107）
"""
import os
import json
import datetime
import logging

from ..config import PREDICTION_DIR, PREDICTION_FILE, _PRED_DOMAIN_KEYWORDS, _PRED_LOCK

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 预测领域检测 & 数据操作
# ---------------------------------------------------------------------------
def _detect_prediction_domain(text):
    """根据关键词判断用户问题属于哪个预测领域"""
    t = (text or '').lower()
    for dom, kws in _PRED_DOMAIN_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in t:
                return dom
    return None


def _load_predictions():
    try:
        if os.path.isfile(PREDICTION_FILE):
            with open(PREDICTION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


# W63补100 / JS-20260817-01：彩票选号预测记录（金水谣数据/predictions.json）
# 与 Q&A 预测沉淀（predictions/predictions.json）是两个数据源，
# 统计端点合并两者，避免引擎看板只显示 Q&A 的几条记录。
_LOT_PREDICTION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    '金水谣数据', 'predictions.json')


def _load_lottery_predictions_raw():
    """读取彩票选号预测原始记录列表（保留 coverage/hits 等字段，供滚动命中率计算）"""
    try:
        if not os.path.isfile(_LOT_PREDICTION_FILE):
            return []
        with open(_LOT_PREDICTION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_lottery_predictions():
    """读取彩票选号预测记录并统一为统计结构（lot → domain，reviewed+hits → outcome）"""
    data = _load_lottery_predictions_raw()
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        rec = {
            'id': f"LOT-{r.get('lot', '?')}-{r.get('period', '?')}",
            'time': r.get('time') or r.get('date') or '',
            'domain': r.get('lot') or 'other',
        }
        reviewed = r.get('reviewed')
        hits = int(r.get('hits') or 0)
        if reviewed:
            rec['outcome'] = 'hit' if hits > 0 else 'miss'
        else:
            rec['outcome'] = None
        out.append(rec)
    return out


def _load_all_records():
    """统计口径统一读取：Q&A 预测沉淀 + 彩票选号预测（供 stats/history 聚合）"""
    return _load_predictions() + _load_lottery_predictions()


def _save_predictions(records):
    os.makedirs(PREDICTION_DIR, exist_ok=True)
    tmp = PREDICTION_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PREDICTION_FILE)


def _domain_confidence(domain, window=90):
    """计算某预测领域的置信度（可解释代理指标）。

    定义：该领域最近 window 天内「已标注」预测的命中率。
    数据不足（<5 条已标注）时回退到全局命中率；仍不足则返回 None。

    说明：本系统是 Q&A 式预测沉淀，无多模型共识信号，故以
    「历史同领域命中率」作为置信度代理——UI 据此展示可信档位，
    避免给用户虚假精度。这是诚实可落地的取值，而非凭空概率。
    """
    records = _load_all_records()
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=window)

    def _pt(rec):
        try:
            return datetime.datetime.strptime((rec.get('time') or '')[:19], '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None

    dom_labeled = [r for r in records
                   if r.get('domain') == domain
                   and _pt(r) and _pt(r) >= cutoff
                   and r.get('outcome') in ('hit', 'miss')]
    if len(dom_labeled) >= 5:
        hits = sum(1 for r in dom_labeled if r.get('outcome') == 'hit')
        return round(hits / len(dom_labeled), 4)

    all_labeled = [r for r in records
                   if _pt(r) and _pt(r) >= cutoff
                   and r.get('outcome') in ('hit', 'miss')]
    if len(all_labeled) >= 5:
        hits = sum(1 for r in all_labeled if r.get('outcome') == 'hit')
        return round(hits / len(all_labeled), 4)

    return None


def record_prediction(question, answer, domain=None, confidence=None):
    """保存一条预测记录（自动识别领域，非预测类不记录），返回记录id或None

    confidence: 可选置信度（0~1）。缺省时按领域历史命中率自动估算。
    """
    try:
        if domain is None:
            domain = _detect_prediction_domain(question)
        if not domain or domain == 'other':
            return None
        now = datetime.datetime.now()
        rec_id = 'P-' + now.strftime('%Y%m%d-%H%M%S') + '-' + '%06d' % now.microsecond
        if confidence is None:
            confidence = _domain_confidence(domain)
        rec = {
            'id': rec_id,
            'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'domain': domain,
            'question': (question or '')[:200],
            'answer': (answer or '')[:600],
            'confidence': confidence,
            'outcome': None,
        }
        with _PRED_LOCK:
            records = _load_predictions()
            records.append(rec)
            if len(records) > 2000:
                records = records[-2000:]
            _save_predictions(records)
        return rec_id
    except Exception as e:
        # JS-20260921-03：改用 logger（原 print 只进控制台，不落日志文件，事后无法追溯）
        logger.error('[prediction] 记录失败: %s', e)
        return None


def list_predictions(limit=200):
    with _PRED_LOCK:  # P2-3: 读也加锁，与写路径统一原子读
        records = _load_predictions()
        records.sort(key=lambda r: r.get('time', ''), reverse=True)
        return records[:limit]


def set_prediction_outcome(rec_id, outcome):
    """更新某条预测的结果标注：hit / miss / None"""
    with _PRED_LOCK:
        records = _load_predictions()
        for r in records:
            if r.get('id') == rec_id:
                r['outcome'] = outcome
                _save_predictions(records)
                return True
    return False


# ---------------------------------------------------------------------------
# POST 路由处理函数
# ---------------------------------------------------------------------------
def handle_prediction_record(handler):
    """POST /api/prediction/record — 保存一条预测记录"""
    cl = int(handler.headers.get('Content-Length', 0) or 0)
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler._send_json({"ok": False, "error": "无效的JSON"})
        return
    rid = record_prediction(data.get('question', ''), data.get('answer', ''), data.get('domain'))
    handler._send_json({"ok": bool(rid), "id": rid})


def handle_prediction_list(handler):
    """POST /api/prediction/list — 列出历史预测"""
    cl = int(handler.headers.get('Content-Length', 0) or 0)
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {}
    limit = int(data.get('limit', 200) or 200)
    recs = list_predictions(limit)
    handler._send_json({"ok": True, "records": recs, "total": len(recs)})


def handle_prediction_outcome(handler):
    """POST /api/prediction/outcome — 更新预测结果标注"""
    cl = int(handler.headers.get('Content-Length', 0) or 0)
    body = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else '{}'
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        handler._send_json({"ok": False, "error": "无效的JSON"})
        return
    ok = set_prediction_outcome(data.get('id'), data.get('outcome'))
    handler._send_json({"ok": ok})


# ---------------------------------------------------------------------------
# GET 路由处理函数
# ---------------------------------------------------------------------------
def handle_prediction_stats(handler):
    """GET /api/prediction/stats — 预测统计（按域聚合 + 趋势）

    W63补100 / JS-20260817-01：合并彩票选号预测（金水谣数据/predictions.json），
    避免看板只统计 Q&A 沉淀的少量记录。
    """
    try:
        records = _load_all_records()

        # 按 domain 聚合
        by_domain = {}
        for rec in records:
            dom = rec.get('domain') or 'other'
            if dom not in by_domain:
                by_domain[dom] = {'total': 0, 'hits': 0, 'misses': 0}
            by_domain[dom]['total'] += 1
            outcome = rec.get('outcome')
            if outcome == 'hit':
                by_domain[dom]['hits'] += 1
            elif outcome == 'miss':
                by_domain[dom]['misses'] += 1

        # 计算命中率
        for dom, d in by_domain.items():
            labeled = d['hits'] + d['misses']
            d['rate'] = round(d['hits'] / labeled, 4) if labeled > 0 else 0.0

        # 最近30天趋势
        now = datetime.datetime.now()
        trend = []
        for i in range(29, -1, -1):
            day = (now - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
            trend.append({'date': day, 'total': 0, 'hits': 0})

        date_index = {t['date']: t for t in trend}
        for rec in records:
            rec_date = (rec.get('time') or '')[:10]
            if rec_date in date_index:
                date_index[rec_date]['total'] += 1
                if rec.get('outcome') == 'hit':
                    date_index[rec_date]['hits'] += 1

        # 总体统计
        total_all = len(records)
        hits_all = sum(1 for r in records if r.get('outcome') == 'hit')
        misses_all = sum(1 for r in records if r.get('outcome') == 'miss')
        labeled_all = hits_all + misses_all
        overall = {
            'total': total_all,
            'hits': hits_all,
            'misses': misses_all,
            'rate': round(hits_all / labeled_all, 4) if labeled_all > 0 else 0.0,
        }

        handler._send_json({
            "ok": True,
            "by_domain": by_domain,
            "trend": trend,
            "overall": overall,
        })
    except Exception as e:
        handler._send_json({"ok": False, "error": f"预测统计失败: {e}"}, 500)


def handle_prediction_history(handler):
    """GET /api/prediction/history?days=90 — 各域历史命中率趋势 + 置信度

    返回每个预测领域最近 days 天的逐日序列（total/hits/misses/rate）
    及当前置信度（_domain_confidence 估算），供前端绘制置信度走势图。
    数据不足的日子 rate 为 None，前端应作断点而非画 0。
    """
    try:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(handler.path).query)
        try:
            days = int((qs.get('days') or ['90'])[0])
        except Exception:
            days = 90
        days = max(7, min(days, 365))

        now = datetime.datetime.now()
        records = _load_all_records()

        domains = sorted({r.get('domain') for r in records
                          if r.get('domain') and r.get('domain') != 'other'})

        series = {}
        for dom in domains:
            arr = []
            for i in range(days - 1, -1, -1):
                day = (now - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
                arr.append({'date': day, 'total': 0, 'hits': 0, 'misses': 0, 'rate': None})
            idx = {a['date']: a for a in arr}
            for r in records:
                d = (r.get('time') or '')[:10]
                if d in idx and r.get('domain') == dom:
                    idx[d]['total'] += 1
                    if r.get('outcome') == 'hit':
                        idx[d]['hits'] += 1
                    elif r.get('outcome') == 'miss':
                        idx[d]['misses'] += 1
            for a in arr:
                lab = a['hits'] + a['misses']
                a['rate'] = round(a['hits'] / lab, 4) if lab > 0 else None
            series[dom] = arr

        confidence = {dom: _domain_confidence(dom) for dom in domains}

        handler._send_json({
            "ok": True,
            "days": days,
            "series": series,
            "confidence": confidence,
        })
    except Exception as e:
        handler._send_json({"ok": False, "error": f"预测历史失败: {e}"}, 500)


def handle_prediction_hit_trend(handler):
    """GET /api/prediction/hit-trend?window=30 — 各彩种滚动命中率趋势

    W63补107 / JS-20260823-01：按彩种×期号聚合复盘覆盖率（engines.lottery_stats.
    rolling_hit_trend 纯计算），返回最近 window 期逐期均值序列 + 与前一窗口对比的
    up/down/flat 趋势，用于区分「小样本运气波动」与「持续退化」。纯只读端点。
    """
    try:
        from urllib.parse import urlparse, parse_qs
        from engines.lottery_stats import rolling_hit_trend
        qs = parse_qs(urlparse(handler.path).query)
        try:
            window = int((qs.get('window') or ['30'])[0])
        except Exception:
            window = 30
        lots = rolling_hit_trend(_load_lottery_predictions_raw(), window)
        handler._send_json({"ok": True, "window": window, "lots": lots})
    except Exception as e:
        handler._send_json({"ok": False, "error": f"滚动命中率趋势失败: {e}"}, 500)
