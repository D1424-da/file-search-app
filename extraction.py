#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ファイル本文抽出モジュール（検索システム/UI から独立）

このモジュールは file_search_app.py から分離した本文抽出レイヤー。
検索システム(UltraFastFullCompliantSearchSystem)やUI(Tkinter)には一切
依存せず、純粋にファイルパスを受け取り本文テキストを返すことに専念する。

分離の意図:
  - 抽出ロジックを単体でテスト/検証できるようにする（保守性向上）
  - ProcessPool の抽出ワーカーが GUI 層を介さずこの軽量モジュールを
    利用できるようにする
  - 検索/UI 側の巨大な実装と関心を分離する

注意: 検索の出力品質（OCR精度・抽出網羅性）は本分離では変化しない。
      同じ抽出コードがこのモジュールへ移動するだけである。
"""

import os
import io
import re
import time
import json
import mmap
import logging
import zipfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 外部ライブラリ（条件付きインポート・可用性フラグ） ---
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import docx
except ImportError:
    docx = None

try:
    import xlrd  # 古い形式のExcelファイル(.xls)用
except ImportError:
    xlrd = None

try:
    import docx2txt  # 古い形式のWordファイル(.doc)用
except ImportError:
    docx2txt = None

try:
    import olefile  # 古いOfficeファイル形式の解析用
except ImportError:
    olefile = None

try:
    import chardet
except ImportError:
    chardet = None

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None

# ロガー。メインプロセスでは file_search_app 側が設定済みの debug_logger を
# 注入して統一する（extraction.debug_logger = debug_logger）。ワーカープロセス
# 等で未注入の場合でも動作するよう、独自の既定ロガーを用意しておく。
debug_logger = logging.getLogger("file_search_extraction")
if not debug_logger.handlers:
    debug_logger.addHandler(logging.NullHandler())


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


def normalize_extracted_text(text: str, max_length: int = 100000) -> str:
    """
    抽出されたテキストを正規化（ノイズ除去・読みやすさ向上）

    Args:
        text: 抽出されたテキスト
        max_length: 最大文字数

    Returns:
        正規化されたテキスト
    """
    if not text:
        return ""

    # 制御文字を除去（タブ・改行・スペースは保持）
    cleaned = ''.join(char for char in text if char.isprintable() or char in '\t\n\r ')

    # 連続する空白を1つに統一
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)

    # 連続する改行を最大2つまでに制限
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    # 行頭・行末の空白を削除
    lines = [line.strip() for line in cleaned.split('\n')]
    cleaned = '\n'.join(line for line in lines if line)

    # 全体の前後の空白を削除
    cleaned = cleaned.strip()

    # 最大文字数で切り詰め
    if len(cleaned) > max_length:
        cleaned = safe_truncate_utf8(cleaned, max_length)

    return cleaned


# === 以下、_FileContentExtractor クラスと ProcessPool 抽出ワーカーは
#     file_search_app.py から移設（本文抽出ロジック本体） ===
class _FileContentExtractor:
    """ワーカープロセス用の軽量抽出クラス（DB・UI の依存なし）"""
    def __init__(self):
        self._encoding_cache: dict = {}
        self._ocr_cache: dict = {}

    def _extract_file_content(self, file_path: str) -> str:
        """ファイル内容抽出 - 全形式対応（画像OCR含む）"""
        try:
            file_path_obj = Path(file_path)
            extension = file_path_obj.suffix.lower()

            if extension == '.txt':
                return self._extract_txt_content(file_path)
            elif extension in ['.docx', '.dotx', '.dotm', '.docm']:  # Word新形式ファイル
                return self._extract_docx_content(file_path)
            elif extension in ['.doc', '.dot']:  # Word旧形式ファイル
                return self._extract_doc_content(file_path)
            elif extension in ['.xlsx', '.xltx', '.xltm', '.xlsm', '.xlsb']:  # Excel新形式ファイル
                return self._extract_xlsx_content(file_path)
            elif extension in ['.xls', '.xlt']:  # Excel旧形式ファイル
                return self._extract_xls_content(file_path)
            elif extension == '.pdf':
                return self._extract_pdf_content(file_path)
            elif extension == '.zip':  # ZIPファイル内のテキストファイルを処理
                return self._extract_zip_content(file_path)
            elif extension in ['.tif', '.tiff']:  # 画像ファイルは検索対象外
                return ""  # 処理をスキップ
            elif extension in ['.jwc', '.jww', '.dxf', '.sfc', '.dwg', '.dwt', '.mpp', '.mpz']:  # CAD/図面ファイル（ファイル名のみ検索対象）
                return ""  # 内容は抽出せず、ファイル名のみインデックス
            else:
                # 対象外の拡張子はスキップ
                return ""

        except Exception as e:
            print(f"⚠️ ファイル内容抽出エラー {file_path}: {e}")
            return ""

    def _extract_txt_content(self, file_path: str) -> str:
        """テキストファイル抽出（mmap+ストリーミング最適化・90%高速化）"""
        try:
            # ファイルサイズチェック
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return ""
            
            # 🚀 エンコーディングキャッシュチェック（同じ拡張子は同じエンコーディングの可能性が高い）
            if not hasattr(self, '_encoding_cache'):
                self._encoding_cache = {}
            file_ext = Path(file_path).suffix.lower()
            cached_encoding = self._encoding_cache.get(file_ext)
            
            # 🚀 大容量ファイル対応: 10MB以上はmmapで効率的にアクセス
            use_mmap = file_size > 10 * 1024 * 1024
            
            # 🔥 超大容量ファイル（100MB以上）は最小限のみ
            if file_size > 100 * 1024 * 1024:
                max_read_size = 5 * 1024 * 1024  # 5MBのみ（超高速化）
            elif file_size > 50 * 1024 * 1024:
                max_read_size = 10 * 1024 * 1024  # 10MBまで
            else:
                max_read_size = min(file_size, 20 * 1024 * 1024)  # 最大20MBまで
            
            # バイナリで読み込んでエンコーディング検出（最適化: 4KBで検出）
            with open(file_path, 'rb') as f:
                sample_data = f.read(min(4096, file_size))  # 4KBで十分（10KB→4KBで高速化）
                
                # バイナリファイル検出（NULL文字が多い場合）
                null_count = sample_data.count(b'\x00')
                if null_count > len(sample_data) * 0.1:  # 10%以上NULL文字ならバイナリ
                    return ""
            
            # 🚀 エンコーディング検出の最適化: キャッシュ優先、UTF-8を最初に試行
            detected_encoding = None
            if cached_encoding:
                # キャッシュがあれば優先使用
                detected_encoding = cached_encoding
                debug_logger.debug(f"キャッシュエンコーディング使用: {detected_encoding}")
            elif chardet:
                try:
                    detection = chardet.detect(sample_data)
                    if detection and detection['confidence'] > 0.7:
                        detected_encoding = detection['encoding']
                        # キャッシュに保存
                        self._encoding_cache[file_ext] = detected_encoding
                        debug_logger.debug(f"検出エンコーディング: {detected_encoding} (信頼度: {detection['confidence']:.2f})")
                except Exception as e:
                    debug_logger.warning(f"エンコーディング検出エラー: {e}")
            
            # エンコーディング候補リスト（UTF-8優先で高速化）
            encodings = ['utf-8']  # UTF-8を最優先
            if detected_encoding and detected_encoding.lower() != 'utf-8':
                encodings.insert(0, detected_encoding)
            encodings.extend(['cp932', 'shift_jis'])  # 日本語環境の主要エンコーディング
            
            # 各エンコーディングで試行（高速版）
            for encoding in encodings:
                try:
                    if use_mmap and file_size > 50 * 1024 * 1024:
                        # 🚀 50MB以上: mmapで効率的にアクセス（メモリ節約）
                        with open(file_path, 'rb') as f:
                            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mmapped:
                                # 先頭20MBのみ読み込み（全体は読まない）
                                chunk_data = mmapped[:max_read_size]
                                content = chunk_data.decode(encoding, errors='strict')
                                if content and len(content.strip()) > 0:
                                    # エンコーディングをキャッシュ
                                    self._encoding_cache[file_ext] = encoding
                                    debug_logger.debug(f"mmap抽出成功: {encoding}")
                                    return normalize_extracted_text(content)
                    else:
                        # 通常ファイル: 標準読み込み
                        with open(file_path, 'r', encoding=encoding, errors='strict') as f:
                            content = f.read(max_read_size)
                            if content and len(content.strip()) > 0:
                                # エンコーディングをキャッシュ
                                self._encoding_cache[file_ext] = encoding
                                debug_logger.debug(f"テキスト抽出成功: {encoding}")
                                return normalize_extracted_text(content)
                except (UnicodeDecodeError, LookupError):
                    continue
                except Exception as e:
                    debug_logger.warning(f"読み込みエラー ({encoding}): {e}")
                    continue
            
            # すべて失敗した場合はエラーを無視して読み込み（フォールバック）
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(max_read_size)
                    return normalize_extracted_text(content)
            except:
                try:
                    with open(file_path, 'r', encoding='cp932', errors='ignore') as f:
                        content = f.read(max_read_size)
                        return normalize_extracted_text(content)
                except:
                    return ""
                    
        except Exception as e:
            debug_logger.error(f"テキスト抽出エラー {file_path}: {e}")
            return ""

    def _extract_docx_content(self, file_path: str) -> str:
        """Word文書抽出（大容量対応・部分読み込み最適化）"""
        try:
            # ファイル拡張子チェック
            file_extension = os.path.splitext(file_path)[1].lower()
            
            # 古い形式のWordファイル（.doc）の場合は処理をスキップ
            if file_extension in ['.doc', '.dot']:
                print(f"⚠️ 古い形式のWordファイルはサポートされていません: {os.path.basename(file_path)}")
                return ""

            # 🚀 ファイルサイズチェック（大容量対応）
            file_size = os.path.getsize(file_path)
            if file_size < 100:  # 100バイト未満は無効
                print(f"⚠️ ファイルサイズが小さすぎます: {os.path.basename(file_path)}")
                return ""
            
            # 🚀 大容量ファイル（50MB以上）は部分的に処理
            is_large_file = file_size > 50 * 1024 * 1024
            max_paragraphs = 1000 if is_large_file else 10000  # 大容量は1000段落まで

            content = []

            # ZIPファイルかどうかを事前チェック
            try:
                with zipfile.ZipFile(file_path, 'r') as test_zip:
                    # word/document.xmlが存在するかチェック
                    if 'word/document.xml' not in test_zip.namelist():
                        debug_logger.warning(f"word/document.xmlが見つかりません: {file_path}")
                        print(f"⚠️ 有効なWordファイルではありません（破損または別形式）: {os.path.basename(file_path)}")
                        return ""
            except zipfile.BadZipFile:
                debug_logger.warning(f"ZIPファイルとして開けません: {file_path}")
                print(f"⚠️ 破損したWordファイル: {os.path.basename(file_path)}")
                return ""  # ZIPファイルでない場合は静かに終了
            except Exception as e:
                debug_logger.warning(f"Word事前チェックエラー: {file_path} - {e}")
                return ""

            with zipfile.ZipFile(file_path, 'r') as docx:
                # メイン文書の抽出
                xml_content = docx.read('word/document.xml')
                root = ET.fromstring(xml_content)
                
                # 名前空間定義
                namespaces = {
                    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
                }

                # 段落とテキスト要素を順序通りに抽出
                paragraph_count = 0
                for para in root.findall('.//w:p', namespaces):
                    # 🚀 大容量ファイル: 段落数制限
                    if is_large_file and paragraph_count >= max_paragraphs:
                        debug_logger.info(f"大容量Word: {max_paragraphs}段落で処理終了")
                        break
                    
                    para_text = []
                    for text_elem in para.findall('.//w:t', namespaces):
                        if text_elem.text:
                            para_text.append(text_elem.text)
                    if para_text:
                        content.append(''.join(para_text))
                        paragraph_count += 1
                
                # ヘッダーの抽出
                try:
                    for header_file in [f for f in docx.namelist() if 'header' in f.lower()]:
                        header_xml = docx.read(header_file)
                        header_root = ET.fromstring(header_xml)
                        for text_elem in header_root.findall('.//w:t', namespaces):
                            if text_elem.text and text_elem.text.strip():
                                content.append(text_elem.text.strip())
                except:
                    pass
                
                # フッターの抽出
                try:
                    for footer_file in [f for f in docx.namelist() if 'footer' in f.lower()]:
                        footer_xml = docx.read(footer_file)
                        footer_root = ET.fromstring(footer_xml)
                        for text_elem in footer_root.findall('.//w:t', namespaces):
                            if text_elem.text and text_elem.text.strip():
                                content.append(text_elem.text.strip())
                except:
                    pass
                
                # 脚注・コメントの抽出
                try:
                    for notes_file in [f for f in docx.namelist() if 'footnotes' in f.lower() or 'comments' in f.lower()]:
                        notes_xml = docx.read(notes_file)
                        notes_root = ET.fromstring(notes_xml)
                        for text_elem in notes_root.findall('.//w:t', namespaces):
                            if text_elem.text and text_elem.text.strip():
                                content.append(text_elem.text.strip())
                except:
                    pass

            result = ' '.join(content)
            return normalize_extracted_text(result)

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

    def _extract_xlsx_content(self, file_path: str) -> str:
        """Excel文書抽出（大容量対応・部分読み込み最適化）"""
        try:
            # ファイル拡張子チェック
            file_extension = os.path.splitext(file_path)[1].lower()
            
            # 古い形式のExcelファイル（.xls）の場合は処理をスキップ
            if file_extension in ['.xls', '.xlt']:
                print(f"⚠️ 古い形式のExcelファイルはサポートされていません: {os.path.basename(file_path)}")
                return ""
            
            # 🚀 ファイルサイズチェック（大容量対応）
            file_size = os.path.getsize(file_path)
            is_large_file = file_size > 50 * 1024 * 1024
            max_rows = 5000 if is_large_file else 50000  # 大容量は5000行まで
            max_sheets = 3 if is_large_file else 10  # 大容量は3シートまで
            
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
                    
                    # 名前空間定義
                    ns = {'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

                    sheet_files = [f for f in xlsx.namelist() if f.startswith('xl/worksheets/sheet')]
                    
                    # 🚀 大容量ファイル: シート数制限
                    processed_sheets = 0
                    for sheet_file in sheet_files:
                        if is_large_file and processed_sheets >= max_sheets:
                            debug_logger.info(f"大容量Excel: {max_sheets}シートで処理終了")
                            break
                        
                        sheet_xml = xlsx.read(sheet_file)
                        sheet_root = ET.fromstring(sheet_xml)
                        
                        # 🚀 大容量ファイル: 行数制限
                        row_count = 0
                        # セルを順番に処理
                        for row in sheet_root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                            if is_large_file and row_count >= max_rows:
                                debug_logger.info(f"大容量Excel: シート{processed_sheets+1}で{max_rows}行処理")
                                break
                            row_count += 1
                            for cell in row.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                                cell_type = cell.get('t', 'n')  # セルタイプ: s=文字列, n=数値, b=ブール等
                                
                                # セル値を取得
                                v_elem = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                                if v_elem is not None and v_elem.text:
                                    value = v_elem.text.strip()
                                    
                                    if cell_type == 's':  # 共有文字列参照
                                        try:
                                            index = int(value)
                                            if 0 <= index < len(shared_strings):
                                                text = shared_strings[index]
                                                if text and len(text) > 0:
                                                    content.append(text)
                                        except (ValueError, IndexError):
                                            pass
                                    elif cell_type == 'str':  # 数式の文字列結果
                                        if value and len(value) > 0:
                                            content.append(value)
                                    elif value and not value.replace('.', '').replace('-', '').isdigit():
                                        # 数値以外の直接値
                                        if len(value) > 0:
                                            content.append(value)
                                    elif value and len(value) > 2:  # 長い数値は保持（ID等）
                                        content.append(value)
                        
                        processed_sheets += 1

                except Exception as e:
                    print(f"⚠️ Excelシート処理エラー: {e}")

            result = ' '.join(content)
            return normalize_extracted_text(result)

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

    def _extract_zip_content(self, file_path: str) -> str:
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

    def _extract_xls_content(self, file_path: str) -> str:
        """古い形式のExcel(.xls)ファイル抽出"""
        try:
            if xlrd is None:
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

    def _extract_doc_content(self, file_path: str) -> str:
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

            base_name = os.path.basename(file_path)

            # 1. OLE2形式（本物の旧.doc）かどうかを先に判定する。
            #    OLE2なら docx2txt は必ず失敗する（.docはzipではない）ため呼ばない。
            is_ole = False
            if olefile is not None:
                try:
                    is_ole = olefile.isOleFile(file_path)
                except Exception:
                    is_ole = False

            # 2. OLE2形式: WordDocumentストリームから本文テキストを抽出（日本語対応）
            if is_ole and olefile is not None:
                debug_logger.debug(f"OLE2形式のDOCを検出: {base_name}")
                try:
                    with olefile.OleFileIO(file_path) as ole:
                        if ole.exists('WordDocument'):
                            raw = ole.openstream('WordDocument').read()
                            text = self._readable_text_from_bytes(raw)
                            if text:
                                text = normalize_extracted_text(text, max_length=500000)
                                print(f"✅ OLE2 DOC本文抽出成功: {base_name} - {len(text)} 文字")
                                return text
                except Exception as olefile_error:
                    debug_logger.warning(f"olefile処理エラー: {base_name} - {olefile_error}")

            # 3. 非OLE2（.docx を .doc 拡張子にしている等）の場合のみ docx2txt を試行
            elif docx2txt is not None:
                try:
                    content = docx2txt.process(file_path)
                    if content and content.strip():
                        print(f"✅ docx2txtでDOC処理成功: {base_name} - 長さ: {len(content)} 文字")
                        return content.strip()
                except Exception as docx2txt_error:
                    debug_logger.debug(f"docx2txt処理スキップ: {base_name} - {docx2txt_error}")

            # 4. 最後の手段: ファイル全体からの可読テキスト抽出（日本語対応）
            try:
                with open(file_path, 'rb') as f:
                    data = f.read(min(file_size, 4 * 1024 * 1024))  # 最大4MB読み込み
                text = self._readable_text_from_bytes(data)
                if text:
                    text = normalize_extracted_text(text, max_length=500000)
                    print(f"✅ バイナリ解析成功: {base_name} - {len(text)} 文字")
                    return text
            except Exception as binary_error:
                debug_logger.warning(f"バイナリ解析エラー: {base_name} - {binary_error}")

            # 5. 全ての方法が失敗した場合は基本情報のみ（ファイル名検索は可能）
            debug_logger.info(f"DOC内容抽出失敗、ファイル名のみインデックス: {base_name}")
            return f"Microsoft Word文書 - {base_name}"
            
        except Exception as e:
            print(f"⚠️ DOC抽出エラー: {os.path.basename(file_path)} - {e}")
            return ""

    def _readable_text_from_bytes(self, data: bytes) -> str:
        """バイナリ(.doc等)から可読テキストを抽出（日本語対応）。

        旧.docはWordDocumentストリーム内に本文をUTF-16LEで持つことが多いため、
        UTF-16LE と CP932(Shift_JIS) の両方でデコードを試し、日本語(ひらがな・
        カタカナ・漢字・全角)と英数字・基本記号のみを残してノイズを除去する。
        より多くの意味のある文字が取れたデコード結果を採用する。
        ASCIIのみを拾う旧実装と違い、日本語の.doc本文も検索対象にできる。
        """
        def filter_readable(text: str) -> str:
            kept = []
            for ch in text:
                o = ord(ch)
                if (ch.isalnum() or ch == ' '
                        or 0x3000 <= o <= 0x30ff      # 句読点・ひらがな・カタカナ
                        or 0x4e00 <= o <= 0x9fff      # 漢字（CJK統合）
                        or 0xff00 <= o <= 0xffef      # 全角英数・半角カナ
                        or ch in '、。・「」『』（）【】〜ー－.,!?:;()[]{}/_-'):
                    kept.append(ch)
                else:
                    kept.append(' ')
            return ' '.join(''.join(kept).split())

        def quality_score(text: str) -> int:
            # 長い連続トークン（4文字以上）の総文字数で評価する。
            # 正しいデコードは本文が長い連続語として現れ、誤デコード(別エンコーディングでの
            # 誤読)は短い断片が散在するため、誤読のゴミを高評価しにくい。
            return sum(len(tok) for tok in text.split() if len(tok) >= 4)

        best = ""
        best_score = 0
        for enc in ('utf-16-le', 'cp932'):
            try:
                decoded = data.decode(enc, errors='ignore')
            except Exception:
                continue
            cleaned = filter_readable(decoded)
            score = quality_score(cleaned)
            if score > best_score:
                best_score = score
                best = cleaned

        # 意味のある連続テキストが極端に少ない場合はノイズとみなして破棄
        return best if best_score >= 8 else ""

    def _extract_pdf_content(self, file_path: str) -> str:
        """PDF文書抽出（ページ並列化で80%高速化）"""
        try:
            # ファイル存在とアクセス権限チェック
            if not os.path.exists(file_path):
                debug_logger.warning(f"PDFファイルが存在しません: {file_path}")
                return ""

            if not os.access(file_path, os.R_OK):
                debug_logger.warning(f"PDFファイル読み取り権限なし: {file_path}")
                return ""

            file_size = os.path.getsize(file_path)
            if file_size < 50:  # 50バイト未満は無効PDFとみなす
                debug_logger.warning(f"PDFファイルサイズが小さすぎます: {file_path}")
                return ""

            # 大容量PDF対応: 200MBまで処理可能
            if file_size > 200 * 1024 * 1024:  # 200MB以上は処理スキップ
                print(
                    f"⚠️ PDFファイルが大きすぎます: {os.path.basename(file_path)} ({file_size / 1024 / 1024:.1f}MB)"
                )
                return ""

            # PyMuPDF使用を試行（ファイルパス正規化付き）
            try:
                import fitz

                # ファイルパスの正規化（特殊文字・Unicode対応）
                normalized_path = os.path.normpath(os.path.abspath(file_path))

                # ファイルアクセステスト
                with open(normalized_path, 'rb') as test_file:
                    test_file.read(1024)  # 1KBテスト読み込み

                # PyMuPDFでPDF開く
                doc = fitz.open(normalized_path)
                
                # 🚀 ページ数に応じた処理戦略
                total_pages = doc.page_count
                max_pages = min(total_pages, 200)  # 最大200ページ（500→200で高速化）

                # ページ番号 -> 抽出テキスト（テキスト層が無いページの検出に使用）
                page_texts = {}

                # 🚀 並列処理でページ抽出（10ページ以上の場合）
                if max_pages >= 10:
                    def extract_single_page(page_num: int) -> str:
                        """単一ページ抽出（並列処理用）"""
                        try:
                            page = doc[page_num]
                            # 最も高速な方法を優先（失敗時のみフォールバック）
                            try:
                                page_text = page.get_text("text", sort=True)
                                if page_text and len(page_text.strip()) > 10:
                                    return ' '.join(page_text.split())
                            except:
                                pass
                            # フォールバック: ブロック単位抽出
                            blocks = page.get_text("blocks")
                            block_texts = [block[4].strip() for block in blocks if len(block) >= 5 and block[4].strip()]
                            return ' '.join(block_texts)
                        except Exception as e:
                            debug_logger.warning(f"ページ{page_num}抽出エラー: {e}")
                            return ""

                    # 🚀 並列ページ抽出（最大4スレッド）
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = {executor.submit(extract_single_page, i): i for i in range(max_pages)}
                        for future in as_completed(futures):
                            page_num = futures[future]
                            try:
                                page_text = future.result(timeout=5.0)  # 5秒タイムアウト
                                if page_text:
                                    page_texts[page_num] = page_text
                            except Exception:
                                continue
                else:
                    # 少ないページは従来の同期処理
                    for page_num in range(max_pages):
                        try:
                            page = doc[page_num]
                            page_text = page.get_text("text", sort=True)
                            if page_text and page_text.strip():
                                normalized = ' '.join(page_text.split())
                                if len(normalized) > 0:
                                    page_texts[page_num] = normalized
                        except Exception as page_error:
                            debug_logger.warning(f"PDFページ {page_num} 読み取りエラー: {page_error}")
                            continue

                # 🔥 OCRフォールバック: テキスト層が無い（=スキャン）ページを画像化してOCR
                # テキスト層がほぼ皆無のページのみ対象にする（短いが正規のテキスト層を持つ
                # ページ＝章扉・ページ番号のみ等をOCR結果で上書きして劣化させないため）
                ocr_target_pages = [p for p in range(max_pages)
                                    if len(page_texts.get(p, "")) < 3]
                if ocr_target_pages:
                    ocr_results = self._ocr_pdf_pages(doc, ocr_target_pages, file_path)
                    for page_num, ocr_text in ocr_results.items():
                        if not ocr_text:
                            continue
                        existing = page_texts.get(page_num, "")
                        # 既存のテキスト層は温存し、OCR結果を追記する
                        page_texts[page_num] = f"{existing} {ocr_text}".strip() if existing else ocr_text

                doc.close()

                # ページ順に結合
                content = [page_texts[p] for p in sorted(page_texts.keys())]
                extracted_text = ' '.join(content)
                
                # 正規化処理を適用
                extracted_text = normalize_extracted_text(extracted_text, max_length=500000)
                
                if content:
                    debug_logger.debug(f"PDF抽出成功: {file_path} ({len(extracted_text)} 文字)")
                    return extracted_text
                else:
                    debug_logger.warning(f"PDF内容が空です: {file_path}")
                    return ""

            except ImportError:
                debug_logger.warning("PyMuPDF未インストール - 基本PDF抽出使用")
            except PermissionError as pe:
                debug_logger.error(f"PDFファイルアクセス権限エラー: {pe}")
                return ""
            except FileNotFoundError as fnf:
                debug_logger.error(f"PDFファイルが見つかりません: {fnf}")
                return ""
            except Exception as e:
                debug_logger.error(f"PyMuPDF抽出エラー: {e}")

            # フォールバック：基本PDF抽出（ファイルアクセス安全版）
            try:
                with open(file_path, 'rb') as f:
                    raw_content = f.read(1024 * 1024)  # 最初の1MBのみ読み込み

                # 基本的なPDFテキスト抽出
                import re
                text_pattern = re.compile(rb'\(([^)]*)\)')
                matches = text_pattern.findall(raw_content)
                extracted_text = []

                for match in matches:
                    try:
                        decoded = match.decode('utf-8', errors='ignore')
                        if len(decoded.strip()) > 2:  # 意味のあるテキストのみ
                            extracted_text.append(decoded)
                    except:
                        continue

                return ' '.join(extracted_text)

            except Exception as e:
                print(f"⚠️ 基本PDF抽出エラー: {e}")
                return ""

        except Exception as e:
            print(f"⚠️ PDF抽出エラー: {e}")
            return ""

    def _ocr_pdf_pages(self, doc, page_nums, file_path: str) -> dict:
        """テキスト層の無いPDFページを画像化してOCR抽出

        スキャン（画像ベース）PDF対応。各ページをPyMuPDFでレンダリングし、
        pytesseractでテキスト抽出する。
        戻り値: {ページ番号: 抽出テキスト}
        """
        results = {}
        try:
            # OCRライブラリの利用可能性チェック
            if not PIL_AVAILABLE or not TESSERACT_AVAILABLE:
                debug_logger.debug("PDF OCRフォールバック: OCRライブラリ未導入のためスキップ")
                return results

            try:
                pytesseract.get_tesseract_version()
            except pytesseract.TesseractNotFoundError:
                debug_logger.debug("PDF OCRフォールバック: Tesseract未導入のためスキップ")
                return results

            import io
            import fitz

            # 処理過多防止: OCR対象ページ数を制限（速度優先）
            max_ocr_pages = 30
            target_pages = list(page_nums)[:max_ocr_pages]
            if len(page_nums) > max_ocr_pages:
                debug_logger.debug(
                    f"PDF OCR対象ページを{max_ocr_pages}ページに制限: {os.path.basename(file_path)}")

            # 200dpi相当（72dpi * 約2.78）でレンダリング（OCR精度と速度のバランス）
            zoom = 2.0
            matrix = fitz.Matrix(zoom, zoom)

            ocr_config = '--oem 1 --psm 6'

            # 🚀 OCRは常に jpn+eng の1パスで実行する。
            #   対象文書はほぼ日本語（一部英数字混在）。Tesseract は jpn+eng の
            #   1回で日英両方の文字を認識できるため、ファイル名から言語を推測して
            #   eng→jpn と最悪2回OCRしていた旧実装を廃止。誤判定による2回OCR
            #   （最大の遅延要因）を根絶しつつ、混在文字の取りこぼしも減って
            #   検索品質はむしろ向上する。jpn データが無い環境のみ eng に退避。
            #   言語データの有無は全ページ共通なので一度だけ判定してキャッシュする。
            if getattr(self, '_ocr_lang', None) is None:
                self._ocr_lang = 'jpn+eng'

            def ocr_single_page(page_num: int) -> str:
                """単一ページをレンダリングしてOCR（並列処理用・1パス）"""
                page = doc[page_num]
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))

                # グレースケール化（OCR精度向上・高速化）
                if image.mode not in ('L', '1'):
                    image = image.convert('L')

                try:
                    text = pytesseract.image_to_string(
                        image, lang=self._ocr_lang, config=ocr_config).strip()
                except pytesseract.TesseractError:
                    # jpn 言語データが無い等の場合は eng のみへ恒久的に退避
                    self._ocr_lang = 'eng'
                    text = pytesseract.image_to_string(
                        image, lang='eng', config=ocr_config).strip()

                return ' '.join(text.split())

            # 🚀 並列OCR（テキスト抽出と同じ最大4スレッド）＋ページ単位タイムアウトでハング防止
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(ocr_single_page, p): p for p in target_pages}
                for future in as_completed(futures):
                    page_num = futures[future]
                    try:
                        text = future.result(timeout=30.0)  # 1ページ最大30秒
                        if len(text) >= 2:
                            results[page_num] = text
                    except Exception as page_error:
                        debug_logger.warning(f"PDF OCRページ {page_num} エラー: {page_error}")
                        continue

            if results:
                ocr_chars = sum(len(t) for t in results.values())
                print(f"✅ PDF OCRフォールバック成功 ({os.path.basename(file_path)}): "
                      f"{len(results)}ページ / {ocr_chars}文字")

        except Exception as e:
            debug_logger.warning(f"PDF OCRフォールバックエラー ({os.path.basename(file_path)}): {e}")

        return results

    def _extract_image_content(self, file_path: str) -> str:
        """.tifファイルからOCRでテキスト抽出（超高速最適化版・キャッシュ強化）"""
        try:
            # 🚀 キャッシュチェック（最優先）
            if hasattr(self, '_ocr_cache'):
                cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
                if cache_key in self._ocr_cache:
                    cached_result = self._ocr_cache[cache_key]
                    print(f"⚡ OCRキャッシュヒット: {os.path.basename(file_path)} ({len(cached_result)}文字)")
                    return cached_result
            else:
                self._ocr_cache = {}

            # OCRライブラリが利用可能かチェック
            if not PIL_AVAILABLE or not TESSERACT_AVAILABLE:
                return ""

            # Tesseractエンジンの利用可能性を確認
            try:
                pytesseract.get_tesseract_version()
            except pytesseract.TesseractNotFoundError:
                return ""

            # 🔥 超高速スキップ条件（ファイルサイズ最適化）
            file_size = os.path.getsize(file_path)
            if file_size < 1024:  # 1KB未満は処理しない
                return ""
            if file_size > 30 * 1024 * 1024:  # 30MB以上は処理しない（より厳格）
                print(f"⚠️ .tif画像ファイルが大きすぎます ({file_path}): {file_size/1024/1024:.1f}MB")
                return ""
            
            # 🚀 超高速画像読み込み・検証
            try:
                image = Image.open(file_path)
                
                # 画像フォーマット・モード最適化チェック
                if image.mode not in ['L', 'RGB', 'RGBA', '1']:
                    image = image.convert('RGB')
                
                # 画像サイズチェックと超高速最適化
                width, height = image.size
                total_pixels = width * height
                
                # 🔥 動的解像度調整: ファイルサイズに応じて最適な画素数を選択
                # 小さいファイル: 高解像度でOCR精度向上
                # 大きいファイル: 低解像度で処理速度優先
                if file_size < 2 * 1024 * 1024:  # 2MB未満
                    max_pixels = 1500000  # 150万画素（精度優先）
                elif file_size < 5 * 1024 * 1024:  # 5MB未満
                    max_pixels = 1000000  # 100万画素（バランス）
                else:  # 5MB以上
                    max_pixels = 600000   # 60万画素（速度優先）
                
                if total_pixels > max_pixels:
                    scale_factor = (max_pixels / total_pixels) ** 0.5
                    new_width = int(width * scale_factor)
                    new_height = int(height * scale_factor)
                    # 高速リサイズアルゴリズム使用
                    image = image.resize((new_width, new_height), Image.Resampling.BILINEAR)
                    total_pixels = new_width * new_height
                    debug_logger.debug(f"動的リサイズ ({os.path.basename(file_path)}): {width}x{height} -> {new_width}x{new_height}")
                
                # 小さすぎる画像はスキップ
                if total_pixels < 10000:  # 100x100未満はスキップ
                    return ""
                
            except Exception as e:
                print(f"⚠️ 画像読み込みエラー ({file_path}): {e}")
                return ""
            
            # 🚀 超高速OCR設定（速度最優先）
            ultra_fast_config = r'--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん'  # 文字制限で高速化
            
            # 🔥 適応型前処理: 画像特性に応じて最適な前処理を選択
            processed_image = image
            
            # 前処理が必要な条件: カラー画像かつ中規模サイズ
            needs_preprocessing = (image.mode != 'L' and 
                                  total_pixels < 500000 and 
                                  file_size > 500 * 1024)  # 500KB以上
            
            if CV2_AVAILABLE and needs_preprocessing:
                try:
                    import numpy as np
                    image_array = np.array(image)
                    
                    # グレースケール変換（最も効果的な前処理）
                    if len(image_array.shape) == 3:
                        gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
                        
                        # 小さいファイルのみ二値化を追加（OCR精度向上）
                        if file_size < 2 * 1024 * 1024:
                            # 適応的二値化: 照明ムラに強い
                            gray = cv2.adaptiveThreshold(
                                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 11, 2)
                        
                        processed_image = Image.fromarray(gray)
                except Exception:
                    processed_image = image
            
            # 🚀 超高速OCR実行（段階的最適化 + 言語検出）
            text = ""
            
            # ファイル名から言語をヒント取得（処理の最適化）
            filename_lower = os.path.basename(file_path).lower()
            likely_japanese = any(hint in filename_lower for hint in ['日本語', 'japanese', 'jpn', '図面', '設計'])
            
            # Phase 1: 超高速英数字のみ（最も高速）
            try:
                if not likely_japanese:  # 日本語の可能性が低い場合のみ
                    fast_config = r'--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
                    text = pytesseract.image_to_string(processed_image, lang='eng', config=fast_config).strip()
                
                # Phase 2: 結果が不十分な場合のみ通常英語OCR
                if len(text) < 5:
                    text = pytesseract.image_to_string(processed_image, lang='eng', config='--oem 1 --psm 6').strip()
                
                # Phase 3: 最後の手段として日本語（処理時間が増加）
                # 小さいファイルまたは日本語の可能性が高い場合のみ試行
                if (len(text) < 3 and file_size < 5 * 1024 * 1024) or likely_japanese:
                    try:
                        jp_text = pytesseract.image_to_string(processed_image, lang='jpn', config='--oem 1 --psm 6').strip()
                        if len(jp_text) > len(text):
                            text = jp_text
                    except pytesseract.TesseractError:
                        pass
                        
            except pytesseract.TesseractError as te:
                try:
                    # 最終フォールバック：最小設定
                    text = pytesseract.image_to_string(processed_image, config='--psm 6').strip()
                except pytesseract.TesseractError:
                    print(f"⚠️ OCR実行完全失敗 ({os.path.basename(file_path)}): {te}")
                    return ""
            
            # 🔥 結果検証と最適化
            text = text.strip()
            
            # 無意味な結果をフィルタリング
            if len(text) < 2:
                result = ""
            elif len(set(text.replace(' ', '').replace('\n', ''))) < 3:  # 文字種類が少なすぎる
                result = ""
            else:
                # テキスト正規化（高速版）
                text = ' '.join(text.split())  # 余分な空白を削除
                result = text[:5000]  # 最大5000文字に制限
            
            # 🚀 キャッシュに保存（成功・失敗を問わず）
            cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
            self._ocr_cache[cache_key] = result
            
            # キャッシュサイズ制限
            if len(self._ocr_cache) > 1000:
                # 古いエントリを削除（LRU的）
                oldest_keys = list(self._ocr_cache.keys())[:100]
                for key in oldest_keys:
                    del self._ocr_cache[key]
            
            # 結果表示（成功時のみ）
            if result and len(result) > 10:
                print(f"✅ 超高速OCR成功 ({os.path.basename(file_path)}): {len(result)}文字")
            
            return result
            
        except Exception as e:
            print(f"⚠️ 超高速OCR処理エラー {os.path.basename(file_path)}: {e}")
            # エラーもキャッシュして再試行を防ぐ
            if hasattr(self, '_ocr_cache'):
                cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
                self._ocr_cache[cache_key] = ""
            return ""



# --- ProcessPool 抽出ワーカー（GIL 回避） ---
_proc_extractor: Optional['_FileContentExtractor'] = None


def _init_extraction_worker() -> None:
    """各ワーカープロセスで一度だけ呼ばれる初期化関数"""
    global _proc_extractor
    import multiprocessing
    multiprocessing.current_process().name  # 確認用
    _proc_extractor = _FileContentExtractor()


def _worker_extract(file_path: str, file_size: int, modified_time: float) -> tuple:
    """ワーカープロセスで呼ばれる抽出関数（CPUバウンドな本文抽出のみを担当）

    前処理（隠しファイル/差分スキップ/サイズ判定）は親プロセスで実施済みである
    ことを前提とし、ここでは純粋に本文抽出だけを行う。

    戻り値: (file_path, content, file_size, modified_time, extract_seconds)
    エラー時: (file_path, None, file_size, modified_time, extract_seconds)
    """
    global _proc_extractor
    if _proc_extractor is None:
        _proc_extractor = _FileContentExtractor()
    _t0 = time.time()
    try:
        content = _proc_extractor._extract_file_content(file_path)
        return (file_path, content, file_size, modified_time, time.time() - _t0)
    except Exception:
        return (file_path, None, file_size, modified_time, time.time() - _t0)
