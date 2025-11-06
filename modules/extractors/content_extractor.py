#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
統合ファイル抽出器
すべての抽出機能を統合したメインエクストラクター
"""

from pathlib import Path
from typing import Optional

from .base_extractor import extract_txt_content, extract_zip_content
from .office_extractor import (
    extract_docx_content, 
    extract_xlsx_content,
    extract_doc_content, 
    extract_xls_content
)
from .pdf_extractor import extract_pdf_content
from .ocr_extractor import OCRExtractor


class FileContentExtractor:
    """統合ファイル内容抽出器"""
    
    def __init__(self):
        self.ocr_extractor = OCRExtractor()
    
    def extract_file_content(self, file_path: str) -> str:
        """ファイル内容抽出 - 全形式対応（画像OCR含む）"""
        try:
            file_path_obj = Path(file_path)
            extension = file_path_obj.suffix.lower()

            if extension == '.txt':
                return extract_txt_content(file_path)
            elif extension in ['.docx', '.dotx', '.dotm', '.docm']:  # Word新形式ファイル
                return extract_docx_content(file_path)
            elif extension in ['.doc', '.dot']:  # Word旧形式ファイル
                return extract_doc_content(file_path)
            elif extension in ['.xlsx', '.xltx', '.xltm', '.xlsm', '.xlsb']:  # Excel新形式ファイル
                return extract_xlsx_content(file_path)
            elif extension in ['.xls', '.xlt']:  # Excel旧形式ファイル
                return extract_xls_content(file_path)
            elif extension == '.pdf':
                return extract_pdf_content(file_path)
            elif extension == '.zip':  # ZIPファイル内のテキストファイルを処理
                return extract_zip_content(file_path)
            elif extension in ['.tif', '.tiff']:  # .tifファイルのみ画像処理対象
                return self.ocr_extractor.extract_image_content(file_path)
            else:
                # 対象外の拡張子はスキップ
                return ""

        except Exception as e:
            print(f"⚠️ ファイル内容抽出エラー {file_path}: {e}")
            return ""
            
    def check_ocr_availability(self) -> tuple[bool, str]:
        """OCR機能の利用可能性を確認"""
        return self.ocr_extractor.check_ocr_availability()