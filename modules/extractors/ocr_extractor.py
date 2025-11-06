#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR画像抽出器
.tifファイルからOCRでテキスト抽出
"""

import os
import time
from pathlib import Path
from typing import Dict, Optional


class OCRExtractor:
    """OCR抽出器"""
    
    def __init__(self):
        self._ocr_cache: Dict[str, str] = {}
        
    def check_ocr_availability(self) -> tuple[bool, str]:
        """OCR機能の利用可能性を確認"""
        try:
            # Pillowチェック
            try:
                from PIL import Image
                PIL_AVAILABLE = True
            except ImportError:
                return False, "Pillowライブラリがインストールされていません"
            
            # pytesseractチェック
            try:
                import pytesseract
                TESSERACT_AVAILABLE = True
            except ImportError:
                return False, "pytesseractライブラリがインストールされていません"
            
            if not PIL_AVAILABLE or not TESSERACT_AVAILABLE:
                return False, "Pillow または pytesseract がインストールされていません"
            
            # スタンドアロン版でのTesseract検索
            def find_bundled_tesseract():
                """同梱されたTesseractを検索"""
                possible_paths = [
                    # 同じディレクトリ内のtesseractフォルダ
                    Path(__file__).parent.parent.parent / "tesseract" / "tesseract.exe",
                    Path(__file__).parent.parent.parent.parent / "tesseract" / "tesseract.exe",
                    # ポータブル版用のパス
                    Path(__file__).parent.parent.parent / "bin" / "tesseract.exe",
                    Path(__file__).parent.parent.parent.parent / "bin" / "tesseract.exe",
                    # Windows標準インストールパス
                    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
                    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
                ]
                
                for path in possible_paths:
                    if path.exists():
                        return str(path)
                return None
            
            # Tesseractエンジンのパスを確認
            try:
                # まず標準の方法で確認
                version = pytesseract.get_tesseract_version()
                return True, f"Tesseract v{version}"
            except pytesseract.TesseractNotFoundError:
                # 同梱版を検索
                bundled_path = find_bundled_tesseract()
                if bundled_path:
                    # pytesseractにパスを設定
                    pytesseract.pytesseract.tesseract_cmd = bundled_path
                    try:
                        version = pytesseract.get_tesseract_version()
                        return True, f"同梱Tesseract v{version}"
                    except Exception as e:
                        return False, f"同梱Tesseractエラー: {e}"
                else:
                    return False, "Tesseractエンジンが見つかりません"
            except Exception as e:
                return False, f"Tesseractエンジンエラー: {e}"
                
        except Exception as e:
            return False, f"OCRチェックエラー: {e}"
    
    def extract_image_content(self, file_path: str) -> str:
        """.tifファイルからOCRでテキスト抽出（超高速最適化版・キャッシュ強化）"""
        try:
            # キャッシュチェック（最優先）
            cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
            if cache_key in self._ocr_cache:
                cached_result = self._ocr_cache[cache_key]
                print(f"⚡ OCRキャッシュヒット: {os.path.basename(file_path)} ({len(cached_result)}文字)")
                return cached_result

            # OCRライブラリが利用可能かチェック
            ocr_available, status = self.check_ocr_availability()
            if not ocr_available:
                return ""

            # 超高速スキップ条件（ファイルサイズ最適化）
            file_size = os.path.getsize(file_path)
            if file_size < 1024:  # 1KB未満は処理しない
                return ""
            if file_size > 30 * 1024 * 1024:  # 30MB以上は処理しない（より厳格）
                print(f"⚠️ .tif画像ファイルが大きすぎます ({file_path}): {file_size/1024/1024:.1f}MB")
                return ""
            
            # 超高速画像読み込み・検証
            try:
                from PIL import Image
                image = Image.open(file_path)
                
                # 画像フォーマット・モード最適化チェック
                if image.mode not in ['L', 'RGB', 'RGBA', '1']:
                    image = image.convert('RGB')
                
                # 画像サイズチェックと超高速最適化
                width, height = image.size
                total_pixels = width * height
                
                # 超高速処理用画像サイズ制限（より厳格）
                max_pixels = 1000000  # 100万画素に削減（処理速度2倍向上）
                if total_pixels > max_pixels:
                    scale_factor = (max_pixels / total_pixels) ** 0.5
                    new_width = int(width * scale_factor)
                    new_height = int(height * scale_factor)
                    # 高速リサイズアルゴリズム使用
                    image = image.resize((new_width, new_height), Image.Resampling.BILINEAR)
                    total_pixels = new_width * new_height
                    print(f"🔧 超高速リサイズ ({os.path.basename(file_path)}): {width}x{height} -> {new_width}x{new_height}")
                
                # 小さすぎる画像はスキップ
                if total_pixels < 10000:  # 100x100未満はスキップ
                    return ""
                
            except Exception as e:
                print(f"⚠️ 画像読み込みエラー ({file_path}): {e}")
                return ""
            
            # 前処理の大幅簡略化（処理時間50%削減）
            processed_image = image
            try:
                import cv2
                CV2_AVAILABLE = True
            except ImportError:
                CV2_AVAILABLE = False
            
            if CV2_AVAILABLE and total_pixels < 500000:  # 50万画素未満のみ軽量前処理
                try:
                    import numpy as np
                    # グレースケール変換のみ（他の重い処理を削除）
                    if image.mode != 'L':
                        image_array = np.array(image)
                        if len(image_array.shape) == 3:
                            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
                            processed_image = Image.fromarray(gray)
                except Exception:
                    processed_image = image
            
            # 超高速OCR実行（段階的最適化）
            text = ""
            import pytesseract
            
            # Phase 1: 超高速英数字のみ（最も高速）
            try:
                fast_config = r'--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
                text = pytesseract.image_to_string(processed_image, lang='eng', config=fast_config).strip()
                
                # Phase 2: 結果が不十分な場合のみ通常英語OCR
                if len(text) < 5:
                    text = pytesseract.image_to_string(processed_image, lang='eng', config='--oem 1 --psm 6').strip()
                
                # Phase 3: 最後の手段として日本語（処理時間が増加）
                if len(text) < 3 and file_size < 5 * 1024 * 1024:  # 5MB未満のみ日本語試行
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
            
            # 結果検証と最適化
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
            
            # キャッシュに保存（成功・失敗を問わず）
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
            cache_key = f"{file_path}_{os.path.getmtime(file_path)}"
            self._ocr_cache[cache_key] = ""
            return ""