# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


repo_root = Path(SPECPATH).parent
src_root = repo_root / "pc" / "src"
resources = src_root / "bootloader_upgrade_tool" / "gui" / "resources"

a = Analysis(
    [str(repo_root / "packaging" / "pyinstaller_entry.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[(str(resources), "bootloader_upgrade_tool/gui/resources")],
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
    [],
    exclude_binaries=True,
    name="DSP28377D_Bootloader_Upgrade_Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DSP28377D_Bootloader_Upgrade_Tool",
)
