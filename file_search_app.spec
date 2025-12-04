# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['file_search_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config', 'config'),
        ('modules', 'modules'),
        ('data_storage', 'data_storage'),
        ('cache', 'cache'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.filedialog',
        'tkinter.ttk',
        'PIL',
        'PIL.Image',
        'fitz',
        'docx',
        'openpyxl',
        'pytesseract',
        'xlrd',
        'docx2txt',
        'lxml',
        'chardet',
        'psutil',
        'concurrent.futures',
        'asyncio',
        'sqlite3',
        'hashlib',
        'json',
        'pickle',
        'gzip',
        'mmap',
        'queue',
        're',
        'unicodedata',
        'xml.etree.ElementTree',
        'zipfile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ファイル検索アプリ',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUIアプリなのでコンソールを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # アイコンファイルがあれば指定可能
)
