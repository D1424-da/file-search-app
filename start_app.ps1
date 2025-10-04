# Ultra Fast 100% Compliant Search App - PowerShell起動スクリプト

# 文字エンコーディングを設定
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "🚀 Ultra Fast 100% Compliant Search App 起動中..." -ForegroundColor Green

# カレントディレクトリをスクリプトの場所に設定
Set-Location -Path $PSScriptRoot

# Pythonバージョンチェック
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python検出: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Pythonが見つかりません" -ForegroundColor Red
    Write-Host "Python 3.7以上をインストールしてください" -ForegroundColor Yellow
    Read-Host "何かキーを押してください"
    exit 1
}

# tkinter動作確認
try {
    python -c "import tkinter" 2>$null
    Write-Host "✅ tkinter利用可能" -ForegroundColor Green
} catch {
    Write-Host "⚠️ tkinterが利用できない可能性があります" -ForegroundColor Yellow
}

# アプリケーション起動
Write-Host "🎯 アプリケーションを起動します..." -ForegroundColor Cyan

try {
    python "file_search_app.py"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ アプリケーションが正常に終了しました" -ForegroundColor Green
    } else {
        Write-Host "❌ アプリケーションがエラーで終了しました (終了コード: $LASTEXITCODE)" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ アプリケーションの起動に失敗しました: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "" 
    Write-Host "解決方法:" -ForegroundColor Yellow
    Write-Host "1. Python 3.7以上がインストールされているか確認" -ForegroundColor White
    Write-Host "2. tkinterが利用可能か確認" -ForegroundColor White
    Write-Host "3. ファイルの権限を確認" -ForegroundColor White
}

Write-Host ""
Write-Host "デバッグ情報:" -ForegroundColor Cyan
Write-Host "- ログファイル: ultra_fast_app_debug.log" -ForegroundColor White
Write-Host "- 設定ファイル: config/user_settings.json" -ForegroundColor White

Read-Host "何かキーを押してください"
