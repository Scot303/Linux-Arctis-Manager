# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
import subprocess

from PyInstaller.utils.hooks import collect_submodules

sys.path.append('.')

hiddenimports = ['PyQt6', 'PyQt6.sip']
hiddenimports += collect_submodules('arctis_manager.devices')

python_ver_p = subprocess.run('python --version', shell=True, check=True, stdout=subprocess.PIPE)
python_ver = '.'.join(python_ver_p.stdout.decode('utf-8').replace('Python ', '').split('.')[0:2])
# Use the standard system Qt6 plugins path on Arch-based systems
qt_plugins_path = Path('/usr/lib/qt6/plugins')

print(f"Using Qt6 plugins path for spec: {str(qt_plugins_path)}")

a = Analysis(
    ['arctis_manager.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('arctis_manager/images/steelseries_logo.svg', 'arctis_manager/images/'),
        ('arctis_manager/lang/*.json', 'arctis_manager/lang/'),
        (qt_plugins_path.joinpath('platforms'), 'PyQt6/Qt6/plugins/platforms/'), # Keep target dir structure for PyQt
    ],
    hiddenimports=hiddenimports,
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
    name='arctis-manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
