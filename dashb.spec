# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Dashb.

Build with (from the project root, after building web-app/dist and the LHM helper):

    uv run pyinstaller dashb.spec --noconfirm

Produces a single-file `dist/Dashb.exe`. See README.md for the full build pipeline
(web-app build, LHM helper publish) this spec assumes has already run.
"""

from pathlib import Path

project_root = Path(SPECPATH).resolve()

datas = [
    (str(project_root / "web-app" / "dist"), "web-app/dist"),
    (str(project_root / "dashb" / "assets"), "dashb/assets"),
]

# The LHM helper is Windows-only and optional at build time (e.g. skip it when
# building/testing on a non-Windows machine); lhm.py falls back to no elevated
# sensors if it's absent from the bundle.
helper_publish = (
    project_root
    / "helpers"
    / "lhm-helper"
    / "bin"
    / "Release"
    / "net8.0"
    / "win-x64"
    / "publish"
)
if helper_publish.is_dir():
    datas.append((str(helper_publish), "lhm-helper"))

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Dashb",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / "dashb" / "assets" / "app.ico"),
)
