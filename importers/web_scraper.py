# -*- coding: utf-8 -*-
"""金水谣系统 - 网页抓取最新开奖"""
import requests


class WebScraper:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})

    def scrape_all(self, callback):
        for eng, name in [("ssq", "双色球"), ("dlt", "大乐透"), ("3d", "福彩3D"), ("pls", "排列三"), ("qxc", "七星彩"), ("kl8", "快乐8"), ("qlc", "七乐彩")]:
            try:
                r = self.s.get(f"http://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name={eng}&issueCount=1", timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("result"):
                        item = data["result"][0]
                        period = int(item["code"])
                        nums = f"{item['red']}+{item['blue']}" if name in ["双色球", "大乐透"] else item["red"]
                        callback(name, period, nums, "开奖数据", "中彩网")
            except Exception:
                continue