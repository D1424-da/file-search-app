#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
検索システムコア
3層統合検索システムの中核部分
"""

import os
import time
import threading
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .database_manager import DatabaseManager
from .cache_manager import CacheManager
from ..extractors import FileContentExtractor
from ..utils import setup_debug_logger, enhanced_search_match, normalize_search_text_ultra

# デバッグロガー
debug_logger = setup_debug_logger('UltraFastSearchSystem')


class UltraFastFullCompliantSearchSystem:
    """3層統合検索システム（即座層・高速層・完全層）"""
    
    def __init__(self, project_root: str, db_count: int = 8, optimal_threads: int = 8):
        self.project_root = Path(project_root)
        self.db_count = db_count
        self.optimal_threads = optimal_threads
        
        # 統計情報
        self.stats = {
            "indexed_files": 0,
            "search_count": 0,
            "immediate_layer_hits": 0,
            "hot_layer_hits": 0,
            "complete_layer_hits": 0,
            "total_search_time": 0,
            "avg_search_time": 0,
            "error_count": 0,
            "optimization_count": 0
        }
        
        # 状態管理
        self.indexing_in_progress = False
        self.indexing_cancelled = False
        self.shutdown_requested = False
        
        # コンポーネント初期化
        self.database_manager = DatabaseManager(project_root, db_count)
        self.cache_manager = CacheManager(project_root)
        self.content_extractor = FileContentExtractor()
        
        # データベースパス（互換性のため）
        self.complete_db_paths = self.database_manager.complete_db_paths
        
        # キャッシュ参照（互換性のため）
        self.immediate_cache = self.cache_manager.immediate_cache
        self.hot_cache = self.cache_manager.hot_cache
        self.max_immediate_cache = self.cache_manager.max_immediate_cache
        
        # 初期化実行
        self.initialize_databases()
    
    def initialize_databases(self):
        """データベース初期化"""
        print("🗄️ 3層統合検索システム初期化中...")
        debug_logger.info("3層統合検索システム初期化開始")
        
        # データベース初期化
        self.database_manager.initialize_databases()
        
        # キャッシュ復元
        self.cache_manager.load_caches()
        
        print(f"✅ 3層統合検索システム初期化完了 (DB:{self.db_count}個, キャッシュ復元完了)")
        debug_logger.info("3層統合検索システム初期化完了")
    
    def ultra_fast_search(self, query: str, max_results: int = 5500) -> List[Dict[str, Any]]:
        """最適化済み検索メソッド - 3層検索システム"""
        if not query or not query.strip():
            return []

        query = query.strip()
        start_time = time.time()

        # 統計更新（軽量化）
        self.stats["search_count"] += 1

        try:
            # 第1層: 即座層検索（最優先キャッシュ）
            immediate_results = self._search_immediate_layer(query)
            if immediate_results:
                self.stats["immediate_layer_hits"] += 1
                self.stats["total_search_time"] += time.time() - start_time
                self._update_average_search_time()
                return immediate_results[:max_results]

            # 第2層: ホット層検索（一時キャッシュ）
            hot_results = self._search_hot_layer(query)
            if hot_results:
                self.stats["hot_layer_hits"] += 1
                self.stats["total_search_time"] += time.time() - start_time
                self._update_average_search_time()
                
                # 即座層にキャッシュ（非同期）
                threading.Timer(0.001, self._cache_search_results, args=[query, hot_results]).start()
                return hot_results[:max_results]

            # 第3層: 完全検索（データベース）
            complete_results = self._search_complete_layer(query, max_results)
            self.stats["complete_layer_hits"] += 1
            self.stats["total_search_time"] += time.time() - start_time
            self._update_average_search_time()

            # 結果をキャッシュに追加（非同期）
            if complete_results:
                threading.Timer(0.001, self._cache_search_results, args=[query, complete_results]).start()

            return complete_results

        except Exception as e:
            error_time = time.time() - start_time
            self.stats["error_count"] += 1
            self.stats["total_search_time"] += error_time
            debug_logger.error(f"検索エラー: {e} ({error_time:.3f}s)")
            print(f"⚠️ 検索エラー: {e}")
            return []
    
    def unified_three_layer_search(self,
                                   query: str,
                                   max_results: int = 5500,
                                   file_type_filter: str = "all") -> List[Dict[str, Any]]:
        """最適化済み3層統合検索 - パフォーマンス重視版"""
        start_time = time.time()
        results = []

        try:
            # インデックス中の動作制御（軽量化）
            if self.indexing_in_progress:
                # インデックス中はキャッシュ優先で高速検索
                results.extend(self._search_immediate_layer(query)[:max_results // 2] or [])
                results.extend(self._search_hot_layer(query)[:max_results // 2] or [])
                
                # 結果が不十分な場合のみDB検索
                if len(results) < max_results // 4:
                    try:
                        db_results = self._search_complete_layer(query, max_results // 4)
                        if db_results:
                            results.extend(db_results)
                    except Exception:
                        pass  # インデックス中のDB検索エラーは無視
                        
            else:
                # 通常時：最適化された3層検索
                # 完全層優先検索（最新・正確）
                complete_results = self._search_complete_layer(query, max_results // 2) or []
                results.extend(complete_results)

                # 即座層で補完
                immediate_results = self._search_immediate_layer(query) or []
                results.extend(immediate_results[:max_results // 4])

                # 高速層で補完
                hot_results = self._search_hot_layer(query) or []
                results.extend(hot_results[:max_results // 4])

            # 重複除去とランキング（最適化版）
            unique_results = self._deduplicate_and_rank_optimized(results)

            # ファイル種類フィルタを適用
            if file_type_filter != "all":
                filtered_results = []
                for result in unique_results:
                    file_path = result.get('file_path', '')
                    if file_path.lower().endswith(file_type_filter.lower()):
                        filtered_results.append(result)
                unique_results = filtered_results

            # 統計更新
            search_time = time.time() - start_time
            self.stats["search_count"] += 1
            self.stats["avg_search_time"] = ((self.stats["avg_search_time"] *
                                              (self.stats["search_count"] - 1) + search_time) /
                                             self.stats["search_count"])

            # 自動最適化チェック（インデックス中以外）
            if not self.indexing_in_progress:
                self.check_auto_optimization()

            # 検索結果の出力メッセージ
            status_msg = "📦 [インデックス中]" if self.indexing_in_progress else "✅ [完了]"
            cache_msg = f" キャッシュ:{len(results) - len(unique_results)}"
            
            # レイヤー別結果件数を計算（完全層優先表示）
            layer_counts = {}
            for result in unique_results:
                layer = result.get('layer', 'unknown')
                if layer.startswith('complete'):
                    layer_key = 'complete'
                else:
                    layer_key = layer
                layer_counts[layer_key] = layer_counts.get(layer_key, 0) + 1
            
            # 完全層を最初に表示する順序で並べ替え
            ordered_layers = ['complete', 'immediate', 'hot']
            layer_parts = []
            for layer in ordered_layers:
                if layer in layer_counts:
                    layer_parts.append(f"{layer}:{layer_counts[layer]}")
            # その他のレイヤーがあれば追加
            for layer, count in layer_counts.items():
                if layer not in ordered_layers:
                    layer_parts.append(f"{layer}:{count}")
            
            layer_msg = " / ".join(layer_parts)
            print(f"🔍 {status_msg} 3層統合検索: {len(unique_results)}件 ({search_time:.4f}秒) [フィルタ: {file_type_filter}]{cache_msg} [{layer_msg}]")
            
            return unique_results[:max_results]

        except Exception as e:
            print(f"❌ 統合検索エラー: {e}")
            return []
    
    def _search_immediate_layer(self, query: str) -> List[Dict[str, Any]]:
        """即座層検索"""
        return self.cache_manager.search_immediate_layer(query)
    
    def _search_hot_layer(self, query: str) -> List[Dict[str, Any]]:
        """高速層検索"""
        return self.cache_manager.search_hot_layer(query)
    
    def _search_complete_layer(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """完全層検索"""
        return self.database_manager.parallel_search(query, max_results)
    
    def _cache_search_results(self, query: str, results: List[Dict[str, Any]]):
        """検索結果をキャッシュに保存"""
        try:
            # 即座層キャッシュへ追加
            if len(self.immediate_cache) < self.max_immediate_cache:
                self.immediate_cache[query] = results.copy()
            else:
                # LRU的削除（最初のキーを削除）
                oldest_key = next(iter(self.immediate_cache))
                del self.immediate_cache[oldest_key]
                self.immediate_cache[query] = results.copy()
                
        except Exception as e:
            debug_logger.warning(f"キャッシュ保存エラー: {e}")
    
    def _update_average_search_time(self):
        """平均検索時間を更新"""
        if self.stats["search_count"] > 0:
            self.stats["avg_search_time"] = self.stats["total_search_time"] / self.stats["search_count"]
    
    def _deduplicate_and_rank_optimized(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """最適化版重複除去とランキング - 高速化重視"""
        if not results:
            return []
            
        seen_paths = set()
        unique_results = []
        
        # レイヤー優先度を事前計算
        priority_map = {
            'complete': 1000,
            'immediate': 100, 
            'hot': 10
        }
        
        # レイヤー名からの優先度取得（最適化）
        def get_priority(result):
            if not isinstance(result, dict):
                return (0, 0)
            layer = result.get('layer', 'unknown')
            # complete_db_0等の場合はcompleteとして扱う
            layer_base = layer.split('_')[0] if '_' in layer else layer
            priority = priority_map.get(layer_base, 1)
            score = result.get('relevance_score', 0)
            return (priority, score)
        
        # ソート（最適化）
        results.sort(key=get_priority, reverse=True)
        
        # 重複除去（最適化）
        for result in results:
            if isinstance(result, dict) and 'file_path' in result:
                path = result['file_path']
                if path not in seen_paths:
                    seen_paths.add(path)
                    unique_results.append(result)

        return unique_results
    
    def live_progressive_index_file(self, file_path: str) -> bool:
        """ライブプログレッシブファイルインデックス"""
        debug_logger.debug(f"インデックス開始: {file_path}")

        # キャンセルチェック
        if hasattr(self, 'indexing_cancelled') and self.indexing_cancelled:
            debug_logger.debug(f"インデックス処理がキャンセルされました: {file_path}")
            return False

        try:
            file_path_obj = Path(file_path)

            # macOS隠しファイル（._で始まるファイル）をスキップ
            if file_path_obj.name.startswith('._'):
                debug_logger.debug(f"macOS隠しファイルをスキップ: {file_path_obj.name}")
                return False

            # その他の隠しファイル・システムファイルもスキップ
            if file_path_obj.name.startswith('.DS_Store') or file_path_obj.name.startswith('Thumbs.db'):
                debug_logger.debug(f"システムファイルをスキップ: {file_path_obj.name}")
                return False

            if not file_path_obj.exists():
                debug_logger.warning(f"ファイルが存在しません: {file_path}")
                return False

            # ファイル情報取得
            stat = file_path_obj.stat()
            file_size = stat.st_size
            modified_time = stat.st_mtime

            debug_logger.debug(f"ファイル情報 - サイズ: {file_size}, 更新時刻: {modified_time}")

            # ファイル内容抽出
            debug_logger.debug(f"コンテンツ抽出開始: {file_path}")
            content = self.content_extractor.extract_content(file_path)
            if not content:
                debug_logger.warning(f"コンテンツが空または抽出失敗: {file_path}")
                return False

            debug_logger.info(f"コンテンツ抽出成功: {file_path} ({len(content)}文字)")
            file_hash = hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest()
            debug_logger.debug(f"ハッシュ計算完了: {file_hash[:8]}...")

            # 3層構造最適化処理
            file_data = {
                'file_name': file_path_obj.name,
                'file_type': file_path_obj.suffix.lower(),
                'size': file_size
            }

            # 即座層に追加
            self.cache_manager.add_to_immediate_cache(str(file_path), content, file_data)

            # 完全層への追加（非同期）
            threading.Timer(5.0, self._move_to_complete_layer,
                            args=[file_path, content, file_hash]).start()

            self.stats["indexed_files"] += 1
            debug_logger.info(f"3層構造最適化インデックス完了: {file_path}")
            return True

        except Exception as e:
            debug_logger.error(f"ファイルインデックスエラー {file_path}: {e}")
            print(f"❌ ファイルインデックスエラー {file_path}: {e}")
            return False
    
    def _move_to_complete_layer(self, file_path: str, content: str, file_hash: str):
        """完全層移動（データベース保存）"""
        try:
            if self.shutdown_requested:
                return
                
            file_path_obj = Path(file_path)
            
            # ファイル情報再取得
            stat = file_path_obj.stat()
            file_data = {
                'file_path': str(file_path),
                'file_name': file_path_obj.name,
                'content': content,
                'file_type': file_path_obj.suffix.lower(),
                'size': stat.st_size,
                'modified_time': stat.st_mtime,
                'indexed_time': time.time(),
                'hash': file_hash
            }
            
            # データベースに保存
            success = self.database_manager.store_document(file_data)
            
            if success:
                debug_logger.debug(f"完全層保存成功: {os.path.basename(file_path)}")
            else:
                debug_logger.warning(f"完全層保存失敗: {os.path.basename(file_path)}")
            
        except Exception as e:
            debug_logger.error(f"完全層移動エラー: {e}")
    
    def bulk_index_directory_with_progress(self, directory_path: str, 
                                           progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """進捗コールバック対応フォルダ一括インデックス"""
        try:
            self.indexing_in_progress = True
            self.indexing_cancelled = False
            
            start_time = time.time()
            
            # サポートするファイル拡張子
            supported_extensions = {
                '.txt', '.pdf', '.docx', '.xlsx', '.tif', '.tiff',
                '.doc', '.xls', '.ppt', '.pptx',
                '.dot', '.dotx', '.dotm', '.docm',
                '.xlt', '.xltx', '.xltm', '.xlsm', '.xlsb',
                '.zip'
            }
            
            # ファイル収集
            all_files = []
            for root, dirs, files in os.walk(directory_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in supported_extensions):
                        all_files.append(os.path.join(root, file))
            
            if not all_files:
                return {
                    'success_count': 0,
                    'total_files': 0,
                    'total_time': 0,
                    'files_per_second': 0
                }
            
            # ファイル分類
            light_files, medium_files, heavy_files = self._categorize_files_by_size(all_files)
            
            # 進捗情報初期化
            if progress_callback:
                progress_callback(
                    total_files=len(all_files),
                    category_totals={'light': len(light_files), 'medium': len(medium_files), 'heavy': len(heavy_files)}
                )
            
            # 並列処理でファイルインデックス
            success_count = 0
            
            # カテゴリ別に順次処理（軽量→中程度→重い）
            for category, files in [('light', light_files), ('medium', medium_files), ('heavy', heavy_files)]:
                if self.indexing_cancelled:
                    break
                    
                with ThreadPoolExecutor(max_workers=self.optimal_threads) as executor:
                    futures = {executor.submit(self._process_single_file_with_progress, 
                                              file_path, category, progress_callback): file_path 
                              for file_path in files}
                    
                    for future in as_completed(futures):
                        if self.indexing_cancelled:
                            break
                            
                        try:
                            result = future.result(timeout=30.0)
                            if result:
                                success_count += 1
                        except Exception as e:
                            debug_logger.error(f"ファイル処理エラー: {e}")
            
            total_time = time.time() - start_time
            files_per_second = success_count / total_time if total_time > 0 else 0
            
            return {
                'success_count': success_count,
                'total_files': len(all_files),
                'total_time': total_time,
                'files_per_second': files_per_second
            }
            
        except Exception as e:
            debug_logger.error(f"一括インデックスエラー: {e}")
            return {
                'success_count': 0,
                'total_files': 0,
                'total_time': 0,
                'files_per_second': 0
            }
        finally:
            self.indexing_in_progress = False
    
    def _categorize_files_by_size(self, files: List[str]) -> tuple:
        """ファイルサイズによる分類"""
        light_files = []    # <10MB
        medium_files = []   # 10MB-100MB  
        heavy_files = []    # >100MB
        
        for file_path in files:
            try:
                size_bytes = Path(file_path).stat().st_size
                if size_bytes < 10 * 1024 * 1024:  # 10MB
                    light_files.append(file_path)
                elif size_bytes < 100 * 1024 * 1024:  # 100MB
                    medium_files.append(file_path)
                else:
                    heavy_files.append(file_path)
            except:
                light_files.append(file_path)  # エラー時は軽量扱い
        
        return light_files, medium_files, heavy_files
    
    def _process_single_file_with_progress(self, file_path: str, category: str, 
                                           progress_callback: Optional[Callable] = None) -> bool:
        """進捗付き単一ファイル処理"""
        try:
            # 進捗更新
            if progress_callback:
                progress_callback(current_file=file_path, category=category, success=True)
            
            # ファイル処理
            result = self.live_progressive_index_file(file_path)
            
            return result
        except Exception as e:
            # エラーも進捗に記録
            if progress_callback:
                progress_callback(current_file=file_path, category=category, success=False)
            return False
    
    def check_auto_optimization(self):
        """自動最適化チェック"""
        try:
            # 検索数が多い場合に最適化を実行
            if self.stats["search_count"] % 1000 == 0 and self.stats["search_count"] > 0:
                self.stats["optimization_count"] += 1
                debug_logger.info(f"自動最適化実行 ({self.stats['search_count']}回検索後)")
        except Exception as e:
            debug_logger.error(f"自動最適化エラー: {e}")
    
    def get_comprehensive_statistics(self) -> Dict[str, Any]:
        """包括的統計情報取得"""
        return {
            "indexed_files": self.stats["indexed_files"],
            "search_count": self.stats["search_count"],
            "layer_hits": {
                "immediate": self.stats["immediate_layer_hits"],
                "hot": self.stats["hot_layer_hits"],
                "complete": self.stats["complete_layer_hits"]
            },
            "search_performance": {
                "avg_search_time": self.stats["avg_search_time"],
                "total_search_time": self.stats["total_search_time"]
            },
            "cache_statistics": self.cache_manager.get_cache_statistics(),
            "database_statistics": self.database_manager.get_statistics()
        }
    
    def get_optimization_statistics(self) -> Dict[str, Any]:
        """最適化統計情報取得"""
        return {
            "optimization_count": self.stats["optimization_count"],
            "error_count": self.stats["error_count"],
            "system_status": {
                "indexing_in_progress": self.indexing_in_progress,
                "databases_available": len(self.complete_db_paths),
                "optimal_threads": self.optimal_threads
            }
        }
    
    def save_caches(self):
        """キャッシュ保存"""
        self.cache_manager.save_caches()
    
    def load_caches(self):
        """キャッシュ復元"""
        self.cache_manager.load_caches()
    
    def clear_cache(self):
        """キャッシュクリア"""
        self.cache_manager.clear_cache()
    
    def shutdown(self):
        """システムシャットダウン"""
        try:
            self.shutdown_requested = True
            self.indexing_cancelled = True
            
            # キャッシュ保存
            self.cache_manager.shutdown()
            
            # データベースクリーンアップ
            self.database_manager.shutdown()
            
            debug_logger.info("検索システムシャットダウン完了")
            
        except Exception as e:
            debug_logger.error(f"シャットダウンエラー: {e}")