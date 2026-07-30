# Python 3.10.13 安装指南

## 1. 准备工作
1. 备份当前项目和数据
2. 下载Python安装程序
3. 准备依赖包列表

## 2. 下载链接
- Windows 64位安装程序: https://www.python.org/ftp/python/3.10.13/python-3.10.13-amd64.exe
- 官方下载页: https://www.python.org/downloads/release/python-31013/

## 3. 安装步骤
1. 运行安装程序 `python-3.10.13-amd64.exe`
2. 勾选以下选项:
   - ✅ Install for all users
   - ✅ Add Python to PATH
   - ✅ 建议安装到: D:\Python310
3. 点击安装
4. 验证安装: 打开CMD/PowerShell运行 `python --version`

## 4. 依赖迁移
下载当前依赖清单并重新安装:
```powershell
# 1. 导出依赖包列表
D:\python38\python.exe -m pip freeze > requirements-backup.txt

# 2. 安装Python 3.10
# 3. 为Python 3.10重新安装
D:\Python310\python.exe -m pip install -r requirements-backup.txt
```

## 5. 验证测试
使用验证脚本测试兼容性:
```powershell
D:\Python310\python.exe C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\tools\python_upgrade_assistant.py --test
```

## 6. 注意事项
- 金水谣项目可能需要调整`#! python`指向
- 检查虚拟环境是否使用正确版本
- 验证第三方库功能正常

