#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
キャッシュ管理
3層キャッシュシステムの管理
"""

import os
import time
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..utils import setup_debug_logger, enhanced_search_match, normalize_search_text_ultra

# デバッグロガー
debug_logger = setup_debug_logger('CacheManager')


class CacheManager:
    """3層キャッシュ管理システム"""
    
    def __init__(self, project_root: str, max_immediate_cache: int = 150000, 
                 max_hot_cache: int = 1500000):
        self.project_root = Path(project_root)
        self.max_immediate_cache = max_immediate_cache
        self.max_hot_cache = max_hot_cache
        
        # 3層キャッシュ
        self.immediate_cache: Dict[str, Any] = {}  # 即座層 (揮発性)
        self.hot_cache: Dict[str, Any] = {}        # 高速層 (永続化)
        
        # 移動タイマー管理
        self._move_timers: List[threading.Timer] = []
        
        # シャットダウン管理
        self.shutdown_requested = False
        
    def add_to_immediate_cache(self, file_path: str, content: str, file_data: Dict[str, Any]):
        """即座層キャッシュに追加"""
        try:
            immediate_data = {
                'file_path': file_path,
                'file_name': file_data['file_name'],
                'content_preview': self._safe_truncate_utf8(content, 500),
                'file_type': file_data['file_type'],
                'size': file_data['size'],
                'indexed_time': time.time(),
                'layer': 'immediate'
            }

            self.immediate_cache[file_path] = immediate_data
            
            # キャッシュサイズ制限
            if len(self.immediate_cache) > self.max_immediate_cache:
                cleanup_count = max(1, self.max_immediate_cache // 10)
                sorted_items = sorted(self.immediate_cache.items(),
                                    key=lambda x: x[1]['indexed_time'])
                
                for i in range(cleanup_count):
                    if i < len(sorted_items):
                        oldest_key = sorted_items[i][0]
                        del self.immediate_cache[oldest_key]
            
            # 高速層移動タイマー設定
            timer = threading.Timer(1.0, self._move_to_hot_layer, args=[file_path, content])
            timer.start()
            self._move_timers.append(timer)
            
        except Exception as e:
            debug_logger.error(f"即座層追加エラー: {e}")
    
    def _move_to_hot_layer(self, file_path: str, content: str):
        """高速層移動"""
        try:
            if self.shutdown_requested:
                return
                
            # 即座層から削除
            base_data = self.immediate_cache.pop(file_path, None)
            if base_data is None:
                base_data = {
                    'file_name': os.path.basename(file_path),
                    'file_type': Path(file_path).suffix.lower(),
                    'size': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    'indexed_time': time.time()
                }

            # 高速層データ作成
            hot_data = base_data.copy()
            hot_data.update({
                'file_path': file_path,
                'content': content[:10000],
                'layer': 'hot',
                'moved_from_immediate': time.time()
            })

            self.hot_cache[file_path] = hot_data

            # キャッシュサイズ制限
            if len(self.hot_cache) > self.max_hot_cache:
                oldest_key = min(self.hot_cache.keys(),
                                 key=lambda k: self.hot_cache[k]['indexed_time'])
                del self.hot_cache[oldest_key]
            
        except Exception as e:
            debug_logger.error(f"高速層移動エラー: {e}")
    
    def search_immediate_layer(self, query: str) -> List[Dict[str, Any]]:
        """即座層検索"""
        results = []
        half_width, full_width, normalized, query_patterns = normalize_search_text_ultra(query)

        cache_items = list(self.immediate_cache.items())
        
        # 大量キャッシュ時は並列検索
        if len(cache_items) > 1000:
            def search_cache_chunk(chunk_items):
                chunk_results = []
                for key, data in chunk_items:
                    content_text = data.get('content_preview', data.get('content', '')) + ' ' + data.get('file_name', '')
                    if enhanced_search_match(content_text, query_patterns):
                        chunk_results.append({
                            'file_path': data['file_path'],
                            'file_name': data['file_name'],
                            'content_preview': content_text[:200],
                            'layer': 'immediate',
                            'relevance_score': 1.0
                        })
                return chunk_results

            # チャンクサイズを動的調整
            chunk_size = max(200, len(cache_items) // 8)
            chunks = [cache_items[i:i + chunk_size] for i in range(0, len(cache_items), chunk_size)]

            with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
                future_to_chunk = {executor.submit(search_cache_chunk, chunk): chunk for chunk in chunks}
                
                for future in as_completed(future_to_chunk):
                    try:
                        chunk_results = future.result(timeout=1.0)
                        results.extend(chunk_results)
                    except Exception as e:
                        debug_logger.warning(f"即座層並列検索エラー: {e}")
        else:
            # 小規模キャッシュは従来通り
            for key, data in cache_items:
                content_text = data.get('content_preview', data.get('content', '')) + ' ' + data.get('file_name', '')
                if enhanced_search_match(content_text, query_patterns):
                    results.append({
                        'file_path': data['file_path'],
                        'file_name': data['file_name'],
                        'content_preview': content_text[:200],
                        'layer': 'immediate',
                        'relevance_score': 1.0
                    })

        return sorted(results, key=lambda x: x['relevance_score'], reverse=True)
    
    def search_hot_layer(self, query: str) -> List[Dict[str, Any]]:
        """高速層検索"""
        results = []
        half_width, full_width, normalized, query_patterns = normalize_search_text_ultra(query)

        cache_items = list(self.hot_cache.items())
        
        # 大量キャッシュ時は並列検索
        if len(cache_items) > 5000:
            def search_cache_chunk(chunk_items):
                chunk_results = []
                for key, data in chunk_items:
                    content_text = data.get('content', '') + ' ' + data.get('file_name', '')
                    if enhanced_search_match(content_text, query_patterns):
                        chunk_results.append({
                            'file_path': data['file_path'],
                            'file_name': data['file_name'],
                            'content_preview': data['content'][:200],
                            'layer': 'hot',
                            'relevance_score': 0.8
                        })
                return chunk_results

            # チャンクサイズを動的調整
            chunk_size = max(500, len(cache_items) // 8)
            chunks = [cache_items[i:i + chunk_size] for i in range(0, len(cache_items), chunk_size)]

            with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
                future_to_chunk = {executor.submit(search_cache_chunk, chunk): chunk for chunk in chunks}
                
                for future in as_completed(future_to_chunk):
                    try:
                        chunk_results = future.result(timeout=1.5)
                        results.extend(chunk_results)
                    except Exception as e:
                        debug_logger.warning(f"高速層並列検索エラー: {e}")
        else:
            # 小規模キャッシュは従来通り
            for key, data in cache_items:
                content_text = data.get('content', '') + ' ' + data.get('file_name', '')
                if enhanced_search_match(content_text, query_patterns):
                    results.append({
                        'file_path': data['file_path'],
                        'file_name': data['file_name'],
                        'content_preview': data['content'][:200],
                        'layer': 'hot',
                        'relevance_score': 0.8
                    })

        return sorted(results, key=lambda x: x['relevance_score'], reverse=True)
    
    def save_caches(self):
        """キャッシュ永続化（高速層のみ）"""
        try:
            if self.shutdown_requested:
                return
                
            cache_dir = self.project_root / "cache"
            cache_dir.mkdir(exist_ok=True)
            
            # 高速層キャッシュのコピー作成
            try:
                hot_cache_copy = dict(self.hot_cache)
            except RuntimeError:
                debug_logger.warning("キャッシュコピー中にサイズ変更")
                return
            
            # 並列処理でキャッシュファイル保存
            def save_cache_file(cache_data, filename):
                try:
                    cache_file = cache_dir / filename
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(cache_data, f, ensure_ascii=False, indent=2)
                    return len(cache_data), filename
                except Exception as e:
                    debug_logger.error(f"キャッシュファイル保存エラー {filename}: {e}")
                    return 0, filename
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                future = executor.submit(save_cache_file, hot_cache_copy, "hot_cache.json")
                try:
                    count, filename = future.result(timeout=5.0)
                    debug_logger.info(f"キャッシュ保存完了: {filename} ({count}件)")
                except Exception as e:
                    debug_logger.error(f"キャッシュ保存エラー: {e}")
            
        except Exception as e:
            debug_logger.error(f"キャッシュ保存エラー: {e}")
    
    def load_caches(self):
        """キャッシュ復元（高速層のみ）"""
        try:
            cache_dir = self.project_root / "cache"
            
            # 即座層は常に空で開始
            self.immediate_cache = {}
            
            # 高速層キャッシュ読み込み
            def load_cache_file(filename):
                try:
                    cache_file = cache_dir / filename
                    if cache_file.exists():
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            return json.load(f), filename
                    return {}, filename
                except Exception as e:
                    debug_logger.error(f"キャッシュファイル読み込みエラー {filename}: {e}")
                    return {}, filename
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                future = executor.submit(load_cache_file, "hot_cache.json")
                try:
                    cache_data, filename = future.result(timeout=5.0)
                    if filename == "hot_cache.json":
                        loaded_hot_cache = cache_data
                except Exception as e:
                    debug_logger.error(f"キャッシュ読み込みエラー: {e}")
                    loaded_hot_cache = {}
            
            # 古いキャッシュエントリをクリーンアップ（7日以上古い）
            if loaded_hot_cache:
                def cleanup_cache_entry(items):
                    current_time = time.time()
                    cache_expiry_seconds = 7 * 24 * 3600
                    cleaned_items = {}
                    expired_count = 0
                    
                    for file_path, cache_data in items:
                        cache_time = cache_data.get('moved_from_immediate', 
                                                   cache_data.get('indexed_time', 0))
                        
                        if current_time - cache_time < cache_expiry_seconds:
                            cleaned_items[file_path] = cache_data
                        else:
                            expired_count += 1
                    
                    return cleaned_items, expired_count
                
                # キャッシュアイテムを分割して並列処理
                items = list(loaded_hot_cache.items())
                if items:
                    chunk_size = max(1, len(items) // 4)
                    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
                    
                    with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as executor:
                        futures = [executor.submit(cleanup_cache_entry, chunk) for chunk in chunks]
                        
                        cleaned_cache = {}
                        total_expired = 0
                        
                        for future in as_completed(futures):
                            try:
                                chunk_cleaned, chunk_expired = future.result(timeout=5.0)
                                cleaned_cache.update(chunk_cleaned)
                                total_expired += chunk_expired
                            except Exception as e:
                                debug_logger.error(f"キャッシュクリーンアップエラー: {e}")
                    
                    self.hot_cache = cleaned_cache
                    
                    if total_expired > 0:
                        debug_logger.info(f"高速層期限切れキャッシュクリーンアップ: {total_expired}件削除")
                else:
                    self.hot_cache = {}
            else:
                self.hot_cache = {}
            
            # 古い即座層キャッシュファイルがあれば削除
            immediate_cache_file = cache_dir / "immediate_cache.json"
            if immediate_cache_file.exists():
                immediate_cache_file.unlink()
            
            debug_logger.info(f"キャッシュ復元完了: immediate=0 (新規), hot={len(self.hot_cache)}")
            
        except Exception as e:
            debug_logger.error(f"キャッシュ復元エラー: {e}")
            self.immediate_cache = {}
            self.hot_cache = {}
    
    def clear_cache(self):
        """キャッシュクリア"""
        try:
            self.immediate_cache.clear()
            self.hot_cache.clear()
            
            # キャッシュファイルも削除
            cache_dir = self.project_root / "cache"
            if cache_dir.exists():
                cache_files = ["hot_cache.json", "immediate_cache.json"]
                for filename in cache_files:
                    cache_file = cache_dir / filename
                    if cache_file.exists():
                        cache_file.unlink()
            
            print("✅ キャッシュクリア完了")
            
        except Exception as e:
            debug_logger.error(f"キャッシュクリアエラー: {e}")
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """キャッシュ統計情報取得"""
        return {
            "immediate_layer": len(self.immediate_cache),
            "hot_layer": len(self.hot_cache),
            "immediate_size_mb": self._calculate_cache_size(self.immediate_cache),
            "hot_size_mb": self._calculate_cache_size(self.hot_cache)
        }
    
    def _calculate_cache_size(self, cache: Dict[str, Any]) -> float:
        """キャッシュサイズ計算（MB）"""
        try:
            total_size = 0
            for data in cache.values():
                content = data.get('content', '') or data.get('content_preview', '')
                total_size += len(str(content).encode('utf-8'))
            return total_size / (1024 * 1024)  # MB
        except:
            return 0.0
    
    def shutdown(self):
        """シャットダウン処理"""
        try:
            self.shutdown_requested = True
            
            # タイマーの停止
            for timer in self._move_timers:
                if timer.is_alive():
                    timer.cancel()
            self._move_timers.clear()
            
            # 最終キャッシュ保存
            self.save_caches()
            
        except Exception as e:
            debug_logger.error(f"キャッシュシャットダウンエラー: {e}")
    
    def _safe_truncate_utf8(self, text: str, max_length: int) -> str:
        """UTF-8文字列を安全に切り取る"""
        if not text or len(text) <= max_length:
            return text
        
        truncated = text[:max_length]
        
        try:
            truncated.encode('utf-8')
            return truncated
        except UnicodeEncodeError:
            for i in range(1, min(4, max_length) + 1):
                try:
                    safe_text = text[:max_length - i]
                    safe_text.encode('utf-8')
                    return safe_text
                except UnicodeEncodeError:
                    continue
            return ""