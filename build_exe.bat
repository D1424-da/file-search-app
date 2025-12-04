@echo off
chcp 65001 > nul
echo ==========================================
echo ファイル検索アプリ - EXE ビルドツール
echo ==========================================
echo.

echo [1/3] 既存のビルドファイルをクリーンアップ中...
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"
echo クリーンアップ完了
echo.

echo [2/3] PyInstallerでEXEファイルをビルド中...
echo この処理には数分かかる場合があります...
echo.
call .venv\Scripts\activate.bat
pyinstaller file_search_app.spec --clean
echo.

if exist "dist\ファイル検索アプリ.exe" (
    echo [3/3] ビルド成功！
    echo.
    echo ==========================================
    echo EXEファイルが作成されました:
    echo dist\ファイル検索アプリ.exe
    echo ==========================================
    echo.
    echo 注意事項:
    echo - 初回起動時、ウイルス対策ソフトに警告される場合があります
    echo - Tesseract-OCRは別途インストールが必要です
    echo - configフォルダとdata_storageフォルダは実行ファイルと同じ場所に配置してください
    echo.
) else (
    echo [3/3] ビルド失敗
    echo エラーが発生しました。上記のメッセージを確認してください。
    echo.
)

pause
