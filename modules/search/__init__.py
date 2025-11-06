#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
検索システムモジュール

3層統合検索システム（即座層・高速層・完全層）の管理
"""

from .search_system import UltraFastFullCompliantSearchSystem
from .database_manager import DatabaseManager
from .cache_manager import CacheManager

__version__ = "1.0.0"
__author__ = "File Search App Team"

__all__ = [
    'UltraFastFullCompliantSearchSystem',
    'DatabaseManager',
    'CacheManager'
]