# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# Добавляем текуую директорию
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('.env', '.'),
        ('config.py', '.'),
        ('database.py', '.'),
        ('vk_bot/main.py', 'vk_bot'),
        ('vk_bot/__init__.py', 'vk_bot'),
    ],
    hiddenimports=[
        'uvicorn',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan.auto',
        'fastapi',
        'starlette',
        'jinja2',
        'aiosqlite',
        'vk_api',
        'vk_api.bot_longpoll',
        'web.app',
        'database',
        'config',
        'vk_bot.main',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AntidrugBot',
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
