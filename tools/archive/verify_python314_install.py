#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 3.14.6 安装验证脚本
运行: python verify_python314_install.py
检查Python 3.14.6是否正确安装和配置
"""

import sys
import os
import platform
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime


class Python314InstallationVerifier:
    """Python 3.14.6安装验证器"""
    
    def __init__(self):
        self.expected_version = "3.14.6"
        self.expected_path = r"D:\Python314"
        self.verification_results = {
            "timestamp": datetime.now().isoformat(),
            "expected_version": self.expected_version,
            "expected_path": self.expected_path,
            "system_info": {},
            "installation_checks": {},
            "configuration_checks": {},
            "jinshuiyao_compatibility": {},
            "recommendations": []
        }
    
    def check_system_info(self):
        """检查系统信息"""
        print("\n" + "="*80)
        print("🔍 系统信息检查")
        print("="*80)
        
        system_info = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0],
            "python_version": sys.version,
            "python_executable": sys.executable,
            "current_working_dir": os.getcwd()
        }
        
        self.verification_results["system_info"] = system_info
        
        print(f"🐍 当前Python版本: {sys.version.split()[0]}")
        print(f"📁 当前Python路径: {sys.executable}")
        print(f"💻 操作系统: {system_info['platform']} {system_info['platform_version']}")
        print(f"⚙️  系统架构: {system_info['architecture']}")
        
        return system_info
    
    def check_python_version(self):
        """检查Python版本"""
        print("\n📊 Python版本检查:")
        
        current_version = sys.version.split()[0]
        is_correct_version = current_version == self.expected_version
        
        check_result = {
            "current_version": current_version,
            "expected_version": self.expected_version,
            "is_correct": is_correct_version,
            "status": "✅ 正确" if is_correct_version else f"❌ 错误 (期望: {self.expected_version})"
        }
        
        self.verification_results["installation_checks"]["version_check"] = check_result
        
        print(f"  当前版本: {current_version}")
        print(f"  期望版本: {self.expected_version}")
        print(f"  结果: {check_result['status']}")
        
        return is_correct_version
    
    def check_installation_path(self):
        """检查安装路径"""
        print("\n📁 安装路径检查:")
        
        python_exe_path = sys.executable
        expected_exe_path = os.path.join(self.expected_path, "python.exe")
        
        is_correct_path = python_exe_path.lower() == expected_exe_path.lower()
        
        check_result = {
            "actual_path": python_exe_path,
            "expected_path": expected_exe_path,
            "is_correct": is_correct_path,
            "status": "✅ 正确" if is_correct_path else "❌ 路径不符"
        }
        
        self.verification_results["installation_checks"]["path_check"] = check_result
        
        print(f"  实际路径: {python_exe_path}")
        print(f"  期望路径: {expected_exe_path}")
        print(f"  结果: {check_result['status']}")
        
        # 检查目录是否存在
        install_dir = os.path.dirname(python_exe_path)
        dir_exists = os.path.exists(install_dir)
        print(f"  安装目录存在: {'✅ 是' if dir_exists else '❌ 否'}")
        
        return is_correct_path
    
    def check_environment_path(self):
        """检查环境变量PATH"""
        print("\n🔧 环境变量PATH检查:")
        
        path_var = os.environ.get('PATH', '')
        paths = path_var.split(';')
        
        python_paths_found = []
        for path in paths:
            if path.strip() and "python" in path.lower():
                python_paths_found.append(path)
        
        # 检查是否包含期望的Python路径
        has_expected_path = False
        expected_paths = [
            self.expected_path,
            os.path.join(self.expected_path, "Scripts")
        ]
        
        for expected in expected_paths:
            for path in paths:
                if path.strip() and expected.lower() in path.lower():
                    has_expected_path = True
                    break
        
        check_result = {
            "path_variable": path_var,
            "python_paths_found": python_paths_found,
            "has_expected_path": has_expected_path,
            "status": "✅ 正确配置" if has_expected_path else "⚠️  可能需要手动配置"
        }
        
        self.verification_results["configuration_checks"]["path_variable_check"] = check_result
        
        print(f"  PATH包含Python路径: {'✅ 是' if python_paths_found else '❌ 否'}")
        if python_paths_found:
            print(f"  找到的Python路径:")
            for path in python_paths_found[:5]:  # 只显示前5个
                print(f"    - {path}")
        
        print(f"  包含期望路径 {self.expected_path}: {'✅ 是' if has_expected_path else '❌ 否'}")
        
        return has_expected_path
    
    def check_pip_installation(self):
        """检查pip安装"""
        print("\n📦 pip包管理器检查:")
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                check=True
            )
            
            pip_version = result.stdout.strip()
            is_pip_working = True
            
        except (subprocess.CalledProcessError, FileNotFoundError):
            pip_version = "未找到或不可用"
            is_pip_working = False
        
        check_result = {
            "pip_version": pip_version,
            "is_working": is_pip_working,
            "status": "✅ 正常" if is_pip_working else "❌ 不可用"
        }
        
        self.verification_results["installation_checks"]["pip_check"] = check_result
        
        print(f"  pip版本: {pip_version}")
        print(f"  pip状态: {check_result['status']}")
        
        return is_pip_working
    
    def check_optional_components(self):
        """检查可选组件"""
        print("\n🔧 可选组件检查:")
        
        components_to_check = {
            "tkinter": "Tkinter GUI支持",
            "idlelib": "IDLE开发环境",
            "venv": "虚拟环境模块",
            "ensurepip": "确保pip安装"
        }
        
        components_status = {}
        
        for module_name, description in components_to_check.items():
            try:
                __import__(module_name)
                components_status[module_name] = {
                    "name": description,
                    "installed": True,
                    "status": "✅ 已安装"
                }
            except ImportError:
                components_status[module_name] = {
                    "name": description,
                    "installed": False,
                    "status": "❌ 未安装"
                }
        
        self.verification_results["installation_checks"]["components_check"] = components_status
        
        for component_name, info in components_status.items():
            print(f"  {info['name']}: {info['status']}")
        
        # 特别检查tcl/tk（金水谣GUI需要）
        try:
            import tkinter
            tk_version = tkinter.TkVersion
            tk_available = True
            print(f"  Tkinter版本: {tk_version}")
        except ImportError:
            tk_available = False
            print(f"  Tkinter: ❌ 不可用（金水谣GUI可能需要）")
            self.verification_results["recommendations"].append("Tkinter未安装，金水谣系统GUI可能需要此组件")
        
        return components_status
    
    def check_installation_options(self):
        """检查安装选项配置"""
        print("\n⚙️  安装选项验证:")
        
        # 检查是否安装了调试符号（不应该安装）
        debug_symbols_dir = os.path.join(self.expected_path, "debug")
        has_debug_symbols = os.path.exists(debug_symbols_dir)
        
        # 检查是否预编译了标准库
        pycache_dirs = []
        lib_dir = os.path.join(self.expected_path, "Lib")
        if os.path.exists(lib_dir):
            for root, dirs, files in os.walk(lib_dir):
                if "__pycache__" in dirs:
                    pycache_dirs.append(os.path.relpath(root, lib_dir))
        
        has_precompiled = len(pycache_dirs) > 0
        
        options_status = {
            "debug_symbols": {
                "installed": has_debug_symbols,
                "expected": False,
                "status": "❌ 不应安装" if has_debug_symbols else "✅ 正确（未安装）",
                "description": "调试符号文件"
            },
            "precompiled_library": {
                "installed": has_precompiled,
                "expected": False,
                "status": "❌ 预编译库" if has_precompiled else "✅ 正确（未预编译）",
                "description": "预编译标准库"
            }
        }
        
        self.verification_results["configuration_checks"]["options_check"] = options_status
        
        print(f"  调试符号: {options_status['debug_symbols']['status']}")
        print(f"  预编译库: {options_status['precompiled_library']['status']}")
        
        if has_debug_symbols:
            self.verification_results["recommendations"].append("检测到调试符号，安装时可以取消'Download debugging symbols'选项")
        
        if has_precompiled:
            self.verification_results["recommendations"].append("检测到预编译库，安装时可以取消'Precompile standard library'选项")
        
        return options_status
    
    def check_jinshuiyao_compatibility(self):
        """检查金水谣系统兼容性"""
        print("\n🤖 金水谣系统兼容性检查:")
        
        compatibility_tests = {}
        
        # 检查关键模块导入
        critical_modules = [
            ("numpy", "数值计算"), 
            ("pandas", "数据分析"),
            ("cryptography", "加密库"),
            ("requests", "HTTP请求"),
            ("json", "JSON处理"),
            ("os", "系统操作"),
            ("sys", "系统信息"),
            ("datetime", "日期时间"),
            ("math", "数学函数")
        ]
        
        for module_name, description in critical_modules:
            try:
                __import__(module_name)
                compatibility_tests[module_name] = {
                    "description": description,
                    "compatible": True,
                    "status": "✅ 兼容"
                }
            except ImportError as e:
                compatibility_tests[module_name] = {
                    "description": description,
                    "compatible": False,
                    "status": "⚠️  未安装",
                    "error": str(e)
                }
        
        self.verification_results["jinshuiyao_compatibility"]["module_check"] = compatibility_tests
        
        for module_name, info in compatibility_tests.items():
            print(f"  {info['description']} ({module_name}): {info['status']}")
        
        # Python 3.14新特性测试
        print("\n🚀 Python 3.14新特性测试:")
        
        new_features = {
            "match_statement": "结构模式匹配 (match/case)",
            "union_types": "类型联合运算符 (|)",
            "parenthesized_context_managers": "带括号的上下文管理器",
            "better_error_messages": "改进的错误信息"
        }
        
        feature_results = {}
        
        # 测试match语句（Python 3.10+）
        try:
            code = """
def test_match(value):
    match value:
        case 1:
            return "one"
        case 2:
            return "two"
        case _:
            return "other"
"""
            exec(code, {"__name__": "__main__"})
            feature_results["match_statement"] = {"supported": True, "status": "✅ 支持"}
        except SyntaxError:
            feature_results["match_statement"] = {"supported": False, "status": "❌ 不支持"}
        
        # 测试联合类型运算符（Python 3.10+）
        try:
            code = """
from typing import Union
def test_union(value: int | str) -> int | str:
    return value
"""
            exec(code, {"__name__": "__main__"})
            feature_results["union_types"] = {"supported": True, "status": "✅ 支持"}
        except SyntaxError:
            feature_results["union_types"] = {"supported": False, "status": "❌ 不支持"}
        
        for feature_name, info in feature_results.items():
            print(f"  {new_features[feature_name]}: {info['status']}")
        
        self.verification_results["jinshuiyao_compatibility"]["python314_features"] = feature_results
        
        return compatibility_tests
    
    def check_command_line_tools(self):
        """检查命令行工具"""
        print("\n🖥️  命令行工具检查:")
        
        tools_to_check = [
            ("python", "Python解释器"),
            ("pip", "包管理器"),
            ("py", "Python启动器"),
            ("idle", "IDLE编辑器")
        ]
        
        tool_status = {}
        
        for tool_name, description in tools_to_check:
            try:
                if tool_name == "python":
                    # python命令已在其他地方检查
                    tool_status[tool_name] = {"available": True, "status": "✅ 可用"}
                elif tool_name == "py":
                    result = subprocess.run(["py", "--help"], capture_output=True, text=True)
                    tool_status[tool_name] = {"available": result.returncode == 0, "status": "✅ 可用" if result.returncode == 0 else "❌ 不可用"}
                else:
                    result = subprocess.run([tool_name, "--version"], capture_output=True, text=True)
                    tool_status[tool_name] = {"available": result.returncode == 0, "status": "✅ 可用" if result.returncode == 0 else "❌ 不可用"}
            except (FileNotFoundError, subprocess.CalledProcessError):
                tool_status[tool_name] = {"available": False, "status": "❌ 不可用"}
            
            print(f"  {description} ({tool_name}): {tool_status[tool_name]['status']}")
        
        self.verification_results["configuration_checks"]["command_line_tools"] = tool_status
        
        return tool_status
    
    def generate_verification_report(self):
        """生成验证报告"""
        print("\n" + "="*80)
        print("📋 安装验证报告")
        print("="*80)
        
        # 汇总检查结果
        all_checks_passed = True
        issues_count = 0
        
        # 检查主要项目
        checks = [
            ("Python版本", self.verification_results["installation_checks"]["version_check"]["is_correct"]),
            ("安装路径", self.verification_results["installation_checks"]["path_check"]["is_correct"]),
            ("PATH环境变量", self.verification_results["configuration_checks"]["path_variable_check"]["has_expected_path"]),
            ("pip包管理器", self.verification_results["installation_checks"]["pip_check"]["is_working"])
        ]
        
        print("\n✅ 检查结果汇总:")
        for check_name, check_result in checks:
            status = "✅ 通过" if check_result else "❌ 失败"
            print(f"  {check_name}: {status}")
            if not check_result:
                all_checks_passed = False
                issues_count += 1
        
        # 显示诊断信息
        if not all_checks_passed:
            print(f"\n⚠️  发现 {issues_count} 个问题，需要关注:")
            
            if not self.verification_results["installation_checks"]["version_check"]["is_correct"]:
                print(f"  - Python版本不正确，当前: {sys.version.split()[0]}")
            
            if not self.verification_results["installation_checks"]["path_check"]["is_correct"]:
                print(f"  - 安装路径不正确")
                print(f"    当前路径: {sys.executable}")
                print(f"    期望路径: {self.expected_path}\\python.exe")
            
            if not self.verification_results["configuration_checks"]["path_variable_check"]["has_expected_path"]:
                print(f"  - PATH环境变量未包含Python目录")
                print(f"    需要添加: {self.expected_path} 和 {self.expected_path}\\Scripts")
            
            if not self.verification_results["installation_checks"]["pip_check"]["is_working"]:
                print(f"  - pip不可用，需要重新安装或修复")
        else:
            print("\n🎉 所有主要检查项通过！")
        
        # 显示建议
        if self.verification_results["recommendations"]:
            print("\n💡 建议:")
            for i, recommendation in enumerate(self.verification_results["recommendations"], 1):
                print(f"  {i}. {recommendation}")
        
        # 生成报告文件
        report_file = "python_314_installation_verification_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(self.verification_results, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 详细验证报告已保存: {report_file}")
        
        # 最终总结
        print("\n" + "="*80)
        if all_checks_passed:
            print("✨ Python 3.14.6 安装验证成功！")
            print("🎯 下一步: 创建虚拟环境并安装金水谣系统依赖包")
        else:
            print("🔧 安装验证发现问题，请根据建议进行修复")
            print("💡 您可以:")
            print("  1. 重新运行安装程序")
            print("  2. 手动配置环境变量")
            print("  3. 运行修复脚本")
        print("="*80)
        
        return all_checks_passed
    
    def generate_fix_script(self):
        """生成修复脚本"""
        fix_script_content = f"""@echo off
REM Python 3.14.6 安装修复脚本
REM 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

echo Python 3.14.6 安装修复工具
echo ========================================
echo 检测到的Python路径: {sys.executable}
echo ========================================

REM 1. 检查Python版本
echo 1. 检查Python版本...
python --version
echo.

REM 2. 检查环境变量
echo 2. 检查PATH环境变量...
echo %PATH% | findstr "Python314"
echo.

REM 3. pip修复（如果可用）
echo 3. 尝试修复pip...
python -m ensurepip --upgrade 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ pip修复失败
) else (
    echo ✅ pip修复成功
)
echo.

REM 4. 测试关键功能
echo 4. 测试Python关键功能...
python -c "import sys; print(f'Python版本: {{sys.version}}'); print(f'安装路径: {{sys.executable}}')"
echo.

REM 5. 下一步建议
echo 5. 下一步建议:
echo   - 如果PATH未配置，手动添加以下路径到系统环境变量:
echo       1. {self.expected_path}
echo       2. {self.expected_path}\\Scripts
echo   - 或者重新运行安装程序并确保勾选"Add Python to environment variables"
echo   - 创建虚拟环境: python -m venv venv_314
echo.
echo ========================================
echo 修复完成！请运行python --version验证
echo ========================================
pause
"""
        
        fix_script_file = "fix_python314_installation.bat"
        with open(fix_script_file, 'w', encoding='utf-8') as f:
            f.write(fix_script_content)
        
        print(f"🔧 已生成修复脚本: {fix_script_file}")
        print(f"   运行: {fix_script_file}")
        
        return fix_script_file
    
    def run_full_verification(self):
        """运行完整验证流程"""
        print("🐍 Python 3.14.6 安装验证工具")
        print("版本: 1.0 | 日期: 2026-07-18")
        
        try:
            # 执行各项检查
            self.check_system_info()
            self.check_python_version()
            self.check_installation_path()
            self.check_environment_path()
            self.check_pip_installation()
            self.check_optional_components()
            self.check_installation_options()
            self.check_jinshuiyao_compatibility()
            self.check_command_line_tools()
            
            # 生成报告
            all_passed = self.generate_verification_report()
            
            # 生成修复脚本（如果有问题）
            if not all_passed:
                self.generate_fix_script()
            
            # 提供下一步建议
            print("\n📋 下一步行动:")
            if all_passed:
                print("✅ 安装验证通过，可以开始使用Python 3.14.6")
                print("💡 建议操作:")
                print("  1. 创建金水谣系统虚拟环境:")
                print(f"     {sys.executable} -m venv venv_314")
                print("  2. 安装金水谣系统依赖:")
                print("     pip install numpy pandas matplotlib akshare cryptography")
                print("  3. 测试金水谣系统:")
                print("     python tools\\jinshuiyao_python310_validator.py")
            else:
                print("🔧 需要修复安装问题")
                print("💡 建议操作:")
                print("  1. 运行生成的修复脚本: fix_python314_installation.bat")
                print("  2. 重新检查安装选项配置")
                print("  3. 如果问题持续，重新安装Python 3.14.6")
            
            return all_passed
            
        except Exception as e:
            print(f"❌ 验证过程中出错: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """主函数"""
    verifier = Python314InstallationVerifier()
    success = verifier.run_full_verification()
    
    # 根据验证结果返回退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()