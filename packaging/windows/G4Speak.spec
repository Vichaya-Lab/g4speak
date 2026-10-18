# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent.parent

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=[(str(project_root / 'assets'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2',
        'torch', 'scipy', 'matplotlib', 'sympy', 'tensorflow',
        'cv2', 'numba', 'llvmlite',
        'faster_whisper', 'sherpa_onnx', 'keyboard',
        'transformers', 'huggingface_hub', 'anthropic',
        'av', 'ctranslate2', 'mediapipe',
        'llama_cpp', 'IPython', 'pytest', 'notebook', 'jupyter', 'jedi', 'parso',
        'PySide6_WebEngine', 'PySide6_Pdf', 'PySide6_Addons', 'PySide6_Qml',
    ],
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
    name='G4Speak',
    version=str(project_root / 'packaging/windows/version.txt'),
    icon=str(project_root / 'assets/logo.ico'),
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
)
