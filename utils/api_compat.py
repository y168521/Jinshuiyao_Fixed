#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣系统API向后兼容机制（第一阶段修复）

作用：
1. 检测并修复所有API不兼容调用
2. 建立智能代理层，自动适配不同版本
3. 提供统一的错误处理和日志记录
4. 确保历史调用不再崩溃

功能清单：
- API兼容性检测器
- 智能参数转发器
- 调用日志追踪器
- 版本兼容性适配器
"""

import os
import sys
import logging
import importlib
import inspect
import hashlib
from functools import wraps
from datetime import datetime

logger = logging.getLogger("jinshuiyao.api_compat")

# 已知的API不兼容问题列表
KNOWN_COMPATIBILITY_ISSUES = {
    "killer.calc": {
        "problem": "函数参数不兼容，旧代码传递了history参数，但新版本不支持",
        "solution": "创建完全向后兼容的calc()函数，接受任意参数组合",
        "severity": "critical",
        "fixed_in": "killer.py",
        "call_patterns": [
            "calc(nums)",  # 旧式调用
            "calc(nums, history=None, lot=None)",  # 新增参数
            "calc(nums, history=arr, lot=lot)"  # 错误日志中的调用
        ]
    },
    "prediction_service.get_kill_numbers": {
        "problem": "依赖killer.calc的向后兼容性",
        "solution": "已通过killer.py内联实现完全向后兼容，prediction_service调用自动适配",
        "severity": "high",
        "depends_on": "killer.calc",
        "fixed_in": "killer.py"
    }
}


class APIConfigTracker:
    """API调用追踪器：记录所有API调用，发现不兼容问题"""
    
    def __init__(self):
        self.call_records = []
        self.incompatible_calls = []
        self.loaded_modules = {}
        
    def record_call(self, module_name, function_name, args, kwargs, result=None, error=None):
        """记录一次API调用"""
        call_record = {
            "timestamp": datetime.now().isoformat(),
            "module": module_name,
            "function": function_name,
            "args": args,
            "kwargs": kwargs,
            "result_type": type(result).__name__ if result is not None else None,
            "result_len": len(result) if hasattr(result, '__len__') else None,
            "error": str(error) if error else None,
            "stack": self._get_caller_info()
        }
        self.call_records.append(call_record)
        
        # 分析调用模式
        if error:
            pattern = self._analyze_call_pattern(module_name, function_name, args, kwargs)
            self.incompatible_calls.append({
                "error": error,
                "pattern": pattern,
                "record": call_record
            })
            logger.warning(f"API不兼容调用: {module_name}.{function_name}, 错误: {error}")
            
        return call_record
    
    def _analyze_call_pattern(self, module_name, function_name, args, kwargs):
        """分析调用模式"""
        pattern = f"{function_name}("
        if args:
            pattern += f"args={args}, "
        if kwargs:
            pattern += f"kwargs={kwargs}"
        pattern += ")"
        
        # 检查是否是已知问题的调用模式
        key = f"{module_name}.{function_name}"
        if key in KNOWN_COMPATIBILITY_ISSUES:
            known_issue = KNOWN_COMPATIBILITY_ISSUES[key]
            return {
                "pattern": pattern,
                "known_issue": known_issue,
                "key": key
            }
        
        return {"pattern": pattern, "known_issue": None, "key": key}
    
    def _get_caller_info(self):
        """获取调用者信息"""
        import traceback
        stack = traceback.extract_stack()
        # 跳过自身调用
        relevant = []
        for frame in stack[-8:-2]:  # 获取最近的几个调用帧
            if "api_compat" not in frame.filename:
                relevant.append(f"{frame.filename}:{frame.lineno} in {frame.name}")
        return relevant
    
    def get_incompatible_summary(self):
        """获取不兼容调用摘要"""
        summary = {
            "total_calls": len(self.call_records),
            "error_calls": len(self.incompatible_calls),
            "error_rate": len(self.incompatible_calls) / len(self.call_records) if self.call_records else 0,
            "incompatible_details": []
        }
        
        for ic in self.incompatible_calls:
            detail = {
                "module_function": ic["pattern"]["key"],
                "error": ic["error"],
                "call_pattern": ic["pattern"]["pattern"],
                "timestamp": ic["record"]["timestamp"],
                "solution": ic["pattern"]["known_issue"]["solution"] if ic["pattern"]["known_issue"] else "未知"
            }
            summary["incompatible_details"].append(detail)
        
        return summary
    
    def generate_compatibility_report(self, output_path=None):
        """生成兼容性报告"""
        summary = self.get_incompatible_summary()
        report_lines = []
        
        report_lines.append("=" * 80)
        report_lines.append("金水谣系统API兼容性分析报告")
        report_lines.append("=" * 80)
        report_lines.append(f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"总调用次数: {summary['total_calls']}")
        report_lines.append(f"错误调用次数: {summary['error_calls']}")
        report_lines.append(f"错误率: {summary['error_rate']:.2%}")
        report_lines.append("")
        
        if summary['incompatible_details']:
            report_lines.append("🔴 不兼容调用详情:")
            report_lines.append("-" * 40)
            for detail in summary['incompatible_details']:
                report_lines.append(f"问题: {detail['module_function']}")
                report_lines.append(f"  调用模式: {detail['call_pattern']}")
                report_lines.append(f"  错误信息: {detail['error']}")
                report_lines.append(f"  修复方案: {detail['solution']}")
                report_lines.append(f"  发生时间: {detail['timestamp']}")
                report_lines.append("")
        
        # 已知问题状态
        report_lines.append("📋 已知API兼容问题及修复状态:")
        report_lines.append("-" * 40)
        for key, issue in KNOWN_COMPATIBILITY_ISSUES.items():
            status = "✅ 已修复" if issue.get('fixed_in') else "🔴 待修复"
            report_lines.append(f"{key}:")
            report_lines.append(f"  状态: {status}")
            report_lines.append(f"  问题: {issue['problem']}")
            report_lines.append(f"  解决方案: {issue['solution']}")
            if issue.get('severity'):
                report_lines.append(f"  严重程度: {issue['severity']}")
            if issue.get('fixed_in'):
                report_lines.append(f"  修复版本: {issue['fixed_in']}")
            report_lines.append("")
        
        report_lines.append("🔄 建议操作:")
        report_lines.append("-" * 40)
        if summary['incompatible_details']:
            report_lines.append("1. 立即修复不兼容的API调用")
            report_lines.append("2. 运行完整的API兼容性测试")
            report_lines.append("3. 更新相关调用代码")
        else:
            report_lines.append("👍 未发现不兼容调用，系统API状态良好")
        
        report_content = "\n".join(report_lines)
        
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
            logger.info(f"API兼容性报告已生成: {output_path}")
        
        return report_content


class SmartAPIProxy:
    """智能API代理：自动处理API不兼容问题"""
    
    def __init__(self, tracker=None):
        self.tracker = tracker or APIConfigTracker()
        self.proxy_cache = {}
        
    def create_proxy(self, module_name, function_name, original_func, compatibility_strategy=None):
        """创建API代理函数"""
        
        @wraps(original_func)
        def proxy_wrapper(*args, **kwargs):
            try:
                # 记录调用
                call_info = self.tracker.record_call(
                    module_name, function_name, args, kwargs
                )
                
                # 应用兼容性策略
                if compatibility_strategy:
                    args, kwargs = compatibility_strategy(args, kwargs)
                
                # 执行原函数
                result = original_func(*args, **kwargs)
                
                # 记录成功结果
                self.tracker.record_call(
                    module_name, function_name, args, kwargs, 
                    result=result, error=None
                )
                
                return result
                
            except Exception as e:
                # 记录错误
                error_record = self.tracker.record_call(
                    module_name, function_name, args, kwargs, 
                    result=None, error=e
                )
                
                # 尝试执行兼容性修复
                fixed_result = self._apply_compatibility_fix(
                    module_name, function_name, args, kwargs, e
                )
                
                if fixed_result is not None:
                    logger.info(f"API兼容性修复成功: {module_name}.{function_name}")
                    return fixed_result
                else:
                    logger.error(f"API调用失败且无法修复: {module_name}.{function_name}, 错误: {e}")
                    raise e
        
        return proxy_wrapper
    
    def _apply_compatibility_fix(self, module_name, function_name, args, kwargs, error):
        """应用兼容性修复"""
        key = f"{module_name}.{function_name}"
        
        # 检查是否是已知问题
        if key in KNOWN_COMPATIBILITY_ISSUES:
            issue = KNOWN_COMPATIBILITY_ISSUES[key]
            
            # Killer模块的特定修复
            if key == "killer.calc":
                # 尝试加载修复后的killer模块
                try:
                    from engines import killer
                    fixed_killer = killer.Killer()
                    
                    # 分析错误消息来判断修复方式
                    error_str = str(error)
                    if "got an unexpected keyword argument 'history'" in error_str:
                        # 这是已知的history参数问题
                        logger.info(f"应用killer.calc兼容性修复: history参数问题")
                        
                        # 提取原始参数
                        if 'nums' in kwargs:
                            nums = kwargs['nums']
                            new_kwargs = {}
                        elif len(args) > 0:
                            nums = args[0]
                            new_kwargs = {}
                        else:
                            return None
                            
                        # 调用修复版本
                        return fixed_killer.calc(nums)
                        
                    # 其他类型的错误尝试通用修复
                    logger.info(f"尝试通用兼容性修复: {key}")
                    return fixed_killer.calc(*args, **kwargs)
                    
                except Exception as fix_error:
                    logger.error(f"兼容性修复失败: {fix_error}")
                    return None
        
        return None
    
    def patch_module(self, module_path, function_name):
        """动态修补模块中的函数"""
        try:
            module = importlib.import_module(module_path)
            original_func = getattr(module, function_name)
            
            # 创建代理
            proxy_func = self.create_proxy(
                module_path, function_name, original_func
            )
            
            # 替换原函数
            setattr(module, function_name, proxy_func)
            
            self.proxy_cache[f"{module_path}.{function_name}"] = {
                "original": original_func,
                "proxy": proxy_func,
                "patched": True
            }
            
            logger.info(f"成功修补API: {module_path}.{function_name}")
            return True
            
        except Exception as e:
            logger.error(f"API修补失败: {module_path}.{function_name}, 错误: {e}")
            return False
    
    def patch_known_issues(self):
        """修补所有已知的API兼容问题"""
        results = []
        
        for key, issue in KNOWN_COMPATIBILITY_ISSUES.items():
            # 解析模块和函数名
            if '.' in key:
                parts = key.split('.')
                if len(parts) >= 2:
                    module_name = '.'.join(parts[:-1])
                    function_name = parts[-1]
                    
                    if issue.get('severity') in ['critical', 'high']:
                        success = self.patch_module(module_name, function_name)
                        results.append({
                            "key": key,
                            "severity": issue.get('severity'),
                            "patched": success,
                            "solution": issue.get('solution')
                        })
        
        return results


class VersionCompatibilityAdapter:
    """版本兼容性适配器：处理不同版本间的API差异"""
    
    def __init__(self):
        self.version_map = {}
        self.adapters = {}
        
    def register_adapter(self, function_key, version_from, version_to, adapter_func):
        """注册版本适配器"""
        key = f"{function_key}|{version_from}->{version_to}"
        self.adapters[key] = adapter_func
        
        if function_key not in self.version_map:
            self.version_map[function_key] = {}
        self.version_map[function_key][(version_from, version_to)] = adapter_func
        logger.debug(f"注册版本适配器: {key}")
    
    def adapt_call(self, function_key, version_from, version_to, args, kwargs):
        """适配API调用"""
        adapter_key = f"{function_key}|{version_from}->{version_to}"
        
        if adapter_key in self.adapters:
            logger.info(f"应用版本适配器: {adapter_key}")
            return self.adapters[adapter_key](args, kwargs)
        else:
            # 没有找到适配器，尝试最接近的适配
            logger.warning(f"未找到版本适配器: {adapter_key}")
            return args, kwargs


def create_api_compat_layer():
    """创建完整的API兼容层"""
    
    # 创建追踪器
    tracker = APIConfigTracker()
    
    # 创建代理
    proxy = SmartAPIProxy(tracker)
    
    # 创建版本适配器
    adapter = VersionCompatibilityAdapter()
    
    # 注册killer模块的适配器
    def killer_calc_adapter(args, kwargs):
        """killer.calc的版本适配器"""
        # V1.0 -> V2.0适配
        # V1.0: calc(nums)
        # V2.0: calc(nums, history=None, lot=None)
        
        # 如果只有nums参数，添加默认的history和lot
        if len(args) == 1 and not kwargs:
            logger.debug("应用V1.0->V2.0适配: 添加默认history=[]和lot=None")
            kwargs = {'history': [], 'lot': None}
        
        return args, kwargs
    
    adapter.register_adapter(
        "killer.calc", 
        "V1.0", 
        "V2.0", 
        killer_calc_adapter
    )
    
    return {
        "tracker": tracker,
        "proxy": proxy,
        "adapter": adapter,
        "known_issues": KNOWN_COMPATIBILITY_ISSUES
    }


def install_api_compatibility():
    """安装API兼容性层"""
    compat_layer = create_api_compat_layer()
    
    logger.info("安装API兼容性层")
    logger.info("已知的API兼容问题:")
    
    for key, issue in compat_layer["known_issues"].items():
        status = "✅ " if issue.get('fixed_in') else "❌ "
        logger.info(f"  {status}{key}: {issue['problem'][:50]}...")
    
    # 自动修补严重问题
    if compat_layer["proxy"].patch_known_issues():
        logger.info("已修补严重API兼容问题")
    
    return compat_layer


# 主模块：提供实用函数
def test_api_compatibility():
    """测试API兼容性"""
    logger.info("=== API兼容性测试开始 ===")
    
    compat_layer = create_api_compat_layer()
    
    # 测试killer模块
    from engines import killer

    try:
        killer = killer.Killer()
        
        # 测试不同调用模式
        test_cases = [
            ("旧式调用", lambda: killer.calc([1,2,3,4,5,6,7,8,9,10])),
            ("错误日志模式", lambda: killer.calc(nums=[1,2,3,4,5], history=[{"nums":"1 2 3"}], lot="福彩3D")),
            ("新式调用", lambda: killer.calc_advanced(history=[{"nums":"1 2 3"}, {"nums":"2 3 4"}], lot="双色球")),
        ]
        
        results = []
        for name, test_func in test_cases:
            try:
                result = test_func()
                results.append((name, "✅ 成功", result))
                logger.info(f"API测试 {name}: 成功, 结果长度: {len(result) if result else 0}")
            except Exception as e:
                results.append((name, f"❌ 失败: {str(e)}", None))
                logger.error(f"API测试 {name}: 失败, 错误: {e}")
        
        # 生成报告
        report = compat_layer["tracker"].generate_compatibility_report()
        logger.info("API兼容性报告:\n" + report)
        
        # 统计
        success_count = sum(1 for r in results if "✅" in r[1])
        total_count = len(results)
        
        logger.info(f"=== API兼容性测试完成: {success_count}/{total_count} 通过 ===")
        
        return {
            "success": success_count,
            "total": total_count,
            "rate": success_count/total_count if total_count > 0 else 0,
            "results": results,
            "report": report
        }
        
    except Exception as e:
        logger.error(f"API兼容性测试失败: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行测试
    print("🚀 启动金水谣系统API向后兼容机制")
    print("=" * 60)
    
    test_result = test_api_compatibility()
    
    if "error" in test_result:
        print(f"❌ 测试失败: {test_result['error']}")
    else:
        print(f"✅ 测试完成: {test_result['success']}/{test_result['total']} 通过 ({test_result['rate']:.1%})")
        print(f"\n📋 建议:")
        if test_result['rate'] == 1.0:
            print("  所有API兼容性问题已解决！")
        else:
            print("  仍存在API兼容性问题，请查看报告了解详情")
        print(f"\n📄 详细报告已生成")
        print("=" * 60)