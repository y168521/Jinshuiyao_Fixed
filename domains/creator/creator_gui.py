# -*- coding: utf-8 -*-
"""金水谣创作者工具箱 - 独立GUI窗口

功能：
  - 六大创作者工具统一入口：AI文案/语音转文字/智能配音/OCR/音频提取/去水印
  - 左栏工具选择，中栏动态输入面板，右栏依赖状态
  - 底部操作日志，全程可追溯
  - 每个工具依赖缺失时优雅降级，提示"该工具依赖未安装"

数据源：复用 domains.creator.domain.CreatorDomain，各工具延迟加载依赖
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

# -----------------------------------------------------------------------
# 导入路径处理 —— 与 stock_gui.py 保持一致
# -----------------------------------------------------------------------
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from core.theme import Theme


# =======================================================================
# 工具定义表（key -> (中文名, 颜色, 依赖键列表)）
# =======================================================================
TOOL_DEFS = [
    ("ai_copy",      "AI文案",     Theme.COLOR_PRIMARY,   ["ai_service"]),
    ("stt",          "语音转文字",  Theme.COLOR_ACCENT,    ["speech_recognition"]),
    ("tts",          "智能配音",    Theme.COLOR_SECONDARY, ["edge_tts"]),
    ("ocr",          "OCR识别",     Theme.COLOR_PURPLE,    ["pytesseract", "PIL"]),
    ("audio_extract", "音频提取",   Theme.COLOR_PINK,      ["moviepy"]),
    ("watermark",    "去水印",      Theme.COLOR_AMBER,     ["cv2"]),
]

# AI文案风格选项（与 AICopywriter.STYLE_NAMES 一致）
COPY_STYLES = [
    ("xiaohongshu", "小红书种草文"),
    ("douyin",      "抖音带货文"),
    ("wechat",      "朋友圈文案"),
    ("article",     "公众号文章"),
    ("product",     "产品描述"),
    ("script",      "视频脚本"),
]

# TTS语音选项（与 TTSEngine.VOICES 一致）
TTS_VOICES = [
    ("zh_female_1", "中文女声1（晓晓）"),
    ("zh_female_2", "中文女声2（晓伊）"),
    ("zh_male_1",   "中文男声1（云希）"),
    ("zh_male_2",   "中文男声2（云健）"),
    ("en_female",   "英文女声（Jenny）"),
    ("en_male",     "英文男声（Guy）"),
]


# =======================================================================
# 创作者工具箱主窗口
# =======================================================================
class CreatorToolboxWindow:
    """金水谣创作者工具箱主窗口"""

    def __init__(self, master=None):
        self.root = master or tk.Tk()
        self.root.title("金水谣创作者工具箱")
        self.root.geometry("1200x800")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.minsize(1000, 650)

        # 业务层
        self._domain = None
        self._current_tool = None  # 当前选中的工具key

        # 初始化创作者域
        self._init_domain()

        # 构建UI
        self._build_ui()

        # 启动时自动选中第一个工具
        self.root.after(300, lambda: self._on_select_tool("ai_copy"))

    # ---------------------------------------------------------------
    # 业务初始化
    # ---------------------------------------------------------------

    def _init_domain(self):
        """初始化 CreatorDomain（不可用时降级提示）"""
        self._domain_err = None
        try:
            from domains.creator.domain import CreatorDomain
            self._domain = CreatorDomain()
            ok = self._domain.setup()
            if not ok:
                self._domain_err = "CreatorDomain.setup() 返回 False"
                print("[WARN] CreatorDomain.setup() 返回False")
        except Exception as e:
            self._domain_err = str(e)
            print(f"[ERR] 创作者工具箱子系统初始化失败: {e}")
            self._domain = None

    def _ensure_domain(self):
        """确保创作者域已初始化；未初始化则自动重试一次"""
        if self._domain is not None:
            return True
        self._init_domain()
        return self._domain is not None

    # ---------------------------------------------------------------
    # UI构建
    # ---------------------------------------------------------------

    def _build_ui(self):
        """构建主界面"""
        # 顶部标题栏
        self._build_header()

        # 主体三栏布局
        main_frame = tk.Frame(self.root, bg=Theme.BG_DEEP)
        main_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        main_frame.grid_columnconfigure(0, weight=0, minsize=200)
        main_frame.grid_columnconfigure(1, weight=3, minsize=520)
        main_frame.grid_columnconfigure(2, weight=0, minsize=240)
        main_frame.grid_rowconfigure(0, weight=1)

        # 左栏：工具选择列表
        self._build_left_panel(main_frame)

        # 中栏：动态输入面板容器
        self._build_middle_panel(main_frame)

        # 右栏：工具状态面板
        self._build_right_panel(main_frame)

        # 底部：操作日志
        self._build_bottom_panel()

    def _build_header(self):
        """顶部标题栏"""
        header = tk.Frame(self.root, bg=Theme.BG_CARD, height=50)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(header, text="金水谣创作者工具箱",
                 font=(Theme.FONT_FAMILY, 16, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(side="left", padx=20, pady=8)

        # 子系统状态指示
        self._status_label = tk.Label(header, text="子系统: 初始化中...",
                                      font=(Theme.FONT_FAMILY, 10),
                                      fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self._status_label.pack(side="right", padx=20)

        # 当前时间
        self._time_label = tk.Label(header,
                                    font=(Theme.FONT_FAMILY, 10),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self._time_label.pack(side="right", padx=10)
        self._update_clock()

    def _update_clock(self):
        """更新时钟"""
        self._time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._update_clock)

    def _build_left_panel(self, parent):
        """左栏：工具选择列表"""
        left = tk.Frame(parent, bg=Theme.BG_DEEP, width=200)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)

        list_frame = tk.Frame(left, bg=Theme.BG_CARD, padx=12, pady=12)
        list_frame.pack(fill="both", expand=True)

        tk.Label(list_frame, text="工具选择",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        self._tool_buttons = {}
        for key, name, color, _deps in TOOL_DEFS:
            btn = tk.Button(list_frame, text=name,
                            font=(Theme.FONT_FAMILY, 11, "bold"),
                            fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                            activebackground=color,
                            activeforeground=Theme.BG_DEEP,
                            relief="flat", cursor="hand2",
                            pady=12,
                            command=lambda k=key: self._on_select_tool(k))
            btn.pack(fill="x", pady=(0, 8))
            self._tool_buttons[key] = btn

    def _build_middle_panel(self, parent):
        """中栏：动态输入面板容器（按选中工具切换内容）"""
        self._middle_container = tk.Frame(parent, bg=Theme.BG_CARD)
        self._middle_container.grid(row=0, column=1, sticky="nsew")
        # 默认提示
        tk.Label(self._middle_container, text="请从左侧选择一个工具",
                 font=(Theme.FONT_FAMILY, 13),
                 fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(expand=True)

    def _build_right_panel(self, parent):
        """右栏：工具依赖状态面板"""
        right = tk.Frame(parent, bg=Theme.BG_DEEP, width=240)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.grid_propagate(False)

        status_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        status_frame.pack(fill="both", expand=True)

        tk.Label(status_frame, text="工具状态",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 12))

        self._tool_status_labels = {}
        for key, name, _color, _deps in TOOL_DEFS:
            row = tk.Frame(status_frame, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=5)
            tk.Label(row, text=f"● {name}",
                     font=(Theme.FONT_FAMILY, 10),
                     fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD).pack(side="left")
            lbl = tk.Label(row, text="检测中",
                           font=(Theme.FONT_FAMILY, 10, "bold"),
                           fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
            lbl.pack(side="right")
            self._tool_status_labels[key] = lbl

        # 刷新状态按钮
        tk.Button(status_frame, text="刷新状态",
                  font=(Theme.FONT_FAMILY, 10),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_PRIMARY,
                  activebackground=Theme.COLOR_PRIMARY,
                  activeforeground=Theme.BG_DEEP,
                  relief="flat", cursor="hand2", pady=6,
                  command=self._refresh_status).pack(fill="x", pady=(16, 0))

    def _build_bottom_panel(self):
        """底部：操作日志"""
        bottom = tk.Frame(self.root, bg=Theme.BG_DEEP, height=150)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        bottom.pack_propagate(False)

        log_frame = tk.Frame(bottom, bg=Theme.BG_CARD, padx=10, pady=8)
        log_frame.pack(fill="both", expand=True)

        header_row = tk.Frame(log_frame, bg=Theme.BG_CARD)
        header_row.pack(fill="x")

        tk.Label(header_row, text="操作日志",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(side="left")

        tk.Button(header_row, text="清空",
                  font=(Theme.FONT_FAMILY, 9),
                  fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                  activebackground=Theme.BG_ACTIVE,
                  activeforeground=Theme.TEXT_PRIMARY,
                  relief="flat", cursor="hand2", padx=10,
                  command=self._clear_log).pack(side="right")

        # 日志文本框 + 滚动条
        log_body = tk.Frame(log_frame, bg=Theme.BG_CARD)
        log_body.pack(fill="both", expand=True, pady=(6, 0))

        scrollbar = tk.Scrollbar(log_body)
        scrollbar.pack(side="right", fill="y")

        self._log_text = tk.Text(log_body, bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
                                 font=("Consolas", 9), padx=10, pady=8,
                                 relief="flat", wrap="word", state="disabled",
                                 yscrollcommand=scrollbar.set)
        self._log_text.pack(fill="both", expand=True)
        scrollbar.config(command=self._log_text.yview)

        self._log("创作者工具箱已就绪")

    # ---------------------------------------------------------------
    # 工具选择与面板切换
    # ---------------------------------------------------------------

    def _on_select_tool(self, tool_key):
        """选择工具，切换中栏面板"""
        self._current_tool = tool_key

        # 更新按钮高亮
        for key, _name, color, _deps in TOOL_DEFS:
            btn = self._tool_buttons[key]
            if key == tool_key:
                btn.config(bg=color, fg=Theme.BG_DEEP)
            else:
                btn.config(bg=Theme.BG_HOVER, fg=Theme.TEXT_SECONDARY)

        # 清空中栏容器
        for widget in self._middle_container.winfo_children():
            widget.destroy()

        # 根据工具构建对应面板
        builder = {
            "ai_copy":       self._build_ai_copy_panel,
            "stt":           self._build_stt_panel,
            "tts":           self._build_tts_panel,
            "ocr":           self._build_ocr_panel,
            "audio_extract": self._build_audio_extract_panel,
            "watermark":     self._build_watermark_panel,
        }.get(tool_key)
        if builder:
            builder(self._middle_container)

    # ---------------------------------------------------------------
    # 各工具输入面板
    # ---------------------------------------------------------------

    def _build_panel_header(self, parent, title, desc=""):
        """构建面板标题区"""
        tk.Label(parent, text=title,
                 font=(Theme.FONT_FAMILY, 14, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", padx=15, pady=(15, 4))
        if desc:
            tk.Label(parent, text=desc,
                     font=(Theme.FONT_FAMILY, 10),
                     fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD).pack(anchor="w", padx=15, pady=(0, 12))
        else:
            tk.Frame(parent, bg=Theme.BG_CARD, height=8).pack()

    def _make_path_row(self, parent, label, entry_var, filetypes=None, is_save=False):
        """创建带浏览按钮的文件路径输入行

        Args:
            parent: 父容器
            label: 标签文本
            entry_var: 与Entry绑定的StringVar
            filetypes: 文件类型过滤 [(描述, 扩展名), ...]
            is_save: 是否为保存对话框

        Returns:
            tk.Entry: 路径输入框
        """
        row = tk.Frame(parent, bg=Theme.BG_CARD)
        row.pack(fill="x", padx=15, pady=6)

        tk.Label(row, text=label,
                 font=(Theme.FONT_FAMILY, 11),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))

        input_row = tk.Frame(row, bg=Theme.BG_CARD)
        input_row.pack(fill="x")

        entry = tk.Entry(input_row, textvariable=entry_var,
                         font=(Theme.FONT_FAMILY, 10),
                         fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                         insertbackground=Theme.TEXT_PRIMARY,
                         relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        def _browse():
            if is_save:
                path = filedialog.asksaveasfilename(filetypes=filetypes) if filetypes \
                    else filedialog.asksaveasfilename()
            else:
                path = filedialog.askopenfilename(filetypes=filetypes) if filetypes \
                    else filedialog.askopenfilename()
            if path:
                entry_var.set(path)

        tk.Button(input_row, text="浏览...",
                  font=(Theme.FONT_FAMILY, 9),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_PRIMARY,
                  activebackground=Theme.COLOR_PRIMARY,
                  activeforeground=Theme.BG_DEEP,
                  relief="flat", cursor="hand2", padx=10,
                  command=_browse).pack(side="right")
        return entry

    def _make_result_text(self, parent, height=14):
        """创建结果文本框（带滚动条）"""
        wrap = tk.Frame(parent, bg=Theme.BG_CARD)
        wrap.pack(fill="both", expand=True, padx=15, pady=(8, 15))

        tk.Label(wrap, text="结果",
                 font=(Theme.FONT_FAMILY, 11, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))

        body = tk.Frame(wrap, bg=Theme.BG_CARD)
        body.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(body)
        scrollbar.pack(side="right", fill="y")

        txt = tk.Text(body, bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
                      font=(Theme.FONT_FAMILY, 10), padx=10, pady=8,
                      relief="flat", wrap="word", height=height,
                      yscrollcommand=scrollbar.set)
        txt.pack(fill="both", expand=True)
        scrollbar.config(command=txt.yview)
        return txt

    def _make_action_button(self, parent, text, cmd, color=Theme.COLOR_PRIMARY):
        """创建操作按钮"""
        btn = tk.Button(parent, text=text,
                        font=(Theme.FONT_FAMILY, 11, "bold"),
                        fg=Theme.BG_DEEP, bg=color,
                        activebackground=color,
                        activeforeground=Theme.BG_DEEP,
                        relief="flat", cursor="hand2", padx=24, pady=8,
                        command=cmd)
        btn.pack(anchor="w", padx=15, pady=(4, 8))
        return btn

    # ---- AI文案 ----
    def _build_ai_copy_panel(self, parent):
        """AI文案生成面板"""
        self._build_panel_header(parent, "AI智能文案", "输入话题与风格，一键生成种草/带货/脚本等文案")

        # 话题输入
        topic_row = tk.Frame(parent, bg=Theme.BG_CARD)
        topic_row.pack(fill="x", padx=15, pady=6)
        tk.Label(topic_row, text="话题",
                 font=(Theme.FONT_FAMILY, 11),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        self._copy_topic_var = tk.StringVar()
        tk.Entry(topic_row, textvariable=self._copy_topic_var,
                 font=(Theme.FONT_FAMILY, 10),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                 insertbackground=Theme.TEXT_PRIMARY,
                 relief="flat").pack(fill="x", ipady=4)

        # 风格选择
        style_row = tk.Frame(parent, bg=Theme.BG_CARD)
        style_row.pack(fill="x", padx=15, pady=6)
        tk.Label(style_row, text="风格",
                 font=(Theme.FONT_FAMILY, 11),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        self._copy_style_var = tk.StringVar(value=COPY_STYLES[0][1])
        style_menu = tk.OptionMenu(style_row, self._copy_style_var,
                                   *[name for _k, name in COPY_STYLES])
        style_menu.config(font=(Theme.FONT_FAMILY, 10),
                          fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                          activebackground=Theme.BG_ACTIVE,
                          activeforeground=Theme.TEXT_PRIMARY,
                          relief="flat", highlightthickness=0)
        style_menu.pack(fill="x", ipady=2)

        self._make_action_button(parent, "生成文案", self._cmd_ai_copy, Theme.COLOR_PRIMARY)
        self._copy_result_text = self._make_result_text(parent, height=12)

    # ---- 语音转文字 ----
    def _build_stt_panel(self, parent):
        """语音转文字面板"""
        self._build_panel_header(parent, "语音转文字", "选择音频文件，自动转录为文字（中文）")

        self._stt_path_var = tk.StringVar()
        self._make_path_row(parent, "音频文件路径", self._stt_path_var,
                            filetypes=[("音频文件", "*.mp3 *.wav *.flac *.aac *.m4a"),
                                       ("所有文件", "*.*")])

        self._make_action_button(parent, "开始转录", self._cmd_stt, Theme.COLOR_ACCENT)
        self._stt_result_text = self._make_result_text(parent, height=14)

    # ---- 智能配音 ----
    def _build_tts_panel(self, parent):
        """智能配音面板"""
        self._build_panel_header(parent, "智能配音", "输入文本，选择语音，合成MP3音频")

        text_row = tk.Frame(parent, bg=Theme.BG_CARD)
        text_row.pack(fill="x", padx=15, pady=6)
        tk.Label(text_row, text="待合成文本",
                 font=(Theme.FONT_FAMILY, 11),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        self._tts_text = tk.Text(text_row, font=(Theme.FONT_FAMILY, 10),
                                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                                 insertbackground=Theme.TEXT_PRIMARY,
                                 relief="flat", height=6, wrap="word")
        self._tts_text.pack(fill="x")

        # 语音选择
        voice_row = tk.Frame(parent, bg=Theme.BG_CARD)
        voice_row.pack(fill="x", padx=15, pady=6)
        tk.Label(voice_row, text="语音",
                 font=(Theme.FONT_FAMILY, 11),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 4))
        self._tts_voice_var = tk.StringVar(value=TTS_VOICES[0][1])
        voice_menu = tk.OptionMenu(voice_row, self._tts_voice_var,
                                   *[name for _k, name in TTS_VOICES])
        voice_menu.config(font=(Theme.FONT_FAMILY, 10),
                          fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                          activebackground=Theme.BG_ACTIVE,
                          activeforeground=Theme.TEXT_PRIMARY,
                          relief="flat", highlightthickness=0)
        voice_menu.pack(fill="x", ipady=2)

        self._make_action_button(parent, "合成配音", self._cmd_tts, Theme.COLOR_SECONDARY)
        self._tts_result_text = self._make_result_text(parent, height=6)

    # ---- OCR识别 ----
    def _build_ocr_panel(self, parent):
        """OCR图片转文字面板"""
        self._build_panel_header(parent, "OCR图片转文字", "选择图片，识别其中的中英文文字")

        self._ocr_path_var = tk.StringVar()
        self._make_path_row(parent, "图片文件路径", self._ocr_path_var,
                            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp"),
                                       ("所有文件", "*.*")])

        self._make_action_button(parent, "开始识别", self._cmd_ocr, Theme.COLOR_PURPLE)
        self._ocr_result_text = self._make_result_text(parent, height=14)

    # ---- 音频提取 ----
    def _build_audio_extract_panel(self, parent):
        """音频提取面板"""
        self._build_panel_header(parent, "音频提取", "从视频文件中提取音频轨道")

        self._extract_path_var = tk.StringVar()
        self._make_path_row(parent, "视频文件路径", self._extract_path_var,
                            filetypes=[("视频文件", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv"),
                                       ("所有文件", "*.*")])

        self._make_action_button(parent, "提取音频", self._cmd_audio_extract, Theme.COLOR_PINK)
        self._extract_result_text = self._make_result_text(parent, height=8)

    # ---- 去水印 ----
    def _build_watermark_panel(self, parent):
        """去水印面板"""
        self._build_panel_header(parent, "去水印", "对图片进行水印区域检测与去除处理")

        self._watermark_path_var = tk.StringVar()
        self._make_path_row(parent, "图片文件路径", self._watermark_path_var,
                            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp"),
                                       ("所有文件", "*.*")])

        self._make_action_button(parent, "处理水印", self._cmd_watermark, Theme.COLOR_AMBER)
        self._watermark_result_text = self._make_result_text(parent, height=8)

    # ---------------------------------------------------------------
    # 工具命令执行（后台线程，避免阻塞UI）
    # ---------------------------------------------------------------

    def _run_tool(self, action_name, func, result_handler):
        """通用工具执行器：校验域、后台执行、回主线程更新UI

        Args:
            action_name: 操作名称（用于日志）
            func: 无参可调用，返回结果dict
            result_handler: 接收结果dict的回调（在主线程执行）
        """
        if not self._ensure_domain():
            reason = self._domain_err or "未知原因"
            messagebox.showerror("创作者工具箱子系统初始化失败",
                                 f"无法连接创作者服务：{reason}\n\n请检查项目目录是否完整，或稍后重试。")
            return

        self._log(f"开始执行：{action_name}")

        def worker():
            try:
                result = func()
                self.root.after(0, lambda: result_handler(result))
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: (
                    self._log(f"[失败] {action_name}: {err}"),
                    messagebox.showerror("错误", f"{action_name}失败: {err}")
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _cmd_ai_copy(self):
        """执行AI文案生成"""
        topic = self._copy_topic_var.get().strip()
        if not topic:
            messagebox.showwarning("提示", "请输入文案话题")
            return
        # 反查风格key
        style_key = COPY_STYLES[0][0]
        for k, name in COPY_STYLES:
            if name == self._copy_style_var.get():
                style_key = k
                break

        self._run_tool(
            "AI文案生成",
            lambda: self._domain.write_copy(topic, style=style_key),
            lambda r: self._on_ai_copy_done(r, topic)
        )

    def _on_ai_copy_done(self, result, topic):
        """AI文案生成完成"""
        self._display_result(self._copy_result_text, result, topic=topic)
        mode = result.get("mode", "unknown")
        mode_text = {"ai": "AI生成", "template": "模板生成"}.get(mode, mode)
        word_count = result.get("word_count", 0)
        self._log(f"AI文案生成完成（{mode_text}，{word_count}字）")

    def _cmd_stt(self):
        """执行语音转文字"""
        path = self._stt_path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请选择音频文件")
            return
        self._run_tool(
            "语音转文字",
            lambda: self._domain.transcribe_audio(path),
            lambda r: self._on_stt_done(r, path)
        )

    def _on_stt_done(self, result, path):
        """语音转文字完成"""
        self._display_result(self._stt_result_text, result)
        text = result.get("text", "")
        if text:
            self._log(f"语音转文字完成，识别 {len(text)} 字")
        else:
            self._log(f"语音转文字完成，未识别到内容（{result.get('mode', 'unknown')}）")

    def _cmd_tts(self):
        """执行智能配音"""
        text = self._tts_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("提示", "请输入待合成文本")
            return
        # 反查语音key
        voice_key = TTS_VOICES[0][0]
        for k, name in TTS_VOICES:
            if name == self._tts_voice_var.get():
                voice_key = k
                break

        self._run_tool(
            "智能配音",
            lambda: self._domain.text_to_speech(text, output_path=None, voice=voice_key),
            lambda r: self._on_tts_done(r)
        )

    def _on_tts_done(self, result):
        """智能配音完成"""
        self._display_result(self._tts_result_text, result)
        audio_path = result.get("audio_path", "")
        if audio_path:
            self._log(f"智能配音完成：{audio_path}")
        else:
            self._log(f"智能配音完成（{result.get('mode', 'unknown')}）")

    def _cmd_ocr(self):
        """执行OCR识别"""
        path = self._ocr_path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请选择图片文件")
            return
        self._run_tool(
            "OCR识别",
            lambda: self._domain.recognize_image(path),
            lambda r: self._on_ocr_done(r, path)
        )

    def _on_ocr_done(self, result, path):
        """OCR识别完成"""
        self._display_result(self._ocr_result_text, result)
        text = result.get("text", "")
        if text:
            self._log(f"OCR识别完成，识别 {len(text)} 字")
        else:
            self._log(f"OCR识别完成，未识别到文字（{result.get('mode', 'unknown')}）")

    def _cmd_audio_extract(self):
        """执行音频提取"""
        path = self._extract_path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请选择视频文件")
            return
        self._run_tool(
            "音频提取",
            lambda: self._domain.extract_audio(path),
            lambda r: self._on_extract_done(r, path)
        )

    def _on_extract_done(self, result, path):
        """音频提取完成"""
        self._display_result(self._extract_result_text, result)
        audio_path = result.get("audio_path", "")
        if audio_path:
            self._log(f"音频提取完成：{audio_path}")
        else:
            self._log(f"音频提取完成（{result.get('mode', 'unknown')}）")

    def _cmd_watermark(self):
        """执行去水印"""
        path = self._watermark_path_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请选择图片文件")
            return
        self._run_tool(
            "去水印",
            lambda: self._domain.remove_watermark(path),
            lambda r: self._on_watermark_done(r, path)
        )

    def _on_watermark_done(self, result, path):
        """去水印完成"""
        self._display_result(self._watermark_result_text, result)
        out_path = result.get("output_path", "")
        if out_path:
            self._log(f"去水印完成：{out_path}")
        else:
            self._log(f"去水印完成（{result.get('mode', 'unknown')}）")

    # ---------------------------------------------------------------
    # 结果展示与状态
    # ---------------------------------------------------------------

    def _display_result(self, text_widget, result, topic=None):
        """将工具返回结果格式化后写入文本框

        根据结果dict中的字段智能格式化，缺失依赖时显示降级提示。
        """
        text_widget.config(state="normal")
        text_widget.delete("1.0", "end")

        # 降级/错误模式优先提示
        mode = result.get("mode", "")
        if mode in ("degraded", "error"):
            text_widget.insert("end", "该工具依赖未安装，当前为降级模式\n\n",
                               ("warn",))
            text_widget.tag_config("warn", foreground=Theme.COLOR_AMBER)

        error = result.get("error")
        if error:
            text_widget.insert("end", f"错误：{error}\n\n",
                               ("err",))
            text_widget.tag_config("err", foreground=Theme.COLOR_RED)

        # 文案类：标题 + 正文 + 标签
        if "content" in result or "title" in result:
            title = result.get("title", "")
            content = result.get("content", "")
            tags = result.get("tags", [])
            if title:
                text_widget.insert("end", f"【标题】{title}\n\n", ("title",))
                text_widget.tag_config("title", foreground=Theme.COLOR_PRIMARY,
                                       font=(Theme.FONT_FAMILY, 11, "bold"))
            if content:
                text_widget.insert("end", f"{content}\n\n")
            if tags:
                text_widget.insert("end", "【标签】" + " ".join(f"#{t}" for t in tags),
                                   ("tag",))
                text_widget.tag_config("tag", foreground=Theme.COLOR_SECONDARY)
        # 纯文本类（OCR/STT）：text字段
        elif result.get("text"):
            text_widget.insert("end", result["text"])

        # 通用元信息：输出路径 / 时长 / 置信度等
        meta_lines = []
        for k in ("audio_path", "output_path", "duration", "size_bytes",
                  "confidence", "voice", "language", "speed", "lang"):
            if k in result and result[k] not in (None, ""):
                val = result[k]
                if k == "duration" and isinstance(val, (int, float)):
                    val = f"{val:.1f}秒"
                if k == "size_bytes" and isinstance(val, (int, float)):
                    val = f"{val / 1024:.1f} KB"
                meta_lines.append(f"{k}: {val}")
        if meta_lines:
            if text_widget.index("end-1c") != "1.0":
                text_widget.insert("end", "\n\n")
            text_widget.insert("end", "【元信息】\n" + "\n".join(meta_lines),
                               ("meta",))
            text_widget.tag_config("meta", foreground=Theme.TEXT_SECONDARY)

        # 兜底：无任何可显示字段时，输出完整字典
        if text_widget.index("end-1c") == "1.0":
            import json
            try:
                text_widget.insert("end", json.dumps(result, ensure_ascii=False, indent=2,
                                                     default=str))
            except Exception:
                text_widget.insert("end", str(result))

        text_widget.config(state="disabled")
        text_widget.see("end")

    def _refresh_status(self):
        """刷新右栏工具状态面板"""
        if self._domain is None:
            for key in self._tool_status_labels:
                self._tool_status_labels[key].config(text="未就绪", fg=Theme.COLOR_RED)
            self._status_label.config(text="子系统: 未就绪", fg=Theme.COLOR_RED)
            return

        try:
            status = self._domain.status()
            tools = status.get("tools", {})
            deps = status.get("dependencies", {})

            for key, _name, _color, dep_keys in TOOL_DEFS:
                # 该工具所有依赖是否可用
                all_ok = all(deps.get(d, False) for d in dep_keys) if dep_keys else True
                # 兼容部分工具可用但降级（如AI文案模板模式）
                tool_text = tools.get(key, "")
                if all_ok:
                    text, color = "可用", Theme.COLOR_GREEN
                elif tool_text and "降级" not in tool_text:
                    text, color = tool_text, Theme.COLOR_SECONDARY
                else:
                    text, color = "降级", Theme.COLOR_AMBER
                self._tool_status_labels[key].config(text=text, fg=color)

            # 顶部状态摘要
            available = sum(1 for v in deps.values() if v)
            total = len(deps) if deps else 0
            self._status_label.config(
                text=f"子系统: 就绪 ({available}/{total} 依赖可用)",
                fg=Theme.COLOR_GREEN if available > 0 else Theme.COLOR_AMBER)
            self._log(f"工具状态已刷新（{available}/{total} 依赖可用）")
        except Exception as e:
            self._log(f"状态刷新失败: {e}")
            self._status_label.config(text="子系统: 状态查询失败", fg=Theme.COLOR_RED)

    # ---------------------------------------------------------------
    # 日志
    # ---------------------------------------------------------------

    def _log(self, message):
        """追加一条操作日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self._log_text.config(state="normal")
        self._log_text.insert("end", line)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        """清空操作日志"""
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ---------------------------------------------------------------
    # 运行
    # ---------------------------------------------------------------

    def run(self):
        """启动GUI主循环"""
        # 首次刷新工具状态
        self.root.after(400, self._refresh_status)
        self.root.mainloop()


# =======================================================================
# 入口
# =======================================================================
def main():
    """创作者工具箱入口"""
    try:
        from core.gui_registry import register
        register('creator', '创作者工具箱')
    except Exception:
        pass
    root = tk.Tk()
    try:
        from core.tk_style import apply_dark_style
        apply_dark_style(root)
    except Exception:
        pass
    app = CreatorToolboxWindow(root)
    app.run()


if __name__ == "__main__":
    main()
