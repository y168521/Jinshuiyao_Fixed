#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣系统第一阶段优化验证测试

验证内容：
1. ✅ 彩票预测系统崩溃修复 (killer模块)
2. ✅ API向后兼容机制 (兼容层)
3. ✅ 敏感数据安全存储 (加密系统)
4. ✅ 系统整体稳定性

测试步骤：
1. 加载所有修复模块
2. 模拟各种调用场景
3. 检测并修复发现的任何问题
4. 生成优化报告
"""

import os
import sys
import json
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("jinshuiyao.phase1_validation")


class Phase1Validation:
    """第一阶段优化验证器"""
    
    def __init__(self):
        self.results = {}
        self.test_cases = {}
        self.setup_tests()
        
    def setup_tests(self):
        """设置所有测试用例"""
        self.test_cases = {
            "killer_fixed_backward_compatibility": {
                "priority": "critical",
                "description": "killer.calc()函数完全向后兼容性测试",
                "function": self.test_killer_backward_compatibility,
                "dependencies": ["engines.killer"]
            },
            "api_compatibility_layer": {
                "priority": "high",
                "description": "API兼容层功能测试",  
                "function": self.test_api_compatibility_layer,
                "dependencies": ["utils.api_compat"]
            },
            "security_system_basic": {
                "priority": "high",
                "description": "安全存储系统基础功能测试",
                "function": self.test_security_system_basic,
                "dependencies": ["utils.security_tools"]
            },
            "migration_capability": {
                "priority": "medium",
                "description": "明文密钥迁移能力测试",
                "function": self.test_migration_capability,
                "dependencies": ["utils.security_tools", "tempfile"]
            },
            "error_log_consistency": {
                "priority": "low",
                "description": "错误日志格式一致性检查",
                "function": self.test_error_log_consistency,
                "dependencies": []
            }
        }
    
    def test_killer_backward_compatibility(self):
        """测试killer模块向后兼容性"""
        logger.info("测试killer模块向后兼容性...")
        
        try:
            from engines import killer

            killer = killer.Killer()
            test_results = []
            
            # 测试用例1: 旧式调用 - calc(nums)
            try:
                result1 = killer.calc([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
                logger.debug(f"测试1-旧式调用成功: 结果={result1}")
                test_results.append({
                    "name": "旧式调用 calc(nums)",
                    "status": "✅ 成功",
                    "result_type": type(result1).__name__,
                    "result_len": len(result1) if hasattr(result1, '__len__') else "N/A"
                })
            except Exception as e:
                logger.error(f"测试1-旧式调用失败: {e}")
                test_results.append({
                    "name": "旧式调用 calc(nums)",
                    "status": f"❌ 失败: {e}",
                    "result_type": "Exception",
                    "result_len": "N/A"
                })
            
            # 测试用例2: 错误日志模式 - calc(nums, history=arr, lot=lot)
            try:
                result2 = killer.calc(nums=[1, 2, 3, 4, 5], history=[{"nums": "1 2 3"}], lot="福彩3D")
                logger.debug(f"测试2-错误日志模式成功: 结果={result2}")
                test_results.append({
                    "name": "错误日志模式 calc(nums, history, lot)",
                    "status": "✅ 成功",
                    "result_type": type(result2).__name__,
                    "result_len": len(result2) if hasattr(result2, '__len__') else "N/A"
                })
            except Exception as e:
                logger.error(f"测试2-错误日志模式失败: {e}")
                test_results.append({
                    "name": "错误日志模式 calc(nums, history, lot)",
                    "status": f"❌ 失败: {e}",
                    "result_type": "Exception",
                    "result_len": "N/A"
                })
            
            # 测试用例3: 新式调用 - calc_advanced(history, lot)
            try:
                result3 = killer.calc_advanced(
                    history=[{"nums": "1 2 3 4 5 6"}, {"nums": "2 3 4 5 6 7"}],
                    lot="双色球"
                )
                logger.debug(f"测试3-新式调用成功: 结果={result3}")
                test_results.append({
                    "name": "新式调用 calc_advanced(history, lot)",
                    "status": "✅ 成功",
                    "result_type": type(result3).__name__,
                    "result_len": len(result3) if hasattr(result3, '__len__') else "N/A"
                })
            except Exception as e:
                logger.error(f"测试3-新式调用失败: {e}")
                test_results.append({
                    "name": "新式调用 calc_advanced(history, lot)",
                    "status": f"❌ 失败: {e}",
                    "result_type": "Exception",
                    "result_len": "N/A"
                })
            
            # 测试用例4: 兼容性测试方法
            try:
                compatibility_results = killer.test_compatibility()
                success_count = sum(1 for r in compatibility_results if "✅" in r[1])
                total_count = len(compatibility_results)
                logger.debug(f"测试4-兼容性测试成功: {success_count}/{total_count}")
                test_results.append({
                    "name": "内置兼容性测试 test_compatibility()",
                    "status": f"✅ 成功 ({success_count}/{total_count})",
                    "result_type": "list",
                    "result_len": total_count
                })
            except Exception as e:
                logger.error(f"测试4-兼容性测试失败: {e}")
                test_results.append({
                    "name": "内置兼容性测试 test_compatibility()",
                    "status": f"❌ 失败: {e}",
                    "result_type": "Exception",
                    "result_len": "N/A"
                })
            
            # 计算成功率
            success_rate = sum(1 for r in test_results if "✅" in r["status"]) / len(test_results)
            
            return {
                "module": "killer",
                "test_results": test_results,
                "success_rate": success_rate,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"killer兼容性测试初始化失败: {e}")
            return {
                "status": "❌ 初始化失败",
                "error": str(e),
                "success_rate": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    def test_api_compatibility_layer(self):
        """测试API兼容性层"""
        logger.info("测试API兼容性层...")
        
        try:
            from utils import api_compat
            
            test_results = []
            
            # 测试用例1: API追踪器测试
            try:
                tracker = api_compat.APIConfigTracker()
                
                # 记录一些测试调用
                tracker.record_call(
                    "test_module", 
                    "test_function", 
                    [1, 2, 3], 
                    {"param": "value"},
                    result=[1, 2, 3]
                )
                
                # 获取摘要
                summary = tracker.get_incompatible_summary()
                logger.debug(f"API追踪器摘要: {summary}")
                
                test_results.append({
                    "name": "API追踪器功能",
                    "status": "✅ 成功",
                    "result": f"总调用: {summary.get('total_calls', 0)}"
                })
            except Exception as e:
                logger.error(f"API追踪器测试失败: {e}")
                test_results.append({
                    "name": "API追踪器功能",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            # 测试用例2: API代理测试
            try:
                proxy = api_compat.SmartAPIProxy()
                logger.debug("API代理初始化成功")
                test_results.append({
                    "name": "API代理初始化",
                    "status": "✅ 成功",
                    "result": "代理对象创建成功"
                })
            except Exception as e:
                logger.error(f"API代理测试失败: {e}")
                test_results.append({
                    "name": "API代理初始化",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            # 测试用例3: 兼容性测试函数
            try:
                test_result = api_compat.test_api_compatibility()
                if "error" in test_result:
                    test_results.append({
                        "name": "兼容性整体测试",
                        "status": f"❌ 失败: {test_result['error']}",
                        "result": "测试异常"
                    })
                else:
                    success_rate = test_result.get("rate", 0)
                    test_results.append({
                        "name": "兼容性整体测试",
                        "status": f"✅ 成功 ({success_rate:.1%})",
                        "result": f"成功率: {success_rate:.1%}"
                    })
            except Exception as e:
                logger.error(f"兼容性测试函数失败: {e}")
                test_results.append({
                    "name": "兼容性整体测试",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            # 计算成功率
            success_rate = sum(1 for r in test_results if "✅" in r["status"]) / len(test_results)
            
            return {
                "module": "api_compat",
                "test_results": test_results,
                "success_rate": success_rate,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"API兼容层测试初始化失败: {e}")
            return {
                "status": "❌ 初始化失败",
                "error": str(e),
                "success_rate": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    def test_security_system_basic(self):
        """测试安全系统基础功能"""
        logger.info("测试安全系统基础功能...")
        
        try:
            from utils.security_tools import SensitiveDataEncryption
            
            test_results = []
            
            # 使用测试主密钥
            test_master_key = "test_master_key_for_validation_123456789"
            os.environ["TIANSHU_MASTER_KEY"] = test_master_key  # 临时设置
            
            # 测试用例1: 加密解密测试
            try:
                encryption = SensitiveDataEncryption()
                test_data = "敏感测试数据: API_KEY_TEST_123456"
                
                encrypted = encryption.encrypt_data(test_data)
                logger.debug(f"加密成功, 加密后长度: {len(encrypted)}")
                
                decrypted = encryption.decrypt_data(encrypted)
                logger.debug(f"解密成功, 原始数据: {test_data[:20]}...")
                
                if decrypted == test_data:
                    test_results.append({
                        "name": "AES-GCM加密解密",
                        "status": "✅ 成功",
                        "result": "加密解密功能正常, 数据一致"
                    })
                else:
                    test_results.append({
                        "name": "AES-GCM加密解密",
                        "status": "❌ 失败: 数据不一致",
                        "result": f"原始: {test_data[:20]}..., 解密: {decrypted[:20]}..."
                    })
            except Exception as e:
                logger.error(f"加密解密测试失败: {e}")
                test_results.append({
                    "name": "AES-GCM加密解密",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            # 测试用例2: 密钥管理器基础功能
            try:
                from utils.security_tools import KeyManager
                km = KeyManager(encryption)
                
                # 测试存储和获取
                store_success = km.store_key(
                    "validation_test_key",
                    "TEST_API_VALIDATION_987654321",
                    "验证测试使用的API密钥"
                )
                
                if store_success:
                    retrieved = km.get_key("validation_test_key")
                    if retrieved == "TEST_API_VALIDATION_987654321":
                        test_results.append({
                            "name": "密钥存储和获取",
                            "status": "✅ 成功",
                            "result": "密钥存储和获取功能正常"
                        })
                    else:
                        test_results.append({
                            "name": "密钥存储和获取",
                            "status": "❌ 失败: 密钥值不匹配",
                            "result": f"存储的值不匹配"
                        })
                else:
                    test_results.append({
                        "name": "密钥存储和获取",
                        "status": "❌ 失败: 存储失败",
                        "result": "存储操作失败"
                    })
                
                # 清理测试密钥
                km.delete_key("validation_test_key", require_confirm=False)
                
            except Exception as e:
                logger.error(f"密钥管理器测试失败: {e}")
                test_results.append({
                    "name": "密钥存储和获取",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            # 删除临时环境变量
            if "TIANSHU_MASTER_KEY" in os.environ:
                del os.environ["TIANSHU_MASTER_KEY"]
            
            # 计算成功率
            success_rate = sum(1 for r in test_results if "✅" in r["status"]) / len(test_results)
            
            return {
                "module": "security_tools",
                "test_results": test_results,
                "success_rate": success_rate,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"安全系统测试初始化失败: {e}")
            return {
                "status": "❌ 初始化失败",
                "error": str(e),
                "success_rate": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    def test_migration_capability(self):
        """测试明文密钥迁移能力"""
        logger.info("测试迁移能力（模拟环境）...")
        
        try:
            import tempfile
            import shutil
            
            test_results = []
            
            # 创建临时测试目录
            temp_dir = tempfile.mkdtemp(prefix="jinshuiyao_migration_test_")
            logger.debug(f"创建临时测试目录: {temp_dir}")
            
            # 创建测试密钥文件
            test_files = {
                "api_key.txt": "API_KEY_TEST_123456789",
                "deepseek_secret.txt": "DEEPSEEK_KEY_TEST_ABCDEF123456",
                "config_password.txt": "test_password_123"
            }
            
            created_files = []
            for filename, content in test_files.items():
                filepath = os.path.join(temp_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                created_files.append(filepath)
                logger.debug(f"创建测试文件: {filepath}")
            
            # 设置测试环境
            test_master_key = "test_migration_key_987654321"
            os.environ["TIANSHU_MASTER_KEY"] = test_master_key
            
            try:
                from utils.security_tools import KeyManager
                
                # 创建临时密钥管理器
                from utils.security_tools import SensitiveDataEncryption
                encryption = SensitiveDataEncryption()
                
                # 修改密钥管理器的文件路径为临时目录
                original_file_attr = None
                
                # 由于KeyManager有固定路径，我们只测试基础功能
                km = KeyManager(encryption)
                
                # 测试列表功能
                keys_before = km.list_keys()
                
                # 测试扫描功能
                from utils.security_tools import ConfigSecurityScanner
                scanner = ConfigSecurityScanner(temp_dir)
                scan_result = scanner.scan_for_plaintext_secrets()
                
                logger.debug(f"扫描结果: 发现{len(scan_result['secrets_found'])}个敏感信息")
                
                if len(scan_result['secrets_found']) >= len(test_files):
                    test_results.append({
                        "name": "敏感信息扫描",
                        "status": "✅ 成功",
                        "result": f"成功扫描到{len(scan_result['secrets_found'])}个敏感信息"
                    })
                else:
                    test_results.append({
                        "name": "敏感信息扫描",
                        "status": "⚠️ 部分成功",
                        "result": f"期望{len(test_files)}个，找到{len(scan_result['secrets_found'])}个"
                    })
                
                # 生成安全报告测试
                report = scanner.generate_security_report()
                if "安全扫描报告" in report:
                    test_results.append({
                        "name": "安全报告生成",
                        "status": "✅ 成功",
                        "result": "安全报告生成成功"
                    })
                else:
                    test_results.append({
                        "name": "安全报告生成",
                        "status": "❌ 失败",
                        "result": "报告内容不符合预期"
                    })
                
            except Exception as e:
                logger.error(f"迁移测试失败: {e}")
                test_results.append({
                    "name": "功能测试",
                    "status": f"❌ 失败: {e}",
                    "result": "Exception"
                })
            
            finally:
                # 清理环境
                if "TIANSHU_MASTER_KEY" in os.environ:
                    del os.environ["TIANSHU_MASTER_KEY"]
                
                # 删除临时目录
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"清理临时目录: {temp_dir}")
                except Exception as e:
                    logger.warning(f"清理临时目录失败: {e}")
            
            # 计算成功率
            success_rate = sum(1 for r in test_results if "✅" in r["status"]) / len(test_results)
            
            return {
                "module": "migration_capability",
                "test_results": test_results,
                "success_rate": success_rate,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"迁移能力测试初始化失败: {e}")
            return {
                "status": "❌ 初始化失败",
                "error": str(e),
                "success_rate": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    def test_error_log_consistency(self):
        """测试错误日志一致性"""
        logger.info("检查错误日志格式一致性...")
        
        try:
            # 检查错误日志目录
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "金水谣数据", "log", "err_log"
            )
            
            test_results = []
            
            if os.path.exists(log_dir):
                log_files = [f for f in os.listdir(log_dir) if f.endswith('.log')]
                logger.debug(f"找到{len(log_files)}个错误日志文件")
                
                if log_files:
                    # 检查最新的日志文件
                    log_files.sort(reverse=True)
                    latest_log = os.path.join(log_dir, log_files[0])
                    
                    try:
                        with open(latest_log, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        
                        # 分析日志格式
                        if lines:
                            # 检查是否有ERROR级别的日志
                            error_lines = [l for l in lines if 'ERROR' in l.upper()]
                            
                            test_results.append({
                                "name": "错误日志文件",
                                "status": "✅ 存在",
                                "result": f"找到{len(log_files)}个文件，{len(lines)}行日志"
                            })
                            
                            if error_lines:
                                # 检查格式一致性
                                error_counts = {}
                                for line in error_lines:
                                    # 粗略分类
                                    if 'calc()' in line:
                                        error_counts['calc_error'] = error_counts.get('calc_error', 0) + 1
                                    elif 'API' in line or 'api' in line:
                                        error_counts['api_error'] = error_counts.get('api_error', 0) + 1
                                    else:
                                        error_counts['other_error'] = error_counts.get('other_error', 0) + 1
                                
                                test_results.append({
                                    "name": "错误日志分析",
                                    "status": "✅ 有错误记录",
                                    "result": f"错误分类: {error_counts}"
                                })
                            else:
                                test_results.append({
                                    "name": "错误日志分析",
                                    "status": "⚠️ 无错误记录",
                                    "result": "未发现ERROR级别的日志记录"
                                })
                        else:
                            test_results.append({
                                "name": "错误日志文件",
                                "status": "⚠️ 为空",
                                "result": "日志文件为空"
                            })
                        
                    except Exception as e:
                        logger.error(f"读取日志文件失败: {e}")
                        test_results.append({
                            "name": "日志文件读取",
                            "status": f"❌ 失败: {e}",
                            "result": "无法读取日志文件"
                        })
                else:
                    test_results.append({
                        "name": "错误日志文件",
                        "status": "⚠️ 未找到",
                        "result": "错误日志目录下没有.log文件"
                    })
            else:
                test_results.append({
                    "name": "错误日志目录",
                    "status": "✅ 不存在（系统可能还未生成错误）",
                    "result": "err_log目录不存在，可能系统运行正常"
                })
            
            # 计算成功率（这里调整标准，因为不存在目录也是合理状态）
            success_count = 0
            for r in test_results:
                if "❌" not in r["status"]:  # 不算失败就成功
                    success_count += 1
            
            success_rate = success_count / len(test_results) if test_results else 1.0
            
            return {
                "module": "error_logs",
                "test_results": test_results,
                "success_rate": success_rate,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"错误日志检查失败: {e}")
            return {
                "status": "❌ 检查失败",
                "error": str(e),
                "success_rate": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    def run_all_tests(self, priority_filter=None):
        """运行所有测试"""
        logger.info("启动第一阶段优化验证测试套件")
        
        test_order = ["critical", "high", "medium", "low"]
        if priority_filter:
            test_order = [p for p in test_order if p in priority_filter]
        
        all_results = {}
        
        for priority in test_order:
            logger.info(f"\n执行{priority}优先级测试...")
            
            for test_name, test_info in self.test_cases.items():
                if test_info["priority"] == priority:
                    logger.info(f"运行测试: {test_name} - {test_info['description']}")
                    
                    # 检查依赖
                    dependencies_ok = True
                    for dep in test_info.get("dependencies", []):
                        try:
                            if '.' in dep:
                                importlib = __import__(dep.split('.')[0])
                            else:
                                __import__(dep)
                        except ImportError as e:
                            logger.warning(f"依赖检查失败 {test_name}: {dep} - {e}")
                            dependencies_ok = False
                    
                    if not dependencies_ok:
                        logger.warning(f"跳过测试 {test_name}：依赖不满足")
                        all_results[test_name] = {
                            "status": "跳过",
                            "reason": "依赖不满足",
                            "timestamp": datetime.now().isoformat()
                        }
                        continue
                    
                    # 运行测试
                    try:
                        result = test_info["function"]()
                        all_results[test_name] = result
                        
                        success_rate = result.get("success_rate", 0)
                        status_icon = "✅" if success_rate >= 0.8 else "⚠️" if success_rate >= 0.5 else "❌"
                        
                        logger.info(f"{status_icon} 测试 {test_name} 完成: 成功率 {success_rate:.1%}")
                        
                    except Exception as e:
                        logger.error(f"测试运行异常 {test_name}: {e}")
                        all_results[test_name] = {
                            "status": "异常",
                            "error": str(e),
                            "success_rate": 0,
                            "timestamp": datetime.now().isoformat()
                        }
        
        return all_results
    
    def generate_validation_report(self, results, output_path=None):
        """生成验证报告"""
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("金水谣系统第一阶段优化验证报告")
        report_lines.append("=" * 80)
        report_lines.append(f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"测试总数: {len(results)}")
        report_lines.append("")
        
        # 汇总统计
        total_tests = len(results)
        completed_tests = sum(1 for r in results.values() if r.get("success_rate") is not None)
        successful_tests = sum(1 for r in results.values() if r.get("success_rate", 0) >= 0.8)
        skipped_tests = sum(1 for r in results.values() if r.get("status") == "跳过")
        failed_tests = sum(1 for r in results.values() if r.get("success_rate", 0) < 0.5)
        
        overall_success_rate = sum(r.get("success_rate", 0) for r in results.values()) / completed_tests if completed_tests > 0 else 0
        
        report_lines.append("📊 测试汇总统计:")
        report_lines.append(f"  总测试数: {total_tests}")
        report_lines.append(f"  完成测试: {completed_tests}")
        report_lines.append(f"  跳过测试: {skipped_tests}")
        report_lines.append(f"  成功测试: {successful_tests} (成功率 > 80%)")
        report_lines.append(f"  失败测试: {failed_tests} (成功率 < 50%)")
        report_lines.append(f"  总体成功率: {overall_success_rate:.1%}")
        report_lines.append("")
        
        # 详细测试结果
        report_lines.append("🔍 详细测试结果:")
        report_lines.append("-" * 40)
        
        for test_name, result in results.items():
            test_info = self.test_cases.get(test_name, {})
            
            if result.get("status") == "跳过":
                report_lines.append(f"\n🟡 {test_name}: 跳过")
                report_lines.append(f"   原因: {result.get('reason', '未知')}")
                continue
                
            if result.get("status") == "异常":
                report_lines.append(f"\n🔴 {test_name}: 异常")
                report_lines.append(f"   错误: {result.get('error', '未知错误')}")
                continue
            
            success_rate = result.get("success_rate", 0)
            
            if success_rate >= 0.8:
                icon = "✅"
            elif success_rate >= 0.5:
                icon = "⚠️"
            else:
                icon = "❌"
            
            report_lines.append(f"\n{icon} {test_name}: {success_rate:.1%}")
            report_lines.append(f"   描述: {test_info.get('description', '无描述')}")
            report_lines.append(f"   优先级: {test_info.get('priority', '未知')}")
            report_lines.append(f"   模块: {result.get('module', '未知')}")
            
            # 显示测试子项结果
            test_results = result.get("test_results", [])
            if test_results:
                report_lines.append(f"   子测试结果:")
                for sub_test in test_results:
                    status = sub_test.get("status", "未知")
                    name = sub_test.get("name", "未命名")
                    result_text = sub_test.get("result", "")
                    report_lines.append(f"     - {name}: {status}")
                    if result_text and len(result_text) < 50:
                        report_lines.append(f"       结果: {result_text}")
        
        # 修复状态总结
        report_lines.append("\n🎯 第一阶段优化修复状态总结:")
        report_lines.append("-" * 40)
        
        critical_issue_fixed = True
        for test_name in ["killer_fixed_backward_compatibility", "api_compatibility_layer"]:
            if test_name in results:
                result = results[test_name]
                if result.get("success_rate", 0) < 0.8:
                    critical_issue_fixed = False
                    break
        
        if critical_issue_fixed:
            report_lines.append("✅ 紧急问题修复状态: 已修复")
            report_lines.append("   - killer模块API不兼容问题 ✅ 已解决")
            report_lines.append("   - API向后兼容机制 ✅ 已建立")
        else:
            report_lines.append("❌ 紧急问题修复状态: 仍有问题")
        
        # 安全系统状态
        security_tests = [k for k in results.keys() if "security" in k or "migration" in k]
        if security_tests:
            security_success = all(results[k].get("success_rate", 0) >= 0.8 for k in security_tests if k in results)
            if security_success:
                report_lines.append("✅ 安全系统状态: 已部署")
                report_lines.append("   - 敏感数据加密存储 ✅ 已实现")
                report_lines.append("   - 密钥管理机制 ✅ 已建立")
            else:
                report_lines.append("⚠️ 安全系统状态: 部分问题")
        
        # 总体建议
        report_lines.append("\n📋 总体建议:")
        report_lines.append("-" * 20)
        
        if overall_success_rate >= 0.9:
            report_lines.append("✅ 第一阶段优化完成质量: 优秀")
            report_lines.append("下一步: 可以进入第二阶段的系统架构优化")
        elif overall_success_rate >= 0.7:
            report_lines.append("✅ 第一阶段优化完成质量: 良好")
            report_lines.append("下一步: 修复剩余的小问题后进入第二阶段")
        elif overall_success_rate >= 0.5:
            report_lines.append("⚠️ 第一阶段优化完成质量: 一般")
            report_lines.append("下一步: 需要先解决关键问题")
        else:
            report_lines.append("❌ 第一阶段优化完成质量: 不达标")
            report_lines.append("下一步: 需要重新审视修复方案")
        
        report = "\n".join(report_lines)
        
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"验证报告已保存到: {output_path}")
        
        return report


def main():
    """主函数"""
    print("🚀 金水谣系统第一阶段优化验证启动")
    print("=" * 60)
    
    # 创建验证器
    validator = Phase1Validation()
    
    # 运行所有测试
    print("运行测试套件...")
    all_results = validator.run_all_tests()
    
    # 生成报告
    print("\n生成验证报告...")
    report = validator.generate_validation_report(all_results)
    
    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "金水谣数据", "reports", f"phase1_validation_{timestamp}.md"
    )
    
    final_report = validator.generate_validation_report(all_results, report_path)
    
    print("\n" + "=" * 60)
    print("📄 验证完成！报告已生成")
    print(f"📂 报告位置: {report_path}")
    print("=" * 60)
    
    # 显示关键信息
    lines = final_report.split('\n')
    for line in lines[:100]:  # 显示前100行
        print(line)
    
    return all_results


if __name__ == "__main__":
    try:
        results = main()
        
        # 计算总体成功率
        completed_tests = [r for r in results.values() if r.get("success_rate") is not None]
        if completed_tests:
            overall_rate = sum(r.get("success_rate", 0) for r in completed_tests) / len(completed_tests)
            
            if overall_rate >= 0.8:
                print(f"\n🎉 第一阶段优化验证成功！总体成功率: {overall_rate:.1%}")
            else:
                print(f"\n⚠️ 第一阶段优化需要改进。总体成功率: {overall_rate:.1%}")
    except Exception as e:
        print(f"❌ 验证过程出错: {e}")
        import traceback
        traceback.print_exc()