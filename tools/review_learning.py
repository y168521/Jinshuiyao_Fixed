# -*- coding: utf-8 -*-
"""金水谣 · 审查自学习模块 + 反馈 API

ReviewLearning 类：从审查反馈中学习，持续优化模式置信度/阈值/白名单。
反馈 API 路由：接收开发者对审查意见的反馈（接受/驳回/部分接受/漏报）。

数据存储：金水谣数据/review/review_feedback.jsonl（追加式）
"""
import json
import os
import time
import threading
import copy

# ─── 项目根 ───
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 数据路径 ───
_REVIEW_DATA_DIR = os.path.join(_PROJECT_ROOT, "金水谣数据", "review")
_FEEDBACK_FILE = os.path.join(_REVIEW_DATA_DIR, "review_feedback.jsonl")
_PATTERN_LIB_PATH = os.path.join(_PROJECT_ROOT, "knowledge", "pattern_library.json")
_METRICS_FILE = os.path.join(_REVIEW_DATA_DIR, "review_metrics.json")
_DECISIONS_FILE = os.path.join(_PROJECT_ROOT, "金水谣数据", "log", "ai_decisions.md")

# ─── 锁 ───
_learning_lock = threading.Lock()


class ReviewLearning:
    """从审查反馈中学习，持续优化"""

    def __init__(self):
        self.patterns = self._load_patterns()
        self.metrics = self._load_metrics()

    def _load_patterns(self):
        """加载模式库"""
        if not os.path.isfile(_PATTERN_LIB_PATH):
            return {}
        with open(_PATTERN_LIB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {p["id"]: p for p in data.get("patterns", [])}

    def _save_patterns(self):
        """保存模式库（线程安全）"""
        data = {"patterns": list(self.patterns.values()), "metadata": {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}}
        with open(_PATTERN_LIB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_metrics(self):
        """加载度量数据"""
        if not os.path.isfile(_METRICS_FILE):
            return {"total_reviews": 0, "total_feedbacks": 0,
                    "false_positive_count": 0, "miss_count": 0,
                    "accepted_count": 0, "rejected_count": 0,
                    "weekly_stats": []}
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_metrics(self):
        """保存度量数据"""
        with open(_METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.metrics, f, ensure_ascii=False, indent=2)

    def analyze_feedback(self, review_id, feedback):
        """
        分析反馈并学习

        feedback 结构:
        {
          "accepted": [issue_id_1, ...],     # 开发者接受的审查意见
          "rejected": [issue_id_2, ...],      # 开发者驳回的（误报）
          "partial": [{"id": ..., "note": "优先级应该是P1而非P0"}],
          "missed": ["文件:行 有类似问题但没报出来"]  # 漏报
        }
        """
        os.makedirs(_REVIEW_DATA_DIR, exist_ok=True)

        # 1. 记录原始反馈
        feedback_record = {
            "review_id": review_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "accepted": feedback.get("accepted", []),
            "rejected": feedback.get("rejected", []),
            "partial": feedback.get("partial", []),
            "missed": feedback.get("missed", []),
        }
        with open(_FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_record, ensure_ascii=False) + "\n")

        # 2. 更新度量
        self.metrics["total_feedbacks"] += 1
        self.metrics["accepted_count"] += len(feedback.get("accepted", []))
        self.metrics["rejected_count"] += len(feedback.get("rejected", []))
        self.metrics["false_positive_count"] += len(feedback.get("rejected", []))
        self.metrics["miss_count"] += len(feedback.get("missed", []))

        # 3. 误报分析 → 降低模式置信度/加白名单
        with _learning_lock:
            self.patterns = self._load_patterns()  # 重新加载最新
            for rejected_id in feedback.get("rejected", []):
                # 查找对应模式
                for pid, pat in self.patterns.items():
                    if rejected_id.startswith(pid):
                        old_conf = pat.get("confidence", 0.7)
                        new_conf = max(0.0, old_conf - 0.1)
                        self.patterns[pid]["confidence"] = new_conf
                        # 置信度低于 0.3 自动降级为 P3
                        if new_conf < 0.3 and pat.get("severity", "P2") != "P3":
                            self.patterns[pid]["severity"] = "P3"
                            self.patterns[pid]["_auto_downgraded"] = True

            # 4. 漏报分析 → 新增模式种子
            for missed_desc in feedback.get("missed", []):
                new_id = f"PAT-NEW-{int(time.time()) % 10000:04d}"
                self.patterns[new_id] = {
                    "id": new_id,
                    "category": "unclassified",
                    "name": f"漏报发现: {missed_desc[:30]}",
                    "description": missed_desc,
                    "detection": {"method": "manual", "rule": "待人工确认"},
                    "severity": "P1",  # 漏报默认 P1（重要但待确认）
                    "confidence": 0.5,
                    "fix_hint": "待确认",
                    "historical_refs": [review_id],
                    "occurrence_count": 0,
                    "status": "pending_confirmation",  # 需人工确认后改为 active
                }

            # 5. 优先级调整
            for partial in feedback.get("partial", []):
                note = partial.get("note", "")
                # 从反馈中提取建议的优先级
                for sev in ["P0", "P1", "P2", "P3"]:
                    if sev in note:
                        issue_id = partial.get("id", "")
                        for pid, pat in self.patterns.items():
                            if issue_id.startswith(pid):
                                self.patterns[pid]["severity"] = sev
                                self.patterns[pid]["_priority_adjusted"] = True
                                break

            # 6. 写入 ai_decisions.md（复用现有 Layer A+B）
            self._write_decision_card(review_id, feedback)

            # 7. 保存
            self._save_patterns()
            self._save_metrics()

        return {"status": "ok", "patterns_adjusted": len(feedback.get("rejected", [])),
                "new_patterns": len(feedback.get("missed", [])),
                "priority_adjusted": len(feedback.get("partial", []))}

    def _write_decision_card(self, review_id, feedback):
        """写入 ai_decisions 决策卡"""
        card = f"""
### 审查反馈学习 [{review_id}] · {time.strftime('%Y-%m-%d %H:%M')}

- **属主**: ReviewLearning 自学习模块
- **做了什么**: 分析开发者对审查报告的反馈，调整模式置信度/优先级/新增漏报模式
- **为什么(根因)**: 误报降低信任度→加白名单；漏报→新模式种子；优先级偏差→人工校正
- **验证**: 接受{len(feedback.get('accepted', []))}条/驳回{len(feedback.get('rejected', []))}条/漏报{len(feedback.get('missed', []))}条
- **坑**: 误报过多会降低开发者对审查的信任；漏报需人工确认后再激活
- **有效方法**: 反馈→分析→调整→再审查的闭环机制
- **关联文件**: {_FEEDBACK_FILE}, {_PATTERN_LIB_PATH}, {_METRICS_FILE}
- **关联总索引**: JS-{time.strftime('%Y%m%d')}-NN

---
"""
        if os.path.isfile(_DECISIONS_FILE):
            with open(_DECISIONS_FILE, "a", encoding="utf-8") as f:
                f.write(card)
        else:
            os.makedirs(os.path.dirname(_DECISIONS_FILE), exist_ok=True)
            with open(_DECISIONS_FILE, "w", encoding="utf-8") as f:
                f.write("# AI 决策记录\n\n" + card)

    def get_review_metrics(self, period_days=7):
        """计算审查效果指标"""
        self.metrics = self._load_metrics()

        total_feedbacks = self.metrics.get("total_feedbacks", 0)
        accepted = self.metrics.get("accepted_count", 0)
        rejected = self.metrics.get("rejected_count", 0)
        missed = self.metrics.get("miss_count", 0)

        total_issues = accepted + rejected
        false_positive_rate = (rejected / total_issues * 100) if total_issues > 0 else 0
        acceptance_rate = (accepted / total_issues * 100) if total_issues > 0 else 0
        miss_rate = (missed / (missed + accepted) * 100) if (missed + accepted) > 0 else 0

        # 模式命中率
        hits_file = os.path.join(_REVIEW_DATA_DIR, "pattern_hits.jsonl")
        pattern_hit_count = 0
        if os.path.isfile(hits_file):
            with open(hits_file, "r", encoding="utf-8") as f:
                pattern_hit_count = sum(1 for _ in f)

        return {
            "total_reviews": self.metrics.get("total_reviews", 0),
            "total_feedbacks": total_feedbacks,
            "false_positive_rate": round(false_positive_rate, 1),
            "miss_rate": round(miss_rate, 1),
            "acceptance_rate": round(acceptance_rate, 1),
            "pattern_hit_count": pattern_hit_count,
            "active_patterns": len([p for p in self.patterns.values() if p.get("status", "active") == "active"]),
            "pending_patterns": len([p for p in self.patterns.values() if p.get("status") == "pending_confirmation"]),
        }


# ─── HTTP 反馈 API 处理器 ───
def handle_review_feedback(handler, parsed):
    """POST /api/review/feedback — 提交审查反馈"""
    try:
        body = handler._read_body()
        data = json.loads(body)
        review_id = data.get("review_id", "")
        feedback = data.get("feedback", {})

        if not review_id:
            handler._send_json({"error": "review_id 必填", "ok": False}, 400)
            return

        learner = ReviewLearning()
        result = learner.analyze_feedback(review_id, feedback)

        handler._send_json({"ok": True, "result": result})
    except Exception as e:
        handler._send_json({"error": f"反馈处理失败: {e}", "ok": False}, 500)


def handle_review_trigger(handler, parsed):
    """POST /api/review/trigger — 触发审查（走全局统一入口 run_review）"""
    try:
        body = handler._read_body()
        data = json.loads(body) if body else {}
        mode = data.get("mode", "quick")
        files = data.get("files", None)
        enable_learning = data.get("enable_learning", True)

        # 走全局统一入口（确保 Pipeline 顺序、metrics、自学习全局一致）
        from run_review import run_review
        report = run_review(mode=mode, files=files, enable_learning=enable_learning)

        handler._send_json({"ok": True, "report": report})
    except Exception as e:
        handler._send_json({"error": f"审查触发失败: {e}", "ok": False}, 500)


def handle_review_dashboard(handler, parsed):
    """GET /api/review/dashboard — 审查仪表盘数据"""
    try:
        learner = ReviewLearning()
        metrics = learner.get_review_metrics()

        # 最近审查历史
        history_file = os.path.join(_REVIEW_DATA_DIR, "review_history.jsonl")
        recent_reviews = []
        if os.path.isfile(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-10:]:
                try:
                    recent_reviews.append(json.loads(line))
                except Exception:
                    pass

        # 模式命中 TOP5
        hits_file = os.path.join(_REVIEW_DATA_DIR, "pattern_hits.jsonl")
        pattern_hits_summary = {}
        if os.path.isfile(hits_file):
            with open(hits_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        hit = json.loads(line)
                        pid = hit.get("pattern_id", "")
                        pattern_hits_summary[pid] = pattern_hits_summary.get(pid, 0) + 1
                    except Exception:
                        pass

        # 排序取 TOP5
        top_patterns = sorted(pattern_hits_summary.items(), key=lambda x: x[1], reverse=True)[:5]
        top_patterns_detail = []
        for pid, count in top_patterns:
            pat = learner.patterns.get(pid, {})
            top_patterns_detail.append({
                "pattern_id": pid,
                "name": pat.get("name", pid),
                "hits": count,
                "confidence": pat.get("confidence", 0),
                "severity": pat.get("severity", "P2"),
            })

        dashboard = {
            "metrics": metrics,
            "recent_reviews": recent_reviews,
            "top_patterns": top_patterns_detail,
            "patterns_total": len(learner.patterns),
        }

        handler._send_json({"ok": True, "dashboard": dashboard})
    except Exception as e:
        handler._send_json({"error": f"仪表盘数据获取失败: {e}", "ok": False}, 500)


def handle_review_patterns(handler, parsed):
    """GET /api/review/patterns — 查模式库"""
    try:
        learner = ReviewLearning()
        patterns_list = list(learner.patterns.values())

        # 过滤参数
        qs = urllib.parse.parse_qs(parsed.query)
        category = qs.get("category", [None])[0]
        severity = qs.get("severity", [None])[0]
        status = qs.get("status", [None])[0]

        if category:
            patterns_list = [p for p in patterns_list if p.get("category") == category]
        if severity:
            patterns_list = [p for p in patterns_list if p.get("severity") == severity]
        if status:
            patterns_list = [p for p in patterns_list if p.get("status", "active") == status]

        handler._send_json({"ok": True, "patterns": patterns_list, "total": len(patterns_list)})
    except Exception as e:
        handler._send_json({"error": f"模式库查询失败: {e}", "ok": False}, 500)


import urllib.parse  # noqa: E402 — needed by handle_review_patterns
