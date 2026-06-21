# 🛠️ 開発引き継ぎメモ（DEVELOPMENT NOTES）

開発を再開する人へ。現状・既知の課題・次にやるべきことをまとめる。
**最初にこのファイルを読むこと。**

最終更新: 2026-06-21

---

## 1. 🔴 未解決の課題: 一部TIFFでOCR抽出できない（最優先）

### 症状
- ユーザー環境で、テキストが含まれているはずの `.tif` / `.tiff` から
  OCRで本文が抽出されない（検索プレビューに本文が出ない）。
- 報告されたファイルの情報:
  ```
  Format: TIFF
  Mode: 1            ← 1ビット白黒（bilevel）
  Size: (2866, 2026)
  Frames: 1
  ```

### これまでに実施した修正（コミット）
| コミット | 内容 |
|---------|------|
| `bb4ca8b` | TIFF OCRを段階的(英→日)から `jpn+eng` 1パスに統一。<br>旧実装は英語OCRが3文字以上返ると日本語OCRをスキップしており、<br>日本語文書のテキストが一切取れないバグがあった。 |
| `a182281` | Mode "1"(白黒2値)対応。常に "L" へ変換、リサイズを LANCZOS 化、<br>縮小の画素上限を 1.5M→4M 等に引き上げ、bilevelは再二値化を回避。 |

### 検証状況
- **テスト環境（Linux + tesseract 5.3.4 + jpn データ）では成功している。**
  生成した Mode "1" / 2866×2026 のTIFF（英数字+日本語）から
  `Hello World Test 12345` / `SISTERS AYER COURT` / `吉野町 添付書類 検索`
  をすべて正しく抽出できた（`extraction._FileContentExtractor._extract_image_content`）。
- **しかしユーザー環境では依然として抽出できていない。**
  → テスト環境とユーザー環境のどこかに差分がある。

### 次に確認すべき仮説（優先順）
1. **Tesseractの日本語データ(jpn)が未インストール**
   - 最有力。`jpn+eng` で実行 → jpn が無いと `TesseractError` → `eng` 退避。
     英語のみだと日本語スキャンはほぼ空になる。
   - 確認: `tesseract --list-langs` に `jpn` があるか。
   - `extraction.py` の `_tif_ocr_lang` フォールバックログ（eng退避）を確認。
2. **Tesseract本体が見つかっていない / パス未設定**
   - `setup_tesseract_path()`（file_search_app.py）がパスを通せているか。
   - `pytesseract.get_tesseract_version()` が例外なら `_extract_image_content`
     は即 `""` を返す（=黙って空）。ここにログを足すと切り分けやすい。
3. **OCRキャッシュに空文字が残っている**
   - `_ocr_cache` は失敗時も `""` をキャッシュする（`{path}_{mtime}` キー）。
   - 過去に失敗した結果がDBに `""` で入っていると、mtimeが変わらない限り
     再抽出されない。→ ファイル更新 or DB再構築 or キャッシュ無効化が必要。
   - **重要**: コード修正しても、対象ファイルを再インデックスしないと反映されない。
     「🔄 手動更新」では mtime 差分で**スキップされる**点に注意（下記2参照）。
     検証時は対象TIFFを一度 touch するか、DBを作り直すこと。
4. **遅延OCR（defer_ocr）で背景OCRに回ったまま完了していない**
   - 一括インデックス中、画像OCRは `needs_ocr` で後回しになる
     （`_extract_file_content` の IMAGE_OCR_EXTENSIONS 分岐）。
   - 背景OCRが走っているか、`_pending_ocr` キューに溜まったままでないか確認。
   - 背景OCRは新インデックス開始時に `_ocr_bg_cancel` で中断される。
5. **実ファイル特有の画像特性**
   - 圧縮方式（CCITT G4 等）、極端な解像度、傾き、低コントラスト等。
   - 実ファイル1枚を Python で開いて `_extract_image_content` を直接叩き、
     `pytesseract.image_to_string` の生出力を確認するのが確実。

### 切り分け用スニペット（実環境で実行）
```python
import extraction, pytesseract
print("tesseract:", pytesseract.get_tesseract_version())
print("langs:", pytesseract.get_languages())   # 'jpn' があるか
ext = extraction._FileContentExtractor()
ext._ocr_cache = {}  # キャッシュ無効化
print(repr(ext._extract_image_content(r"C:\path\to\problem.tif")))
```
→ ここで空なら抽出層の問題、テキストが出るならインデックス/キャッシュ/DB側の問題。

---

## 2. ✅ 実装済み: 手動更新ボタン（🔄 手動更新）

- インデックス後に追加/更新されたファイルを手動で差分インデックスする機能。
- UI: インデックス制御行に「🔄 手動更新」ボタンを追加（`setup_ui`）。
- 仕組み: `start_bulk_indexing` で `self.last_index_path` を記憶し、
  `manual_update_index()` が同じパスを `bulk_index_worker` で再スキャン。
- `bulk_index_worker` 内の差分判定（`_index_mtime_cache`）により、
  **未更新ファイルは再抽出されずスキップ**される（高速）。
- ⚠️ 上記課題1の検証では、この差分スキップのせいで「修正したのに変わらない」
  と誤認しやすい。検証時はファイルのmtime更新かDB再構築を行うこと。

---

## 3. 🗺️ コードマップ（OCR/抽出まわり）

- `extraction.py`
  - `_FileContentExtractor._extract_file_content` … 拡張子で分岐する入口
  - `_extract_image_content` … **TIFF OCR本体（課題1の中心）**
  - `_extract_pdf_content` / `_ocr_pdf_pages` … PDFのテキスト層+スキャンOCR
  - `_worker_extract` / `_init_extraction_worker` … ProcessPoolワーカー
  - `IMAGE_OCR_EXTENSIONS = {'.tif', '.tiff'}` / `TARGET_EXTENSIONS`
- `file_search_app.py`
  - `setup_tesseract_path()` … Tesseractパス解決
  - `bulk_index_worker()` … 一括インデックス本体
  - `_pending_ocr` / `_ocr_bg_*` … 遅延・背景OCRの制御
  - `manual_update_index()` / `_on_manual_update_done()` … 手動更新
  - `last_index_path` … 手動更新の対象パス

---

## 4. 📌 環境メモ

- OCRは `jpn+eng` 1パスが前提。**jpn 言語データ必須。**
- `opencv-python` / `numpy` は任意（OCR前処理）。未導入でも動作する
  （`CV2_AVAILABLE=False` で素通り）。bilevel画像では前処理自体スキップ。
- DBディレクトリは `data_storage/`（旧ドキュメントの `fulltext_search_app/` は誤り）。
- 失敗を含めOCR結果はキャッシュされる点に常に注意（再現性のワナ）。
