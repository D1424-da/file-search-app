#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
メインUI
Tkinterベースのファイル検索アプリケーションUI
"""

import os
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Dict, Any, List, Optional
import threading
import subprocess
import webbrowser
import sqlite3
import platform
from datetime import datetime

from ..search import UltraFastFullCompliantSearchSystem
from ..utils import ProgressTracker, setup_debug_logger

# デバッグロガー
debug_logger = setup_debug_logger('MainUI')


class UltraFastCompliantUI:
    """100%仕様適合 超高速全文検索UI"""

    def __init__(self, search_system: UltraFastFullCompliantSearchSystem):
        self.search_system = search_system
        self.root = tk.Tk()
        self.root.title("100%仕様適合 超高速ライブ全文検索アプリ")
        self.root.geometry("1200x800")
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.on_search_change)
        self.last_search_time: float = 0.0
        self.search_delay = 0.3
        self.min_search_length = 2
        
        # 統計更新制限用
        self._last_stats_update_time = 0.0
        self._stats_update_interval = 2.0
        self._pending_stats_update = False
        
        # フォルダオープン管理用
        self._opening_folder: bool = False
        self._double_click_processing: bool = False
        self._global_folder_requests = []
        self._explorer_processes = set()

        # 大容量インデックス用変数
        self.drive_info = {}
        self.bulk_indexing_active = False
        self.selected_folder_path = None

        # 進捗トラッキング
        self.progress_tracker = ProgressTracker()
        self.progress_window = None

        # インデックス処理キャンセル機能
        self.indexing_cancelled = False
        self.current_indexing_thread = None

        # 統計更新コールバック設定
        if hasattr(self.search_system, '_stats_update_callback'):
            self.search_system._stats_update_callback = self.update_statistics
        
        # シャットダウン処理の設定
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 増分インデックス機能の開始
        if hasattr(self.search_system, 'start_incremental_scanning'):
            self.search_system.start_incremental_scanning()

        self.setup_ui()
        
        # 初回ドライブ検出
        self.root.after(1000, self.refresh_drives)
    
    def setup_ui(self):
        """UIセットアップ"""
        # メインウィンドウ作成
        self.root = tk.Tk()
        self.root.title("100%仕様適合 超高速ライブ全文検索アプリ")
        self.root.geometry("1200x800")
        
        # ウィンドウ終了処理の設定
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # アイコン設定（可能な場合）
        try:
            # Windows用アイコン設定
            if os.name == 'nt':
                self.root.iconbitmap(default='')
        except:
            pass
        
        # メインフレーム作成
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 検索セクション
        self.create_search_section(main_frame)
        
        # 結果表示セクション
        self.create_results_section(main_frame)
        
        # 統計情報セクション
        self.create_statistics_section(main_frame)
        
        # インデックス管理セクション
        self.create_index_section(main_frame)
        
        # ステータスバー
        self.create_status_bar(main_frame)
        
        # 初期フォーカス設定
        self.search_entry.focus()
        
        # 定期統計更新開始
        self.start_periodic_updates()
    
    def create_search_section(self, parent):
        """検索セクション作成"""
        search_frame = ttk.LabelFrame(parent, text="🔍 検索", padding=10)
        search_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 検索入力
        input_frame = ttk.Frame(search_frame)
        input_frame.pack(fill=tk.X)
        
        ttk.Label(input_frame, text="キーワード:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(input_frame, textvariable=self.search_var, font=("", 12))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # リアルタイム検索のバインド
        self.search_var.trace('w', self.on_search_change)
        
        # 検索ボタン
        self.search_button = ttk.Button(input_frame, text="🔍 検索", command=self.search_files)
        self.search_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # クリアボタン
        self.clear_button = ttk.Button(input_frame, text="🗑️ クリア", command=self.clear_search)
        self.clear_button.pack(side=tk.LEFT)
        
        # ファイル種類フィルタ
        filter_frame = ttk.Frame(search_frame)
        filter_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(filter_frame, text="ファイル種類:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.file_type_var = tk.StringVar(value="all")
        file_types = [
            ("すべて", "all"),
            ("テキスト (.txt)", ".txt"),
            ("Word文書 (.docx)", ".docx"),
            ("Excel (.xlsx)", ".xlsx"),
            ("PDF (.pdf)", ".pdf"),
            ("画像 (.tif)", ".tif")
        ]
        
        self.file_type_combo = ttk.Combobox(filter_frame, textvariable=self.file_type_var, 
                                           values=[item[1] for item in file_types], 
                                           state="readonly", width=20)
        self.file_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # 検索モードスイッチ
        self.live_search_var = tk.BooleanVar(value=True)
        self.live_search_check = ttk.Checkbutton(filter_frame, 
                                                text="リアルタイム検索",
                                                variable=self.live_search_var)
        self.live_search_check.pack(side=tk.LEFT)
    
    def create_results_section(self, parent):
        """結果表示セクション作成"""
        results_frame = ttk.LabelFrame(parent, text="📋 検索結果", padding=10)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 結果カウントラベル
        self.result_count_var = tk.StringVar(value="検索結果: 0件")
        self.result_count_label = ttk.Label(results_frame, textvariable=self.result_count_var)
        self.result_count_label.pack(anchor=tk.W, pady=(0, 5))
        
        # Treeviewウィジェット
        tree_frame = ttk.Frame(results_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # 列定義
        columns = ("rank", "filename", "path", "size", "type", "layer")
        self.results_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)
        
        # ヘッダー設定
        headers = {
            "rank": "#",
            "filename": "ファイル名",
            "path": "パス", 
            "size": "サイズ",
            "type": "種類",
            "layer": "レイヤー"
        }
        
        widths = {
            "rank": 50,
            "filename": 300,
            "path": 400,
            "size": 80,
            "type": 80,
            "layer": 100
        }
        
        for col in columns:
            self.results_tree.heading(col, text=headers[col])
            self.results_tree.column(col, width=widths[col], minwidth=50)
        
        # スクロールバー
        scrollbar_v = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.results_tree.yview)
        scrollbar_h = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
        
        # レイアウト
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_v.grid(row=0, column=1, sticky="ns")
        scrollbar_h.grid(row=1, column=0, sticky="ew")
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        
        # イベントバインド
        self.results_tree.bind("<Double-1>", self.open_selected_file)
        self.results_tree.bind("<Button-3>", self.show_context_menu)
        self.results_tree.bind("<Motion>", self._on_tree_motion)
        self.results_tree.bind("<Leave>", self._on_tree_leave)
        
        # ファイル種類色設定
        self._setup_file_type_colors()
    
    def create_statistics_section(self, parent):
        """統計情報セクション作成"""
        stats_frame = ttk.LabelFrame(parent, text="📊 統計情報", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 3層統計表示
        layers_frame = ttk.Frame(stats_frame)
        layers_frame.pack(fill=tk.X)
        
        # 即座層
        immediate_frame = ttk.Frame(layers_frame)
        immediate_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(immediate_frame, text="⚡ 即座層:", font=("", 9, "bold")).pack(anchor=tk.W)
        self.immediate_label = ttk.Label(immediate_frame, text="0 ファイル")
        self.immediate_label.pack(anchor=tk.W)
        
        # 高速層
        hot_frame = ttk.Frame(layers_frame)
        hot_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(hot_frame, text="🔥 高速層:", font=("", 9, "bold")).pack(anchor=tk.W)
        self.hot_label = ttk.Label(hot_frame, text="0 ファイル")
        self.hot_label.pack(anchor=tk.W)
        
        # 完全層
        complete_frame = ttk.Frame(layers_frame)
        complete_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(complete_frame, text="💾 完全層:", font=("", 9, "bold")).pack(anchor=tk.W)
        self.complete_label = ttk.Label(complete_frame, text="0 ファイル")
        self.complete_label.pack(anchor=tk.W)
        
        # その他統計
        other_stats_frame = ttk.Frame(stats_frame)
        other_stats_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.stats_label = ttk.Label(other_stats_frame, text="検索回数: 0 | 平均時間: 0.000秒")
        self.stats_label.pack(anchor=tk.W)
        
        # ボタンフレーム
        stats_buttons_frame = ttk.Frame(stats_frame)
        stats_buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(stats_buttons_frame, text="📊 詳細統計", command=self.show_detailed_stats).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(stats_buttons_frame, text="🔄 統計更新", command=self.update_statistics).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(stats_buttons_frame, text="🗑️ キャッシュクリア", command=self.clear_cache).pack(side=tk.LEFT)
    
    def create_index_section(self, parent):
        """インデックス管理セクション作成"""
        index_frame = ttk.LabelFrame(parent, text="📁 インデックス管理", padding=10)
        index_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 対象選択
        target_frame = ttk.Frame(index_frame)
        target_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(target_frame, text="対象:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.target_type_var = tk.StringVar(value="folder")
        ttk.Radiobutton(target_frame, text="フォルダー", 
                       variable=self.target_type_var, value="folder",
                       command=self.on_target_type_changed).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(target_frame, text="ドライブ", 
                       variable=self.target_type_var, value="drive",
                       command=self.on_target_type_changed).pack(side=tk.LEFT)
        
        # フォルダー選択
        folder_frame = ttk.Frame(index_frame)
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.folder_var = tk.StringVar(value="フォルダーが選択されていません")
        self.folder_label = ttk.Label(folder_frame, textvariable=self.folder_var)
        self.folder_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.folder_browse_btn = ttk.Button(folder_frame, text="📁 選択", command=self.browse_folder)
        self.folder_browse_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # ドライブ選択
        drive_frame = ttk.Frame(index_frame)
        drive_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.drive_var = tk.StringVar()
        self.drive_combo = ttk.Combobox(drive_frame, textvariable=self.drive_var, 
                                       state="disabled", width=20)
        self.drive_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.drive_combo.bind('<<ComboboxSelected>>', self.on_drive_selected)
        
        self.refresh_drives_btn = ttk.Button(drive_frame, text="🔄 更新", 
                                            command=self.refresh_drives, state="disabled")
        self.refresh_drives_btn.pack(side=tk.LEFT)
        
        # 対象情報表示
        self.target_info_var = tk.StringVar(value="対象を選択してください")
        self.target_info_label = ttk.Label(index_frame, textvariable=self.target_info_var)
        self.target_info_label.pack(anchor=tk.W, pady=(0, 10))
        
        # インデックス操作ボタン
        buttons_frame = ttk.Frame(index_frame)
        buttons_frame.pack(fill=tk.X)
        
        self.bulk_index_btn = ttk.Button(buttons_frame, text="🚀 インデックス開始", 
                                        command=self.start_bulk_indexing, state="disabled")
        self.bulk_index_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.cancel_index_btn = ttk.Button(buttons_frame, text="⏹️ キャンセル", 
                                          command=self.cancel_indexing, state="disabled")
        self.cancel_index_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(buttons_frame, text="📋 単体ファイル", command=self.index_folder).pack(side=tk.LEFT)
        
        # 進捗表示
        self.bulk_progress_var = tk.StringVar(value="待機中...")
        self.bulk_progress_label = ttk.Label(index_frame, textvariable=self.bulk_progress_var)
        self.bulk_progress_label.pack(anchor=tk.W, pady=(10, 0))
    
    def create_status_bar(self, parent):
        """ステータスバー作成"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar(value="準備完了")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        self.status_label.pack(fill=tk.X)
    
    def on_search_change(self, *args):
        """検索テキスト変更時の処理（リアルタイム検索）"""
        if self.live_search_var.get():
            query = self.search_var.get().strip()
            if len(query) >= 2:  # 2文字以上で検索開始
                # 少し遅延させてから検索実行
                self.root.after(300, lambda: self.perform_search(query))
            elif len(query) == 0:
                self.clear_results()
    
    def search_files(self):
        """検索実行"""
        query = self.search_var.get().strip()
        self.perform_search(query)
    
    def perform_search(self, query: str):
        """実際の検索処理"""
        if not query:
            self.clear_results()
            return
        
        # 現在のクエリが変更されていない場合のみ実行
        if query != self.search_var.get().strip():
            return
        
        start_time = time.time()
        self.status_var.set(f"検索中: {query}")
        
        try:
            # ファイル種類フィルタを適用した検索
            file_type_filter = self.file_type_var.get()
            results = self.search_system.unified_three_layer_search(
                query, 
                max_results=5500,
                file_type_filter=file_type_filter
            )
            
            # 結果を表示
            self.display_results(results)
            
            search_time = time.time() - start_time
            self.status_var.set(f"検索完了: {len(results)}件 ({search_time:.3f}秒)")
            
        except Exception as e:
            self.status_var.set(f"検索エラー: {e}")
            debug_logger.error(f"検索エラー: {e}")
    
    def display_results(self, results: List[Dict[str, Any]]):
        """検索結果を表示"""
        # 既存の結果をクリア
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        
        # 結果カウント更新
        self.result_count_var.set(f"検索結果: {len(results):,}件")
        
        if not results:
            return
        
        # 結果を表示
        for i, result in enumerate(results):
            try:
                rank = i + 1
                filename = result.get('file_name', 'N/A')
                filepath = result.get('file_path', 'N/A')
                size = self._format_file_size(result.get('size', 0))
                file_type = result.get('file_type', 'N/A')
                layer = result.get('layer', 'N/A')
                
                # ファイル種類に応じたタグ設定
                tag = self._get_file_type_tag(file_type)
                
                item_id = self.results_tree.insert('', tk.END, values=(
                    rank, filename, filepath, size, file_type, layer
                ), tags=[tag])
                
            except Exception as e:
                debug_logger.error(f"結果表示エラー: {e}")
                continue
    
    def _format_file_size(self, size_bytes: int) -> str:
        """ファイルサイズの書式設定"""
        try:
            if size_bytes < 1024:
                return f"{size_bytes}B"
            elif size_bytes < 1024**2:
                return f"{size_bytes/1024:.1f}KB"
            elif size_bytes < 1024**3:
                return f"{size_bytes/(1024**2):.1f}MB"
            else:
                return f"{size_bytes/(1024**3):.1f}GB"
        except:
            return "N/A"
    
    def clear_search(self):
        """検索クリア"""
        self.search_var.set("")
        self.clear_results()
        self.search_entry.focus()
    
    def clear_results(self):
        """結果クリア"""
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.result_count_var.set("検索結果: 0件")
        self.status_var.set("準備完了")
    
    def open_selected_file(self, event):
        """選択ファイルを開く（ダブルクリック時）"""
        # 重複防止処理
        current_time = time.time()
        
        if getattr(self, '_double_click_processing', False):
            debug_logger.warning("ダブルクリック処理中のため、新しいイベントをブロック")
            return
            
        if hasattr(self, '_last_double_click_time'):
            time_diff = current_time - self._last_double_click_time
            if time_diff < 0.5:
                debug_logger.warning(f"ダブルクリック時間間隔不足: {time_diff:.3f}秒")
                return
        
        self._double_click_processing = True
        self._last_double_click_time = current_time
        
        try:
            selection = self.results_tree.selection()
            if not selection:
                return

            item = self.results_tree.item(selection[0])
            file_path = item['values'][2]  # パス列

            if not os.path.exists(file_path):
                messagebox.showwarning("警告", f"ファイルが見つかりません:\n{file_path}")
                return

            debug_logger.info(f"ファイルをハイライト表示: {os.path.basename(file_path)}")
            self._open_folder_with_highlight(file_path)

        except Exception as e:
            debug_logger.error(f"ファイルハイライト表示エラー: {e}")
            messagebox.showerror("エラー", f"ファイルハイライト表示に失敗しました:\n{e}")
        finally:
            # フラグリセット
            self.root.after(3000, self._reset_double_click_flag)
    
    def _reset_double_click_flag(self):
        """ダブルクリック処理フラグリセット"""
        try:
            self._double_click_processing = False
            debug_logger.debug("ダブルクリック処理フラグリセット完了")
        except Exception as e:
            debug_logger.error(f"ダブルクリックフラグリセットエラー: {e}")
            self._double_click_processing = False
    
    def _open_folder_with_highlight(self, file_path: str):
        """フォルダを開いてファイルをハイライト"""
        try:
            # 重複防止
            current_time = time.time()
            if current_time - getattr(self, '_last_folder_open_time', 0) < 1.0:
                return
            self._last_folder_open_time = current_time

            if not os.path.exists(file_path):
                messagebox.showwarning("警告", f"ファイルが見つかりません:\n{file_path}")
                return

            # Explorerでファイルをハイライト表示
            try:
                subprocess.run(['explorer', f'/select,{file_path}'], check=False,
                             creationflags=subprocess.CREATE_NO_WINDOW)
                print(f"ファイルをハイライト表示しました: {os.path.basename(file_path)}")
                return
            except Exception:
                pass
            
            # 代替手段：フォルダを開く
            try:
                folder_path = os.path.dirname(file_path)
                os.startfile(folder_path)
                print(f"フォルダを開きました: {os.path.basename(folder_path)}")
            except Exception as e:
                messagebox.showerror("エラー", f"フォルダを開けませんでした: {e}")
                
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル表示エラー: {e}")
    
    def show_context_menu(self, event):
        """右クリックコンテキストメニュー表示"""
        selection = self.results_tree.selection()
        if not selection:
            return

        item = self.results_tree.item(selection[0])
        file_path = item['values'][2]

        # コンテキストメニュー作成
        context_menu = tk.Menu(self.root, tearoff=0)
        context_menu.add_command(label="📂 フォルダを開く",
                                command=lambda: self._open_folder_with_highlight(file_path))
        context_menu.add_command(label="📋 パスをコピー",
                                command=lambda: self._copy_path_to_clipboard(file_path))

        # メニュー表示
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()
    
    def _copy_path_to_clipboard(self, file_path: str):
        """パスをクリップボードにコピー"""
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(file_path)
            print(f"パスをコピーしました: {os.path.basename(file_path)}")
        except Exception as e:
            messagebox.showerror("エラー", f"パスをコピーできませんでした: {e}")
    
    def _on_tree_motion(self, event):
        """ツリービューでのマウスホバー効果"""
        try:
            item_id = self.results_tree.identify_row(event.y)
            
            if hasattr(self, '_hovered_item') and self._hovered_item != item_id:
                self._clear_hover_highlight(self._hovered_item)
            
            if item_id and item_id != getattr(self, '_hovered_item', None):
                self._apply_hover_highlight(item_id)
                self._hovered_item = item_id
                
                # ファイル情報をタイトルバーに表示
                item_values = self.results_tree.item(item_id, 'values')
                if len(item_values) >= 3:
                    file_name = item_values[1]
                    self.root.title(f"100%仕様適合 超高速ライブ全文検索アプリ - ホバー中: {file_name}")
        except:
            pass
    
    def _on_tree_leave(self, event):
        """ツリービューからマウスが離れた時の処理"""
        try:
            if hasattr(self, '_hovered_item'):
                self._clear_hover_highlight(self._hovered_item)
                del self._hovered_item
            self.root.title("100%仕様適合 超高速ライブ全文検索アプリ")
        except:
            pass
    
    def _apply_hover_highlight(self, item_id):
        """アイテムにホバー強調を適用"""
        try:
            current_tags = self.results_tree.item(item_id, 'tags')
            self.results_tree.tag_configure('hover')
            new_tags = list(current_tags) if current_tags else []
            if 'hover' not in new_tags:
                new_tags.append('hover')
                self.results_tree.item(item_id, tags=new_tags)
        except:
            pass
    
    def _clear_hover_highlight(self, item_id):
        """アイテムからホバー強調を解除"""
        try:
            current_tags = self.results_tree.item(item_id, 'tags')
            if current_tags and 'hover' in current_tags:
                new_tags = [tag for tag in current_tags if tag != 'hover']
                self.results_tree.item(item_id, tags=new_tags)
        except:
            pass
    
    def _get_file_type_tag(self, file_ext: str) -> str:
        """ファイル拡張子に基づいてタグを決定"""
        file_type_map = {
            '.txt': 'text', '.md': 'text', '.log': 'text', '.csv': 'text', '.json': 'text',
            '.doc': 'document', '.docx': 'document', '.dot': 'document', '.dotx': 'document',
            '.dotm': 'document', '.docm': 'document', '.rtf': 'document', '.odt': 'document',
            '.pdf': 'pdf',
            '.xls': 'excel', '.xlsx': 'excel', '.xlt': 'excel', '.xltx': 'excel',
            '.xltm': 'excel', '.xlsm': 'excel', '.xlsb': 'excel', '.ods': 'excel',
            '.ppt': 'powerpoint', '.pptx': 'powerpoint', '.odp': 'powerpoint',
            '.tif': 'image', '.tiff': 'image', '.png': 'image', '.jpg': 'image',
            '.jpeg': 'image', '.bmp': 'image', '.gif': 'image',
            '.zip': 'archive'
        }
        return file_type_map.get(file_ext, 'other')
    
    def _setup_file_type_colors(self):
        """ファイル種類に応じた色設定"""
        try:
            # 標準色使用（背景色・文字色なし）
            self.results_tree.tag_configure('text')
            self.results_tree.tag_configure('document')
            self.results_tree.tag_configure('pdf')
            self.results_tree.tag_configure('excel')
            self.results_tree.tag_configure('powerpoint')
            self.results_tree.tag_configure('image')
            self.results_tree.tag_configure('archive')
            self.results_tree.tag_configure('other')
            
            # ハイライト用（選択時の効果）
            self.results_tree.tag_configure('highlight', background='#FFD700', foreground='#000000')
        except Exception as e:
            debug_logger.error(f"ファイル種類色設定エラー: {e}")
    
    def update_statistics(self):
        """統計情報更新"""
        try:
            stats = self.search_system.get_comprehensive_statistics()
            
            # キャッシュ統計
            cache_stats = stats.get('cache_statistics', {})
            immediate_count = cache_stats.get('immediate_layer', 0)
            hot_count = cache_stats.get('hot_layer', 0)
            
            self.immediate_label.config(text=f"{immediate_count:,} ファイル")
            self.hot_label.config(text=f"{hot_count:,} ファイル")
            
            # データベース統計
            db_stats = stats.get('database_statistics', {})
            complete_count = db_stats.get('total_documents', 0)
            self.complete_label.config(text=f"{complete_count:,} ファイル")
            
            # 検索統計
            search_stats = stats.get('search_performance', {})
            search_count = stats.get('search_count', 0)
            avg_time = search_stats.get('avg_search_time', 0)
            
            self.stats_label.config(text=f"検索回数: {search_count:,} | 平均時間: {avg_time:.3f}秒")
            
            debug_logger.debug(f"統計更新: immediate={immediate_count}, hot={hot_count}, complete={complete_count}")
            
        except Exception as e:
            debug_logger.error(f"統計更新エラー: {e}")
            self.stats_label.config(text="統計更新エラー")
    
    def start_periodic_updates(self):
        """定期統計更新開始"""
        self.update_statistics()
        # 8秒間隔で統計更新
        self.root.after(8000, self.start_periodic_updates)
    
    def show_detailed_stats(self):
        """詳細統計表示"""
        try:
            stats = self.search_system.get_comprehensive_statistics()
            optimization_stats = self.search_system.get_optimization_statistics()

            stats_window = tk.Toplevel(self.root)
            stats_window.title("📊 詳細統計情報")
            stats_window.geometry("600x500")
            stats_window.transient(self.root)

            main_frame = ttk.Frame(stats_window, padding=10)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # テキストウィジェット
            text_widget = tk.Text(main_frame, wrap=tk.WORD, font=("Consolas", 9))
            scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=text_widget.yview)
            text_widget.configure(yscrollcommand=scrollbar.set)

            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # 統計情報を表示
            self._display_stats_text(text_widget, stats, optimization_stats)

            # 更新ボタン
            button_frame = ttk.Frame(stats_window)
            button_frame.pack(fill=tk.X, pady=(10, 0))
            
            ttk.Button(button_frame, text="🔄 更新", 
                      command=lambda: self._update_detailed_stats_display(text_widget)).pack(side=tk.LEFT)

        except Exception as e:
            messagebox.showerror("エラー", f"詳細統計表示エラー: {e}")
    
    def _display_stats_text(self, text_widget, stats: Dict[str, Any], optimization_stats: Dict[str, Any]):
        """統計テキスト表示"""
        text_widget.delete(1.0, tk.END)
        
        stats_text = "📊 詳細統計情報\n"
        stats_text += "=" * 50 + "\n\n"
        
        # 基本統計
        stats_text += f"📋 基本統計:\n"
        stats_text += f"  インデックス済みファイル: {stats.get('indexed_files', 0):,}件\n"
        stats_text += f"  検索実行回数: {stats.get('search_count', 0):,}回\n\n"
        
        # レイヤー統計
        layer_hits = stats.get('layer_hits', {})
        stats_text += f"🔍 レイヤー別ヒット数:\n"
        stats_text += f"  即座層: {layer_hits.get('immediate', 0):,}回\n"
        stats_text += f"  高速層: {layer_hits.get('hot', 0):,}回\n"
        stats_text += f"  完全層: {layer_hits.get('complete', 0):,}回\n\n"
        
        # キャッシュ統計
        cache_stats = stats.get('cache_statistics', {})
        stats_text += f"💾 キャッシュ統計:\n"
        stats_text += f"  即座層: {cache_stats.get('immediate_layer', 0):,}件\n"
        stats_text += f"  高速層: {cache_stats.get('hot_layer', 0):,}件\n"
        stats_text += f"  即座層サイズ: {cache_stats.get('immediate_size_mb', 0):.1f}MB\n"
        stats_text += f"  高速層サイズ: {cache_stats.get('hot_size_mb', 0):.1f}MB\n\n"
        
        # データベース統計
        db_stats = stats.get('database_statistics', {})
        stats_text += f"🗄️ データベース統計:\n"
        stats_text += f"  総ドキュメント数: {db_stats.get('total_documents', 0):,}件\n"
        stats_text += f"  データベース数: {db_stats.get('database_count', 0)}個\n\n"
        
        # パフォーマンス統計
        perf_stats = stats.get('search_performance', {})
        stats_text += f"⚡ パフォーマンス統計:\n"
        stats_text += f"  平均検索時間: {perf_stats.get('avg_search_time', 0):.4f}秒\n"
        stats_text += f"  総検索時間: {perf_stats.get('total_search_time', 0):.2f}秒\n\n"
        
        # システム統計
        system_stats = optimization_stats.get('system_status', {})
        stats_text += f"🔧 システム状態:\n"
        stats_text += f"  インデックス中: {'はい' if system_stats.get('indexing_in_progress', False) else 'いいえ'}\n"
        stats_text += f"  利用可能DB: {system_stats.get('databases_available', 0)}個\n"
        stats_text += f"  最適スレッド数: {system_stats.get('optimal_threads', 0)}\n"
        stats_text += f"  最適化回数: {optimization_stats.get('optimization_count', 0):,}回\n"
        
        text_widget.insert(tk.END, stats_text)
    
    def _update_detailed_stats_display(self, text_widget):
        """詳細統計表示更新"""
        try:
            stats = self.search_system.get_comprehensive_statistics()
            optimization_stats = self.search_system.get_optimization_statistics()
            self._display_stats_text(text_widget, stats, optimization_stats)
        except Exception as e:
            text_widget.delete(1.0, tk.END)
            text_widget.insert(tk.END, f"統計更新エラー: {e}")
    
    def clear_cache(self):
        """キャッシュクリア"""
        try:
            if messagebox.askyesno("確認", "すべてのキャッシュをクリアしますか？"):
                self.search_system.clear_cache()
                self.update_statistics()
                messagebox.showinfo("完了", "キャッシュをクリアしました")
        except Exception as e:
            messagebox.showerror("エラー", f"キャッシュクリアエラー: {e}")
    
    def index_folder(self):
        """フォルダインデックス"""
        try:
            folder = filedialog.askdirectory(title="インデックス対象フォルダを選択")
            
            if folder:
                # 確認ダイアログ
                folder_name = os.path.basename(folder) or folder
                if messagebox.askyesno("インデックス確認", 
                                     f"フォルダ '{folder_name}' をインデックスしますか？"):
                    
                    # プログレス表示
                    progress_window = tk.Toplevel(self.root)
                    progress_window.title("インデックス実行中")
                    progress_window.geometry("400x100")
                    progress_window.transient(self.root)
                    progress_window.grab_set()
                    
                    progress_label = ttk.Label(progress_window, text="インデックス処理中...")
                    progress_label.pack(expand=True)
                    
                    progress_bar = ttk.Progressbar(progress_window, mode='indeterminate')
                    progress_bar.pack(fill=tk.X, padx=20, pady=10)
                    progress_bar.start()
                    
                    def index_worker():
                        try:
                            result = self.search_system.bulk_index_directory_with_progress(folder)
                            
                            self.root.after(0, progress_window.destroy)
                            self.root.after(0, lambda: messagebox.showinfo(
                                "完了", 
                                f"インデックス完了!\n"
                                f"処理ファイル数: {result.get('success_count', 0):,}\n"
                                f"処理時間: {result.get('total_time', 0):.1f}秒"
                            ))
                            self.root.after(0, self.update_statistics)
                            
                        except Exception as e:
                            self.root.after(0, progress_window.destroy)
                            self.root.after(0, lambda: messagebox.showerror("エラー", f"インデックスエラー: {e}"))
                    
                    threading.Thread(target=index_worker, daemon=True).start()
                    
        except Exception as e:
            messagebox.showerror("エラー", f"フォルダインデックスエラー: {e}")
    
    def refresh_drives(self):
        """ドライブ一覧更新"""
        # 簡易実装：基本的なドライブ検出のみ
        try:
            drives = []
            if os.name == 'nt':  # Windows
                import string
                for drive_letter in string.ascii_uppercase:
                    drive_path = f"{drive_letter}:\\"
                    if os.path.exists(drive_path):
                        drives.append(drive_path)
            else:  # Linux/macOS
                drives = ["/"]
            
            self.drive_combo['values'] = drives
            if drives:
                self.drive_combo.current(0)
                self.on_drive_selected()
                
        except Exception as e:
            messagebox.showerror("エラー", f"ドライブ更新エラー: {e}")
    
    def on_drive_selected(self, event=None):
        """ドライブ選択時の処理"""
        if self.target_type_var.get() == "drive":
            selected_drive = self.drive_var.get()
            if selected_drive:
                self.target_info_var.set(f"ドライブ: {selected_drive}")
                self.bulk_index_btn.config(state="normal")
    
    def on_target_type_changed(self):
        """対象タイプ変更時の処理"""
        target_type = self.target_type_var.get()
        
        if target_type == "drive":
            self.drive_combo.config(state="readonly")
            self.refresh_drives_btn.config(state="normal")
            self.folder_browse_btn.config(state="disabled")
            self.refresh_drives()
        else:  # folder
            self.drive_combo.config(state="disabled")
            self.refresh_drives_btn.config(state="disabled")
            self.folder_browse_btn.config(state="normal")
            self.target_info_var.set("フォルダーを選択してください")
            self.bulk_index_btn.config(state="disabled")
    
    def browse_folder(self):
        """フォルダー選択"""
        try:
            folder_path = filedialog.askdirectory(title="インデックス対象フォルダを選択")
            
            if folder_path:
                self.selected_folder_path = folder_path
                display_path = folder_path
                if len(display_path) > 60:
                    display_path = "..." + display_path[-57:]
                
                self.folder_var.set(display_path)
                self.target_info_var.set(f"フォルダー: {os.path.basename(folder_path)}")
                self.bulk_index_btn.config(state="normal")
                
        except Exception as e:
            messagebox.showerror("エラー", f"フォルダー選択エラー: {e}")
    
    def start_bulk_indexing(self):
        """大容量インデックス開始"""
        if self.bulk_indexing_active:
            messagebox.showwarning("警告", "既にインデックス処理が実行中です")
            return
        
        # 対象パス取得
        target_type = self.target_type_var.get()
        if target_type == "drive":
            target_path = self.drive_var.get()
            target_name = f"ドライブ {target_path}"
        else:
            target_path = self.selected_folder_path
            target_name = f"フォルダー {Path(target_path).name}"
        
        if not target_path:
            messagebox.showerror("エラー", "対象を選択してください")
            return
        
        # 確認ダイアログ
        if not messagebox.askyesno("インデックス開始", f"{target_name} のインデックスを開始しますか？"):
            return
        
        # インデックス開始
        self.bulk_indexing_active = True
        self.bulk_index_btn.config(state="disabled", text="処理中...")
        self.cancel_index_btn.config(state="normal")
        self.bulk_progress_var.set("インデックス処理中...")
        
        def indexing_worker():
            try:
                result = self.search_system.bulk_index_directory_with_progress(target_path)
                
                self.root.after(0, lambda: messagebox.showinfo(
                    "完了", 
                    f"インデックス完了!\n"
                    f"処理ファイル数: {result.get('success_count', 0):,}\n"
                    f"処理時間: {result.get('total_time', 0):.1f}秒"
                ))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("エラー", f"インデックスエラー: {e}"))
            finally:
                self.bulk_indexing_active = False
                self.root.after(0, lambda: self.bulk_index_btn.config(state="normal", text="🚀 インデックス開始"))
                self.root.after(0, lambda: self.cancel_index_btn.config(state="disabled"))
                self.root.after(0, lambda: self.bulk_progress_var.set("完了"))
                self.root.after(0, self.update_statistics)
        
        self.current_indexing_thread = threading.Thread(target=indexing_worker, daemon=True)
        self.current_indexing_thread.start()
    
    def cancel_indexing(self):
        """インデックス処理キャンセル"""
        try:
            self.indexing_cancelled = True
            self.bulk_indexing_active = False
            self.bulk_index_btn.config(state="normal", text="🚀 インデックス開始")
            self.cancel_index_btn.config(state="disabled")
            self.bulk_progress_var.set("キャンセルしました")
            messagebox.showinfo("キャンセル", "インデックス処理をキャンセルしました")
            
        except Exception as e:
            messagebox.showerror("エラー", f"キャンセル処理エラー: {e}")
    
    def create_realtime_progress_window(self, title: str) -> tk.Toplevel:
        """リアルタイム進捗ウィンドウ作成"""
        progress_window = tk.Toplevel(self.root)
        progress_window.title(title)
        progress_window.geometry("500x300")
        progress_window.transient(self.root)
        progress_window.grab_set()
        
        main_frame = ttk.Frame(progress_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 進捗バー
        progress_bar = ttk.Progressbar(main_frame, mode='determinate')
        progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        # 情報表示
        info_text = tk.Text(main_frame, height=10, wrap=tk.WORD)
        info_scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=info_text.yview)
        info_text.configure(yscrollcommand=info_scrollbar.set)
        
        info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        info_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ウィンドウにウィジェットの参照を保存
        progress_window.progress_bar = progress_bar
        progress_window.info_text = info_text
        
        return progress_window
    
    def update_progress_window(self):
        """進捗ウィンドウ更新"""
        if not self.progress_window or not self.progress_window.winfo_exists():
            return
        
        try:
            progress_info = self.progress_tracker.get_progress_info()
            
            # 進捗バー更新
            progress_percent = progress_info['progress_percent']
            self.progress_window.progress_bar['value'] = progress_percent
            
            # 情報テキスト更新
            info_text = f"進捗: {progress_percent:.1f}%\n"
            info_text += f"処理済み: {progress_info['processed_files']:,}ファイル\n"
            info_text += f"成功: {progress_info['successful_files']:,}ファイル\n"
            info_text += f"エラー: {progress_info['error_files']:,}ファイル\n"
            info_text += f"処理速度: {progress_info['processing_speed']:.1f} files/sec\n"
            
            current_file = progress_info['current_file']
            if current_file:
                info_text += f"\n現在処理中:\n{os.path.basename(current_file)}"
            
            self.progress_window.info_text.delete(1.0, tk.END)
            self.progress_window.info_text.insert(tk.END, info_text)
            
            # 次回更新をスケジュール
            self.root.after(1000, self.update_progress_window)
            
        except Exception as e:
            debug_logger.error(f"進捗ウィンドウ更新エラー: {e}")
    
    def on_closing(self):
        """ウィンドウ閉鎖処理"""
        try:
            print("アプリケーション終了処理開始...")
            
            # 検索システムのシャットダウン
            if hasattr(self.search_system, 'shutdown'):
                self.search_system.shutdown()
            
            # ウィンドウを破棄
            self.root.quit()
            self.root.destroy()
            
        except Exception as e:
            print(f"終了処理エラー: {e}")
            try:
                self.root.quit()
            except:
                pass