@echo off
chcp 65001 >nul
REM file_search_app- 改良版起動スクリプト
echo.
echo 🚀 file_search_app 起動中...
echo ================================

REM カレントディレクトリをスクリプトの場所に設定
cd /d "%~dp0"

REM Pythonの存在確認
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ Pythonが見つかりません
    echo.
    echo 💡 Python 3.7以上をインストールしてください
    echo    ダウンロード: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Pythonバージョン表示
echo ✅ Python検出成功
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo    バージョン: %%i
echo.

REM 必要ライブラリの自動インストール
echo 📦 必要ライブラリをチェック中...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

if %ERRORLEVEL% neq 0 (
    echo ⚠️ ライブラリのインストールでエラーが発生しました
    echo    インターネット接続を確認してください
    echo.
    pause
    exit /b 1
)

echo ✅ ライブラリチェック完了
echo.

REM tkinterの動作確認
echo 🔍 GUI環境をチェック中...
python -c "import tkinter" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ⚠️ tkinterが利用できません（GUI機能に影響する可能性があります）
) else (
    echo ✅ GUI環境利用可能
)
echo.

REM アプリケーション起動
echo 🎯 アプリケーションを起動します...
echo ================================
echo.

REM Pythonでアプリケーションを起動
python file_search_app.py

REM 終了処理
echo.
echo ================================

REM エラーが発生した場合の対処
if %ERRORLEVEL% neq 0 (
    echo ❌ アプリケーションがエラーで終了しました
    echo    エラーコード: %ERRORLEVEL%
    echo.
    echo 💡 解決方法:
    echo    1. Python 3.7以上がインストールされているか確認
    echo    2. 必要なライブラリが不足している場合は自動インストールされます
    echo    3. インターネット接続を確認（初回起動時）
    echo    4. ログファイルを確認: file_search_app.log
    echo.
    echo 📋 デバッグ情報:
    echo    - 設定ファイル: config/user_settings.json
    echo    - ログファイル: file_search_app.log
    echo.
    pause
) else (
    echo ✅ アプリケーションが正常に終了しました
    echo.
    echo 📋 次回も同じようにこのファイルをダブルクリックして起動してください
    timeout /t 3 /nobreak >nul
)
