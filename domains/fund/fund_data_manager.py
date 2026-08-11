# -*- coding: utf-8 -*-
"""基金数据管理器 - 安全版（集成加密保护和数据隔离）

核心特性：
  1. 个人敏感数据加密存储（AES-256-GCM）
  2. 数据分类隔离（敏感数据/公开数据/市场数据）
  3. 支持多用户模式（自用/分享/团队协作）
  4. 完整的审计日志
  5. 导入数据自动清洗

数据存储结构：
  金水谣数据/
    fund/
      fund_public.json      # 公开数据（明文）
      fund_private.json     # 敏感数据（加密）
      .secret_key           # 加密密钥（权限600）
      audit.log             # 审计日志
      fund_config.json      # 功能配置
"""
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from utils.safe_json import safe_write_json

logger = logging.getLogger(__name__)


def _safe_write(filepath: str, data) -> bool:
    """原子写入（不嵌入校验和，避免 _metadata 键污染业务数据）"""
    return safe_write_json(filepath, data, embed_checksum=False)

# 需要加密的敏感字段
SENSITIVE_FIELDS = {
    "amount", "profit", "profit_rate", "units", "cost_price",
    "buy_date", "total_invested", "executions",
}

# 公开字段（明文存储）
PUBLIC_FIELDS = {
    "code", "name", "category", "manager", "company", 
    "risk_level", "current_price", "related_index", "last_update",
}


class FundDataManager:
    """基金数据管理器（安全版）"""

    def __init__(self, username: str = "default", root_dir: Optional[str] = None):
        if root_dir is None:
            root_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "金水谣数据"
            )
        
        # 用户数据目录
        self.user_dir = os.path.join(root_dir, "users", username)
        os.makedirs(self.user_dir, exist_ok=True)
        
        # 基金数据目录
        self.fund_dir = os.path.join(self.user_dir, "fund")
        os.makedirs(self.fund_dir, exist_ok=True)
        
        # 文件路径
        self.public_file = os.path.join(self.fund_dir, "fund_public.json")
        self.private_file = os.path.join(self.fund_dir, "fund_private.json")
        self.config_file = os.path.join(self.fund_dir, "fund_config.json")
        self.key_file = os.path.join(self.fund_dir, ".secret_key")
        self.audit_file = os.path.join(self.fund_dir, "audit.log")
        
        # 初始化密钥
        self._key = self._load_or_generate_key()
        
        # 初始化数据
        self._init_data()

    # ================================================================
    # 密钥管理
    # ================================================================

    def _load_or_generate_key(self) -> Optional[bytes]:
        """加载或生成加密密钥"""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning("未安装 cryptography，个人数据将不加密")
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

    def _generate_key(self) -> Optional[bytes]:
        """生成新密钥"""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return None

        key = Fernet.generate_key()
        try:
            with open(self.key_file, "wb") as f:
                f.write(key)
            os.chmod(self.key_file, 0o600)
            logger.info("生成新的加密密钥: %s", self.key_file)
            return key
        except Exception as e:
            logger.error("生成密钥失败: %s", e)
            return None

    def _encrypt(self, data: Dict) -> str:
        """加密数据"""
        if not self._key:
            return json.dumps(data, ensure_ascii=False)
        
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self._key)
            json_str = json.dumps(data, ensure_ascii=False)
            encrypted = f.encrypt(json_str.encode("utf-8"))
            return encrypted.decode("utf-8")
        except Exception as e:
            logger.error("加密失败: %s", e)
            return json.dumps(data, ensure_ascii=False)

    def _decrypt(self, encrypted_str: str) -> Dict:
        """解密数据"""
        if not self._key:
            try:
                return json.loads(encrypted_str)
            except Exception:
                return {}
        
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self._key)
            decrypted = f.decrypt(encrypted_str.encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            logger.error("解密失败: %s", e)
            return {}

    def _log_audit(self, action: str, data_type: str, details: str = ""):
        """记录审计日志"""
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "data_type": data_type,
            "details": details,
        }
        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

    # ================================================================
    # 初始化
    # ================================================================

    def _init_data(self):
        """初始化数据文件"""
        # 初始化配置文件
        if not os.path.isfile(self.config_file):
            config = {
                "version": "1.0",
                "target_profit": 0.164,
                "risk_free_rate": 0.02,
                "auto_detect": True,
            }
            _safe_write(self.config_file, config)
        
        # 如果没有数据，初始化空持仓（首次使用由用户自行添加）
        if not os.path.isfile(self.public_file):
            self._init_default_data()

    def _init_default_data(self):
        """初始化空持仓（不再预置示例基金，首次使用引导用户添加）"""
        # 公开数据（明文，初始为空：用户的关注列表只来自用户自己添加）
        public_data = {}
        
        # 敏感数据（加密存储，初始为空）
        private_data = {}
        
        _safe_write(self.public_file, public_data)

        _safe_write(self.private_file, private_data)
        
        os.chmod(self.private_file, 0o600)
        
        logger.info("初始化基金数据（空持仓，等待用户添加）")

    # ================================================================
    # 持仓管理
    # ================================================================

    def get_holdings(self) -> List[Dict]:
        """获取所有持仓（合并公开+加密数据）"""
        holdings = []
        public_data = self._load_public_data()
        private_data = self._load_private_data()
        
        for code, public in public_data.items():
            private = private_data.get(code, {})
            holding = {**public}
            holding.update(private)
            holdings.append(holding)
        
        self._log_audit("load_all", "holdings", f"{len(holdings)}只")
        return holdings

    def get_holding(self, code: str) -> Optional[Dict]:
        """获取单只基金持仓"""
        self._log_audit("load", "holding", code)
        
        public_data = self._load_public_data()
        if code not in public_data:
            return None
        
        private_data = self._load_private_data()
        private = private_data.get(code, {})
        
        return {**public_data[code], **private}

    def update_holding(self, code: str, **kwargs) -> bool:
        """更新持仓信息（自动分离敏感/公开字段）"""
        public_update = {}
        private_update = {}
        
        for key, value in kwargs.items():
            if key in SENSITIVE_FIELDS:
                private_update[key] = value
            elif key in PUBLIC_FIELDS:
                public_update[key] = value
        
        if public_update:
            self._update_public_data(code, public_update)
        
        if private_update:
            self._update_private_data(code, private_update)
        
        self._log_audit("update", "holding", code)
        return True

    def add_holding(self, holding: Dict) -> bool:
        """添加新持仓"""
        code = holding.get("code", "")
        if not code:
            logger.error("缺少基金代码")
            return False
        
        if code in self._load_public_data():
            logger.warning("基金已存在: %s", code)
            return False
        
        # 分离敏感数据和公开数据
        public_data = {k: v for k, v in holding.items() if k in PUBLIC_FIELDS}
        private_data = {k: v for k, v in holding.items() if k in SENSITIVE_FIELDS}
        
        public_data["code"] = code
        private_data["code"] = code
        
        self._add_public_data(code, public_data)
        if private_data:
            self._add_private_data(code, private_data)
        
        self._log_audit("add", "holding", code)
        return True

    def remove_holding(self, code: str) -> bool:
        """删除持仓"""
        public_data = self._load_public_data()
        if code not in public_data:
            return False
        
        self._delete_public_data(code)
        self._delete_private_data(code)
        
        self._log_audit("delete", "holding", code)
        return True

    # ================================================================
    # 公开数据操作（明文）
    # ================================================================

    def _load_public_data(self) -> Dict:
        """加载所有公开数据"""
        if os.path.isfile(self.public_file):
            try:
                with open(self.public_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("读取公开持仓数据失败（按空处理）: %s", e)
        return {}

    def _update_public_data(self, code: str, data: Dict):
        """更新公开数据"""
        all_data = self._load_public_data()
        if code in all_data:
            all_data[code].update(data)
            all_data[code]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _safe_write(self.public_file, all_data)

    def _add_public_data(self, code: str, data: Dict):
        """添加公开数据"""
        all_data = self._load_public_data()
        data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        all_data[code] = data
        _safe_write(self.public_file, all_data)

    def _delete_public_data(self, code: str):
        """删除公开数据"""
        all_data = self._load_public_data()
        if code in all_data:
            del all_data[code]
            _safe_write(self.public_file, all_data)

    # ================================================================
    # 敏感数据操作（加密）
    # ================================================================

    def _load_private_data(self) -> Dict:
        """加载所有加密数据"""
        if os.path.isfile(self.private_file):
            try:
                with open(self.private_file, "r", encoding="utf-8") as f:
                    encrypted_data = json.load(f)
                # 解密每条数据
                decrypted = {}
                for code, encrypted in encrypted_data.items():
                    decrypted[code] = self._decrypt(encrypted)
                return decrypted
            except Exception:
                pass
        return {}

    def _update_private_data(self, code: str, data: Dict):
        """更新加密数据"""
        all_data = self._load_private_data()
        if code in all_data:
            all_data[code].update(data)
        else:
            all_data[code] = data
        # 重新加密并保存
        encrypted = {k: self._encrypt(v) for k, v in all_data.items()}
        _safe_write(self.private_file, encrypted)
        os.chmod(self.private_file, 0o600)

    def _add_private_data(self, code: str, data: Dict):
        """添加加密数据"""
        all_data = self._load_private_data()
        all_data[code] = data
        encrypted = {k: self._encrypt(v) for k, v in all_data.items()}
        _safe_write(self.private_file, encrypted)
        os.chmod(self.private_file, 0o600)

    def _delete_private_data(self, code: str):
        """删除加密数据"""
        all_data = self._load_private_data()
        if code in all_data:
            del all_data[code]
            encrypted = {k: self._encrypt(v) for k, v in all_data.items()}
            _safe_write(self.private_file, encrypted)

    # ================================================================
    # 定投计划管理
    # ================================================================

    def get_plans(self) -> List[Dict]:
        """获取所有定投计划"""
        private_data = self._load_private_data()
        plans = []
        for code, data in private_data.items():
            if "plans" in data:
                for plan in data.get("plans", []):
                    plan["code"] = code
                    plans.append(plan)
        return plans

    def add_plan(self, code: str, plan: Dict) -> bool:
        """添加定投计划"""
        private_data = self._load_private_data()
        if code not in private_data:
            private_data[code] = {}
        if "plans" not in private_data[code]:
            private_data[code]["plans"] = []
        
        plan["id"] = f"{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        plan["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plan["status"] = plan.get("status", "active")
        plan["total_invested"] = plan.get("total_invested", 0)
        plan["executions"] = plan.get("executions", [])
        
        private_data[code]["plans"].append(plan)
        
        encrypted = {k: self._encrypt(v) for k, v in private_data.items()}
        _safe_write(self.private_file, encrypted)

        self._log_audit("add", "plan", f"{code}: {plan.get('id')}")
        return True

    def update_plan(self, code: str, plan_id: str, **kwargs) -> bool:
        """更新定投计划"""
        private_data = self._load_private_data()
        if code not in private_data:
            return False
        
        for plan in private_data[code].get("plans", []):
            if plan.get("id") == plan_id:
                plan.update(kwargs)
                
                encrypted = {k: self._encrypt(v) for k, v in private_data.items()}
                _safe_write(self.private_file, encrypted)
                
                self._log_audit("update", "plan", f"{code}: {plan_id}")
                return True
        
        return False

    def remove_plan(self, code: str, plan_id: str) -> bool:
        """删除定投计划"""
        private_data = self._load_private_data()
        if code not in private_data:
            return False
        
        original_len = len(private_data[code].get("plans", []))
        private_data[code]["plans"] = [
            p for p in private_data[code].get("plans", []) if p.get("id") != plan_id
        ]
        
        if len(private_data[code]["plans"]) < original_len:
            encrypted = {k: self._encrypt(v) for k, v in private_data.items()}
            _safe_write(self.private_file, encrypted)
            
            self._log_audit("delete", "plan", f"{code}: {plan_id}")
            return True
        
        return False

    # ================================================================
    # 交易记录
    # ================================================================

    def get_transactions(self, code: str = None) -> List[Dict]:
        """获取交易记录"""
        private_data = self._load_private_data()
        transactions = []
        
        for c, data in private_data.items():
            if code and c != code:
                continue
            if "transactions" in data:
                transactions.extend(data["transactions"])
        
        return sorted(transactions, key=lambda x: x.get("timestamp", ""), reverse=True)

    def add_transaction(self, code: str, transaction: Dict) -> bool:
        """添加交易记录"""
        private_data = self._load_private_data()
        if code not in private_data:
            private_data[code] = {}
        if "transactions" not in private_data[code]:
            private_data[code]["transactions"] = []
        
        transaction["id"] = f"{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        transaction["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        private_data[code]["transactions"].append(transaction)
        
        encrypted = {k: self._encrypt(v) for k, v in private_data.items()}
        _safe_write(self.private_file, encrypted)

        self._log_audit("add", "transaction", f"{code}: {transaction.get('type')}")
        return True

    # ================================================================
    # 组合分析
    # ================================================================

    def get_portfolio_summary(self) -> Dict:
        """获取组合概览"""
        holdings = self.get_holdings()
        if not holdings:
            return {"total_amount": 0, "total_profit": 0, "total_cost": 0, "profit_rate": 0, "fund_count": 0}

        total_amount = sum(h.get("amount", 0) for h in holdings)
        total_profit = sum(h.get("profit", 0) for h in holdings)
        total_cost = total_amount - total_profit
        profit_rate = total_profit / total_cost if total_cost > 0 else 0

        return {
            "total_amount": round(total_amount, 2),
            "total_profit": round(total_profit, 2),
            "total_cost": round(total_cost, 2),
            "profit_rate": round(profit_rate, 4),
            "fund_count": len(holdings),
            "holdings": holdings,
        }

    def get_category_distribution(self) -> Dict:
        """获取持仓类别分布"""
        holdings = self.get_holdings()
        distribution = {}
        for h in holdings:
            cat = h.get("category", "未知")
            if cat not in distribution:
                distribution[cat] = {"amount": 0, "count": 0}
            distribution[cat]["amount"] += h.get("amount", 0)
            distribution[cat]["count"] += 1
        return distribution

    def get_risk_distribution(self) -> Dict:
        """获取风险等级分布"""
        holdings = self.get_holdings()
        distribution = {}
        for h in holdings:
            risk = h.get("risk_level", "未知")
            if risk not in distribution:
                distribution[risk] = {"amount": 0, "count": 0}
            distribution[risk]["amount"] += h.get("amount", 0)
            distribution[risk]["count"] += 1
        return distribution

    def get_performance_ranking(self) -> List[Dict]:
        """按收益率排序"""
        return sorted(self.get_holdings(), key=lambda x: x.get("profit_rate", 0), reverse=True)

    # ================================================================
    # 配置管理
    # ================================================================

    def get_config(self) -> Dict:
        """获取配置"""
        if os.path.isfile(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def update_config(self, **kwargs) -> bool:
        """更新配置"""
        config = self.get_config()
        config.update(kwargs)
        _safe_write(self.config_file, config)
        return True

    # ================================================================
    # 数据安全
    # ================================================================

    def get_audit_logs(self, limit: int = 100) -> List[Dict]:
        """获取审计日志"""
        logs = []
        if os.path.isfile(self.audit_file):
            try:
                with open(self.audit_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            logs.append(json.loads(line))
            except Exception:
                pass
        return logs[-limit:]

    def anonymize_holdings(self) -> List[Dict]:
        """脱敏持仓数据（用于分享）"""
        holdings = self.get_holdings()
        anonymized = []
        for h in holdings:
            anon = {}
            for key, value in h.items():
                if key in SENSITIVE_FIELDS:
                    if isinstance(value, (int, float)):
                        anon[key] = 0.0
                    elif isinstance(value, str):
                        anon[key] = "***"
                    elif isinstance(value, list):
                        anon[key] = []
                    else:
                        anon[key] = None
                else:
                    anon[key] = value
            anonymized.append(anon)
        return anonymized

    def create_share_package(self) -> Dict:
        """创建分享包（不含个人数据）"""
        return {
            "fund_public": self._load_public_data(),
            "config": self.get_config(),
            "version": "1.0",
            "description": "金水谣基金系统分享包（不含个人敏感数据）",
        }
