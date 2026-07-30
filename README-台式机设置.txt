台式机设置步骤（交给 WorkBuddy）：

1. 打开 Git Bash，运行：
   cd /c/Users/Administrator/Nutstore/1/我的坚果云/模型/Jinshuiyao_Fixed
   git pull

2. 在代码文件夹找到「同步代码.bat」，双击测试能否正常运行

3. 设置定时自动同步（每小时执行）：
   以管理员身份打开 PowerShell，粘贴运行：

   $batPath = "$env:USERPROFILE\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\同步代码.bat"
   schtasks /Create /SC HOURLY /TN "Jinshuiyao自动同步" /TR "`"$batPath`"" /IT /F

4. 以后两台电脑都无需任何操作，每小时自动同步
