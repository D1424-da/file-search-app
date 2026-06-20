#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""インデックス対象診断ツール

指定したフォルダ（ローカル/ネットワーク共有のUNCパス）が、
file_search_app.py の一括インデックス処理で実際に「対象になるか」を、
本体と同じ走査ロジック（対象拡張子・除外ディレクトリ判定）で確認する。

使い方（Windows）:
    python check_index_target.py "\\\\server\\share\\folder"
    python check_index_target.py "Z:\\共有\\資料"
    python check_index_target.py            # 引数省略時はカレントディレクトリ

ネットワーク共有がインデックス対象に入っているかを、実際にindexする前に
安全に（DBを変更せずに）確認できる。
"""
import os
import sys
from pathlib import Path

# --- 対象拡張子は extraction の正準定義を import（手書きコピーの乖離を防ぐ）---
#   extraction は GUI/tkinter に依存しない軽量モジュールのため安全に import できる。
from extraction import TARGET_EXTENSIONS

# --- 除外ディレクトリ判定はローカル定義のまま ---
#   本体(file_search_app.py)から import したいが、同モジュールは import 時に
#   tkinter のロードやロガー/OCR初期化など重い副作用を伴う（GUI起動自体は
#   __main__ ガードで防がれるが、tkinter 未導入環境では import 自体が失敗する）。
#   診断ツールを単体で確実に動かすため、ここでは本体と同一内容の skip 定義を
#   ローカルに保持する（SKIP_DIR_NAMES/SKIP_DIR_PREFIXES と完全一致判定）。
SKIP_DIR_NAMES = {'system32', 'windows', 'pagefile', 'temp', 'tmp',
                  '.git', 'node_modules', '__pycache__',
                  'cache', 'log', 'logs', 'backup', 'trash'}
SKIP_DIR_PREFIXES = ('$recycle',)


def matched_skip_keyword(root_path: str):
    """除外対象なら、ヒットした除外名を返す（本体と同じ「構成要素の完全一致」判定）。

    部分一致ではなくパスをディレクトリ単位に分割して完全一致で照合するため、
    catalog/template/blog 等の正当なフォルダを誤除外しない。
    """
    for raw in root_path.replace('\\', '/').split('/'):
        comp = raw.lower()
        if not comp:
            continue
        if comp in SKIP_DIR_NAMES:
            return comp
        if comp.startswith(SKIP_DIR_PREFIXES):
            return comp
    return None


def diagnose(target_path: str) -> int:
    print("=" * 70)
    print(f"📂 診断対象: {target_path}")
    is_unc = target_path.startswith('\\\\') or target_path.startswith('//')
    print(f"   種別: {'ネットワーク共有 (UNCパス)' if is_unc else 'ローカル/ドライブ'}")

    if not os.path.exists(target_path):
        print("❌ パスにアクセスできません（存在しない/権限不足/未接続）")
        print("   → ネットワーク共有の場合は接続・認証・権限を確認してください。")
        return 1

    target_files = []
    excluded_dirs = []  # (パス, ヒットしたキーワード)
    scanned_dirs = 0

    for root, dirs, files in os.walk(target_path):
        # 本体と同じ除外判定（パス全体への部分一致）
        kw = matched_skip_keyword(root)
        if kw:
            excluded_dirs.append((root, kw))
            dirs.clear()  # サブディレクトリも走査しない（本体と同じ挙動）
            continue

        scanned_dirs += 1
        for file in files:
            if Path(file).suffix.lower() in TARGET_EXTENSIONS:
                target_files.append(str(Path(root) / file))

    print("-" * 70)
    print(f"✅ 走査したディレクトリ数 : {scanned_dirs:,}")
    print(f"🚫 除外したディレクトリ数 : {len(excluded_dirs):,}")
    print(f"📄 インデックス対象ファイル: {len(target_files):,} 件")

    if target_files:
        print("\n   対象ファイル例（先頭10件）:")
        for f in target_files[:10]:
            print(f"     - {f}")

    if excluded_dirs:
        print("\n⚠️  以下のディレクトリは除外対象（フォルダ名が除外名と完全一致）のため除外されました。")
        print("    対象に含めたい場合は、フォルダ名(log/logs/tmp/temp/cache/backup/trash 等)を")
        print("    変更するか、本体の SKIP_DIR_NAMES から該当名を外してください。")
        for path, kw in excluded_dirs[:20]:
            print(f"     - [{kw}] {path}")
        if len(excluded_dirs) > 20:
            print(f"     ... 他 {len(excluded_dirs) - 20} 件")

    print("=" * 70)
    if target_files:
        print("結論: このフォルダはインデックス対象に入ります（上記件数が登録されます）。")
        return 0
    else:
        print("結論: 対象ファイルが0件です。除外設定または対象拡張子をご確認ください。")
        return 2


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    sys.exit(diagnose(path))
