# 🚀 file_search_app

Word・Excel・PDF・テキスト・画像(OCR)・ZIPファイルの全文検索機能を持つ高性能デスクトップアプリケーション

## ✨ 主要機能

- **⚡ 超高速並列処理**: 2000ファイル/秒対応・マルチスレッド最適化
- **🛑 キャンセル機能**: インデックス処理中の安全な中断機能付き
- **📡 自動監視（増分インデックス）**: インデックス済みフォルダ/ドライブを
  バックグラウンドで定期再スキャンし、新規・更新ファイルを自動でインデックスへ追加
  （ポーリング方式・外部依存なし。監視対象はアプリ再起動後も継続）
- **🔄 手動更新**: 待たずに今すぐ差分を取り込みたいときに手動で再スキャン
- **📁 全文検索対応**: ファイル名・ファイル内容の完全検索
- **🌏 多言語対応**: 日本語（ひらがな・カタカナ・漢字）・半角全角自動対応
- **📊 大規模対応**: 数十万ファイルを瞬時に検索・分割データベース構造
- **🎯 多形式対応**: Word(.docx/.doc)・Excel(.xlsx/.xls)・PDF・テキスト・画像(OCR)・ZIP
- **🖼️ OCR機能**: .tif/.tiff画像内テキストの検索対応（Tesseract自動インストール）
- **🔧 自動最適化**: 必要ライブラリの自動インストール・システム最適化

## 🛠️ 技術スタック

### 📋 標準ライブラリ (組み込み)
- **Python**: 3.7以上（推奨: 3.10以上）
- **GUI**: tkinter (標準)
- **データベース**: SQLite3 FTS5 (標準)
- **並列処理**: concurrent.futures・threading・ProcessPool (標準)
- **ファイル処理**: zipfile・pathlib・mmap (標準)

### 📦 外部ライブラリ (自動インストール)
- **PDF処理**: PyMuPDF (fitz)
- **Word処理**: python-docx (.docx), docx2txt (.doc), olefile (旧.doc解析)
- **Excel処理**: openpyxl (.xlsx/.xlsm), xlrd (.xls)
- **文字検出**: chardet (自動エンコード検出)
- **システム監視**: psutil (最適化用)
- **OCR機能**: pytesseract + Pillow (画像処理)
- **OCR前処理(任意)**: opencv-python + numpy (二値化等。未導入でも動作)
- **OCRエンジン**: Tesseract + 日本語データ(jpn) (自動インストール対応)

## 🏗️ アーキテクチャ

本文抽出ロジックは `extraction.py` に分離されている（検索/UIから独立）。
ProcessPool ワーカーがこの軽量モジュールを使って CPU バウンドな抽出を担う。

```
file_search_app.py   検索システム・GUI(Tkinter)・インデックス制御
        │  (_worker_extract を ProcessPool で呼ぶ)
        ▼
extraction.py        本文抽出レイヤー（txt/Word/Excel/PDF/TIFF-OCR/ZIP）
```

- **PDF**: PyMuPDFでテキスト層を抽出。テキスト層が無いスキャンページは
  Tesseract(`jpn+eng`)でOCRフォールバック
- **TIFF/TIF**: 全フレーム(マルチページ対応)を Tesseract(`jpn+eng`)でOCR
- **遅延OCR**: 一括インデックス本体はOCRを後回し（needs_ocr通知）にして
  スループットを確保し、本体完了後に背景OCRで補完する
- **自動監視**: `UltraFastFullCompliantSearchSystem.start_incremental_scanning()`
  がバックグラウンドスレッドで監視対象ルート(`watched_roots`)を定期再スキャン。
  差分キャッシュ(`_index_mtime_cache`)で未更新を弾き、新規/更新のみ
  `live_progressive_index_file()` で索引する。監視対象は
  `data_storage/watched_roots.json` に永続化（再起動後も継続）。

## 🗂️ プロジェクト構成

```
📁 プロジェクトフォルダ/
├── 📄 file_search_app.py                 # 🎯 メインアプリ（検索/GUI/インデックス）
├── 📄 extraction.py                      # 📑 本文抽出レイヤー（OCR含む）
├── 📄 check_index_target.py              # インデックス対象確認ツール
├── 📄 README.md                          # 本ファイル
├── 📄 DEVELOPMENT_NOTES.md               # 🛠️ 開発引き継ぎメモ（既知の課題）
├── 📄 BUILD_GUIDE.md                     # EXEビルド手順
├── 📄 EXE使用ガイド.md                   # EXE版の使い方
├── 📄 requirements.txt                   # 依存関係
├── 📄 start_app_improved.ps1             # PowerShell起動スクリプト
├── 📄 起動.bat                           # Windows起動スクリプト
├── 📄 診断ツール.bat                     # システム診断ツール
├── 📄 build_exe.bat                      # EXEビルドスクリプト
├── 📁 config/                            # 設定ディレクトリ
│   ├── 📄 default_settings.json
│   ├── 📄 user_settings.json
│   └── 📄 auto_install_settings.json
├── 📁 cache/                             # キャッシュ（実行時作成）
└── 📁 data_storage/                      # データベース（実行時作成）
    ├── 📄 complete_search_db_*.db        # 分割FTS5データベース
    └── 📄 watched_roots.json             # 自動監視の対象ルート（再起動後も継続）
```

## 🚀 起動方法

### Windows
```batch
REM 🎯 推奨起動方法
起動.bat

REM または PowerShell
start_app_improved.ps1

REM 直接実行
python file_search_app.py
```

### macOS / Linux
```bash
# 直接実行
python3 file_search_app.py

# 仮想環境使用時
source .venv/bin/activate
python file_search_app.py
```

### 🔧 初回起動時の自動セットアップ
1. 必要ライブラリの自動インストール確認
2. Tesseract OCRエンジン + 日本語データの自動インストール（OCR機能使用時）
3. データベースの自動初期化

## 🎮 使用方法

### 📂 フォルダ・ドライブのインデックス
1. **起動**: アプリケーションを起動
2. **対象選択**: ドライブまたはフォルダを選択
3. **インデックス開始**: 🚀「インデックス開始」ボタンをクリック
4. **キャンセル**: 処理中は❌「キャンセル」ボタンで中断可能
5. **自動監視**: 一度インデックスしたフォルダ/ドライブは自動監視に登録され、
   以後この配下に追加・更新されたファイルはバックグラウンドで自動インデックスされる
   （既定 約10秒間隔のポーリング。一括インデックス実行中は休止）
6. **手動更新**: 自動監視を待たず今すぐ取り込みたいときは🔄「手動更新」ボタンで
   その場で差分スキャンを実行（未更新ファイルはmtime差分でスキップ）

### 🔍 検索実行
1. **検索語入力**: 上部の検索ボックスに検索したい語句を入力
2. **検索実行**: Enterキーまたは「検索実行」ボタンをクリック
3. **結果確認**: 検索結果リストから目的のファイルを選択
4. **ファイル表示**: ダブルクリックでファイルを開く（開かない場合は右クリック）

### ⚙️ 高度な機能
- **🖼️ OCR検索**: .tif/.tiff画像内のテキストも自動検索（背景OCR）
- **📁 ZIP検索**: ZIPファイル内のテキストファイル内容も検索対象
- **🌍 多言語対応**: 日本語OCRは `jpn+eng` の1パスで日英混在を認識
- **🔄 リアルタイム検索**: 入力と同時に検索結果を更新

## 📁 対応ファイル形式

| カテゴリ | 形式 | ライブラリ | 備考 |
|---------|------|-----------|------|
| **📄 PDF** | .pdf | PyMuPDF | テキスト層+スキャンOCR |
| **📝 Word** | .docx, .doc | python-docx, docx2txt, olefile | 新旧形式対応 |
| **📊 Excel** | .xlsx, .xlsm, .xls | openpyxl, xlrd | 新旧形式対応 |
| **📃 テキスト** | .txt, .csv, .json, .log等 | chardet | 自動エンコード検出 |
| **🖼️ 画像** | .tif, .tiff | pytesseract + Pillow | OCR処理(jpn+eng) |
| **📁 ZIP** | .zip | zipfile | 内容検索対応 |
| **📐 CAD/図面** | .jww, .dxf, .dwg等 | ― | ファイル名のみ索引 |

## 🛠️ トラブルシューティング

### よくある問題と解決方法

**❓ ライブラリがインストールできない**
```bash
# 管理者権限で実行、または手動インストール
pip install -r requirements.txt
```

**❓ OCR機能が使えない / 日本語が抽出されない**
- Tesseractエンジンと**日本語データ(jpn)**の両方が必要
- 手動インストール: [Tesseract公式](https://github.com/UB-Mannheim/tesseract/wiki)
- インストール時に「Japanese」言語データを必ず選択
- ⚠️ 一部のTIFFでOCR抽出できない既知の課題あり → `DEVELOPMENT_NOTES.md` 参照

**❓ 処理が重い・遅い**
- キャンセル機能で処理を中断
- 診断ツール（`診断ツール.bat`）でシステム状態確認

**❓ ファイルが見つからない**
- インデックス処理が完了しているか確認
- 新規追加ファイルは🔄「手動更新」ボタンで差分追加
- 対象フォルダ・ドライブが正しく選択されているか確認

## ⚡ パフォーマンス仕様

- **🚀 処理速度**: 最大2000ファイル/秒（環境依存）
- **🔄 並列処理**: ProcessPoolによるCPUコア活用・動的スレッド調整
- **🗄️ データベース**: 分割FTS5構造による負荷分散
- **💾 キャッシュ**: 3層構造（即座・高速・完全層）+ OCRキャッシュ
- **🛑 キャンセル**: リアルタイム処理中断機能
- **📈 差分インデックス**: 未更新ファイルは再抽出をスキップ

---

## 📜 ライセンス

このプロジェクトはMITライセンスの下で公開されています。
（同梱ライブラリのライセンスは別途各ライブラリに従います。特にPyMuPDFはAGPL/商用）

## 🤝 貢献

バグ報告・機能要望・プルリクエストを歓迎します。
開発を再開する際は **`DEVELOPMENT_NOTES.md`** の既知の課題を必ず確認してください。

---

**🚀 file_search_app** - 高速・安定・多機能な全文検索ソリューション
