# ファイル検索アプリ - EXE化ガイド

## 概要
このドキュメントでは、ファイル検索アプリをWindows実行ファイル(.exe)に変換する方法を説明します。

## 前提条件
- Python 3.12以上がインストールされていること
- 仮想環境(.venv)が作成されていること
- 必要なパッケージがインストールされていること

## ビルド手順

### 1. 自動ビルド（推奨）
`build_exe.bat` をダブルクリックするだけで自動的にビルドが実行されます。

```batch
build_exe.bat
```

### 2. 手動ビルド
コマンドプロンプトから以下を実行:

```batch
# 仮想環境を有効化
call .venv\Scripts\activate.bat

# PyInstallerでビルド
pyinstaller file_search_app.spec --clean
```

## ビルド成果物

ビルドが成功すると、以下の場所にEXEファイルが生成されます:
```
dist\ファイル検索アプリ.exe
```

## 配布方法

### 単独実行ファイル
`dist\ファイル検索アプリ.exe` は単独で実行可能です。

### 必要な追加ファイル（推奨）
より完全な動作のために、以下のフォルダも一緒に配布することを推奨します:

```
配布フォルダ/
  ├── ファイル検索アプリ.exe
  ├── config/
  │   ├── default_settings.json
  │   └── user_settings.json (オプション)
  └── data_storage/  (初回起動時に自動作成されます)
```

## 注意事項

### OCR機能について
OCR機能を使用する場合、Tesseract-OCRを別途インストールする必要があります:
- ダウンロード: https://github.com/UB-Mannheim/tesseract/wiki
- インストール後、パスを設定ファイルで指定

### ウイルス対策ソフトの警告
初回実行時にウイルス対策ソフトから警告が出る場合があります。これは、
PyInstallerで作成されたEXEファイルが未署名であるためです。安全性を
確認の上、例外として許可してください。

### ファイルサイズ
生成されるEXEファイルは約100-150MBになります。これは、Pythonランタイムと
すべての依存ライブラリが含まれているためです。

## トラブルシューティング

### ビルドエラー
- 仮想環境が正しく有効化されているか確認
- `pip install -r requirements.txt` で依存パッケージを再インストール
- `build`と`dist`フォルダを削除してから再ビルド

### 実行時エラー
- configフォルダが正しく配置されているか確認
- data_storageフォルダへの書き込み権限があるか確認
- イベントログでエラー詳細を確認

## specファイルのカスタマイズ

`file_search_app.spec` を編集することで、以下のカスタマイズが可能です:

- **アイコン設定**: `icon='your_icon.ico'` を追加
- **コンソール表示**: `console=True` でデバッグ用コンソールを表示
- **追加データファイル**: `datas` リストに追加

## ビルドオプション

### 詳細なビルドオプション

```batch
# 単一EXEファイル（デフォルト）
pyinstaller file_search_app.spec --clean

# ディレクトリ形式（起動が速い）
pyinstaller file_search_app.spec --clean --onedir

# デバッグモード
pyinstaller file_search_app.spec --clean --debug=all
```

## パフォーマンス

- **初回起動**: 5-10秒程度かかる場合があります
- **2回目以降**: 1-3秒程度で起動します
- **検索速度**: Pythonスクリプト実行時と同等

## 更新手順

アプリを更新する場合:

1. ソースコードを修正
2. `build_exe.bat` を再実行
3. 新しい `dist\ファイル検索アプリ.exe` を配布

## ライセンスと配布

配布時は、使用しているライブラリのライセンスを確認してください:
- PyMuPDF (AGPL/商用ライセンス)
- python-docx (MIT)
- openpyxl (MIT)
- pytesseract (Apache 2.0)
