# -*- coding: utf-8 -*-
"""音频工具箱 GUI（独立模块，逻辑不变，仅从 audio_toolkit 包导入依赖）"""
import os
import logging
import threading

logger = logging.getLogger(__name__)

from ._core import FFMPEG_PATH, FORMATS, VIDEO_EXTS, AUDIO_EXTS
from .ffmpeg_ops import (
    video_to_audio, convert_audio, read_metadata, write_metadata,
    trim_audio, concat_audio, get_audio_info, format_duration,
)
from .processing import normalize_loudness, analyze_audio, smart_optimize


class _GuiState:
    """持有 run_gui 内所有可变状态和控件引用，使回调可提取到模块级。"""
    __slots__ = ("root", "file_list", "output_dir_var", "format_var", "status_var",
                 "progress_var", "is_processing", "mode_var", "tree", "file_count_label",
                 "meta_vars", "meta_path_var", "loud_path_var", "smart_path_var",
                 "smart_report", "trim_tree", "trim_count_label", "trim_files",
                 "start_sec_var", "end_sec_var", "convert_btn")


def _apply_theme(style):
    """配置 ttk 深色主题样式。"""
    style.theme_use("clam")
    style.configure("Dark.TFrame", background="#1a1a2e")
    style.configure("Dark.TLabel", background="#1a1a2e", foreground="#e0e0e0",
                    font=("Microsoft YaHei UI", 10))
    style.configure("Title.TLabel", background="#1a1a2e", foreground="#00d4aa",
                    font=("Microsoft YaHei UI", 16, "bold"))
    style.configure("Status.TLabel", background="#1a1a2e", foreground="#7a8499",
                    font=("Microsoft YaHei UI", 9))
    style.configure("Dark.TButton", font=("Microsoft YaHei UI", 10))
    style.configure("Convert.TButton", font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("Dark.TLabelframe", background="#1a1a2e", foreground="#00d4aa")
    style.configure("Dark.TLabelframe.Label", background="#1a1a2e", foreground="#00d4aa",
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Dark.TNotebook", background="#1a1a2e")
    style.configure("Dark.TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=[12, 4])


def _build_convert_tab(notebook, st: _GuiState):
    """构建 Tab1：视频转音频 / 格式互转。"""
    import tkinter as tk
    from tkinter import ttk, filedialog

    tab = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab, text=" 转换 ")

    mode_frame = ttk.Frame(tab, style="Dark.TFrame")
    mode_frame.pack(fill="x", padx=10, pady=(5, 0))
    ttk.Radiobutton(mode_frame, text="视频转音频", variable=st.mode_var, value="video",
                     style="Dark.TLabel").pack(side="left", padx=10)
    ttk.Radiobutton(mode_frame, text="音频格式互转", variable=st.mode_var, value="audio",
                     style="Dark.TLabel").pack(side="left", padx=10)

    list_frame = ttk.LabelFrame(tab, text=" 文件列表 ", style="Dark.TLabelframe")
    list_frame.pack(fill="both", expand=True, padx=10, pady=5)

    btn_frame = ttk.Frame(list_frame, style="Dark.TFrame")
    btn_frame.pack(fill="x", padx=10, pady=5)
    ttk.Button(btn_frame, text="添加文件", command=lambda: _cb_add_files(st)).pack(side="left", padx=2)
    ttk.Button(btn_frame, text="添加文件夹", command=lambda: _cb_add_folder(st)).pack(side="left", padx=2)
    ttk.Button(btn_frame, text="清空", command=lambda: _cb_clear_list(st)).pack(side="left", padx=2)
    st.file_count_label = ttk.Label(btn_frame, text="0 个文件", style="Status.TLabel")
    st.file_count_label.pack(side="right", padx=5)

    columns = ("filename", "size", "duration", "status")
    st.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
    st.tree.heading("filename", text="文件名")
    st.tree.heading("size", text="大小")
    st.tree.heading("duration", text="时长")
    st.tree.heading("status", text="状态")
    st.tree.column("filename", width=350, minwidth=200)
    st.tree.column("size", width=80, minwidth=60, anchor="center")
    st.tree.column("duration", width=80, minwidth=60, anchor="center")
    st.tree.column("status", width=180, minwidth=120, anchor="center")
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=st.tree.yview)
    st.tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=5)
    st.tree.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 5))

    settings_frame = ttk.Frame(tab, style="Dark.TFrame")
    settings_frame.pack(fill="x", padx=10, pady=5)
    ttk.Label(settings_frame, text="输出目录:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Entry(settings_frame, textvariable=st.output_dir_var, width=35).pack(side="left", padx=2)
    ttk.Button(settings_frame, text="浏览",
               command=lambda: st.output_dir_var.set(filedialog.askdirectory() or st.output_dir_var.get())).pack(side="left", padx=2)
    ttk.Label(settings_frame, text="格式:", style="Dark.TLabel").pack(side="left", padx=(20, 5))
    ttk.Combobox(settings_frame, textvariable=st.format_var, values=list(FORMATS.keys()),
                 state="readonly", width=16).pack(side="left", padx=2)


def _build_meta_tab(notebook, st: _GuiState):
    """构建 Tab2：元数据编辑。"""
    import tkinter as tk
    from tkinter import ttk, filedialog

    tab = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab, text=" 元数据 ")

    meta_file_frame = ttk.Frame(tab, style="Dark.TFrame")
    meta_file_frame.pack(fill="x", padx=15, pady=(10, 5))
    ttk.Label(meta_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Entry(meta_file_frame, textvariable=st.meta_path_var, width=50).pack(side="left", padx=2, fill="x", expand=True)
    ttk.Button(meta_file_frame, text="浏览", command=lambda: _cb_browse_meta(st)).pack(side="left", padx=2)
    ttk.Button(meta_file_frame, text="读取", command=lambda: _cb_load_metadata(st)).pack(side="left", padx=2)

    fields_frame = ttk.LabelFrame(tab, text=" 标签信息 ", style="Dark.TLabelframe")
    fields_frame.pack(fill="x", padx=15, pady=5)

    field_defs = [
        ("title", "歌名"), ("artist", "歌手"), ("album", "专辑"),
        ("year", "年份"), ("genre", "流派"), ("track", "曲号"),
        ("comment", "备注"),
    ]
    for key, label in field_defs:
        row = ttk.Frame(fields_frame, style="Dark.TFrame")
        row.pack(fill="x", padx=10, pady=3)
        ttk.Label(row, text=f"{label}:", width=8, style="Dark.TLabel").pack(side="left")
        var = tk.StringVar()
        st.meta_vars[key] = var
        ttk.Entry(row, textvariable=var, width=40).pack(side="left", padx=5, fill="x", expand=True)

    ttk.Button(fields_frame, text="保存标签", command=lambda: _cb_save_metadata(st)).pack(pady=8)


def _build_loud_tab(notebook, st: _GuiState):
    """构建 Tab3：音量标准化。"""
    import tkinter as tk
    from tkinter import ttk, filedialog

    tab = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab, text=" 标准化 ")

    ttk.Label(tab,
              text="EBU R128 音量标准化\n将音频音量统一到 -14 LUFS（音乐平台推荐响度）",
              style="Dark.TLabel", justify="center").pack(pady=(15, 10))

    loud_file_frame = ttk.Frame(tab, style="Dark.TFrame")
    loud_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(loud_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Entry(loud_file_frame, textvariable=st.loud_path_var, width=50).pack(side="left", padx=2, fill="x", expand=True)
    ttk.Button(loud_file_frame, text="浏览",
               command=lambda: st.loud_path_var.set(
                   filedialog.askopenfilename(
                       filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")]) or "")).pack(side="left", padx=2)

    loud_btn_frame = ttk.Frame(tab, style="Dark.TFrame")
    loud_btn_frame.pack(fill="x", padx=15, pady=10)
    ttk.Button(loud_btn_frame, text="开始标准化", command=lambda: _cb_do_normalize(st)).pack(pady=5)


def _build_trim_tab(notebook, st: _GuiState):
    """构建 Tab4：裁剪拼接。"""
    import tkinter as tk
    from tkinter import ttk

    tab = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab, text=" 裁剪拼接 ")

    ttk.Label(tab,
              text="裁剪: 选择单个文件，设定起止时间\n拼接: 选择多个文件，按顺序合并",
              style="Dark.TLabel", justify="center").pack(pady=(15, 10))

    trim_file_frame = ttk.Frame(tab, style="Dark.TFrame")
    trim_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(trim_file_frame, text="文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Button(trim_file_frame, text="添加音频", command=lambda: _cb_add_trim_files(st)).pack(side="left", padx=2)
    st.trim_count_label = ttk.Label(trim_file_frame, text="", style="Status.TLabel")
    st.trim_count_label.pack(side="left", padx=5)

    trim_list_frame = ttk.Frame(tab, style="Dark.TFrame")
    trim_list_frame.pack(fill="both", expand=True, padx=15, pady=5)

    trim_columns = ("filename", "duration")
    st.trim_tree = ttk.Treeview(trim_list_frame, columns=trim_columns, show="headings", height=6)
    st.trim_tree.heading("filename", text="文件名")
    st.trim_tree.heading("duration", text="时长")
    st.trim_tree.column("filename", width=400, minwidth=200)
    st.trim_tree.column("duration", width=100, minwidth=80, anchor="center")
    st.trim_tree.pack(fill="both", expand=True)

    trim_params = ttk.Frame(tab, style="Dark.TFrame")
    trim_params.pack(fill="x", padx=15, pady=5)
    ttk.Label(trim_params, text="开始(秒):", style="Dark.TLabel").pack(side="left")
    ttk.Entry(trim_params, textvariable=st.start_sec_var, width=8).pack(side="left", padx=5)
    ttk.Label(trim_params, text="结束(秒):", style="Dark.TLabel").pack(side="left", padx=(15, 0))
    ttk.Entry(trim_params, textvariable=st.end_sec_var, width=8).pack(side="left", padx=5)

    trim_btn_frame = ttk.Frame(tab, style="Dark.TFrame")
    trim_btn_frame.pack(fill="x", padx=15, pady=5)
    ttk.Button(trim_btn_frame, text="裁剪", command=lambda: _cb_do_trim(st)).pack(side="left", padx=5)
    ttk.Button(trim_btn_frame, text="拼接全部", command=lambda: _cb_do_concat(st)).pack(side="left", padx=5)


def _build_smart_tab(notebook, st: _GuiState):
    """构建 Tab5：智能优化。"""
    import tkinter as tk
    from tkinter import ttk, filedialog

    tab = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(tab, text=" 智能优化 ")

    ttk.Label(tab,
              text="智能检测音频问题并一键修复\n\n自动处理: 采样率→44100Hz | 声道→立体声\n"
                   "码率→320kbps | 音量→-14LUFS | 保留元数据",
              style="Dark.TLabel", justify="center").pack(pady=(15, 10))

    smart_file_frame = ttk.Frame(tab, style="Dark.TFrame")
    smart_file_frame.pack(fill="x", padx=15, pady=5)
    ttk.Label(smart_file_frame, text="音频文件:", style="Dark.TLabel").pack(side="left", padx=(0, 5))
    ttk.Entry(smart_file_frame, textvariable=st.smart_path_var, width=50).pack(side="left", padx=2, fill="x", expand=True)
    ttk.Button(smart_file_frame, text="浏览",
               command=lambda: st.smart_path_var.set(
                   filedialog.askopenfilename(
                       filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma"), ("所有文件", "*.*")]) or "")).pack(side="left", padx=2)

    st.smart_report = tk.Text(tab, height=10, bg="#131a2a", fg="#e0e0e0",
                             font=("Microsoft YaHei UI", 10), wrap="word",
                             insertbackground="#e0e0e0", selectbackground="#00d4aa")
    st.smart_report.pack(fill="both", expand=True, padx=15, pady=5)

    smart_btn_frame = ttk.Frame(tab, style="Dark.TFrame")
    smart_btn_frame.pack(fill="x", padx=15, pady=5)
    ttk.Button(smart_btn_frame, text="检测问题", command=lambda: _cb_do_analyze(st)).pack(side="left", padx=5)
    ttk.Button(smart_btn_frame, text="一键优化", command=lambda: _cb_do_smart_optimize(st)).pack(side="left", padx=5)


# ---------------------------------------------------------------------------
# 回调函数（模块级，通过 _GuiState 访问闭包状态）
# ---------------------------------------------------------------------------

def _cb_add_files(st: _GuiState):
    from tkinter import filedialog
    mode = st.mode_var.get()
    exts = [("视频文件", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm")] if mode == "video" \
        else [("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma")]
    paths = filedialog.askopenfilenames(title="选择文件", filetypes=exts + [("所有文件", "*.*")])
    for p in paths:
        iid = st.tree.insert("", "end", values=(os.path.basename(p), "...", "...", "等待中"))
        st.file_list.append({"path": p, "iid": iid})
    _cb_update_count(st)


def _cb_add_folder(st: _GuiState):
    from tkinter import filedialog
    dir_path = filedialog.askdirectory(title="选择文件夹")
    if dir_path:
        mode = st.mode_var.get()
        for f in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, f)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(f)[1].lower()
            if (mode == "video" and ext in VIDEO_EXTS) or (mode == "audio" and ext in AUDIO_EXTS):
                iid = st.tree.insert("", "end", values=(f, "...", "...", "等待中"))
                st.file_list.append({"path": full, "iid": iid})
        _cb_update_count(st)


def _cb_clear_list(st: _GuiState):
    st.tree.delete(*st.tree.get_children())
    st.file_list.clear()
    _cb_update_count(st)


def _cb_update_count(st: _GuiState):
    st.file_count_label.config(text=f"{len(st.file_list)} 个文件")


def _cb_browse_meta(st: _GuiState):
    from tkinter import filedialog
    p = filedialog.askopenfilename(
        filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")])
    if p:
        st.meta_path_var.set(p)


def _cb_load_metadata(st: _GuiState):
    from tkinter import messagebox
    p = st.meta_path_var.get()
    if not p or not os.path.exists(p):
        messagebox.showwarning("提示", "请先选择音频文件")
        return
    meta = read_metadata(p)
    if meta.get("error"):
        messagebox.showerror("错误", meta["error"])
        return
    for key, var in st.meta_vars.items():
        var.set(meta.get(key, ""))
    st.status_var.set(f"已读取标签: {os.path.basename(p)}")


def _cb_save_metadata(st: _GuiState):
    from tkinter import messagebox
    p = st.meta_path_var.get()
    if not p or not os.path.exists(p):
        messagebox.showwarning("提示", "请先选择音频文件")
        return
    kwargs = {}
    for key, var in st.meta_vars.items():
        val = var.get().strip()
        if val:
            kwargs[key] = val
    result = write_metadata(p, **kwargs)
    if result["success"]:
        messagebox.showinfo("成功", "标签已保存")
        st.status_var.set("标签保存成功")
    else:
        messagebox.showerror("失败", result.get("error", "未知错误"))


def _cb_do_normalize(st: _GuiState):
    from tkinter import messagebox
    p = st.loud_path_var.get()
    if not p or not os.path.exists(p):
        messagebox.showwarning("提示", "请先选择音频文件")
        return
    out = st.output_dir_var.get() or os.path.dirname(p)
    st.status_var.set("正在进行音量标准化...")
    st.progress_var.set(10)

    def worker():
        result = normalize_loudness(p, out, progress_callback=prog_cb)
        st.root.after(0, lambda: finish(result))
        st.root.after(0, lambda: st.convert_btn.config(state="normal"))

    def prog_cb(pct, msg):
        st.root.after(0, lambda: st.progress_var.set(pct))
        st.root.after(0, lambda: st.status_var.set(msg))

    def finish(result):
        if result["success"]:
            out_name = os.path.basename(result["output"])
            st.status_var.set(f"标准化完成 -> {out_name} ({result.get('mode', '?')})")
            messagebox.showinfo("完成",
                                f"音量标准化完成!\n原始: {result.get('original_lufs', '?')} LUFS\n"
                                f"目标: {result.get('target_lufs', -14)} LUFS\n输出: {out_name}")
        else:
            st.status_var.set("标准化失败")
            messagebox.showerror("失败", result.get("error", "未知错误"))

    st.convert_btn.config(state="disabled")
    threading.Thread(target=worker, daemon=True).start()


def _cb_add_trim_files(st: _GuiState):
    from tkinter import filedialog
    paths = filedialog.askopenfilenames(
        title="选择音频文件",
        filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.ogg"), ("所有文件", "*.*")])
    for p in paths:
        info = get_audio_info(p)
        dur = format_duration(info.get("duration", 0))
        st.trim_tree.insert("", "end", values=(os.path.basename(p), dur))
        st.trim_files.append(p)
    st.trim_count_label.config(text=f"{len(st.trim_files)} 个文件")


def _cb_do_trim(st: _GuiState):
    from tkinter import messagebox
    if len(st.trim_files) == 0:
        messagebox.showwarning("提示", "请先添加文件")
        return
    p = st.trim_files[0]
    try:
        start = float(st.start_sec_var.get())
    except ValueError:
        start = 0
    try:
        end = float(st.end_sec_var.get())
    except ValueError:
        messagebox.showwarning("提示", "请输入结束时间(秒)")
        return
    if end <= start:
        messagebox.showwarning("提示", "结束时间必须大于开始时间")
        return
    out = st.output_dir_var.get() or os.path.dirname(p)
    st.status_var.set(f"裁剪中 {start}s - {end}s...")
    result = trim_audio(p, out, start, end)
    if result["success"]:
        st.status_var.set(f"裁剪完成 -> {os.path.basename(result['output'])}")
        messagebox.showinfo("完成", f"裁剪完成! 时长: {result['duration_sec']:.0f}秒")
    else:
        messagebox.showerror("失败", result.get("error", ""))


def _cb_do_concat(st: _GuiState):
    from tkinter import messagebox
    if len(st.trim_files) < 2:
        messagebox.showwarning("提示", "拼接至少需要2个文件")
        return
    out = st.output_dir_var.get() or os.path.dirname(st.trim_files[0])
    st.status_var.set("拼接中...")
    result = concat_audio(st.trim_files, out)
    if result["success"]:
        st.status_var.set(f"拼接完成 -> {os.path.basename(result['output'])}")
        messagebox.showinfo("完成", f"拼接完成! {len(st.trim_files)}个文件已合并")
    else:
        messagebox.showerror("失败", result.get("error", ""))


def _cb_do_analyze(st: _GuiState):
    from tkinter import messagebox
    p = st.smart_path_var.get()
    if not p or not os.path.exists(p):
        messagebox.showwarning("提示", "请先选择音频文件")
        return
    report = analyze_audio(p)
    st.smart_report.delete("1.0", "end")
    st.smart_report.insert("end",
                        f"文件: {report['filename']}\n"
                        f"大小: {report.get('size_mb', 0):.2f} MB\n"
                        f"时长: {format_duration(report.get('duration', 0))}\n"
                        f"编码: {report.get('codec', '?')} | 采样率: {report.get('sample_rate', '?')}Hz | "
                        f"声道: {report.get('channels', '?')} | 码率: {report.get('bitrate', 0):.0f}kbps\n"
                        f"\n质量评分: {report['score']}/100\n{'=' * 40}\n")
    if report["issues"]:
        for issue in report["issues"]:
            icon = "[!]" if issue.get("score", 0) <= -15 else "[~]"
            st.smart_report.insert("end", f"{icon} {issue['msg']} (扣{abs(issue.get('score', 0))}分)\n")
    else:
        st.smart_report.insert("end", "[OK] 音频质量良好，无需优化\n")
    st.status_var.set(f"检测完成 - 评分: {report['score']}/100")


def _cb_do_smart_optimize(st: _GuiState):
    from tkinter import messagebox
    p = st.smart_path_var.get()
    if not p or not os.path.exists(p):
        messagebox.showwarning("提示", "请先选择音频文件")
        return
    out = st.output_dir_var.get() or os.path.dirname(p)
    st.status_var.set("智能优化中...")
    st.progress_var.set(10)

    def worker():
        result = smart_optimize(p, out, progress_callback=prog_cb)
        st.root.after(0, lambda: finish(result))

    def prog_cb(pct, msg):
        st.root.after(0, lambda: st.progress_var.set(pct))
        st.root.after(0, lambda: st.status_var.set(msg))

    def finish(result):
        if result["success"]:
            out_name = os.path.basename(result["output"])
            fixes = "\n".join(f"  - {f}" for f in result.get("issues_fixed", []))
            st.smart_report.delete("1.0", "end")
            st.smart_report.insert("end",
                                f"[OK] 优化完成!\n输出: {out_name}\n"
                                f"处理时长: {result['time']:.1f}s\n修复项目:\n{fixes}\n")
            st.status_var.set(f"优化完成 -> {out_name}")
            messagebox.showinfo("完成",
                                f"智能优化完成!\n输出: {out_name}\n\n"
                                f"修复了 {len(result.get('issues_fixed', []))} 个问题")
        else:
            st.status_var.set("优化失败")
            messagebox.showerror("失败", result.get("error", ""))

    threading.Thread(target=worker, daemon=True).start()


def _convert_worker(st: _GuiState):
    """转换工作线程：遍历文件列表执行视频转音频/格式互转。"""
    total = len(st.file_list)
    fmt = st.format_var.get()
    mode = st.mode_var.get()

    for idx, item in enumerate(st.file_list):
        p = item["path"]
        iid = item["iid"]
        st.root.after(0, lambda iid=iid, idx=idx, total=total:
                   st.tree.item(iid, values=(st.tree.item(iid)["values"][0],
                                          st.tree.item(iid)["values"][1],
                                          st.tree.item(iid)["values"][2],
                                          f"处理中 ({idx+1}/{total})")))
        st.root.after(0, lambda idx=idx, total=total:
                   st.status_var.set(f"处理 {idx+1}/{total}: {os.path.basename(p)}"))

        def prog_cb(pct, msg):
            overall = (idx + pct / 100) / total * 100
            st.root.after(0, lambda o=overall: st.progress_var.set(o))

        if mode == "video":
            result = video_to_audio(p, st.output_dir_var.get(), fmt, prog_cb)
        else:
            result = convert_audio(p, st.output_dir_var.get(), fmt, prog_cb)

        if result["success"]:
            out_name = os.path.basename(result["output"])
            if len(out_name) > 25:
                out_name = out_name[:15] + "..." + out_name[-5:]
            s_val = f"完成 -> {out_name} ({result.get('size_mb', 0):.1f}MB)"
            st.root.after(0, lambda iid=iid, s=s_val: st.tree.item(iid, values=(
                st.tree.item(iid)["values"][0], st.tree.item(iid)["values"][1],
                st.tree.item(iid)["values"][2], s)))
        else:
            err = result.get("error", "")[:50]
            st.root.after(0, lambda iid=iid, e=err: st.tree.item(iid, values=(
                st.tree.item(iid)["values"][0], st.tree.item(iid)["values"][1],
                st.tree.item(iid)["values"][2], f"失败: {e}")))

        st.progress_var.set((idx + 1) / total * 100)

    st.root.after(0, lambda: st.status_var.set("全部处理完成!"))
    st.root.after(0, lambda: st.progress_var.set(100))
    st.is_processing = False
    st.root.after(0, lambda: st.convert_btn.config(state="normal"))


def _cb_start_convert(st: _GuiState):
    from tkinter import messagebox
    if st.is_processing or not st.file_list:
        messagebox.showwarning("提示", "请先添加文件")
        return
    if not st.output_dir_var.get():
        st.output_dir_var.set(os.path.dirname(st.file_list[0]["path"]))
    st.is_processing = True
    st.convert_btn.config(state="disabled")
    threading.Thread(target=lambda: _convert_worker(st), daemon=True).start()


def _cb_handle_drop(st: _GuiState, data):
    if isinstance(data, str):
        data = [data]
    for f in data:
        f = f.strip('{}').strip('"')
        if os.path.isfile(f):
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                iid = st.tree.insert("", "end", values=(os.path.basename(f), "...", "...", "等待中"))
                st.file_list.append({"path": f, "iid": iid})
                _cb_update_count(st)


def _init_state(root) -> _GuiState:
    """创建 _GuiState 并初始化所有 tkinter 变量。"""
    import tkinter as tk
    st = _GuiState()
    st.root = root
    st.file_list = []
    st.output_dir_var = tk.StringVar(value="")
    st.format_var = tk.StringVar(value="MP3 (320kbps)")
    st.status_var = tk.StringVar(value="就绪 - 选择功能模块开始")
    st.progress_var = tk.DoubleVar(value=0)
    st.is_processing = False
    st.mode_var = tk.StringVar(value="video")
    st.meta_vars = {}
    st.meta_path_var = tk.StringVar(value="")
    st.loud_path_var = tk.StringVar(value="")
    st.smart_path_var = tk.StringVar(value="")
    st.trim_files = []
    st.start_sec_var = tk.StringVar(value="0")
    st.end_sec_var = tk.StringVar(value="")
    return st


def _build_title_bar(root):
    """构建顶部标题栏（含 FFmpeg 状态）。"""
    import tkinter as tk
    from tkinter import ttk
    title_frame = ttk.Frame(root, style="Dark.TFrame")
    title_frame.pack(fill="x", padx=20, pady=(15, 5))
    ttk.Label(title_frame, text="音频工具箱 V2.0", style="Title.TLabel").pack(side="left")
    ffmpeg_status = "FFmpeg: " + ("已就绪" if FFMPEG_PATH else "未找到!")
    tk.Label(title_frame, text=ffmpeg_status, bg="#1a1a2e",
             fg="#00d4aa" if FFMPEG_PATH else "#ff6b6b",
             font=("Microsoft YaHei UI", 9)).pack(side="right")


def _build_bottom_bar(root, st: _GuiState):
    """构建底部状态栏 + 转换按钮。"""
    from tkinter import ttk
    bottom_frame = ttk.Frame(root, style="Dark.TFrame")
    bottom_frame.pack(fill="x", padx=20, pady=(5, 15))
    ttk.Progressbar(bottom_frame, variable=st.progress_var, maximum=100).pack(fill="x")
    ttk.Label(bottom_frame, textvariable=st.status_var, style="Status.TLabel").pack(fill="x", pady=(2, 0))
    st.convert_btn = ttk.Button(bottom_frame, text="开始处理", style="Convert.TButton")
    st.convert_btn.pack(side="left")
    st.convert_btn.config(command=lambda: _cb_start_convert(st))


def run_gui():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("音频工具箱 V2.0")
    root.geometry("800x680")
    root.minsize(720, 600)
    root.configure(bg="#1a1a2e")

    _apply_theme(ttk.Style())
    st = _init_state(root)

    _build_title_bar(root)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=20, pady=10)
    _build_convert_tab(notebook, st)
    _build_meta_tab(notebook, st)
    _build_loud_tab(notebook, st)
    _build_trim_tab(notebook, st)
    _build_smart_tab(notebook, st)

    _build_bottom_bar(root, st)

    try:
        root.drop_target_register("DND_Files")
        root.dnd_bind("<<Drop>>", lambda e: _cb_handle_drop(st, e.data))
    except Exception as _e:
        logger.debug("drag-drop not available: %s", _e)

    root.mainloop()
