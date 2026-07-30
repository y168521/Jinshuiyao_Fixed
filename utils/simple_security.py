#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣系统 - 简化安全存储系统 (兼容Python 3.8)

不使用复杂的cryptography库，使用Python标准库提供基本的加密功能
只提供最基本的安全存储能力，防止明文存储敏感数据
"""

import os
import json
import base64
import hashlib
import logging
import getpass
from datetime import datetime
import hmac
import random
import secrets

logger = logging.getLogger("jinshuiyao.simple_security")


class SimpleSensitiveDataStorage:
    """简化版的敏感数据存储 (兼容所有Python版本)"""
    
    def __init__(self, password=None):
        # 使用密码或环境变量
        if password:
            self.password = password
        else:
            self.password = os.environ.get("TIANSHU_SIMPLE_KEY", "default_secure_key_2026")
        
        # 存储目录
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.secure_dir = os.path.join(self.base_dir, "金水谣数据", "simple_secure")
        self.data_file = os.path.join(self.secure_dir, "secure_storage.json.enc")
        self.access_log_dir = os.path.join(self.secure_dir, "access_logs")
        
        # 确保目录存在
        os.makedirs(self.secure_dir, exist_ok=True)
        os.makedirs(self.access_log_dir, exist_ok=True)
        
        # 加载数据
        self.data = self._load_data()
    
    def _load_data(self):
        """加载加密数据"""
        if not os.path.exists(self.data_file):
            logger.info("安全存储文件不存在，创建新的存储文件")
            return {}
        
        try:
            with open(self.data_file, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                return {}
            
            # 简单解密: Base64解码 + HMAC验证
            try:
                decoded = base64.b64decode(encrypted_data)
                data_json = decoded.decode('utf-8')
                
                # HMAC验证（简单完整性检查）
                expected_hmac = hashlib.sha256((data_json + self.password).encode()).hexdigest()
                
                # 存储时我们会在末尾存储HMAC，现在验证
                json_end = data_json.rfind("}")
                if json_end > 0:
                    actual_data = data_json[:json_end+1]
                    stored_hmac = data_json[json_end+1:]
                    
                    computed_hmac = hashlib.sha256((actual_data + self.password).encode()).hexdigest()
                    
                    if stored_hmac[:64] == computed_hmac[:64]:
                        data = json.loads(actual_data)
                        logger.info(f"成功加载安全存储数据，包含 {len(data)} 个条目")
                        return data
                    else:
                        logger.warning("HMAC验证失败，数据可能被篡改")
            except Exception as e:
                logger.warning(f"解密数据失败，可能格式不同: {e}")
            
            # 如果解密失败，尝试直接解析（向后兼容）
            try:
                data = json.loads(encrypted_data.decode('utf-8'))
                logger.info("使用兼容模式加载数据")
                return data
            except (ValueError, UnicodeDecodeError):
                logger.error("无法解析安全存储文件")
                
        except Exception as e:
            logger.error(f"加载安全存储文件失败: {e}")
        
        return {}
    
    def _save_data(self):
        """保存加密数据"""
        try:
            # 转换为JSON
            data_json = json.dumps(self.data, ensure_ascii=False)
            
            # 计算HMAC用于完整性校验
            data_hmac = hashlib.sha256((data_json + self.password).encode()).hexdigest()
            
            # 组合数据+HMAC
            protected_data = data_json + data_hmac[:32]  # 取HMAC前32字符
            
            # Base64编码存储
            encoded_data = base64.b64encode(protected_data.encode('utf-8'))
            
            with open(self.data_file, 'wb') as f:
                f.write(encoded_data)
            
            logger.debug("安全存储数据已保存")
            return True
            
        except Exception as e:
            logger.error(f"保存安全存储数据失败: {e}")
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
        
        # 记录到文件
        log_file = os.path.join(
            self.access_log_dir, 
            f"access_{datetime.now().strftime('%Y%m%d')}.log.json"
        )
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.warning(f"写入访问日志失败: {e}")
        
        if not success:
            logger.warning(f"异常访问记录: {key_name}, 动作: {action}")
    
    def store_key(self, key_name, key_value, description="", tags=None):
        """存储密钥"""
        try:
            # 简单混淆: 使用密码对值进行简单HMAC混淆
            stored_value = self._obfuscate_value(key_value)
            
            self.data[key_name] = {
                "value": stored_value,
                "original_len": len(key_value),
                "description": description,
                "created_at": datetime.now().isoformat(),
                "last_accessed": None,
                "access_count": 0,
                "tags": tags or []
            }
            
            success = self._save_data()
            if success:
                self._log_access(key_name, "store", True)
                logger.info(f"密钥 '{key_name}' 已安全存储")
                return True
            else:
                self._log_access(key_name, "store", False)
                return False
                
        except Exception as e:
            logger.error(f"存储密钥失败: {key_name}, 错误: {e}")
            self._log_access(key_name, "store", False)
            return False
    
    def get_key(self, key_name):
        """获取密钥"""
        try:
            if key_name not in self.data:
                logger.warning(f"密钥不存在: {key_name}")
                self._log_access(key_name, "get", False)
                return None
            
            key_info = self.data[key_name]
            
            # 还原值
            original_value = self._deobfuscate_value(
                key_info["value"], 
                key_info.get("original_len", 0)
            )
            
            # 更新访问信息
            key_info["last_accessed"] = datetime.now().isoformat()
            key_info["access_count"] = key_info.get("access_count", 0) + 1
            
            # 保存更新
            self._save_data()
            
            # 记录成功访问
            self._log_access(key_name, "get", True)
            
            return original_value
            
        except Exception as e:
            logger.error(f"获取密钥失败: {key_name}, 错误: {e}")
            self._log_access(key_name, "get", False)
            return None
    
    def _obfuscate_value(self, value):
        """混淆值 (基于密码的简单混淆)"""
        value_str = str(value)
        # 简单的异或混淆
        key_bytes = self.password.encode()
        value_bytes = value_str.encode()
        
        result = []
        for i, char in enumerate(value_bytes):
            key_char = key_bytes[i % len(key_bytes)]
            result.append(char ^ key_char)
        
        # 转换为十六进制字符串存储
        return ''.join(f'{b:02x}' for b in result)
    
    def _deobfuscate_value(self, obfuscated_hex, original_len):
        """还原值"""
        try:
            # 从十六进制转换回字节
            obfuscated_bytes = bytes.fromhex(obfuscated_hex)
            key_bytes = self.password.encode()
            
            result = []
            for i, char in enumerate(obfuscated_bytes):
                key_char = key_bytes[i % len(key_bytes)]
                result.append(char ^ key_char)
            
            # 裁切到原始长度
            result_bytes = bytes(result)[:original_len]
            return result_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"还原值失败: {e}")
            return ""
    
    def list_keys(self, show_values=False):
        """列出所有密钥"""
        try:
            if not self.data:
                print("📭 无存储的密钥")
                return []
            
            print(f"🔑 已存储的密钥 ({len(self.data)} 个):")
            print("-" * 60)
            
            result = []
            for idx, (key_name, key_info) in enumerate(self.data.items(), 1):
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
                    print(f"   存储值: {masked}")
                
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
        """掩码显示密钥"""
        if not key_value:
            return ""
        
        if len(key_value) <= visible_chars * 2:
            return key_value
            
        start = key_value[:visible_chars]
        end = key_value[-visible_chars:]
        middle_len = len(key_value) - visible_chars * 2
        
        return f"{start}{'*' * middle_len}{end}"
    
    def migrate_plaintext_files(self, file_patterns=None):
        """迁移明文密钥文件"""
        if file_patterns is None:
            file_patterns = ["*key*.txt", "*secret*.txt", "*token*.txt"]
        
        migrated = []
        failed = []
        
        import glob
        base_dir = self.base_dir
        
        for pattern in file_patterns:
            search_path = os.path.join(base_dir, "**", pattern)
            files = glob.glob(search_path, recursive=True)
            
            for file_path in files:
                try:
                    # 跳过安全目录
                    if "simple_secure" in file_path or "secure" in file_path:
                        continue
                    
                    # 跳过备份文件
                    if "backup" in file_path.lower() or "migrated" in file_path.lower():
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
                    
                    # 存储到安全系统
                    success = self.store_key(
                        key_name, 
                        content,
                        description=f"从明文文件迁移: {file_path}",
                        tags=["migrated", "plaintext", "simple_secure"]
                    )
                    
                    if success:
                        # 备份原文件
                        backup_path = file_path + ".simple_backup"
                        try:
                            import shutil
                            shutil.copy2(file_path, backup_path)
                            
                            # 创建提示文件
                            notice_path = file_path + ".SIMPLE_SECURE_MIGRATION.txt"
                            with open(notice_path, 'w', encoding='utf-8') as f:
                                f.write(f"""⚠️ 重要提示 ⚠️

此文件中的敏感信息已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 
迁移到简单安全存储系统。

原内容已备份到: {backup_path}

现在请使用以下方式访问该密钥:
从代码中: 
  from utils.simple_security import SimpleSensitiveDataStorage
  store = SimpleSensitiveDataStorage("你的密码")
  key = store.get_key("{key_name}")

或者设置环境变量 TI_SIMPLE_KEY="你的密码"

请不要删除此提示文件。
""")
                            
                            migrated.append({
                                "original": file_path,
                                "backup": backup_path,
                                "key_name": key_name,
                                "notice": notice_path
                            })
                            
                        except Exception as backup_error:
                            logger.error(f"备份文件失败 {file_path}: {backup_error}")
                            failed.append({
                                "file": file_path,
                                "error": f"备份失败: {backup_error}"
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


def test_simple_security():
    """测试简化安全系统"""
    logging.basicConfig(level=logging.INFO)
    
    print("🔒 简化安全存储系统测试")
    print("=" * 60)
    
    try:
        # 创建存储对象
        store = SimpleSensitiveDataStorage("test_password_123")
        
        # 测试存储和获取
        print("测试密钥存储和获取...")
        store.store_key("test_api_key", "API_TEST_123456789", "测试API密钥")
        
        retrieved = store.get_key("test_api_key")
        if retrieved == "API_TEST_123456789":
            print("✅ 密钥存储和获取测试通过")
        else:
            print(f"❌ 密钥存储测试失败，获取的值: {retrieved}")
            return False
        
        # 测试列表功能
        print("\n测试密钥列表...")
        keys = store.list_keys()
        if keys:
            print("✅ 密钥列表测试通过")
        else:
            print("❌ 密钥列表测试失败")
            return False
        
        # 测试迁移功能
        print("\n测试迁移功能...")
        import tempfile
        import os
        
        temp_dir = tempfile.mkdtemp()
        test_file = os.path.join(temp_dir, "test_key.txt")
        with open(test_file, 'w') as f:
            f.write("TEST_MIGRATION_KEY_987654321")
        
        store2 = SimpleSensitiveDataStorage("test_migration_password")
        
        import sys
        original_cwd = os.getcwd()
        original_base_dir = store2.base_dir
        try:
            # 临时设置base_dir用于测试
            store2.base_dir = temp_dir
            result = store2.migrate_plaintext_files()
            
            if result["success_rate"] > 0:
                print(f"✅ 迁移功能测试通过 (成功率: {result['success_rate']:.1%})")
            else:
                print(f"❌ 迁移功能测试失败")
                return False
        finally:
            store2.base_dir = original_base_dir
            os.chdir(original_cwd)
            import shutil
            shutil.rmtree(temp_dir)
        
        print("\n" + "=" * 60)
        print("✅ 简化安全系统测试全部通过")
        return True
        
    except Exception as e:
        print(f"❌ 简化安全系统测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="金水谣系统简化安全工具")
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # init 命令
    init_parser = subparsers.add_parser('init', help='初始化安全存储')
    init_parser.add_argument('--password', help='密码')
    
    # migrate 命令
    migrate_parser = subparsers.add_parser('migrate', help='迁移明文密钥')
    migrate_parser.add_argument('--password', help='密码')
    
    # list 命令
    list_parser = subparsers.add_parser('list', help='列出所有密钥')
    list_parser.add_argument('--password', help='密码')
    list_parser.add_argument('--show', action='store_true', help='显示密钥值')
    
    # get 命令
    get_parser = subparsers.add_parser('get', help='获取密钥')
    get_parser.add_argument('key_name', help='密钥名称')
    get_parser.add_argument('--password', help='密码')
    
    # store 命令
    store_parser = subparsers.add_parser('store', help='存储密钥')
    store_parser.add_argument('key_name', help='密钥名称')
    store_parser.add_argument('key_value', help='密钥值')
    store_parser.add_argument('--password', help='密码')
    
    args = parser.parse_args()
    
    if not args.command:
        # 默认运行测试
        success = test_simple_security()
        if not success:
            parser.print_help()
    else:
        # 执行命令
        password = args.password or os.environ.get("TIANSHU_SIMPLE_KEY")
        if not password:
            print("❌ 错误: 请设置密码")
            print("  方式1: --password 参数指定")
            print("  方式2: 设置环境变量 TIANSHU_SIMPLE_KEY")
            exit(1)
        
        store = SimpleSensitiveDataStorage(password)
        
        if args.command == 'init':
            print("✅ 简化安全存储已初始化")
            print(f"  存储目录: {store.secure_dir}")
            print(f"  数据文件: {store.data_file}")
            
        elif args.command == 'migrate':
            print("🔄 开始迁移明文密钥文件...")
            result = store.migrate_plaintext_files()
            
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
            store.list_keys(show_values=args.show)
        
        elif args.command == 'get':
            key_value = store.get_key(args.key_name)
            if key_value:
                print(f"🔑 密钥 '{args.key_name}':")
                print(f"  值: {key_value}")
            else:
                print(f"❌ 未找到密钥: {args.key_name}")
        
        elif args.command == 'store':
            description = input("输入密钥描述: ")
            tags_input = input("输入标签(用逗号分隔): ")
            tags = [t.strip() for t in tags_input.split(',')] if tags_input else []
            
            success = store.store_key(args.key_name, args.key_value, description, tags)
            if success:
                print(f"✅ 密钥 '{args.key_name}' 已存储")
            else:
                print(f"❌ 存储失败")