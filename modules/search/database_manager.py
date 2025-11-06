#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データベース管理
SQLite データベースの初期化、管理、最適化機能
"""

import os
import sqlite3
import threading
import time
import hashlib
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Any, Optional

from ..utils import setup_debug_logger, get_optimal_thread_count

# デバッグロガー
debug_logger = setup_debug_logger('DatabaseManager')


class DatabaseManager:
    """データベース管理クラス"""
    
    def __init__(self, project_root: str, db_count: Optional[int] = None):
        self.project_root = Path(project_root)
        self.db_count = db_count or self._calculate_optimal_db_count()
        
        # データベースパス設定
        self.db_paths = []
        self.complete_db_paths = []
        for i in range(self.db_count):
            db_path = self.project_root / "data_storage" / f"ultra_fast_search_db_{i}.db"
            complete_db_path = self.project_root / "data_storage" / f"complete_search_db_{i}.db"
            self.db_paths.append(db_path)
            self.complete_db_paths.append(complete_db_path)
        
        self.database_timeout = 180.0
        
    def _calculate_optimal_db_count(self) -> int:
        """システムリソースに基づく最適データベース数計算"""
        try:
            hardware_info = self._get_comprehensive_hardware_info()
            
            # CPUアーキテクチャに基づく基本DB数
            cpu_cores = hardware_info['cpu_cores']
            logical_cores = hardware_info['logical_cores']
            
            if cpu_cores >= 20:
                base_db_count = min(logical_cores, 48)
            elif cpu_cores >= 16:
                base_db_count = min(logical_cores, 40)
            elif cpu_cores >= 12:
                base_db_count = min(logical_cores, 32)
            elif cpu_cores >= 8:
                base_db_count = min(logical_cores * 0.8, 24)
            elif cpu_cores >= 6:
                base_db_count = min(logical_cores * 0.75, 16)
            elif cpu_cores >= 4:
                base_db_count = min(logical_cores * 0.6, 12)
            else:
                base_db_count = max(2, cpu_cores)
            
            # メモリとストレージ調整
            memory_gb = hardware_info['memory_gb']
            if memory_gb >= 128:
                memory_multiplier = 2.2
            elif memory_gb >= 64:
                memory_multiplier = 2.0
            elif memory_gb >= 32:
                memory_multiplier = 1.7
            elif memory_gb >= 16:
                memory_multiplier = 1.4
            elif memory_gb >= 8:
                memory_multiplier = 1.0
            else:
                memory_multiplier = 0.8
            
            calculated_db_count = int(base_db_count * memory_multiplier)
            optimal_db_count = max(2, min(calculated_db_count, 64))
            
            print(f"🧮 最適DB数計算: {cpu_cores}コア → {optimal_db_count}個")
            return optimal_db_count
            
        except Exception as e:
            print(f"⚠️ 動的DB数計算エラー: {e}")
            return 6  # デフォルト値
    
    def _get_comprehensive_hardware_info(self) -> Dict[str, Any]:
        """ハードウェア情報取得"""
        info = {
            'cpu_cores': 4,
            'logical_cores': 4,
            'memory_gb': 8.0
        }
        
        try:
            import psutil
            info['cpu_cores'] = psutil.cpu_count(logical=False) or 4
            info['logical_cores'] = psutil.cpu_count(logical=True) or 4
            memory = psutil.virtual_memory()
            info['memory_gb'] = memory.total / (1024 ** 3)
        except ImportError:
            import multiprocessing
            info['cpu_cores'] = multiprocessing.cpu_count()
            info['logical_cores'] = multiprocessing.cpu_count()
        except Exception:
            pass
            
        return info
    
    def initialize_databases(self):
        """データベース初期化"""
        start_time = time.time()
        
        try:
            # データベースディレクトリの確実な作成
            db_dir = self.project_root / "data_storage"
            db_dir.mkdir(parents=True, exist_ok=True)
            debug_logger.info(f"データベースディレクトリ確認/作成: {db_dir}")
            
            print(f"🔧 データベース高速並列初期化開始: {self.db_count}個")
            
            def initialize_single_db(db_index: int) -> tuple:
                """単一データベースの初期化"""
                complete_db_path = self.complete_db_paths[db_index]
                db_name = complete_db_path.name
                
                try:
                    # 既存データベースファイルの確認
                    if complete_db_path.exists() and complete_db_path.stat().st_size > 1024:
                        try:
                            conn = sqlite3.connect(str(complete_db_path), timeout=5.0)
                            cursor = conn.cursor()
                            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='documents'")
                            if cursor.fetchone()[0] > 0:
                                conn.close()
                                return db_index, True, f"既存DB使用: {db_name}"
                            conn.close()
                        except:
                            pass
                    
                    # 新規データベース作成
                    conn = sqlite3.connect(str(complete_db_path), timeout=15.0)
                    cursor = conn.cursor()
                    
                    # 高速モード設定
                    cursor.execute("PRAGMA synchronous=OFF")
                    cursor.execute("PRAGMA journal_mode=MEMORY")
                    cursor.execute("PRAGMA temp_store=MEMORY")
                    cursor.execute("PRAGMA cache_size=10000")

                    # テーブル作成
                    cursor.executescript('''
                        CREATE TABLE IF NOT EXISTS documents (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            file_path TEXT UNIQUE NOT NULL,
                            file_name TEXT NOT NULL,
                            content TEXT NOT NULL,
                            file_type TEXT NOT NULL,
                            size INTEGER,
                            modified_time REAL,
                            indexed_time REAL,
                            hash TEXT
                        );
                        
                        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                            file_path,
                            file_name, 
                            content, 
                            file_type,
                            tokenize='trigram'
                        );
                        
                        CREATE INDEX IF NOT EXISTS idx_file_path ON documents(file_path);
                        CREATE INDEX IF NOT EXISTS idx_file_type ON documents(file_type);
                        CREATE INDEX IF NOT EXISTS idx_modified_time ON documents(modified_time);
                    ''')
                    
                    # FTS5最適化設定
                    for setting in [
                        "INSERT INTO documents_fts(documents_fts, rank) VALUES('pgsz', '4096')",
                        "INSERT INTO documents_fts(documents_fts, rank) VALUES('crisismerge', '16')",
                        "INSERT INTO documents_fts(documents_fts, rank) VALUES('usermerge', '4')",
                        "INSERT INTO documents_fts(documents_fts, rank) VALUES('automerge', '8')"
                    ]:
                        try:
                            cursor.execute(setting)
                        except sqlite3.Error:
                            pass
                    
                    # 本番モード設定
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA journal_mode=WAL")
                    
                    conn.commit()
                    conn.close()
                    
                    return db_index, True, f"新規作成: {db_name}"
                    
                except Exception as e:
                    return db_index, False, f"エラー: {db_name} - {str(e)}"
            
            # 並列初期化実行
            success_count = 0
            max_init_workers = min(8, self.db_count)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_init_workers) as executor:
                futures = {executor.submit(initialize_single_db, i): i for i in range(self.db_count)}
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        db_index, success, message = future.result(timeout=30.0)
                        if success:
                            success_count += 1
                            debug_logger.debug(f"DB{db_index}初期化成功")
                        else:
                            debug_logger.error(f"DB{db_index}初期化失敗: {message}")
                            print(f"❌ データベース {db_index+1} 初期化エラー")
                    except Exception as e:
                        print(f"❌ データベース初期化タイムアウト: {e}")

            initialization_time = time.time() - start_time
            print(f"✅ データベース並列初期化完了: {success_count}/{self.db_count}個 ({initialization_time:.2f}秒)")

        except Exception as e:
            print(f"❌ データベース初期化エラー: {e}")
            debug_logger.error(f"データベース初期化エラー: {e}")
    
    def get_db_index_for_file(self, file_path: str) -> int:
        """ファイルパスに基づいてデータベースインデックスを決定"""
        hash_value = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        return int(hash_value, 16) % self.db_count
    
    def add_document_to_db(self, file_path: str, content: str, file_data: Dict[str, Any], 
                          file_hash: str) -> bool:
        """ドキュメントをデータベースに追加"""
        db_index = self.get_db_index_for_file(file_path)
        complete_db_path = self.complete_db_paths[db_index]
        
        max_retries = 8
        retry_delay = 0.05
        
        for attempt in range(max_retries):
            conn = None
            try:
                conn = sqlite3.connect(
                    str(complete_db_path),
                    timeout=120.0,
                    check_same_thread=False
                )
                
                # WALモードとパフォーマンス設定
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=20000")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.execute("PRAGMA busy_timeout=120000")
                
                cursor = conn.cursor()
                
                # 既存チェック
                cursor.execute('SELECT id FROM documents WHERE file_path = ?', (file_path,))
                existing = cursor.fetchone()
                
                # データ準備
                safe_content = content[:2000000] if content else ""
                safe_file_name = file_data['file_name'][:500] if file_data['file_name'] else os.path.basename(file_path)
                safe_file_type = file_data['file_type'][:100] if file_data['file_type'] else "unknown"
                
                # 特殊文字のエスケープ
                safe_content = safe_content.replace('\x00', '')
                safe_file_name = safe_file_name.replace('\x00', '')
                
                if existing:
                    # 更新処理
                    conn.execute("BEGIN EXCLUSIVE")
                    
                    cursor.execute(
                        '''
                        UPDATE documents 
                        SET content = ?, file_name = ?, file_type = ?, size = ?, 
                            modified_time = ?, indexed_time = ?, hash = ?
                        WHERE file_path = ?
                    ''', (safe_content, safe_file_name, safe_file_type, file_data['size'],
                          time.time(), time.time(), file_hash, file_path))

                    cursor.execute('DELETE FROM documents_fts WHERE rowid = ?', (existing[0],))
                    cursor.execute(
                        '''
                        INSERT INTO documents_fts(rowid, file_path, file_name, content, file_type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (existing[0], file_path, safe_file_name, safe_content, safe_file_type))

                    conn.commit()
                    
                else:
                    # 新規追加処理
                    conn.execute("BEGIN EXCLUSIVE")
                    
                    cursor.execute(
                        '''
                        INSERT INTO documents (file_path, file_name, content, file_type, size, 
                                             modified_time, indexed_time, hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (file_path, safe_file_name, safe_content, safe_file_type,
                          file_data['size'], time.time(), time.time(), file_hash))

                    doc_id = cursor.lastrowid
                    if doc_id:
                        cursor.execute(
                            '''
                            INSERT INTO documents_fts(rowid, file_path, file_name, content, file_type)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (doc_id, file_path, safe_file_name, safe_content, safe_file_type))

                    conn.commit()

                return True
                
            except sqlite3.OperationalError as e:
                error_msg = str(e).lower()
                if ("database is locked" in error_msg or "database is busy" in error_msg) and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
                else:
                    debug_logger.error(f"DB{db_index}運用エラー: {e}")
                    return False
                    
            except Exception as e:
                debug_logger.error(f"DB{db_index}予期しないエラー: {e}")
                return False
                
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except:
                        pass
        
        return False
    
    def search_in_databases(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """全データベースで並列検索"""
        from ..utils import normalize_search_text_ultra
        
        results = []
        
        try:
            half_width, full_width, normalized, query_patterns = normalize_search_text_ultra(query)
            
            def search_single_db(db_index: int) -> List[Dict[str, Any]]:
                db_results = []
                try:
                    complete_db_path = self.complete_db_paths[db_index]
                    conn = sqlite3.connect(complete_db_path, timeout=30.0)
                    conn.execute('PRAGMA journal_mode=WAL')
                    conn.execute('PRAGMA synchronous=NORMAL')
                    cursor = conn.cursor()

                    for idx, pattern in enumerate(query_patterns[:3]):
                        try:
                            if len(pattern) <= 2:
                                # LIKE検索
                                cursor.execute(
                                    '''
                                    SELECT file_path, file_name, content, file_type,
                                           1.0 as relevance_score
                                    FROM documents_fts
                                    WHERE (content LIKE ? OR file_name LIKE ?)
                                    ORDER BY file_name
                                    LIMIT ?
                                ''', (f'%{pattern}%', f'%{pattern}%', max_results // self.db_count + 20))
                                
                                rows = cursor.fetchall()
                                for row in rows:
                                    result = {
                                        'file_path': row[0],
                                        'file_name': row[1],
                                        'content_preview': row[2][:200] if row[2] else '',
                                        'layer': f'complete_db_{db_index}_like',
                                        'file_type': row[3],
                                        'size': len(row[2]) if row[2] else 0,
                                        'relevance_score': 1.5 + 0.2 * (len(query_patterns) - idx)
                                    }
                                    db_results.append(result)
                                if rows:
                                    break
                            
                            if len(pattern) >= 3:
                                # FTS5検索
                                search_queries = [
                                    f'content:"{pattern}" OR file_name:"{pattern}"',
                                    f'content:{pattern} OR file_name:{pattern}',
                                    f'content:{pattern}* OR file_name:{pattern}*'
                                ]
                                
                                for search_query in search_queries:
                                    try:
                                        cursor.execute(
                                            '''
                                            SELECT file_path, file_name, content, file_type,
                                                   rank AS relevance_score
                                            FROM documents_fts
                                            WHERE documents_fts MATCH ?
                                            ORDER BY rank
                                            LIMIT ?
                                        ''', (search_query, max_results // self.db_count + 20))
                                        
                                        rows = cursor.fetchall()
                                        for row in rows:
                                            result = {
                                                'file_path': row[0],
                                                'file_name': row[1],
                                                'content_preview': row[2][:200] if row[2] else '',
                                                'layer': f'complete_db_{db_index}',
                                                'file_type': row[3],
                                                'size': len(row[2]) if row[2] else 0,
                                                'relevance_score': (row[4] if len(row) > 4 and row[4] else 0.5) + 0.1 * (len(query_patterns) - idx)
                                            }
                                            db_results.append(result)
                                        
                                        if rows:
                                            break
                                    except sqlite3.OperationalError:
                                        continue
                        except Exception:
                            continue

                    conn.close()
                    
                except Exception as e:
                    debug_logger.warning(f"DB{db_index}検索エラー: {e}")
                
                return db_results

            # 並列検索実行
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.db_count) as executor:
                future_to_db = {executor.submit(search_single_db, i): i for i in range(self.db_count)}
                
                for future in concurrent.futures.as_completed(future_to_db):
                    db_index = future_to_db[future]
                    try:
                        db_results = future.result(timeout=10.0)
                        results.extend(db_results)
                    except Exception as e:
                        debug_logger.warning(f"DB{db_index}並列検索エラー: {e}")

            # 重複除去とスコア順ソート
            seen_paths = set()
            unique_results = []
            for result in sorted(results, key=lambda x: x.get('relevance_score', 0), reverse=True):
                if isinstance(result, dict) and 'file_path' in result:
                    if result['file_path'] not in seen_paths:
                        unique_results.append(result)
                        seen_paths.add(result['file_path'])

            return unique_results[:max_results]

        except Exception as e:
            debug_logger.error(f"並列検索エラー: {e}")
            return []
    
    def get_database_statistics(self) -> Dict[str, Any]:
        """データベース統計情報取得"""
        try:
            def get_single_db_stats(db_index: int) -> Dict[str, Any]:
                stats = {
                    'db_index': db_index,
                    'file_count': 0,
                    'file_type_stats': {},
                    'storage_size': 0,
                    'error': None
                }
                
                try:
                    complete_db_path = self.complete_db_paths[db_index]
                    
                    if not os.path.exists(complete_db_path):
                        return stats
                    
                    file_size = os.path.getsize(complete_db_path)
                    if file_size < 1024:
                        return stats
                        
                    conn = sqlite3.connect(complete_db_path, timeout=5.0)
                    cursor = conn.cursor()
                    
                    # テーブル存在チェック
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'")
                    if not cursor.fetchone():
                        conn.close()
                        return stats
                    
                    # ファイル数カウント
                    cursor.execute("SELECT COUNT(*) FROM documents")
                    count_result = cursor.fetchone()
                    stats['file_count'] = count_result[0] if count_result else 0
                    
                    if stats['file_count'] > 0:
                        # ファイル種類別統計
                        try:
                            cursor.execute("SELECT file_type, COUNT(*) FROM documents GROUP BY file_type")
                            for row in cursor.fetchall():
                                if row and len(row) >= 2:
                                    stats['file_type_stats'][row[0]] = row[1]
                        except Exception:
                            pass
                    
                    stats['storage_size'] = file_size
                    conn.close()
                    
                except Exception as e:
                    stats['error'] = str(e)
                
                return stats
            
            # 並列統計取得
            all_db_stats = []
            max_workers = min(self.db_count, 4)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_db = {executor.submit(get_single_db_stats, i): i for i in range(self.db_count)}
                
                for future in concurrent.futures.as_completed(future_to_db, timeout=30.0):
                    try:
                        db_stats = future.result(timeout=10.0)
                        all_db_stats.append(db_stats)
                    except Exception:
                        pass
            
            # 統計集計
            valid_stats = [stats for stats in all_db_stats if stats['error'] is None]
            total_file_count = sum(stats['file_count'] for stats in valid_stats)
            all_file_type_stats = {}
            total_storage_size = sum(stats['storage_size'] for stats in valid_stats)
            
            for stats in valid_stats:
                for file_type, count in stats['file_type_stats'].items():
                    all_file_type_stats[file_type] = all_file_type_stats.get(file_type, 0) + count
            
            return {
                "total_files": total_file_count,
                "db_count": self.db_count,
                "valid_databases": len(valid_stats),
                "file_type_distribution": all_file_type_stats,
                "total_storage_size": total_storage_size,
                "individual_databases": valid_stats
            }

        except Exception as e:
            debug_logger.error(f"統計情報取得エラー: {e}")
            return {
                "total_files": 0,
                "db_count": self.db_count,
                "valid_databases": 0,
                "file_type_distribution": {},
                "total_storage_size": 0,
                "individual_databases": [],
                "error": str(e)
            }
    
    def optimize_databases(self):
        """データベース最適化"""
        print("🔧 データベース最適化開始...")
        
        def optimize_single_database(db_index: int):
            try:
                complete_db_path = self.complete_db_paths[db_index]
                conn = sqlite3.connect(complete_db_path, timeout=60.0)
                cursor = conn.cursor()

                cursor.execute("INSERT INTO documents_fts(documents_fts) VALUES('optimize')")
                cursor.execute("VACUUM")
                cursor.execute("ANALYZE")
                cursor.execute("PRAGMA optimize")
                
                conn.commit()
                conn.close()
                
                print(f"✅ DB{db_index}最適化完了")

            except Exception as e:
                print(f"⚠️ DB{db_index}最適化エラー: {e}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.db_count, 4)) as executor:
            futures = [executor.submit(optimize_single_database, i) for i in range(self.db_count)]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result(timeout=120)
                except Exception as e:
                    print(f"⚠️ 最適化エラー: {e}")
        
        print("✅ データベース最適化完了")