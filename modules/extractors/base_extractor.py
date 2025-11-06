#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本ファイル抽出器
テキストファイルとZIPファイルの内容抽出
"""

import os
import zipfile
from pathlib import Path
from typing import Optional


def extract_txt_content(file_path: str) -> str:
    """テキストファイル抽出"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except:
        try:
            with open(file_path, 'r', encoding='cp932', errors='ignore') as f:
                return f.read()
        except:
            return ""


def extract_zip_content(file_path: str) -> str:
    """ZIPファイル内のテキストファイル抽出"""
    try:
        content = []
        max_files = 50  # 処理するファイル数の上限
        max_file_size = 1024 * 1024  # 1ファイルあたりの最大サイズ（1MB）
        processed_files = 0
        
        # サポートするテキストファイル拡張子
        text_extensions = {'.txt', '.md', '.log', '.csv', '.json', '.xml', '.html', '.htm', '.py', '.js', '.css'}
        
        with zipfile.ZipFile(file_path, 'r') as zip_file:
            for file_info in zip_file.infolist():
                # ディレクトリをスキップ
                if file_info.is_dir():
                    continue
                
                # ファイル数制限チェック
                if processed_files >= max_files:
                    print(f"📦 ZIPファイル内ファイル数制限到達: {max_files}件")
                    break
                
                # ファイル名とサイズチェック
                file_name = file_info.filename
                file_ext = os.path.splitext(file_name)[1].lower()
                
                # テキストファイルのみ処理
                if file_ext not in text_extensions:
                    continue
                
                # ファイルサイズチェック
                if file_info.file_size > max_file_size:
                    print(f"📦 ZIPファイル内の大きなファイルをスキップ: {file_name} ({file_info.file_size} bytes)")
                    continue
                
                try:
                    # ファイル内容を抽出
                    with zip_file.open(file_info) as inner_file:
                        # エンコーディング自動検出
                        raw_data = inner_file.read()
                        
                        # UTF-8で試行
                        try:
                            text_content = raw_data.decode('utf-8')
                        except UnicodeDecodeError:
                            # Shift_JISで試行
                            try:
                                text_content = raw_data.decode('shift_jis')
                            except UnicodeDecodeError:
                                # chardetライブラリで自動検出
                                try:
                                    import chardet
                                    detected = chardet.detect(raw_data)
                                    if detected['encoding']:
                                        text_content = raw_data.decode(detected['encoding'])
                                    else:
                                        text_content = raw_data.decode('utf-8', errors='ignore')
                                except (ImportError, UnicodeDecodeError):
                                    text_content = raw_data.decode('utf-8', errors='ignore')
                        
                        # テキスト内容を追加（ファイル名も含める）
                        if text_content.strip():
                            content.append(f"[{file_name}]\n{text_content.strip()}")
                            processed_files += 1
                
                except Exception as inner_error:
                    print(f"📦 ZIPファイル内ファイル処理エラー {file_name}: {inner_error}")
                    continue
        
        result = '\n\n'.join(content)
        if result:
            print(f"📦 ZIPファイル処理完了: {processed_files}個のテキストファイルを抽出")
        return result
        
    except zipfile.BadZipFile:
        print(f"⚠️ 不正なZIPファイル: {file_path}")
        return ""
    except Exception as e:
        print(f"⚠️ ZIP抽出エラー: {e}")
        return ""