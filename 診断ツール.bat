@echo off
chcp 65001 >nul
REM 診断スクリプト - アプリケーション起動問題の診断

echo.
echo 🔍 Ultra Fast Search App 診断ツール
echo ================================
echo.

REM カレントディレクトリをスクリプトの場所に設定
cd /d "%~dp0"

echo 📋 システム診断を開始します...
echo.

REM 1. Python確認
echo [1/7] Python確認中...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ Python未検出
    echo    💡 Python 3.7以上をインストールしてください
    echo       https://www.python.org/downloads/
) else (
    echo ✅ Python検出成功
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo    %%i
)
echo.

REM 2. ファイル存在確認
echo [2/7] 必要ファイル確認中...
if exist "fulltext_search_app\ultra_fast_100_percent_compliant_app.py" (
    echo ✅ メインアプリケーションファイル: 存在
) else (
    echo ❌ メインアプリケーションファイル: 不足
)

if exist "requirements.txt" (
    echo ✅ 要件ファイル: 存在
) else (
    echo ❌ 要件ファイル: 不足
)

if exist "config" (
    echo ✅ 設定フォルダ: 存在
) else (
    echo ❌ 設定フォルダ: 不足
)
echo.

REM 3. tkinter確認
echo [3/7] GUI環境確認中...
python -c "import tkinter" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ tkinter未利用可能
    echo    💡 Python再インストールが必要かもしれません
) else (
    echo ✅ tkinter利用可能
)
echo.

REM 4. 権限確認
echo [4/7] ファイル権限確認中...
echo test > test_write.tmp 2>nul
if exist test_write.tmp (
    echo ✅ 書き込み権限: OK
    del test_write.tmp >nul 2>&1
) else (
    echo ❌ 書き込み権限: NG
    echo    💡 管理者権限で実行してください
)
echo.

REM 5. ログファイル確認
echo [5/7] ログファイル確認中...
if exist "ultra_fast_app_debug.log" (
    echo ✅ ログファイル: 存在
    for /f %%a in ('dir /b ultra_fast_app_debug.log') do (
        for /f "tokens=1,2" %%b in ('dir /-c ultra_fast_app_debug.log ^| find "%%a"') do (
            echo    最終更新: %%b %%c
        )
    )
    echo.
    echo 📄 最新ログエントリ（最後の5行）:
    echo ------------------------------------
    for /f "skip=1 delims=" %%i in ('powershell -command "Get-Content 'ultra_fast_app_debug.log' | Select-Object -Last 5"') do echo    %%i
    echo ------------------------------------
) else (
    echo ⚠️ ログファイル: 未存在（初回起動前）
)
echo.

REM 6. 設定ファイル確認
echo [6/7] 設定ファイル確認中...
if exist "config\user_settings.json" (
    echo ✅ ユーザー設定: 存在
) else (
    echo ⚠️ ユーザー設定: 未存在（初回起動時に作成されます）
)

if exist "config\default_settings.json" (
    echo ✅ デフォルト設定: 存在
) else (
    echo ❌ デフォルト設定: 不足
)
echo.

REM 7. データベース確認
echo [7/7] データベース確認中...
set db_count=0
for %%f in (fulltext_search_app\complete_search_db_*.db) do (
    set /a db_count+=1
)
if %db_count% gtr 0 (
    echo ✅ データベースファイル: %db_count%個存在
) else (
    echo ⚠️ データベースファイル: 未存在（初回スキャン時に作成されます）
)
echo.

echo ================================
echo 🔍 診断完了
echo.
echo 💡 問題が見つかった場合の対処法:
echo    1. Python未検出 → Python 3.7以上をインストール
echo    2. ファイル不足 → アプリケーションを再ダウンロード
echo    3. tkinter未利用可能 → Python再インストール
echo    4. 書き込み権限NG → 管理者権限で実行
echo    5. その他 → ログファイルを確認
echo.
echo 📞 サポートが必要な場合は、この診断結果をコピーしてお知らせください
echo.
pause
