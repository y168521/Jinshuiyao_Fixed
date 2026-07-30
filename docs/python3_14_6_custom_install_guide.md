# Python 3.14.6 定制化安装配置指南

## 安装程序：python-3.14.6-amd64.exe

### 🔗 下载地址
**Windows 64位安装包：**
```
主链接：https://www.python.org/ftp/python/3.14.6/python-3.14.6-amd64.exe
备用链接：https://www.python.org/downloads/release/python-3146/
文件大小：约35-40MB
SHA256验证：建议从官网验证文件完整性
```

## 🎯 安装选项配置参考表

| 选项 | 功能解释 | 推荐操作 | 详细说明 |
|------|----------|----------|----------|
| **Install Python 3.14 for all users** | 安装后本机所有 Windows 账户都能使用这个 Python；勾选后安装路径会变更到系统盘 Program Files 目录 | ✅ **建议勾选** | 优点：多用户共用、后续权限问题更少<br>缺点：需要管理员权限安装<br>安装路径：`C:\Program Files\Python314` |
| **Associate files with Python** | 把.py后缀文件默认关联用 Python 打开 | ✅ **保持勾选** | 双击.py文件会自动使用Python打开<br>方便脚本直接运行<br>避免每次右键选择打开方式 |
| **Create shortcuts for installed applications** | 在开始菜单生成 Python、IDLE 快捷方式 | ✅ **保持勾选** | 开始菜单中会有：<br>- Python 3.14 (64-bit)<br>- IDLE (Python 3.14 64-bit)<br>- Python Manuals (3.14) |
| **Add Python to environment variables** | 核心关键项，自动写入系统 PATH 环境变量，cmd 直接调用 python 命令，无需手动配置 | ✅ **必须勾选** | 当前已勾选，无需修改<br>确保命令行中可以直接调用 `python`<br>这是最重要的选项 |
| **Precompile standard library** | 预编译标准库 pyc 文件，小幅提升初次运行速度，会占用更多磁盘空间 | ❌ **普通用户不用勾选** | 额外占用约20-30MB磁盘空间<br>首次运行Python脚本时编译pyc文件<br>对于金水谣系统无显著影响 |
| **Download debugging symbols** | 用于 C 语言层面源码调试，普通编程完全用不上 | ❌ **全部取消勾选** | 文件巨大（约200MB+）<br>仅开发Python解释器或C扩展时需要<br>普通Python编程完全不需要 |
| **Download debug binaries** | 调试版本的可执行文件，包含调试信息 | ❌ **全部取消勾选** | 与调试符号类似，不需要<br>会显著增加安装包大小 |
| **Download free-threaded binaries** | 无 GIL 多线程版本 Python，属于实验性功能，常规开发不推荐 | ❌ **取消勾选** | Python 3.14新增的实验性功能<br>可能存在稳定性问题<br>金水谣系统目前不需要 |

## 📁 自定义安装配置（高级选项）

### 点击"Customize installation"

**可选组件选择：**
| 组件 | 推荐 | 说明 |
|------|------|------|
| **Python.exe** | ✅ 必须 | Python解释器主程序 |
| **pip** | ✅ 推荐 | Python包管理器，安装第三方库必需 |
| **Python launcher for Windows** | ✅ 推荐 | 支持多种Python版本并存和切换 |
| **Python test suite** | ⚠️ 可选 | 测试套件，一般用户不需要 |
| **tcl/tk and IDLE** | ✅ 推荐（金水谣系统） | Python自带的GUI开发环境<br>金水谣系统的GUI可能需要Tkinter |
| **Python manual** | ⚠️ 可选 | Python官方文档，可在线查看 |
| **py.exe launcher** | ✅ 推荐 | Python启动器，多版本管理 |

**高级选项（Advanced Options）：**
| 选项 | 推荐 | 说明 |
|------|------|------|
| **Install for all users** | ✅ 推荐 | 同主界面的选项 |
| **Associate files with Python** | ✅ 推荐 | 同主界面的选项 |
| **Create shortcuts** | ✅ 推荐 | 同主界面的选项 |
| **Add Python to environment variables** | ✅ **必须** | 同主界面的选项 |
| **Precompile standard library** | ❌ 不选 | 同主界面的选项 |
| **Download debugging symbols** | ❌ 不选 | 同主界面的选项 |
| **Customize install location** | ✅ 推荐 | 自定义安装目录 |

### 📍 推荐安装目录

根据金水谣系统的原有目录结构：

**方案A（与Python 3.8保持一致）：**
```
D:\Python314\
```
优势：
- 保持原有目录命名规范
- 与Python 3.8并排安装
- 便于版本管理和切换

**方案B（系统标准目录）：**
```
C:\Program Files\Python314\
```
优势：
- 系统标准化管理
- 多用户可用
- 与"Install for all users"选项一致

**推荐：方案A**
```
安装目录：D:\Python314
```

## 🚀 安装步骤详细说明

### 第1步：下载安装包
1. 下载 `python-3.14.6-amd64.exe` 到桌面或Downloads文件夹
2. 验证文件完整性（可选）

### 第2步：运行安装程序
1. 双击安装程序
2. 勾选以下选项：
   - ✅ Install Python 3.14 for all users
   - ✅ Associate files with Python (.py)
   - ✅ Create shortcuts for installed applications
   - ✅ Add Python to environment variables
3. 点击"Customize installation"

### 第3步：自定义安装
1. **可选组件（Select optional features）**：
   - ✅ pip
   - ✅ tcl/tk and IDLE（金水谣GUI需要）
   - ✅ Python launcher for Windows
   - ✅ Python test suite（可选）
2. 点击Next

### 第4步：高级选项
1. **高级选项（Advanced Options）**：
   - ✅ Install for all users（已勾选）
   - ✅ Associate files with Python（已勾选）
   - ✅ Create shortcuts（已勾选）
   - ✅ Add Python to environment variables（已勾选）
   - ❌ Precompile standard library（**取消勾选**）
   - ❌ Download debug binaries（**取消勾选**）
2. **安装位置（Customize install location）**：
   ```
   输入：D:\Python314
   ```
3. 点击Install

### 第5步：等待安装完成
1. 安装过程约2-5分钟
2. 看到"Setup was successful"表示安装成功
3. 可点击"Disable path length limit"选项（如果显示）

## ✅ 安装后验证

### 基础验证
```powershell
# 验证版本
python --version
# 期待输出：Python 3.14.6

# 验证路径
where python
# 期待输出包含：D:\Python314\python.exe

# 验证pip
pip --version
# 期待输出：pip 25.x.x ...
```

### 金水谣系统特别验证
```powershell
# 验证Python 3.14基础功能
python -c "import sys; print(f'版本：{sys.version}'); print(f'安装路径：{sys.executable}'); print(f'架构：{sys.platform}')"

# 验证关键模块
python -c "
# 测试基础模块导入
modules = ['numpy', 'pandas', 'cryptography', 'json', 'os', 'sys']
for module in modules:
    try:
        __import__(module)
        print(f'✅ {module}: 导入成功')
    except ImportError:
        print(f'⚠️  {module}: 未安装')
"
```

## 🔧 配置环境变量（手动检查）

### 自动配置（推荐）
安装程序已自动配置PATH，但建议验证：

```powershell
# 检查PATH变量
echo %PATH% | findstr "Python314"
# 应该看到包含 D:\Python314\ 和 D:\Python314\Scripts\

# 或者在PowerShell中
$env:PATH -split ';' | Select-String "Python314"
```

### 手动配置（如果需要）
如果PATH未正确配置，手动添加：
1. 系统属性 → 高级 → 环境变量
2. 系统变量的PATH中添加：
   ```
   D:\Python314\
   D:\Python314\Scripts\
   ```

## 🐍 Python启动器配置（多版本管理）

### 如果已有多个Python版本
```powershell
# 查看所有Python版本
py --list
# 显示类似：
# -V:3.14 *    Python 3.14 (64-bit)
# -V:3.8       Python 3.8 (64-bit)

# 使用特定版本
py -3.14 script.py    # 使用Python 3.14
py -3.8 script.py     # 使用Python 3.8
```

### 设置默认版本
```powershell
# 设置Python 3.14为默认
py -3.14 -m venv venv_default

# 验证默认版本
py --version
# 应该显示：Python 3.14.6
```

## 📁 金水谣系统配置建议

### 1. 虚拟环境管理
```powershell
# 创建金水谣Python 3.14虚拟环境
D:\Python314\python.exe -m venv venv_314
# 激活
venv_314\Scripts\activate
# 安装金水谣依赖
pip install numpy pandas matplotlib akshare cryptography
```

### 2. 项目目录结构建议
```
D:\
├── python38\          # 原有Python 3.8.10
├── Python314\         # 新安装Python 3.14.6
├── Nutstore\
│   └── 1\
│       └── 我的坚果云\
│           └── 模型\
│               └── Jinshuiyao_Fixed\
│                   ├── venv_314\          # Python 3.14虚拟环境
│                   ├── docs\
│                   ├── engines\
│                   ├── utils\
│                   └── tools\
```

### 3. 启动脚本配置
创建 `start_jinshuiyao.bat`：
```batch
@echo off
echo 启动金水谣模型系统 (Python 3.14.6)
echo ========================================

REM 激活Python 3.14虚拟环境
call venv_314\Scripts\activate

REM 验证Python版本
python --version

REM 启动金水谣系统
python main.py

pause
```

## 🔍 常见问题排查

### 问题1：`'python' is not recognized`
**原因**：PATH环境变量未配置
**解决**：
```powershell
# 方法A：使用完整路径
D:\Python314\python.exe --version

# 方法B：使用Python启动器
py --version

# 方法C：手动添加PATH（见上文）
```

### 问题2：安装程序权限不足
**原因**：需要管理员权限
**解决**：
1. 右键点击安装程序 → "以管理员身份运行"
2. 或先运行管理员权限的PowerShell/CMD

### 问题3：与其他Python版本冲突
**解决**：
1. 使用Python启动器 `py` 指定版本
2. 使用完整路径调用
3. 调整PATH变量顺序

### 问题4：依赖包安装失败
**原因**：Python 3.14新版本兼容性问题
**解决**：
```powershell
# 尝试升级pip
python -m pip install --upgrade pip

# 尝试新版本或兼容版本
pip install numpy==1.26.4
pip install pandas==2.2.2
pip install akshare==1.19.62

# 如果仍有问题，降级到Python 3.13.12
```

## 📞 技术支持

### 金水谣系统升级支持
如果您在升级到Python 3.14.6后遇到金水谣系统兼容性问题：

1. **测试兼容性**：
   ```powershell
   python tools\jinshuiyao_python310_validator.py
   ```

2. **查看升级指南**：
   ```
   docs\python_3_10_upgrade_guide.md
   ```

3. **回滚到Python 3.13.12**：
   ```
   下载：https://www.python.org/ftp/python/3.13.12/python-3.13.12-amd64.exe
   ```

4. **临时切换回Python 3.8.10**：
   ```batch
   D:\python38\python.exe main.py
   ```

## 🎉 安装完成确认清单

- [ ] 下载了 `python-3.14.6-amd64.exe`
- [ ] 按照推荐选项配置安装
- [ ] 安装到 `D:\Python314` 目录
- [ ] 验证 `python --version` 返回 `Python 3.14.6`
- [ ] 验证 `pip --version` 正常
- [ ] 验证PATH包含Python目录
- [ ] 创建了金水谣系统虚拟环境 `venv_314`
- [ ] 测试了关键模块导入
- [ ] 创建了启动脚本 `start_jinshuiyao.bat`

祝您安装顺利！如果遇到任何问题，随时可以咨询。 🚀