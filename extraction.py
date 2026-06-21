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
import struct
import logging
import zipfile
import threading
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# 🚀 Tesseract OCR の OpenMP スレッド過剰（oversubscription）を抑止する。
#   pytesseract は tesseract バイナリを呼び出すが、tesseract は 1 呼び出しあたり
#   複数の OpenMP スレッドを使おうとする。バルクインデックスでは外側の並列
#   (最大8) × ページOCRの内側並列 が重なり、tesseract が多数同時に起動して
#   コア数を大きく超えるスレッドが殺到し、コンテキストスイッチで律速する。
#   各 tesseract を 1 スレッドに固定し、並列はアプリ側の「ファイル×ページ」
#   並列だけで取ることでクリーンなコア活用にする。
#   ※認識精度（検索品質）には一切影響しない。環境変数が既に指定されていれば尊重。
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

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


# === エクスポートする正規（カノニカル）定数 ===
#   OCR対象の画像拡張子・索引対象の全拡張子は複数ファイルで重複していたため、
#   このモジュールを単一の真実の源（single source of truth）とする。
#   他モジュールはここを参照し、リテラル集合の複製を持たないこと。

# OCRで本文抽出する画像拡張子（TIFF）
IMAGE_OCR_EXTENSIONS = {'.tif', '.tiff'}

# 索引対象の全拡張子（file_search_app.py の2箇所のリストの和集合・重複排除）。
#   オフィス文書/CAD・図面/プロジェクト/画像/アーカイブを網羅する。
TARGET_EXTENSIONS = frozenset({
    # テキスト/オフィス文書
    '.txt', '.doc', '.docx', '.pdf', '.xls', '.xlsx', '.ppt', '.pptx',
    '.rtf', '.odt', '.ods', '.odp', '.csv', '.json', '.log',
    # Word関連
    '.dot', '.dotx', '.dotm', '.docm',
    # Excel関連
    '.xlt', '.xltx', '.xltm', '.xlsm', '.xlsb',
    # CAD/図面
    '.jwc', '.dxf', '.sfc', '.jww', '.dwg', '.dwt',
    # プロジェクト
    '.mpp', '.mpz',
    # 画像（OCR対象）
    '.tif', '.tiff',
    # アーカイブ
    '.zip',
})


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
        # 一括インデックス中はファイル単位で多並列に走るため、ページ内並列を
        # 絞って Tesseract のオーバーサブスクリプション（CPUコア超過の奪い合い）
        # を防ぐ。bulk_index_worker 開始/終了時に切り替える。
        self.bulk_mode: bool = False
        # 遅延OCR: True の間はスキャンPDFのOCRを実行せず needs_ocr で通知のみ。
        # 一括インデックス本体をOCRに律速させないため、本体中だけ True にする。
        self.defer_ocr: bool = False
        # 🔬 PDFのテキスト層抽出時間/OCR時間をスレッドセーフに記録する。
        #   live 経路では複数スレッドが同一 extractor を共有するため、インスタンス
        #   属性に直書きすると別ファイルの計測値と競合する。スレッドローカルに置く。
        self._tls = threading.local()

    def _page_workers(self) -> int:
        """PDFページ処理（テキスト抽出/OCR）の並列スレッド数を返す。

        一括インデックス中はファイル単位で既に多並列に走るため、各PDF内でも
        4ページ並列にすると「ファイル並列 × ページ並列」で Tesseract が CPU
        コア数を大きく超えて起動し、互いに奪い合って急減速する（オーバー
        サブスクリプション）。そこでバルク時はページ並列を 2 に絞り、全体の
        同時 OCR 数を CPU コア数付近に抑える。大型スキャンPDFの「尻尾」を
        短くするため 1 ではなく 2 を残す。
        ライブ（単一ファイル）処理時は他に並列が無いので 4 まで使う。
        いずれも CPU コア数を上限にする。
        """
        cpu = os.cpu_count() or 4
        target = 2 if self.bulk_mode else 4
        return max(1, min(target, cpu))

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
            elif extension in IMAGE_OCR_EXTENSIONS:
                # 画像ファイル: OCRで本文抽出。一括インデックス中(defer_ocr)は本体を
                # 高速に保つためOCRを後回しにし、needs_ocr で通知のみ行う。
                self._tls.pdf_needs_ocr = False
                if getattr(self, 'defer_ocr', False):
                    self._tls.pdf_needs_ocr = True
                    return ""
                return self._extract_image_content(file_path)
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
                #   sharedStrings.xml は <si>（文字列1個）の並び。リッチテキストの
                #   <si> は複数の <r><t> に分割されるため、<si> 単位で本文の <t> を
                #   連結して「1要素=1文字列」にする。旧実装は全要素の text をフラットに
                #   集めており、<si> が複数 run を持つとインデックスがずれて別セルの
                #   文字列が表示される（文字化け/誤内容）バグがあった。
                #   さらに重要: 日本語版Excelはセルのふりがなを <rPh><t>…</t></rPh>
                #   として <si> 内に保存する。si.iter('t') は再帰的なので rPh 内の
                #   読み仮名(カタカナ)まで拾い、本文末尾に「ミセキショ」等の入力に無い
                #   カタカナが連結される。本文は <si> 直下の <t>(単純文字列)と
                #   <r>/<t>(リッチテキストのrun)のみで構成されるため、rPh を含む
                #   その他の <t> は対象外にする。
                try:
                    _ns_main = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    shared_strings_xml = xlsx.read('xl/sharedStrings.xml')
                    shared_root = ET.fromstring(shared_strings_xml)
                    shared_strings = []
                    for si in shared_root.iter(_ns_main + 'si'):
                        parts = []
                        # <si> 直下の <t>（ふりがなを持たない単純文字列）
                        t_direct = si.find(_ns_main + 't')
                        if t_direct is not None and t_direct.text:
                            parts.append(t_direct.text)
                        # <r>/<t>（リッチテキストの run 本文）。rPh は <r> 配下に
                        # は無いためここに混入しない。
                        for r in si.findall(_ns_main + 'r'):
                            for t in r.findall(_ns_main + 't'):
                                if t.text:
                                    parts.append(t.text)
                        shared_strings.append(''.join(parts))
                except:
                    shared_strings = []

                # ワークシート処理
                try:
                    # シート表示名の解決: workbook.xml の <sheets><sheet name r:id> と
                    #   workbook.xml.rels の rId→Target を突き合わせ、各 worksheet ファイルに
                    #   対応する表示名を得る。これにより .xls 抽出と同じ [シート: 名前] を出せる。
                    _r_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
                    sheet_name_by_file = {}
                    try:
                        rels_xml = xlsx.read('xl/_rels/workbook.xml.rels')
                        rels_root = ET.fromstring(rels_xml)
                        rid_to_target = {}
                        for rel in rels_root:
                            rid = rel.get('Id')
                            target = rel.get('Target')
                            if rid and target:
                                # Target は workbook.xml からの相対(例 worksheets/sheet1.xml)
                                norm = target.lstrip('/')
                                if not norm.startswith('xl/'):
                                    norm = 'xl/' + norm
                                rid_to_target[rid] = norm
                        workbook_xml = xlsx.read('xl/workbook.xml')
                        wb_root = ET.fromstring(workbook_xml)
                        for sh in wb_root.iter(_ns_main + 'sheet'):
                            name = sh.get('name')
                            rid = sh.get(_r_ns + 'id')
                            if name and rid and rid in rid_to_target:
                                sheet_name_by_file[rid_to_target[rid]] = name
                    except Exception:
                        sheet_name_by_file = {}

                    sheet_files = [f for f in xlsx.namelist() if f.startswith('xl/worksheets/sheet')]
                    # シート順は数値部分で安定ソート（sheet2 が sheet10 より前に来るように）
                    def _sheet_sort_key(fname):
                        m = re.search(r'sheet(\d+)\.xml$', fname)
                        return (0, int(m.group(1))) if m else (1, fname)
                    sheet_files.sort(key=_sheet_sort_key)

                    # 🚀 大容量ファイル: シート数制限
                    processed_sheets = 0
                    for sheet_file in sheet_files:
                        if is_large_file and processed_sheets >= max_sheets:
                            debug_logger.info(f"大容量Excel: {max_sheets}シートで処理終了")
                            break

                        sheet_xml = xlsx.read(sheet_file)
                        sheet_root = ET.fromstring(sheet_xml)

                        # シート見出し（.xls 抽出と同じ書式）。表示名が無ければファイル名から補う。
                        sheet_name = sheet_name_by_file.get(sheet_file)
                        if not sheet_name:
                            m = re.search(r'(sheet\d+)\.xml$', sheet_file)
                            sheet_name = m.group(1) if m else sheet_file
                        content.append(f"[シート: {sheet_name}]")

                        # 🚀 大容量ファイル: 行数制限
                        row_count = 0
                        # 行単位で処理（行内のセルは空白連結、行は改行で連結）
                        for row in sheet_root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                            if is_large_file and row_count >= max_rows:
                                debug_logger.info(f"大容量Excel: シート{processed_sheets+1}で{max_rows}行処理")
                                break
                            row_count += 1
                            row_values = []
                            for cell in row.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                                cell_type = cell.get('t', 'n')  # セルタイプ: s=文字列, n=数値, b=ブール, str=数式文字列, inlineStr=直接埋込文字列

                                if cell_type == 'inlineStr':
                                    # インライン文字列は <v> ではなく <is><t> に本文がある。
                                    # 旧実装はこれを読まず、openpyxl 等が書く .xlsx の本文が
                                    # 丸ごと欠落していた。<is> 配下の全 <t> を連結する。
                                    is_elem = cell.find(_ns_main + 'is')
                                    if is_elem is not None:
                                        parts = [t.text for t in is_elem.iter(_ns_main + 't') if t.text]
                                        text = ''.join(parts).strip()
                                        if text:
                                            row_values.append(text)
                                    continue

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
                                                    row_values.append(text)
                                        except (ValueError, IndexError):
                                            pass
                                    elif cell_type == 'str':  # 数式の文字列結果
                                        if value and len(value) > 0:
                                            row_values.append(value)
                                    elif value and not value.replace('.', '').replace('-', '').isdigit():
                                        # 数値以外の直接値
                                        if len(value) > 0:
                                            row_values.append(value)
                                    elif value and len(value) > 2:  # 長い数値は保持（ID等）
                                        row_values.append(value)

                            if row_values:
                                content.append(' '.join(row_values))

                        processed_sheets += 1

                except Exception as e:
                    print(f"⚠️ Excelシート処理エラー: {e}")

            result = '\n'.join(content)
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
                # 2a. piece table(CLX)による正確な本文抽出（文字化け回避の本命）
                try:
                    with olefile.OleFileIO(file_path) as ole:
                        text = self._extract_doc_text_ole(ole)
                    if text and len(text) >= 4:
                        text = normalize_extracted_text(text, max_length=500000)
                        print(f"✅ DOC本文抽出成功(piece table): {base_name} - {len(text)} 文字")
                        return text
                except Exception as pt_error:
                    debug_logger.warning(f"piece table抽出エラー: {base_name} - {pt_error}")
                # 2b. フォールバック: WordDocumentストリームの生バイト解析
                try:
                    with olefile.OleFileIO(file_path) as ole:
                        if ole.exists('WordDocument'):
                            raw = ole.openstream('WordDocument').read()
                            text = self._readable_text_from_bytes(raw)
                            if text:
                                text = normalize_extracted_text(text, max_length=500000)
                                print(f"✅ OLE2 DOC本文抽出成功(raw): {base_name} - {len(text)} 文字")
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
                # 半角カナ・半角形(0xFF61–0xFFEF)は最優先で除外する。
                #   生バイナリを cp932 で誤デコードすると、ゴミバイトの多くがこの範囲
                #   (ｦｧ…ﾝ)に落ち、ソースに無いカタカナがプレビューに出る「幻のカタカナ」
                #   化けの主因だった。なお半角カナは ch.isalnum()==True のため、下の
                #   isalnum 判定より先にここで弾かないと漏れる。本物の半角カナを失う
                #   より化けを出さない方を優先する（本文は全角カナ範囲で取れる）。
                if 0xff61 <= o <= 0xffef:
                    kept.append(' ')
                    continue
                if (ch.isalnum() or ch == ' '
                        or 0x3000 <= o <= 0x30ff      # 句読点・ひらがな・全角カタカナ
                        or 0x4e00 <= o <= 0x9fff      # 漢字（CJK統合）
                        or 0xff01 <= o <= 0xff60      # 全角英数・記号（半角カナは除外）
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

        def is_confident(text: str) -> bool:
            # 生バイナリの誤デコード(ゴミ)と本物の本文を見分ける。
            #   重要な観測: ランダムなバイト列を cp932/utf-16le でデコードすると、
            #   その大半は「漢字」範囲の有効なコードポイントに落ちる一方、ひらがなは
            #   ほとんど現れない（ランダム漢字ノイズ）。逆に本物の日本語の散文は
            #   助詞・送り仮名のため必ず相当量のひらがなを含む。したがって
            #     ・CJK(漢字・かな)主体なのに「ひらがなが極端に少ない」→ ノイズ
            #     ・ASCII主体(英数の本文)はそのまま信頼
            #   で判定する。これにより「幻のカタカナ」を含むゴミ scrape を破棄できる。
            if not text:
                return False
            hira = kana = cjk = ascii_alpha = ascii_digit = total = 0
            for ch in text:
                if ch == ' ':
                    continue
                total += 1
                o = ord(ch)
                if 0x3040 <= o <= 0x309f:
                    hira += 1
                    cjk += 1
                elif 0x30a0 <= o <= 0x30ff:
                    kana += 1
                    cjk += 1
                elif 0x4e00 <= o <= 0x9fff:
                    cjk += 1
                elif ch.isascii() and ch.isalpha():
                    ascii_alpha += 1
                elif ch.isascii() and ch.isdigit():
                    ascii_digit += 1
            if total == 0:
                return False
            # CJK文字が相当量あるなら、本物の日本語散文の指標であるひらがな比率を要求。
            #   ・ランダム漢字ノイズ → ひらがな≒0 で弾かれる。
            #   ・utf-16le本文を cp932 で誤読したゴミ(高位バイト0x30由来の '0' 多数)も、
            #     ひらがながほぼ無いので弾かれる。ASCII判定より先に CJK 判定を行うのが要。
            if cjk / total >= 0.20:
                return (hira / cjk) >= 0.15
            # CJK がほとんど無く ASCII *英字* が主体なら英語/英数本文として信頼。
            #   英字(数字でなく)を要求するのが要点: 誤デコードのゴミは高位バイト 0x30 由来の
            #   数字 '0' が多く英字が少ないため、数字ではなく英字比率で判定すると弾ける。
            if ascii_alpha / total >= 0.50:
                return True
            return False

        # 各エンコーディングでデコードし、(信頼できるか, スコア) で最良を選ぶ。
        #   信頼できる候補を常に優先する。例えば utf-16le の本文を cp932 で誤読すると
        #   空白の無い連続ゴミになり quality_score だけだと誤読側が高得点になりがちだが、
        #   誤読側はひらがな比率が低く is_confident=False なので選ばれない。
        best = ""
        best_key = (False, -1)  # (信頼できる, スコア)
        for enc in ('utf-16-le', 'cp932'):
            try:
                decoded = data.decode(enc, errors='ignore')
            except Exception:
                continue
            cleaned = filter_readable(decoded)
            key = (is_confident(cleaned), quality_score(cleaned))
            if key > best_key:
                best_key = key
                best = cleaned

        # 低信頼のスクレイプは破棄する。ノイズ排除はひらがな比率による is_confident が
        #   担う（ランダム/誤デコードのゴミは is_confident=False で弾かれる）。文字数の
        #   floor は極端に短い断片を避ける程度に留め(旧 best_score>=8)、正当だが短い本文
        #   まで捨てないようにする。両条件を満たさない場合は "" を返し、ファイル名のみで
        #   インデックスさせる（幻のカタカナを出さない）。
        if best_key[0] and best_key[1] >= 8:
            return best
        return ""

    def _extract_doc_text_ole(self, ole) -> str:
        """OLE2形式(.doc)の本文を FIB + piece table(CLX) から正確に抽出する。

        旧.docの本文は WordDocument ストリームに書式バイトと混在して格納され、
        各テキスト片(piece)の位置・符号化は Table ストリーム内の piece table(CLX)が
        示す。CLX を辿って各 piece を UTF-16LE か CP1252(8bit圧縮)の正しい符号化で
        デコードし連結することで、書式バイトが混入しない正確な本文を得る。
        生バイトを当て推量でデコードする方式と違い文字化けしない。
        参考: [MS-DOC] FIB / Clx / PlcPcd / Pcd。
        """
        if not ole.exists('WordDocument'):
            return ""
        wd = ole.openstream('WordDocument').read()
        if len(wd) < 0x200:
            return ""
        # FIB: 使用する Table ストリーム選択フラグ と CLX の位置(fcClx/lcbClx)
        flags = struct.unpack_from('<H', wd, 0x000A)[0]
        table_name = '1Table' if (flags & 0x0200) else '0Table'
        if not ole.exists(table_name):
            alt = '0Table' if table_name == '1Table' else '1Table'
            if not ole.exists(alt):
                return ""
            table_name = alt
        fcClx = struct.unpack_from('<I', wd, 0x01A2)[0]
        lcbClx = struct.unpack_from('<I', wd, 0x01A6)[0]
        if lcbClx == 0:
            return ""
        tbl = ole.openstream(table_name).read()
        clx = tbl[fcClx:fcClx + lcbClx]
        # CLX を走査し Pcdt(0x02) 内の PlcPcd を取り出す（Prc(0x01)は読み飛ばす）
        i = 0
        plcpcd = b''
        while i < len(clx):
            if clx[i] == 0x01:  # Prc: cbGrpprl(2B) ぶんを読み飛ばす
                if i + 3 > len(clx):
                    break
                cb = struct.unpack_from('<H', clx, i + 1)[0]
                i += 3 + cb
            elif clx[i] == 0x02:  # Pcdt: lcb(4B) の後に PlcPcd 本体
                if i + 5 > len(clx):
                    break
                lcb = struct.unpack_from('<I', clx, i + 1)[0]
                plcpcd = clx[i + 5:i + 5 + lcb]
                break
            else:
                break
        if not plcpcd:
            return ""
        # PlcPcd: (n+1)個のCP(各4B) に続いて n個のPCD(各8B)
        n = (len(plcpcd) - 4) // 12
        if n <= 0:
            return ""
        cps = [struct.unpack_from('<I', plcpcd, k * 4)[0] for k in range(n + 1)]
        pcd_base = (n + 1) * 4
        parts = []
        for k in range(n):
            char_count = cps[k + 1] - cps[k]
            if char_count <= 0:
                continue
            # PCD は8バイト。先頭2バイトのフラグを挟んで fc(4B) が続く
            fc = struct.unpack_from('<I', plcpcd, pcd_base + k * 8 + 2)[0]
            if fc & 0x40000000:  # fCompressed: CP1252(1バイト/文字), 実位置は fc/2
                offset = (fc & 0x3FFFFFFF) // 2
                raw = wd[offset:offset + char_count]
                parts.append(raw.decode('cp1252', errors='ignore'))
            else:                # 非圧縮: UTF-16LE(2バイト/文字)
                offset = fc & 0x3FFFFFFF
                raw = wd[offset:offset + char_count * 2]
                parts.append(raw.decode('utf-16-le', errors='ignore'))
        text = ''.join(parts)
        # Word制御コードを整形（段落=\r、セル/行末などを改行/空白へ）
        text = text.replace('\r', '\n').replace('\x07', '\n').replace('\x0b', '\n')
        text = ''.join(ch if (ch in '\n\t' or ord(ch) >= 0x20) else ' ' for ch in text)
        return text.strip()

    def _extract_pdf_content(self, file_path: str) -> str:
        """PDF文書抽出（ページ並列化で80%高速化）"""
        # 🔬 PDF抽出のテキスト層抽出時間とOCR時間を分けて記録する（スレッドローカル）。
        #   親プロセス/呼び出し側が pdf_text_secs/pdf_ocr_secs を読み取り、性能診断へ集約。
        self._tls.pdf_text_secs = 0.0
        self._tls.pdf_ocr_secs = 0.0
        # 遅延OCR用フラグ: このPDFがOCR必要（スキャンページあり）だが、今回は
        # OCRを後回しにした場合に True。呼び出し側が保留キューへ積む判断に使う。
        self._tls.pdf_needs_ocr = False
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

                # 🔒 PyMuPDF は単一 Document の並行アクセスがスレッドセーフでない
                #   （セグフォルト/文字化けの原因）。doc への全アクセスをこのロックで
                #   直列化する。OCRの重い image_to_string はロック外で実行し、別ページ
                #   のOCRが並列に走るようにする（_ocr_pdf_pages 側で同ロックを共有）。
                doc_lock = threading.Lock()

                # 🚀 ページ数に応じた処理戦略
                total_pages = doc.page_count
                max_pages = min(total_pages, 200)  # 最大200ページ（500→200で高速化）

                # ページ番号 -> 抽出テキスト（テキスト層が無いページの検出に使用）
                page_texts = {}

                _t_text_start = time.time()

                # 🚀 並列処理でページ抽出（10ページ以上の場合）
                if max_pages >= 10:
                    def extract_single_page(page_num: int) -> str:
                        """単一ページ抽出（並列処理用）"""
                        try:
                            # 最も高速な方法を優先（失敗時のみフォールバック）
                            #   sort=False: テキストブロックの幾何学的並べ替え
                            #   （読み順への整列・O(n log n)）を省く。全文検索は
                            #   FTS5 がトークン分割するため語順に依存せず、電子発行
                            #   （テキスト層あり）PDFの抽出が目に見えて速くなる。
                            #   🔒 doc へのアクセスは doc_lock で直列化する。
                            try:
                                with doc_lock:
                                    page = doc[page_num]
                                    page_text = page.get_text("text", sort=False)
                                if page_text and len(page_text.strip()) > 10:
                                    return ' '.join(page_text.split())
                            except:
                                pass
                            # フォールバック: ブロック単位抽出
                            with doc_lock:
                                page = doc[page_num]
                                blocks = page.get_text("blocks")
                            block_texts = [block[4].strip() for block in blocks if len(block) >= 5 and block[4].strip()]
                            return ' '.join(block_texts)
                        except Exception as e:
                            debug_logger.warning(f"ページ{page_num}抽出エラー: {e}")
                            return ""

                    # 🚀 並列ページ抽出（バルク時は1、ライブ単一処理時は4）
                    with ThreadPoolExecutor(max_workers=self._page_workers()) as executor:
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
                            # 🔒 doc アクセスを直列化（_ocr_pdf_pages と同ロックを共有）
                            with doc_lock:
                                page = doc[page_num]
                                # sort=False: 読み順整列を省いて高速化（検索品質は不変）
                                page_text = page.get_text("text", sort=False)
                            if page_text and page_text.strip():
                                normalized = ' '.join(page_text.split())
                                if len(normalized) > 0:
                                    page_texts[page_num] = normalized
                        except Exception as page_error:
                            debug_logger.warning(f"PDFページ {page_num} 読み取りエラー: {page_error}")
                            continue

                _t_text_elapsed = time.time() - _t_text_start
                self._tls.pdf_text_secs = _t_text_elapsed
                _text_pages = len(page_texts)

                # 🔥 OCRフォールバック: テキスト層が無い（=スキャン）ページを画像化してOCR
                # テキスト層がほぼ皆無のページのみ対象にする（短いが正規のテキスト層を持つ
                # ページ＝章扉・ページ番号のみ等をOCR結果で上書きして劣化させないため）
                ocr_target_pages = [p for p in range(max_pages)
                                    if len(page_texts.get(p, "")) < 3]
                debug_logger.debug(
                    f"[PDF診断] {os.path.basename(file_path)}: "
                    f"総ページ={total_pages} 処理={max_pages} "
                    f"テキスト層={_text_pages}p OCR対象={len(ocr_target_pages)}p "
                    f"テキスト抽出={_t_text_elapsed:.2f}s"
                )
                # 🚀 遅延OCR: 一括インデックス中（defer_ocr=True）はOCRを実行せず、
                #   テキスト層のみで即座に索引する。OCRが必要なら needs_ocr を立てて
                #   呼び出し側に通知し、本体完了後のバックグラウンドパスでOCRさせる。
                #   これによりインデックス本体のスループットがOCRに律速されなくなる。
                if ocr_target_pages and getattr(self, 'defer_ocr', False):
                    self._tls.pdf_needs_ocr = True
                    ocr_target_pages = []  # 今回はOCRしない（後回し）

                _t_ocr_start = time.time()
                if ocr_target_pages:
                    ocr_results = self._ocr_pdf_pages(doc, ocr_target_pages, file_path, doc_lock)
                    for page_num, ocr_text in ocr_results.items():
                        if not ocr_text:
                            continue
                        existing = page_texts.get(page_num, "")
                        # 既存のテキスト層は温存し、OCR結果を追記する
                        page_texts[page_num] = f"{existing} {ocr_text}".strip() if existing else ocr_text

                _t_ocr_elapsed = time.time() - _t_ocr_start
                self._tls.pdf_ocr_secs = _t_ocr_elapsed
                if ocr_target_pages:
                    debug_logger.debug(
                        f"[PDF診断] {os.path.basename(file_path)}: "
                        f"OCR完了={_t_ocr_elapsed:.2f}s "
                        f"OCR対象{len(ocr_target_pages)}p中{len(ocr_results)}p取得"
                    )

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

    def _ocr_pdf_pages(self, doc, page_nums, file_path: str, doc_lock=None) -> dict:
        """テキスト層の無いPDFページを画像化してOCR抽出

        スキャン（画像ベース）PDF対応。各ページをPyMuPDFでレンダリングし、
        pytesseractでテキスト抽出する。
        戻り値: {ページ番号: 抽出テキスト}

        doc_lock: 呼び出し側が保持する threading.Lock。PyMuPDF は単一 Document の
            並行アクセスがスレッドセーフでないため、doc への全アクセス（get_pixmap
            等）をこのロックで直列化する。重い image_to_string はロック外で実行し、
            別ページのOCRを並列に走らせる。None の場合は内部で生成する。
        """
        if doc_lock is None:
            doc_lock = threading.Lock()
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

            def ocr_single_page(page_num: int) -> tuple:
                """単一ページをレンダリングしてOCR（並列処理用・1パス）

                戻り値: (テキスト, 所要秒) ※実時間はワーカー内で計測する。
                as_completed 側で計測すると既に完了済みのため 0 になってしまう。
                """
                _ps = time.time()
                # 🔒 doc アクセス（get_pixmap）はロック内で直列化し、PNGバイト列まで
                #   取り出してからロックを解放する。重いOCR(image_to_string)はロック外で
                #   実行し、別ページのOCRが並列に走るようにする。
                with doc_lock:
                    page = doc[page_num]
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    png_bytes = pix.tobytes("png")
                image = Image.open(io.BytesIO(png_bytes))

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

                return ' '.join(text.split()), time.time() - _ps

            # 🚀 並列OCR（バルク時は1=オーバーサブスクリプション解消、ライブ時は4）
            #   ＋ページ単位タイムアウトでハング防止
            _ocr_page_times: list[float] = []
            _timeout_count = 0
            _t_ocr_all = time.time()
            with ThreadPoolExecutor(max_workers=self._page_workers()) as executor:
                futures = {executor.submit(ocr_single_page, p): p for p in target_pages}
                for future in as_completed(futures):
                    page_num = futures[future]
                    try:
                        text, _page_secs = future.result(timeout=30.0)  # 1ページ最大30秒
                        _ocr_page_times.append(_page_secs)
                        if len(text) >= 2:
                            results[page_num] = text
                    except TimeoutError:
                        _timeout_count += 1
                        debug_logger.warning(
                            f"[OCR診断] タイムアウト(30s) ページ{page_num}: {os.path.basename(file_path)}")
                        continue
                    except Exception as page_error:
                        debug_logger.warning(f"PDF OCRページ {page_num} エラー: {page_error}")
                        continue

            _ocr_total = time.time() - _t_ocr_all
            if _ocr_page_times:
                _avg = sum(_ocr_page_times) / len(_ocr_page_times)
                _max = max(_ocr_page_times)
                debug_logger.debug(
                    f"[OCR診断] {os.path.basename(file_path)}: "
                    f"対象{len(target_pages)}p 成功{len(results)}p タイムアウト{_timeout_count}p "
                    f"ページ平均={_avg:.2f}s 最大={_max:.2f}s 合計={_ocr_total:.2f}s"
                )

            if results:
                ocr_chars = sum(len(t) for t in results.values())
                debug_logger.debug(f"✅ PDF OCRフォールバック成功 ({os.path.basename(file_path)}): "
                                   f"{len(results)}ページ / {ocr_chars}文字")

        except Exception as e:
            debug_logger.warning(f"PDF OCRフォールバックエラー ({os.path.basename(file_path)}): {e}")

        return results

    def _extract_image_content(self, file_path: str) -> str:
        """.tif/.tiffファイルからOCRでテキスト抽出（jpn+eng 1パス版）"""
        try:
            # キャッシュチェック（最優先）
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

            file_size = os.path.getsize(file_path)
            if file_size < 1024:  # 1KB未満は処理しない
                return ""
            if file_size > 30 * 1024 * 1024:  # 30MB以上は処理しない
                print(f"⚠️ .tif画像ファイルが大きすぎます ({file_path}): {file_size/1024/1024:.1f}MB")
                return ""

            # OCR言語: jpn+eng の1パスで日英両方を認識する（PDF OCRと同方式）。
            # 言語キャッシュは PDF OCR(_ocr_pdf_pages)と共有する(_ocr_lang)。
            #   jpn言語データの有無は環境共通の事実なので、PDF/TIFFで別々に
            #   持つ意味がない。PDF側で jpn 欠如を検知して eng へ退避済みなら、
            #   TIFF側も同じ判断を引き継ぐ（二重の失敗を避ける）。
            # ファイル名からの言語推測による段階的OCRは廃止: 英語OCR結果が
            # 3文字以上になると日本語OCRが実行されず、日本語文書のテキストが
            # 一切取れないバグの原因だった。
            if getattr(self, '_ocr_lang', None) is None:
                self._ocr_lang = 'jpn+eng'

            ocr_config = '--oem 1 --psm 6'

            def _ocr_one_frame(frame_image) -> str:
                """単一フレーム（1ページ）をOCRしてテキストを返す（マルチページTIFF対応）"""
                # 元が白黒2値(mode "1")かどうかを記録（既に二値化済みなので
                # 後段の適応的二値化を省ける）。FAX/スキャン文書の多くはこの形式。
                was_bilevel = frame_image.mode == '1'

                # OCR前に必ずグレースケール(L)へ統一する。
                #   mode "1" のままだと
                #     1) Image.resize の BILINEAR が効かず最近傍縮小になり、
                #        2866x2026 のような文書スキャンを縮小すると日本語の
                #        細い線が潰れてOCR不能になる
                #     2) np.array(mode="1") がブール配列になり cv2.adaptiveThreshold
                #        が uint8 を要求して失敗する
                #   ため、L へ変換してから処理する。
                if frame_image.mode != 'L':
                    frame_image = frame_image.convert('L')

                width, height = frame_image.size
                total_pixels = width * height

                # 動的解像度調整: 文書スキャン(例: A4 300dpi ≒ 8.7MP)は高解像度を
                # 保たないと日本語OCRが破綻するため、上限を大きく取る。極端に巨大な
                # 画像のみ縮小して速度を確保する。
                if file_size < 2 * 1024 * 1024:
                    max_pixels = 4000000  # 精度優先
                elif file_size < 5 * 1024 * 1024:
                    max_pixels = 3000000  # バランス
                else:
                    max_pixels = 2000000  # 速度優先

                if total_pixels > max_pixels:
                    scale_factor = (max_pixels / total_pixels) ** 0.5
                    new_width = max(1, int(width * scale_factor))
                    new_height = max(1, int(height * scale_factor))
                    frame_image = frame_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    total_pixels = new_width * new_height
                    debug_logger.debug(f"動的リサイズ ({os.path.basename(file_path)}): {width}x{height} -> {new_width}x{new_height}")

                if total_pixels < 10000:  # 100x100未満はスキップ
                    return ""

                # cv2が利用可能なら適応的二値化でOCR精度を上げる。
                # 元が白黒2値(was_bilevel)の画像は既にクリーンな二値画像なので、
                # ここで再二値化するとかえってノイズを増やすため適用しない。
                if CV2_AVAILABLE and not was_bilevel:
                    try:
                        import numpy as np
                        arr = np.array(frame_image)
                        if arr.dtype == np.uint8 and arr.ndim == 2:  # グレースケール(uint8)確認
                            arr = cv2.adaptiveThreshold(
                                arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 11, 2)
                            frame_image = Image.fromarray(arr)
                    except Exception:
                        pass

                try:
                    text = pytesseract.image_to_string(
                        frame_image, lang=self._ocr_lang, config=ocr_config).strip()
                except pytesseract.TesseractError:
                    # jpn言語データが無い等の場合は eng のみへ恒久的に退避
                    # （PDF OCRと共有する _ocr_lang を更新）。
                    self._ocr_lang = 'eng'
                    try:
                        text = pytesseract.image_to_string(
                            frame_image, lang='eng', config=ocr_config).strip()
                    except pytesseract.TesseractError as te:
                        print(f"⚠️ OCR実行失敗 ({os.path.basename(file_path)}): {te}")
                        return ""

                return text

            # マルチページTIFF対応: 全フレームをOCRして連結
            from PIL import ImageSequence
            try:
                page_texts: list[str] = []
                for frame in ImageSequence.Iterator(Image.open(file_path)):
                    frame_text = _ocr_one_frame(frame.copy())
                    if frame_text:
                        page_texts.append(frame_text)
                text = '\n'.join(page_texts)
            except Exception as e:
                print(f"⚠️ 画像読み込みエラー ({file_path}): {e}")
                return ""

            text = text.strip()

            # 無意味な結果をフィルタリング
            if len(text) < 2 or len(set(text.replace(' ', '').replace('\n', ''))) < 3:
                result = ""
            else:
                result = normalize_extracted_text(text, max_length=50000)

            # キャッシュに保存
            cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
            self._ocr_cache[cache_key] = result

            # キャッシュサイズ制限
            if len(self._ocr_cache) > 1000:
                oldest_keys = list(self._ocr_cache.keys())[:100]
                for key in oldest_keys:
                    del self._ocr_cache[key]

            if result and len(result) > 10:
                print(f"✅ OCR成功 ({os.path.basename(file_path)}): {len(result)}文字")

            return result

        except Exception as e:
            print(f"⚠️ OCR処理エラー {os.path.basename(file_path)}: {e}")
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

    # 🔬 診断ログ出力先の設定（重要）
    #   抽出は spawn された子プロセスで走るため、親プロセスでの
    #   debug_logger 注入（extraction.debug_logger = ...）は子に伝わらない。
    #   子プロセスの debug_logger は NullHandler のままで、ここで追加した
    #   [PDF診断]/[OCR診断]/[抽出診断] ログがすべて捨てられてしまう。
    #   そこでワーカー起動時に専用ファイルへ追記する FileHandler を取り付け、
    #   全ワーカーの診断ログを一箇所に集約する（pid 付きで識別可能）。
    #   全プロセスが同一ファイルへ追記するが、診断用途では多少の行交錯は許容。
    if not any(isinstance(h, logging.FileHandler) for h in debug_logger.handlers):
        try:
            # 既定は WARNING（診断ログの追記 I/O を抑制）。FILESEARCH_DEBUG=1 の
            # ときだけ INFO 診断を extraction_diag.log へ出力する。
            diag_level = logging.INFO if os.environ.get('FILESEARCH_DEBUG') else logging.WARNING
            fh = logging.FileHandler('extraction_diag.log', mode='a', encoding='utf-8')
            fh.setLevel(diag_level)
            fh.setFormatter(logging.Formatter(
                '%(asctime)s - pid%(process)d - %(levelname)s - %(message)s'))
            debug_logger.addHandler(fh)
            debug_logger.setLevel(diag_level)
        except Exception:
            pass


def _worker_extract(file_path: str, file_size: int, modified_time: float,
                    defer_ocr: bool = False, bulk_mode: bool = False) -> tuple:
    """ワーカープロセスで呼ばれる抽出関数（CPUバウンドな本文抽出のみを担当）

    前処理（隠しファイル/差分スキップ/サイズ判定）は親プロセスで実施済みである
    ことを前提とし、ここでは純粋に本文抽出だけを行う。

    Args:
        file_path: 抽出対象ファイルのパス
        file_size: ファイルサイズ（バイト）
        modified_time: 更新時刻（mtime）
        defer_ocr: True の間はスキャンPDF/画像のOCRを実行せず、OCRが必要な場合は
            pdf_needs_ocr=True で呼び出し側へ通知のみ行う（一括インデックス本体を
            OCRに律速させないため）。
        bulk_mode: 一括インデックス中はページ内並列を絞り、Tesseract の
            オーバーサブスクリプションを防ぐ。

    戻り値（8タプル）:
        (file_path, content, file_size, modified_time, extract_seconds,
         pdf_text_seconds, pdf_ocr_seconds, pdf_needs_ocr)
    エラー時: content=None、pdf_* は 0.0、pdf_needs_ocr は False。
             PDF以外では pdf_* は 0.0。
    """
    global _proc_extractor
    if _proc_extractor is None:
        _proc_extractor = _FileContentExtractor()
    # 呼び出し側の指定を抽出器へ反映（_extract_file_content より前に設定する）
    _proc_extractor.defer_ocr = bool(defer_ocr)
    _proc_extractor.bulk_mode = bool(bulk_mode)
    _t0 = time.time()
    import os as _os
    _ext = Path(file_path).suffix.lower()
    _pid = _os.getpid()
    # PDFのテキスト/OCR内訳はスレッドローカルに残る（PDF以外なら0のまま）
    _proc_extractor._tls.pdf_text_secs = 0.0
    _proc_extractor._tls.pdf_ocr_secs = 0.0
    _proc_extractor._tls.pdf_needs_ocr = False
    try:
        content = _proc_extractor._extract_file_content(file_path)
        _elapsed = time.time() - _t0
        _pdf_text = getattr(_proc_extractor._tls, 'pdf_text_secs', 0.0)
        _pdf_ocr = getattr(_proc_extractor._tls, 'pdf_ocr_secs', 0.0)
        pdf_needs_ocr = bool(getattr(_proc_extractor._tls, 'pdf_needs_ocr', False))
        if _elapsed > 5.0:
            print(
                f"[抽出診断] pid={_pid} ext={_ext} {_elapsed:.2f}s "
                f"(text={_pdf_text:.2f}s ocr={_pdf_ocr:.2f}s) "
                f"size={file_size//1024}KB chars={len(content) if content else 0} "
                f"{os.path.basename(file_path)}"
            )
        return (file_path, content, file_size, modified_time, _elapsed,
                _pdf_text, _pdf_ocr, pdf_needs_ocr)
    except Exception as _e:
        _elapsed = time.time() - _t0
        print(f"[抽出診断] pid={_pid} ext={_ext} ERROR {_elapsed:.2f}s {file_path}: {_e}")
        return (file_path, None, file_size, modified_time, _elapsed, 0.0, 0.0, False)
