#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Officeドキュメント抽出器
Word、Excelファイルの内容抽出
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def extract_docx_content(file_path: str) -> str:
    """Word文書抽出（新旧形式対応・エラーハンドリング強化）"""
    try:
        # ファイル拡張子チェック
        file_extension = os.path.splitext(file_path)[1].lower()
        
        # 古い形式のWordファイル（.doc）の場合は処理をスキップ
        if file_extension in ['.doc', '.dot']:
            print(f"⚠️ 古い形式のWordファイルはサポートされていません: {os.path.basename(file_path)}")
            return ""

        # ファイルサイズチェック（空ファイル回避）
        if os.path.getsize(file_path) < 100:  # 100バイト未満は無効
            print(f"⚠️ ファイルサイズが小さすぎます: {os.path.basename(file_path)}")
            return ""

        content = []

        # ZIPファイルかどうかを事前チェック
        try:
            with zipfile.ZipFile(file_path, 'r') as test_zip:
                # word/document.xmlが存在するかチェック
                if 'word/document.xml' not in test_zip.namelist():
                    print(f"⚠️ 有効なWordファイルではありません: {os.path.basename(file_path)}")
                    return ""
        except zipfile.BadZipFile:
            return ""  # ZIPファイルでない場合は静かに終了

        with zipfile.ZipFile(file_path, 'r') as docx:
            xml_content = docx.read('word/document.xml')
            root = ET.fromstring(xml_content)

            # テキスト要素抽出
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    content.append(elem.text.strip())

        return ' '.join(content)

    except zipfile.BadZipFile:
        print(f"⚠️ Wordファイルが不正なZIP形式です: {os.path.basename(file_path)}")
        return ""
    except Exception as e:
        # より詳細なエラー情報を提供
        if "zip file" in str(e).lower():
            print(f"⚠️ WordファイルのZIP形式エラー: {os.path.basename(file_path)}")
        else:
            print(f"⚠️ Word抽出エラー: {os.path.basename(file_path)} - {e}")
        return ""


def extract_xlsx_content(file_path: str) -> str:
    """Excel文書抽出（新旧形式対応）"""
    try:
        # ファイル拡張子チェック
        file_extension = os.path.splitext(file_path)[1].lower()
        
        # 古い形式のExcelファイル（.xls）の場合は処理をスキップ
        if file_extension in ['.xls', '.xlt']:
            print(f"⚠️ 古い形式のExcelファイルはサポートされていません: {os.path.basename(file_path)}")
            return ""
        
        # ZIPファイルかどうかを事前チェック
        try:
            with zipfile.ZipFile(file_path, 'r') as test_zip:
                # Excel形式の必須ファイルが存在するかチェック
                if 'xl/workbook.xml' not in test_zip.namelist():
                    print(f"⚠️ 有効なExcelファイルではありません: {os.path.basename(file_path)}")
                    return ""
        except zipfile.BadZipFile:
            print(f"⚠️ ZIPファイルでないため処理をスキップ: {os.path.basename(file_path)}")
            return ""
        except Exception as e:
            print(f"⚠️ Excelファイル検証エラー: {os.path.basename(file_path)} - {e}")
            return ""
        
        content = []
        with zipfile.ZipFile(file_path, 'r') as xlsx:
            # 共有文字列取得
            try:
                shared_strings_xml = xlsx.read('xl/sharedStrings.xml')
                shared_root = ET.fromstring(shared_strings_xml)
                shared_strings = [elem.text or '' for elem in shared_root.iter() if elem.text]
            except:
                shared_strings = []

            # ワークシート処理
            try:
                workbook_xml = xlsx.read('xl/workbook.xml')
                wb_root = ET.fromstring(workbook_xml)

                sheet_files = [f for f in xlsx.namelist() if f.startswith('xl/worksheets/')]

                for sheet_file in sheet_files:
                    sheet_xml = xlsx.read(sheet_file)
                    sheet_root = ET.fromstring(sheet_xml)

                    for elem in sheet_root.iter():
                        if elem.text:
                            # 数値チェックを強化（丸数字等を除外）
                            text = elem.text.strip()
                            if text and text.isascii() and text.isdigit():
                                try:
                                    index = int(text)
                                    if 0 <= index < len(shared_strings):
                                        content.append(shared_strings[index])
                                except (ValueError, IndexError):
                                    pass
                            else:
                                # 直接のテキスト内容を追加（丸数字等を除外）
                                if text and len(text) > 1 and not any(char in text for char in '①②③④⑤⑥⑦⑧⑨⑩'):
                                    content.append(text)

            except Exception as e:
                print(f"⚠️ Excelシート処理エラー: {e}")

        return ' '.join(content)

    except zipfile.BadZipFile:
        print(f"⚠️ Excelファイルが不正なZIP形式です: {os.path.basename(file_path)}")
        return ""
    except Exception as e:
        # より詳細なエラー情報を提供
        if "zip file" in str(e).lower():
            print(f"⚠️ ExcelファイルのZIP形式エラー: {os.path.basename(file_path)}")
        else:
            print(f"⚠️ Excel抽出エラー: {os.path.basename(file_path)} - {e}")
        return ""


def extract_doc_content(file_path: str) -> str:
    """古い形式のWord(.doc)ファイル抽出"""
    try:
        # ファイルの存在確認
        if not os.path.exists(file_path):
            print(f"⚠️ DOCファイルが見つかりません: {file_path}")
            return ""
        
        # ファイルサイズの確認
        try:
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                print(f"⚠️ DOCファイルが空です: {os.path.basename(file_path)}")
                return ""
            elif file_size > 100 * 1024 * 1024:  # 100MB制限
                print(f"⚠️ DOCファイルが大きすぎます ({file_size/1024/1024:.1f}MB): {os.path.basename(file_path)}")
                return ""
        except OSError as size_error:
            print(f"⚠️ DOCファイルサイズ取得エラー: {os.path.basename(file_path)} - {size_error}")
            return ""
        
        print(f"🔄 DOC処理開始: {os.path.basename(file_path)} ({file_size/1024:.1f}KB)")
        
        # 1. docx2txtを試行（一部のDOCファイルにも対応）
        try:
            import docx2txt
            content = docx2txt.process(file_path)
            if content and content.strip():
                content_preview = content.strip()[:100] + "..." if len(content.strip()) > 100 else content.strip()
                print(f"✅ docx2txtでDOC処理成功: {os.path.basename(file_path)} - 長さ: {len(content)} 文字")
                print(f"   内容プレビュー: {content_preview}")
                return content.strip()
        except ImportError:
            print(f"⚠️ docx2txtライブラリが必要です: {os.path.basename(file_path)}")
        except Exception as docx2txt_error:
            print(f"⚠️ docx2txt処理エラー: {os.path.basename(file_path)} - {docx2txt_error}")
        
        # 2. olefileで基本情報を取得（フォールバック）
        try:
            import olefile
            if olefile.isOleFile(file_path):
                print(f"📝 OLE2形式のDOCファイルを検出: {os.path.basename(file_path)}")
                # olefileによる基本的な情報抽出
                with olefile.OleFileIO(file_path) as ole:
                    # Word文書の基本情報を取得
                    if ole.exists('WordDocument'):
                        # 基本的なファイル情報のみ返す（安全な方法）
                        return f"Microsoft Word文書 - {os.path.basename(file_path)} - OLE2形式"
                    else:
                        return f"Microsoft Word文書 - {os.path.basename(file_path)}"
        except ImportError:
            print(f"⚠️ olefileライブラリが必要です: {os.path.basename(file_path)}")
        except Exception as olefile_error:
            print(f"⚠️ olefile処理エラー: {os.path.basename(file_path)} - {olefile_error}")
        
        # 3. 基本的なバイナリ解析による文字列抽出（最後の手段）
        try:
            print(f"🔍 バイナリ解析を試行: {os.path.basename(file_path)}")
            with open(file_path, 'rb') as f:
                data = f.read(min(file_size, 1024*1024))  # 最大1MB読み込み
                
            # 可読文字のみを抽出（基本的な方法）
            text_content = []
            current_word = []
            
            for byte in data:
                char = chr(byte) if 32 <= byte <= 126 or byte in [9, 10, 13] else None
                if char:
                    if char.isalnum() or char in ' .,!?-_()[]{}":;':
                        current_word.append(char)
                    elif current_word:
                        word = ''.join(current_word)
                        if len(word) >= 3:  # 3文字以上の単語のみ
                            text_content.append(word)
                        current_word = []
                elif current_word:
                    word = ''.join(current_word)
                    if len(word) >= 3:
                        text_content.append(word)
                    current_word = []
            
            if text_content:
                extracted_text = ' '.join(text_content[:50])  # 最初の50単語
                if extracted_text.strip():
                    print(f"✅ バイナリ解析成功: {os.path.basename(file_path)} - {len(extracted_text)} 文字")
                    return f"{extracted_text} - {os.path.basename(file_path)}"
                    
        except Exception as binary_error:
            print(f"⚠️ バイナリ解析エラー: {os.path.basename(file_path)} - {binary_error}")
        
        # 4. 全ての方法が失敗した場合は基本情報のみ
        print(f"📝 DOC内容抽出失敗、ファイル名のみインデックス: {os.path.basename(file_path)}")
        return f"Microsoft Word文書 - {os.path.basename(file_path)}"
        
    except Exception as e:
        print(f"⚠️ DOC抽出エラー: {os.path.basename(file_path)} - {e}")
        return ""


def extract_xls_content(file_path: str) -> str:
    """古い形式のExcel(.xls)ファイル抽出"""
    try:
        try:
            import xlrd
        except ImportError:
            print(f"⚠️ xlrdライブラリが必要です（古い形式Excel用）: {os.path.basename(file_path)}")
            return ""
        
        content = []
        
        # xlrdでExcelファイルを開く
        workbook = xlrd.open_workbook(file_path)
        
        # 全シートを処理
        for sheet_index in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(sheet_index)
            
            # シート名を追加
            sheet_name = workbook.sheet_names()[sheet_index]
            content.append(f"[シート: {sheet_name}]")
            
            # 各行・列を処理
            for row_idx in range(sheet.nrows):
                row_values = []
                for col_idx in range(sheet.ncols):
                    cell = sheet.cell(row_idx, col_idx)
                    
                    # セルタイプに応じて値を取得
                    if cell.ctype == xlrd.XL_CELL_TEXT:
                        value = cell.value.strip()
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        # 数値の場合、整数なら整数として表示
                        if cell.value == int(cell.value):
                            value = str(int(cell.value))
                        else:
                            value = str(cell.value)
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        value = str(bool(cell.value))
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        # 日付の場合
                        date_tuple = xlrd.xldate_as_tuple(cell.value, workbook.datemode)
                        value = f"{date_tuple[0]}/{date_tuple[1]}/{date_tuple[2]}"
                    else:
                        value = str(cell.value) if cell.value else ""
                    
                    if value and len(value.strip()) > 0:
                        row_values.append(value.strip())
                
                if row_values:
                    content.append(' '.join(row_values))
        
        result = '\n'.join(content)
        if result:
            print(f"📊 古い形式Excel処理完了: {os.path.basename(file_path)}")
        return result
        
    except Exception as e:
        print(f"⚠️ 古い形式Excel抽出エラー: {os.path.basename(file_path)} - {e}")
        return ""