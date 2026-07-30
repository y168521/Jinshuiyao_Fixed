# -*- coding: utf-8 -*-
"""金水谣系统 - 方案管理器"""
import os
from utils.safe_json import safe_load_json, safe_write_json
from config import SCHEME_CACHE


class SchemeManager:
    def __init__(self):
        self.schemes = {}
        self._dirty = False
        self.load()

    def load(self):
        if os.path.exists(SCHEME_CACHE):
            try:
                self.schemes = safe_load_json(SCHEME_CACHE, default={})
            except Exception:
                self.schemes = {}

    def save(self):
        self._dirty = True

    def flush(self):
        if not self._dirty:
            return
        self._dirty = False
        try:
            safe_write_json(SCHEME_CACHE, self.schemes)
        except Exception:
            pass

    def add_scheme(self, name, lot, period, nums):
        if name not in self.schemes:
            self.schemes[name] = {"hits": [], "total": 0}
        self.schemes[name]["hits"].append(0)
        self.schemes[name]["total"] += 1
        self.save()

    def update_hit(self, name, hits):
        if name in self.schemes:
            self.schemes[name]["hits"].append(hits)
            self.schemes[name]["total"] += 1
            self.save()