# -*- coding: utf-8 -*-
"""数据真实性守卫模块测试"""
import os
import sys
import json
import csv
import tempfile
import unittest

# 确保项目路径
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from core.data_truth_guard import (
    DataTruthGuard, SOURCE_REAL_API, SOURCE_CACHE, SOURCE_FALLBACK,
    SOURCE_HARDCODED, SOURCE_UNKNOWN, SOURCE_LABELS,
    get_guard, run_truth_check, format_truth_report,
)


class TestDataTruthGuardInit(unittest.TestCase):
    """初始化测试"""

    def test_singleton(self):
        """get_guard返回单例"""
        g1 = get_guard()
        g2 = get_guard()
        self.assertIs(g1, g2)

    def test_source_labels_complete(self):
        """SOURCE_LABELS覆盖所有来源类型"""
        for src in [SOURCE_REAL_API, SOURCE_CACHE, SOURCE_FALLBACK,
                     SOURCE_HARDCODED, SOURCE_UNKNOWN]:
            self.assertIn(src, SOURCE_LABELS)


class TestCheckCSVMembers(unittest.TestCase):
    """CSV比赛时效性检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []
        self.tmpdir = tempfile.mkdtemp()

    def _write_csv(self, filename, rows):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(row)
        return path

    def test_expired_match_detected(self):
        """过期比赛被检测为fail"""
        today = "2026-07-14"
        path = self._write_csv("m.csv", [
            ["match_id", "home", "away", "league", "match_time", "odds_win", "odds_draw", "odds_lose"],
            ["1", "巴西", "挪威", "世界杯", "2026-07-04 03:00", "2.5", "3.1", "2.8"],
            ["2", "法国", "西班牙", "世界杯", "2026-07-05 03:00", "2.8", "3.0", "2.6"],
        ])
        status, source, detail, action = self.guard._check_csv_matches(path, today)
        self.assertEqual(status, "fail")
        self.assertEqual(source, SOURCE_FALLBACK)
        self.assertIsNotNone(action)

    def test_today_match_passes(self):
        """今日比赛通过检测"""
        today = "2026-07-14"
        path = self._write_csv("m.csv", [
            ["match_id", "home", "away", "league", "match_time", "odds_win", "odds_draw", "odds_lose"],
            ["1", "杰尔", "维京人", "欧冠", "2026-07-14 22:00", "1.85", "3.40", "3.60"],
            ["2", "新圣徒", "萨巴赫", "欧冠", "2026-07-15 03:00", "2.10", "3.30", "3.15"],
        ])
        status, source, detail, action = self.guard._check_csv_matches(path, today)
        self.assertEqual(status, "pass")
        self.assertEqual(source, SOURCE_CACHE)

    def test_future_only_passes(self):
        """全部为未来赛事通过"""
        today = "2026-07-14"
        path = self._write_csv("m.csv", [
            ["match_id", "home", "away", "league", "match_time", "odds_win", "odds_draw", "odds_lose"],
            ["1", "英格兰", "阿根廷", "世界杯", "2026-07-16 03:00", "2.6", "3.2", "2.7"],
        ])
        status, source, detail, action = self.guard._check_csv_matches(path, today)
        self.assertEqual(status, "pass")

    def test_no_date_warns(self):
        """match_time只有时间（无日期）给出警告"""
        today = "2026-07-14"
        path = self._write_csv("m.csv", [
            ["match_id", "home", "away", "league", "match_time", "odds_win", "odds_draw", "odds_lose"],
            ["1", "杰尔", "维京人", "欧冠", "22:00", "1.85", "3.40", "3.60"],
        ])
        status, source, detail, action = self.guard._check_csv_matches(path, today)
        self.assertEqual(status, "warn")
        self.assertIn("缺少日期", detail)

    def test_missing_csv_warns(self):
        """CSV文件不存在给出警告"""
        status, source, detail, action = self.guard._check_csv_matches(
            os.path.join(self.tmpdir, "nonexistent.csv"), "2026-07-14")
        self.assertEqual(status, "warn")


class TestCheckOddsValidity(unittest.TestCase):
    """赔率合理性检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []
        self.tmpdir = tempfile.mkdtemp()

    def _write_csv(self, filename, rows):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(row)
        return path

    def test_valid_odds_pass(self):
        """合理赔率通过"""
        path = self._write_csv("o.csv", [
            ["match_id", "home_win", "draw", "away_win"],
            ["500_001", "1.85", "3.40", "3.60"],
            ["500_002", "2.10", "3.30", "3.15"],
        ])
        status, detail, action = self.guard._check_odds_validity(path)
        self.assertEqual(status, "pass")

    def test_match_id_not_treated_as_odds(self):
        """match_id字段不被当作赔率解析"""
        path = self._write_csv("o.csv", [
            ["match_id", "home_win", "draw", "away_win"],
            ["500_001", "1.85", "3.40", "3.60"],
        ])
        status, detail, action = self.guard._check_odds_validity(path)
        # match_id=500_001不应触发"超出合理范围"
        self.assertEqual(status, "pass")

    def test_same_odds_detected(self):
        """胜平负赔率完全相同被识别为假数据"""
        path = self._write_csv("o.csv", [
            ["match_id", "home_win", "draw", "away_win"],
            ["1", "2.50", "2.50", "2.50"],
        ])
        status, detail, action = self.guard._check_odds_validity(path)
        self.assertEqual(status, "fail")
        self.assertIn("相同", detail)

    def test_out_of_range_odds_fail(self):
        """赔率超出合理范围被检测"""
        path = self._write_csv("o.csv", [
            ["match_id", "home_win", "draw", "away_win"],
            ["1", "100.0", "3.0", "1.5"],
        ])
        status, detail, action = self.guard._check_odds_validity(path)
        self.assertEqual(status, "fail")


class TestCheckHardcoded(unittest.TestCase):
    """硬编码检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []
        self.tmpdir = tempfile.mkdtemp()

    def test_hardcoded_detected(self):
        """检测到硬编码兜底逻辑"""
        path = os.path.join(self.tmpdir, "data_fetcher.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("""
def _generate_real_league_matches(self):
    real_league_matches = [
        ('英超', '曼城', '利物浦', 1, 2),
        ('英超', '阿森纳', '曼联', 2, 3),
        ('西甲', '皇马', '巴萨', 1, 2),
        ('德甲', '拜仁', '多特', 1, 2),
        ('意甲', '尤文', '国米', 2, 1),
        ('法甲', '巴黎', '马赛', 1, 2),
        ('欧冠', '曼城', '皇马', 1, 2),
        ('欧冠', '拜仁', '米兰', 3, 5),
        ('英超', '热刺', '切尔西', 4, 5),
        ('西甲', '马竞', '瓦伦西亚', 3, 6),
    ]
    return []

def _generate_real_odds(self):
    win = round(random.uniform(1.1, 4.0), 2)
    odds = {'win': win}
    return odds
""")
        self.guard._jinshuiyao_dir = self.tmpdir
        status, detail, action = self.guard._check_hardcoded_football()
        self.assertEqual(status, "warn")
        self.assertIn("硬编码", detail)

    def test_clean_code_passes(self):
        """无硬编码的代码通过"""
        path = os.path.join(self.tmpdir, "data_fetcher.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("""
def fetch_from_api(self):
    response = requests.get(url)
    return response.json()
""")
        self.guard._jinshuiyao_dir = self.tmpdir
        status, detail, action = self.guard._check_hardcoded_football()
        self.assertEqual(status, "pass")


class TestCheckAkshare(unittest.TestCase):
    """akshare检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []

    def test_akshare_installed(self):
        """akshare已安装时通过"""
        status, detail, action = self.guard._check_akshare()
        # 当前环境已安装akshare 1.18.64
        self.assertEqual(status, "pass")
        self.assertIn("akshare", detail)


class TestCheckStockCache(unittest.TestCase):
    """股票缓存时效性检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []

    def test_no_cache_passes(self):
        """无缓存目录通过"""
        # 用临时路径测试（不存在cache子目录）
        self.guard._jinshuiyao_dir = tempfile.mkdtemp()
        status, detail, action = self.guard._check_stock_cache()
        self.assertEqual(status, "pass")

    def test_fresh_cache_passes(self):
        """新鲜缓存通过"""
        tmpdir = tempfile.mkdtemp()
        # 模拟 _check_stock_cache 的路径计算逻辑
        cache_dir = os.path.normpath(os.path.join(tmpdir, "..", "domains", "stock", "cache"))
        os.makedirs(cache_dir, exist_ok=True)
        # 创建一个"新鲜"的缓存文件
        with open(os.path.join(cache_dir, "sh000001.json"), "w") as f:
            f.write("{}")
        self.guard._jinshuiyao_dir = tmpdir
        status, detail, action = self.guard._check_stock_cache()
        self.assertEqual(status, "pass")
        # 清理
        os.unlink(os.path.join(cache_dir, "sh000001.json"))


class TestCheckPredictionsFile(unittest.TestCase):
    """predictions.json检测测试"""

    def setUp(self):
        self.guard = DataTruthGuard.__new__(DataTruthGuard)
        self.guard._report_items = []

    def test_valid_predictions_pass(self):
        """有效的predictions.json通过"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            json.dump({"predictions": {"ssq": [], "dlt": []}}, f)
            path = f.name
        try:
            status, detail, action = self.guard._check_predictions_file(path)
            self.assertEqual(status, "pass")
            self.assertIn("2", detail)  # 2个彩种
        finally:
            os.unlink(path)

    def test_missing_file_warns(self):
        """文件不存在警告"""
        status, detail, action = self.guard._check_predictions_file("nonexistent.json")
        self.assertEqual(status, "warn")

    def test_empty_predictions_warns(self):
        """空predictions警告"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            json.dump({"predictions": {}}, f)
            path = f.name
        try:
            status, detail, action = self.guard._check_predictions_file(path)
            self.assertEqual(status, "warn")
        finally:
            os.unlink(path)

    def test_invalid_json_fails(self):
        """非法JSON失败"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            f.write("{invalid json")
            path = f.name
        try:
            status, detail, action = self.guard._check_predictions_file(path)
            self.assertEqual(status, "fail")
        finally:
            os.unlink(path)


class TestRunFullCheck(unittest.TestCase):
    """完整检测流程测试"""

    def test_returns_valid_report_structure(self):
        """返回的报告结构正确"""
        report = run_truth_check()
        self.assertIn("timestamp", report)
        self.assertIn("overall", report)
        self.assertIn("subsystems", report)
        self.assertIn("summary", report)
        self.assertIn("source_distribution", report)
        self.assertIn("action_required", report)
        self.assertIn("football", report["subsystems"])
        self.assertIn("stock", report["subsystems"])
        self.assertIn("lottery", report["subsystems"])

    def test_overall_is_valid(self):
        """overall值有效"""
        report = run_truth_check()
        self.assertIn(report["overall"], ["healthy", "degraded", "critical"])

    def test_format_report_works(self):
        """格式化报告可调用"""
        report = run_truth_check()
        text = format_truth_report(report)
        self.assertIn("金水谣系统", text)
        self.assertIn("数据真实性", text)

    def test_each_check_has_required_fields(self):
        """每个检测项包含必要字段"""
        report = run_truth_check()
        for ss_name, ss in report["subsystems"].items():
            self.assertIn("status", ss)
            self.assertIn("checks", ss)
            for chk in ss["checks"]:
                self.assertIn("name", chk)
                self.assertIn("status", chk)
                self.assertIn("source", chk)
                self.assertIn("detail", chk)


if __name__ == "__main__":
    unittest.main()
