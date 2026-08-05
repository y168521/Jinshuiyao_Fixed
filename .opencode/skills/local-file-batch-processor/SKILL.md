---
name: local-file-batch-processor
description: 本地文件批处理技能，覆盖音视频格式转换、文档格式转换、批量重命名、文件分类归档、图片压缩处理。使用场景：批量处理文件、格式转换、文件整理归档、重命名规范化、图片压缩。
---

# 本地文件批处理技能

## 常用工具
- **ffmpeg**：音视频处理瑞士军刀
- **ImageMagick**：图片处理
- **pandoc**：文档格式转换
- **Python脚本**：灵活定制

## 音视频处理（ffmpeg）

### 格式转换
```bash
# MP4 转 MP3
ffmpeg -i input.mp4 -vn -acodec libmp3lame output.mp3

# MKV 转 MP4（无损，直接复制流）
ffmpeg -i input.mkv -c copy output.mp4

# 批量转换
for f in *.mkv; do ffmpeg -i "$f" -c copy "${f%.mkv}.mp4"; done
```

### 压缩
```bash
# 视频压缩（CRF 23，质量和体积平衡）
ffmpeg -i input.mp4 -vcodec libx264 -crf 23 output.mp4

# 音频压缩（128kbps）
ffmpeg -i input.wav -b:a 128k output.mp3
```

### 截取与拼接
```bash
# 截取片段（从00:01:00开始，截取30秒）
ffmpeg -i input.mp4 -ss 00:01:00 -t 00:00:30 -c copy output.mp4

# 拼接多个视频
ffmpeg -f concat -i list.txt -c copy output.mp4
```

## 图片处理

### 格式转换
```bash
# PNG 转 JPG
magick input.png output.jpg

# 批量转换
magick mogrify -format jpg *.png
```

### 压缩与缩放
```bash
# 压缩到指定大小以下
magick input.jpg -resize 50% -quality 80 output.jpg

# 批量压缩
magick mogrify -resize 1920x1080 -quality 75 *.jpg
```

### 批量加水印
```bash
magick input.jpg watermark.png -gravity southeast -geometry +10+10 -composite output.jpg
```

## 文档格式转换（pandoc）

### 常用转换
```bash
# Markdown 转 Word
pandoc input.md -o output.docx

# Markdown 转 PDF
pandoc input.md -o output.pdf --pdf-engine=xelatex -V CJKmainfont="微软雅黑"

# Word 转 Markdown
pandoc input.docx -o output.md
```

## 批量重命名

### Python 脚本模板
```python
import os

folder = r"C:\path\to\folder"
for i, filename in enumerate(os.listdir(folder), 1):
    ext = os.path.splitext(filename)[1]
    new_name = f"file_{i:03d}{ext}"
    os.rename(
        os.path.join(folder, filename),
        os.path.join(folder, new_name)
    )
```

### 常见场景
- 按序号重命名
- 批量加前缀/后缀
- 替换文件名中的特定字符
- 按修改时间排序重命名

## 文件分类归档

### 按类型分类
```python
import os
import shutil

file_types = {
    "图片": [".jpg", ".png", ".gif", ".bmp"],
    "文档": [".doc", ".docx", ".pdf", ".txt", ".md"],
    "视频": [".mp4", ".mkv", ".avi"],
    "音频": [".mp3", ".wav", ".flac"],
    "压缩包": [".zip", ".rar", ".7z"],
}

folder = r"C:\path\to\sort"
for filename in os.listdir(folder):
    ext = os.path.splitext(filename)[1].lower()
    for category, exts in file_types.items():
        if ext in exts:
            target_dir = os.path.join(folder, category)
            os.makedirs(target_dir, exist_ok=True)
            shutil.move(
                os.path.join(folder, filename),
                os.path.join(target_dir, filename)
            )
            break
```

### 按日期分类
- 按修改日期归档
- 按拍摄日期（EXIF信息）分类

## 参考资料

