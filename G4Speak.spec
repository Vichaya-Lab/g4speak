# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

try:
    _llama_binaries, _llama_datas, _llama_hidden = collect_all('llama_cpp')
except Exception:
    _llama_binaries, _llama_datas, _llama_hidden = [], [], []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_llama_binaries,
    datas=_llama_datas + [('assets', 'assets')],
    hiddenimports=_llama_hidden,
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
    icon='assets/logo.ico',
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
