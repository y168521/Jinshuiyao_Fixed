# -*- coding: utf-8 -*-
"""MiroFish 万物知识库 - 可视化管理GUI
独立运行，不依赖金水谣其他模块。
用法: python mirofish_gui.py
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import datetime

# ---- 确保能导入 mirofish_db ----
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.join(_this_dir, "..")
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

from knowledge.mirofish_db import MiroFishDB
from core.theme import Theme

# ============================================================
# 常量
# ============================================================
CATEGORY_MAP = {
    "all":         "全部分类",
    "inspiration": "灵感库",
    "project":     "项目",
    "area":        "领域",
    "resource":    "资料",
    "skill":       "技能",
    "archive":     "归档",
}

DOMAIN_MAP = {
    "3d":       "3D",
    "lottery":  "彩票",
    "football": "足彩",
    "music":    "音乐",
    "ai":       "AI",
    "general":  "通用",
    "other":    "其他",
}

ENGINE_HOOKS = [
    "",
    "position_analysis",
    "reposition",
    "weight_calibration",
    "kill_strategy",
    "miss_breakthrough",
    "morph_constraint",
    "smart_brain",
    "backtest",
]

ENGINE_HOOK_LABELS = {
    "":                  "(无)",
    "position_analysis": "位置分析",
    "reposition":        "摆位决策",
    "weight_calibration": "权重校准",
    "kill_strategy":     "杀号策略",
    "miss_breakthrough": "遗漏突破",
    "morph_constraint":  "形态约束",
    "smart_brain":       "智能大脑",
    "backtest":          "回测分析",
}


# ============================================================
# 配置 ttk 暗色样式
# ============================================================
def setup_style():
    style = ttk.Style()
    style.theme_use("clam")

    # Treeview
    style.configure("Dark.Treeview",
                    background=Theme.BG_DEEP,
                    foreground=Theme.TEXT_PRIMARY,
                    fieldbackground=Theme.BG_DEEP,
                    rowheight=28,
                    borderwidth=0)
    style.configure("Dark.Treeview.Heading",
                    background=Theme.BG_HOVER,
                    foreground=Theme.TEXT_PRIMARY,
                    font=(Theme.FONT_FAMILY, 10, "bold"),
                    borderwidth=0)
    style.map("Dark.Treeview",
              background=[("selected", Theme.COLOR_PRIMARY_DARK),
                          ("active", Theme.BG_HOVER)],
              foreground=[("selected", Theme.BG_DEEP)])

    # 左侧分类 Treeview
    style.configure("Category.Treeview",
                    background=Theme.BG_CARD,
                    foreground=Theme.TEXT_PRIMARY,
                    fieldbackground=Theme.BG_CARD,
                    rowheight=32,
                    borderwidth=0,
                    font=(Theme.FONT_FAMILY, 11))
    style.configure("Category.Treeview.Heading",
                    background=Theme.BG_HOVER,
                    foreground=Theme.TEXT_PRIMARY,
                    font=(Theme.FONT_FAMILY, 10, "bold"),
                    borderwidth=0)
    style.map("Category.Treeview",
              background=[("selected", Theme.COLOR_PRIMARY_DARK),
                          ("active", Theme.BG_HOVER)],
              foreground=[("selected", Theme.BG_DEEP)])

    # Combobox
    style.configure("Dark.TCombobox",
                    fieldbackground=Theme.BG_INPUT,
                    background=Theme.BG_HOVER,
                    foreground=Theme.TEXT_PRIMARY,
                    arrowcolor=Theme.TEXT_SECONDARY,
                    borderwidth=0)
    style.map("Dark.TCombobox",
              fieldbackground=[("readonly", Theme.BG_INPUT)],
              selectbackground=[("readonly", Theme.COLOR_PRIMARY_DARK)],
              selectforeground=[("readonly", Theme.TEXT_PRIMARY)])

    # Spinbox
    style.configure("Dark.TSpinbox",
                    fieldbackground=Theme.BG_INPUT,
                    background=Theme.BG_HOVER,
                    foreground=Theme.TEXT_PRIMARY,
                    arrowcolor=Theme.TEXT_SECONDARY,
                    borderwidth=0)

    # Scrollbar
    style.configure("Dark.Vertical.TScrollbar",
                    background=Theme.BG_HOVER,
                    troughcolor=Theme.BG_DEEP,
                    borderwidth=0,
                    arrowsize=14)
    style.map("Dark.Vertical.TScrollbar",
              background=[("active", Theme.BG_ACTIVE)])

    return style


# ============================================================
# 添加知识对话框
# ============================================================
class AddCardDialog(tk.Toplevel):
    """添加知识卡片对话框"""

    def __init__(self, parent, db, on_success=None):
        super().__init__(parent)
        self.db = db
        self.on_success = on_success
        self.title("添加知识卡片")
        self.geometry("560x620")
        self.configure(bg=Theme.BG_DEEP)
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 20, "pady": 6}
        label_cfg = dict(font=(Theme.FONT_FAMILY, 10), fg=Theme.TEXT_SECONDARY,
                         bg=Theme.BG_DEEP)
        entry_cfg = dict(font=(Theme.FONT_FAMILY, 10), fg=Theme.TEXT_PRIMARY,
                         bg=Theme.BG_INPUT, insertbackground=Theme.TEXT_PRIMARY,
                         relief="flat", borderwidth=0, highlightthickness=1,
                         highlightcolor=Theme.COLOR_PRIMARY,
                         highlightbackground=Theme.BORDER)

        # 标题
        tk.Label(self, text="标题 *", **label_cfg).pack(anchor="w", **pad)
        self.title_entry = tk.Entry(self, **entry_cfg)
        self.title_entry.pack(fill="x", **pad)

        # 内容
        tk.Label(self, text="内容 *", **label_cfg).pack(anchor="w", **pad)
        self.content_text = scrolledtext.ScrolledText(
            self, width=60, height=8, font=(Theme.FONT_FAMILY, 10),
            bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
            insertbackground=Theme.TEXT_PRIMARY,
            relief="flat", borderwidth=0, highlightthickness=1,
            highlightcolor=Theme.COLOR_PRIMARY,
            highlightbackground=Theme.BORDER)
        self.content_text.pack(fill="x", **pad)

        # 分类 & 领域 行
        row1 = tk.Frame(self, bg=Theme.BG_DEEP)
        row1.pack(fill="x", **pad)
        tk.Label(row1, text="分类:", **label_cfg).pack(side="left")
        self.category_var = tk.StringVar(value="inspiration")
        cat_display = [CATEGORY_MAP.get(k, k) for k in CATEGORY_MAP.keys()]
        self._cat_cb = ttk.Combobox(row1, textvariable=self.category_var,
                                    values=cat_display,
                                    state="readonly", width=16,
                                    style="Dark.TCombobox")
        self._cat_cb.pack(side="left", padx=10)
        # 初始化选中项
        cat_keys = list(CATEGORY_MAP.keys())
        if "inspiration" in cat_keys:
            self._cat_cb.current(cat_keys.index("inspiration"))
        self._cat_cb.bind("<<ComboboxSelected>>", self._on_cat_select)

        tk.Label(row1, text="领域:", **label_cfg).pack(side="left", padx=(20, 0))
        self.domain_var = tk.StringVar(value="general")
        dom_display = [DOMAIN_MAP.get(k, k) for k in DOMAIN_MAP.keys()]
        self._dom_cb = ttk.Combobox(row1, textvariable=self.domain_var,
                                    values=dom_display,
                                    state="readonly", width=12,
                                    style="Dark.TCombobox")
        self._dom_cb.pack(side="left", padx=10)
        dom_keys = list(DOMAIN_MAP.keys())
        if "general" in dom_keys:
            self._dom_cb.current(dom_keys.index("general"))
        self._dom_cb.bind("<<ComboboxSelected>>", self._on_dom_select)

        # 引擎钩子 & 优先级 行
        row2 = tk.Frame(self, bg=Theme.BG_DEEP)
        row2.pack(fill="x", **pad)
        tk.Label(row2, text="引擎钩子:", **label_cfg).pack(side="left")
        self.hook_var = tk.StringVar(value="")
        hook_display = [ENGINE_HOOK_LABELS.get(h, h) for h in ENGINE_HOOKS]
        self._hook_cb = ttk.Combobox(row2, textvariable=self.hook_var,
                                     values=hook_display,
                                     state="readonly", width=20,
                                     style="Dark.TCombobox")
        self._hook_cb.pack(side="left", padx=10)
        self._hook_cb.current(0)
        self._hook_cb.bind("<<ComboboxSelected>>", self._on_hook_select)
        tk.Label(row2, text="优先级:", **label_cfg).pack(side="left", padx=(20, 0))
        self.priority_var = tk.IntVar(value=5)
        pri_spin = ttk.Spinbox(row2, from_=1, to=10,
                               textvariable=self.priority_var, width=5,
                               style="Dark.TSpinbox")
        pri_spin.pack(side="left", padx=10)

        # 标签
        tk.Label(self, text="标签 (逗号分隔):", **label_cfg).pack(anchor="w", **pad)
        self.tags_entry = tk.Entry(self, **entry_cfg)
        self.tags_entry.pack(fill="x", **pad)

        # 来源
        tk.Label(self, text="来源:", **label_cfg).pack(anchor="w", **pad)
        self.source_entry = tk.Entry(self, **entry_cfg)
        self.source_entry.insert(0, "用户输入")
        self.source_entry.pack(fill="x", **pad)

        # 按钮
        btn_frame = tk.Frame(self, bg=Theme.BG_DEEP)
        btn_frame.pack(fill="x", pady=15)
        tk.Button(btn_frame, text="确认添加", font=(Theme.FONT_FAMILY, 11, "bold"),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_ACCENT,
                  activebackground=Theme.COLOR_GREEN,
                  relief="flat", padx=25, pady=8, cursor="hand2",
                  command=self._on_add).pack(side="right", padx=10)
        tk.Button(btn_frame, text="取消", font=(Theme.FONT_FAMILY, 11),
                  fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                  activebackground=Theme.BORDER,
                  relief="flat", padx=25, pady=8, cursor="hand2",
                  command=self.destroy).pack(side="right")

    def _on_cat_select(self, event=None):
        """分类下拉框选择回调：将中文label转回英文key"""
        idx = self._cat_cb.current()
        cat_keys = list(CATEGORY_MAP.keys())
        if 0 <= idx < len(cat_keys):
            self.category_var.set(cat_keys[idx])

    def _on_dom_select(self, event=None):
        """领域下拉框选择回调：将中文label转回英文key"""
        idx = self._dom_cb.current()
        dom_keys = list(DOMAIN_MAP.keys())
        if 0 <= idx < len(dom_keys):
            self.domain_var.set(dom_keys[idx])

    def _on_hook_select(self, event=None):
        """引擎钩子下拉框选择回调：将中文label转回英文key"""
        idx = self._hook_cb.current()
        if 0 <= idx < len(ENGINE_HOOKS):
            self.hook_var.set(ENGINE_HOOKS[idx])

    def _on_add(self):
        title = self.title_entry.get().strip()
        content = self.content_text.get("1.0", "end").strip()
        if not title:
            messagebox.showwarning("提示", "请输入标题", parent=self)
            return
        if not content:
            messagebox.showwarning("提示", "请输入内容", parent=self)
            return
        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        source = self.source_entry.get().strip() or "用户输入"
        card_id = self.db.add_card(
            title=title,
            content=content,
            category=self.category_var.get(),
            domain=self.domain_var.get(),
            tags=tags,
            source=source,
            engine_hook=self.hook_var.get(),
            priority=self.priority_var.get(),
        )
        messagebox.showinfo("成功", f"知识卡片已添加 (ID: {card_id})", parent=self)
        self.destroy()
        if self.on_success:
            self.on_success()


# ============================================================
# 快速导入对话框（增强版 - 智能预览 + 一键粘贴）
# ============================================================
class QuickImportDialog(tk.Toplevel):
    """快速导入文本对话框 - 增强版

    支持智能识别预览、一键粘贴、实时分类建议。
    """

    def __init__(self, parent, db, on_success=None):
        super().__init__(parent)
        self.db = db
        self.on_success = on_success
        self.title("快速导入知识")
        self.geometry("700x650")
        self.configure(bg=Theme.BG_DEEP)
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        label_cfg = dict(font=(Theme.FONT_FAMILY, 10), fg=Theme.TEXT_SECONDARY,
                         bg=Theme.BG_DEEP)

        # --- 顶部提示语 ---
        tk.Label(self, text="把你想记录的任何内容粘贴到下面：技巧、灵感、经验、文章...",
                 font=(Theme.FONT_FAMILY, 11), fg=Theme.COLOR_PRIMARY,
                 bg=Theme.BG_DEEP).pack(anchor="w", padx=20, pady=(15, 5))

        # --- 文本框 ---
        self.text = scrolledtext.ScrolledText(
            self, width=80, height=10, font=(Theme.FONT_FAMILY, 10),
            bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
            insertbackground=Theme.TEXT_PRIMARY,
            relief="flat", borderwidth=0, highlightthickness=1,
            highlightcolor=Theme.COLOR_PRIMARY,
            highlightbackground=Theme.BORDER)
        self.text.pack(fill="both", expand=True, padx=20, pady=5)

        # 绑定文本变化事件，实时预览
        self.text.bind("<KeyRelease>", self._on_text_changed)

        # --- 智能预览区域 ---
        preview_outer = tk.Frame(self, bg=Theme.BG_CARD, relief="flat",
                                borderwidth=0, highlightthickness=1,
                                highlightbackground=Theme.BORDER)
        preview_outer.pack(fill="x", padx=20, pady=(5, 5))

        tk.Label(preview_outer, text="  智能预览",
                 font=(Theme.FONT_FAMILY, 10, "bold"),
                 fg=Theme.COLOR_SECONDARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(8, 2), padx=10)

        preview_inner = tk.Frame(preview_outer, bg=Theme.BG_CARD)
        preview_inner.pack(fill="x", padx=10, pady=(0, 8))

        # 预览行1：领域 + 分类 + 卡片数量
        row1 = tk.Frame(preview_inner, bg=Theme.BG_CARD)
        row1.pack(fill="x", pady=2)

        tk.Label(row1, text="检测领域:", **label_cfg).pack(side="left")
        self._build_cn_combobox(
            row1, "domain_var", "general", DOMAIN_MAP, side="left", padx=8, width=14)

        tk.Label(row1, text="推荐分类:", **label_cfg).pack(side="left", padx=(15, 0))
        self._build_cn_combobox(
            row1, "category_var", "inspiration", CATEGORY_MAP, side="left", padx=8, width=14)

        tk.Label(row1, text="预计卡片:", **label_cfg).pack(side="left", padx=(15, 0))
        self.estimate_label = tk.Label(row1, text="-", font=(Theme.FONT_FAMILY, 10, "bold"),
                                       fg=Theme.COLOR_GREEN, bg=Theme.BG_CARD)
        self.estimate_label.pack(side="left", padx=5)

        # 预览行2：标签 + 引擎钩子
        row2 = tk.Frame(preview_inner, bg=Theme.BG_CARD)
        row2.pack(fill="x", pady=2)

        tk.Label(row2, text="自动标签:", **label_cfg).pack(side="left")
        self.tags_preview_label = tk.Label(row2, text="(粘贴文字后自动识别)",
                                           font=(Theme.FONT_FAMILY, 9),
                                           fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD,
                                           wraplength=400, justify="left")
        self.tags_preview_label.pack(side="left", padx=8)

        # 预览行3：引擎钩子
        row3 = tk.Frame(preview_inner, bg=Theme.BG_CARD)
        row3.pack(fill="x", pady=2)

        tk.Label(row3, text="引擎钩子:", **label_cfg).pack(side="left")
        self.hook_preview_label = tk.Label(row3, text="(无)",
                                           font=(Theme.FONT_FAMILY, 9),
                                           fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.hook_preview_label.pack(side="left", padx=8)

        # --- 选项行（分类/领域下拉框 - 与预览联动） ---
        # 用户可手动覆盖，下拉框已显示预览推荐值

        # --- 按钮行 ---
        btn_frame = tk.Frame(self, bg=Theme.BG_DEEP)
        btn_frame.pack(fill="x", padx=20, pady=15)
        tk.Button(btn_frame, text="导入", font=(Theme.FONT_FAMILY, 11, "bold"),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_ACCENT,
                  activebackground=Theme.COLOR_GREEN,
                  relief="flat", padx=25, pady=8, cursor="hand2",
                  command=self._on_import).pack(side="right", padx=10)
        tk.Button(btn_frame, text="取消", font=(Theme.FONT_FAMILY, 11),
                  fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                  activebackground=Theme.BORDER,
                  relief="flat", padx=25, pady=8, cursor="hand2",
                  command=self.destroy).pack(side="right")
        tk.Button(btn_frame, text="一键粘贴", font=(Theme.FONT_FAMILY, 11),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_SECONDARY,
                  activebackground=Theme.WARNING,
                  relief="flat", padx=18, pady=8, cursor="hand2",
                  command=self._paste_from_clipboard).pack(side="right", padx=(0, 10))

    def _build_cn_combobox(self, parent, var_attr, default_key, label_map,
                           side="left", padx=8, width=14):
        """辅助方法：创建一个显示中文label但存储英文key的Combobox。

        Parameters
        ----------
        parent : tk.Widget
            父容器
        var_attr : str
            本实例的属性名（如 "domain_var"），Combobox的值存在此变量中
        default_key : str
            默认选中的英文key
        label_map : dict
            {英文key: 中文label} 映射
        """
        var = tk.StringVar(value=default_key)
        setattr(self, var_attr, var)

        # 显示值用中文label
        display_values = [label_map.get(k, k) for k in label_map.keys()]
        cb = ttk.Combobox(parent, textvariable=var,
                          values=display_values,
                          state="readonly", width=width,
                          style="Dark.TCombobox")
        cb.pack(side=side, padx=padx)

        # 初始化选中项的index
        keys_list = list(label_map.keys())
        if default_key in keys_list:
            idx = keys_list.index(default_key)
            cb.current(idx)

        # 将 Combobox 存储以便后续联动
        setattr(self, f"_{var_attr}_cb", cb)
        setattr(self, f"_{var_attr}_map", label_map)

    def _set_cn_combobox_value(self, var_attr, key):
        """设置中文Combobox的选中值（通过英文key）"""
        label_map = getattr(self, f"_{var_attr}_map", None)
        cb = getattr(self, f"_{var_attr}_cb", None)
        if not label_map or not cb:
            return
        keys_list = list(label_map.keys())
        if key in keys_list:
            idx = keys_list.index(key)
            cb.current(idx)
            getattr(self, var_attr).set(key)

    def _on_text_changed(self, event=None):
        """文本变化时实时调用智能分类预览"""
        raw = self.text.get("1.0", "end").strip()
        if len(raw) < 10:
            # 内容太少，重置预览
            self.tags_preview_label.config(text="(粘贴文字后自动识别)", fg=Theme.TEXT_MUTED)
            self.hook_preview_label.config(text="(无)", fg=Theme.TEXT_MUTED)
            self.estimate_label.config(text="-", fg=Theme.TEXT_MUTED)
            self._set_cn_combobox_value("domain_var", "general")
            self._set_cn_combobox_value("category_var", "inspiration")
            return

        classify = self.db.smart_classify(raw)
        count = MiroFishDB.estimate_card_count(raw)

        # 更新领域
        self._set_cn_combobox_value("domain_var", classify["domain"])

        # 更新分类
        self._set_cn_combobox_value("category_var", classify["category"])

        # 更新标签预览
        tags = classify.get("tags", [])
        if tags:
            tags_text = "  ".join(f"[{t}]" for t in tags)
            self.tags_preview_label.config(text=tags_text, fg=Theme.COLOR_PRIMARY)
        else:
            self.tags_preview_label.config(text="(未检测到特定标签)", fg=Theme.TEXT_MUTED)

        # 更新引擎钩子
        hook = classify.get("hook", "")
        if hook:
            hook_label = ENGINE_HOOK_LABELS.get(hook, hook)
            self.hook_preview_label.config(text=hook_label, fg=Theme.COLOR_SECONDARY)
        else:
            self.hook_preview_label.config(text="(无)", fg=Theme.TEXT_MUTED)

        # 更新预估卡片数
        self.estimate_label.config(text=f"{count} 张", fg=Theme.COLOR_GREEN)

    def _paste_from_clipboard(self):
        """一键粘贴：从剪贴板读取内容"""
        try:
            content = self.root.clipboard_get()
            if content and content.strip():
                self.text.delete("1.0", "end")
                self.text.insert("1.0", content)
                # 触发实时预览
                self._on_text_changed()
            else:
                messagebox.showinfo("提示", "剪贴板为空，请先复制内容", parent=self)
        except Exception:
            messagebox.showinfo("提示", "无法读取剪贴板，请手动粘贴", parent=self)

    def _on_import(self):
        raw = self.text.get("1.0", "end").strip()
        if not raw or len(raw) < 10:
            messagebox.showwarning("提示", "请粘贴至少10个字符的文本", parent=self)
            return
        card_ids = self.db.import_from_text(
            text=raw,
            category=self.category_var.get(),
            domain=self.domain_var.get(),
            source="快速导入",
        )
        if card_ids:
            messagebox.showinfo("成功",
                                f"成功导入 {len(card_ids)} 张知识卡片",
                                parent=self)
            self.destroy()
            if self.on_success:
                self.on_success()
        else:
            messagebox.showwarning("提示", "未能提取到有效知识段落", parent=self)


# ============================================================
# 主应用
# ============================================================
class MiroFishApp:
    """MiroFish 知识库管理主界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("MiroFish 万物知识库 - 可视化管理")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.geometry("1280x780")
        self.root.minsize(960, 600)

        # 数据库
        self.db = MiroFishDB()

        # 当前选中卡片ID列表缓存 (用于列表显示)
        self._cards_cache = []  # list[dict]

        # 配置样式
        self.style = setup_style()

        # 构建 UI
        self._build_ui()

        # 初始加载
        self._refresh_category_tree()
        self._load_cards()

    # ----------------------------------------------------------
    # UI 构建
    # ----------------------------------------------------------
    def _build_ui(self):
        self._build_header()
        self._build_status_bar()

        # 主内容区
        main = tk.Frame(self.root, bg=Theme.BG_DEEP)
        main.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        # 左侧面板
        self._build_left_panel(main)

        # 右侧面板
        self._build_right_panel(main)

    # --- 顶部工具栏 ---
    def _build_header(self):
        header = tk.Frame(self.root, bg=Theme.BG_CARD, height=60)
        header.pack(fill="x", padx=15, pady=(15, 5))
        header.pack_propagate(False)

        # 左侧标题
        tf = tk.Frame(header, bg=Theme.BG_CARD)
        tf.pack(side="left", padx=20)
        icon = tk.Frame(tf, bg=Theme.COLOR_PRIMARY, width=36, height=36)
        icon.pack(side="left")
        icon.pack_propagate(False)
        tk.Label(icon, text="M", font=("Arial", 18, "bold"),
                 fg=Theme.BG_DEEP, bg=Theme.COLOR_PRIMARY).pack(expand=True)

        info = tk.Frame(tf, bg=Theme.BG_CARD)
        info.pack(side="left", padx=12)
        tk.Label(info, text="MiroFish 万物知识库",
                 font=(Theme.FONT_FAMILY, 16, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w")
        tk.Label(info, text="PARA分类 · 知识管理",
                 font=(Theme.FONT_FAMILY, 10),
                 fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")

        # 右侧工具按钮
        rf = tk.Frame(header, bg=Theme.BG_CARD)
        rf.pack(side="right", padx=20)

        btn_cfg = dict(font=(Theme.FONT_FAMILY, 10), relief="flat",
                       padx=14, pady=7, cursor="hand2")

        self.search_entry = tk.Entry(rf, font=(Theme.FONT_FAMILY, 10),
                                     fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                                     insertbackground=Theme.TEXT_PRIMARY,
                                     relief="flat", borderwidth=0,
                                     highlightthickness=1,
                                     highlightcolor=Theme.COLOR_PRIMARY,
                                     highlightbackground=Theme.BORDER,
                                     width=18)
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.insert(0, "搜索关键词...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        tk.Button(rf, text="搜索", fg=Theme.TEXT_SECONDARY,
                  bg=Theme.BG_HOVER, activebackground=Theme.BORDER,
                  command=self._do_search, **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="添加知识", fg=Theme.BG_DEEP,
                  bg=Theme.COLOR_ACCENT, activebackground=Theme.COLOR_GREEN,
                  command=self._on_add_card, **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="快速导入", fg=Theme.TEXT_SECONDARY,
                  bg=Theme.BG_HOVER, activebackground=Theme.BORDER,
                  command=self._on_quick_import, **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="删除", fg=Theme.TEXT_SECONDARY,
                  bg=Theme.BG_HOVER, activebackground=Theme.BORDER,
                  command=self._on_delete, **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="有效性+", fg=Theme.BG_DEEP,
                  bg=Theme.COLOR_GREEN, activebackground=Theme.SUCCESS,
                  command=lambda: self._update_effectiveness(10), **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="有效性-", fg=Theme.TEXT_PRIMARY,
                  bg=Theme.COLOR_RED, activebackground=Theme.ERROR,
                  command=lambda: self._update_effectiveness(-10), **btn_cfg).pack(side="left", padx=(0, 6))

        tk.Button(rf, text="使用帮助", fg=Theme.BG_DEEP,
                  bg=Theme.COLOR_PURPLE, activebackground="#7c3aed",
                  command=self._show_help, **btn_cfg).pack(side="left")

    # --- 底部状态栏 ---
    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=Theme.BG_CARD, height=32)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_icon = tk.Label(bar, text="●", font=(Theme.FONT_FAMILY, 11),
                                    fg=Theme.SUCCESS, bg=Theme.BG_CARD)
        self.status_icon.pack(side="left", padx=15)
        self.status_text = tk.Label(bar, text="就绪",
                                    font=(Theme.FONT_FAMILY, 10),
                                    fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self.status_text.pack(side="left", padx=5)

        self.time_label = tk.Label(bar, text="",
                                   font=(Theme.FONT_FAMILY, 10),
                                   fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.time_label.pack(side="left", padx=20)

        self.stats_label = tk.Label(bar, text="",
                                    font=(Theme.FONT_FAMILY, 10),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.stats_label.pack(side="right", padx=15)

        self._update_time()

    # --- 左侧分类面板 ---
    def _build_left_panel(self, parent):
        left = tk.Frame(parent, bg=Theme.BG_CARD, width=200)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        tk.Label(left, text="分类浏览",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", padx=15, pady=(12, 8))

        self.cat_tree = ttk.Treeview(left, show="tree",
                                     style="Category.Treeview",
                                     selectmode="browse")
        cat_scroll = ttk.Scrollbar(left, orient="vertical",
                                   command=self.cat_tree.yview,
                                   style="Dark.Vertical.TScrollbar")
        self.cat_tree.configure(yscrollcommand=cat_scroll.set)

        cat_scroll.pack(side="right", fill="y", padx=(0, 5), pady=5)
        self.cat_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)

        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category_select)

        # 底部统计
        self.left_stats_label = tk.Label(left, text="",
                                        font=(Theme.FONT_FAMILY, 9),
                                        fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD,
                                        wraplength=180, justify="left")
        self.left_stats_label.pack(anchor="w", padx=15, pady=(5, 10))

    # --- 右侧卡片列表+详情面板 ---
    def _build_right_panel(self, parent):
        right = tk.Frame(parent, bg=Theme.BG_DEEP)
        right.pack(side="right", fill="both", expand=True)

        # 上方：卡片列表
        list_frame = tk.Frame(right, bg=Theme.BG_CARD)
        list_frame.pack(fill="both", expand=True, pady=(0, 8))

        list_header = tk.Frame(list_frame, bg=Theme.BG_CARD)
        list_header.pack(fill="x", padx=15, pady=(10, 5))
        tk.Label(list_header, text="知识卡片列表",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(side="left")
        self.count_label = tk.Label(list_header, text="(0)",
                                    font=(Theme.FONT_FAMILY, 10),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.count_label.pack(side="left", padx=8)

        # 表格
        cols = ("title", "domain", "tags", "effectiveness", "priority", "created")
        self.card_tree = ttk.Treeview(list_frame, show="headings",
                                      columns=cols,
                                      style="Dark.Treeview",
                                      selectmode="browse")

        col_config = [
            ("title",         "标题",   280),
            ("domain",        "领域",   65),
            ("tags",          "标签",   180),
            ("effectiveness", "有效性", 65),
            ("priority",      "优先级", 55),
            ("created",       "创建时间", 140),
        ]
        for cid, heading, width in col_config:
            self.card_tree.heading(cid, text=heading)
            self.card_tree.column(cid, width=width, minwidth=50, anchor="center" if cid != "title" else "w")

        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                   command=self.card_tree.yview,
                                   style="Dark.Vertical.TScrollbar")
        self.card_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y", padx=(0, 5), pady=5)
        self.card_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)

        self.card_tree.bind("<<TreeviewSelect>>", self._on_card_select)
        self.card_tree.bind("<Double-1>", self._on_card_double_click)

        # 右键菜单
        self._context_menu = tk.Menu(self.root, tearoff=0, font=(Theme.FONT_FAMILY, 10),
                                     bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                                     activebackground=Theme.COLOR_PRIMARY_DARK,
                                     activeforeground=Theme.BG_DEEP,
                                     relief="flat", borderwidth=0)
        self._context_menu.add_command(label="复制标题", command=self._ctx_copy_title)
        self._context_menu.add_command(label="复制内容", command=self._ctx_copy_content)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="查看详情", command=self._ctx_view_detail)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="调整有效性 +10", command=lambda: self._update_effectiveness(10))
        self._context_menu.add_command(label="调整有效性 -10", command=lambda: self._update_effectiveness(-10))
        self._context_menu.add_separator()
        self._context_menu.add_command(label="删除", command=self._on_delete)

        self.card_tree.bind("<Button-3>", self._on_right_click)

        # 下方：卡片详情
        detail_frame = tk.Frame(right, bg=Theme.BG_CARD)
        detail_frame.pack(fill="both", expand=True)

        detail_header = tk.Frame(detail_frame, bg=Theme.BG_CARD)
        detail_header.pack(fill="x", padx=15, pady=(8, 4))
        tk.Label(detail_header, text="卡片详情",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(side="left")

        self.detail_text = scrolledtext.ScrolledText(
            detail_frame, font=(Theme.FONT_FAMILY, 10),
            bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
            insertbackground=Theme.TEXT_PRIMARY,
            relief="flat", borderwidth=0,
            highlightthickness=0,
            wrap="word", state="disabled")
        self.detail_text.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    # ----------------------------------------------------------
    # 数据操作
    # ----------------------------------------------------------
    def _refresh_category_tree(self):
        """刷新左侧分类树"""
        self.cat_tree.delete(*self.cat_tree.get_children())
        stats = self.db.stats()
        by_cat = stats.get("by_category", {})
        total = stats.get("total_cards", 0)

        # "全部" 节点
        all_id = self.cat_tree.insert("", "end",
                                      text=f"  全部分类  ({total})",
                                      values=("all", total),
                                      open=True)
        # 各分类节点
        for cat_key in ["inspiration", "project", "area", "resource", "skill", "archive"]:
            count = by_cat.get(cat_key, 0)
            label = CATEGORY_MAP.get(cat_key, cat_key)
            self.cat_tree.insert(all_id, "end",
                                 text=f"  {label}  ({count})",
                                 values=(cat_key, count))

        # 自动选中"全部"
        children = self.cat_tree.get_children(all_id)
        if children:
            self.cat_tree.selection_set(children[0])

        # 左下统计
        by_dom = stats.get("by_domain", {})
        dom_parts = [f"{DOMAIN_MAP.get(k, k)}:{v}" for k, v in sorted(by_dom.items(), key=lambda x: -x[1])[:5]]
        self.left_stats_label.config(text=f"总计: {total} 张卡片\n领域: {', '.join(dom_parts)}")
        self.stats_label.config(text=f"总计 {total} 张卡片")

    def _load_cards(self, category=None, query=None):
        """加载卡片列表"""
        self.card_tree.delete(*self.card_tree.get_children())

        results = self.db.search(category=category, query=query, limit=9999)
        self._cards_cache = results

        for card in results:
            tags_str = ", ".join(card.get("tags", [])[:3])
            if len(card.get("tags", [])) > 3:
                tags_str += f" (+{len(card['tags'])-3})"
            eff = card.get("effectiveness", 50)
            pri = card.get("priority", 5)
            created = card.get("created", "")[:16]

            # 有效性颜色标识
            eff_display = f"{eff}"
            if eff >= 70:
                eff_display += " [高]"
            elif eff <= 30:
                eff_display += " [低]"

            self.card_tree.insert("", "end", iid=card["id"], values=(
                card.get("title", ""),
                DOMAIN_MAP.get(card.get("domain", "general"), card.get("domain", "")),
                tags_str,
                eff_display,
                pri,
                created,
            ))

        self.count_label.config(text=f"({len(results)})")
        self._log(f"加载 {len(results)} 张卡片" + (f" [分类={CATEGORY_MAP.get(category, category)}]" if category else ""))

    def _show_card_detail(self, card_id):
        """显示卡片详情"""
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")

        # 从缓存中查找
        card = None
        for c in self._cards_cache:
            if c["id"] == card_id:
                card = c
                break

        if not card:
            self.detail_text.insert("end", "未找到该卡片。")
            self.detail_text.config(state="disabled")
            return

        hook_label = ENGINE_HOOK_LABELS.get(card.get("engine_hook", ""), card.get("engine_hook", "(无)"))
        cat_label = CATEGORY_MAP.get(card.get("category", ""), card.get("category", ""))
        dom_label = DOMAIN_MAP.get(card.get("domain", ""), card.get("domain", ""))
        tags_str = ", ".join(card.get("tags", [])) if card.get("tags") else "无"

        detail = (
            f"{'='*50}\n"
            f"  标题: {card.get('title', '')}\n"
            f"{'='*50}\n\n"
            f"  ID:           {card.get('id', '')}\n"
            f"  分类:         {cat_label} ({card.get('category', '')})\n"
            f"  领域:         {dom_label} ({card.get('domain', '')})\n"
            f"  标签:         {tags_str}\n"
            f"  来源:         {card.get('source', '')}\n"
            f"  引擎钩子:     {hook_label}\n"
            f"  优先级:       {card.get('priority', 5)} / 10\n"
            f"  有效性:       {card.get('effectiveness', 50)} / 100\n"
            f"  使用次数:     {card.get('use_count', 0)}\n"
            f"  最后使用:     {card.get('last_used', '从未')}\n"
            f"  创建时间:     {card.get('created', '')}\n"
            f"  更新时间:     {card.get('updated', '')}\n"
            f"\n{'-'*50}\n"
            f"  内容:\n\n{card.get('content', '')}\n"
        )
        self.detail_text.insert("end", detail)
        self.detail_text.config(state="disabled")

    # ----------------------------------------------------------
    # 事件回调
    # ----------------------------------------------------------
    def _on_category_select(self, event=None):
        sel = self.cat_tree.selection()
        if not sel:
            return
        item = self.cat_tree.item(sel[0])
        cat = item["values"][0] if item["values"] else "all"
        if cat == "all":
            cat = None
        self._current_category = cat
        # 清除搜索框
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, "搜索关键词...")
        self._load_cards(category=cat)

    def _on_card_select(self, event=None):
        sel = self.card_tree.selection()
        if sel:
            self._show_card_detail(sel[0])

    def _on_card_double_click(self, event=None):
        sel = self.card_tree.selection()
        if sel:
            self._show_card_detail(sel[0])

    def _on_right_click(self, event=None):
        """右键菜单：选中卡片并弹出菜单"""
        # 先选中右键点击的行
        item = self.card_tree.identify_row(event.y)
        if item:
            self.card_tree.selection_set(item)
            self._show_card_detail(item)
            self._context_menu.post(event.x_root, event.y_root)

    def _ctx_copy_title(self):
        """右键：复制标题"""
        sel = self.card_tree.selection()
        if sel:
            card = self._find_card(sel[0])
            if card:
                self.root.clipboard_clear()
                self.root.clipboard_append(card.get("title", ""))

    def _ctx_copy_content(self):
        """右键：复制内容"""
        sel = self.card_tree.selection()
        if sel:
            card = self._find_card(sel[0])
            if card:
                self.root.clipboard_clear()
                self.root.clipboard_append(card.get("content", ""))

    def _ctx_view_detail(self):
        """右键：查看详情"""
        sel = self.card_tree.selection()
        if sel:
            self._show_card_detail(sel[0])

    def _find_card(self, card_id):
        """根据ID从缓存中查找卡片"""
        for c in self._cards_cache:
            if c["id"] == card_id:
                return c
        return None

    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "搜索关键词...":
            self.search_entry.delete(0, tk.END)

    def _on_search_focus_out(self, event):
        if not self.search_entry.get().strip():
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, "搜索关键词...")

    def _do_search(self):
        query = self.search_entry.get().strip()
        if query == "搜索关键词..." or not query:
            # 无搜索词时恢复当前分类的全部列表
            self._load_cards(category=getattr(self, '_current_category', None))
            return
        cat = getattr(self, '_current_category', None)
        self._load_cards(category=cat, query=query)

    def _on_add_card(self):
        AddCardDialog(self.root, self.db, on_success=self._refresh_all)

    def _on_quick_import(self):
        QuickImportDialog(self.root, self.db, on_success=self._refresh_all)

    def _on_delete(self):
        sel = self.card_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的卡片")
            return
        card_id = sel[0]
        # 查找卡片标题
        card_title = card_id
        for c in self._cards_cache:
            if c["id"] == card_id:
                card_title = c.get("title", card_id)
                break

        confirmed = messagebox.askyesno(
            "确认删除",
            f"确定要删除以下知识卡片吗？\n\n标题: {card_title}\nID: {card_id}\n\n此操作不可撤销。",
            icon="warning"
        )
        if not confirmed:
            return

        ok = self.db.remove_card(card_id)
        if ok:
            self._log(f"已删除卡片: {card_title}")
            self._refresh_all()
        else:
            messagebox.showerror("错误", "删除失败，卡片可能不存在")

    def _update_effectiveness(self, delta):
        sel = self.card_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要调整的卡片")
            return
        card_id = sel[0]
        new_score = self.db.update_effectiveness(card_id, delta)
        if new_score is not None:
            card_title = card_id
            for c in self._cards_cache:
                if c["id"] == card_id:
                    card_title = c.get("title", card_id)
                    break
            self._log(f"有效性更新: {card_title} -> {new_score} ({delta:+d})")
            self._refresh_all()
        else:
            messagebox.showerror("错误", "更新失败，卡片可能不存在")

    def _refresh_all(self):
        """刷新所有数据"""
        self._refresh_category_tree()
        cat = getattr(self, '_current_category', None)
        query = self.search_entry.get().strip()
        if query and query != "搜索关键词...":
            self._load_cards(category=cat, query=query)
        else:
            self._load_cards(category=cat)

    # ----------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------
    def _log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.status_text.config(text=f"[{ts}] {msg}")

    def _update_time(self):
        self.time_label.config(text=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._update_time)

    def _show_help(self):
        """显示使用帮助"""
        help_text = (
            "使用指南：\n\n"
            "1. 添加知识：点击'添加知识'手动创建知识卡片\n"
            "2. 快速导入：点击'快速导入'，粘贴任意文字，系统自动识别分类\n"
            "3. 搜索：在搜索框输入关键词回车搜索\n"
            "4. 分类浏览：点击左侧分类树筛选\n"
            "5. 查看详情：点击列表中的卡片，下方显示完整内容\n"
            "6. 删除：选中卡片后点击'删除'按钮\n"
            "7. 有效性调整：选中卡片后点击'有效性+'或'有效性-'\n"
            "8. 知识自动生效：添加的知识会被预测引擎自动调用\n"
            "\n右键菜单：在卡片列表上右键可以复制标题、复制内容、调整有效性等。"
        )
        messagebox.showinfo("使用帮助", help_text)


# ============================================================
# 入口
# ============================================================
def main():
    try:
        from core.gui_registry import register
        register('mirofish', '金水谣预测面板')
    except Exception:
        pass
    root = tk.Tk()
    try:
        from core.tk_style import apply_dark_style
        apply_dark_style(root)
    except Exception:
        pass
    app = MiroFishApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
