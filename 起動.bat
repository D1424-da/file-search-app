@echo off
chcp 65001 >nul
REM Ultra Fast 100% Compliant Search App - 起動スクリプト
echo 🚀 Ultra Fast 100%% Compliant Search App 起動中...

REM カレントディレクトリをスクリプトの場所に設定
cd /d "%~dp0"

REM 必要ライブラリの自動インストール
echo 📦 必要ライブラリをチェック中...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

if %ERRORLEVEL% neq 0 (
    echo ⚠️ ライブラリのインストールでエラーが発生しました。インターネット接続を確認してください。
    pause
    exit /b 1
)

echo ✅ ライブラリチェック完了
echo.

REM Pythonでアプリケーションを起動
python file_search_app.py

REM エラーが発生した場合の対処
if %ERRORLEVEL% neq 0 (
    echo.
    echo ❌ アプリケーションの起動に失敗しました
    echo エラーコード: %ERRORLEVEL%
    echo.
    echo 💡 解決方法:
    echo 1. Python 3.7以上がインストールされているか確認してください
    echo 2. 必要なライブラリが不足している場合は自動インストールされます
    echo 3. インターネット接続を確認してください（初回起動時）
    echo.
    pause
) else (
    echo ✅ アプリケーションが正常に終了しました
)
