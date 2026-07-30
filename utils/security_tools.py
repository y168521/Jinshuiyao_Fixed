#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣系统 - 敏感数据安全存储与加密系统

作用：
1. 加密存储API密钥等敏感数据
2. 替代明文txt存储方案
3. 提供安全的密钥读取接口
4. 建立敏感数据审计追踪

功能特点：
- AES-GCM强加密
- 环境变量集成
- 密钥轮换机制
- 访问日志记录
- 异常访问检测
"""

import os
import json
import base64
import hashlib
import logging
import getpass
from datetime import datetime
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding, hashes
import hmac
import random
import string

logger = logging.getLogger("jinshuiyao.security")


class SensitiveDataEncryption:
    """敏感数据AES-GCM加密系统"""
    
    def __init__(self, master_key=None):
        # 优先使用传入的master key，否则从环境变量获取
        if master_key:
            self.master_key = master_key
        else:
            self.master_key = os.environ.get("TIANSHU_MASTER_KEY")
            
        if not self.master_key:
            raise ValueError("未设置主密钥，请设置环境变量 TIANSHU_MASTER_KEY")
        
        # 派生加密密钥
        self.encryption_key = self._derive_key(self.master_key, "encryption_salt")
    
    def _derive_key(self, master_key, salt_str):
        """派生出固定大小的密钥"""
        salt = salt_str.encode('utf-8')
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # AES-256需要32字节
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        return kdf.derive(master_key.encode('utf-8'))
    
    def encrypt_data(self, plaintext):
        """加密数据"""
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')
        
        # 生成随机IV
        iv = os.urandom(12)  # GCM推荐使用12字节IV
        
        # 创建加密器
        cipher = Cipher(
            algorithms.AES(self.encryption_key),
            modes.GCM(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        
        # 加密数据
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        
        # 获取认证标签
        tag = encryptor.tag
        
        # 组合IV + 标签 + 密文
        result = iv + tag + ciphertext
        
        # Base64编码便于存储
        return base64.b64encode(result).decode('utf-8')
    
    def decrypt_data(self, encrypted_data):
        """解密数据"""
        try:
            # Base64解码
            data = base64.b64decode(encrypted_data)
            
            # 分离组件
            iv = data[:12]
            tag = data[12:28]  # GCM标签16字节
            ciphertext = data[28:]
            
            # 创建解密器
            cipher = Cipher(
                algorithms.AES(self.encryption_key),
                modes.GCM(iv, tag),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            
            # 解密
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            logger.error(f"解密失败: {e}")
            raise ValueError(f"解密错误: {e}")
    
    def encrypt_and_store(self, data_dict, output_path):
        """加密并存储数据"""
        try:
            # 转换字典为JSON字符串
            if isinstance(data_dict, dict):
                json_str = json.dumps(data_dict, ensure_ascii=False, indent=2)
            else:
                json_str = str(data_dict)
            
            # 加密
            encrypted = self.encrypt_data(json_str)
            
            # 存储
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(encrypted)
            
            logger.info(f"敏感数据已加密存储到: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"加密存储失败: {e}")
            return False


class KeyManager:
    """密钥管理器：集中管理所有API密钥"""
    
    def __init__(self, encryption_system=None):
        self.encryption = encryption_system or SensitiveDataEncryption()
        self.keys = {}
        self.access_log = []
        self.key_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "金水谣数据", "secure", "encrypted_keys.dat"
        )
        self._load_keys()
    
    def _load_keys(self):
        """加载已存储的密钥"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
            
            if os.path.exists(self.key_file):
                with open(self.key_file, 'r', encoding='utf-8') as f:
                    encrypted_data = f.read()
                
                if encrypted_data:
                    decrypted = self.encryption.decrypt_data(encrypted_data)
                    self.keys = json.loads(decrypted)
                    logger.info(f"已加载 {len(self.keys)} 个密钥")
                
            else:
                logger.info("密钥文件不存在，将创建新文件")
                self.keys = {}
                
        except Exception as e:
            logger.warning(f"加载密钥失败: {e}")
            self.keys = {}
    
    def _save_keys(self):
        """保存密钥"""
        try:
            encrypted = self.encryption.encrypt_data(json.dumps(self.keys))
            os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
            
            with open(self.key_file, 'w', encoding='utf-8') as f:
                f.write(encrypted)
            
            logger.debug("密钥已保存")
            return True
            
        except Exception as e:
            logger.error(f"保存密钥失败: {e}")
            return False
    
    def _log_access(self, key_name, action, success=True):
        """记录访问日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "key_name": key_name,
            "action": action,
            "success": success,
            "user": getpass.getuser(),
            "pid": os.getpid()
        }
        self.access_log.append(log_entry)
        
        # 限制日志大小
        if len(self.access_log) > 1000:
            self.access_log = self.access_log[-500:]
        
        # 记录到文件（不加密的访问日志）
        log_dir = os.path.join(
            os.path.dirname(self.key_file), "access_logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"access_{datetime.now().strftime('%Y%m')}.log")
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        if not success:
            logger.warning(f"异常密钥访问: {key_name}, 动作: {action}")
    
    def store_key(self, key_name, key_value, description="", tags=None):
        """存储密钥"""
        try:
            self.keys[key_name] = {
                "value": key_value,
                "description": description,
                "created_at": datetime.now().isoformat(),
                "last_accessed": None,
                "access_count": 0,
                "tags": tags or []
            }
            
            success = self._save_keys()
            if success:
                self._log_access(key_name, "store", True)
                logger.info(f"密钥 '{key_name}' 已存储")
            else:
                self._log_access(key_name, "store", False)
                
            return success
            
        except Exception as e:
            logger.error(f"存储密钥失败: {key_name}, 错误: {e}")
            self._log_access(key_name, "store", False)
            return False
    
    def get_key(self, key_name):
        """获取密钥（核心功能）"""
        try:
            if key_name not in self.keys:
                logger.warning(f"密钥不存在: {key_name}")
                self._log_access(key_name, "get", False)
                return None
            
            key_info = self.keys[key_name]
            
            # 更新访问信息
            key_info["last_accessed"] = datetime.now().isoformat()
            key_info["access_count"] = key_info.get("access_count", 0) + 1
            
            # 保存更新
            self._save_keys()
            
            # 记录成功访问
            self._log_access(key_name, "get", True)
            
            # 返回密钥值
            return key_info["value"]
            
        except Exception as e:
            logger.error(f"获取密钥失败: {key_name}, 错误: {e}")
            self._log_access(key_name, "get", False)
            return None
    
    def delete_key(self, key_name, require_confirm=True):
        """删除密钥"""
        try:
            if key_name not in self.keys:
                logger.warning(f"尝试删除不存在的密钥: {key_name}")
                return False
            
            if require_confirm:
                print(f"⚠️  警告: 即将永久删除密钥 '{key_name}'")
                confirmation = input("输入 'DELETE' 确认删除: ")
                if confirmation != "DELETE":
                    print("取消删除")
                    return False
            
            del self.keys[key_name]
            success = self._save_keys()
            
            if success:
                self._log_access(key_name, "delete", True)
                logger.info(f"密钥 '{key_name}' 已删除")
            else:
                self._log_access(key_name, "delete", False)
                
            return success
            
        except Exception as e:
            logger.error(f"删除密钥失败: {key_name}, 错误: {e}")
            self._log_access(key_name, "delete", False)
            return False
    
    def list_keys(self, show_values=False):
        """列出所有密钥"""
        try:
            if not self.keys:
                print("📭 无存储的密钥")
                return []
            
            print(f"🔑 已存储的密钥 ({len(self.keys)} 个):")
            print("-" * 60)
            
            result = []
            for idx, (key_name, key_info) in enumerate(self.keys.items(), 1):
                created = key_info.get("created_at", "未知时间")
                last_access = key_info.get("last_accessed", "从未访问")
                access_count = key_info.get("access_count", 0)
                desc = key_info.get("description", "")
                
                print(f"{idx}. {key_name}")
                print(f"   描述: {desc}")
                print(f"   创建时间: {created}")
                print(f"   最后访问: {last_access}")
                print(f"   访问次数: {access_count}")
                
                if show_values:
                    value = key_info.get("value", "")
                    masked = self._mask_key(value)
                    print(f"   密钥值: {masked}")
                
                if key_info.get("tags"):
                    print(f"   标签: {', '.join(key_info['tags'])}")
                
                print()
                result.append({
                    "name": key_name,
                    "description": desc,
                    "created_at": created,
                    "access_count": access_count
                })
            
            return result
            
        except Exception as e:
            logger.error(f"列出密钥失败: {e}")
            return []
    
    def _mask_key(self, key_value, visible_chars=4):
        """掩码显示密钥（只显示部分字符）"""
        if not key_value:
            return ""
        
        # 只显示开头和结尾少量字符
        if len(key_value) <= visible_chars * 2:
            return key_value
            
        start = key_value[:visible_chars]
        end = key_value[-visible_chars:]
        middle_len = len(key_value) - visible_chars * 2
        
        return f"{start}{'*' * middle_len}{end}"
    
    def migrate_plaintext_files(self, file_patterns=None):
        """迁移明文密钥文件到加密存储"""
        if file_patterns is None:
            file_patterns = ["*key*.txt", "*secret*.txt", "*token*.txt"]
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        migrated = []
        failed = []
        
        import glob
        for pattern in file_patterns:
            search_path = os.path.join(base_dir, "**", pattern)
            files = glob.glob(search_path, recursive=True)
            
            for file_path in files:
                try:
                    # 跳过已加密的文件
                    if "secure" in file_path or "encrypted" in file_path.lower():
                        continue
                    
                    logger.info(f"迁移明文文件: {file_path}")
                    
                    # 读取文件内容
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    
                    if not content:
                        logger.warning(f"文件为空: {file_path}")
                        continue
                    
                    # 提取密钥名称
                    file_name = os.path.basename(file_path)
                    key_name = os.path.splitext(file_name)[0]
                    
                    # 存储到加密系统
                    success = self.store_key(
                        key_name, 
                        content,
                        description=f"从明文文件迁移: {file_path}",
                        tags=["migrated", "plaintext"]
                    )
                    
                    if success:
                        # 备份原文件（添加.backup扩展名）
                        backup_path = file_path + ".migrated_backup"
                        os.rename(file_path, backup_path)
                        logger.info(f"已将原文件备份到: {backup_path}")
                        
                        # 创建提示文件
                        notice_path = file_path + ".MIGRATION_NOTICE.txt"
                        with open(notice_path, 'w', encoding='utf-8') as f:
                            f.write(f"""⚠️ 重要提示 ⚠️

此文件中的敏感信息已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 迁移到加密存储系统。

原内容已备份到: {backup_path}

现在请使用以下方式访问该密钥:
python -m utils.security_tools get_key {key_name}

或通过代码调用:
from utils.security_tools import KeyManager
km = KeyManager()
key = km.get_key("{key_name}")

请不要删除此提示文件。
""")
                        
                        migrated.append({
                            "original": file_path,
                            "backup": backup_path,
                            "key_name": key_name,
                            "notice": notice_path
                        })
                    else:
                        failed.append({
                            "file": file_path,
                            "error": "存储失败"
                        })
                    
                except Exception as e:
                    failed.append({
                        "file": file_path,
                        "error": str(e)
                    })
                    logger.error(f"迁移文件失败 {file_path}: {e}")
        
        return {
            "migrated": migrated,
            "failed": failed,
            "total_attempted": len(migrated) + len(failed),
            "success_rate": len(migrated) / (len(migrated) + len(failed)) if (len(migrated) + len(failed)) > 0 else 0
        }


class ConfigSecurityScanner:
    """配置安全扫描器：检测安全风险"""
    
    def __init__(self, base_dir=None):
        if base_dir is None:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.base_dir = base_dir
        
        self.risks = []
        self.secrets_found = []
        self.recommendations = []
    
    def scan_for_plaintext_secrets(self):
        """扫描明文存储的敏感信息"""
        import re
        
        # 常见密钥模式
        secret_patterns = [
            (r'(?i)api[_-]?key\s*[:=]\s*[\'"]?([a-zA-Z0-9_-]{20,})[\'"]?', "API密钥"),
            (r'(?i)secret\s*[:=]\s*[\'"]?([a-zA-Z0-9_-]{10,})[\'"]?', "密钥"),
            (r'(?i)password\s*[:=]\s*[\'"]?([^\s\'"]{6,})[\'"]?', "密码"),
            (r'(?i)token\s*[:=]\s*[\'"]?([a-zA-Z0-9_-]{20,})[\'"]?', "访问令牌"),
            (r'-----BEGIN PRIVATE KEY-----', "私钥"),
            (r'-----BEGIN RSA PRIVATE KEY-----', "RSA私钥"),
            (r'-----BEGIN OPENSSH PRIVATE KEY-----', "SSH私钥"),
            (r'[a-fA-F0-9]{64}', "SHA-256哈希"),
            (r'(?i)deepseek.*key', "DeepSeek密钥"),
        ]
        
        # 扫描文件
        import glob
        
        # 需要扫描的文件类型
        scan_extensions = ['.py', '.json', '.yaml', '.yml', '.txt', '.ini', '.cfg', '.conf']
        
        files_scanned = 0
        for ext in scan_extensions:
            search_path = os.path.join(self.base_dir, "**", f"*{ext}")
            files = glob.glob(search_path, recursive=True)
            
            for file_path in files:
                try:
                    # 跳过某些目录
                    skip_patterns = ['__pycache__', '.git', 'venv', '.idea', '.vscode']
                    if any(pattern in file_path for pattern in skip_patterns):
                        continue
                    
                    # 跳过已加密文件
                    if 'encrypted_keys.dat' in file_path or 'secure' in file_path:
                        continue
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    files_scanned += 1
                    
                    for pattern, description in secret_patterns:
                        matches = re.findall(pattern, content)
                        if matches:
                            for match in matches:
                                if isinstance(match, tuple):
                                    match = match[0] if match else ""
                                
                                if match and len(match.strip()) > 5:  # 最小长度过滤
                                    relative_path = os.path.relpath(file_path, self.base_dir)
                                    self.secrets_found.append({
                                        "file": relative_path,
                                        "pattern": description,
                                        "content": match[:50] + "..." if len(match) > 50 else match,
                                        "severity": "high" if description in ["私钥", "RSA私钥", "SSH私钥"] else "medium"
                                    })
                                    logger.warning(f"发现敏感信息: {relative_path} - {description}")
                
                except Exception as e:
                    logger.error(f"扫描文件失败 {file_path}: {e}")
        
        # 生成建议
        if self.secrets_found:
            self.recommendations.append("立即迁移明文密钥到加密存储系统")
            self.recommendations.append("删除或替换包含敏感信息的配置文件")
            self.recommendations.append("设置.gitignore忽略敏感文件")
        
        return {
            "files_scanned": files_scanned,
            "secrets_found": self.secrets_found,
            "high_risk_count": sum(1 for s in self.secrets_found if s['severity'] == 'high'),
            "recommendations": self.recommendations
        }
    
    def scan_file_permissions(self):
        """扫描文件权限问题"""
        import stat
        
        risks = []
        
        # 检查关键目录权限
        critical_dirs = [
            os.path.join(self.base_dir, "金水谣数据"),
            os.path.join(self.base_dir, "engines"),
            os.path.join(self.base_dir, "scripts")
        ]
        
        for dir_path in critical_dirs:
            if os.path.exists(dir_path):
                try:
                    st = os.stat(dir_path)
                    mode = stat.S_IMODE(st.st_mode)
                    
                    if mode & stat.S_IWOTH:  # 其他用户可写
                        risks.append({
                            "path": os.path.relpath(dir_path, self.base_dir),
                            "issue": "目录权限过松（其他用户可写）",
                            "severity": "high",
                            "recommendation": f"修改权限: chmod o-w '{dir_path}'"
                        })
                except Exception as e:
                    logger.error(f"权限检查失败 {dir_path}: {e}")
        
        if risks:
            self.risks.extend(risks)
            self.recommendations.append("检查并修复目录权限")
            
        return risks
    
    def generate_security_report(self):
        """生成安全报告"""
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("金水谣系统安全扫描报告")
        report_lines.append("=" * 80)
        report_lines.append(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"扫描目录: {self.base_dir}")
        report_lines.append("")
        
        # 敏感信息扫描结果
        secret_result = self.scan_for_plaintext_secrets()
        report_lines.append(f"🔍 敏感信息扫描:")
        report_lines.append(f"  扫描文件数: {secret_result['files_scanned']}")
        report_lines.append(f"  发现敏感信息: {len(secret_result['secrets_found'])} 处")
        report_lines.append(f"  高风险: {secret_result['high_risk_count']} 处")
        
        if secret_result['secrets_found']:
            report_lines.append("")
            report_lines.append("🔴 发现的敏感信息:")
            for secret in secret_result['secrets_found']:
                report_lines.append(f"  - {secret['file']}: {secret['pattern']}")
                report_lines.append(f"    内容: {secret['content']}")
                report_lines.append(f"    风险等级: {secret['severity']}")
        
        # 权限扫描结果
        perm_result = self.scan_file_permissions()
        if perm_result:
            report_lines.append("")
            report_lines.append("🔴 权限问题:")
            for risk in perm_result:
                report_lines.append(f"  - {risk['path']}: {risk['issue']}")
                report_lines.append(f"    建议: {risk['recommendation']}")
        
        # 建议
        report_lines.append("")
        report_lines.append("📋 安全建议:")
        for rec in secret_result['recommendations'] + (self.recommendations or []):
            report_lines.append(f"  - {rec}")
        
        # 紧急程度评估
        total_risks = len(secret_result['secrets_found']) + len(perm_result)
        if total_risks > 5 or secret_result['high_risk_count'] > 0:
            risk_level = "🔴 高风险"
        elif total_risks > 0:
            risk_level = "🟡 中等风险"
        else:
            risk_level = "🟢 低风险"
        
        report_lines.append("")
        report_lines.append("📊 风险等级汇总:")
        report_lines.append(f"  总体风险: {risk_level}")
        report_lines.append(f"  总发现风险: {total_risks} 处")
        
        report_content = "\n".join(report_lines)
        return report_content


def test_security_system():
    """测试安全系统功能"""
    logging.basicConfig(level=logging.INFO)
    
    print("🔒 金水谣系统安全存储系统测试")
    print("=" * 60)
    
    try:
        # 测试加密系统
        print("🔐 测试加密系统...")
        test_key = "test_master_key_1234567"
        encryption = SensitiveDataEncryption(test_key)
        
        test_data = "这是敏感测试数据：API_KEY_ABC123DEF456"
        encrypted = encryption.encrypt_data(test_data)
        decrypted = encryption.decrypt_data(encrypted)
        
        assert decrypted == test_data, "加密解密失败"
        print("  ✅ 加密解密功能正常")
        
        # 测试密钥管理器
        print("\n🗝️ 测试密钥管理器...")
        km = KeyManager(encryption)
        km.store_key("test_api_key", "TEST_API_123456", "测试API密钥")
        
        retrieved_key = km.get_key("test_api_key")
        assert retrieved_key == "TEST_API_123456", "密钥获取失败"
        print("  ✅ 密钥存储和获取功能正常")
        
        # 测试配置文件安全扫描
        print("\n🔍 测试安全扫描...")
        scanner = ConfigSecurityScanner()
        report = scanner.generate_security_report()
        print("  ✅ 安全扫描功能正常")
        
        # 显示扫描摘要
        print(f"\n📊 安全扫描结果摘要:")
        lines = report.split('\n')
        for line in lines[:15]:  # 显示前15行摘要
            if line.strip():
                print(f"  {line}")
        
        print("\n" + "=" * 60)
        print("✅ 安全系统测试通过")
        print("\n💡 建议操作:")
        print("  1. 设置环境变量 TIANSHU_MASTER_KEY")
        print("  2. 运行 python -m utils.security_tools scan 扫描风险")
        print("  3. 运行 python -m utils.security_tools migrate 迁移明文密钥")
        
        return True
        
    except Exception as e:
        print(f"❌ 安全系统测试失败: {e}")
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="金水谣系统安全工具")
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # scan 命令
    scan_parser = subparsers.add_parser('scan', help='安全扫描')
    scan_parser.add_argument('--output', help='输出报告文件路径')
    
    # migrate 命令
    migrate_parser = subparsers.add_parser('migrate', help='迁移明文密钥')
    migrate_parser.add_argument('--confirm', action='store_true', help='自动确认')
    
    # list 命令
    list_parser = subparsers.add_parser('list', help='列出所有密钥')
    list_parser.add_argument('--show', action='store_true', help='显示密钥值')
    
    # get 命令
    get_parser = subparsers.add_parser('get', help='获取密钥')
    get_parser.add_argument('key_name', help='密钥名称')
    
    # store 命令
    store_parser = subparsers.add_parser('store', help='存储密钥')
    store_parser.add_argument('key_name', help='密钥名称')
    store_parser.add_argument('key_value', help='密钥值')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if args.command == 'scan':
        scanner = ConfigSecurityScanner()
        report = scanner.generate_security_report()
        print(report)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n📄 报告已保存到: {args.output}")
    
    elif args.command == 'migrate':
        # 首先检查主密钥
        master_key = os.environ.get("TIANSHU_MASTER_KEY")
        if not master_key:
            print("❌ 错误: 请先设置环境变量 TIANSHU_MASTER_KEY")
            print("  命令: export TIANSHU_MASTER_KEY=your_secure_key")
            exit(1)
        
        encryption = SensitiveDataEncryption(master_key)
        km = KeyManager(encryption)
        
        print("🔄 开始迁移明文密钥文件...")
        print(f"扫描目录: {km.key_file}")
        
        if not args.confirm:
            print("⚠️ 警告: 此操作将:")
            print("  1. 加密存储所有明文密钥")
            print("  2. 备份原文件")
            print("  3. 创建迁移提示文件")
            confirm = input("是否继续? (yes/no): ")
            if confirm.lower() != 'yes':
                print("取消操作")
                exit(0)
        
        result = km.migrate_plaintext_files()
        print(f"\n📊 迁移结果:")
        print(f"  成功迁移: {len(result['migrated'])} 个文件")
        print(f"  失败: {len(result['failed'])} 个文件")
        print(f"  成功率: {result['success_rate']:.1%}")
        
        if result['migrated']:
            print(f"\n✅ 已迁移的文件:")
            for item in result['migrated']:
                print(f"  - {item['original']} -> key: {item['key_name']}")
        
        if result['failed']:
            print(f"\n❌ 失败的文件:")
            for item in result['failed']:
                print(f"  - {item['file']}: {item['error']}")
    
    elif args.command == 'list':
        master_key = os.environ.get("TIANSHU_MASTER_KEY")
        if not master_key:
            print("❌ 错误: 请先设置环境变量 TIANSHU_MASTER_KEY")
            exit(1)
        
        encryption = SensitiveDataEncryption(master_key)
        km = KeyManager(encryption)
        km.list_keys(show_values=args.show)
    
    elif args.command == 'get':
        master_key = os.environ.get("TIANSHU_MASTER_KEY")
        if not master_key:
            print("❌ 错误: 请先设置环境变量 TIANSHU_MASTER_KEY")
            exit(1)
        
        encryption = SensitiveDataEncryption(master_key)
        km = KeyManager(encryption)
        key_value = km.get_key(args.key_name)
        
        if key_value:
            print(f"🔑 密钥 '{args.key_name}':")
            print(f"  值: {key_value}")
        else:
            print(f"❌ 未找到密钥: {args.key_name}")
    
    elif args.command == 'store':
        master_key = os.environ.get("TIANSHU_MASTER_KEY")
        if not master_key:
            print("❌ 错误: 请先设置环境变量 TIANSHU_MASTER_KEY")
            exit(1)
        
        encryption = SensitiveDataEncryption(master_key)
        km = KeyManager(encryption)
        
        description = input("输入密钥描述: ")
        
        success = km.store_key(args.key_name, args.key_value, description)
        if success:
            print(f"✅ 密钥 '{args.key_name}' 已存储")
        else:
            print(f"❌ 存储失败")
    
    else:
        # 默认运行测试
        success = test_security_system()
        if not success:
            parser.print_help()