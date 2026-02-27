# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('assets\\server_icon.ico', 'assets'), ('assets\\platform-tools\\adb.exe', 'assets\\platform-tools'), ('assets\\platform-tools\\AdbWinApi.dll', 'assets\\platform-tools'), ('assets\\platform-tools\\AdbWinUsbApi.dll', 'assets\\platform-tools'), ('assets\\driver', 'assets\\driver')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SonarLink-Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['assets\\server_icon.ico'],
)
