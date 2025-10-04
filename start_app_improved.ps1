# file_search_app- 改良版PowerShell起動スクリプト

# 文字エンコーディングを設定
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$host.UI.RawUI.OutputEncoding = [System.Text.Encoding]::UTF8

# 色付きメッセージの表示
Write-Host ""
Write-Host "🚀 file_search_app起動中..." -ForegroundColor Green
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# カレントディレクトリをスクリプトの場所に設定
Set-Location -Path $PSScriptRoot

# Pythonバージョンチェック
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python検出成功" -ForegroundColor Green
    Write-Host "   バージョン: $pythonVersion" -ForegroundColor White
    Write-Host ""
} catch {
    Write-Host "❌ Pythonが見つかりません" -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 Python 3.7以上をインストールしてください" -ForegroundColor Yellow
    Write-Host "   ダウンロード: https://www.python.org/downloads/" -ForegroundColor White
    Write-Host ""
    Read-Host "何かキーを押してください"
    exit 1
}

# 必要ライブラリのチェック
Write-Host "📦 必要ライブラリをチェック中..." -ForegroundColor Cyan
try {
    python -m pip install -r requirements.txt --quiet --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ ライブラリチェック完了" -ForegroundColor Green
    } else {
        Write-Host "⚠️ ライブラリのインストールでエラーが発生しました" -ForegroundColor Yellow
        Write-Host "   インターネット接続を確認してください" -ForegroundColor White
    }
} catch {
    Write-Host "⚠️ ライブラリチェックでエラーが発生しました" -ForegroundColor Yellow
}
Write-Host ""

# tkinter動作確認
Write-Host "🔍 GUI環境をチェック中..." -ForegroundColor Cyan
try {
    python -c "import tkinter" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ GUI環境利用可能" -ForegroundColor Green
    } else {
        Write-Host "⚠️ tkinterが利用できない可能性があります" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠️ tkinterの確認でエラーが発生しました" -ForegroundColor Yellow
}
Write-Host ""

# アプリケーション起動
Write-Host "🎯 アプリケーションを起動します..." -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

try {
    python "file_search_app.py"
    
    Write-Host ""
    Write-Host "================================" -ForegroundColor Cyan
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ アプリケーションが正常に終了しました" -ForegroundColor Green
        Write-Host ""
        Write-Host "📋 次回も同じようにこのファイルを右クリック→PowerShellで実行してください" -ForegroundColor White
    } else {
        Write-Host "❌ アプリケーションがエラーで終了しました (終了コード: $LASTEXITCODE)" -ForegroundColor Red
        Write-Host ""
        Write-Host "💡 解決方法:" -ForegroundColor Yellow
        Write-Host "   1. Python 3.7以上がインストールされているか確認" -ForegroundColor White
        Write-Host "   2. 必要なライブラリが不足している場合は自動インストールされます" -ForegroundColor White
        Write-Host "   3. インターネット接続を確認（初回起動時）" -ForegroundColor White
        Write-Host "   4. ログファイルを確認: file_search_app.log" -ForegroundColor White
    }
} catch {
    Write-Host "❌ アプリケーションの起動に失敗しました: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "" 
    Write-Host "💡 解決方法:" -ForegroundColor Yellow
    Write-Host "   1. Python 3.7以上がインストールされているか確認" -ForegroundColor White
    Write-Host "   2. tkinterが利用可能か確認" -ForegroundColor White
    Write-Host "   3. ファイルの権限を確認" -ForegroundColor White
    Write-Host "   4. ウイルス対策ソフトの除外設定を確認" -ForegroundColor White
}

Write-Host ""
Write-Host "📋 デバッグ情報:" -ForegroundColor Cyan
Write-Host "   - ログファイル: file_search_app.log" -ForegroundColor White
Write-Host "   - 設定ファイル: config/user_settings.json" -ForegroundColor White
Write-Host ""

# 終了前の待機
Write-Host "3秒後に自動で閉じます..." -ForegroundColor Gray
Start-Sleep -Seconds 3
