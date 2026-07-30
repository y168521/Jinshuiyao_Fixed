# -*- coding: utf-8 -*-
"""金水谣系统 - 统一期号转换工具"""
import re
import datetime


class PeriodNormalizer:
    @staticmethod
    def normalize(period_raw, lottery_name):
        """
        统一转换任意格式期号为7位 YYYYPPP 格式
        - 3位期号：补当年年份
        - 4位期号：补20前缀（YYPPP → 20YYPPP）
        - 5位期号：YYPPP → 20YYPPP（YY<50 → 20，≥50→19）
        - 6位期号：YYYPPP → 补0？→ 其实是 YYYPP → 200YYPP？这里按5位规则处理
        - >7位：取末尾7位
        """
        if isinstance(period_raw, int):
            period_raw = str(period_raw)
        ps = str(period_raw).strip()
        ps = re.sub(r'\D+', '', ps)
        if not ps:
            return None

        length = len(ps)
        if length == 3:
            cur_year = int(datetime.datetime.now().strftime("%Y"))
            return int(f"{cur_year}{ps}")
        elif length == 4:
            yy = int(ps[:2])
            prefix = "19" if yy >= 50 else "20"
            return int(prefix + ps)
        elif length == 5:
            return PeriodNormalizer._five_to_seven(ps)
        elif length == 6:
            return PeriodNormalizer._six_to_seven(ps)
        elif length > 7:
            return int(ps[-7:])
        try:
            return int(ps)
        except Exception:
            return None

    @staticmethod
    def _five_to_seven(ps):
        yy = int(ps[:2])
        prefix = "19" if yy >= 50 else "20"
        return int(prefix + ps)

    @staticmethod
    def _six_to_seven(ps):
        if len(ps) == 6:
            if ps[0] == '2' and ps[1] == '0':
                return int(ps)
            yy = int(ps[:2])
            prefix = "19" if yy >= 50 else "20"
            return int(prefix + ps)
        return int(ps)

    @staticmethod
    def validate_period(lottery_name, period_int):
        """验证转换后是否在合理范围内"""
        try:
            p = int(period_int)
        except Exception:
            return False
        ps = str(p)
        if len(ps) != 7:
            return False
        year = int(ps[:4])
        seq = int(ps[4:])
        cur_year = datetime.datetime.now().year
        if year < 2015 or year > cur_year:
            return False
        if lottery_name in ["福彩3D", "排列三", "快乐8"]:
            max_seq = 400
        elif lottery_name in ["双色球", "大乐透", "七乐彩", "七星彩"]:
            max_seq = 200
        else:
            max_seq = 400
        if seq < 1 or seq > max_seq:
            return False
        return True
