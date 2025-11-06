#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDFファイル抽出器
PDFファイルの内容抽出
"""

import os
from pathlib import Path
from typing import Optional


def extract_pdf_content(file_path: str) -> str:
    """PDF文書抽出（ファイルアクセスエラー対応強化）"""
    try:
        # ファイル存在とアクセス権限チェック
        if not os.path.exists(file_path):
            return ""

        if not os.access(file_path, os.R_OK):
            return ""

        file_size = os.path.getsize(file_path)
        if file_size < 50:  # 50バイト未満は無効PDFとみなす
            return ""

        if file_size > 50 * 1024 * 1024:  # 50MB以上は処理スキップ
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
            content = []

            # ページ数制限（CPU負荷軽減）
            max_pages = min(doc.page_count, 100)  # 最大100ページまで

            for page_num in range(max_pages):
                try:
                    page = doc[page_num]
                    page_text = page.get_text()
                    if page_text and page_text.strip():
                        content.append(page_text)
                except Exception as page_error:
                    continue

            doc.close()
            extracted_text = ' '.join(content)
            
            # 最大文字数制限（メモリ効率化）
            if len(extracted_text) > 500000:  # 50万文字制限
                extracted_text = extracted_text[:500000]
            
            if content:
                return extracted_text
            else:
                return ""

        except ImportError:
            pass
        except PermissionError:
            return ""
        except FileNotFoundError:
            return ""
        except Exception:
            pass

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

        except Exception:
            return ""

    except Exception:
        return ""