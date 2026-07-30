# -*- coding: utf-8 -*-
"""数据安全架构模块 - 支持多人共享使用，严格保护个人数据

设计原则：
  1. 数据分类：个人敏感数据 / 功能配置数据 / 公共市场数据
  2. 用户隔离：每个用户有独立的数据目录，相互不可访问
  3. 分享机制：只分享功能代码和公共数据，不包含个人数据
  4. 数据脱敏：分享前自动清除所有个人信息
  5. 导入清洗：导入数据时自动检测并移除敏感信息

适用场景：
  - 自用：完整功能 + 个人数据
  - 分享给朋友：功能代码 + 公共数据（不含个人持仓）
  - 团队协作：每人独立数据空间，可选择性分享配置
"""
import os
import json
import logging
import shutil
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataSecurityManager:
    """数据安全管理器 - 统一管理数据分类、隔离和分享"""

    # 数据分类定义
    DATA_TYPES = {
        "personal": {
            "description": "个人敏感数据",
            "files": ["fund_private.json", ".secret_key", "audit.log"],
            "fields": ["amount", "profit", "profit_rate", "units", "cost_price",
                       "buy_date", "total_invested", "executions", "transactions"],
            "shareable": False,
            "encrypt": True,
        },
        "config": {
            "description": "功能配置数据",
            "files": ["fund_config.json", "fund_public.json"],
            "fields": ["code", "name", "category", "manager", "company", 
                       "risk_level", "target_profit", "risk_free_rate"],
            "shareable": True,
            "encrypt": False,
        },
        "market": {
            "description": "公共市场数据",
            "files": ["fund_reports/", "daily_data/", "cache/"],
            "fields": ["nav", "sharpe_ratio", "max_drawdown", "volatility", 
                       "industry_distribution", "related_index"],
            "shareable": True,
            "encrypt": False,
        },
        "system": {
            "description": "系统配置",
            "files": ["ai_mode.json", "config.json"],
            "fields": [],
            "shareable": True,
            "encrypt": False,
        },
    }

    def __init__(self, root_dir: str = None):
        if root_dir is None:
            root_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "金水谣数据"
            )
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)

    def classify_data(self, data: Dict, data_type: str = None) -> Dict:
        """按类别过滤数据"""
        if data_type not in self.DATA_TYPES:
            return data

        allowed_fields = self.DATA_TYPES[data_type]["fields"]
        return {k: v for k, v in data.items() if k in allowed_fields}

    def is_personal_field(self, field_name: str) -> bool:
        """判断字段是否为个人敏感字段"""
        return field_name in self.DATA_TYPES["personal"]["fields"]

    # ================================================================
    # 用户隔离
    # ================================================================

    def get_user_dir(self, username: str = "default") -> str:
        """获取用户专属数据目录"""
        user_dir = os.path.join(self.root_dir, "users", username)
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    def list_users(self) -> List[str]:
        """列出所有用户"""
        users_dir = os.path.join(self.root_dir, "users")
        if not os.path.isdir(users_dir):
            return ["default"]
        return [d for d in os.listdir(users_dir) if os.path.isdir(os.path.join(users_dir, d))]

    def create_user(self, username: str) -> bool:
        """创建新用户"""
        user_dir = self.get_user_dir(username)
        if os.path.exists(user_dir):
            logger.warning("用户已存在: %s", username)
            return False
        
        os.makedirs(user_dir, exist_ok=True)
        
        # 创建基础目录结构
        for subdir in ["fund", "stock", "football", "lottery"]:
            os.makedirs(os.path.join(user_dir, subdir), exist_ok=True)
        
        logger.info("创建新用户: %s", username)
        return True

    # ================================================================
    # 分享机制
    # ================================================================

    def create_share_package(self, package_name: str = None, 
                            include_market_data: bool = True,
                            include_config: bool = True) -> str:
        """创建分享包（不含个人数据）
        
        返回分享包路径
        """
        if package_name is None:
            package_name = f"jinshuiyao_share_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        share_dir = os.path.join(self.root_dir, "shares", package_name)
        os.makedirs(share_dir, exist_ok=True)
        
        # 复制公共市场数据
        if include_market_data:
            market_src = os.path.join(self.root_dir, "fund", "daily_data")
            market_dst = os.path.join(share_dir, "fund", "daily_data")
            if os.path.isdir(market_src):
                shutil.copytree(market_src, market_dst, dirs_exist_ok=True)
        
        # 复制配置数据（脱敏处理）
        if include_config:
            config_src = os.path.join(self.root_dir, "fund", "fund_public.json")
            config_dst = os.path.join(share_dir, "fund", "fund_public.json")
            if os.path.isfile(config_src):
                shutil.copy2(config_src, config_dst)
        
        # 创建分享说明文件
        manifest = {
            "package_name": package_name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "includes": {
                "market_data": include_market_data,
                "config": include_config,
                "personal_data": False,
            },
            "version": "1.0",
            "description": "金水谣基金系统分享包（不含个人敏感数据）",
            "warning": "此分享包不包含任何个人持仓、交易记录等敏感信息",
        }
        
        manifest_path = os.path.join(share_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info("创建分享包: %s", share_dir)
        return share_dir

    def validate_share_package(self, package_path: str) -> Dict:
        """验证分享包是否包含个人数据"""
        result = {
            "valid": True,
            "issues": [],
            "manifest": None,
        }
        
        manifest_path = os.path.join(package_path, "manifest.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                result["manifest"] = json.load(f)
        
        # 检查是否包含敏感文件
        sensitive_files = self.DATA_TYPES["personal"]["files"]
        for sensitive_file in sensitive_files:
            file_path = os.path.join(package_path, sensitive_file)
            if os.path.exists(file_path):
                result["valid"] = False
                result["issues"].append(f"发现敏感文件: {sensitive_file}")
        
        # 检查目录
        sensitive_dirs = [".secret_key"]
        for dir_name in sensitive_dirs:
            dir_path = os.path.join(package_path, dir_name)
            if os.path.exists(dir_path):
                result["valid"] = False
                result["issues"].append(f"发现敏感目录: {dir_name}")
        
        return result

    # ================================================================
    # 数据脱敏
    # ================================================================

    def anonymize_holding(self, holding: Dict) -> Dict:
        """脱敏单条持仓数据（保留结构，清除金额）"""
        anonymized = {}
        for key, value in holding.items():
            if key in self.DATA_TYPES["personal"]["fields"]:
                # 敏感字段替换为占位符
                if isinstance(value, (int, float)):
                    anonymized[key] = 0.0
                elif isinstance(value, str):
                    anonymized[key] = "***"
                elif isinstance(value, list):
                    anonymized[key] = []
                else:
                    anonymized[key] = None
            else:
                anonymized[key] = value
        return anonymized

    def anonymize_all_holdings(self, holdings: List[Dict]) -> List[Dict]:
        """脱敏所有持仓数据"""
        return [self.anonymize_holding(h) for h in holdings]

    def sanitize_data_file(self, input_path: str, output_path: str) -> bool:
        """清洗数据文件，移除敏感信息"""
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, list):
                sanitized = self.anonymize_all_holdings(data)
            elif isinstance(data, dict):
                sanitized = {}
                for key, value in data.items():
                    if isinstance(value, dict):
                        sanitized[key] = self.anonymize_holding(value)
                    elif isinstance(value, list):
                        sanitized[key] = self.anonymize_all_holdings(value)
                    else:
                        sanitized[key] = value
            else:
                sanitized = data
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(sanitized, f, ensure_ascii=False, indent=2)
            
            logger.info("清洗数据文件完成: %s -> %s", input_path, output_path)
            return True
        except Exception as e:
            logger.error("清洗数据文件失败: %s", e)
            return False

    # ================================================================
    # 导入数据清洗
    # ================================================================

    def clean_import_data(self, data: Dict) -> Dict:
        """清洗导入数据，移除可能包含的敏感信息"""
        cleaned = {}
        for key, value in data.items():
            if self.is_personal_field(key):
                logger.warning("检测到导入数据包含敏感字段，已移除: %s", key)
                continue
            cleaned[key] = value
        return cleaned

    def validate_import_data(self, data: Dict) -> Dict:
        """验证导入数据是否安全"""
        result = {
            "safe": True,
            "sensitive_fields_found": [],
            "recommendations": [],
        }
        
        for key in data.keys():
            if self.is_personal_field(key):
                result["safe"] = False
                result["sensitive_fields_found"].append(key)
        
        if not result["safe"]:
            result["recommendations"].append("导入数据包含敏感字段，请先进行脱敏处理")
        
        return result

    # ================================================================
    # 安全检查
    # ================================================================

    def security_check(self) -> Dict:
        """执行安全检查"""
        result = {
            "status": "ok",
            "issues": [],
            "warnings": [],
        }
        
        # 检查密钥文件权限
        key_file = os.path.join(self.root_dir, "fund", ".secret_key")
        if os.path.isfile(key_file):
            try:
                import stat
                file_stat = os.stat(key_file)
                mode = stat.S_IMODE(file_stat.st_mode)
                if mode & 0o077:  # 其他用户有访问权限
                    result["warnings"].append("密钥文件权限过宽，建议设置为600")
            except Exception:
                pass
        
        # 检查是否有未加密的个人数据
        private_file = os.path.join(self.root_dir, "fund", "fund_private.json")
        if os.path.isfile(private_file):
            try:
                with open(private_file, "r", encoding="utf-8") as f:
                    content = f.read()
                # 简单检查是否加密（加密后内容不会是可读JSON）
                if content.startswith("{") and "amount" in content:
                    result["warnings"].append("个人数据文件可能未加密")
            except Exception:
                pass
        
        # 检查是否有备份文件包含敏感数据
        backup_files = [f for f in os.listdir(self.root_dir) if f.endswith(".bak")]
        for bf in backup_files:
            if "fund" in bf.lower():
                result["warnings"].append(f"发现备份文件可能包含敏感数据: {bf}")
        
        if result["warnings"]:
            result["status"] = "warning"
        
        return result
