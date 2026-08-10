#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 3.10依赖包更新助手
用于在金水谣系统升级到Python 3.10后更新依赖包版本

运行方式:
1. 备份后: python update_deps_for_310.py --backup
2. 更新: python update_deps_for_310.py --update
"""

import sys
import json
import subprocess
import argparse
from datetime import datetime
from pathlib import Path


class Python310DependencyUpdater:
    """Python 3.10依赖包更新助手"""
    
    def __init__(self):
        self.current_python = sys.executable
        self.target_python = r"D:\Python310\python.exe"
        self.backup_dir = Path("python_upgrade_backup")
        self.backup_dir.mkdir(exist_ok=True)
        
        # Python 3.10推荐的依赖包版本
        self.recommended_versions_310 = {
            "numpy": "1.26.4",        # Python 3.10兼容，性能优化
            "pandas": "2.2.2",        # Python 3.10兼容，功能完整
            "matplotlib": "3.8.0",     # Python 3.10兼容，稳定版本
            "scipy": "1.13.0",        # Python 3.10兼容
            "requests": "2.32.3",      # 最新稳定版
            "cryptography": "42.0.5",  # Python 3.10兼容，安全
            "akshare": "1.19.62",      # Python 3.10兼容版本
            "customtkinter": "5.2.2",  # 与Python 3.10兼容
            "beautifulsoup4": "4.12.3", # 稳定版本
            "lxml": "5.2.1",           # 稳定版本
            "pillow": "10.3.0",        # Python 3.10兼容
            "scikit-learn": "1.5.0",   # 可选，机器学习
        }
        
        # 需要降级处理的包（如果与Python 3.10不兼容）
        self.downgrade_needed = {
            # 如果有包需要降级，在这里指定
        }
        
        # 可以安全跳过的包（非关键）
        self.skip_packages = {
            "pip", "setuptools", "wheel"
        }
    
    def backup_current_dependencies(self) -> bool:
        """备份当前依赖包"""
        print("🔍 备份当前依赖包状态...")
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"requirements_backup_{timestamp}.txt"
            
            # 导出当前环境的所有包
            result = subprocess.run(
                [self.current_python, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                check=True
            )
            
            packages = result.stdout.strip().split('\n')
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.write(result.stdout)
            
            print(f"✅ 已备份 {len(packages)} 个包到: {backup_file}")
            
            # 创建包版本信息
            pkg_info = {
                "backup_time": timestamp,
                "python_version": sys.version,
                "python_executable": sys.executable,
                "total_packages": len(packages),
                "packages": []
            }
            
            for pkg_line in packages:
                if '==' in pkg_line:
                    name, version = pkg_line.split('==')
                    pkg_info["packages"].append({
                        "name": name.strip(),
                        "version": version.strip()
                    })
            
            info_file = self.backup_dir / f"package_info_{timestamp}.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(pkg_info, f, indent=2, ensure_ascii=False)
            
            print(f"📋 包信息已保存到: {info_file}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 备份失败: {e}")
            print(f"错误输出: {e.stderr}")
            return False
        except Exception as e:
            print(f"❌ 备份过程中出错: {e}")
            return False
    
    def check_python_310_availability(self) -> bool:
        """检查Python 3.10可用性"""
        print("🔍 检查Python 3.10可用性...")
        
        if not Path(self.target_python).exists():
            print(f"❌ Python 3.10未找到: {self.target_python}")
            print(f"💡 请先安装Python 3.10.13到该路径")
            return False
        
        try:
            result = subprocess.run(
                [self.target_python, "--version"],
                capture_output=True,
                text=True,
                check=True
            )
            version_output = result.stdout.strip()
            print(f"✅ 找到Python 3.10: {version_output}")
            
            # 检查版本号
            if "3.10" in version_output:
                print("🎯 Python版本符合要求 (3.10.x)")
                return True
            else:
                print(f"⚠ 警告: 不是Python 3.10版本 ({version_output})")
                return False
                
        except subprocess.CalledProcessError as e:
            print(f"❌ Python 3.10检查失败: {e}")
            return False
    
    def create_python_310_virtualenv(self, env_name: str = "venv_310") -> bool:
        """创建Python 3.10虚拟环境"""
        print(f"🔧 创建Python 3.10虚拟环境 '{env_name}'...")
        
        try:
            # 创建虚拟环境
            result = subprocess.run(
                [self.target_python, "-m", "venv", env_name],
                capture_output=True,
                text=True,
                check=True
            )
            
            print(f"✅ 虚拟环境创建成功: {env_name}")
            
            # 激活脚本提示
            if sys.platform == "win32":
                activate_script = f"{env_name}\\Scripts\\activate"
            else:
                activate_script = f"{env_name}/bin/activate"
            
            print(f"💡 激活命令: {activate_script}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 虚拟环境创建失败: {e}")
            print(f"错误输出: {e.stderr}")
            return False
    
    def generate_compatible_requirements(self, backup_file: Path) -> str:
        """生成兼容Python 3.10的requirements文件"""
        print("🔧 生成Python 3.10兼容的依赖清单...")
        
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                packages = [line.strip() for line in f if line.strip()]
            
            compatible_packages = []
            skipped_packages = []
            updated_packages = []
            
            for package_line in packages:
                if not package_line or package_line.startswith('#'):
                    continue
                
                # 分割包名和版本
                if '==' in package_line:
                    package_name, version = package_line.split('==')
                    package_name = package_name.strip().lower()
                    version = version.strip()
                elif '>=' in package_line:
                    package_name, version = package_line.split('>=')
                    package_name = package_name.strip().lower()
                    version = version.strip()
                else:
                    # 只有包名，没有版本要求
                    package_name = package_line.strip().lower()
                    version = None
                
                # 跳过系统包
                if package_name in self.skip_packages:
                    skipped_packages.append(package_name)
                    continue
                
                # 检查是否有推荐的Python 3.10版本
                if package_name in self.recommended_versions_310:
                    recommended_version = self.recommended_versions_310[package_name]
                    compatible_packages.append(f"{package_name}=={recommended_version}")
                    updated_packages.append(f"{package_name}: {version} → {recommended_version}")
                elif package_name in self.downgrade_needed:
                    required_version = self.downgrade_needed[package_name]
                    compatible_packages.append(f"{package_name}=={required_version}")
                    updated_packages.append(f"{package_name}: {version} → {required_version} (降级)")
                elif version:
                    # 保留原版本，但需要测试兼容性
                    compatible_packages.append(f"{package_name}=={version}")
                else:
                    # 只有包名，没有版本
                    compatible_packages.append(package_name)
            
            # 生成requirements文件内容
            content = f"""# Python 3.10兼容依赖清单
# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 原始备份: {backup_file.name}

# 核心依赖（已检查兼容性）
{chr(10).join(sorted(compatible_packages))}

# 注意：
# 1. 安装前建议先测试关键包兼容性
# 2. 如果遇到兼容性问题，可尝试降级相关包版本
# 3. 建议使用虚拟环境进行安装测试

# 跳过包: {', '.join(skipped_packages) if skipped_packages else '无'}
"""
            
            output_file = self.backup_dir / "requirements_310_compatible.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ 已生成兼容依赖清单: {output_file}")
            print(f"📊 统计:")
            print(f"   兼容包: {len(compatible_packages)}个")
            print(f"   跳过包: {len(skipped_packages)}个")
            print(f"   更新版本: {len(updated_packages)}个")
            
            if updated_packages:
                print("🔄 版本更新:")
                for update in updated_packages:
                    print(f"   - {update}")
            
            return str(output_file)
            
        except Exception as e:
            print(f"❌ 生成兼容依赖清单失败: {e}")
            return ""
    
    def install_compatible_dependencies(self, requirements_file: str, env_path: str = "") -> bool:
        """安装兼容的依赖包"""
        print("🚀 安装Python 3.10兼容依赖包...")
        
        try:
            # 确定使用哪个Python
            if env_path:
                # 使用虚拟环境的Python
                python_cmd = env_path
            else:
                # 使用Python 3.10
                python_cmd = self.target_python
            
            # 升级pip
            print("📦 升级pip...")
            subprocess.run(
                [python_cmd, "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # 安装依赖包
            print("📦 安装依赖包...")
            result = subprocess.run(
                [python_cmd, "-m", "pip", "install", "-r", requirements_file],
                capture_output=True,
                text=True,
                check=True
            )
            
            print(f"✅ 依赖包安装完成")
            
            # 显示已安装的包
            print("📊 验证安装...")
            result = subprocess.run(
                [python_cmd, "-m", "pip", "list"],
                capture_output=True,
                text=True,
                check=True
            )
            
            lines = result.stdout.strip().split('\n')
            package_count = len(lines) - 2  # 减去表头
            print(f"   已安装包数量: {package_count}")
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 安装失败: {e}")
            print(f"错误输出: {e.stderr[:500]}...")  # 只显示前500字符
            return False
        except Exception as e:
            print(f"❌ 安装过程中出错: {e}")
            return False
    
    def verify_critical_packages(self) -> bool:
        """验证关键包兼容性"""
        print("🧪 验证关键包兼容性...")
        
        test_code = """
import sys
print(f"Python版本: {sys.version}")

critical_packages = [
    ("numpy", "1.26.4"),
    ("pandas", "2.2.2"), 
    ("matplotlib", "3.8.0"),
    ("scipy", "1.13.0"),
    ("akshare", "1.19.62"),
    ("cryptography", "42.0.5"),
]

print("关键包导入测试:")
for package_name, min_version in critical_packages:
    try:
        module = __import__(package_name)
        version = getattr(module, '__version__', '未知')
        if version >= min_version:
            print(f"  ✅ {package_name}: {version}")
        else:
            print(f"  ⚠ {package_name}: {version} (需要 {min_version}+)")
    except ImportError as e:
        print(f"  ❌ {package_name}: 导入失败 - {e}")
    except Exception as e:
        print(f"  ❌ {package_name}: 错误 - {e}")

print("\\n金水谣核心功能测试:")
try:
    # 测试基本功能
    import numpy as np
    import pandas as pd
    print(f"  ✅ NumPy版本: {np.__version__}")
    print(f"  ✅ Pandas版本: {pd.__version__}")
    
    # 创建测试数据
    data = np.random.randn(10, 5)
    df = pd.DataFrame(data, columns=[f'col_{i}' for i in range(5)])
    print(f"  ✅ 创建DataFrame: {df.shape}")
    
except Exception as e:
    print(f"  ❌ 功能测试失败: {e}")
"""
        
        try:
            result = subprocess.run(
                [self.target_python, "-c", test_code],
                capture_output=True,
                text=True,
                check=True
            )
            
            print(result.stdout)
            return "❌" not in result.stdout
            
        except Exception as e:
            print(f"❌ 验证失败: {e}")
            return False
    
    def run_backup_mode(self):
        """运行备份模式"""
        print("\n" + "="*80)
        print("💾 Python 3.10升级依赖管理 - 备份模式")
        print("="*80)
        
        success = self.backup_current_dependencies()
        
        if success:
            print("\n📋 下一步建议:")
            print("1. 安装Python 3.10.13 (如果尚未安装)")
            print("2. 运行更新模式: python update_deps_for_310.py --update")
            print("3. 创建虚拟环境进行测试")
        else:
            print("\n⚠ 备份失败，请检查Python环境和权限")
        
        print("="*80)
    
    def run_update_mode(self):
        """运行更新模式"""
        print("\n" + "="*80)
        print("🔄 Python 3.10升级依赖管理 - 更新模式")
        print("="*80)
        
        # 1. 检查Python 3.10
        if not self.check_python_310_availability():
            return
        
        # 2. 查找最新的备份文件
        backup_files = list(self.backup_dir.glob("requirements_backup_*.txt"))
        if not backup_files:
            print("❌ 未找到备份文件，请先运行备份模式")
            print("   运行: python update_deps_for_310.py --backup")
            return
        
        latest_backup = max(backup_files, key=lambda x: x.stat().st_mtime)
        print(f"📁 使用最新备份: {latest_backup.name}")
        
        # 3. 创建虚拟环境（可选）
        create_env = input("\n🤔 是否创建Python 3.10虚拟环境? (y/N): ").lower().strip()
        env_path = ""
        
        if create_env == 'y':
            env_name = input("请输入虚拟环境名称 (默认: venv_310): ").strip() or "venv_310"
            if self.create_python_310_virtualenv(env_name):
                env_path = f"{env_name}/Scripts/python" if sys.platform == "win32" else f"{env_name}/bin/python"
                print(f"📌 虚拟环境Python路径: {env_path}")
        
        # 4. 生成兼容依赖清单
        requirements_file = self.generate_compatible_requirements(latest_backup)
        if not requirements_file:
            return
        
        # 5. 安装依赖
        confirm = input(f"\n🚀 确认安装Python 3.10兼容依赖包? (y/N): ").lower().strip()
        if confirm != 'y':
            print("安装已取消")
            return
        
        success = self.install_compatible_dependencies(requirements_file, env_path)
        
        if success:
            # 6. 验证关键包
            print("\n" + "-"*80)
            verify = input("🧪 是否验证关键包兼容性? (Y/n): ").lower().strip()
            if verify != 'n':
                self.verify_critical_packages()
            
            print("\n✅ 更新完成！")
            print("\n📋 下一步步骤:")
            print("1. 测试金水谣系统核心功能")
            print("2. 运行: python check_python_upgrade.py")
            print("3. 验证杀号引擎、数据加载等关键功能")
            print("4. 如果有问题，查看requirements_310_compatible.txt")
        
        print("="*80)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Python 3.10依赖包更新助手")
    parser.add_argument("--backup", action="store_true", help="备份当前Python环境依赖包")
    parser.add_argument("--update", action="store_true", help="更新到Python 3.10兼容版本")
    parser.add_argument("--verify", action="store_true", help="验证Python 3.10关键包兼容性")
    
    args = parser.parse_args()
    
    updater = Python310DependencyUpdater()
    
    if args.backup:
        updater.run_backup_mode()
    elif args.update:
        updater.run_update_mode()
    elif args.verify:
        if updater.check_python_310_availability():
            updater.verify_critical_packages()
    else:
        # 交互模式
        print("Python 3.10依赖包更新助手")
        print("="*80)
        print("1. 备份当前依赖包 (--backup)")
        print("2. 更新到Python 3.10兼容版本 (--update)")
        print("3. 验证兼容性 (--verify)")
        print("\n例如:")
        print("  备份: python update_deps_for_310.py --backup")
        print("  更新: python update_deps_for_310.py --update")
        print("="*80)


if __name__ == "__main__":
    main()