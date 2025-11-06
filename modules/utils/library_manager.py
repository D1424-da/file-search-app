#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ライブラリ管理ユーティリティ
自動ライブラリインストールとチェック機能
"""

import sys
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List, Tuple


def load_auto_install_settings() -> Dict[str, Any]:
    """自動インストール設定を読み込み"""
    try:
        settings_path = Path(__file__).parent.parent.parent / "config" / "auto_install_settings.json"
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # デフォルト設定
            return {
                "auto_install": {
                    "enabled": True,
                    "ask_permission": True,
                    "python_libraries": {"auto_install": True},
                    "tesseract_ocr": {"auto_install": True, "ask_permission": True}
                }
            }
    except Exception as e:
        print(f"⚠️ 設定ファイル読み込みエラー: {e}")
        return {"auto_install": {"enabled": False}}


def safe_subprocess_run(cmd: List[str], description: str = "コマンド", 
                       timeout: int = 30, **kwargs) -> Tuple[subprocess.CompletedProcess, str]:
    """エンコーディングセーフなsubprocess実行"""
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout,
            encoding='utf-8',
            errors='ignore',
            **kwargs
        )
        return result, None
        
    except subprocess.TimeoutExpired:
        return None, f"{description}がタイムアウト（{timeout}秒）しました"
    except FileNotFoundError:
        return None, f"{description}のコマンドが見つかりません"
    except UnicodeDecodeError as e:
        return None, f"{description}の出力エンコーディングエラー: {str(e)[:100]}..."
    except Exception as e:
        return None, f"{description}実行エラー: {str(e)[:100]}..."


def check_library_availability() -> Dict[str, bool]:
    """ライブラリの利用可能性をチェック"""
    libraries = {}
    
    # psutil
    try:
        import psutil
        libraries['psutil'] = True
    except ImportError:
        libraries['psutil'] = False
    
    # PyMuPDF
    try:
        import fitz
        libraries['fitz'] = True
    except ImportError:
        libraries['fitz'] = False
    
    # openpyxl
    try:
        import openpyxl
        libraries['openpyxl'] = True
    except ImportError:
        libraries['openpyxl'] = False
    
    # python-docx
    try:
        import docx
        libraries['docx'] = True
    except ImportError:
        libraries['docx'] = False
    
    # xlrd
    try:
        import xlrd
        libraries['xlrd'] = True
    except ImportError:
        libraries['xlrd'] = False
    
    # docx2txt
    try:
        import docx2txt
        libraries['docx2txt'] = True
    except ImportError:
        libraries['docx2txt'] = False
    
    # olefile
    try:
        import olefile
        libraries['olefile'] = True
    except ImportError:
        libraries['olefile'] = False
    
    # chardet
    try:
        import chardet
        libraries['chardet'] = True
    except ImportError:
        libraries['chardet'] = False
    
    # Pillow
    try:
        from PIL import Image
        libraries['Pillow'] = True
    except ImportError:
        libraries['Pillow'] = False
    
    # pytesseract
    try:
        import pytesseract
        libraries['pytesseract'] = True
    except ImportError:
        libraries['pytesseract'] = False
    
    # opencv-python
    try:
        import cv2
        libraries['opencv-python'] = True
    except ImportError:
        libraries['opencv-python'] = False
    
    return libraries


def ensure_required_libraries():
    """必要なライブラリを超高速チェック・自動インストール"""
    settings = load_auto_install_settings()
    auto_install_enabled = settings.get("auto_install", {}).get("enabled", True)
    
    # ライブラリ状態確認
    library_status = check_library_availability()
    
    installed_libraries = [name for name, available in library_status.items() if available]
    missing_libraries = [name for name, available in library_status.items() if not available]
    
    # 自動インストールが有効な場合のみ実行
    if auto_install_enabled and missing_libraries:
        print(f"📦 {len(missing_libraries)}個のライブラリを非同期インストール中...")
        
        def background_install():
            """バックグラウンド非同期インストール"""
            for lib in missing_libraries:
                print(f"📦 {lib} をインストール中...")
                
                pip_cmd = [sys.executable, '-m', 'pip', 'install', lib, 
                          '--quiet', '--disable-pip-version-check', '--no-warn-script-location']
                result, error = safe_subprocess_run(pip_cmd, f"{lib}インストール", timeout=60)
                
                if result and result.returncode == 0:
                    print(f"✅ {lib} インストール完了")
                elif error:
                    print(f"⚠️ {lib} インストール失敗（機能は制限されます）: {error}")
                elif result:
                    print(f"⚠️ {lib} インストール失敗（機能は制限されます） - 終了コード: {result.returncode}")
                    if result.stderr:
                        error_msg = result.stderr[:200] if len(result.stderr) > 200 else result.stderr
                        print(f"   詳細: {error_msg}...")
                else:
                    print(f"⚠️ {lib} インストール中に予期しない問題が発生しました")
        
        # デーモンスレッドで非同期実行
        threading.Thread(target=background_install, daemon=True).start()
    elif not auto_install_enabled and missing_libraries:
        print(f"ℹ️ {len(missing_libraries)}個のライブラリが不足していますが、自動インストールは無効です")
        print(f"   不足ライブラリ: {', '.join(missing_libraries)}")
    else:
        print(f"✅ 全ライブラリ利用可能 ({len(installed_libraries)}個) - 最大パフォーマンスモード")
    
    return installed_libraries, missing_libraries