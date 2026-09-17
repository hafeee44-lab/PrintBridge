# -*- mode: python ; coding: utf-8 -*-
"""One file, no console, everything inside.

pypdfium2 carries a native library and zeroconf resolves parts of itself at
run time, so both are collected whole rather than left to static analysis.
"""
import os
from PyInstaller.utils.hooks import collect_all

here = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas, binaries, hiddenimports = [], [], []
for package in ("pypdfium2", "pypdfium2_raw", "zeroconf"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

datas += [(os.path.join(here, "web"), "web")]
hiddenimports += ["printbridge.winprint", "printbridge.render",
                  "printbridge.scan", "printbridge.escl", "printbridge.tray"]

a = Analysis(
    [os.path.join(SPECPATH, "app.py")],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "unittest", "pydoc_data", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Print Bridge",
    icon=os.path.join(SPECPATH, "printbridge.ico"),
    console=False,          # it lives in the tray, not in a window
    disable_windowed_traceback=False,
    upx=False,
    strip=False,
    version=os.path.join(SPECPATH, "version.txt")
        if os.path.exists(os.path.join(SPECPATH, "version.txt")) else None,
)
