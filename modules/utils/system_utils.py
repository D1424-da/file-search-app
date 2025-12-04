#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
システムユーティリティ
システムリソース管理とテキスト正規化
"""

import os
import time
import threading
import unicodedata
import subprocess
import platform
from typing import List, Tuple


def safe_truncate_utf8(text: str, max_length: int) -> str:
    """UTF-8文字列を安全に切り取る（日本語・マルチバイト文字対応）"""
    if not text or len(text) <= max_length:
        return text
    
    # 文字境界で安全に切り取り
    truncated = text[:max_length]
    
    # UTF-8バイト列として正常かチェック
    try:
        truncated.encode('utf-8')
        return truncated
    except UnicodeEncodeError:
        # 最後の文字が不完全な場合、1文字ずつ削っていく
        for i in range(1, min(4, max_length) + 1):  # 最大4バイトまでチェック
            try:
                safe_text = text[:max_length - i]
                safe_text.encode('utf-8')
                return safe_text
            except UnicodeEncodeError:
                continue
        
        # それでもダメなら空文字列
        return ""


def normalize_search_text_ultra(text: str) -> Tuple[str, str, str, List[str]]:
    """
    超高速検索用テキスト正規化（日本語FTS5対応強化版）
    
    Args:
        text (str): 検索テキスト
        
    Returns:
        tuple: (半角版, 全角版, 正規化版, パターンリスト)
    """
    if not text:
        return '', '', '', []

    patterns = []

    # 基本パターン
    patterns.append(text)

    # 半角版（NFKC正規化）
    if unicodedata is not None:
        half_width = unicodedata.normalize('NFKC', text)
        if half_width != text:
            patterns.append(half_width)
    else:
        half_width = text

    # 全角版（半角英数を全角に変換）
    full_width = ''
    for char in text:
        if '!' <= char <= '~':
            full_width += chr(ord(char) + 0xFEE0)
        else:
            full_width += char
    if full_width != text:
        patterns.append(full_width)

    # 正規化版（大文字小文字統一）
    normalized = text.lower()
    if normalized != text:
        patterns.append(normalized)

    # 日本語FTS5対応: 個別文字パターンも追加
    if len(text) >= 2:
        # 各文字を個別に追加（部分マッチ用）
        for i in range(len(text)):
            char = text[i]
            if char not in patterns and len(char.strip()) > 0:
                patterns.append(char)
        
        # 2文字ずつの組み合わせ（bi-gram）
        for i in range(len(text) - 1):
            bigram = text[i:i+2]
            if bigram not in patterns:
                patterns.append(bigram)

    # ひらがな→カタカナ変換
    hiragana_to_katakana = ''
    for char in normalized:
        if 'ぁ' <= char <= 'ゖ':  # ひらがな範囲
            hiragana_to_katakana += chr(ord(char) + 0x60)
        else:
            hiragana_to_katakana += char

    if hiragana_to_katakana != normalized:
        patterns.append(hiragana_to_katakana)

    # カタカナ→ひらがな変換
    katakana_to_hiragana = ''
    for char in normalized:
        if 'ァ' <= char <= 'ヶ':  # カタカナ範囲
            katakana_to_hiragana += chr(ord(char) - 0x60)
        else:
            katakana_to_hiragana += char

    if katakana_to_hiragana != normalized:
        patterns.append(katakana_to_hiragana)

    # スペース区切りの各単語にも適用
    words = text.split()
    if len(words) > 1:
        for word in words:
            if word not in patterns:
                patterns.append(word)
            # 各単語の半角全角変換も追加
            if unicodedata is not None:
                word_half = unicodedata.normalize('NFKC', word)
                if word_half not in patterns:
                    patterns.append(word_half)

    # 重複除去とソート（長い順だが、元の文字列を最優先）
    unique_patterns = []
    unique_patterns.append(text)  # 元のテキストを最優先
    
    for pattern in patterns:
        if pattern not in unique_patterns and pattern != text:
            unique_patterns.append(pattern)
    
    # 長さでソート（ただし、元のテキストは最初に保持）
    first_pattern = unique_patterns[0]
    remaining_patterns = sorted(unique_patterns[1:], key=len, reverse=True)
    final_patterns = [first_pattern] + remaining_patterns

    return half_width, full_width, hiragana_to_katakana, final_patterns


def enhanced_search_match(text: str, query_patterns: List[str]) -> bool:
    """
    拡張検索マッチング（半角全角対応強化版）
    
    Args:
        text (str): 検索対象テキスト
        query_patterns (list): 検索パターンリスト
        
    Returns:
        bool: マッチするかどうか
    """
    if not text or not query_patterns:
        return False

    # テキストも複数パターンで正規化
    text_lower = text.lower()
    text_normalized = unicodedata.normalize('NFKC', text_lower)

    # テキストのひらがな→カタカナ変換
    text_hiragana_to_katakana = ''
    for char in text_lower:
        if 'ぁ' <= char <= 'ゖ':
            text_hiragana_to_katakana += chr(ord(char) + 0x60)
        else:
            text_hiragana_to_katakana += char

    # テキストのカタカナ→ひらがな変換
    text_katakana_to_hiragana = ''
    for char in text_lower:
        if 'ァ' <= char <= 'ヶ':
            text_katakana_to_hiragana += chr(ord(char) - 0x60)
        else:
            text_katakana_to_hiragana += char

    # テキストの正規化バリエーション
    text_variants = [
        text, text_lower, text_normalized, text_hiragana_to_katakana, text_katakana_to_hiragana
    ]

    # 各パターンでマッチングを試行
    for pattern in query_patterns:
        pattern_lower = pattern.lower()
        pattern_normalized = unicodedata.normalize('NFKC', pattern_lower)

        # パターンのひらがな→カタカナ変換
        pattern_hiragana_to_katakana = ''
        for char in pattern_lower:
            if 'ぁ' <= char <= 'ゖ':
                pattern_hiragana_to_katakana += chr(ord(char) + 0x60)
            else:
                pattern_hiragana_to_katakana += char

        # パターンのカタカナ→ひらがな変換
        pattern_katakana_to_hiragana = ''
        for char in pattern_lower:
            if 'ァ' <= char <= 'ヶ':
                pattern_katakana_to_hiragana += chr(ord(char) - 0x60)
            else:
                pattern_katakana_to_hiragana += char

        pattern_variants = [
            pattern, pattern_lower, pattern_normalized, pattern_hiragana_to_katakana,
            pattern_katakana_to_hiragana
        ]

        # 精密マッチング: 3文字以上のパターンで検索（より厳密に）
        for text_variant in text_variants:
            for pattern_variant in pattern_variants:
                # 元のクエリが3文字以上の場合は3文字以上パターンを優先
                if len(query_patterns[0]) >= 3 and len(pattern_variant.strip()) < 3:
                    continue
                # 元のクエリが2文字の場合は2文字以上パターンを対象
                elif len(query_patterns[0]) == 2 and len(pattern_variant.strip()) < 2:
                    continue
                # 1文字のクエリは1文字以上パターンを対象
                elif len(query_patterns[0]) == 1 and len(pattern_variant.strip()) < 1:
                    continue
                
                # 完全一致を優先
                if pattern_variant == text_variant:
                    return True
                
                # 部分一致 - 元のクエリ長に応じて厳密性を調整
                if len(query_patterns[0]) >= 4:
                    # 4文字以上の場合は厳密マッチング（完全一致優先）
                    if pattern_variant == query_patterns[0] and pattern_variant in text_variant:
                        return True
                elif len(pattern_variant) >= 2 and pattern_variant in text_variant:
                    return True

    return False


def get_optimal_thread_count():
    """最適なスレッド数を取得（超高速版・psutil依存なし）"""
    try:
        # psutilが利用可能な場合の高精度設定
        try:
            import psutil
            # 物理コア数と論理コア数を取得
            physical_cores = psutil.cpu_count(logical=False) or 2
            logical_cores = psutil.cpu_count(logical=True) or 4
            
            # 現在のCPU使用率を確認（超高速：0.1秒間隔）
            cpu_usage = psutil.cpu_percent(interval=0.1)
            
            # 利用可能メモリも考慮
            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024**3)
            
            print(f"🔧 システム情報取得完了:")
            print(f"  物理コア: {physical_cores}, 論理コア: {logical_cores}")
            print(f"  CPU使用率: {cpu_usage:.1f}%, 利用可能メモリ: {available_gb:.1f}GB")
        except ImportError:
            # psutilなしでのフォールバック（os.cpu_count使用）
            logical_cores = os.cpu_count() or 4
            physical_cores = max(logical_cores // 2, 2)  # 概算値
            cpu_usage = 25.0  # 標準的な値を想定
            available_gb = 8.0  # 標準的な値を想定
            
            print(f"🔧 システム情報（推定）:")
            print(f"  推定物理コア: {physical_cores}, 論理コア: {logical_cores}")
            print(f"  推定CPU使用率: {cpu_usage:.1f}%, 推定利用可能メモリ: {available_gb:.1f}GB")
        
        # 最大パフォーマンス設定（他アプリ使用考慮）
        if physical_cores >= 16:  # 16コア以上（ワークステーション級）
            if cpu_usage < 20 and available_gb > 8:
                threads = min(physical_cores - 2, 16)  # 最大16スレッド
            elif cpu_usage < 40:
                threads = min(physical_cores - 4, 12)  # 最大12スレッド
            else:
                threads = min(physical_cores - 6, 8)   # 最大8スレッド
                
        elif physical_cores >= 12:  # 12-15コア（高性能CPU）
            if cpu_usage < 20 and available_gb > 6:
                threads = min(physical_cores - 2, 12)  # 最大12スレッド
            elif cpu_usage < 40:
                threads = min(physical_cores - 3, 10)  # 最大10スレッド
            else:
                threads = min(physical_cores - 4, 8)   # 最大8スレッド
                
        elif physical_cores >= 8:  # 8-11コア（中高性能CPU）
            if cpu_usage < 25 and available_gb > 4:
                threads = min(physical_cores - 1, 10)  # 最大10スレッド
            elif cpu_usage < 50:
                threads = min(physical_cores - 2, 8)   # 最大8スレッド
            else:
                threads = min(physical_cores - 3, 6)   # 最大6スレッド
                
        elif physical_cores >= 6:  # 6-7コア（中性能CPU）
            if cpu_usage < 25 and available_gb > 3:
                threads = min(physical_cores - 1, 8)   # 最大8スレッド
            elif cpu_usage < 50:
                threads = min(physical_cores - 1, 6)   # 最大6スレッド
            else:
                threads = min(physical_cores - 2, 4)   # 最大4スレッド
                
        elif physical_cores >= 4:  # 4-5コア（標準CPU）
            if cpu_usage < 20 and available_gb > 2:
                threads = min(physical_cores, 6)       # 最大6スレッド
            elif cpu_usage < 40:
                threads = min(physical_cores, 5)       # 最大5スレッド
            else:
                threads = min(physical_cores - 1, 3)   # 最大3スレッド
        else:
            # 4コア未満は保守的に
            threads = max(physical_cores - 1, 2)
        
        # 最終的な安全チェック
        threads = max(min(threads, 16), 2)  # 2-16スレッドの範囲
        
        print(f"  決定スレッド数: {threads} (最大パフォーマンス優先)")
        
        return threads
        
    except Exception as e:
        print(f"⚠️ スレッド数計算エラー: {e}")
        return 4  # デフォルト値


def setup_debug_logger(name: str = 'FileSearchApp'):
    """デバッグログ設定（重複防止版）"""
    import logging
    
    logger = logging.getLogger(name)

    # 既存のハンドラーをクリア（重複防止）
    if logger.handlers:
        logger.handlers.clear()

    logger.setLevel(logging.DEBUG)

    # ファイルハンドラー（上書きモード）
    file_handler = logging.FileHandler('file_search_app.log', mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    # フォーマッター（シンプル版）
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    # 親ロガーへの伝播を無効化（重複出力防止）
    logger.propagate = False

    return logger


def auto_install_tesseract_engine():
    """Tesseract OCRエンジンの自動インストール"""
    try:
        print("🔍 Tesseract OCR自動セットアップ開始...")
        
        # 既存のTesseractをチェック
        try:
            result = subprocess.run(['tesseract', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("✅ Tesseract OCRエンジンは既にインストール済みです")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            pass
        
        # OS別インストール
        system = platform.system().lower()
        
        if system == 'windows':
            print("🔧 Windows用Tesseractの自動インストールを実行中...")
            # Chocolateyまたは直接ダウンロードでのインストールを試行
            try:
                # Chocolateyを試す
                subprocess.run(['choco', 'install', 'tesseract', '-y'], 
                              check=True, timeout=300)
                print("✅ Tesseract OCRインストール完了 (Chocolatey)")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                print("⚠️ Chocolateyが利用できません。手動インストールが必要です")
                print("   👉 https://github.com/UB-Mannheim/tesseract/wiki からダウンロードしてください")
                
        elif system in ['linux', 'darwin']:  # Linux or macOS
            print(f"🔧 {system}用Tesseractの自動インストールを実行中...")
            try:
                if system == 'linux':
                    # Ubuntu/Debian系
                    subprocess.run(['sudo', 'apt-get', 'update'], check=True, timeout=60)
                    subprocess.run(['sudo', 'apt-get', 'install', '-y', 'tesseract-ocr'], 
                                  check=True, timeout=300)
                else:  # macOS
                    # Homebrew
                    subprocess.run(['brew', 'install', 'tesseract'], check=True, timeout=300)
                
                print("✅ Tesseract OCRインストール完了")
                return True
                
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                print("⚠️ 自動インストールに失敗しました。手動インストールが必要です")
        
        return False
        
    except Exception as e:
        print(f"❌ Tesseract自動セットアップエラー: {e}")
        return False