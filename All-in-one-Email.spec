# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []

# PySide6 is deliberately NOT collect_all'd. PyInstaller ships its own PySide6
# hook, which pulls in exactly the Qt modules the imports reach plus their
# dependencies; running collect_all on top of it made the hook's work redundant
# and landed a second copy of every Qt library in the bundle — 195 MB of
# Qt6WebEngineCore.dll twice over, among the rest.

# dependency_injector is a Cython extension whose submodules are imported
# dynamically, so its hidden imports do have to be collected. Its datas are
# only the .c/.pyx/.pyi sources shipped inside the wheel — build-time files
# with nothing to do at runtime.
_, di_binaries, di_hiddenimports = collect_all('dependency_injector')
binaries += di_binaries
hiddenimports += di_hiddenimports

# SQLAlchemy resolves its dialect from an entry point at runtime, which the
# static analysis cannot follow.
hiddenimports += ['sqlalchemy.dialects.sqlite']

# Qt modules this app never touches. QtQml/QtQuick are absent from the list on
# purpose: QtWebEngine is built on them and breaks without them.
excludes = [
    'tkinter',
    'PySide6.QtDesigner',
    'PySide6.QtUiTools',
    'PySide6.QtTest',
    'PySide6.QtHelp',
    'PySide6.QtSql',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
]


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='All-in-one-Email',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is off for a distributed build: it saves little on a bundle this size
    # and compressed executables are a standing source of antivirus false
    # positives, which is a worse problem than a larger download.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icons/app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='All-in-one-Email',
)
