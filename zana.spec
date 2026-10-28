# PyInstaller spec for Zana (one-folder, windowed).  Build:  tools\build_exe.ps1
# AI models are NOT bundled; see README ("Packaged app").
from PyInstaller.utils.hooks import collect_all

datas = [("assets/zana.ico", "assets")]
binaries = []
hiddenimports = []
# Packages with native libraries / data files that PyInstaller can't discover itself.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "piper", "av", "_sounddevice_data"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["openwakeword", "scipy", "sklearn", "matplotlib", "tkinter", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtPdf", "PySide6.QtCharts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Zana",
    console=False,
    icon="assets/zana.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Zana")
