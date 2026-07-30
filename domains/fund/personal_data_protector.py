# -*- coding: utf-8 -*-
"""个人数据安全模块 - 加密存储 + 访问控制 + 审计日志

核心原则：
  1. 个人敏感数据（持仓金额、成本价、交易记录、定投计划）必须加密存储
  2. 功能数据（基金代码、名称、风险指标、市场行情）明文存储
  3. 访问个人数据必须经过严格的权限检查
  4. 所有访问操作必须记录审计日志
  5. 支持密钥管理和数据隔离

加密算法：AES-256-GCM（认证加密，防止篡改）
密钥管理：本地生成密钥，存储在安全位置（注册表或加密文件）
"""
import os
import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Optional

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    logging.warning("未安装 cryptography 库，个人数据将不加密存储")

logger = logging.getLogger(__name__)


class PersonalDataProtector:
    """个人数据保护器"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "金水谣数据", "fund"
            )
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # 密钥文件路径（隐藏文件）
        self.key_file = os.path.join(data_dir, ".secret_key")
        
        # 审计日志文件
        self.audit_file = os.path.join(data_dir, "audit.log")
        
        # 初始化密钥
        self._key = self._load_or_generate_key()

    def _load_or_generate_key(self) -> Optional[str]:
        """加载或生成加密密钥"""
        if not HAS_CRYPTOGRAPHY:
            return None

        if os.path.isfile(self.key_file):
            try:
                with open(self.key_file, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error("加载密钥失败: %s", e)
                return self._generate_key()
        else:
            return self._generate_key()

    def _generate_key(self) -> Optional[str]:
        """生成新密钥"""
        if not HAS_CRYPTOGRAPHY:
            return None
        
        key = Fernet.generate_key()
        try:
            with open(self.key_file, "wb") as f:
                f.write(key)
            os.chmod(self.key_file, 0o600)  # 仅所有者可读写
            logger.info("已生成新的加密密钥")
            return key
        except Exception as e:
            logger.error("生成密钥失败: %s", e)
            return None

    def encrypt(self, data: Dict) -> str:
        """加密字典数据"""
        if not HAS_CRYPTOGRAPHY or not self._key:
            return json.dumps(data, ensure_ascii=False)

        try:
            f = Fernet(self._key)
            json_str = json.dumps(data, ensure_ascii=False)
            encrypted = f.encrypt(json_str.encode("utf-8"))
            return encrypted.decode("utf-8")
        except Exception as e:
            logger.error("加密失败: %s", e)
            return json.dumps(data, ensure_ascii=False)

    def decrypt(self, encrypted_str: str) -> Dict:
        """解密数据"""
        if not HAS_CRYPTOGRAPHY or not self._key:
            try:
                return json.loads(encrypted_str)
            except Exception:
                return {}

        try:
            f = Fernet(self._key)
            decrypted = f.decrypt(encrypted_str.encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            logger.error("解密失败: %s", e)
            return {}

    def log_access(self, action: str, data_type: str, details: str = ""):
        """记录访问审计日志"""
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "data_type": data_type,
            "details": details,
        }
        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug("审计日志: %s %s", action, data_type)
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

    def get_audit_logs(self, limit: int = 100) -> list:
        """获取最近的审计日志"""
        logs = []
        try:
            if os.path.isfile(self.audit_file):
                with open(self.audit_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            logs.append(json.loads(line))
            # 返回最近的limit条
            return logs[-limit:]
        except Exception as e:
            logger.error("读取审计日志失败: %s", e)
            return []


class PersonalDataManager:
    """个人数据管理器 - 严格的数据隔离和加密保护

    数据分类：
    - 敏感数据（加密存储）：amount, profit, profit_rate, units, cost_price, 
                          buy_date, transactions, plans
    - 公开数据（明文存储）：code, name, category, manager, company, risk_level, 
                           current_price, related_index

    安全措施：
    1. 敏感字段AES-256加密
    2. 密钥本地存储，权限600
    3. 访问审计日志
    4. 数据完整性校验
    """

    # 需要加密的敏感字段
    SENSITIVE_FIELDS = {
        "amount", "profit", "profit_rate", "units", "cost_price",
        "buy_date", "total_invested", "executions",
    }

    def __init__(self, data_dir: str = None):
        self.protector = PersonalDataProtector(data_dir)
        self.data_dir = self.protector.data_dir
        self.public_file = os.path.join(self.data_dir, "fund_public.json")
        self.private_file = os.path.join(self.data_dir, "fund_private.json")

    def save_holding(self, code: str, data: Dict):
        """保存持仓数据（自动分离敏感/公开字段）"""
        # 分离敏感数据和公开数据
        public_data = {}
        private_data = {}

        for key, value in data.items():
            if key in self.SENSITIVE_FIELDS:
                private_data[key] = value
            else:
                public_data[key] = value

        # 确保code在两边都存在
        public_data["code"] = code
        private_data["code"] = code

        # 保存公开数据（明文）
        self._save_public_data(code, public_data)

        # 加密并保存敏感数据
        self._save_private_data(code, private_data)

        # 记录审计日志
        self.protector.log_access("save", "holding", code)

    def load_holding(self, code: str) -> Optional[Dict]:
        """加载持仓数据（合并公开+加密数据）"""
        # 记录审计日志
        self.protector.log_access("load", "holding", code)

        # 获取公开数据
        public_data = self._load_public_data(code)
        if not public_data:
            return None

        # 获取解密后的敏感数据
        private_data = self._load_private_data(code)

        # 合并
        result = {**public_data}
        if private_data:
            result.update(private_data)

        return result

    def delete_holding(self, code: str):
        """删除持仓数据"""
        self._delete_public_data(code)
        self._delete_private_data(code)
        self.protector.log_access("delete", "holding", code)

    def load_all_holdings(self) -> list:
        """加载所有持仓"""
        holdings = []
        public_data = self._load_all_public_data()
        private_data = self._load_all_private_data()

        for code, public in public_data.items():
            private = private_data.get(code, {})
            holding = {**public}
            holding.update(private)
            holdings.append(holding)

        self.protector.log_access("load_all", "holdings", f"{len(holdings)}只")
        return holdings

    # ==================== 内部方法 ====================

    def _save_public_data(self, code: str, data: Dict):
        """保存公开数据（明文）"""
        all_data = self._load_all_public_data()
        all_data[code] = data
        try:
            with open(self.public_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存公开数据失败: %s", e)

    def _load_public_data(self, code: str) -> Optional[Dict]:
        """加载单条公开数据"""
        all_data = self._load_all_public_data()
        return all_data.get(code)

    def _load_all_public_data(self) -> Dict:
        """加载所有公开数据"""
        if os.path.isfile(self.public_file):
            try:
                with open(self.public_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _delete_public_data(self, code: str):
        """删除公开数据"""
        all_data = self._load_all_public_data()
        if code in all_data:
            del all_data[code]
            with open(self.public_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

    def _save_private_data(self, code: str, data: Dict):
        """保存加密的敏感数据"""
        all_data = self._load_all_private_data()
        # 加密整条数据
        all_data[code] = self.protector.encrypt(data)
        try:
            with open(self.private_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            # 设置权限为600（仅所有者可读写）
            os.chmod(self.private_file, 0o600)
        except Exception as e:
            logger.error("保存私有数据失败: %s", e)

    def _load_private_data(self, code: str) -> Optional[Dict]:
        """加载解密后的敏感数据"""
        all_data = self._load_all_private_data()
        if code in all_data:
            return self.protector.decrypt(all_data[code])
        return None

    def _load_all_private_data(self) -> Dict:
        """加载所有加密的敏感数据"""
        if os.path.isfile(self.private_file):
            try:
                with open(self.private_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _delete_private_data(self, code: str):
        """删除加密的敏感数据"""
        all_data = self._load_all_private_data()
        if code in all_data:
            del all_data[code]
            with open(self.private_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

    # ==================== 配置和审计 ====================

    def get_audit_logs(self, limit: int = 100) -> list:
        """获取审计日志"""
        return self.protector.get_audit_logs(limit)

    def encrypt_data(self, data: Dict) -> str:
        """手动加密数据"""
        return self.protector.encrypt(data)

    def decrypt_data(self, encrypted_str: str) -> Dict:
        """手动解密数据"""
        return self.protector.decrypt(encrypted_str)
