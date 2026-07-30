# -*- coding: utf-8 -*-
"""金水谣系统 - OCR文本智能导入"""
import re
from fetchers.fetcher import Fetcher
from utils.number_utils import fix_period_5to7, fix_period_short_to7, is_valid_period
from config import LOTTERY_RULES


class LotteryDataImporter:
    LOT_MAP = {
        "排列3": "排列三", "排列三": "排列三", "排三": "排列三", "排3": "排列三", "p3": "排列三",
        "3d": "福彩3D", "福彩3d": "福彩3D", "福彩3D": "福彩3D",
        "双色球": "双色球", "ssq": "双色球",
        "大乐透": "大乐透", "dlt": "大乐透",
        "七星彩": "七星彩", "7星彩": "七星彩",
        "快乐8": "快乐8", "kl8": "快乐8",
        "七乐彩": "七乐彩",
    }
    LOT_NAMES_RE = r'(双色球|大乐透|福彩3[Dd]|排列3|排列三|排三|P3|排3|七乐彩|七星彩|7星彩|快乐8|ssq|dlt|kl8)'
    ANALYSIS_KW = r'不要蓝|杀号|杀码|推荐|预测|胆码|拖码|参考|防|本期|上期|历史|走势|分析|精选|实票|晒票'
    SKIP_KW = r'排列5|排列五|时时彩|11选5|快3|赛车|PK10|六合彩'

    @staticmethod
    def _clean_line(line):
        line = line.strip()
        line = re.sub(r'【[^】]*】', '', line)
        line = re.sub(r'（[^）]*）', '', line)
        line = re.sub(r'\([^)]*\)', '', line)
        line = re.sub(r'开奖号[码]?[:：]\s*', '', line)
        line = re.sub(r'中国福利彩票|开奖信息|今日公告', '', line, flags=re.I)
        line = re.sub(r'第[一二三四五六七八九十]+张图片文字', '', line, flags=re.I)
        line = re.sub(r'^\d+[\.\、]\s*', '', line)
        line = re.sub(r'\s+', ' ', line).strip()
        return line

    @staticmethod
    def _norm_lot(name):
        if not name:
            return None
        name = name.lower()
        return LotteryDataImporter.LOT_MAP.get(name, name)

    @staticmethod
    def _detect_lot(line):
        m = re.search(LotteryDataImporter.LOT_NAMES_RE, line, re.I)
        if m:
            return LotteryDataImporter._norm_lot(m.group(1))
        return None

    @staticmethod
    def _extract_period(line):
        m = re.search(r'(\d{3,7})\s*期', line)
        if m:
            return m.group(1)
        m = re.search(r'\b(20[2-9]\d{4})\b', line)
        if m:
            return m.group(1)
        m = re.search(r'\b(20[2-9]\d{3})\b', line)
        if m:
            return m.group(1)
        m = re.match(r'^\s*(\d{3,4})(?:\s|$)', line)
        if m:
            return m.group(1)
        m = re.search(r'\b(\d{3,6})\b', line)
        if m and not re.match(r'^0+$', m.group(1)):
            return m.group(1)
        return None

    @staticmethod
    def _extract_numbers(line, lot, period_str=None):
        clean = line
        for kw in ['排列3', '排列三', '排三', 'P3', '排3', '3D', '福彩3D', '七乐彩', '七星彩', '7星彩', '快乐8', '双色球', '大乐透', 'ssq', 'dlt', 'kl8']:
            clean = re.sub(rf'{kw}\s*', '', clean, flags=re.I)
        if period_str:
            clean = re.sub(r'(?<!\d)' + re.escape(str(period_str)) + r'(?!\d)', ' ', clean)
        clean = re.sub(r'[-−—–]', '+', clean)

        has_plus = '+' in clean
        if has_plus:
            parts = clean.split('+', 1)
            main_raw = parts[0]
            spec_raw = parts[1] if len(parts) > 1 else ''
        else:
            main_raw = clean
            spec_raw = ''

        def smart_split_digits(s):
            result = []
            for token in re.findall(r'\d+', s):
                tl = len(token)
                if lot in ('福彩3D', '排列三') and all(0 <= int(c) <= 9 for c in token):
                    for c in token:
                        result.append(int(c))
                    continue
                if tl >= 4 and tl % 2 == 0:
                    pairs = [int(token[i:i + 2]) for i in range(0, tl, 2)]
                    if lot in ('快乐8',) and all(1 <= p <= 80 for p in pairs):
                        result.extend(pairs)
                        continue
                    if lot in ('双色球', '大乐透') and all(1 <= p <= 35 for p in pairs):
                        result.extend(pairs)
                        continue
                n = int(token)
                if lot in ('福彩3D', '排列三'):
                    if 0 <= n <= 9:
                        result.append(n)
                elif lot == '七乐彩':
                    if 1 <= n <= 30:
                        result.append(n)
                elif lot == '快乐8':
                    if 1 <= n <= 80:
                        result.append(n)
                elif lot in ('双色球', '大乐透'):
                    if 1 <= n <= 35:
                        result.append(n)
                elif lot == '七星彩':
                    if 0 <= n <= 14:
                        result.append(n)
                else:
                    result.append(n)
            return result

        main_nums = smart_split_digits(main_raw)
        spec_nums = smart_split_digits(spec_raw) if has_plus else []

        return main_nums, spec_nums, has_plus

    @staticmethod
    def _format_and_save(lot, period_str, main_nums, spec_nums, has_plus):
        rule = LOTTERY_RULES.get(lot)
        if not rule:
            return False

        if lot == "七乐彩":
            if len(main_nums) < 7:
                return False
            main_nums = main_nums[:7]
            nums_str = ",".join(f"{x:02d}" for x in sorted(main_nums))
            if spec_nums:
                nums_str += f"+{spec_nums[0]:02d}"
        elif lot in ("福彩3D", "排列三"):
            if len(main_nums) < 3:
                return False
            main_nums = main_nums[:3]
            nums_str = ",".join(f"{x:02d}" for x in main_nums)
        elif lot == "快乐8":
            if len(main_nums) < 10:
                return False
            main_nums = main_nums[:20]
            nums_str = ",".join(f"{x:02d}" for x in sorted(main_nums))
        elif lot in ("双色球", "大乐透"):
            red_cnt = rule["red"][2]
            blue_cnt = rule.get("blue", [0, 0, 1])[2]
            if len(main_nums) < red_cnt:
                return False
            red_nums = main_nums[:red_cnt]
            blue_nums = spec_nums[:blue_cnt] if spec_nums else main_nums[red_cnt:red_cnt + blue_cnt]
            nums_str = ",".join(f"{x:02d}" for x in sorted(red_nums))
            if blue_nums:
                nums_str += "+" + ",".join(f"{x:02d}" for x in sorted(blue_nums))
        elif lot == "七星彩":
            if len(main_nums) < 7:
                return False
            nums = main_nums[:7]
            if nums[6] > 14:
                nums[6] = nums[6] % 10
            nums_str = ",".join(f"{x:02d}" for x in nums)
        else:
            nums_str = ",".join(f"{x:02d}" for x in main_nums)

        period = int(period_str) if isinstance(period_str, str) else period_str
        if isinstance(period, int) and 100 <= period < 10000:
            period = fix_period_short_to7(period)
        elif isinstance(period, int) and 10000 <= period < 100000:
            period = fix_period_5to7(period)
        elif isinstance(period, int) and 100000 <= period < 1000000:
            period = fix_period_5to7(period)

        Fetcher()._save(lot, [{"period": period, "lottery": lot, "nums": nums_str, "time": ""}])
        return True

    @staticmethod
    def parse_and_save(text):
        imported = 0
        errors = []

        sections = re.split(r'\n\s*(?=图\d+)', text.strip())
        if len(sections) == 1 and not re.match(r'^图\d+', sections[0]):
            sections = [text.strip()]

        for section in sections:
            lines_raw = section.strip().split('\n')
            clean_lines = []
            for line in lines_raw:
                line = line.strip()
                if not line:
                    continue
                if re.match(r'^\d{4}年\d{1,2}月\d{1,2}日', line):
                    continue
                if re.search(r'星期[一二三四五六日]', line):
                    continue
                if re.search(LotteryDataImporter.ANALYSIS_KW, line):
                    has_period = LotteryDataImporter._extract_period(line)
                    num_count = len(re.findall(r'\b\d+\b', line))
                    if not (has_period and num_count >= 3):
                        continue
                if re.search(LotteryDataImporter.SKIP_KW, line):
                    continue
                nums_only = re.findall(r'\b\d\b', line)
                if len(nums_only) == 5 and not re.search(r'双色球|大乐透|福彩3D|排列3|排列三|七乐彩|七星彩|快乐8', line, re.I):
                    continue
                line = LotteryDataImporter._clean_line(line)
                if line:
                    clean_lines.append(line)

            if not clean_lines:
                continue

            section_lot = None
            section_text = ' '.join(clean_lines[:3])
            section_lot = LotteryDataImporter._detect_lot(section_text)

            records = []
            i = 0
            while i < len(clean_lines):
                line = clean_lines[i]
                period = LotteryDataImporter._extract_period(line)
                if not period:
                    i += 1
                    continue

                lot = LotteryDataImporter._detect_lot(line) or section_lot
                if not lot:
                    all_nums = re.findall(r'\d+', line)
                    if len(all_nums) == 3 and all(0 <= int(n) <= 9 for n in all_nums):
                        lot = "福彩3D"
                    elif len(all_nums) >= 10 and all(1 <= int(n) <= 80 for n in all_nums):
                        lot = "快乐8"
                    elif len(all_nums) >= 7 and all(1 <= int(n) <= 30 for n in all_nums):
                        lot = "七乐彩"
                    else:
                        i += 1
                        continue
                section_lot = lot

                merged_text = line
                j = i + 1
                while j < len(clean_lines):
                    next_line = clean_lines[j]
                    next_period = LotteryDataImporter._extract_period(next_line)
                    next_lot = LotteryDataImporter._detect_lot(next_line)
                    if next_period and not next_lot:
                        break
                    if next_lot:
                        break
                    merged_text += ' ' + next_line
                    j += 1

                main_nums, spec_nums, has_plus = LotteryDataImporter._extract_numbers(merged_text, lot, period)
                if main_nums:
                    records.append((period, main_nums, spec_nums, has_plus))

                i = j

            for period_str, main_nums, spec_nums, has_plus in records:
                lot = section_lot
                if LotteryDataImporter._format_and_save(lot, period_str, main_nums, spec_nums, has_plus):
                    imported += 1
                else:
                    preview = f"{lot or '?'} {period_str} 号码不足"
                    errors.append(preview)

        return imported, errors