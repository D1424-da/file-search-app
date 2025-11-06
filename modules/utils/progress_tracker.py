#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
進捗トラッキング
リアルタイム進捗管理機能
"""

import time
import threading
from typing import Dict, Any


class ProgressTracker:
    """リアルタイム進捗トラッキング"""
    
    def __init__(self):
        self.reset()
        self._lock = threading.Lock()
        
    def reset(self):
        """進捗をリセット"""
        with getattr(self, '_lock', threading.Lock()):
            self.total_files = 0
            self.processed_files = 0
            self.successful_files = 0
            self.error_files = 0
            self.current_file = ""
            self.start_time = time.time()
            self.last_update_time = time.time()
            self.category_progress = {"light": 0, "medium": 0, "heavy": 0}
            self.category_totals = {"light": 0, "medium": 0, "heavy": 0}
            self.processing_speed = 0.0
            self.estimated_remaining_time = 0.0
            
    def set_total_files(self, total: int, category_breakdown: Dict[str, int] = None):
        """総ファイル数を設定"""
        with self._lock:
            self.total_files = total
            if category_breakdown:
                self.category_totals.update(category_breakdown)
                
    def update_progress(self, current_file: str = "", category: str = "", success: bool = True):
        """進捗を更新"""
        with self._lock:
            if success:
                self.successful_files += 1
            else:
                self.error_files += 1
                
            self.processed_files += 1
            if current_file:
                self.current_file = current_file
                
            if category:
                self.category_progress[category] = self.category_progress.get(category, 0) + 1
                
            # 処理速度計算
            current_time = time.time()
            elapsed = current_time - self.start_time
            if elapsed > 0:
                self.processing_speed = self.processed_files / elapsed
                
                # 残り時間推定
                remaining_files = self.total_files - self.processed_files
                if self.processing_speed > 0:
                    self.estimated_remaining_time = remaining_files / self.processing_speed
            
            self.last_update_time = current_time
            
    def get_progress_info(self) -> Dict[str, Any]:
        """進捗情報を取得"""
        with self._lock:
            progress_percent = (self.processed_files / self.total_files * 100) if self.total_files > 0 else 0
            
            return {
                'total_files': self.total_files,
                'processed_files': self.processed_files,
                'successful_files': self.successful_files,
                'error_files': self.error_files,
                'current_file': self.current_file,
                'progress_percent': progress_percent,
                'processing_speed': self.processing_speed,
                'estimated_remaining_time': self.estimated_remaining_time,
                'category_progress': self.category_progress.copy(),
                'category_totals': self.category_totals.copy(),
                'elapsed_time': time.time() - self.start_time
            }