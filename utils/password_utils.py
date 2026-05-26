"""
密码加密工具
使用 bcrypt 加密存储密码
"""

from passlib.hash import bcrypt
from typing import Optional


def hash_password(password: str) -> str:
    """
    加密密码
    
    Args:
        password: 明文密码
        
    Returns:
        加密后的密码哈希
    """
    return bcrypt.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    验证密码
    
    Args:
        password: 明文密码
        hashed: 加密后的密码哈希
        
    Returns:
        验证是否通过
    """
    try:
        return bcrypt.verify(password, hashed)
    except Exception:
        return False


def is_hashed(password: str) -> bool:
    """
    判断密码是否已加密
    
    Args:
        password: 密码字符串
        
    Returns:
        是否已加密
    """
    # bcrypt 哈希以 $2 开头
    return password.startswith('$2')
