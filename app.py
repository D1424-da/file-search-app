#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ファイル検索アプリケーション - メイン実行ファイル
100%仕様適合 超高速ライブ全文検索アプリ

モジュール化されたファイル検索アプリケーションのエントリーポイント
"""

import os
import sys
import time
import threading
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# モジュールのインポート
from modules.search import UltraFastFullCompliantSearchSystem
from modules.ui import UltraFastCompliantUI
from modules.utils import setup_debug_logger, auto_install_tesseract_engine

# デバッグロガー
debug_logger = setup_debug_logger('MainApp')

# OCRセットアップフラグ
ocr_setup_needed = True


def check_system_requirements():
    """システム要件チェック"""
    try:
        print("🔍 システム要件チェック中...")
        
        # Pythonバージョンチェック
        if sys.version_info < (3, 8):
            print("❌ Python 3.8以上が必要です")
            return False
        
        # 必要なモジュールの存在チェック
        required_modules = ['tkinter', 'sqlite3', 'threading', 'pathlib']
        missing_modules = []
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)
        
        if missing_modules:
            print(f"❌ 必要なモジュールが不足しています: {', '.join(missing_modules)}")
            return False
        
        print("✅ システム要件チェック完了")
        return True
        
    except Exception as e:
        print(f"❌ システム要件チェックエラー: {e}")
        return False


def display_startup_info():
    """起動情報表示"""
    print("\n" + "="*70)
    print("🚀 100%仕様適合 超高速ライブ全文検索アプリケーション")
    print("="*70)
    print("📋 機能:")
    print("  • 3層統合検索システム（即座層・高速層・完全層）")
    print("  • リアルタイム検索")
    print("  • 多形式ファイル対応（Word, Excel, PDF, テキスト, 画像OCR）")
    print("  • 並列インデックス処理")
    print("  • インテリジェントキャッシュ")
    print("  • 高速SQLite FTS5検索")
    print("="*70)
    
    # システム情報表示
    try:
        import psutil
        physical_cores = psutil.cpu_count(logical=False)
        logical_cores = psutil.cpu_count(logical=True)
        memory_gb = psutil.virtual_memory().total / (1024**3)
        print(f"💻 システム仕様: {physical_cores}物理コア/{logical_cores}論理コア, {memory_gb:.1f}GB RAM")
    except ImportError:
        print("💻 システム仕様: 詳細情報取得不可（psutilがインストールされていません）")
    except Exception as e:
        print(f"💻 システム仕様: 情報取得エラー - {e}")
    
    print(f"📁 プロジェクトルート: {project_root}")
    print()


def initialize_search_system():
    """検索システム初期化"""
    try:
        print("🔧 検索システム初期化中...")
        start_time = time.time()
        
        # 検索システムを初期化
        search_system = UltraFastFullCompliantSearchSystem(project_root)
        
        init_time = time.time() - start_time
        print(f"✅ 検索システム初期化完了 ({init_time:.2f}秒)")
        
        # システム設定サマリー表示
        print(f"⚡ システム設定:")
        print(f"  - データベース数: {search_system.db_count}個")
        print(f"  - 最適スレッド数: {search_system.optimal_threads}")
        print(f"  - 即座層キャッシュ上限: {search_system.max_immediate_cache:,}件")
        
        # 初期統計表示
        try:
            initial_stats = search_system.get_comprehensive_statistics()
            cache_stats = initial_stats.get('cache_statistics', {})
            db_stats = initial_stats.get('database_statistics', {})
            
            print(f"📊 初期統計:")
            print(f"  - 即座層: {cache_stats.get('immediate_layer', 0):,}件")
            print(f"  - 高速層: {cache_stats.get('hot_layer', 0):,}件") 
            print(f"  - 完全層: {db_stats.get('total_documents', 0):,}件")
        except Exception as e:
            debug_logger.warning(f"初期統計取得エラー: {e}")
        
        return search_system
        
    except Exception as e:
        print(f"❌ 検索システム初期化エラー: {e}")
        debug_logger.error(f"検索システム初期化エラー: {e}")
        raise


def initialize_ui(search_system):
    """UI初期化"""
    try:
        print("🎨 UI初期化中...")
        start_time = time.time()
        
        # UIを初期化
        app = UltraFastCompliantUI(search_system)
        
        init_time = time.time() - start_time
        print(f"✅ UI初期化完了 ({init_time:.2f}秒)")
        
        return app
        
    except Exception as e:
        print(f"❌ UI初期化エラー: {e}")
        debug_logger.error(f"UI初期化エラー: {e}")
        raise


def setup_ocr_if_needed(app):
    """OCR機能のセットアップ（必要な場合）"""
    if ocr_setup_needed:
        print("🔍 OCR機能の自動セットアップを開始...")
        try:
            # UI初期化後の遅延実行
            app.root.after(1000, lambda: threading.Thread(
                target=auto_install_tesseract_engine, 
                daemon=True
            ).start())
            print("✅ OCR自動セットアップをバックグラウンドで開始しました")
        except Exception as e:
            print(f"⚠️ OCR自動セットアップエラー: {e}")


def main():
    """メイン関数"""
    try:
        # 起動情報表示
        display_startup_info()
        
        # システム要件チェック
        if not check_system_requirements():
            print("❌ システム要件を満たしていません。アプリケーションを終了します。")
            sys.exit(1)
        
        # 検索システム初期化
        search_system = initialize_search_system()
        
        # UI初期化
        app = initialize_ui(search_system)
        
        # OCR自動セットアップ
        setup_ocr_if_needed(app)
        
        # 起動完了メッセージ
        print("🎯 アプリケーション準備完了")
        print("💡 超並列処理、メガキャッシュ最適化、ゼロ待機時間が有効です")
        print("🔍 検索を開始してください！")
        print()
        
        debug_logger.info("アプリケーション起動完了 - UIメインループ開始")
        
        # 起動後統計更新（遅延実行）
        app.root.after(1000, app.update_statistics)  # 1秒後
        app.root.after(3000, app.update_statistics)  # 3秒後（安全性確保）
        
        # UIメインループ開始
        app.root.mainloop()
        
    except KeyboardInterrupt:
        print("\n⏹️ ユーザーによる中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ アプリケーション起動エラー: {e}")
        debug_logger.error(f"アプリケーション起動エラー: {e}")
        
        # エラーの詳細をデバッグログに記録
        import traceback
        debug_logger.error("エラーの詳細:")
        debug_logger.error(traceback.format_exc())
        
        # ユーザー向けエラーメッセージ
        print("\nアプリケーションでエラーが発生しました。")
        print("詳細はログファイルを確認してください。")
        
        sys.exit(1)


if __name__ == "__main__":
    main()