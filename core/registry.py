# -*- coding: utf-8 -*-
"""金水谣内核 - 域注册表

管理所有已注册的子系统（域），提供注册、查询、列表功能。
借鉴 OpenStack Stevedore 的 DriverManager 思想。
"""
import logging

logger = logging.getLogger(__name__)

# 已注册的子系统
_registered_domains = {}


def register(domain_id, domain_class, description=""):
    """注册一个子系统
    
    Args:
        domain_id: 子系统标识符（如 "lottery", "football"）
        domain_class: 子系统类（必须实现标准接口）
        description: 子系统描述
    """
    if domain_id in _registered_domains:
        logger.warning("子系统 %s 已存在，将被覆盖", domain_id)
    _registered_domains[domain_id] = {
        "class": domain_class,
        "description": description,
    }
    logger.info("子系统已注册: %s (%s)", domain_id, description or domain_class.__name__)


def get_domain(domain_id):
    """获取已注册的子系统类
    
    Args:
        domain_id: 子系统标识符
        
    Returns:
        子系统类，或 None
    """
    entry = _registered_domains.get(domain_id)
    if entry:
        return entry["class"]
    return None


def list_domains():
    """列出所有已注册的子系统
    
    Returns:
        list: [(domain_id, description), ...]
    """
    return [(did, entry["description"]) for did, entry in _registered_domains.items()]


def is_registered(domain_id):
    """检查子系统是否已注册"""
    return domain_id in _registered_domains
