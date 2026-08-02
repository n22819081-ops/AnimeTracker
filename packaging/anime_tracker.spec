# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root=Path(SPECPATH).parent
datas=[(str(root/'assets'/'anime_tracker.ico'),'assets'),(str(root/'Create-ModernScheduledTask.ps1'),'.')]
for package in ('certifi','winotify'):
    try:datas+=collect_data_files(package)
    except Exception:pass

a=Analysis(
    [str(root/'packaging'/'entrypoint.py')],
    pathex=[str(root/'src')],
    binaries=[],datas=datas,
    hiddenimports=['PySide6.QtNetwork','requests','urllib3','certifi','winotify','sqlite3'],
    hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=['tkinter','pytest','pytestqt','tests','setuptools','pip'],
    noarchive=False,optimize=1,
)
pyz=PYZ(a.pure)
exe=EXE(
    pyz,a.scripts,[],exclude_binaries=True,name='Anime Tracker',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    disable_windowed_traceback=False,
    icon=str(root/'assets'/'anime_tracker.ico'),
    version=str(root/'packaging'/'version_info.txt'),
)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,upx_exclude=[],name='Anime Tracker')
